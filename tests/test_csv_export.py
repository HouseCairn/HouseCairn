"""One table of a home as CSV, safe to open in a spreadsheet (docs/adr/0048)."""

import csv
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import csv_export, exports
from housecairn.homes.models import Home, Role
from housecairn.rooms import services as room_services
from housecairn.tasks import services as task_services
from tests.data_support import fill_home

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db

HOSTILE = ['=HYPERLINK("https://example.com")', "+1+1", "-2+3", "@SUM(A1)", "\tTab", "\rReturn"]


def read(response: Any) -> list[dict[str, str]]:
    body = response.content
    assert body.startswith(b"\xef\xbb\xbf")  # the byte order mark Excel needs for UTF-8
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))


@pytest.fixture
def full(
    media_root: Path,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> User:
    member = make_user("member@example.com", display_name="Sam")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    return member


@pytest.mark.parametrize("value", HOSTILE)
def test_a_cell_that_would_run_as_a_formula_is_neutralised(value: str) -> None:
    assert csv_export.neutralise(value) == "'" + value
    assert csv_export.neutralise("Kitchen") == "Kitchen"
    assert csv_export.neutralise("") == ""


def test_every_table_lists_a_known_section() -> None:
    names = {s.name for _a, s in exports.all_sections()}
    assert {e.section for e in csv_export.ENTITIES.values()} <= names
    assert set(csv_export.ENTITIES) == {
        "rooms",
        "items",
        "tasks",
        "history",
        "stock",
        "contractors",
        "reports",
    }


def test_hostile_names_come_out_inert(client: Client, alice: User, alice_home: Home) -> None:
    for value in HOSTILE:
        room_services.create_room(alice, alice_home, name=value)
    client.force_login(alice)
    response = client.get(
        reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": "rooms"})
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment" in response["Content-Disposition"]
    names = [row["name"] for row in read(response)]
    assert len(names) == len(HOSTILE)
    # The service trims spaces and tabs around a name; whatever is left starts inert.
    assert not [n for n in names if n.startswith(csv_export.FORMULA_STARTS)]
    for value in HOSTILE[:4]:
        assert "'" + value in names


def test_people_by_display_name_amounts_with_a_point_and_the_currency(
    client: Client, alice: User, alice_home: Home, full: User
) -> None:
    client.force_login(alice)
    url = reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": "tasks"})
    rows = {row["title"]: row for row in read(client.get(url))}
    task = rows["Service the boiler"]
    assert task["assignee"] == "Sam"
    assert "member@example.com" not in client.get(url).content.decode()
    assert task["labour_budget"] == "90.00"
    assert task["currency"] == "EUR"
    history = read(
        client.get(
            reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": "history"})
        )
    )
    done = next(r for r in history if r["status"] == "done")
    assert (done["actual_cost"], done["currency"], done["completed_by"]) == ("95.50", "EUR", "Sam")


@pytest.mark.parametrize("entity", sorted(csv_export.ENTITIES))
def test_every_table_downloads_for_a_reader_with_its_rows(
    client: Client,
    alice_home: Home,
    full: User,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
    entity: str,
) -> None:
    reader = make_user("reader@example.com")
    add_member(alice_home, reader, Role.READ_ONLY)
    client.force_login(reader)
    response = client.get(
        reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": entity})
    )
    assert response.status_code == 200
    assert read(response)


def test_a_deleted_task_and_its_history_are_left_out(
    client: Client, alice: User, alice_home: Home
) -> None:
    task = task_services.create_task(alice, alice_home, title="Gone")
    task_services.delete_task(alice, task)
    client.force_login(alice)
    for entity in ("tasks", "history"):
        response = client.get(
            reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": entity})
        )
        assert read(response) == []


def test_a_stranger_and_an_unknown_table_get_404(
    client: Client, bob: User, alice: User, alice_home: Home
) -> None:
    client.force_login(bob)
    url = reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": "rooms"})
    assert client.get(url).status_code == 404
    client.force_login(alice)
    assert (
        client.get(
            reverse("homes:export-csv", kwargs={"home_id": alice_home.id, "entity": "accounts"})
        ).status_code
        == 404
    )


def test_a_token_reads_the_tables_of_its_homes_only(
    api_client: APIClient,
    alice: User,
    alice_home: Home,
    bob: User,
    bob_home: Home,
    add_member: Callable[..., Any],
) -> None:
    add_member(bob_home, alice, Role.OWNER)
    room_services.create_room(alice, alice_home, name="Kitchen")
    _token, raw = token_services.issue_token(
        alice, name="read", scopes=["read"], homes=[alice_home]
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    mine = api_client.get(
        reverse("api-v1:home-export-csv", kwargs={"home_id": alice_home.id, "entity": "rooms"})
    )
    assert mine.status_code == 200
    assert [r["name"] for r in read(mine)] == ["Kitchen"]
    other = api_client.get(
        reverse("api-v1:home-export-csv", kwargs={"home_id": bob_home.id, "entity": "rooms"})
    )
    assert other.status_code == 404
    # The whole archive stays a signed-in owner's: no token, even on its own home.
    assert (
        api_client.post(
            reverse("api-v1:home-export", kwargs={"home_id": alice_home.id})
        ).status_code
        == 403
    )
