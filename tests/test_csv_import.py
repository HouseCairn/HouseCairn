"""Import of CSV tables into a home: preview, then one transaction (docs/adr/0048)."""

import csv
import io
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes import csv_export, csv_import
from housecairn.homes import services as home_services
from housecairn.homes.models import Home, Role
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Contractor, Occurrence, Task
from tests.data_support import fill_home

pytest_plugins = ("tests.rooms_fixtures",)
pytestmark = pytest.mark.django_db

TABLES = ("stock", "rooms", "items", "contractors", "tasks")
# Columns made again by an import, and so left out of the comparison.
MADE_AGAIN = {"id", "created_at", "updated_at", "position", "label_content_type"}


def table(home: Home, name: str) -> str:
    data, _name = csv_export.build_csv(home, csv_export.ENTITIES[name])
    return data.decode("utf-8")


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.removeprefix(csv_export.BOM))))


def names_by_id(home: Home) -> dict[str, str]:
    """Identifier of every row of the importable tables -> its table and name."""
    out: dict[str, str] = {}
    for name in TABLES:
        key = csv_import.entities()[name].key
        for row in rows(table(home, name)):
            out[row["id"]] = f"{name}:{row[key]}"
    return out


def comparable(home: Home, name: str) -> list[dict[str, str]]:
    """The rows of a table, references by name, without what an import makes again."""
    names = names_by_id(home)
    out = []
    for row in rows(table(home, name)):
        out.append({k: names.get(v, v) for k, v in row.items() if k not in MADE_AGAIN})
    return sorted(out, key=lambda r: sorted(r.items()))


def run(actor: User, home: Home, *, confirm: bool, **texts: str) -> csv_import.Report:
    return csv_import.run(actor, home, texts, confirm=confirm)


def counts(home: Home) -> tuple[int, ...]:
    return tuple(
        m._default_manager.filter(home=home).count()
        for m in (Room, Item, Task, Article, Contractor, Occurrence)
    )


@pytest.fixture
def copy(
    media_root: Path,
    alice: User,
    alice_home: Home,
    make_user: Callable[..., User],
    add_member: Callable[..., Any],
) -> Home:
    """A home filled with every table, and an empty one with the same household."""
    member = make_user("member@example.com", display_name="Sam")
    add_member(alice_home, member, Role.MEMBER)
    fill_home(alice, member, alice_home)
    target = home_services.create_home(alice, name="Copy")
    add_member(target, member, Role.MEMBER)
    return target


# --- Round trip --------------------------------------------------------------------------


def test_the_tables_exported_come_back_whole_in_another_home(
    alice: User, alice_home: Home, copy: Home
) -> None:
    texts = {name: table(alice_home, name) for name in TABLES}
    report = csv_import.run(alice, copy, texts, confirm=True)
    assert report.written, report.as_data()
    assert report.refused == 0, report.as_data()
    for name in TABLES:
        assert comparable(copy, name) == comparable(alice_home, name), name
    # The rows are new: the source home keeps its own, untouched.
    assert not Room.objects.filter(home=copy, id__in=Room.objects.filter(home=alice_home)).exists()
    task = Task.objects.get(home=copy, title="Service the boiler")
    assert task.occurrences.get().due_on == task.series_start


def test_a_table_saved_again_by_a_spreadsheet_without_its_mark_comes_back(
    alice: User, alice_home: Home, copy: Home
) -> None:
    text = table(alice_home, "contractors").removeprefix(csv_export.BOM)
    report = run(alice, copy, confirm=True, contractors=text)
    assert report.written
    contractor = Contractor.objects.get(home=copy)
    # The export wrote `'+33 …` so that a spreadsheet does not compute it; the import
    # takes the mark off again.
    assert contractor.phone == "+33 1 23 45 67 89"


