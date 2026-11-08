"""A person in charge is named by their display name, never by their address (docs/adr/0045)."""

from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts import services as account_services
from housecairn.accounts.models import User
from housecairn.homes.models import Home, Membership, Role
from housecairn.tasks import agenda, services
from housecairn.tasks.models import Task
from tests.tasks_fixtures import TODAY

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

ADDRESS = "bob@example.com"


@pytest.fixture
def shared_task(
    alice: User, bob: User, alice_home: Home, add_member: Callable[..., Membership]
) -> Task:
    add_member(alice_home, bob, Role.MEMBER)
    task = services.create_task(
        alice, alice_home, title="Bleed the radiators", assignee=bob, due_on=None
    )
    occurrence = services.open_occurrence_of(task)
    assert occurrence is not None
    services.complete(bob, occurrence)
    services.create_task(alice, alice_home, title="Clean the gutters", assignee=bob, due_on=TODAY)
    return task


def pages(home: Home, task: Task) -> dict[str, str]:
    kwargs = {"home_id": home.id}
    return {
        "today": reverse("tasks:today", kwargs=kwargs),
        "list": reverse("tasks:list", kwargs=kwargs),
        "history": reverse("tasks:history", kwargs=kwargs),
        "history filtered": f"{reverse('tasks:history', kwargs=kwargs)}?person={task.assignee_id}",
        "detail": reverse("tasks:detail", kwargs={**kwargs, "task_id": task.id}),
        "new": reverse("tasks:create", kwargs=kwargs),
        "edit": reverse("tasks:edit", kwargs={**kwargs, "task_id": task.id}),
        "household": reverse("homes:household", kwargs=kwargs),
    }


@pytest.mark.parametrize("display_name", ["Bobby", ""])
def test_the_address_of_a_member_is_on_no_task_page(
    client: Client,
    alice: User,
    bob: User,
    alice_home: Home,
    shared_task: Task,
    display_name: str,
) -> None:
    account_services.set_display_name(bob, display_name)
    alice_prefs = agenda.update_preferences(alice, today_group="person")
    assert alice_prefs.today_group == "person"
    client.force_login(alice)
    shown = display_name or "bob"
    for label, url in pages(alice_home, shared_task).items():
        response = client.get(url)
        assert response.status_code == 200, label
        text = response.text
        assert ADDRESS not in text, label
        if label in {"today", "history", "household", "edit", "new"}:
            assert shown in text, label


def test_the_occurrence_row_of_today_names_the_assignee(
    client: Client, alice: User, bob: User, alice_home: Home, shared_task: Task
) -> None:
    """Grouped as it is by default, Today shows the person on each row, by name."""
    account_services.set_display_name(bob, "Bobby")
    client.force_login(alice)
    assert agenda.preferences_of(alice).today_group != "person"  # the person is on the row
    page = client.get(pages(alice_home, shared_task)["today"]).text
    row = page[page.index("Clean the gutters") :]
    assert "Bobby" in row.split("</li>")[0]
    assert ADDRESS not in page
    assert "bob@" not in page


def test_the_home_of_a_member_names_them_too(
    client: Client, bob: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    client.force_login(bob)
    text = client.get(reverse("my-home")).text
    assert ADDRESS not in text
    assert "Clean the gutters" in text


def test_the_assignee_choice_lists_names(
    client: Client, bob: User, alice: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    client.force_login(alice)
    text = client.get(pages(alice_home, shared_task)["new"]).text
    assert ">Bobby</option>" in text
    assert f">{ADDRESS}</option>" not in text


def test_the_api_names_the_assignee_and_who_closed_it(
    api_client: APIClient, alice: User, bob: User, alice_home: Home, shared_task: Task
) -> None:
    account_services.set_display_name(bob, "Bobby")
    api_client.force_authenticate(alice)
    kwargs = {"home_id": alice_home.id}
    tasks = api_client.get(reverse("api-v1:home-task-list", kwargs=kwargs)).json()["results"]
    assert {t["assignee_name"] for t in tasks} == {"Bobby"}
    rows = api_client.get(reverse("api-v1:home-occurrence-list", kwargs=kwargs)).json()["results"]
    assert {r["assignee_name"] for r in rows} == {"Bobby"}
    assert "Bobby" in {r["completed_by_name"] for r in rows}
    members = api_client.get(reverse("api-v1:home-member-list", kwargs=kwargs)).json()["results"]
    assert {m["user"]["name"] for m in members} == {"alice", "Bobby"}
