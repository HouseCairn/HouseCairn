"""API of stock: parity with the screens, scopes, roles, isolation (docs/adr/0038)."""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.rooms import conf
from housecairn.rooms.models import Item
from housecairn.stock import services
from housecairn.stock.models import Article, Movement, Supplier
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def client_of_alice(api_client: APIClient, alice: User) -> APIClient:
    api_client.force_authenticate(alice)
    return api_client


@pytest.fixture
def supplier(alice: User, article: Article) -> Supplier:
    return services.create_supplier(alice, article, name="Acme", last_price=Decimal("4.2"))


class TestArticles:
    def test_crud_with_quantity_and_compatible_items(
        self, client_of_alice: APIClient, alice_home: Home, owner_item: Item
    ) -> None:
        created = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Anode", "threshold": "1", "compatible_items": [str(owner_item.id)]},
            format="json",
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert (body["quantity"], body["low"], body["compatible_items"]) == (
            "0.00",
            True,
            [str(owner_item.id)],
        )
        assert body["label_url"] is None
        detail = api("article-detail", alice_home, article_id=body["id"])
        movement = client_of_alice.post(
            api("movement-list", alice_home),
            {"article": body["id"], "kind": "entry", "quantity": "3"},
        )
        assert movement.status_code == 201
        assert client_of_alice.get(detail).json()["quantity"] == "3.00"
        assert client_of_alice.get(detail).json()["low"] is False
        patched = client_of_alice.patch(detail, {"name": "Anode 2"}, format="json")
        assert patched.json()["name"] == "Anode 2"
        assert patched.json()["compatible_items"] == [str(owner_item.id)]
        assert (
            client_of_alice.patch(detail, {"compatible_items": []}, format="json").json()[
                "compatible_items"
            ]
            == []
        )
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404

    def test_the_quantity_is_not_writable(
        self, client_of_alice: APIClient, alice_home: Home, article: Article
    ) -> None:
        created = client_of_alice.post(
            api("article-list", alice_home), {"name": "x", "quantity": "99"}, format="json"
        )
        assert created.json()["quantity"] == "0.00"
        detail = api("article-detail", alice_home, article_id=article.id)
        client_of_alice.patch(detail, {"quantity": "99"}, format="json")
        assert client_of_alice.get(detail).json()["quantity"] == "0.00"

    def test_validation_errors_are_reported_by_field(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        assert client_of_alice.post(api("article-list", alice_home), {}).status_code == 400
        response = client_of_alice.post(
            api("article-list", alice_home), {"name": "x", "threshold": "-1"}, format="json"
        )
        assert response.status_code == 400
        assert "threshold" in response.json()

    def test_listing_filters_and_paginates(
        self, client_of_alice: APIClient, alice: User, alice_home: Home, article: Article
    ) -> None:
        services.create_article(alice, alice_home, name="Paint")
        services.create_supplier(alice, article, name="Acme Parts")
        address = api("article-list", alice_home)
        names = [a["name"] for a in client_of_alice.get(address).json()["results"]]
        assert names == ["Boiler filter", "Paint"]
        assert [
            a["name"] for a in client_of_alice.get(address, {"q": "acme"}).json()["results"]
        ] == ["Boiler filter"]
        low = client_of_alice.get(address, {"low": "true"}).json()["results"]
        assert [a["name"] for a in low] == ["Boiler filter"]
        first = client_of_alice.get(address, {"page_size": 1}).json()
        assert [a["name"] for a in first["results"]] == ["Boiler filter"]
        assert [a["name"] for a in client_of_alice.get(first["next"]).json()["results"]] == [
            "Paint"
        ]

    def test_filter_by_compatible_item(
        self, client_of_alice: APIClient, alice_home: Home, article: Article, owner_item: Item
    ) -> None:
        address = api("article-list", alice_home)
        hit = client_of_alice.get(address, {"item": str(owner_item.id)}).json()["results"]
        assert [a["id"] for a in hit] == [str(article.id)]
        assert client_of_alice.get(address, {"item": str(uuid.uuid4())}).json()["results"] == []
        assert client_of_alice.get(address, {"item": "nope"}).status_code == 400

    def test_an_item_of_another_home_is_refused(
        self, client_of_alice: APIClient, alice_home: Home, article: Article, foreign_item: Item
    ) -> None:
        response = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "x", "compatible_items": [str(foreign_item.id)]},
            format="json",
        )
        assert response.status_code == 400
        assert "compatible_items" in response.json()
        detail = api("article-detail", alice_home, article_id=article.id)
        refused = client_of_alice.patch(
            detail, {"compatible_items": [str(foreign_item.id)]}, format="json"
        )
        assert refused.status_code == 400
        assert article.compatible_items.count() == 1