@pytest.mark.parametrize(
    "value", ['=HYPERLINK("https://example.com")', "+1+1", "-2+3", "@SUM(A1)", "\tTab"]
)
def test_a_neutralised_formula_is_read_back_as_its_text(
    alice: User, alice_home: Home, value: str
) -> None:
    room = room_services.create_room(alice, alice_home, name="Kitchen", notes=value)
    exported = table(alice_home, "rooms")
    assert rows(exported)[0]["notes"] == "'" + value
    room_services.delete_room(alice, room)
    report = run(alice, alice_home, confirm=True, rooms=exported)
    assert report.written, report.as_data()
    assert Room.objects.get(home=alice_home).notes == value


# --- Nothing before the confirmation, everything or nothing after --------------------------


def test_the_preview_writes_nothing(alice: User, alice_home: Home, copy: Home) -> None:
    texts = {name: table(alice_home, name) for name in TABLES}
    before = counts(copy), AuditEvent.objects.count()
    report = csv_import.run(alice, copy, texts, confirm=False)
    assert report.can_confirm
    assert not report.written
    assert report.accepted == sum(len(rows(t)) for t in texts.values())
    assert (counts(copy), AuditEvent.objects.count()) == before


def test_a_failure_while_writing_writes_nothing(
    alice: User, alice_home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "name\nKitchen\nHall\nAttic\n"
    calls = iter(range(10))
    original = csv_import.entities()["rooms"].create

    def fail_on_the_third(actor: Any, home: Home, values: dict[str, Any]) -> Any:
        if next(calls) == 2:
            raise RuntimeError("disk full")
        return original(actor, home, values)

    monkeypatch.setitem(
        csv_import.REGISTRY,
        "rooms",
        csv_import.ImportEntity(
            "rooms", Room, "name", frozenset({"name"}), fail_on_the_third, label="Rooms"
        ),
    )
    with pytest.raises(RuntimeError):
        run(alice, alice_home, confirm=True, rooms=text)
    assert not Room.objects.filter(home=alice_home).exists()


def test_the_import_is_recorded_once_in_the_audit_log(alice: User, alice_home: Home) -> None:
    run(alice, alice_home, confirm=True, rooms="name\nKitchen\nHall\n")
    event = AuditEvent.objects.get(action="home.imported")
    assert event.home_id == alice_home.id
    assert (event.detail["count"], event.detail["fields"]) == (2, ["rooms"])


# --- Rows refused, rows flagged --------------------------------------------------------------


def test_a_row_already_in_the_home_is_refused_and_never_merged(
    alice: User, alice_home: Home
) -> None:
    room_services.create_room(alice, alice_home, name="Kitchen", notes="Mine")
    exported = table(alice_home, "rooms").replace("Mine", "Theirs")
    report = run(alice, alice_home, confirm=True, rooms=exported)
    assert report.refused == 1
    assert not report.written
    assert "already in this home" in report.files[0].rows[0].errors[0]
    assert Room.objects.get(home=alice_home).notes == "Mine"


def test_an_identifier_twice_in_a_file_is_refused(alice: User, alice_home: Home) -> None:
    key = uuid.uuid4()
    report = run(alice, alice_home, confirm=False, rooms=f"id,name\n{key},A\n{key},B\n")
    assert [r.refused for r in report.files[0].rows] == [False, True]


def test_a_name_already_in_the_home_is_added_with_a_warning(alice: User, alice_home: Home) -> None:
    room_services.create_room(alice, alice_home, name="Kitchen")
    report = run(alice, alice_home, confirm=True, rooms="name\nkitchen\n")
    assert report.written
    assert report.files[0].rows[0].warnings
    assert Room.objects.filter(home=alice_home).count() == 2


def test_a_reference_to_a_row_of_another_home_is_refused(
    alice: User, alice_home: Home, bob: User, bob_home: Home
) -> None:
    theirs = room_services.create_room(bob, bob_home, name="Their kitchen")
    report = run(alice, alice_home, confirm=True, items=f"name,room\nOven,{theirs.id}\n")
    row = report.files[0].rows[0]
    assert row.refused
    assert "not in this home" in row.errors[0]
    assert not Item.objects.filter(home=alice_home).exists()
    # Nor by its name: names are only looked for in this home.
    report = run(alice, alice_home, confirm=True, items="name,room\nOven,Their kitchen\n")
    assert report.files[0].rows[0].refused


def test_the_identifier_of_a_row_of_another_home_gives_a_new_row(
    alice: User, alice_home: Home, bob: User, bob_home: Home
) -> None:
    theirs = room_services.create_room(bob, bob_home, name="Their kitchen", notes="Theirs")
    report = run(alice, alice_home, confirm=True, rooms=f"id,name,notes\n{theirs.id},Mine,Mine\n")
    assert report.written
    mine = Room.objects.get(home=alice_home)
    assert mine.id != theirs.id
    theirs.refresh_from_db()
    assert (theirs.home_id, theirs.notes) == (bob_home.id, "Theirs")


def test_references_between_the_files_of_one_import_resolve(alice: User, alice_home: Home) -> None:
    room_key, item_key = uuid.uuid4(), uuid.uuid4()
    report = run(
        alice,
        alice_home,
        confirm=True,
        rooms=f"id,name\n{room_key},Kitchen\n",
        items=f"id,name,room\n{item_key},Oven,{room_key}\n",
        tasks=f"title,item,series_start\nClean the oven,{item_key},2026-12-01\n",
    )
    assert report.written, report.as_data()
    task = Task.objects.get(home=alice_home)
    assert task.item is not None
    assert task.item.name == "Oven"
    assert task.room is not None
    assert task.room.name == "Kitchen"
    assert task.occurrences.get().due_on.isoformat() == "2026-12-01"


def test_a_row_naming_a_refused_row_is_refused_too(alice: User, alice_home: Home) -> None:
    room_key = uuid.uuid4()
    report = run(
        alice,
        alice_home,
        confirm=False,
        rooms=f"id,name,kind\n{room_key},Kitchen,nowhere\n",
        items=f"name,room\nOven,{room_key}\n",
    )
    assert [f.refused for f in report.files] == [1, 1]
    assert "refused" in report.files[1].rows[0].errors[0]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("name,kind\nKitchen,nowhere\n", "kind"),
        ("name,links\nOven,[[[\n", "links"),
        ("name,installed_on\nOven,10/11/2026\n", "YYYY-MM-DD"),
        ("name,room\nOven,\n", "room"),
    ],
)
def test_a_value_that_is_not_valid_refuses_its_row_with_the_reason(
    alice: User, alice_home: Home, text: str, reason: str
) -> None:
    room_services.create_room(alice, alice_home, name="Kitchen")
    table_name = "rooms" if text.startswith("name,kind") else "items"
    report = run(alice, alice_home, confirm=False, **{table_name: text})
    row = report.files[0].rows[0]
    assert row.refused
    assert reason in " ".join(row.errors)


