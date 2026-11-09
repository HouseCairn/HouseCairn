"""API of QR labels: parity with the screens, scopes, roles, isolation (docs/adr/0047)."""

import re
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.labels import services
from housecairn.labels.models import Label, new_code
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = pytest.mark.django_db


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-label-{name}", kwargs={"home_id": home.id, **kwargs})


def resolve(code: str) -> str:
    return reverse("api-v1:label-resolve", kwargs={"code": code})


@pytest.fixture
def client_of_alice(api_client: APIClient, alice: User) -> APIClient:
    api_client.force_authenticate(alice)
    return api_client


@pytest.fixture
def label(alice: User, alice_home: Home, owner_item: Item) -> Label:
    return services.create_label(alice, alice_home, kind="item", target_id=owner_item.id)[0]


def client_of(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


class TestLabels:
    def test_making_one_returns_201_then_the_same_one_with_200(
        self, client_of_alice: APIClient, alice_home: Home, owner_room: Room
    ) -> None:
        body = {"kind": "room", "target": str(owner_room.id)}
        first = client_of_alice.post(api("list", alice_home), body, format="json")
        again = client_of_alice.post(api("list", alice_home), body, format="json")
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json() == again.json()
        data = first.json()
        assert (data["kind"], data["target"], data["name"], data["place"]) == (
            "room",
            str(owner_room.id),
            "Living room",
            "",
        )
        assert data["url"] == f"http://testserver/l/{data['code']}/"
        assert re.fullmatch(r"[A-Za-z0-9_-]{22}", data["code"])

    def test_list_filter_and_detail(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        label: Label,
        owner_room: Room,
        alice: User,
    ) -> None:
        services.create_label(alice, alice_home, kind="room", target_id=owner_room.id)
        everything = client_of_alice.get(api("list", alice_home)).json()["results"]
        assert {row["kind"] for row in everything} == {"item", "room"}
        only = client_of_alice.get(api("list", alice_home), {"kind": "item"}).json()["results"]
        assert [row["id"] for row in only] == [str(label.id)]
        detail = client_of_alice.get(api("detail", alice_home, label_id=label.id))
        assert detail.status_code == 200
        assert detail.json()["code"] == label.code

    def test_a_bad_target_is_a_validation_error(
        self, client_of_alice: APIClient, alice_home: Home, foreign_item: Item
    ) -> None:
        for body in (
            {"kind": "item", "target": str(foreign_item.id)},
            {"kind": "item", "target": str(uuid.uuid4())},
            {"kind": "widget", "target": str(uuid.uuid4())},
            {"kind": "item"},
            {},
        ):
            response = client_of_alice.post(api("list", alice_home), body, format="json")
            assert response.status_code == 400, body
        assert Label.objects.count() == 0

    def test_revoking_and_regenerating(
        self, client_of_alice: APIClient, alice_home: Home, label: Label
    ) -> None:
        fresh = client_of_alice.post(api("regenerate", alice_home, label_id=label.id))
        assert fresh.status_code == 201
        assert fresh.json()["code"] != label.code
        assert client_of_alice.get(resolve(label.code)).status_code == 404
        assert client_of_alice.get(resolve(fresh.json()["code"])).status_code == 200
        gone = client_of_alice.delete(api("detail", alice_home, label_id=fresh.json()["id"]))
        assert gone.status_code == 204
        assert client_of_alice.get(resolve(fresh.json()["code"])).status_code == 404
        assert client_of_alice.get(api("list", alice_home)).json()["results"] == []

    def test_resolving_answers_where_a_code_leads(
        self, client_of_alice: APIClient, alice_home: Home, label: Label, owner_item: Item
    ) -> None:
        body = client_of_alice.get(resolve(label.code)).json()
        assert body == {
            "home": str(alice_home.id),
            "kind": "item",
            "target": str(owner_item.id),
        }

    def test_print_gives_a_pdf_of_the_chosen_labels(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        label: Label,
        alice: User,
        owner_room: Room,
    ) -> None:
        other = services.create_label(alice, alice_home, kind="room", target_id=owner_room.id)[0]
        for layout, expected in (("a4-3x8", 2), ("roll-62", 2)):
            response = client_of_alice.post(
                api("print", alice_home),
                {"labels": [str(label.id), str(other.id)], "layout": layout},
                format="json",
            )
            assert response.status_code == 200, response.content
            assert response["Content-Type"] == "application/pdf"
            assert response.content.startswith(b"%PDF-")
            assert len(re.findall(rb"/S /URI", response.content)) == expected
            assert f"http://testserver/l/{label.code}/".encode() in response.content

    def test_print_refuses_what_it_cannot_print(
        self, client_of_alice: APIClient, alice_home: Home, label: Label
    ) -> None:
        for body in (
            {"labels": []},
            {"labels": ["nope"]},
            {"labels": [str(label.id)], "layout": "poster"},
            {"labels": [str(label.id)] * 201},
            {},
        ):
            response = client_of_alice.post(api("print", alice_home), body, format="json")
            assert response.status_code == 400, body
        assert (
            client_of_alice.post(
                api("print", alice_home), {"labels": [str(uuid.uuid4())]}, format="json"
            ).status_code
            == 404
        )

    def test_the_schema_describes_every_operation(self, client_of_alice: APIClient) -> None:
        schema = client_of_alice.get(reverse("api-schema"), {"format": "json"}).json()
        paths = {p for p in schema["paths"] if "/labels/" in p}
        assert "/api/v1/labels/resolve/{code}/" in paths
        assert "/api/v1/homes/{home_id}/labels/print/" in paths
        assert "/api/v1/homes/{home_id}/labels/{label_id}/regenerate/" in paths
        printing = schema["paths"]["/api/v1/homes/{home_id}/labels/print/"]["post"]
        assert "application/pdf" in printing["responses"]["200"]["content"]


class TestRoles:
    def test_a_reader_lists_reads_prints_and_resolves(
        self, alice_home: Home, reader: User, label: Label
    ) -> None:
        client = client_of(reader)
        assert client.get(api("list", alice_home)).json()["results"]
        assert client.get(api("detail", alice_home, label_id=label.id)).status_code == 200
        assert client.get(resolve(label.code)).status_code == 200
        printed = client.post(api("print", alice_home), {"labels": [str(label.id)]}, format="json")
        assert printed.status_code == 200

    def test_a_reader_changes_nothing(
        self, alice_home: Home, reader: User, label: Label, owner_room: Room
    ) -> None:
        client = client_of(reader)
        made = client.post(
            api("list", alice_home), {"kind": "room", "target": str(owner_room.id)}, format="json"
        )
        assert made.status_code == 403
        assert client.post(api("regenerate", alice_home, label_id=label.id)).status_code == 403
        assert client.delete(api("detail", alice_home, label_id=label.id)).status_code == 403
        label.refresh_from_db()
        assert label.revoked_at is None
        assert Label.objects.count() == 1

    def test_a_member_who_writes_makes_and_revokes(
        self, alice_home: Home, member: User, owner_room: Room
    ) -> None:
        client = client_of(member)
        made = client.post(
            api("list", alice_home), {"kind": "room", "target": str(owner_room.id)}, format="json"
        )
        assert made.status_code == 201
        assert (
            client.delete(api("detail", alice_home, label_id=made.json()["id"])).status_code == 204
        )


class TestIsolation:
    def test_another_homes_labels_do_not_exist_for_me(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        bob: User,
        bob_home: Home,
        foreign_item: Item,
    ) -> None:
        theirs = services.create_label(bob, bob_home, kind="item", target_id=foreign_item.id)[0]
        assert client_of_alice.get(api("list", bob_home)).status_code == 404
        assert client_of_alice.get(api("detail", bob_home, label_id=theirs.id)).status_code == 404
        assert client_of_alice.get(api("detail", alice_home, label_id=theirs.id)).status_code == 404
        assert (
            client_of_alice.delete(api("detail", alice_home, label_id=theirs.id)).status_code == 404
        )
        assert (
            client_of_alice.post(
                api("print", alice_home), {"labels": [str(theirs.id)]}, format="json"
            ).status_code
            == 404
        )
        assert client_of_alice.get(resolve(theirs.code)).status_code == 404
        theirs.refresh_from_db()
        assert theirs.revoked_at is None

    def test_resolving_gives_one_answer_for_unknown_revoked_and_foreign(
        self,
        client_of_alice: APIClient,
        alice: User,
        bob: User,
        bob_home: Home,
        foreign_item: Item,
        alice_home: Home,
        owner_item: Item,
    ) -> None:
        foreign = services.create_label(bob, bob_home, kind="item", target_id=foreign_item.id)[0]
        revoked = services.create_label(alice, alice_home, kind="item", target_id=owner_item.id)[0]
        services.revoke_label(alice, revoked)
        answers = [
            client_of_alice.get(resolve(code))
            for code in (foreign.code, revoked.code, new_code(), "x", "é" * 22)
        ]
        assert {a.status_code for a in answers} == {404}
        assert len({a.content for a in answers}) == 1

    def test_an_instance_administrator_who_is_not_a_member_gets_nothing(
        self, alice_home: Home, site_admin: User, label: Label
    ) -> None:
        client = client_of(site_admin)
        assert client.get(api("list", alice_home)).status_code == 404
        assert client.get(resolve(label.code)).status_code == 404

    def test_anonymous_requests_are_refused(self, alice_home: Home, label: Label) -> None:
        anonymous = APIClient()
        for method, address in (
            ("get", api("list", alice_home)),
            ("get", api("detail", alice_home, label_id=label.id)),
            ("post", api("print", alice_home)),
            ("get", resolve(label.code)),
        ):
            assert getattr(anonymous, method)(address).status_code in (401, 403), address

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
        self, token: Callable[..., APIClient], alice_home: Home, label: Label, owner_room: Room
    ) -> None:
        reading = token(["read"])
        assert reading.get(api("list", alice_home)).status_code == 200
        assert reading.get(resolve(label.code)).status_code == 200
        assert reading.delete(api("detail", alice_home, label_id=label.id)).status_code == 403
        writing = token(["write"])
        made = writing.post(
            api("list", alice_home), {"kind": "room", "target": str(owner_room.id)}, format="json"
        )
        assert made.status_code == 201
        assert writing.get(api("list", alice_home)).status_code == 403
        assert token(["events"]).get(api("list", alice_home)).status_code == 403

    def test_a_token_bound_to_another_home_resolves_nothing(
        self, token: Callable[..., APIClient], alice: User, alice_home: Home, label: Label
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        client = token(["read", "write"], [second])
        assert client.get(resolve(label.code)).status_code == 404
        assert client.get(api("list", alice_home)).status_code == 404
        assert client.get(api("list", second)).status_code == 200

    def test_a_label_in_the_list_of_another_kind_is_not_confused(
        self, client_of_alice: APIClient, alice_home: Home, label: Label, article: Article
    ) -> None:
        made = client_of_alice.post(
            api("list", alice_home), {"kind": "item", "target": str(article.id)}, format="json"
        )
        assert made.status_code == 400
