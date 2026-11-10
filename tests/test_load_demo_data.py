"""`manage.py load_demo_data`: a fictional home for screenshots and demonstrations."""

import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from housecairn.accounts.models import User
from housecairn.homes.management.commands.load_demo_data import load
from housecairn.homes.models import Home, Membership, Role
from housecairn.projects.models import BudgetLine, Project
from housecairn.rooms.models import Room
from housecairn.tasks.models import Occurrence, Task

pytestmark = pytest.mark.django_db


def _names(home: Home) -> tuple[list[str], list[str], list[str]]:
    rooms = list(Room.objects.filter(home=home).order_by("position").values_list("name", flat=True))
    tasks = sorted(Task.objects.filter(home=home).values_list("title", flat=True))
    projects = sorted(Project.objects.filter(home=home).values_list("title", flat=True))
    return rooms, tasks, projects


def test_the_english_home_has_rooms_tasks_and_projects(alice: User) -> None:
    out = StringIO()
    call_command("load_demo_data", "--owner", "ALICE@example.com", stdout=out)
    home = Home.objects.get(name="Example house")
    assert out.getvalue().startswith("Example house (")
    rooms, tasks, projects = _names(home)
    assert rooms == ["Living room", "Kitchen", "Bathroom", "Hallway", "Utility room", "Garden"]
    assert "Test the smoke detector" in tasks
    assert len(tasks) == 6
    assert projects == ["Redo the bathroom", "Repaint the living room"]
    assert Membership.objects.get(home=home, user=alice).role == Role.OWNER
    planned = sorted(BudgetLine.objects.filter(home=home).values_list("planned", flat=True))
    assert [str(p) for p in planned] == ["240.00", "650.00"]


def test_the_french_home_has_french_names(alice: User) -> None:
    call_command(
        "load_demo_data", "--owner", "alice@example.com", "--language", "fr", stdout=StringIO()
    )
    home = Home.objects.get(name="Maison d'exemple")
    rooms, tasks, projects = _names(home)
    assert rooms == ["Salon", "Cuisine", "Salle de bain", "Entrée", "Buanderie", "Jardin"]
    assert "Tester le détecteur de fumée" in tasks
    assert projects == ["Refaire la salle de bain", "Repeindre le salon"]
    # No English name leaks into the French home.
    english = {"Living room", "Kitchen", "Test the smoke detector", "Repaint the living room"}
    assert not english & {*rooms, *tasks, *projects}


def test_dates_are_relative_to_today(alice: User) -> None:
    today = datetime.date(2030, 3, 15)
    home = load(alice, "en", today)
    due = Occurrence.objects.filter(task__home=home).values_list("task__title", "due_on")
    by_title = dict(due)
    assert by_title["Test the smoke detector"] == today - datetime.timedelta(days=3)
    assert by_title["Descale the kettle"] == today
    assert by_title["Bleed the radiators"] == today + datetime.timedelta(days=20)


def test_an_unknown_account_is_refused(db: None) -> None:
    with pytest.raises(CommandError, match="No account"):
        call_command("load_demo_data", "--owner", "nobody@example.com")
    assert not Home.objects.exists()


def test_a_second_run_in_the_same_language_is_refused(alice: User) -> None:
    call_command("load_demo_data", "--owner", "alice@example.com", stdout=StringIO())
    with pytest.raises(CommandError, match="already has"):
        call_command("load_demo_data", "--owner", "alice@example.com", stdout=StringIO())
    assert Home.objects.filter(name="Example house").count() == 1
    call_command(
        "load_demo_data", "--owner", "alice@example.com", "--language", "fr", stdout=StringIO()
    )
    assert Home.objects.count() == 2


def test_an_unknown_language_is_refused(alice: User) -> None:
    with pytest.raises(CommandError):
        call_command("load_demo_data", "--owner", "alice@example.com", "--language", "de")