def test_cells_with_quotes_and_line_breaks_are_kept(alice: User, alice_home: Home) -> None:
    text = 'name,notes\r\n"Kitchen, north","Line one\r\nLine ""two"""\r\n'
    run(alice, alice_home, confirm=True, rooms=text)
    room = Room.objects.get(home=alice_home)
    assert (room.name, room.notes) == ("Kitchen, north", 'Line one\r\nLine "two"')


def test_unknown_columns_are_ignored_and_shown(alice: User, alice_home: Home) -> None:
    report = run(alice, alice_home, confirm=True, rooms="name,colour of the cat\nKitchen,black\n")
    assert report.written
    assert report.files[0].ignored_columns == ["colour of the cat"]


def test_a_person_is_matched_by_display_name_among_the_members(
    alice: User, alice_home: Home, make_user: Callable[..., User], add_member: Callable[..., Any]
) -> None:
    sam = make_user("sam@example.com", display_name="Sam")
    add_member(alice_home, sam, Role.MEMBER)
    make_user("stranger@example.com", display_name="Robin")
    report = run(alice, alice_home, confirm=True, tasks="title,assignee\nA,Sam\nB,Robin\n")
    assert report.written
    assignees = dict(Task.objects.filter(home=alice_home).values_list("title", "assignee"))
    assert assignees == {"A": sam.pk, "B": None}
    assert report.files[0].rows[1].warnings