class TestLabelOverTheApi:
    def test_upload_download_and_remove(
        self, client_of_alice: APIClient, alice_home: Home, media_root: Path
    ) -> None:
        created = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tin", "label": upload(image_bytes("PNG", gps=True), "x.png", "image/png")},
            format="multipart",
        )
        assert created.status_code == 201, created.content
        body = created.json()
        assert body["label_url"]
        assert "label" not in body
        content = client_of_alice.get(body["label_url"])
        assert content.status_code == 200
        assert content["Content-Type"] == "image/png"
        assert content["X-Content-Type-Options"] == "nosniff"
        detail = api("article-detail", alice_home, article_id=body["id"])
        removed = client_of_alice.patch(detail, {"clear_label": True}, format="json")
        assert removed.json()["label_url"] is None
        assert client_of_alice.get(body["label_url"]).status_code == 404
        assert list((media_root / "stock" / str(alice_home.id)).iterdir()) == []

    def test_a_fake_type_is_refused(self, client_of_alice: APIClient, alice_home: Home) -> None:
        response = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tin", "label": upload(b"<script>1</script>", "x.jpg", "image/jpeg")},
            format="multipart",
        )
        assert response.status_code == 400
        assert "label" in response.json()
        assert not Article.objects.filter(name="Tin").exists()

    def test_an_oversized_body_is_refused_before_it_is_read(
        self, client_of_alice: APIClient, alice_home: Home
    ) -> None:
        response = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tin"},
            format="json",
            CONTENT_LENGTH=str(conf.photo_max_bytes() + conf.MULTIPART_OVERHEAD + 1),
        )
        assert response.status_code == 413

    def test_a_file_over_the_limit_is_refused(
        self, client_of_alice: APIClient, alice_home: Home, settings: object
    ) -> None:
        settings.HOUSECAIRN_PHOTO_MAX_BYTES = conf.MIN_PHOTO_MAX_BYTES  # type: ignore[attr-defined]
        from tests.rooms_support import noise_image

        response = client_of_alice.post(
            api("article-list", alice_home),
            {"name": "Tin", "label": upload(noise_image(side=96), "x.png", "image/png")},
            format="multipart",
        )
        assert response.status_code == 400
        assert "label" in response.json()


