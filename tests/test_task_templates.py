"""The library of task templates and the tasks it makes (docs/adr/0049)."""

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from django.test import Client
from django.urls import reverse
from django.utils import translation
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes.models import Home, Role
from housecairn.rooms import services as room_services
from housecairn.tasks import task_templates
from housecairn.tasks.models import RepeatMode, Task

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs" / "_static" / "schemas" / "task-templates.schema.json"


def raw() -> Any:
    return yaml.safe_load(task_templates.LIBRARY.read_text(encoding="utf-8"))


# --- The library -------------------------------------------------------------------------


def test_the_library_follows_its_published_schema() -> None:
    jsonschema.validate(raw(), json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_the_schema_refuses_a_template_without_a_source_or_a_language() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for change in (
        lambda t: t.pop("source"),
        lambda t: t["title"].pop("fr"),
        lambda t: t["source"].update(url="http://example.com"),
        lambda t: t.update(region="FR") or t.pop("note", None),
        lambda t: t["every"].update(unit="fortnight"),
    ):
        broken = raw()
        change(broken["templates"][0])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)


def test_the_library_has_about_twenty_common_templates() -> None:
    found = task_templates.library()
    assert len(found.templates) >= 20
    assert {"smoke-alarm-battery", "boiler-service", "chimney-sweep", "ventilation-vents"} <= {
        t.id for t in found.templates
    }
    assert all(found.of_equipment(e.id) for e in found.equipment)


def test_every_interval_has_its_source_and_a_regional_rule_says_so() -> None:
    for template in task_templates.library().templates:
        assert template.source_url.startswith("https://"), template.id
        assert template.source_title, template.id
        if template.region:
            # A rule of one country is never written as a rule for everyone.
            assert template.note is not None
            assert "Elsewhere" in template.note.en
            assert "Ailleurs" in template.note.fr


def test_the_library_holds_no_secret_and_no_personal_data() -> None:
    text = json.dumps(raw(), ensure_ascii=False)  # the values, not the comments
    assert "@" not in text
    assert not re.search(r"(?i)password|token|secret|api[_-]?key", text)
    assert not re.search(r"\+?\d[\d .-]{8,}\d", text)  # no phone number


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["templates"][0].update(equipment="nothing-like-it"),
        lambda d: d["templates"][0]["title"].pop("fr"),
        lambda d: d["templates"][0]["source"].update(url="http://example.com"),
        lambda d: d["templates"][0].update(region="FR") or d["templates"][0].pop("note", None),
        lambda d: d["templates"][1].update(id=d["templates"][0]["id"]),
        lambda d: d["templates"][0]["every"].update(unit="fortnight"),
        lambda d: d["templates"][0].update(season="monsoon"),
        lambda d: d.update(version=2),
    ],
)
def test_the_code_refuses_a_library_it_cannot_read(change: Callable[[Any], Any]) -> None:
    broken = copy.deepcopy(raw())
    change(broken)
    with pytest.raises((ValueError, KeyError)):
        task_templates.parse(broken)


# --- The tasks it makes --------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(("language", "title"), [("en", "Replace the battery"), ("fr", "Changer")])
def test_a_template_becomes_the_task_it_describes(
    alice: User, alice_home: Home, language: str, title: str
) -> None:
    template = task_templates.library().get("smoke-alarm-battery")
    assert template is not None
    with translation.override(language):
        (task,) = task_templates.add_templates(alice, alice_home, ["smoke-alarm-battery"])
    task.refresh_from_db()
    assert task.title.startswith(title)
    assert (task.repeat_mode, task.repeat_unit, task.repeat_interval) == (
        RepeatMode.AFTER_LAST,
        "year",
        1,
    )
    assert task.estimated_minutes == template.minutes
    assert template.source_url in task.notes
    assert task.occurrences.count() == 1


@pytest.mark.django_db
def test_a_template_keeps_its_season_and_its_regional_note(alice: User, alice_home: Home) -> None:
    with translation.override("fr"):
        (task,) = task_templates.add_templates(alice, alice_home, ["boiler-service"])
    assert task.season == "autumn"
    assert "En France" in task.notes


@pytest.mark.django_db
def test_an_unknown_template_adds_nothing(alice: User, alice_home: Home) -> None:
    with pytest.raises(ValueError, match="no-such"):
        task_templates.add_templates(alice, alice_home, ["smoke-alarm-test", "no-such"])
    assert not Task.objects.filter(home=alice_home).exists()


