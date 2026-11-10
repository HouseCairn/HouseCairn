"""Stock follows the tasks: Done takes the planned materials, Undo gives them back (ADR 0046)."""

import io
import zipfile
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.stock import services as stock_services
from housecairn.stock.models import Article, Movement
from housecairn.tasks import materials, services
from housecairn.tasks.models import MaterialDraw, Occurrence, Status, Task

pytest_plugins = ("tests.tasks_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

D = Decimal


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"tasks:{name}", kwargs={"home_id": home.id, **kwargs})


def api(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"api-v1:home-{name}", kwargs={"home_id": home.id, **kwargs})


def stock(article: Article) -> Decimal:
    return stock_services.quantity_of(article)


def ledger(article: Article) -> list[tuple[str, Decimal]]:
    return [
        (m.kind, m.delta)
        for m in Movement.all_objects.filter(article=article).order_by("created_at", "id")
    ]


@pytest.fixture
def filters(alice: User, article: Article) -> Article:
    """The boiler filter, with 5 in stock."""
    stock_services.record_movement(alice, article, kind="entry", quantity=D("5"))
    return article


@pytest.fixture
def paint(alice: User, alice_home: Home) -> Article:
    item = stock_services.create_article(alice, alice_home, name="White paint", unit="litre")
    stock_services.record_movement(alice, item, kind="entry", quantity=D("10"))
    return item


@pytest.fixture
def needs_two(alice: User, owner_task: Task, filters: Article) -> Task:
    materials.add_material(alice, owner_task, filters, D("2"))
    return owner_task


