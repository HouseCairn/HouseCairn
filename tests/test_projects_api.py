"""API of projects: parity with the screens, amounts, scopes, roles, isolation (docs/adr/0050)."""

import uuid
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
from housecairn.projects import services
from housecairn.projects.models import BudgetLine, Project, ProjectFile, ProjectTask, Quote
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Task
from tests.rooms_support import image_bytes, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def client_of_alice(api_client: APIClient, alice: User) -> APIClient:
    api_client.force_authenticate(alice)
    return api_client


class TestProjectGap:
    def test_the_gap_of_a_project_is_the_sum_of_the_gaps_of_its_lines(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
    ) -> None:
        paint = BudgetLine.objects.get(project=living_room_project, label="Paint")
        services.update_line(alice, paint, paid=Decimal("350"))
        painter = services.create_quote(alice, living_room_project, amount=Decimal("540.50"))
        services.accept_quote(alice, painter, labour_line)
        detail = client_of_alice.get(
            api("project-detail", alice_home, project_id=living_room_project.id)
        ).json()
        assert (detail["planned"], detail["committed"], detail["paid"]) == (
            "800.00",
            "540.50",
            "350.00",
        )
        assert (detail["gap"], detail["budget_state"]) == ("-90.50", "over")
        listed = client_of_alice.get(api("project-list", alice_home)).json()["results"]
        assert [(p["gap"], p["budget_state"]) for p in listed] == [("-90.50", "over")]
        lines = client_of_alice.get(
            api("budget-line-list", alice_home), {"project": str(living_room_project.id)}
        ).json()["results"]
        assert sorted(line["gap"] for line in lines) == ["-40.50", "-50.00"]