# --- Screens ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_smoke_alarm_battery_is_added_in_two_steps(alice: User, alice_home: Home) -> None:
    """The criterion of the MVP: from the list of tasks, tick the template, add it."""
    client = Client()
    client.force_login(alice)
    tasks = reverse("tasks:list", kwargs={"home_id": alice_home.id})
    page = reverse("tasks:templates", kwargs={"home_id": alice_home.id})
    assert page.encode() in client.get(tasks).content
    shown = client.get(f"{page}?next={tasks}")
    assert shown.status_code == 200
    assert b'value="smoke-alarm-battery"' in shown.content
    done = client.post(page, {"templates": ["smoke-alarm-battery"], "next": tasks})
    assert done.status_code == 302
    assert done["Location"] == tasks
    assert Task.objects.filter(home=alice_home, title__icontains="battery").count() == 1


@pytest.mark.django_db
def test_the_screen_gives_a_room_and_a_first_date(alice: User, alice_home: Home) -> None:
    room = room_services.create_room(alice, alice_home, name="Hall")
    client = Client()
    client.force_login(alice)
    page = reverse("tasks:templates", kwargs={"home_id": alice_home.id})
    client.post(page, {"templates": ["rcd-test"], "room": str(room.id), "due_on": "2026-12-01"})
    task = Task.objects.get(home=alice_home)
    assert task.room == room
    assert str(task.occurrences.get().due_on) == "2026-12-01"


@pytest.mark.django_db
def test_a_reader_cannot_add_from_a_template(
    alice_home: Home, make_user: Callable[..., User], add_member: Callable[..., Any]
) -> None:
    reader = make_user("reader@example.com")
    add_member(alice_home, reader, Role.READ_ONLY)
    client = Client()
    client.force_login(reader)
    page = reverse("tasks:templates", kwargs={"home_id": alice_home.id})
    assert client.get(page).status_code == 403
    assert client.post(page, {"templates": ["rcd-test"]}).status_code == 403
    assert not Task.objects.filter(home=alice_home).exists()


@pytest.mark.django_db
def test_the_equipment_checked_for_a_new_home_creates_its_tasks(alice: User) -> None:
    client = Client()
    client.force_login(alice)
    response = client.post(
        reverse("homes:create"),
        {
            "name": "Cottage",
            "currency": "EUR",
            "hemisphere": "north",
            "equipment": ["smoke-alarm", "gutters"],
        },
    )
    assert response.status_code == 302
    home = Home.objects.get(name="Cottage")
    expected = {
        t.title.get("en")
        for e in ("smoke-alarm", "gutters")
        for t in task_templates.library().of_equipment(e)
    }
    assert set(Task.objects.filter(home=home).values_list("title", flat=True)) == expected


@pytest.mark.django_db
def test_a_new_home_without_equipment_has_no_task(alice: User) -> None:
    client = Client()
    client.force_login(alice)
    client.post(reverse("homes:create"), {"name": "Flat", "currency": "EUR", "hemisphere": "north"})
    assert not Task.objects.filter(home__name="Flat").exists()


# --- API ---------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_api_lists_the_library_to_any_token(
    api_client: APIClient, alice: User, alice_home: Home
) -> None:
    _token, raw_token = token_services.issue_token(
        alice, name="t", scopes=["read"], homes=[alice_home]
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
    body = api_client.get(reverse("api-v1:task-template-list")).json()
    assert len(body["templates"]) == len(task_templates.library().templates)
    assert body["templates"][0]["title"].keys() == {"en", "fr"}


@pytest.mark.django_db
@pytest.mark.parametrize(("scopes", "status"), [(["read"], 403), (["write"], 201)])
def test_a_token_adds_from_templates_with_the_write_scope(
    api_client: APIClient, alice: User, alice_home: Home, scopes: list[str], status: int
) -> None:
    _token, raw_token = token_services.issue_token(
        alice, name="t", scopes=scopes, homes=[alice_home]
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
    response = api_client.post(
        reverse("api-v1:home-task-from-templates", kwargs={"home_id": alice_home.id}),
        {"templates": ["smoke-alarm-test", "co-alarm-test"]},
    )
    assert response.status_code == status
    assert Task.objects.filter(home=alice_home).count() == (2 if status == 201 else 0)


@pytest.mark.django_db
def test_the_api_refuses_another_home_and_unknown_templates(
    api_client: APIClient, alice: User, alice_home: Home, bob: User, bob_home: Home
) -> None:
    api_client.force_authenticate(alice)
    url = reverse("api-v1:home-task-from-templates", kwargs={"home_id": alice_home.id})
    assert api_client.post(url, {"templates": ["no-such"]}).status_code == 400
    theirs = room_services.create_room(bob, bob_home, name="Theirs")
    refused = api_client.post(url, {"templates": ["rcd-test"], "room": str(theirs.id)})
    assert (refused.status_code, refused.json()) == (
        400,
        {"room": ["This room is not in this home."]},
    )
    other = reverse("api-v1:home-task-from-templates", kwargs={"home_id": bob_home.id})
    assert api_client.post(other, {"templates": ["rcd-test"]}).status_code == 404
    assert not Task.objects.exists()
