"""A home holding at least one row of every exported table, and readers of its archive."""

import datetime
import io
import json
import zipfile
from decimal import Decimal
from typing import IO, Any

from django.utils import timezone

from housecairn.accounts.models import User
from housecairn.calendar import feeds
from housecairn.events.models import Event
from housecairn.homes import exports
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.labels import services as label_services
from housecairn.projects import services as project_services
from housecairn.projects.models import ProjectLink
from housecairn.reports import services as report_services
from housecairn.rooms import services as room_services
from housecairn.stock import services as stock_services
from housecairn.tasks import services as task_services
from housecairn.tasks.models import TaskMaterial
from tests.rooms_support import image_bytes, upload

NO_DELIVERY = home_services.Delivery()
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def export_data(archive: zipfile.ZipFile | IO[bytes] | bytes) -> dict[str, Any]:
    """Every section of the archive in one dictionary, with `home` and `people`."""
    if isinstance(archive, bytes):
        archive = io.BytesIO(archive)
    zipped = archive if isinstance(archive, zipfile.ZipFile) else zipfile.ZipFile(archive)
    manifest = json.loads(zipped.read(exports.MANIFEST))
    data: dict[str, Any] = {"manifest": manifest}
    for app in manifest["apps"]:
        document = json.loads(zipped.read(f"data/{app}.json"))
        data.update(document["sections"])
        if app == "homes":
            data["home"] = document["home"]
            data["people"] = document["people"]
    return data


def archive_bytes(home: Home) -> bytes:
    archive, _name = exports.build_archive(home)
    return archive.read()


def fill_home(owner: User, member: User, home: Home) -> dict[str, Any]:
    """Create one row of every table a home holds, through the services where they exist."""
    room = room_services.create_room(
        owner, home, name="Kitchen", kind="kitchen", notes="North side"
    )
    room_services.update_room(
        owner, room, paint_colour="Sage", paint_brand="Acme", floor_covering="Tiles"
    )
    other_room = room_services.create_room(owner, home, name="Hall")
    item = room_services.create_item(
        owner,
        room,
        name="Boiler",
        brand="Acme",
        model="B-2",
        serial_number="SN-1",
        installed_on=datetime.date(2020, 5, 1),
        warranty_ends_on=datetime.date(2030, 5, 1),
        links=[{"label": "Manual", "url": "https://example.com/manual"}],
    )
    photo = room_services.add_photo(
        owner, upload=upload(image_bytes()), room=room, caption="Before"
    )
    room_services.add_photo(owner, upload=upload(image_bytes("PNG")), item=item)
    article = stock_services.create_article(
        owner,
        home,
        name="Filter",
        unit="piece",
        threshold=Decimal("2"),
        compatible_items=[item],
        rooms=[room, other_room],
        label=upload(image_bytes()),
    )
    room_services.update_room(owner, other_room, paint_article=article)
    stock_services.create_supplier(
        owner, article, name="Shop", url="https://example.com/shop", last_price=Decimal("12.50")
    )
    stock_services.record_movement(
        owner, article, kind="entry", quantity=Decimal("5"), note="Bought"
    )
    contractor = task_services.create_contractor(
        owner, home, name="Plumber Ltd", trade="plumber", phone="+33 1 23 45 67 89"
    )
    task = task_services.create_task(
        owner,
        home,
        title="Service the boiler",
        room=room,
        item=item,
        assignee=member,
        contractor=contractor,
        labour_budget=Decimal("90.00"),
        repeat_mode="fixed",
        repeat_unit="year",
        repeat_interval=1,
        due_on=datetime.date(2026, 10, 1),
    )
    TaskMaterial.objects.create(home=home, task=task, article=article, quantity=Decimal("1"))
    occurrence = task.occurrences.get()
    closing = task_services.complete(
        member, occurrence, on=datetime.date(2026, 10, 2), actual_cost=Decimal("95.50"), note="Done"
    )
    task_services.add_attachment(owner, task, upload=upload(image_bytes()), name="Plate")
    task_services.add_attachment(
        owner,
        task,
        occurrence=occurrence,
        upload=upload(PDF, "bill.pdf", "application/pdf"),
        name="Bill",
    )
    project = project_services.create_project(
        owner, home, title="Paint the hall", goal="Brighter", rooms=[other_room]
    )
    line = project_services.create_line(
        owner, project, label="Paint", nature="material", planned=Decimal("150.00")
    )
    quote = project_services.create_quote(
        owner,
        project,
        contractor=contractor,
        amount=Decimal("1250.50"),
        budget_line=line,
        status="accepted",
    )
    project_services.add_file(owner, project, upload=upload(image_bytes()))
    project_services.add_file(
        owner, project, quote=quote, upload=upload(PDF, "quote.pdf", "application/pdf")
    )
    ProjectLink.objects.create(
        home=home, project=project, url="https://example.com/idea", title="Idea"
    )
    project_services.add_task(owner, project, title="Sand the walls", room=other_room)
    project_services.set_envelope(owner, home, year=2026, amount=Decimal("3000.00"))
    label, _created = label_services.create_label(owner, home, kind="room", target_id=room.id)
    revoked, _created = label_services.create_label(owner, home, kind="item", target_id=item.id)
    label_services.revoke_label(owner, revoked)
    report = report_services.create_report(
        member, home, title="Leak under the sink", room=room, photo=upload(image_bytes())
    )
    Event.objects.create(
        home=home, kind="water-leak", payload={"sensor": "sink"}, received_by=owner
    )
    feeds.create_feed(owner, home)
    home_services.invite(owner, home, email="new@example.com", role="member", delivery=NO_DELIVERY)
    return {
        "room": room,
        "item": item,
        "photo": photo,
        "article": article,
        "task": task,
        "occurrence": occurrence,
        "closing": closing,
        "project": project,
        "label": label,
        "report": report,
        "at": timezone.now(),
    }


def archive_text(archive: zipfile.ZipFile | IO[bytes] | bytes) -> str:
    """Every data document of the archive, as one text (to look for what must not be there)."""
    if isinstance(archive, bytes):
        archive = io.BytesIO(archive)
    zipped = archive if isinstance(archive, zipfile.ZipFile) else zipfile.ZipFile(archive)
    names = [n for n in zipped.namelist() if n.endswith(".json")]
    return "\n".join(zipped.read(n).decode() for n in sorted(names))


def stored_file(instance: Any) -> Any:
    """The file of a row the export would read (`None` when it would leave it out)."""
    section = exports.section_of_model(type(instance))
    assert section is not None
    return exports.stored_path(instance, section.files[0])


def exported_files(home: Home) -> list[str]:
    """The paths of the files the archive of the home holds."""
    _docs, files = exports.documents(home)
    return [f.name for f in files]