# --- Files refused -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("kind\nkitchen\n", "missing"),
        ("name;kind\nKitchen;kitchen\n", "semicolons"),  # always commas
        ("name,Name\nA,B\n", "twice"),
        ("", "empty"),
        ('name\n"Kitchen\n', "not a valid CSV"),
        ("name\nKit\x00chen\n", "not a CSV"),
    ],
)
def test_a_file_that_is_not_a_table_is_refused_whole(
    alice: User, alice_home: Home, text: str, reason: str
) -> None:
    report = run(alice, alice_home, confirm=True, rooms=text)
    assert report.error
    assert reason in report.files[0].error
    assert not report.written
    assert not Room.objects.filter(home=alice_home).exists()


def test_a_file_not_in_utf8_is_refused() -> None:
    with pytest.raises(csv_import.ImportRefusedError, match="UTF-8"):
        csv_import.decode("name\nCuisine équipée\n".encode("latin-1"))
    assert csv_import.decode(b"\xef\xbb\xbfname\n") == "name\n"


def test_files_of_too_many_rows_are_refused(
    alice: User, alice_home: Home, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_import, "MAX_ROWS", 3)
    report = run(alice, alice_home, confirm=True, rooms="name\nA\nB\nC\nD\n")
    assert report.error
    assert "more than 3 rows" in report.files[0].error
    assert run(alice, alice_home, confirm=False, rooms="name\nA\nB\nC\n").can_confirm
    # The cap is for the files of one import together.
    report = run(alice, alice_home, confirm=False, rooms="name\nA\nB\n", stock="name\nC\nD\n")
    assert report.error
    assert "more than 3 rows" in report.files[1].error


def test_files_too_large_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csv_import, "MAX_BYTES", 10)
    big = SimpleUploadedFile("rooms.csv", b"name\n" + b"A\n" * 10)
    with pytest.raises(csv_import.ImportRefusedError, match="too large"):
        csv_import.texts_from_uploads({"rooms": big})


# --- Who may import ----------------------------------------------------------------------------


def test_a_reader_cannot_import(
    alice: User, alice_home: Home, make_user: Callable[..., User], add_member: Callable[..., Any]
) -> None:
    reader = make_user("reader@example.com")
    add_member(alice_home, reader, Role.READ_ONLY)
    with pytest.raises(PermissionDenied):
        run(reader, alice_home, confirm=False, rooms="name\nKitchen\n")
    # Refused before any file is read, not only by the services that would write a row:
    # a reader learns nothing of the home from the preview.
    with pytest.raises(PermissionDenied):
        run(reader, alice_home, confirm=False, items="name,room\nOven,Kitchen\n")
    client = Client()
    client.force_login(reader)
    url = reverse("homes:import", kwargs={"home_id": alice_home.id})
    assert client.get(url).status_code == 403
    upload = SimpleUploadedFile("rooms.csv", b"name\nKitchen\n", content_type="text/csv")
    assert client.post(url, {"rooms": upload}).status_code == 403
    assert not Room.objects.filter(home=alice_home).exists()


def test_a_stranger_does_not_see_the_page(alice_home: Home, bob: User) -> None:
    client = Client()
    client.force_login(bob)
    url = reverse("homes:import", kwargs={"home_id": alice_home.id})
    assert client.get(url).status_code == 404


def _api_import(client: APIClient, home: Home, **data: Any) -> Any:
    files = {
        name: SimpleUploadedFile(f"{name}.csv", text.encode(), content_type="text/csv")
        for name, text in data.pop("files").items()
    }
    return client.post(
        reverse("api-v1:home-import", kwargs={"home_id": home.id}),
        {**files, **data},
        format="multipart",
    )


