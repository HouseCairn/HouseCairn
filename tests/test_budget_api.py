"""API of the budget: the figures of the screens, amounts as strings, scopes, isolation."""

import csv
import io
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.projects import services as project_services
from housecairn.projects.models import BudgetLine, Project
from housecairn.rooms.models import Room
from tests.test_budget import TODAY, finish, make_task, pin

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = pytest.mark.django_db

D = Decimal
VIEWS = ("", "rooms", "projects", "tasks")


def address(view: str, home: Home) -> str:
    name = "home-budget" + (f"-{view}" if view else "")
    return reverse(f"api-v1:{name}", kwargs={"home_id": home.id})


@pytest.fixture
def client_of_alice(api_client: APIClient, alice: User) -> APIClient:
    api_client.force_authenticate(alice)
    return api_client


@pytest.fixture
def painted(
    alice: User,
    alice_home: Home,
    owner_room: Room,
    living_room_project: Project,
    labour_line: BudgetLine,
) -> Project:
    pin(living_room_project)
    project_services.update_project(alice, living_room_project, rooms=[owner_room])
    offer = project_services.create_quote(alice, living_room_project, amount=D("970"))
    project_services.accept_quote(alice, offer, labour_line)
    project_services.set_envelope(alice, alice_home, year=2026, amount=D("1500"))
    task = make_task(alice, alice_home, "Wash", room=owner_room, labour_budget=D("50"))
    finish(alice, task, on=TODAY, cost="80")
    return living_room_project