class TestSuppliers:
    def test_crud(self, client_of_alice: APIClient, alice_home: Home, article: Article) -> None:
        created = client_of_alice.post(
            api("supplier-list", alice_home),
            {
                "article": str(article.id),
                "name": "Acme",
                "url": "https://shop.example.com/a",
                "last_price": "12.5",
            },
        )
        assert created.status_code == 201, created.content
        detail = api("supplier-detail", alice_home, supplier_id=created.json()["id"])
        assert client_of_alice.get(detail).json()["last_price"] == "12.50"
        assert client_of_alice.patch(detail, {"name": "Acme 2"}).json()["name"] == "Acme 2"
        assert client_of_alice.delete(detail).status_code == 204
        assert client_of_alice.get(detail).status_code == 404

    @pytest.mark.parametrize(
        "link", ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd"]
    )
    def test_only_web_links_are_accepted(
        self, client_of_alice: APIClient, alice_home: Home, article: Article, link: str
    ) -> None:
        response = client_of_alice.post(
            api("supplier-list", alice_home),
            {"article": str(article.id), "name": "Acme", "url": link},
        )
        assert response.status_code == 400
        assert "url" in response.json()
        assert not Supplier.objects.exists()

    def test_filter_and_no_move_between_articles(
        self,
        client_of_alice: APIClient,
        alice: User,
        alice_home: Home,
        article: Article,
        supplier: Supplier,
    ) -> None:
        other = services.create_article(alice, alice_home, name="Other")
        services.create_supplier(alice, other, name="Elsewhere")
        address = api("supplier-list", alice_home)
        assert len(client_of_alice.get(address).json()["results"]) == 2
        mine = client_of_alice.get(address, {"article": str(article.id)}).json()["results"]
        assert [s["name"] for s in mine] == ["Acme"]
        detail = api("supplier-detail", alice_home, supplier_id=supplier.id)
        moved = client_of_alice.patch(detail, {"article": str(other.id)})
        assert moved.status_code == 400
        same = client_of_alice.patch(detail, {"article": str(article.id), "name": "Acme 3"})
        assert same.status_code == 200

    def test_an_article_of_another_home_is_refused(
        self, client_of_alice: APIClient, alice_home: Home, foreign_article: Article
    ) -> None:
        response = client_of_alice.post(
            api("supplier-list", alice_home), {"article": str(foreign_article.id), "name": "x"}
        )
        assert response.status_code == 400
        assert "article" in response.json()
        assert not Supplier.objects.exists()


class TestMovements:
    def test_the_ledger(
        self, client_of_alice: APIClient, alice_home: Home, article: Article
    ) -> None:
        address = api("movement-list", alice_home)

        def post(**data: object) -> dict[str, object]:
            return client_of_alice.post(address, {"article": str(article.id), **data}).json()

        entry = post(kind="entry", quantity="5", occurred_on="2026-03-01", note="bought")
        assert (entry["delta"], entry["occurred_on"], entry["note"]) == (
            "5.00",
            "2026-03-01",
            "bought",
        )
        assert post(kind="exit", quantity="2")["delta"] == "-2.00"
        assert post(kind="inventory", quantity="10")["delta"] == "7.00"
        refused = client_of_alice.post(
            address, {"article": str(article.id), "kind": "exit", "quantity": "99"}
        )
        assert refused.status_code == 400
        assert "quantity" in refused.json()
        assert services.quantity_of(article) == 10
        rows = client_of_alice.get(address, {"article": str(article.id)}).json()["results"]
        assert len(rows) == 3
        assert [
            r["kind"] for r in client_of_alice.get(address, {"kind": "exit"}).json()["results"]
        ] == ["exit"]
        detail = api("movement-detail", alice_home, movement_id=entry["id"])
        assert client_of_alice.get(detail).json()["note"] == "bought"

    def test_a_line_is_never_changed_or_deleted(
        self, client_of_alice: APIClient, alice: User, alice_home: Home, article: Article
    ) -> None:
        line = services.record_movement(alice, article, kind="entry", quantity=Decimal("1"))
        detail = api("movement-detail", alice_home, movement_id=line.id)
        for method in ("patch", "put", "delete"):
            assert getattr(client_of_alice, method)(detail, {"quantity": "9"}).status_code == 405
        assert Movement.objects.get(id=line.id).quantity == 1

    def test_the_delta_and_the_kind_are_checked(
        self, client_of_alice: APIClient, alice_home: Home, article: Article
    ) -> None:
        address = api("movement-list", alice_home)
        data = {"article": str(article.id), "quantity": "1"}
        assert client_of_alice.post(address, {**data, "kind": "x"}).status_code == 400
        assert (
            client_of_alice.post(address, {**data, "kind": "entry", "delta": "50"}).json()["delta"]
            == "1.00"
        )
        assert (
            client_of_alice.post(address, {**data, "kind": "entry", "quantity": "-1"}).status_code
            == 400
        )
        assert (
            client_of_alice.post(address, {**data, "kind": "entry", "quantity": "0"}).status_code
            == 400
        )

    def test_an_article_of_another_home_is_refused(
        self, client_of_alice: APIClient, alice_home: Home, foreign_article: Article
    ) -> None:
        response = client_of_alice.post(
            api("movement-list", alice_home),
            {"article": str(foreign_article.id), "kind": "entry", "quantity": "1"},
        )
        assert response.status_code == 400
        assert not Movement.objects.exists()


