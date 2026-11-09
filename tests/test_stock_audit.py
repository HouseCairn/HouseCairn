"""Articles and suppliers in the audit log of the home (docs/adr/0045, 0038)."""

import json
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.audit.models import AuditEvent
from housecairn.homes.models import Home
from housecairn.stock import services
from housecairn.stock.models import Article, Supplier
from housecairn.tasks import materials
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Occurrence, Task

pytest_plugins = ("tests.tasks_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

D = Decimal
STOCK_ACTIONS = ("article.", "supplier.")


def stock_events(home: Home | None = None) -> list[AuditEvent]:
    found = AuditEvent.objects.filter(action__regex=r"^(article|supplier)\.").order_by(
        "created_at", "id"
    )
    if home is not None:
        found = found.filter(home_id=home.id)
    return list(found)


@pytest.fixture
def supplier(alice: User, article: Article) -> Supplier:
    return services.create_supplier(
        alice, article, name="Hardware Shop", reference="HS-9", last_price=D("12.50")
    )


class TestArticles:
    def test_create_update_delete_write_one_line_each_with_the_title_only(
        self, alice: User, alice_home: Home
    ) -> None:
        made = services.create_article(
            alice,
            alice_home,
            name="Roof tile",
            notes="the key is under the mat",
            storage_location="Attic, left shelf",
            manufacturer_reference="RT-77",
        )
        services.update_article(alice, made, threshold=D("4"), notes="another secret")
        services.delete_article(alice, made)
        events = stock_events(alice_home)
        assert [e.action for e in events] == [
            "article.created",
            "article.updated",
            "article.deleted",
        ]
        assert {e.detail["title"] for e in events} == {"Roof tile"}
        assert events[1].detail["fields"] == ["notes", "threshold"]
        assert all(e.actor_id == alice.id for e in events)
        text = json.dumps([e.detail for e in events])
        for hidden in ("key is under", "another secret", "Attic", "RT-77"):
            assert hidden not in text

    def test_relations_and_the_label_are_named_never_shown(
        self, alice: User, article: Article, owner_item: object
    ) -> None:
        services.update_article(alice, article, compatible_items=[], rooms=[], clear_label=True)
        (event,) = [e for e in stock_events() if e.action == "article.updated"]
        assert event.detail["fields"] == ["compatible_items", "label", "rooms"]

    def test_the_lines_read_as_sentences(self, alice: User, alice_home: Home) -> None:
        made = services.create_article(alice, alice_home, name="Roof tile")
        services.delete_article(alice, made)
        sentences = [e.label for e in stock_events(alice_home)]
        assert sentences == ["Stock article added: Roof tile", "Stock article deleted: Roof tile"]

    def test_a_refused_write_leaves_no_line(
        self, alice: User, reader: User, alice_home: Home, article: Article
    ) -> None:
        before = len(stock_events())
        assert before == 1  # the fixture article: writes are recorded, so refusals can be told
        with pytest.raises(PermissionDenied):
            services.create_article(reader, alice_home, name="Nope")
        with pytest.raises(PermissionDenied):
            services.update_article(reader, article, name="Nope")
        with pytest.raises(PermissionDenied):
            services.delete_article(reader, article)
        with pytest.raises(ValidationError):
            services.create_article(alice, alice_home, name="")
        with pytest.raises(ValidationError):
            services.update_article(alice, article, name="")
        assert len(stock_events()) == before


class TestSuppliers:
    def test_create_update_delete_write_one_line_each(
        self, alice: User, alice_home: Home, supplier: Supplier
    ) -> None:
        services.update_supplier(alice, supplier, last_price=D("9"), url="https://example.com/p")
        services.delete_supplier(alice, supplier)
        events = [e for e in stock_events(alice_home) if e.action.startswith("supplier.")]
        assert [e.action for e in events] == [
            "supplier.created",
            "supplier.updated",
            "supplier.deleted",
        ]
        assert {e.detail["title"] for e in events} == {"Hardware Shop"}
        assert events[1].detail["fields"] == ["last_price", "url"]
        text = json.dumps([e.detail for e in events])
        for hidden in ("HS-9", "12.5", "example.com"):
            assert hidden not in text
        assert events[0].label == "Supplier added: Hardware Shop"

    def test_a_reader_leaves_no_line(
        self, reader: User, supplier: Supplier, article: Article
    ) -> None:
        before = len(stock_events())
        assert before == 2  # the article and the supplier of the fixtures
        with pytest.raises(PermissionDenied):
            services.create_supplier(reader, article, name="x")
        with pytest.raises(PermissionDenied):
            services.update_supplier(reader, supplier, name="x")
        with pytest.raises(PermissionDenied):
            services.delete_supplier(reader, supplier)
        assert len(stock_events()) == before


class TestReadingAndIsolation:
    def test_only_an_owner_reads_the_lines(
        self, alice: User, reader: User, member: User, alice_home: Home, article: Article
    ) -> None:
        assert any(e.action == "article.created" for e in audit.home_log(alice, alice_home.id))
        for other in (reader, member):
            with pytest.raises(PermissionDenied):
                audit.home_log(other, alice_home.id)

    def test_a_home_never_sees_the_lines_of_another(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, article: Article
    ) -> None:
        foreign = services.create_article(bob, bob_home, name="Foreign tile")
        services.create_supplier(bob, foreign, name="Foreign shop")
        mine = {e.detail.get("title") for e in audit.home_log(alice, alice_home.id)}
        theirs = {e.detail.get("title") for e in audit.home_log(bob, bob_home.id)}
        assert "Foreign tile" not in mine
        assert "Foreign shop" not in mine
        assert "Boiler filter" not in theirs
        assert {"Foreign tile", "Foreign shop"} <= theirs
        with pytest.raises(PermissionDenied):
            audit.home_log(alice, bob_home.id)


class TestMovementsStayOutOfTheLog:
    def test_movements_and_task_draws_write_no_line(
        self,
        alice: User,
        article: Article,
        owner_task: Task,
        owner_occurrence: Occurrence,
    ) -> None:
        services.record_movement(alice, article, kind="entry", quantity=D("5"))
        materials.add_material(alice, owner_task, article, D("2"))
        before = AuditEvent.objects.filter(action__startswith="article.").count()
        assert before == 1  # the fixture article is in the log; the movements below are not
        total = AuditEvent.objects.count()
        services.record_movement(alice, article, kind="exit", quantity=D("1"))
        services.record_movement(alice, article, kind="inventory", quantity=D("3"))
        closing = task_services.complete(alice, owner_occurrence)
        task_services.undo(alice, closing.occurrence)
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        assert not any(a.startswith(("movement.", "draw.", "material_draw.")) for a in actions)
        assert AuditEvent.objects.filter(action__startswith="article.").count() == before
        later = AuditEvent.objects.order_by("created_at", "id")[total:]
        assert not [e for e in later if e.action.startswith(STOCK_ACTIONS)]