class TestFigures:
    def test_amounts_are_strings_with_two_decimals_and_the_gap_is_signed(
        self, client_of_alice: APIClient, alice_home: Home, painted: Project
    ) -> None:
        body = client_of_alice.get(address("projects", alice_home)).json()
        line = body["lines"][0]
        assert line["name"] == "Paint the living room"
        assert line["counted_in"] == 2026
        assert line["amounts"] == {
            "planned": "800.00",
            "committed": "970.00",
            "paid": "0.00",
            "engaged": "970.00",
            "gap": "-170.00",
            "to_pay": "970.00",
            "budget_state": "over",
        }
        assert body["currency"] == "EUR"
        assert body["total"]["gap"] == "-170.00"

    def test_by_room_by_task_and_the_overview(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room, painted: Project
    ) -> None:
        rooms = client_of_alice.get(address("rooms", alice_home) + "?year=2026").json()
        assert [(line["id"], line["name"]) for line in rooms["lines"]] == [
            (str(owner_room.id), "Living room")
        ]
        assert rooms["lines"][0]["projects"]["engaged"] == "970.00"
        assert rooms["lines"][0]["upkeep"]["paid"] == "80.00"
        tasks = client_of_alice.get(address("tasks", alice_home) + "?year=2026").json()
        assert tasks["lines"][0]["estimate"] == "50.00"
        assert tasks["lines"][0]["annual_cost"] is None
        assert tasks["lines"][0]["total_paid"] == "80.00"
        assert tasks["unlisted"] == 0
        overview = client_of_alice.get(address("", alice_home) + "?year=2026").json()
        assert overview["envelope"]["envelope"] == "1500.00"
        assert overview["envelope"]["left_to_spend"] == "450.00"
        assert overview["envelope"]["sure_budget"] is None
        assert {n["nature"] for n in overview["by_nature"]} == {
            "material",
            "labour",
            "rental",
            "other",
        }
        assert overview["rolling"]["upkeep"]["paid"] == "80.00"
        assert overview["years"][0] >= 2026

    def test_a_year_that_is_not_one_is_refused(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        for raw in ("abc", "12", "9999"):
            assert (
                client_of_alice.get(address("rooms", alice_home) + f"?year={raw}").status_code
                == 400
            )

    def test_every_view_has_its_file(
        self, client_of_alice: APIClient, alice_home: Home, painted: Project
    ) -> None:
        for view in VIEWS:
            response = client_of_alice.get(address(view, alice_home) + "?year=2026&export=csv")
            assert response.status_code == 200, view
            assert response["Content-Type"].startswith("text/csv")
            rows = list(csv.reader(io.StringIO(response.content.decode())))
            assert len(rows) >= 2, view

    def test_the_schema_describes_every_route_with_amounts_as_strings(
        self, client_of_alice: APIClient
    ) -> None:
        schema = client_of_alice.get(reverse("api-schema") + "?format=json").json()
        for path in (
            "/api/v1/budget/",
            "/api/v1/homes/{home_id}/budget/",
            "/api/v1/homes/{home_id}/budget/rooms/",
            "/api/v1/homes/{home_id}/budget/projects/",
            "/api/v1/homes/{home_id}/budget/tasks/",
        ):
            assert path in schema["paths"], path
            assert set(schema["paths"][path]) == {"get"}, path  # figures only: nothing to write
        amounts = schema["components"]["schemas"]["Amounts"]["properties"]
        assert amounts["planned"]["type"] == "string"
        assert amounts["gap"]["format"] == "decimal"


class TestSeveralHomes:
    def test_the_combined_view_adds_by_currency_and_names_each_home(
        self, client_of_alice: APIClient, alice: User, alice_home: Home
    ) -> None:
        chalet = home_services.create_home(alice, name="Chalet", currency="CHF")
        flat = home_services.create_home(alice, name="Flat")
        for home, amount in ((alice_home, "100"), (chalet, "70"), (flat, "5")):
            project_services.create_project(alice, home, title="Work", budget=D(amount))
        body = client_of_alice.get(reverse("api-v1:budget-combined")).json()
        assert [entry["currency"] for entry in body] == ["CHF", "EUR"]
        eur = body[1]
        assert eur["total"]["planned"] == "105.00"
        assert [h["name"] for h in eur["homes"]] == ["Flat", "Main house"]

    def test_a_token_bound_to_one_home_adds_up_that_home_only(
        self, alice: User, alice_home: Home
    ) -> None:
        other = home_services.create_home(alice, name="Chalet", currency="CHF")
        project_services.create_project(alice, other, title="Work", budget=D("70"))
        _token, raw = token_services.issue_token(
            alice, name="t", scopes=["read"], homes=[alice_home], lifetime=timedelta(days=1)
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        body = client.get(reverse("api-v1:budget-combined")).json()
        assert [entry["currency"] for entry in body] == ["EUR"]
        assert [home["name"] for home in body[0]["homes"]] == ["Main house"]
        assert client.get(address("rooms", other)).status_code == 404


class TestAccess:
    @pytest.fixture
    def token(self, alice: User, alice_home: Home) -> Callable[..., APIClient]:
        def make(scopes: list[str], homes: list[Home] | None = None) -> APIClient:
            _token, raw = token_services.issue_token(
                alice,
                name="t",
                scopes=scopes,
                homes=homes or [alice_home],
                lifetime=timedelta(days=1),
            )
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
            return client

        return make

    def test_scopes_of_a_token(self, token: Callable[..., APIClient], alice_home: Home) -> None:
        for view in VIEWS:
            assert token(["read"]).get(address(view, alice_home)).status_code == 200
            assert token(["write"]).get(address(view, alice_home)).status_code == 403
            assert token(["events"]).get(address(view, alice_home)).status_code == 403
            # Figures only: no method changes anything.
            for method in ("post", "put", "patch", "delete"):
                response = getattr(token(["read", "write"]), method)(
                    address(view, alice_home), {}, format="json"
                )
                assert response.status_code == 405, (view, method)

    def test_a_token_of_another_home_sees_nothing(
        self, token: Callable[..., APIClient], alice: User, alice_home: Home
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        client = token(["read"], [second])
        for view in VIEWS:
            assert client.get(address(view, alice_home)).status_code == 404, view
            assert client.get(address(view, second)).status_code == 200, view

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_another_person_and_the_instance_administrator_see_nothing(
        self,
        request: pytest.FixtureRequest,
        api_client: APIClient,
        who: str,
        alice_home: Home,
        painted: Project,
    ) -> None:
        api_client.force_authenticate(request.getfixturevalue(who))
        for view in VIEWS:
            assert api_client.get(address(view, alice_home)).status_code == 404, view
            assert api_client.get(address(view, alice_home) + "?export=csv").status_code == 404, (
                view
            )

    def test_a_reader_reads(self, api_client: APIClient, reader: User, alice_home: Home) -> None:
        api_client.force_authenticate(reader)
        for view in VIEWS:
            assert api_client.get(address(view, alice_home)).status_code == 200

    def test_anonymous_requests_are_refused(self, alice_home: Home) -> None:
        for view in VIEWS:
            assert APIClient().get(address(view, alice_home)).status_code in {401, 403}
        assert APIClient().get(reverse("api-v1:budget-combined")).status_code in {401, 403}