class TestDone:
    def test_done_takes_the_planned_quantity_for_the_occurrence(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        closing = services.complete(alice, owner_occurrence)
        assert closing.short == ()
        assert stock(filters) == D("3.00")
        movement = Movement.objects.filter(article=filters).latest("created_at")
        assert (movement.kind, movement.delta, movement.occurrence_id) == (
            "exit",
            D("-2.00"),
            owner_occurrence.id,
        )
        assert movement.occurred_on == closing.occurrence.completed_on
        (draw,) = materials.draws_of(owner_occurrence)
        assert (draw.wanted, draw.drawn) == (D("2.00"), D("2.00"))

    def test_every_material_is_taken(
        self,
        alice: User,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
        paint: Article,
    ) -> None:
        materials.add_material(alice, needs_two, paint, D("1.5"))
        services.complete(alice, owner_occurrence)
        assert (stock(filters), stock(paint)) == (D("3.00"), D("8.50"))

    def test_a_task_without_materials_touches_no_stock(
        self, alice: User, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        assert ledger(filters) == [("entry", D("5.00"))]
        assert not MaterialDraw.objects.exists()

    def test_skipping_takes_nothing(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.skip(alice, owner_occurrence)
        assert stock(filters) == D("5.00")

    def test_the_next_occurrence_takes_again(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        closing = services.complete(alice, owner_occurrence)
        assert closing.next is not None
        services.complete(alice, closing.next)
        assert stock(filters) == D("1.00")

    def test_done_twice_takes_once(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        with pytest.raises(ValidationError):
            services.complete(alice, owner_occurrence)
        assert stock(filters) == D("3.00")
        assert MaterialDraw.objects.count() == 1

    def test_two_closings_at_once_take_once(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        """Two people press Done: each holds the occurrence as it was read, still open."""
        first = Occurrence.objects.get(pk=owner_occurrence.pk)
        second = Occurrence.objects.get(pk=owner_occurrence.pk)
        services.complete(alice, first)
        with pytest.raises(ValidationError):
            services.complete(alice, second)
        assert stock(filters) == D("3.00")
        assert [kind for kind, _ in ledger(filters)] == ["entry", "exit"]

    def test_the_closing_locks_the_occurrence_then_the_articles(
        self,
        alice: User,
        needs_two: Task,
        owner_occurrence: Occurrence,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The row of the occurrence is locked before the stock is read, and so is the article.

        On PostgreSQL this is `SELECT ... FOR UPDATE`: the second of two closings waits for the
        first, then finds the occurrence closed. SQLite has no row lock, so the request for it is
        what is checked here.
        """
        locked: list[str] = []
        original = QuerySet.select_for_update

        def spy(self: QuerySet[Any], *args: Any, **kwargs: Any) -> QuerySet[Any]:
            locked.append(self.model.__name__)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(QuerySet, "select_for_update", spy)
        services.complete(alice, owner_occurrence)
        assert locked.index("Occurrence") < locked.index("Article")

    def test_a_second_draw_for_one_article_is_refused_by_the_database(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        with pytest.raises(IntegrityError), transaction.atomic():
            MaterialDraw.objects.create(
                home=owner_occurrence.home,
                occurrence=owner_occurrence,
                article=filters,
                wanted=D("1"),
                drawn=D("1"),
            )

    def test_a_deleted_article_is_left_out(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        stock_services.delete_article(alice, filters)
        closing = services.complete(alice, owner_occurrence)
        assert closing.occurrence.status == Status.DONE
        assert not MaterialDraw.objects.exists()

    def test_a_reader_takes_nothing(
        self,
        reader: User,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        with pytest.raises(PermissionDenied):
            services.complete(reader, owner_occurrence)
        assert stock(filters) == D("5.00")


class TestNotEnoughStock:
    """Done is never blocked: the stock goes down to zero and the shortage is said (ADR 0046)."""

    def test_done_goes_through_and_the_stock_stops_at_zero(
        self, alice: User, owner_occurrence: Occurrence, filters: Article, owner_task: Task
    ) -> None:
        materials.add_material(alice, owner_task, filters, D("8"))
        closing = services.complete(alice, owner_occurrence)
        assert closing.occurrence.status == Status.DONE
        assert stock(filters) == D("0.00")
        ((short,),) = [closing.short]
        assert (short.article, short.wanted, short.drawn, short.missing) == (
            filters,
            D("8.00"),
            D("5.00"),
            D("3.00"),
        )
        # The ledger holds what really left; it never goes negative.
        assert ledger(filters) == [("entry", D("5.00")), ("exit", D("-5.00"))]

    def test_an_empty_stock_writes_no_line(
        self, alice: User, owner_occurrence: Occurrence, article: Article, owner_task: Task
    ) -> None:
        materials.add_material(alice, owner_task, article, D("1"))
        closing = services.complete(alice, owner_occurrence)
        assert closing.short[0].drawn == D("0.00")
        assert ledger(article) == []
        (draw,) = materials.draws_of(owner_occurrence)
        assert (draw.wanted, draw.drawn) == (D("1.00"), D("0.00"))

    def test_undoing_gives_back_what_was_taken_only(
        self, alice: User, owner_occurrence: Occurrence, filters: Article, owner_task: Task
    ) -> None:
        materials.add_material(alice, owner_task, filters, D("8"))
        services.complete(alice, owner_occurrence)
        services.undo(alice, owner_occurrence)
        assert stock(filters) == D("5.00")

    def test_the_screen_says_so(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        owner_occurrence: Occurrence,
        filters: Article,
        owner_task: Task,
    ) -> None:
        materials.add_material(alice, owner_task, filters, D("8"))
        response = signed_in.post(
            url(
                "complete",
                alice_home,
                task_id=owner_task.id,
                occurrence_id=owner_occurrence.id,
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert "Not enough in stock, the stock is at zero: Boiler filter: 5 of 8." in response.text
        assert Occurrence.objects.get(pk=owner_occurrence.pk).status == Status.DONE

    def test_the_api_says_so_and_goes_through(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        owner_occurrence: Occurrence,
        filters: Article,
        owner_task: Task,
    ) -> None:
        materials.add_material(alice, owner_task, filters, D("8"))
        api_client.force_authenticate(alice)
        response = api_client.post(
            api("occurrence-complete", alice_home, occurrence_id=owner_occurrence.id)
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["occurrence"]["status"] == "done"
        assert [
            (s["article_name"], s["wanted"], s["drawn"], s["missing"]) for s in body["short"]
        ] == [("Boiler filter", "8.00", "5.00", "3.00")]
        assert [(s["drawn"], s["missing"]) for s in body["occurrence"]["stock"]] == [
            ("5.00", "3.00")
        ]

    def test_a_task_that_is_enough_reports_no_shortage(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
    ) -> None:
        api_client.force_authenticate(alice)
        response = api_client.post(
            api("occurrence-complete", alice_home, occurrence_id=owner_occurrence.id)
        )
        assert response.json()["short"] == []


class TestUndo:
    def test_undo_puts_the_stock_back_by_new_lines(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.undo(alice, owner_occurrence)
        assert stock(filters) == D("5.00")
        # Nothing was erased: the exit is still there, with its reverse.
        assert ledger(filters) == [("entry", D("5.00")), ("exit", D("-2.00")), ("entry", D("2.00"))]
        assert not materials.draws_of(owner_occurrence)
        assert Movement.objects.filter(article=filters, occurrence=owner_occurrence).count() == 2

    def test_done_again_after_undo_takes_again(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.undo(alice, owner_occurrence)
        services.complete(alice, owner_occurrence)
        assert stock(filters) == D("3.00")
        assert materials.draws_of(owner_occurrence).count() == 1

    def test_undoing_a_skip_touches_no_stock(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.skip(alice, owner_occurrence)
        services.undo(alice, owner_occurrence)
        assert ledger(filters) == [("entry", D("5.00"))]

    def test_undo_with_an_article_deleted_since(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        stock_services.delete_article(alice, filters)
        services.undo(alice, owner_occurrence)
        assert Occurrence.objects.get(pk=owner_occurrence.pk).status == Status.PLANNED

    def test_a_refused_undo_leaves_the_stock_alone(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        closing = services.complete(alice, owner_occurrence)
        assert closing.next is not None
        services.postpone(alice, closing.next, services.today() + services.today().resolution)
        with pytest.raises(ValidationError):
            services.undo(alice, owner_occurrence)
        assert stock(filters) == D("3.00")
        assert materials.draws_of(owner_occurrence).count() == 1

    def test_the_screen_undo_puts_it_back(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        done = Occurrence.objects.get(pk=owner_occurrence.pk)
        response = signed_in.post(
            url("undo", alice_home, task_id=needs_two.id, occurrence_id=done.id)
        )
        assert response.status_code == 302
        assert stock(filters) == D("5.00")

    def test_the_api_undo_puts_it_back(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        api_client.force_authenticate(alice)
        response = api_client.post(
            api("occurrence-undo", alice_home, occurrence_id=owner_occurrence.id)
        )
        assert response.status_code == 200
        assert stock(filters) == D("5.00")


class TestRealQuantity:
    """Done stays one gesture; the quantity really used is entered after, when completing."""

    def test_less_puts_the_difference_back(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.update_occurrence(alice, owner_occurrence, used={filters.id: D("1")})
        assert stock(filters) == D("4.00")
        assert ledger(filters)[-1] == ("entry", D("1.00"))
        (draw,) = materials.draws_of(owner_occurrence)
        assert (draw.wanted, draw.drawn) == (D("1.00"), D("1.00"))

    def test_more_takes_the_difference(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.update_occurrence(alice, owner_occurrence, used={filters.id: D("4")})
        assert stock(filters) == D("1.00")
        assert ledger(filters)[-1] == ("exit", D("-2.00"))

    def test_nothing_used_gives_everything_back(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.update_occurrence(alice, owner_occurrence, used={filters.id: D("0")})
        assert stock(filters) == D("5.00")
        # And undoing afterwards gives back nothing more.
        services.undo(alice, owner_occurrence)
        assert stock(filters) == D("5.00")

    def test_more_than_the_stock_holds_stops_at_zero(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        services.update_occurrence(alice, owner_occurrence, used={filters.id: D("9")})
        assert stock(filters) == D("0.00")
        (draw,) = materials.draws_of(owner_occurrence)
        assert (draw.wanted, draw.drawn, draw.missing) == (D("9.00"), D("5.00"), D("4.00"))
        services.undo(alice, owner_occurrence)
        assert stock(filters) == D("5.00")

    def test_the_same_quantity_changes_nothing(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        before = ledger(filters)
        services.update_occurrence(alice, owner_occurrence, used={filters.id: D("2")})
        assert ledger(filters) == before

    def test_the_cost_is_kept_with_the_quantities(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        done = services.update_occurrence(
            alice, owner_occurrence, used={filters.id: D("1")}, actual_cost=D("12.5")
        )
        assert done.actual_cost == D("12.5")
        assert Occurrence.objects.get(pk=owner_occurrence.pk).actual_cost == D("12.5")

    def test_an_article_not_taken_is_refused(
        self,
        alice: User,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
        paint: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        with pytest.raises(ValidationError) as caught:
            services.update_occurrence(alice, owner_occurrence, used={paint.id: D("1")})
        assert "used" in caught.value.message_dict
        assert stock(paint) == D("10.00")

    def test_a_negative_quantity_is_refused_and_nothing_changes(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        services.complete(alice, owner_occurrence)
        with pytest.raises(ValidationError):
            services.update_occurrence(
                alice, owner_occurrence, used={filters.id: D("-1")}, completion_note="x"
            )
        assert stock(filters) == D("3.00")
        assert Occurrence.objects.get(pk=owner_occurrence.pk).completion_note == ""

    def test_an_open_occurrence_cannot_be_completed_with_quantities(
        self, alice: User, needs_two: Task, owner_occurrence: Occurrence, filters: Article
    ) -> None:
        with pytest.raises(ValidationError):
            services.update_occurrence(alice, owner_occurrence, used={filters.id: D("1")})
        assert stock(filters) == D("5.00")

    def test_a_reader_changes_nothing(
        self,
        alice: User,
        reader: User,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        with pytest.raises(PermissionDenied):
            services.update_occurrence(reader, owner_occurrence, used={filters.id: D("0")})
        assert stock(filters) == D("3.00")

    def test_the_screen_adjusts_the_quantity(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        address = url(
            "occurrence-edit", alice_home, task_id=needs_two.id, occurrence_id=owner_occurrence.id
        )
        page = signed_in.get(address)
        assert "Used: Boiler filter (piece)" in page.text
        response = signed_in.post(
            address,
            {
                "completed_on": services.today().isoformat(),
                "actual_cost": "",
                "completion_note": "used one",
                f"used_{filters.id}": "1",
            },
        )
        assert response.status_code == 302, response.text
        assert stock(filters) == D("4.00")

    def test_the_screen_refuses_a_negative_quantity(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        address = url(
            "occurrence-edit", alice_home, task_id=needs_two.id, occurrence_id=owner_occurrence.id
        )
        response = signed_in.post(
            address,
            {"completed_on": services.today().isoformat(), f"used_{filters.id}": "-1"},
        )
        assert response.status_code == 200
        assert stock(filters) == D("3.00")

    def test_the_api_adjusts_the_quantity_like_the_screen(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        api_client.force_authenticate(alice)
        detail = api("occurrence-detail", alice_home, occurrence_id=owner_occurrence.id)
        response = api_client.patch(
            detail,
            {"used": [{"article": str(filters.id), "quantity": "1"}], "completion_note": "x"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert stock(filters) == D("4.00")
        assert [(s["article_name"], s["wanted"], s["drawn"]) for s in response.json()["stock"]] == [
            ("Boiler filter", "1.00", "1.00")
        ]
        bad = api_client.patch(
            detail, {"used": [{"article": str(filters.id), "quantity": "-1"}]}, format="json"
        )
        assert bad.status_code == 400
        elsewhere = api_client.patch(
            detail,
            {"used": [{"article": str(owner_occurrence.id), "quantity": "1"}]},
            format="json",
        )
        assert elsewhere.status_code == 400
        assert stock(filters) == D("4.00")

    def test_a_reader_cannot_adjust_through_the_api(
        self,
        api_client: APIClient,
        alice: User,
        reader: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        api_client.force_authenticate(reader)
        detail = api("occurrence-detail", alice_home, occurrence_id=owner_occurrence.id)
        response = api_client.patch(
            detail, {"used": [{"article": str(filters.id), "quantity": "0"}]}, format="json"
        )
        assert response.status_code == 403
        assert stock(filters) == D("3.00")


class TestParity:
    def test_the_screen_and_the_api_leave_the_same_ledger(
        self,
        signed_in: Client,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        filters: Article,
    ) -> None:
        api_client.force_authenticate(alice)
        outcomes = []
        for through in ("screen", "api"):
            task = services.create_task(alice, alice_home, title=f"Task {through}")
            materials.add_material(alice, task, filters, D("2"))
            occurrence = services.open_occurrence_of(task)
            assert occurrence is not None
            before = len(ledger(filters))
            if through == "screen":
                signed_in.post(
                    url("complete", alice_home, task_id=task.id, occurrence_id=occurrence.id)
                )
            else:
                api_client.post(api("occurrence-complete", alice_home, occurrence_id=occurrence.id))
            outcomes.append(ledger(filters)[before:])
        assert outcomes[0] == outcomes[1] == [("exit", D("-2.00"))]


class TestIsolationAndData:
    def test_a_stranger_cannot_close_a_task_of_another_home(
        self,
        client: Client,
        bob: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        client.force_login(bob)
        response = client.post(
            url(
                "complete",
                alice_home,
                task_id=needs_two.id,
                occurrence_id=owner_occurrence.id,
            )
        )
        assert response.status_code == 404
        assert stock(filters) == D("5.00")

    def test_the_article_ledger_names_the_task(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        page = signed_in.get(
            reverse("stock:detail", kwargs={"home_id": alice_home.id, "article_id": filters.id})
        )
        assert needs_two.title in page.text
        listed = APIClient()
        listed.force_authenticate(alice)
        rows = listed.get(api("movement-list", alice_home), {"article": filters.id}).json()
        assert str(owner_occurrence.id) in [row["occurrence"] for row in rows["results"]]

    def test_the_export_holds_the_draws_and_the_link_of_the_movements(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        needs_two: Task,
        owner_occurrence: Occurrence,
        filters: Article,
    ) -> None:
        services.complete(alice, owner_occurrence)
        client.force_login(alice)
        response = client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
        from tests.data_support import export_data

        data = export_data(zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))))
        assert [(d["occurrence"], d["wanted"], d["drawn"]) for d in data["stock_draws"]] == [
            (str(owner_occurrence.id), "2.00", "2.00")
        ]
        assert str(owner_occurrence.id) in [m["occurrence"] for m in data["stock_movements"]]

    def test_erasing_the_home_erases_the_draws(
        self, alice: User, alice_home: Home, needs_two: Task, owner_occurrence: Occurrence
    ) -> None:
        services.complete(alice, owner_occurrence)
        with TestCase.captureOnCommitCallbacks(execute=True):
            home_services.delete_home(alice, alice_home, confirmation="Main house")
        assert not MaterialDraw.all_objects.exists()
        assert not Movement.all_objects.exists()