@pytest.mark.parametrize(("scopes", "status"), [(["read"], 403), (["write"], 201)])
def test_a_token_imports_with_the_write_scope_only(
    api_client: APIClient, alice: User, alice_home: Home, scopes: list[str], status: int
) -> None:
    _token, raw = token_services.issue_token(alice, name="t", scopes=scopes, homes=[alice_home])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = _api_import(
        api_client, alice_home, files={"rooms": "name\nKitchen\n"}, confirm="true"
    )
    assert response.status_code == status
    assert Room.objects.filter(home=alice_home).exists() is (status == 201)


def test_a_token_of_another_home_cannot_import_here(
    api_client: APIClient,
    alice: User,
    alice_home: Home,
    bob_home: Home,
    add_member: Callable[..., Any],
) -> None:
    add_member(bob_home, alice, Role.OWNER)
    _token, raw = token_services.issue_token(alice, name="t", scopes=["write"], homes=[bob_home])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    response = _api_import(
        api_client, alice_home, files={"rooms": "name\nKitchen\n"}, confirm="true"
    )
    assert response.status_code == 404
    assert not Room.objects.filter(home=alice_home).exists()


def test_the_api_previews_by_default_and_reports_each_row(
    api_client: APIClient, alice: User, alice_home: Home
) -> None:
    api_client.force_authenticate(alice)
    response = _api_import(api_client, alice_home, files={"rooms": "name,kind\nA,kitchen\nB,x\n"})
    assert response.status_code == 200
    body = response.json()
    assert (body["written"], body["accepted"], body["refused"]) == (False, 1, 1)
    assert body["files"][0]["rows"][1]["status"] == "refused"
    assert not Room.objects.filter(home=alice_home).exists()
    refused = _api_import(api_client, alice_home, files={"rooms": "kind\nkitchen\n"})
    assert refused.status_code == 400


# --- The screen --------------------------------------------------------------------------------


def test_the_screen_previews_then_writes_on_confirmation(alice: User, alice_home: Home) -> None:
    client = Client()
    client.force_login(alice)
    url = reverse("homes:import", kwargs={"home_id": alice_home.id})
    home_page = reverse("homes:detail", kwargs={"home_id": alice_home.id})
    page = client.get(f"{url}?next={home_page}")
    assert page.status_code == 200
    upload = SimpleUploadedFile(
        "rooms.csv", "\ufeffname,kind\r\nKitchen,kitchen\r\nAttic,x\r\n".encode(), "text/csv"
    )
    preview = client.post(url, {"rooms": upload, "next": home_page})
    assert preview.status_code == 200
    assert not Room.objects.filter(home=alice_home).exists()
    text = preview.context["report"].files[0].text
    assert b'name="confirm"' in preview.content
    assert b"Attic" in preview.content
    done = client.post(url, {"text_rooms": text, "confirm": "1", "next": home_page})
    assert done.status_code == 302
    assert done["Location"] == home_page
    assert list(Room.objects.filter(home=alice_home).values_list("name", flat=True)) == ["Kitchen"]


def test_the_home_page_offers_the_import_to_who_may_write(
    alice: User, alice_home: Home, make_user: Callable[..., User], add_member: Callable[..., Any]
) -> None:
    reader = make_user("reader@example.com")
    add_member(alice_home, reader, Role.READ_ONLY)
    client = Client()
    page = reverse("homes:detail", kwargs={"home_id": alice_home.id})
    target = reverse("homes:import", kwargs={"home_id": alice_home.id})
    client.force_login(alice)
    assert target.encode() in client.get(page).content
    client.force_login(reader)
    assert target.encode() not in client.get(page).content


def test_the_tasks_of_an_import_are_planned(alice: User, alice_home: Home) -> None:
    run(alice, alice_home, confirm=True, tasks="title,series_start\nCheck the alarm,2026-12-01\n")
    task = Task.objects.get(home=alice_home)
    assert task_services.open_occurrence_of(task) is not None