class TestRolesAndIsolation:
    def endpoints(
        self, home: Home, article: Article, supplier: Supplier, movement: Movement
    ) -> list[tuple[str, str]]:
        return [
            ("get", api("article-list", home)),
            ("get", api("article-detail", home, article_id=article.id)),
            ("get", api("article-label", home, article_id=article.id)),
            ("get", api("supplier-list", home)),
            ("get", api("supplier-detail", home, supplier_id=supplier.id)),
            ("get", api("movement-list", home)),
            ("get", api("movement-detail", home, movement_id=movement.id)),
        ]

    def writes(
        self, home: Home, article: Article, supplier: Supplier
    ) -> list[tuple[str, str, dict[str, object]]]:
        return [
            ("post", api("article-list", home), {"name": "x"}),
            ("patch", api("article-detail", home, article_id=article.id), {"name": "x"}),
            ("delete", api("article-detail", home, article_id=article.id), {}),
            ("post", api("supplier-list", home), {"article": str(article.id), "name": "x"}),
            ("patch", api("supplier-detail", home, supplier_id=supplier.id), {"name": "x"}),
            ("delete", api("supplier-detail", home, supplier_id=supplier.id), {}),
            (
                "post",
                api("movement-list", home),
                {"article": str(article.id), "kind": "entry", "quantity": "1"},
            ),
        ]

    @pytest.fixture
    def movement(self, alice: User, article: Article) -> Movement:
        return services.record_movement(alice, article, kind="entry", quantity=Decimal("2"))

    @pytest.fixture
    def with_label(self, alice: User, article: Article) -> Article:
        return services.update_article(alice, article, label=upload(image_bytes()))

    def test_read_only_members_read_and_change_nothing(
        self,
        api_client: APIClient,
        reader: User,
        alice_home: Home,
        with_label: Article,
        supplier: Supplier,
        movement: Movement,
    ) -> None:
        api_client.force_authenticate(reader)
        for method, address in self.endpoints(alice_home, with_label, supplier, movement):
            assert getattr(api_client, method)(address).status_code == 200, address
        for method, address, data in self.writes(alice_home, with_label, supplier):
            response = getattr(api_client, method)(address, data, format="json")
            assert response.status_code == 403, (method, address)
        assert Article.objects.get(id=with_label.id).name == "Boiler filter"
        assert Movement.objects.count() == 1

    def test_a_member_writes(
        self, api_client: APIClient, member: User, alice_home: Home, article: Article
    ) -> None:
        api_client.force_authenticate(member)
        assert api_client.post(api("article-list", alice_home), {"name": "x"}).status_code == 201
        movement = {"article": str(article.id), "kind": "entry", "quantity": "1"}
        assert api_client.post(api("movement-list", alice_home), movement).status_code == 201

    def test_another_home_is_a_404_everywhere(
        self,
        api_client: APIClient,
        bob: User,
        alice_home: Home,
        with_label: Article,
        supplier: Supplier,
        movement: Movement,
    ) -> None:
        api_client.force_authenticate(bob)
        for method, address in self.endpoints(alice_home, with_label, supplier, movement):
            assert getattr(api_client, method)(address).status_code == 404, address
        for method, address, data in self.writes(alice_home, with_label, supplier):
            response = getattr(api_client, method)(address, data, format="json")
            assert response.status_code == 404, (method, address)
        assert Movement.objects.count() == 1

    def test_the_rows_of_another_home_are_not_reachable_through_mine(
        self,
        client_of_alice: APIClient,
        alice_home: Home,
        bob: User,
        bob_home: Home,
        foreign_article: Article,
    ) -> None:
        theirs_supplier = services.create_supplier(bob, foreign_article, name="Theirs")
        theirs_move = services.record_movement(
            bob, foreign_article, kind="entry", quantity=Decimal("1")
        )
        reached = [
            api("article-detail", alice_home, article_id=foreign_article.id),
            api("article-label", alice_home, article_id=foreign_article.id),
            api("supplier-detail", alice_home, supplier_id=theirs_supplier.id),
            api("movement-detail", alice_home, movement_id=theirs_move.id),
        ]
        for address in reached:
            assert client_of_alice.get(address).status_code == 404, address
        for name in ("article-list", "supplier-list", "movement-list"):
            assert client_of_alice.get(api(name, alice_home)).json()["results"] == []
        assert client_of_alice.delete(reached[0]).status_code == 404
        assert Article.objects.filter(id=foreign_article.id).exists()

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
        self,
        token: Callable[..., APIClient],
        alice_home: Home,
        article: Article,
        supplier: Supplier,
        movement: Movement,
    ) -> None:
        reading = token(["read"])
        for method, address in self.endpoints(alice_home, article, supplier, movement)[:2]:
            assert getattr(reading, method)(address).status_code == 200, address
        for method, address, data in self.writes(alice_home, article, supplier):
            assert getattr(reading, method)(address, data, format="json").status_code == 403
        writing = token(["write"])
        assert writing.post(api("article-list", alice_home), {"name": "x"}).status_code == 201
        assert writing.get(api("article-list", alice_home)).status_code == 403
        events_only = token(["events"])
        assert events_only.get(api("article-list", alice_home)).status_code == 403
        assert events_only.post(api("article-list", alice_home), {"name": "y"}).status_code == 403

    def test_a_token_bound_to_another_home_sees_nothing(
        self,
        token: Callable[..., APIClient],
        alice: User,
        alice_home: Home,
        article: Article,
        supplier: Supplier,
        movement: Movement,
    ) -> None:
        second = home_services.create_home(alice, name="Holiday flat")
        client = token(["read", "write"], [second])
        for method, address in self.endpoints(alice_home, article, supplier, movement):
            assert getattr(client, method)(address).status_code == 404, address
        assert client.get(api("article-list", second)).status_code == 200

    def test_anonymous_requests_are_refused_and_change_nothing(
        self, alice_home: Home, article: Article, supplier: Supplier, movement: Movement
    ) -> None:
        anonymous = APIClient()
        for method, address in self.endpoints(alice_home, article, supplier, movement):
            assert getattr(anonymous, method)(address).status_code in {401, 403}, address
        for method, address, data in self.writes(alice_home, article, supplier):
            response = getattr(anonymous, method)(address, data, format="json")
            assert response.status_code in {401, 403}, (method, address)
        assert Article.objects.get(id=article.id).name == "Boiler filter"
        assert Movement.objects.count() == 1


def test_the_schema_lists_the_stock_operations(client_of_alice: APIClient) -> None:
    schema = client_of_alice.get(
        reverse("api-schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json"
    ).json()
    base = "/api/v1/homes/{home_id}"
    for path in (
        f"{base}/articles/",
        f"{base}/articles/{{article_id}}/",
        f"{base}/articles/{{article_id}}/label/",
        f"{base}/suppliers/",
        f"{base}/suppliers/{{supplier_id}}/",
        f"{base}/movements/",
        f"{base}/movements/{{movement_id}}/",
    ):
        assert path in schema["paths"], path