class TestProjects:
    def test_crud_with_amounts_as_exact_strings(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        created = client_of_alice.post(
            api("project-list", alice_home),
            {"title": "Redo the bathroom", "priority": "high", "budget": "5000"},
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert (body["planned"], body["committed"], body["paid"], body["gap"]) == (
            "5000.00",
            "0.00",
            "0.00",
            "5000.00",
        )
        assert (body["status"], body["budget_state"], body["season_months"]) == (
            "idea",
            "under",
            None,
        )
        assert "budget" not in body
        detail = api("project-detail", alice_home, project_id=body["id"])
        patched = client_of_alice.patch(
            detail, {"status": "in_progress", "season": "winter", "estimated_minutes": 2880}
        )
        assert patched.status_code == 200, patched.content
        assert patched.json()["season_months"] == [12, 2]
        refused = client_of_alice.patch(detail, {"budget": "1"})
        assert refused.status_code == 400
        listed = client_of_alice.get(api("project-list", alice_home), {"status": "in_progress"})
        assert [p["title"] for p in listed.json()["results"]] == ["Redo the bathroom"]
        assert (
            client_of_alice.get(api("project-list", alice_home), {"status": "done"}).json()[
                "results"
            ]
            == []
        )
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404

    def test_the_list_gives_the_amounts_of_each_project_without_a_query_each(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        django_assert_max_num_queries: Callable[..., object],
    ) -> None:
        for number in range(6):
            services.create_project(alice, alice_home, title=f"P{number}", budget=Decimal("10"))
        with django_assert_max_num_queries(20):
            response = client_of_alice.get(api("project-list", alice_home))
        assert [p["planned"] for p in response.json()["results"]] == ["10.00"] * 6

    def test_a_title_is_required_and_errors_name_the_field(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        response = client_of_alice.post(api("project-list", alice_home), {"title": ""})
        assert response.status_code == 400
        assert "title" in response.json()
        response = client_of_alice.post(
            api("project-list", alice_home), {"title": "T", "budget": "10000000000"}
        )
        assert response.status_code == 400
        assert "budget" in response.json()
        response = client_of_alice.post(
            api("project-list", alice_home), {"title": "T", "season": "custom"}
        )
        assert response.status_code == 400

    def test_rooms_are_the_rooms_of_the_home(
        self,
        client_of_alice: APIClient,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        owner_room: object,
    ) -> None:
        from housecairn.rooms import services as room_services

        foreign = room_services.create_room(bob, bob_home, name="Hall")
        response = client_of_alice.post(
            api("project-list", alice_home), {"title": "T", "rooms": [str(foreign.id)]}
        )
        assert response.status_code == 400


class TestLinesAndQuotes:
    def test_the_living_room_scenario_through_the_api(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        project = client_of_alice.post(api("project-list", alice_home), {"title": "Paint"}).json()
        paint = client_of_alice.post(
            api("budget-line-list", alice_home),
            {"project": project["id"], "label": "Paint", "nature": "material", "planned": "300"},
        ).json()
        labour = client_of_alice.post(
            api("budget-line-list", alice_home),
            {"project": project["id"], "label": "Painter", "nature": "labour", "planned": "500"},
        ).json()
        assert (paint["committed"], labour["gap"]) == ("0.00", "500.00")
        first = client_of_alice.post(
            api("quote-list", alice_home),
            {
                "project": project["id"],
                "contractor_name": "Painter A",
                "amount": "620.00",
                "status": "received",
            },
        )
        second = client_of_alice.post(
            api("quote-list", alice_home),
            {"project": project["id"], "contractor_name": "painter a", "amount": "780"},
        )
        assert first.status_code == 201, first.content
        assert second.status_code == 201, second.content
        assert first.json()["contractor"] == second.json()["contractor"]  # found, not duplicated
        accepted = client_of_alice.post(
            api("quote-accept", alice_home, quote_id=first.json()["id"]),
            {"budget_line": labour["id"]},
        )
        assert accepted.status_code == 200, accepted.content
        assert (accepted.json()["status"], accepted.json()["budget_line"]) == (
            "accepted",
            labour["id"],
        )
        spent = client_of_alice.patch(
            api("budget-line-detail", alice_home, line_id=labour["id"]), {"paid": "120"}
        )
        assert (spent.json()["committed"], spent.json()["paid"], spent.json()["gap"]) == (
            "620.00",
            "120.00",
            "-120.00",
        )
        assert spent.json()["budget_state"] == "over"
        total = client_of_alice.get(
            api("project-detail", alice_home, project_id=project["id"])
        ).json()
        assert (total["planned"], total["committed"], total["paid"], total["gap"]) == (
            "800.00",
            "620.00",
            "120.00",
            "180.00",
        )
        assert total["budget_state"] == "under"
        lines = client_of_alice.get(api("budget-line-list", alice_home), {"project": project["id"]})
        assert sorted(line["committed"] for line in lines.json()["results"]) == ["0.00", "620.00"]
        rejected = client_of_alice.patch(
            api("quote-detail", alice_home, quote_id=first.json()["id"]), {"status": "rejected"}
        )
        assert (rejected.json()["status"], rejected.json()["budget_line"]) == ("rejected", None)

    def test_accepting_asks_for_a_line_of_the_home(
        self, client_of_alice: APIClient, alice_home: Home, quote: Quote, foreign_project: Project
    ) -> None:
        address = api("quote-accept", alice_home, quote_id=quote.id)
        for body in (
            {},
            {"budget_line": "nope"},
            {"budget_line": str(uuid.uuid4())},
            {"budget_line": str(foreign_project.lines.get().id)},
        ):
            assert client_of_alice.post(address, body).status_code == 400, body
        quote.refresh_from_db()
        assert quote.status == "received"

    def test_a_quote_names_its_contractor_once(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        response = client_of_alice.post(
            api("quote-list", alice_home),
            {
                "project": str(living_room_project.id),
                "contractor_name": "X",
                "contractor": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 400

    def test_amounts_out_of_range_are_refused(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        for bad in ("10000000000", "-1", "1.234", "NaN", "abc", 1e30):
            for resource, extra in (
                ("budget-line-list", {"label": "L", "planned": bad}),
                ("quote-list", {"amount": bad}),
            ):
                response = client_of_alice.post(
                    api(resource, alice_home),
                    {"project": str(living_room_project.id), **extra},
                    format="json",
                )
                assert response.status_code == 400, (resource, bad, response.content)
        ok = client_of_alice.post(
            api("budget-line-list", alice_home),
            {"project": str(living_room_project.id), "label": "L", "planned": "9999999999.99"},
        )
        assert ok.status_code == 201
        assert ok.json()["planned"] == "9999999999.99"

    def test_a_line_or_a_quote_cannot_change_project(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        alice: User,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        other = services.create_project(alice, alice_home, title="Other")
        for name, key, pk in (
            ("budget-line-detail", "line_id", labour_line.id),
            ("quote-detail", "quote_id", quote.id),
        ):
            response = client_of_alice.patch(
                api(name, alice_home, **{key: pk}), {"project": str(other.id)}
            )
            assert response.status_code == 400, name

    def test_the_paperless_slot_is_in_the_api(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        response = client_of_alice.post(
            api("quote-list", alice_home),
            {
                "project": str(living_room_project.id),
                "paperless_id": 7,
                "paperless_url": "https://paperless.example.com/documents/7/",
            },
        )
        assert response.status_code == 201
        assert response.json()["paperless_id"] == 7
        bad = client_of_alice.post(
            api("quote-list", alice_home),
            {"project": str(living_room_project.id), "paperless_url": "ftp://x.example.com/a"},
        )
        assert bad.status_code == 400

    def test_deleting_a_line_and_a_quote(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        alice: User,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        assert (
            client_of_alice.delete(
                api("budget-line-detail", alice_home, line_id=labour_line.id)
            ).status_code
            == 204
        )
        assert (
            client_of_alice.get(api("quote-detail", alice_home, quote_id=quote.id)).json()["status"]
            == "received"
        )
        assert (
            client_of_alice.delete(api("quote-detail", alice_home, quote_id=quote.id)).status_code
            == 204
        )
        assert not Quote.objects.filter(id=quote.id).exists()


class TestTasksOfAProject:
    def test_three_tasks_created_from_the_project_and_one_put_in(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
    ) -> None:
        for title in ("A", "B", "C"):
            response = client_of_alice.post(
                api("project-task-list", alice_home),
                {"project": str(living_room_project.id), "title": title, "due_on": "2027-01-15"},
            )
            assert response.status_code == 201, response.content
        listed = client_of_alice.get(
            api("project-task-list", alice_home), {"project": str(living_room_project.id)}
        ).json()["results"]
        assert len(listed) == 3
        assert {t.title for t in Task.objects.filter(home=alice_home)} == {"A", "B", "C"}
        free = task_services.create_task(alice, alice_home, title="Free")
        put = client_of_alice.post(
            api("project-task-list", alice_home),
            {"project": str(living_room_project.id), "task": str(free.id)},
        )
        assert put.status_code == 201
        twice = client_of_alice.post(
            api("project-task-list", alice_home),
            {"project": str(living_room_project.id), "task": str(free.id)},
        )
        assert twice.status_code == 400
        out = client_of_alice.delete(
            api("project-task-detail", alice_home, link_id=put.json()["id"])
        )
        assert out.status_code == 204
        assert Task.objects.filter(id=free.id).exists()

    def test_either_a_task_or_a_title(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        for body in ({}, {"title": "x", "task": str(uuid.uuid4())}):
            response = client_of_alice.post(
                api("project-task-list", alice_home),
                {"project": str(living_room_project.id), **body},
            )
            assert response.status_code == 400

    def test_a_task_of_another_home_cannot_be_put_in(
        self,
        client_of_alice: APIClient,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        living_room_project: Project,
    ) -> None:
        foreign = task_services.create_task(bob, bob_home, title="Theirs")
        response = client_of_alice.post(
            api("project-task-list", alice_home),
            {"project": str(living_room_project.id), "task": str(foreign.id)},
        )
        assert response.status_code == 400
        assert not ProjectTask.objects.exists()


class TestFiles:
    def test_photos_and_quote_files_over_multipart(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        living_room_project: Project,
        quote: Quote,
    ) -> None:
        photo = client_of_alice.post(
            api("project-file-list", alice_home),
            {
                "project": str(living_room_project.id),
                "file": upload(image_bytes(gps=True), "wall.jpg"),
            },
            format="multipart",
        )
        assert photo.status_code == 201, photo.content
        body = photo.json()
        assert (body["is_image"], body["name"], body["quote"]) == (True, "wall.jpg", None)
        content = client_of_alice.get(api("project-file-content", alice_home, file_id=body["id"]))
        assert content["Content-Type"] == "image/jpeg"
        assert b"Exif" not in b"".join(content.streaming_content)
        assert (
            client_of_alice.get(
                api("project-file-thumbnail", alice_home, file_id=body["id"])
            ).status_code
            == 200
        )
        document = client_of_alice.post(
            api("project-file-list", alice_home),
            {
                "project": str(living_room_project.id),
                "quote": str(quote.id),
                "file": upload(PDF, "q.pdf"),
            },
            format="multipart",
        )
        assert document.status_code == 201
        assert document.json()["thumbnail_url"] is None
        refused = client_of_alice.post(
            api("project-file-list", alice_home),
            {"project": str(living_room_project.id), "file": upload(PDF, "q.pdf")},
            format="multipart",
        )
        assert refused.status_code == 400
        listed = client_of_alice.get(
            api("project-file-list", alice_home), {"project": str(living_room_project.id)}
        )
        assert len(listed.json()["results"]) == 2
        assert (
            client_of_alice.delete(
                api("project-file-detail", alice_home, file_id=body["id"])
            ).status_code
            == 204
        )
        assert ProjectFile.objects.count() == 1

    def test_an_oversized_body_is_refused_before_it_is_read(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        response = client_of_alice.post(
            api("project-file-list", alice_home),
            {"project": str(living_room_project.id), "file": upload(image_bytes())},
            format="multipart",
            CONTENT_LENGTH=str(10**9),
        )
        assert response.status_code == 413


class TestEnvelope:
    def test_read_and_set_the_envelope_of_a_year(
        self, client_of_alice: APIClient, alice_home: Home, living_room_project: Project
    ) -> None:
        address = api("envelope", alice_home)
        empty = client_of_alice.get(address, {"year": 2026}).json()
        assert (empty["envelope"], empty["left"], empty["planned"]) == (None, None, "800.00")
        put = client_of_alice.put(address, {"year": 2026, "amount": "5000.50"})
        assert put.status_code == 200, put.content
        assert (put.json()["envelope"], put.json()["left"]) == ("5000.50", "4200.50")
        for bad in (
            {"year": 1999, "amount": "1"},
            {"year": 2026, "amount": "-1"},
            {"year": "x", "amount": "1"},
            {"amount": "1e40"},
            {},
        ):
            assert client_of_alice.put(address, bad).status_code == 400, bad
        assert client_of_alice.get(address, {"year": "abc"}).status_code == 400
        assert client_of_alice.get(address).status_code == 200  # this year


class TestAccess:
    def endpoints(
        self, home: Home, project: Project, line: BudgetLine, quote: Quote
    ) -> list[tuple[str, str]]:
        return [
            ("get", api("project-list", home)),
            ("get", api("project-detail", home, project_id=project.id)),
            ("get", api("budget-line-list", home)),
            ("get", api("budget-line-detail", home, line_id=line.id)),
            ("get", api("quote-list", home)),
            ("get", api("quote-detail", home, quote_id=quote.id)),
            ("get", api("project-file-list", home)),
            ("get", api("project-task-list", home)),
            ("get", api("envelope", home)),
            ("patch", api("project-detail", home, project_id=project.id)),
            ("delete", api("project-detail", home, project_id=project.id)),
            ("patch", api("budget-line-detail", home, line_id=line.id)),
            ("delete", api("budget-line-detail", home, line_id=line.id)),
            ("patch", api("quote-detail", home, quote_id=quote.id)),
            ("delete", api("quote-detail", home, quote_id=quote.id)),
            ("post", api("quote-accept", home, quote_id=quote.id)),
            ("post", api("project-list", home)),
            ("post", api("budget-line-list", home)),
            ("post", api("quote-list", home)),
            ("post", api("project-file-list", home)),
            ("post", api("project-task-list", home)),
            ("put", api("envelope", home)),
        ]

    def test_a_reader_reads_and_changes_nothing(
        self,
        api_client: APIClient,
        reader: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        api_client.force_authenticate(reader)
        body = {
            "title": "x",
            "project": str(living_room_project.id),
            "label": "x",
            "amount": "1",
            "budget_line": str(labour_line.id),
        }
        for method, address in self.endpoints(alice_home, living_room_project, labour_line, quote):
            if method == "post" and address.endswith("/project-files/"):
                response = api_client.post(
                    address, {**body, "file": upload(image_bytes())}, format="multipart"
                )
            else:
                response = getattr(api_client, method)(address, body, format="json")
            expected = 200 if method == "get" else 403
            assert response.status_code == expected, (method, address, response.status_code)
        assert (Project.objects.count(), Quote.objects.count()) == (1, 1)

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_another_home_and_the_instance_administrator_see_nothing(
        self,
        request: pytest.FixtureRequest,
        api_client: APIClient,
        who: str,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        api_client.force_authenticate(request.getfixturevalue(who))
        for method, address in self.endpoints(alice_home, living_room_project, labour_line, quote):
            assert getattr(api_client, method)(address, {}, format="json").status_code == 404, (
                method,
                address,
            )
        assert (Project.objects.count(), BudgetLine.objects.count(), Quote.objects.count()) == (
            1,
            2,
            1,
        )

    def test_identifiers_of_another_home_do_not_resolve_in_mine(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        living_room_project: Project,
        foreign_project: Project,
    ) -> None:
        line = foreign_project.lines.get()
        theirs = foreign_project.quotes.get()
        assert (
            client_of_alice.get(
                api("project-detail", alice_home, project_id=foreign_project.id)
            ).status_code
            == 404
        )
        assert (
            client_of_alice.get(api("budget-line-detail", alice_home, line_id=line.id)).status_code
            == 404
        )
        assert (
            client_of_alice.delete(api("quote-detail", alice_home, quote_id=theirs.id)).status_code
            == 404
        )
        for resource, field in (
            ("budget-line-list", {"label": "x"}),
            ("quote-list", {"amount": "1"}),
            ("project-task-list", {"title": "x"}),
            ("project-file-list", {}),
        ):
            response = client_of_alice.post(
                api(resource, alice_home),
                {"project": str(foreign_project.id), **field},
                format="json",
            )
            assert response.status_code == 400, resource
        listed = client_of_alice.get(api("project-list", alice_home)).json()["results"]
        assert [p["title"] for p in listed] == ["Paint the living room"]
        assert Project.objects.get(id=foreign_project.id).lines.count() == 1

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

    def test_scopes_of_a_token(
        self, token: Callable[..., APIClient], alice_home: Home, living_room_project: Project
    ) -> None:
        reading = token(["read"])
        assert reading.get(api("project-list", alice_home)).status_code == 200
        assert reading.post(api("project-list", alice_home), {"title": "x"}).status_code == 403
        assert reading.put(api("envelope", alice_home), {"amount": "1"}).status_code == 403
        writing = token(["write"])
        assert writing.post(api("project-list", alice_home), {"title": "x"}).status_code == 201
        assert writing.get(api("project-list", alice_home)).status_code == 403
        events = token(["events"])
        assert events.get(api("project-list", alice_home)).status_code == 403

    def test_a_token_bound_to_another_home_sees_nothing(
        self,
        token: Callable[..., APIClient],
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        client = token(["read", "write"], [second])
        for method, address in self.endpoints(alice_home, living_room_project, labour_line, quote):
            assert getattr(client, method)(address, {}, format="json").status_code == 404, (
                method,
                address,
            )
        assert client.get(api("project-list", second)).status_code == 200
        assert client.post(api("project-list", second), {"title": "Mine"}).status_code == 201
        assert not Project.objects.filter(home=alice_home, title="Mine").exists()

    def test_anonymous_requests_are_refused_and_change_nothing(
        self, alice_home: Home, living_room_project: Project, labour_line: BudgetLine, quote: Quote
    ) -> None:
        anonymous = APIClient()
        for method, address in self.endpoints(alice_home, living_room_project, labour_line, quote):
            assert getattr(anonymous, method)(address, {}, format="json").status_code in {
                401,
                403,
            }, address
        assert Project.objects.get(id=living_room_project.id).title == "Paint the living room"


def test_the_schema_lists_the_project_operations(client_of_alice: APIClient) -> None:
    schema = client_of_alice.get(
        reverse("api-schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json"
    ).json()
    base = "/api/v1/homes/{home_id}"
    for path in (
        f"{base}/projects/",
        f"{base}/projects/{{project_id}}/",
        f"{base}/budget-lines/",
        f"{base}/budget-lines/{{line_id}}/",
        f"{base}/quotes/",
        f"{base}/quotes/{{quote_id}}/",
        f"{base}/quotes/{{quote_id}}/accept/",
        f"{base}/project-files/",
        f"{base}/project-files/{{file_id}}/content/",
        f"{base}/project-files/{{file_id}}/thumbnail/",
        f"{base}/project-tasks/",
        f"{base}/envelope/",
    ):
        assert path in schema["paths"], path
    amount = schema["components"]["schemas"]["Project"]["properties"]["planned"]
    assert amount["type"] == "string"
