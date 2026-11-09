"""Projects, quotes, budget lines and their screens (docs/adr/0050)."""

import datetime
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent
from housecairn.homes import quotas
from housecairn.homes.models import Home
from housecairn.projects import services
from housecairn.projects.models import (
    BudgetLine,
    Project,
    ProjectFile,
    ProjectTask,
    Quote,
)
from housecairn.rooms.models import Room
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Task
from tests.rooms_support import image_bytes, upload
from tests.tasks_fixtures import PDF

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]

MAX = Decimal("9999999999.99")


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"projects:{name}", kwargs={"home_id": home.id, **kwargs})


class TestLivingRoomScenario:
    """Two quotes, 800 planned, one accepted, one expense entered, the gap displayed."""

    def test_the_amounts_follow_the_quotes_and_the_payments(
        self, alice: User, living_room_project: Project, labour_line: BudgetLine
    ) -> None:
        cheap = services.create_quote(
            alice, living_room_project, amount=Decimal("620.00"), status="received"
        )
        dear = services.create_quote(
            alice, living_room_project, amount=Decimal("780.00"), status="received"
        )
        assert services.amounts_of(living_room_project) == services.Amounts(
            Decimal("800.00"), Decimal("0"), Decimal("0")
        )
        services.accept_quote(alice, cheap, labour_line)
        services.update_line(alice, labour_line, paid=Decimal("120.00"))
        services.update_quote(alice, dear, status="rejected")
        total = services.amounts_of(living_room_project)
        assert (total.planned, total.committed, total.paid) == (
            Decimal("800.00"),
            Decimal("620.00"),
            Decimal("120.00"),
        )
        assert total.gap == Decimal("180.00")
        assert total.state == "under"
        assert total.to_pay == Decimal("500.00")

    def test_the_page_says_the_gap_in_words(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
    ) -> None:
        accepted = services.create_quote(alice, living_room_project, amount=Decimal("620.00"))
        services.accept_quote(alice, accepted, labour_line)
        services.update_line(alice, labour_line, paid=Decimal("120.00"))
        html = signed_in.get(
            url("detail", alice_home, project_id=living_room_project.id)
        ).content.decode()
        assert "800.00" in html
        assert "620.00" in html
        assert "120.00" in html
        assert "180.00\u00a0EUR left" in html
        listing = signed_in.get(url("list", alice_home) + "?view=ideas").content.decode()
        assert "180.00\u00a0EUR left" in listing

    def test_a_project_over_its_budget_says_so_in_words(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
    ) -> None:
        big = services.create_quote(alice, living_room_project, amount=Decimal("950.00"))
        services.accept_quote(alice, big, labour_line)
        total = services.amounts_of(living_room_project)
        assert (total.gap, total.state, total.over_by) == (
            Decimal("-150.00"),
            "over",
            Decimal("150.00"),
        )
        html = signed_in.get(
            url("detail", alice_home, project_id=living_room_project.id)
        ).content.decode()
        assert "Over budget by 150.00\u00a0EUR" in html

    def test_payments_above_the_commitment_also_count_against_the_plan(
        self, alice: User, living_room_project: Project, labour_line: BudgetLine
    ) -> None:
        services.update_line(alice, labour_line, paid=Decimal("900"))
        total = services.amounts_of(living_room_project)
        assert total.gap == Decimal("-100.00")
        assert total.state == "over"
        assert total.to_pay == Decimal("0")

    def test_an_overrun_on_one_line_is_not_hidden_by_room_left_on_another(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
    ) -> None:
        paint = BudgetLine.objects.get(project=living_room_project, label="Paint")
        services.update_line(alice, paint, paid=Decimal("350"))
        painter = services.create_quote(alice, living_room_project, amount=Decimal("540.50"))
        services.accept_quote(alice, painter, labour_line)
        total = services.amounts_of(living_room_project)
        # Paint is over by 50.00 and the painter by 40.50: 90.50 over, not 259.50 left.
        assert (total.planned, total.committed, total.paid) == (
            Decimal("800.00"),
            Decimal("540.50"),
            Decimal("350.00"),
        )
        assert (total.gap, total.state, total.over_by) == (
            Decimal("-90.50"),
            "over",
            Decimal("90.50"),
        )
        assert services.compare(alice_home, [living_room_project.id])[0].amounts.gap == (
            Decimal("-90.50")
        )
        for page in (
            url("detail", alice_home, project_id=living_room_project.id),
            url("list", alice_home) + "?view=ideas",
        ):
            html = signed_in.get(page).content.decode()
            assert "Over budget by 90.50\u00a0EUR" in html, page
            assert "259.50" not in html, page

    def test_a_project_without_a_budget_has_no_gap_pill(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        empty = services.create_project(alice, alice_home, title="Someday")
        html = signed_in.get(url("detail", alice_home, project_id=empty.id)).content.decode()
        assert "On budget" not in html
        assert "left" not in html.split("<h2>Budget</h2>")[0]


class TestBathroomScenario:
    def test_a_budget_of_5000_and_three_tasks_created_from_the_project(
        self, signed_in: Client, alice_home: Home, alice: User
    ) -> None:
        created = signed_in.post(
            url("create", alice_home),
            {
                "title": "Redo the bathroom",
                "status": "planned",
                "priority": "high",
                "budget": "5000",
            },
        )
        project = Project.objects.get(title="Redo the bathroom")
        assert created.status_code == 302
        assert created["Location"] == url("detail", alice_home, project_id=project.id)
        (line,) = project.lines.all()
        assert (line.planned, line.nature) == (Decimal("5000.00"), "other")
        for title in ("Remove the old bath", "Tile the walls", "Fit the new shower"):
            response = signed_in.post(
                url("task-add", alice_home, project_id=project.id), {"title": title}
            )
            assert response.status_code == 302
        tasks = services.tasks_of(project)
        assert [link.task.title for link in tasks] == [
            "Remove the old bath",
            "Tile the walls",
            "Fit the new shower",
        ]
        assert all(task_services.open_occurrence_of(link.task) for link in tasks)
        html = signed_in.get(url("detail", alice_home, project_id=project.id)).content.decode()
        assert "Tile the walls" in html
        assert "5,000.00" in html
        assert services.amounts_of(project).planned == Decimal("5000.00")

    def test_the_page_of_a_task_names_its_project(
        self, signed_in: Client, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        task = services.add_task(alice, living_room_project, title="Mask the skirting boards")
        free = task_services.create_task(alice, alice_home, title="Bleed the radiators")
        page = signed_in.get(
            reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
        )
        assert "Paint the living room" in page.content.decode()
        other = signed_in.get(
            reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": free.id})
        )
        assert "Part of the project" not in other.content.decode()

    def test_a_task_made_from_the_project_takes_the_room_and_the_date(
        self, alice: User, alice_home: Home, living_room_project: Project, owner_room: Room
    ) -> None:
        day = task_services.today() + datetime.timedelta(days=3)
        task = services.add_task(
            alice, living_room_project, title="Order tiles", due_on=day, room=owner_room
        )
        occurrence = task_services.open_occurrence_of(task)
        assert occurrence is not None
        assert occurrence.due_on == day
        assert task.room_id == owner_room.id


class TestTaskLink:
    def test_a_task_is_in_one_project_at_most(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        other = services.create_project(alice, alice_home, title="Garden shed")
        task = task_services.create_task(alice, alice_home, title="Buy brushes")
        services.attach_task(alice, living_room_project, task)
        with pytest.raises(ValidationError, match="already in a project"):
            services.attach_task(alice, other, task)
        with pytest.raises(IntegrityError), transaction.atomic():
            ProjectTask.objects.create(home=alice_home, project=other, task=task)

    def test_two_people_putting_the_same_task_in_at_once_get_a_clean_refusal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
    ) -> None:
        other = services.create_project(alice, alice_home, title="Other")
        task = task_services.create_task(alice, alice_home, title="Shared")
        services.attach_task(alice, living_room_project, task)
        # The second person read "free" before the first one wrote: only the database is left.
        monkeypatch.setattr(services, "_task_is_taken", lambda _task: False)
        with pytest.raises(ValidationError) as refused:
            services.attach_task(alice, other, task)
        assert "already in a project" in " ".join(refused.value.messages)
        assert ProjectTask.all_objects.filter(task=task).count() == 1
        # On the screen, a message; through the API, a 400.
        monkeypatch.setattr(services, "attachable_tasks", lambda home: Task.objects.all())
        page = signed_in.post(
            url("task-attach", alice_home, project_id=other.id), {"task": task.id}, follow=True
        )
        assert page.status_code == 200
        assert "already in a project" in page.content.decode()
        api = APIClient()
        api.force_authenticate(alice)
        response = api.post(
            reverse("api-v1:home-project-task-list", kwargs={"home_id": alice_home.id}),
            {"project": str(other.id), "task": str(task.id)},
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "task" in response.json()

    def test_only_a_task_of_the_home_that_exists_can_be_put_in(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, living_room_project: Project
    ) -> None:
        foreign = task_services.create_task(bob, bob_home, title="Theirs")
        with pytest.raises(ValidationError):
            services.attach_task(alice, living_room_project, foreign)
        gone = task_services.create_task(alice, alice_home, title="Gone")
        task_services.delete_task(alice, gone)
        with pytest.raises(ValidationError):
            services.attach_task(alice, living_room_project, gone)
        assert not ProjectTask.objects.exists()

    def test_taking_a_task_out_keeps_the_task(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        task = services.add_task(alice, living_room_project, title="Sand the walls")
        (link,) = services.tasks_of(living_room_project)
        services.detach_task(alice, link)
        assert Task.objects.filter(id=task.id).exists()
        assert services.project_of_task(task) is None
        services.attach_task(alice, living_room_project, task)  # it can come back

    def test_deleting_a_task_removes_the_link_and_hides_it_meanwhile(
        self, alice: User, living_room_project: Project
    ) -> None:
        task = services.add_task(alice, living_room_project, title="Sand the walls")
        task_services.delete_task(alice, task)  # soft deletion
        assert services.tasks_of(living_room_project) == []
        assert services.project_of_task(task) is None
        Task.all_objects.filter(id=task.id).delete()  # the purge: the foreign key cascades
        assert not ProjectTask.all_objects.exists()

    def test_deleting_the_project_keeps_the_tasks(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        task = services.add_task(alice, living_room_project, title="Sand the walls")
        services.delete_project(alice, living_room_project)
        assert Task.objects.filter(id=task.id).exists()
        assert services.project_of_task(task) is None
        assert not ProjectTask.objects.exists()

    def test_the_tasks_app_knows_nothing_of_projects(self) -> None:
        names = {field.name for field in Task._meta.get_fields() if not field.auto_created}
        assert "project" not in names
        assert not [f for f in Task._meta.fields if "project" in f.name]


class TestMoney:
    @pytest.mark.parametrize("amount", [Decimal("0"), Decimal("0.01"), MAX])
    def test_amounts_from_nothing_to_the_largest_are_kept_exact(
        self, alice: User, living_room_project: Project, amount: Decimal
    ) -> None:
        line = services.create_line(alice, living_room_project, label="X", planned=amount)
        line.refresh_from_db()
        assert line.planned == amount
        assert isinstance(line.planned, Decimal)

    @pytest.mark.parametrize(
        "amount",
        [
            Decimal("10000000000.00"),
            Decimal("-0.01"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            Decimal("sNaN"),
            Decimal("1.005"),
            1.5,
            True,
            "abc",
            "1e5000",
            "",
        ],
    )
    def test_amounts_out_of_range_or_not_money_are_refused(
        self, alice: User, living_room_project: Project, amount: object
    ) -> None:
        for field in ("planned", "paid"):
            with pytest.raises(ValidationError) as caught:
                services.create_line(alice, living_room_project, label="Y", **{field: amount})
            assert field in caught.value.message_dict
        with pytest.raises(ValidationError):
            services.create_quote(alice, living_room_project, amount=amount)
        with pytest.raises(ValidationError):
            services.set_envelope(alice, living_room_project.home, year=2026, amount=amount)
        assert BudgetLine.objects.filter(label="Y").count() == 0

    def test_a_string_amount_with_two_decimals_is_accepted(
        self, alice: User, living_room_project: Project
    ) -> None:
        line = services.create_line(alice, living_room_project, label="Z", planned="12.50")
        assert line.planned == Decimal("12.50")

    def test_sums_stay_exact_at_the_extremes(self, alice: User, alice_home: Home) -> None:
        project = services.create_project(alice, alice_home, title="Palace")
        for label in "abc":
            services.create_line(alice, project, label=label, planned=MAX, paid=MAX)
        quote = services.create_quote(alice, project, amount=MAX)
        line = project.lines.first()
        assert line is not None
        services.accept_quote(alice, quote, line)
        total = services.amounts_of(project)
        assert total.planned == Decimal("29999999999.97")
        assert (total.committed, total.paid) == (MAX, Decimal("29999999999.97"))
        assert total.gap == Decimal("0.00")
        assert total.state == "on"
        assert isinstance(total.gap, Decimal)

    def test_a_tenth_of_a_cent_never_appears(
        self, alice: User, living_room_project: Project
    ) -> None:
        for _ in range(3):
            services.create_line(alice, living_room_project, label="n", planned=Decimal("0.10"))
        assert services.amounts_of(living_room_project).planned == Decimal("800.30")

    def test_the_database_refuses_a_negative_amount(
        self, living_room_project: Project, labour_line: BudgetLine
    ) -> None:
        with pytest.raises(IntegrityError), transaction.atomic():
            BudgetLine.objects.filter(id=labour_line.id).update(planned=Decimal("-1"))
        with pytest.raises(IntegrityError), transaction.atomic():
            Quote.objects.create(
                home=living_room_project.home, project=living_room_project, amount=Decimal("-1")
            )

    def test_the_form_refuses_what_is_not_money(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        for bad in ("abc", "-5", "NaN", "Infinity", "10000000000", "1.234"):
            response = signed_in.post(
                url("line-create", alice_home, project_id=living_room_project.id),
                {"label": "Bad", "nature": "other", "planned": bad, "paid": "0"},
            )
            assert response.status_code == 200, bad
        assert not BudgetLine.objects.filter(label="Bad").exists()


class TestTypedAmounts:
    """Amounts are typed the way people write them: a comma in French, a point in English."""

    FRENCH = {"headers": {"accept-language": "fr"}}

    @pytest.mark.parametrize(
        ("typed", "stored"),
        [
            ("540,50", "540.50"),
            ("1 250,50", "1250.50"),
            ("1\u00a0250,50", "1250.50"),
            ("1\u202f250,50", "1250.50"),
            ("1\u2009250,50", "1250.50"),
            ("12", "12.00"),
            ("0,5", "0.50"),
        ],
    )
    def test_french_amounts_take_a_comma_and_a_space_for_the_thousands(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        typed: str,
        stored: str,
    ) -> None:
        line = signed_in.post(
            url("line-create", alice_home, project_id=living_room_project.id),
            {"label": "Tiles", "nature": "material", "planned": typed, "paid": typed},
            **self.FRENCH,
        )
        assert line.status_code == 302, line.content[:300]
        saved = BudgetLine.objects.get(label="Tiles")
        assert (saved.planned, saved.paid) == (Decimal(stored), Decimal(stored))
        quote = signed_in.post(
            url("quote-create", alice_home, project_id=living_room_project.id),
            {"amount": typed, "status": "received"},
            **self.FRENCH,
        )
        assert quote.status_code == 302, quote.content[:300]
        assert Quote.objects.get(project=living_room_project, amount=Decimal(stored))
        project = signed_in.post(
            url("create", alice_home),
            {"title": "Shed", "status": "idea", "priority": "normal", "budget": typed},
            **self.FRENCH,
        )
        assert project.status_code == 302, project.content[:300]
        shed = Project.objects.get(title="Shed")
        assert services.amounts_of(shed).planned == Decimal(stored)

    def test_the_french_envelope_takes_a_comma(self, signed_in: Client, alice_home: Home) -> None:
        year = task_services.today().year
        response = signed_in.post(
            url("envelope", alice_home), {"year": year, "amount": "4 000,50"}, **self.FRENCH
        )
        assert response.status_code == 302, response.content[:300]
        assert services.envelope_summary(alice_home, year).envelope == Decimal("4000.50")

    def test_english_amounts_take_a_point(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        response = signed_in.post(
            url("line-create", alice_home, project_id=living_room_project.id),
            {"label": "Tiles", "nature": "material", "planned": "1250.50", "paid": "0"},
        )
        assert response.status_code == 302, response.content[:300]
        assert BudgetLine.objects.get(label="Tiles").planned == Decimal("1250.50")

    @pytest.mark.parametrize("language", ["en", "fr"])
    @pytest.mark.parametrize(
        "bad", ["abc", "-5", "NaN", "Infinity", "1e20", "1e40", "1e5000", "1,234", "1.234"]
    )
    def test_what_is_not_an_amount_is_still_refused(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        language: str,
        bad: str,
    ) -> None:
        response = signed_in.post(
            url("line-create", alice_home, project_id=living_room_project.id),
            {"label": "Bad", "nature": "other", "planned": bad, "paid": "0"},
            headers={"accept-language": language},
        )
        assert response.status_code == 200, (language, bad)
        assert not BudgetLine.objects.filter(label="Bad").exists()

    def test_the_form_shows_the_amount_the_way_it_is_typed(
        self, signed_in: Client, alice: User, living_room_project: Project, labour_line: BudgetLine
    ) -> None:
        services.update_line(alice, labour_line, planned=Decimal("1250.50"))
        page = url("line-edit", labour_line.home, line_id=labour_line.id)
        english = signed_in.get(page).content.decode()
        assert 'value="1250.50"' in english
        french = signed_in.get(page, headers={"accept-language": "fr"}).content.decode()
        assert 'value="1250,50"' in french


class TestQuotes:
    def test_accepting_commits_the_amount_on_the_chosen_line(
        self, alice: User, quote: Quote, labour_line: BudgetLine
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        quote.refresh_from_db()
        assert (quote.status, quote.budget_line_id) == ("accepted", labour_line.id)
        committed = services.committed_by_line([labour_line])
        assert committed[labour_line.id] == Decimal("620.00")

    def test_changing_the_amount_of_an_accepted_quote_moves_the_commitment(
        self, alice: User, living_room_project: Project, quote: Quote, labour_line: BudgetLine
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        services.update_quote(alice, quote, amount=Decimal("700"))
        assert services.amounts_of(living_room_project).committed == Decimal("700.00")

    def test_leaving_accepted_releases_the_commitment(
        self, alice: User, living_room_project: Project, quote: Quote, labour_line: BudgetLine
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        services.update_quote(alice, quote, status="rejected")
        quote.refresh_from_db()
        assert quote.budget_line_id is None
        assert services.amounts_of(living_room_project).committed == Decimal("0")

    def test_accepting_needs_a_line_of_the_same_project(
        self, alice: User, alice_home: Home, quote: Quote
    ) -> None:
        other = services.create_project(alice, alice_home, title="Other")
        elsewhere = services.create_line(alice, other, label="Elsewhere", planned=Decimal("1"))
        with pytest.raises(ValidationError):
            services.accept_quote(alice, quote, elsewhere)
        with pytest.raises(ValidationError):
            services.update_quote(alice, quote, status="accepted")
        quote.refresh_from_db()
        assert quote.status == "received"

    def test_the_database_refuses_an_accepted_quote_without_a_line(self, quote: Quote) -> None:
        with pytest.raises(IntegrityError), transaction.atomic():
            Quote.objects.filter(id=quote.id).update(status="accepted")

    def test_deleting_a_line_sends_its_accepted_quotes_back_to_received(
        self, alice: User, living_room_project: Project, quote: Quote, labour_line: BudgetLine
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        services.delete_line(alice, labour_line)
        quote.refresh_from_db()
        assert (quote.status, quote.budget_line_id) == ("received", None)
        assert services.amounts_of(living_room_project).committed == Decimal("0")
        assert [s.line.label for s in services.line_summaries(living_room_project)] == ["Paint"]

    def test_deleting_a_quote_releases_what_it_committed(
        self, alice: User, living_room_project: Project, quote: Quote, labour_line: BudgetLine
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        services.delete_quote(alice, quote)
        assert services.amounts_of(living_room_project).committed == Decimal("0")
        assert not services.quotes_of(living_room_project.home).exists()

    def test_the_contractor_is_chosen_or_created_by_name(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        first = services.contractor_named(alice, alice_home, "  Painter   B ")
        again = services.contractor_named(alice, alice_home, "painter b")
        assert first is not None
        assert again is not None
        assert first.pk == again.pk
        assert first.name == "Painter B"
        assert services.contractor_named(alice, alice_home, "   ") is None

    def test_a_quote_cannot_use_a_contractor_of_another_home(
        self, bob: User, bob_home: Home, alice: User, living_room_project: Project
    ) -> None:
        stranger = task_services.create_contractor(bob, bob_home, name="Stranger")
        with pytest.raises(ValidationError):
            services.create_quote(alice, living_room_project, contractor=stranger)

    def test_dates_are_ordered_and_bounded(self, alice: User, living_room_project: Project) -> None:
        day = datetime.date(2026, 6, 1)
        with pytest.raises(ValidationError) as caught:
            services.create_quote(
                alice, living_room_project, issued_on=day, valid_until=day - datetime.timedelta(1)
            )
        assert "valid_until" in caught.value.message_dict
        with pytest.raises(ValidationError):
            services.create_quote(alice, living_room_project, issued_on=datetime.date(1900, 1, 1))

    def test_the_paperless_slot_is_kept_and_only_takes_a_web_link(
        self, alice: User, living_room_project: Project
    ) -> None:
        saved = services.create_quote(
            alice,
            living_room_project,
            paperless_id=42,
            paperless_url="https://paperless.example.com/documents/42/",
        )
        assert (saved.paperless_id, saved.paperless_url[:8]) == (42, "https://")
        with pytest.raises(ValidationError):
            services.create_quote(alice, living_room_project, paperless_url="javascript:alert(1)")

    def test_the_quote_form_creates_the_contractor_and_takes_a_file(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        response = signed_in.post(
            url("quote-create", alice_home, project_id=living_room_project.id),
            {
                "contractor_name": "Painter C",
                "amount": "590.50",
                "status": "received",
                "upload": upload(PDF, "quote.pdf", "application/pdf"),
            },
        )
        assert response.status_code == 302, response.content[:300]
        saved = Quote.objects.get(project=living_room_project)
        assert saved.contractor is not None
        assert saved.contractor.name == "Painter C"
        (stored,) = saved.files.all()
        assert (stored.content_type, stored.is_image) == ("application/pdf", False)

    def test_accepting_from_the_page(
        self,
        signed_in: Client,
        alice_home: Home,
        quote: Quote,
        labour_line: BudgetLine,
        living_room_project: Project,
    ) -> None:
        response = signed_in.post(
            url("quote-accept", alice_home, quote_id=quote.id), {"budget_line": labour_line.id}
        )
        assert response.status_code == 302
        quote.refresh_from_db()
        assert quote.status == "accepted"
        # A line of another project is not one of the choices.
        other = services.create_project(
            quote.project.home.memberships.first().user, alice_home, title="Other"
        )  # type: ignore[union-attr]
        foreign_line = services.create_line(
            quote.project.home.memberships.first().user,
            other,
            label="F",
            planned=Decimal("1"),  # type: ignore[union-attr]
        )
        services.update_quote(
            quote.project.home.memberships.first().user,
            quote,
            status="received",  # type: ignore[union-attr]
        )
        signed_in.post(
            url("quote-accept", alice_home, quote_id=quote.id), {"budget_line": foreign_line.id}
        )
        quote.refresh_from_db()
        assert quote.status == "received"

    def test_editing_an_accepted_quote_keeps_its_line_selected(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        quote: Quote,
        labour_line: BudgetLine,
    ) -> None:
        services.accept_quote(alice, quote, labour_line)
        page = url("quote-edit", alice_home, quote_id=quote.id)
        html = signed_in.get(page).content.decode()
        select = re.search(r'<select name="budget_line".*?</select>', html, re.S)
        assert select is not None
        chosen = re.findall(r'<option value="([^"]*)" selected', select.group(0))
        assert chosen == [str(labour_line.id)]
        # What the browser sends back when nothing is touched is accepted.
        response = signed_in.post(
            page, {"amount": "620.00", "status": "accepted", "budget_line": chosen[0]}
        )
        assert response.status_code == 302, response.content[:300]
        quote.refresh_from_db()
        assert (quote.status, quote.budget_line_id) == ("accepted", labour_line.id)

    def test_the_status_buttons_never_accept(
        self, signed_in: Client, alice_home: Home, quote: Quote
    ) -> None:
        signed_in.post(url("quote-status", alice_home, quote_id=quote.id), {"status": "accepted"})
        signed_in.post(url("quote-status", alice_home, quote_id=quote.id), {"status": "rejected"})
        quote.refresh_from_db()
        assert quote.status == "rejected"


class TestProject:
    def test_only_the_title_is_required(self, alice: User, alice_home: Home) -> None:
        project = services.create_project(alice, alice_home, title="Idea")
        assert (project.status, project.priority, project.season) == ("idea", "normal", "")
        assert services.amounts_of(project) == services.Amounts()
        with pytest.raises(ValidationError):
            services.create_project(alice, alice_home, title="")

    def test_the_rooms_must_be_in_the_home(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, owner_room: Room
    ) -> None:
        from housecairn.rooms import services as room_services

        foreign = room_services.create_room(bob, bob_home, name="Hall")
        project = services.create_project(alice, alice_home, title="P", rooms=[owner_room])
        assert list(project.rooms.all()) == [owner_room]
        with pytest.raises(ValidationError):
            services.update_project(alice, project, rooms=[foreign])
        assert list(project.rooms.all()) == [owner_room]

    def test_the_duration_is_bounded(self, alice: User, alice_home: Home) -> None:
        year = 365 * 24 * 60
        assert (
            services.create_project(
                alice, alice_home, title="Long", estimated_minutes=year
            ).estimated_minutes
            == year
        )
        for bad in (0, year + 1):
            with pytest.raises(ValidationError):
                services.create_project(alice, alice_home, title="Bad", estimated_minutes=bad)

    def test_the_season_follows_the_hemisphere_of_the_home(
        self, alice: User, alice_home: Home
    ) -> None:
        project = services.create_project(alice, alice_home, title="Roof", season="summer")
        assert project.season_months == (6, 8)
        alice_home.hemisphere = "south"
        alice_home.save()
        project.refresh_from_db()
        assert project.season_months == (12, 2)

    def test_a_custom_season_needs_its_months_and_others_have_none(
        self, alice: User, alice_home: Home
    ) -> None:
        with pytest.raises(ValidationError):
            services.create_project(alice, alice_home, title="C", season="custom")
        custom = services.create_project(
            alice,
            alice_home,
            title="C",
            season="custom",
            season_start_month=4,
            season_end_month=6,
        )
        assert custom.season_months == (4, 6)
        changed = services.update_project(alice, custom, season="winter")
        assert (changed.season_start_month, changed.season_end_month) == (None, None)
        with pytest.raises(ValidationError):
            services.create_project(
                alice,
                alice_home,
                title="C",
                season="custom",
                season_start_month=0,
                season_end_month=13,
            )

    def test_unknown_fields_are_refused(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValueError, match="Cannot change: colour"):
            services.create_project(alice, alice_home, title="X", colour="red")

    def test_the_list_puts_what_is_going_on_first_and_filters(
        self, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        for title, status in (
            ("Done one", "done"),
            ("Idea one", "idea"),
            ("Going", "in_progress"),
            ("Dropped", "abandoned"),
            ("Soon", "planned"),
        ):
            services.create_project(
                alice,
                alice_home,
                title=title,
                status=status,
                rooms=[owner_room] if title == "Soon" else [],
            )
        ordered = [p.title for p in services.search_projects(alice_home)]
        assert ordered == ["Going", "Soon", "Idea one", "Done one", "Dropped"]
        assert [p.title for p in services.search_projects(alice_home, status="done")] == [
            "Done one"
        ]
        assert [p.title for p in services.search_projects(alice_home, room=owner_room.id)] == [
            "Soon"
        ]
        assert [p.title for p in services.search_projects(alice_home, query="idea")] == ["Idea one"]

    def test_the_comparison_lists_cost_duration_priority_and_season(
        self, signed_in: Client, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        shed = services.create_project(
            alice,
            alice_home,
            title="Garden shed",
            priority="high",
            estimated_minutes=3 * 24 * 60,
            season="summer",
            budget=Decimal("1200"),
        )
        page = signed_in.get(
            url("compare", alice_home) + f"?p={living_room_project.id}&p={shed.id}&p=not-an-id"
        ).content.decode()
        for expected in ("Garden shed", "1,200.00", "3 days", "High", "Summer", "800.00"):
            assert expected in page, expected
        alone = signed_in.get(url("compare", alice_home) + f"?p={shed.id}").content.decode()
        assert "Tick at least two" in alone

    def test_the_comparison_never_shows_a_project_of_another_home(
        self,
        signed_in: Client,
        alice_home: Home,
        foreign_project: Project,
        living_room_project: Project,
    ) -> None:
        page = signed_in.get(
            url("compare", alice_home) + f"?p={living_room_project.id}&p={foreign_project.id}"
        ).content.decode()
        assert "Foreign project" not in page

    def test_the_audit_log_names_the_project_and_nothing_else(
        self, alice: User, alice_home: Home, living_room_project: Project, labour_line: BudgetLine
    ) -> None:
        secret = "Secret remark 7788"
        quote = services.create_quote(
            alice, living_room_project, amount=Decimal("123456.78"), note=secret
        )
        services.accept_quote(alice, quote, labour_line)
        services.update_project(alice, living_room_project, goal="Private goal 9911")
        services.update_line(alice, labour_line, label="Private label 4455")
        shown = [
            (e.action, e.detail)
            for e in AuditEvent.objects.filter(home_id=alice_home.id).order_by("created_at", "id")
            if e.action.startswith(("project", "budget_line", "quote"))
        ]
        assert ("project.created", {"title": "Paint the living room"}) in shown
        assert ("quote.accepted", {"title": "Paint the living room"}) in shown
        raw = repr(shown)
        for hidden in (secret, "123456", "Private goal", "Private label"):
            assert hidden not in raw


class TestPhotosAndFiles:
    def test_a_photo_is_rewritten_without_its_location(
        self, alice: User, living_room_project: Project, media_root: Path
    ) -> None:
        stored = services.add_file(
            alice, living_room_project, upload=upload(image_bytes(gps=True), "../../etc/x.jpg")
        )
        assert stored.is_image
        assert stored.name == "x.jpg"
        assert Path(stored.file.path).parent == media_root / "projects" / str(
            living_room_project.home_id
        )
        assert b"Exif" not in Path(stored.file.path).read_bytes()
        assert stored.thumbnail

    def test_a_photo_of_the_project_is_an_image(
        self, alice: User, living_room_project: Project
    ) -> None:
        with pytest.raises(ValidationError):
            services.add_file(
                alice, living_room_project, upload=upload(PDF, "q.pdf", "application/pdf")
            )
        with pytest.raises(ValidationError):
            services.add_file(
                alice, living_room_project, upload=upload(b"MZ\x90\x00 not an image", "x.jpg")
            )
        assert not ProjectFile.objects.exists()

    def test_a_quote_takes_documents_of_the_allow_list_only(
        self, alice: User, living_room_project: Project, quote: Quote
    ) -> None:
        kept = services.add_file(
            alice,
            living_room_project,
            upload=upload(PDF, "quote.pdf", "application/pdf"),
            quote=quote,
        )
        assert (kept.content_type, kept.is_image) == ("application/pdf", False)
        assert not kept.thumbnail
        with pytest.raises(ValidationError):
            services.add_file(
                alice,
                living_room_project,
                upload=upload(b"MZ\x90\x00\x03\x00\x00\x00", "q.exe", "application/octet-stream"),
                quote=quote,
            )

    def test_a_file_of_another_project_is_refused(
        self, alice: User, alice_home: Home, living_room_project: Project, quote: Quote
    ) -> None:
        other = services.create_project(alice, alice_home, title="Other")
        with pytest.raises(ValidationError):
            services.add_file(alice, other, upload=upload(PDF, "q.pdf"), quote=quote)

    def test_the_counts_are_limited(
        self,
        alice: User,
        living_room_project: Project,
        quote: Quote,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(services, "MAX_PHOTOS_PER_PROJECT", 2)
        monkeypatch.setattr(services, "MAX_FILES_PER_QUOTE", 1)
        for _ in range(2):
            services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        with pytest.raises(ValidationError, match="At most 2 photos"):
            services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        services.add_file(alice, living_room_project, upload=upload(PDF, "a.pdf"), quote=quote)
        with pytest.raises(ValidationError, match="At most 1 files"):
            services.add_file(alice, living_room_project, upload=upload(PDF, "b.pdf"), quote=quote)

    def test_the_quotas_of_the_home_apply(
        self, alice: User, living_room_project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            quotas, "limits", lambda: quotas.Limits(bytes=10 * 1024 * 1024, files=1)
        )
        services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        with pytest.raises(ValidationError, match="already holds 1 files"):
            services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        assert ProjectFile.objects.count() == 1

    def test_deleting_a_photo_erases_it_from_the_disk(
        self, alice: User, living_room_project: Project
    ) -> None:
        from django.test import TestCase

        stored = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        paths = [Path(stored.file.path), Path(stored.thumbnail.path)]
        assert all(p.is_file() for p in paths)
        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_file(alice, stored)
        assert not any(p.exists() for p in paths)

    def test_deleting_the_project_erases_its_files(
        self, alice: User, living_room_project: Project, quote: Quote
    ) -> None:
        from django.test import TestCase

        photo = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        document = services.add_file(
            alice, living_room_project, upload=upload(PDF, "q.pdf"), quote=quote
        )
        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_project(alice, living_room_project)
        assert not Path(photo.file.path).exists()
        assert not Path(document.file.path).exists()

    def test_files_are_served_only_to_the_members_and_never_sniffed(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        quote: Quote,
    ) -> None:
        photo = services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        document = services.add_file(
            alice, living_room_project, upload=upload(PDF, "q.pdf"), quote=quote
        )
        shown = signed_in.get(url("file", alice_home, file_id=photo.id))
        assert shown["Content-Type"] == "image/jpeg"
        assert shown["Content-Disposition"].startswith("inline")
        assert shown["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in shown["Content-Security-Policy"]
        download = signed_in.get(url("file", alice_home, file_id=document.id))
        assert download["Content-Disposition"].startswith("attachment")
        assert signed_in.get(url("file-thumbnail", alice_home, file_id=photo.id)).status_code == 200
        assert (
            signed_in.get(url("file-thumbnail", alice_home, file_id=document.id)).status_code == 404
        )

    def test_the_upload_form_and_an_oversized_body(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        added = signed_in.post(
            url("file-add", alice_home, project_id=living_room_project.id),
            {"photo": upload(image_bytes())},
        )
        assert added.status_code == 302
        assert ProjectFile.objects.count() == 1
        huge = signed_in.post(
            url("file-add", alice_home, project_id=living_room_project.id),
            {"photo": upload(image_bytes())},
            CONTENT_LENGTH=str(10**9),
        )
        assert huge.status_code == 413
        assert ProjectFile.objects.count() == 1


class TestEnvelope:
    def test_the_envelope_is_set_per_year_and_compared_with_the_projects_going_on(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        services.update_project(alice, living_room_project, status="in_progress")
        done = services.create_project(
            alice, alice_home, title="Finished", status="done", budget=Decimal("999")
        )
        services.set_envelope(alice, alice_home, year=2026, amount=Decimal("5000"))
        services.set_envelope(alice, alice_home, year=2026, amount=Decimal("6000.50"))
        summary = services.envelope_summary(alice_home, 2026)
        assert summary.envelope == Decimal("6000.50")
        assert summary.planned == Decimal("800.00")  # the finished project is not counted
        assert summary.left == Decimal("5200.50")
        assert done.status == "done"
        assert services.envelope_summary(alice_home, 2025).envelope is None
        assert services.envelope_summary(alice_home, 2025).left is None
        assert services.envelopes_of(alice_home).count() == 1

    def test_the_years_are_bounded(self, alice: User, alice_home: Home) -> None:
        for year in (1999, 2201):
            with pytest.raises(ValidationError):
                services.set_envelope(alice, alice_home, year=year, amount=Decimal("1"))

    def test_the_screen_shows_the_envelope_and_the_form_sets_it(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        year = task_services.today().year
        response = signed_in.post(url("envelope", alice_home), {"year": year, "amount": "4000"})
        assert response.status_code == 302
        html = signed_in.get(url("list", alice_home)).content.decode()
        assert f"Budget envelope {year}" in html
        assert "4,000.00" in html
        assert "3,200.00" in html
        over = signed_in.post(url("envelope", alice_home), {"year": year, "amount": "100"})
        assert over.status_code == 302
        assert "over the envelope" in signed_in.get(url("list", alice_home)).content.decode()


class TestAccess:
    def pages(self, home: Home, project: Project, line: BudgetLine, quote: Quote) -> list[str]:
        return [
            url("list", home),
            url("detail", home, project_id=project.id),
            url("compare", home) + f"?p={project.id}",
            url("line-edit", home, line_id=line.id),
            url("quote-edit", home, quote_id=quote.id),
            url("edit", home, project_id=project.id),
            url("envelope", home),
        ]

    def posts(self, home: Home, project: Project, line: BudgetLine, quote: Quote) -> list[str]:
        return [
            url("create", home),
            url("edit", home, project_id=project.id),
            url("delete", home, project_id=project.id),
            url("task-add", home, project_id=project.id),
            url("line-create", home, project_id=project.id),
            url("line-edit", home, line_id=line.id),
            url("line-delete", home, line_id=line.id),
            url("quote-create", home, project_id=project.id),
            url("quote-edit", home, quote_id=quote.id),
            url("quote-accept", home, quote_id=quote.id),
            url("quote-status", home, quote_id=quote.id),
            url("quote-delete", home, quote_id=quote.id),
            url("file-add", home, project_id=project.id),
            url("envelope", home),
        ]

    def test_a_reader_reads_and_changes_nothing(
        self,
        client: Client,
        reader: User,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        client.force_login(reader)
        for address in self.pages(alice_home, living_room_project, labour_line, quote)[:3]:
            assert client.get(address).status_code == 200, address
        html = client.get(
            url("detail", alice_home, project_id=living_room_project.id)
        ).content.decode()
        for button in ("Edit the project", "Add a quote", "Add a budget line", "Accept the quote"):
            assert button not in html
        before = (Project.objects.count(), BudgetLine.objects.count(), Quote.objects.count())
        for address in self.posts(alice_home, living_room_project, labour_line, quote):
            assert client.post(address, {"title": "x", "label": "x"}).status_code == 403, address
        assert before == (
            Project.objects.count(),
            BudgetLine.objects.count(),
            Quote.objects.count(),
        )
        with pytest.raises(PermissionDenied):
            services.create_project(reader, alice_home, title="No")

    def test_a_member_writes(
        self, client: Client, member: User, alice_home: Home, living_room_project: Project
    ) -> None:
        client.force_login(member)
        assert (
            client.post(
                url("create", alice_home),
                {"title": "By a member", "status": "idea", "priority": "normal"},
            ).status_code
            == 302
        )
        assert Project.objects.filter(title="By a member").exists()

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_another_home_and_the_instance_administrator_see_nothing(
        self,
        request: pytest.FixtureRequest,
        client: Client,
        who: str,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
        quote: Quote,
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        for address in self.pages(alice_home, living_room_project, labour_line, quote):
            assert client.get(address).status_code == 404, address
        for address in self.posts(alice_home, living_room_project, labour_line, quote):
            assert client.post(address, {"title": "x"}).status_code == 404, address
        assert Project.objects.count() == 1
        assert Quote.objects.count() == 1

    def test_an_identifier_of_another_home_is_a_404_under_my_own_home(
        self,
        signed_in: Client,
        alice_home: Home,
        foreign_project: Project,
    ) -> None:
        line = foreign_project.lines.get()
        stolen = foreign_project.quotes.get()
        assert (
            signed_in.get(url("detail", alice_home, project_id=foreign_project.id)).status_code
            == 404
        )
        assert signed_in.get(url("line-edit", alice_home, line_id=line.id)).status_code == 404
        assert (
            signed_in.post(url("quote-delete", alice_home, quote_id=stolen.id)).status_code == 404
        )
        assert (
            signed_in.post(url("delete", alice_home, project_id=foreign_project.id)).status_code
            == 404
        )
        assert Project.objects.filter(id=foreign_project.id).exists()

    def test_a_signed_out_visitor_is_sent_to_sign_in(
        self, client: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        response = client.get(url("detail", alice_home, project_id=living_room_project.id))
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_the_services_check_the_role_themselves(
        self, reader: User, living_room_project: Project, quote: Quote, labour_line: BudgetLine
    ) -> None:
        checks: list[Callable[[], object]] = [
            lambda: services.update_project(reader, living_room_project, title="x"),
            lambda: services.delete_project(reader, living_room_project),
            lambda: services.create_line(reader, living_room_project, label="x"),
            lambda: services.update_line(reader, labour_line, label="x"),
            lambda: services.delete_line(reader, labour_line),
            lambda: services.create_quote(reader, living_room_project),
            lambda: services.accept_quote(reader, quote, labour_line),
            lambda: services.delete_quote(reader, quote),
            lambda: services.add_task(reader, living_room_project, title="x"),
            lambda: services.add_file(reader, living_room_project, upload=upload(image_bytes())),
            lambda: services.set_envelope(reader, living_room_project.home, year=2026, amount=1),
        ]
        for check in checks:
            with pytest.raises(PermissionDenied):
                check()

    def test_the_navigation_marks_projects(self, signed_in: Client, alice_home: Home) -> None:
        html = signed_in.get(url("list", alice_home)).content.decode()
        assert re.search(
            r'class="nav-link"[^>]*aria-current="page">\s*<svg.*?</svg>\s*Projects', html, re.S
        )


class TestWeb:
    def test_the_entry_leads_to_the_only_home(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.get(reverse("projects"))
        assert response.status_code == 302
        assert response["Location"] == url("list", alice_home)

    def test_the_entry_asks_when_there_are_several_homes(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        from housecairn.homes import services as home_services

        home_services.create_home(alice, name="Holiday flat")
        assert "Choose the home" in signed_in.get(reverse("projects")).content.decode()

    def test_create_edit_and_delete_from_the_screens(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        created = signed_in.post(
            url("create", alice_home),
            {
                "title": "Redo the hall",
                "goal": "Paint and floor",
                "status": "planned",
                "priority": "high",
                "rooms": [owner_room.id],
                "duration_value": "2",
                "duration_unit": "day",
                "season": "spring",
            },
        )
        assert created.status_code == 302
        project = Project.objects.get(title="Redo the hall")
        assert (project.estimated_minutes, project.season, list(project.rooms.all())) == (
            2 * 1440,
            "spring",
            [owner_room],
        )
        form = signed_in.get(url("edit", alice_home, project_id=project.id)).content.decode()
        assert 'name="duration_value"' in form
        assert 'value="2"' in form
        assert 'name="budget"' not in form
        saved = signed_in.post(
            url("edit", alice_home, project_id=project.id),
            {
                "title": "Redo the hall",
                "status": "in_progress",
                "priority": "normal",
                "duration_unit": "hour",
            },
        )
        assert saved.status_code == 302
        project.refresh_from_db()
        assert (project.status, project.estimated_minutes) == ("in_progress", None)
        assert project.rooms.count() == 0
        asked = signed_in.get(url("delete", alice_home, project_id=project.id))
        assert "Delete Redo the hall?" in asked.content.decode()
        assert Project.objects.filter(id=project.id).exists()
        signed_in.post(url("delete", alice_home, project_id=project.id))
        assert not Project.objects.filter(id=project.id).exists()

    def test_a_form_error_shows_on_the_form(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(
            url("create", alice_home), {"title": "", "status": "idea", "priority": "normal"}
        )
        assert response.status_code == 200
        assert "This field is required" in response.content.decode()
        response = signed_in.post(
            url("create", alice_home),
            {
                "title": "T",
                "status": "idea",
                "priority": "normal",
                "duration_value": "999",
                "duration_unit": "day",
            },
        )
        assert "between a minute and a year" in response.content.decode()
        response = signed_in.post(
            url("create", alice_home),
            {"title": "T", "status": "idea", "priority": "normal", "season": "custom"},
        )
        assert "first and the last month" in response.content.decode()

    def test_filters_at_the_head_of_the_list(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        services.create_project(alice, alice_home, title="Alpha shed", status="idea")
        services.create_project(
            alice, alice_home, title="Beta roof", status="in_progress", priority="high"
        )
        page = signed_in.get(url("list", alice_home) + "?status=in_progress").content.decode()
        assert "Beta roof" in page
        assert "Alpha shed" not in page
        page = signed_in.get(url("list", alice_home) + "?view=ideas&q=alpha").content.decode()
        assert "Alpha shed" in page
        assert "Beta roof" not in page
        page = signed_in.get(url("list", alice_home) + "?q=zzz").content.decode()
        assert "No project matches" in page
        page = signed_in.get(url("list", alice_home) + "?status=nonsense&room=x").content.decode()
        assert "Beta roof" in page
        # The tabs: what is going on first, the ideas apart.
        listing = signed_in.get(url("list", alice_home)).content.decode()
        assert "Beta roof" in listing
        assert "Alpha shed" not in listing
        ideas = signed_in.get(url("list", alice_home) + "?view=ideas").content.decode()
        assert "Alpha shed" in ideas
        assert "Beta roof" not in ideas

    def test_the_empty_list_explains_itself(self, signed_in: Client, alice_home: Home) -> None:
        assert "No project yet" in signed_in.get(url("list", alice_home)).content.decode()

    def test_attaching_an_existing_task_from_the_page(
        self, signed_in: Client, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        task = task_services.create_task(alice, alice_home, title="Buy brushes")
        page = signed_in.get(
            url("detail", alice_home, project_id=living_room_project.id)
        ).content.decode()
        assert "Put an existing task in the project" in page
        assert "Buy brushes" in page
        signed_in.post(
            url("task-attach", alice_home, project_id=living_room_project.id), {"task": task.id}
        )
        assert services.project_of_task(task) == living_room_project
        again = signed_in.post(
            url("task-attach", alice_home, project_id=living_room_project.id),
            {"task": task.id},
            follow=True,
        )
        assert "Choose a task that is in no project yet" in again.content.decode()
        signed_in.post(
            url("task-detach", alice_home, project_id=living_room_project.id, task_id=task.id)
        )
        assert services.project_of_task(task) is None

    def test_the_budget_table_is_readable_without_colour(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        html = signed_in.get(
            url("detail", alice_home, project_id=living_room_project.id)
        ).content.decode()
        assert html.count('scope="col"') >= 5
        assert 'scope="row"' in html
        assert "<caption" in html

    def test_money_is_formatted_exactly_in_both_languages(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        project = services.create_project(alice, alice_home, title="Palace", budget=MAX)
        english = signed_in.get(url("detail", alice_home, project_id=project.id)).content.decode()
        assert "9,999,999,999.99\u00a0EUR" in english
        french = signed_in.get(
            url("detail", alice_home, project_id=project.id), headers={"accept-language": "fr"}
        ).content.decode()
        assert re.search(r"9\W999\W999\W999,99\WEUR", french)
        assert "Prévu" in french
