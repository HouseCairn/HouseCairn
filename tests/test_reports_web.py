"""Screens of reports: the form, the lists, the buttons, Today (docs/adr/0047)."""

import re
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home, Role
from housecairn.reports import services
from housecairn.reports.forms import ReportForm
from housecairn.reports.models import Report, ReportStatus
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article
from housecairn.tasks.models import Task
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root")]


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"reports:{name}", kwargs={"home_id": home.id, **kwargs})


def signed(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def reported(reader: User, alice_home: Home) -> Report:
    return services.create_report(reader, alice_home, title="The tap drips")


class TestForm:
    def test_it_has_two_fields_and_a_photo(
        self, client: Client, reader: User, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        body = signed(client, reader).get(url("create", alice_home)).content.decode()
        assert 'name="title"' in body
        assert 'name="place"' in body
        assert 'name="photo"' in body
        assert f'value="room:{owner_room.id}"' in body
        assert f'value="item:{owner_item.id}"' in body
        assert 'accept="image/jpeg,image/png,image/webp"' in body
        assert 'enctype="multipart/form-data"' in body

    @pytest.mark.parametrize("kind", ["room", "item", "article"])
    def test_coming_from_an_object_fills_in_where(
        self,
        client: Client,
        reader: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        article: Article,
        kind: str,
    ) -> None:
        target = {"room": owner_room, "item": owner_item, "article": article}[kind]
        body = signed(client, reader).get(url("create", alice_home), {kind: str(target.id)})
        selected = f'<option value="{kind}:{target.id}" selected>'
        assert selected in body.content.decode()

    def test_a_bad_where_in_the_address_is_ignored(
        self, client: Client, reader: User, alice_home: Home, foreign_item: Item
    ) -> None:
        for query in ({"room": "nonsense"}, {"item": str(foreign_item.id)}, {"article": ""}):
            response = signed(client, reader).get(url("create", alice_home), query)
            assert response.status_code == 200
            select = response.content.decode().split('name="place"')[1].split("</select>")[0]
            assert set(re.findall(r'<option value="([^"]*)" selected>', select)) <= {""}

    def test_a_reader_sends_a_report_with_a_photo(
        self, client: Client, reader: User, alice_home: Home, owner_item: Item
    ) -> None:
        response = signed(client, reader).post(
            url("create", alice_home),
            {
                "title": "The boiler is noisy",
                "place": f"item:{owner_item.id}",
                "photo": upload(image_bytes("PNG"), "x.png", "image/png"),
            },
        )
        report = Report.objects.get()
        assert response.status_code == 302
        assert response["Location"] == url("detail", alice_home, report_id=report.id)
        assert (report.title, report.item, report.reporter) == (
            "The boiler is noisy",
            owner_item,
            reader,
        )
        assert report.has_photo

    def test_what_is_wrong_is_required_and_the_form_comes_back(
        self, client: Client, reader: User, alice_home: Home
    ) -> None:
        response = signed(client, reader).post(url("create", alice_home), {"title": " "})
        assert response.status_code == 200
        assert Report.objects.count() == 0
        assert "This field is required" in response.content.decode()

    def test_a_place_of_another_home_is_not_in_the_list_and_not_accepted(
        self, client: Client, reader: User, alice_home: Home, foreign_item: Item
    ) -> None:
        response = signed(client, reader).post(
            url("create", alice_home), {"title": "x", "place": f"item:{foreign_item.id}"}
        )
        assert response.status_code == 200
        assert Report.objects.count() == 0
        assert "Select a valid choice" in response.content.decode()

    def test_a_bad_file_comes_back_with_a_message(
        self, client: Client, reader: User, alice_home: Home
    ) -> None:
        response = signed(client, reader).post(
            url("create", alice_home),
            {"title": "x", "photo": upload(b"%PDF-1.4 hi", "x.jpg", "image/jpeg")},
        )
        assert response.status_code == 200
        assert Report.objects.count() == 0
        assert "not a valid JPEG, PNG or WebP" in response.content.decode()

    def test_an_oversized_body_is_refused_before_it_is_read(
        self, client: Client, reader: User, alice_home: Home
    ) -> None:
        response = signed(client, reader).post(
            url("create", alice_home),
            {"title": "x"},
            headers={"content-length": str(500 * 1024 * 1024)},
        )
        assert response.status_code == 413

    def test_a_person_outside_the_home_gets_a_404(
        self, client: Client, bob: User, alice_home: Home
    ) -> None:
        signed(client, bob)
        assert client.get(url("create", alice_home)).status_code == 404
        assert client.post(url("create", alice_home), {"title": "x"}).status_code == 404
        assert Report.objects.count() == 0

    def test_a_signed_out_person_is_sent_to_sign_in(self, client: Client, alice_home: Home) -> None:
        response = client.get(url("create", alice_home))
        assert response.status_code == 302
        assert "login" in response["Location"]


class TestLists:
    def test_a_reader_sees_my_reports_with_theirs_only(
        self, client: Client, reader: User, member: User, alice_home: Home, reported: Report
    ) -> None:
        services.create_report(member, alice_home, title="Somebody else's")
        body = signed(client, reader).get(url("list", alice_home)).content.decode()
        assert "My reports" in body
        assert "The tap drips" in body
        assert "Somebody else" not in body
        assert "Reported by" not in body

    def test_a_writer_sees_the_open_ones_first_and_can_filter(
        self,
        client: Client,
        alice: User,
        member: User,
        alice_home: Home,
        reported: Report,
    ) -> None:
        other = services.create_report(member, alice_home, title="A closed one")
        services.close_report(alice, other, resolution="resolved")
        signed(client, alice)
        opened = client.get(url("list", alice_home)).content.decode()
        assert "The tap drips" in opened
        assert "A closed one" not in opened
        closed = client.get(url("list", alice_home), {"show": "closed"}).content.decode()
        assert "A closed one" in closed
        assert "The tap drips" not in closed
        everything = client.get(url("list", alice_home), {"show": "all"}).content.decode()
        assert "A closed one" in everything
        assert "The tap drips" in everything
        mine = client.get(url("list", alice_home), {"show": "mine"}).content.decode()
        assert "The tap drips" not in mine
        fallback = client.get(url("list", alice_home), {"show": "bogus", "page": "x"})
        assert fallback.status_code == 200
        assert "The tap drips" in fallback.content.decode()

    def test_the_reporter_is_named_to_the_people_who_write_never_by_address(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        body = signed(client, alice).get(url("list", alice_home)).content.decode()
        assert "· reader<" in body
        assert "reader@example.com" not in body
        detail = client.get(url("detail", alice_home, report_id=reported.id)).content.decode()
        assert "reader@example.com" not in detail

    def test_a_name_with_a_filler_character_does_not_pass_for_another(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        make_user: Callable[..., User],
        add_member: Callable[..., object],
    ) -> None:
        faked = make_user("faked@example.com", display_name="Alice\u3164")
        add_member(alice_home, faked, Role.READ_ONLY)
        report = services.create_report(faked, alice_home, title="x")
        signed(client, alice)
        assert "· Alice<" in client.get(url("list", alice_home)).content.decode()
        detail = client.get(url("detail", alice_home, report_id=report.id)).content.decode()
        assert "Alice\u3164" not in detail

    def test_two_people_of_one_name_are_told_apart_in_the_list(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        make_user: Callable[..., User],
        add_member: Callable[..., object],
    ) -> None:
        for email, name in (("first@example.com", "Sam"), ("second@example.com", "Sam\u3164")):
            person = make_user(email, display_name=name)
            add_member(alice_home, person, Role.READ_ONLY)
            services.create_report(person, alice_home, title="x")
        body = signed(client, alice).get(url("list", alice_home)).content.decode()
        assert "Sam (first@example.com)" in body
        assert "Sam (second@example.com)" in body

    def test_the_form_alone_offers_the_places_of_this_home_only(
        self, alice_home: Home, owner_room: Room, foreign_item: Item, foreign_article: Article
    ) -> None:
        # The service refuses a foreign place too; this is the layer of the screen on its own.
        form = ReportForm(places=services.places_for_forms(alice_home))
        offered = {
            value
            for _group, options in form.fields["place"].choices
            if _group
            for value, _l in options
        }  # type: ignore[attr-defined]
        assert offered == {f"room:{owner_room.id}"}
        assert f"item:{foreign_item.id}" not in offered
        assert f"article:{foreign_article.id}" not in offered

    def test_an_instance_administrator_who_is_not_a_member_gets_nothing(
        self, client: Client, alice_home: Home, site_admin: User, reported: Report
    ) -> None:
        signed(client, site_admin)
        for address in (
            url("list", alice_home),
            url("create", alice_home),
            url("detail", alice_home, report_id=reported.id),
            url("photo", alice_home, report_id=reported.id),
        ):
            assert client.get(address).status_code == 404, address
        for name in ("to-task", "close", "reopen"):
            assert client.post(url(name, alice_home, report_id=reported.id)).status_code == 404
        assert client.post(url("create", alice_home), {"title": "x"}).status_code == 404
        assert Report.objects.count() == 1
        reported.refresh_from_db()
        assert reported.status == ReportStatus.OPEN

    def test_the_list_is_paged(self, client: Client, alice: User, alice_home: Home) -> None:
        for i in range(35):
            Report.objects.create(home=alice_home, reporter=alice, title=f"r{i}")
        signed(client, alice)
        first = client.get(url("list", alice_home), {"show": "all"}).content.decode()
        second = client.get(url("list", alice_home), {"show": "all", "page": "2"}).content.decode()
        assert "page=2" in first
        assert "Previous" in second


class TestDetail:
    def test_the_reporter_sees_theirs_and_a_writer_sees_it_with_the_buttons(
        self, client: Client, alice: User, reader: User, alice_home: Home, reported: Report
    ) -> None:
        address = url("detail", alice_home, report_id=reported.id)
        body = signed(client, reader).get(address).content.decode()
        assert "The tap drips" in body
        for button in ("Make it a task", "Mark as resolved", "Close without action"):
            assert button not in body
        body = signed(client, alice).get(address).content.decode()
        for button in ("Make it a task", "Mark as resolved", "Close without action"):
            assert button in body
        assert "Reopen" not in body

    def test_another_reader_cannot_open_someone_elses_report(
        self,
        client: Client,
        alice_home: Home,
        reported: Report,
        make_user: Callable[..., User],
        add_member: Callable[..., object],
    ) -> None:
        other = make_user("other@example.com")
        add_member(alice_home, other, Role.READ_ONLY)
        address = url("detail", alice_home, report_id=reported.id)
        assert signed(client, other).get(address).status_code == 404
        assert client.get(url("photo", alice_home, report_id=reported.id)).status_code == 404
        assert client.post(url("to-task", alice_home, report_id=reported.id)).status_code == 404

    def test_the_photo_is_served_to_those_who_may_see_the_report_only(
        self, client: Client, alice: User, reader: User, bob: User, alice_home: Home
    ) -> None:
        report = services.create_report(
            reader, alice_home, title="Crack", photo=upload(image_bytes("JPEG", (300, 200)))
        )
        for name, kind in (("photo", "image/jpeg"), ("photo-thumbnail", "image/jpeg")):
            address = url(name, alice_home, report_id=report.id)
            for who in (reader, alice):
                response = signed(client, who).get(address)
                assert response.status_code == 200
                assert response["Content-Type"] == kind
                assert response["X-Content-Type-Options"] == "nosniff"
                assert "sandbox" in response["Content-Security-Policy"]
                assert response["Cache-Control"].startswith("private")
                assert str(report.id) in response["Content-Disposition"]
                assert "Crack" not in response["Content-Disposition"]
                assert b"".join(response.streaming_content)
            assert signed(client, bob).get(address).status_code == 404

    def test_a_report_without_photo_has_no_photo_page(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        signed(client, alice)
        assert client.get(url("photo", alice_home, report_id=reported.id)).status_code == 404
        assert (
            client.get(url("photo-thumbnail", alice_home, report_id=reported.id)).status_code == 404
        )

    def test_where_leads_to_the_object(
        self, client: Client, alice: User, reader: User, alice_home: Home, owner_item: Item
    ) -> None:
        report = services.create_report(reader, alice_home, title="x", item=owner_item)
        body = (
            signed(client, alice)
            .get(url("detail", alice_home, report_id=report.id))
            .content.decode()
        )
        link = reverse(
            "rooms:item-detail", kwargs={"home_id": alice_home.id, "item_id": owner_item.id}
        )
        assert f'href="{link}"' in body
        assert "Living room · Boiler" in body


class TestButtons:
    def test_make_it_a_task(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        response = signed(client, alice).post(url("to-task", alice_home, report_id=reported.id))
        task = Task.objects.get()
        assert response["Location"] == reverse(
            "tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id}
        )
        reported.refresh_from_db()
        assert (reported.status, reported.task) == (ReportStatus.TASK, task)
        detail = client.get(url("detail", alice_home, report_id=reported.id)).content.decode()
        assert "The tap drips" in detail
        assert "Made into a task" in detail
        # Again: a message, no second task.
        again = client.post(url("to-task", alice_home, report_id=reported.id))
        assert again["Location"] == url("detail", alice_home, report_id=reported.id)
        assert Task.objects.count() == 1

    @pytest.mark.parametrize("resolution", ["resolved", "no_action"])
    def test_close_and_reopen(
        self, client: Client, alice: User, alice_home: Home, reported: Report, resolution: str
    ) -> None:
        signed(client, alice)
        client.post(url("close", alice_home, report_id=reported.id), {"resolution": resolution})
        reported.refresh_from_db()
        assert reported.status == resolution
        body = client.get(url("detail", alice_home, report_id=reported.id)).content.decode()
        assert "Reopen" in body
        assert "Mark as resolved" not in body
        client.post(url("reopen", alice_home, report_id=reported.id))
        reported.refresh_from_db()
        assert reported.status == ReportStatus.OPEN

    def test_a_bad_resolution_changes_nothing(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        signed(client, alice)
        for value in ("", "open", "task", "bogus"):
            client.post(url("close", alice_home, report_id=reported.id), {"resolution": value})
        reported.refresh_from_db()
        assert reported.status == ReportStatus.OPEN

    def test_a_reader_cannot_press_any_of_them(
        self, client: Client, reader: User, alice_home: Home, reported: Report
    ) -> None:
        signed(client, reader)
        for name, data in (
            ("to-task", {}),
            ("close", {"resolution": "resolved"}),
            ("reopen", {}),
        ):
            response = client.post(url(name, alice_home, report_id=reported.id), data)
            assert response.status_code == 403, name
        reported.refresh_from_db()
        assert reported.status == ReportStatus.OPEN
        assert Task.objects.count() == 0

    def test_the_buttons_only_answer_to_post(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        signed(client, alice)
        for name in ("to-task", "close", "reopen"):
            assert client.get(url(name, alice_home, report_id=reported.id)).status_code == 405


class TestToday:
    def test_a_writer_sees_one_line_with_the_open_reports(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        address = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        body = signed(client, alice).get(address).content.decode()
        assert "1 problem reported" in body
        assert url("list", alice_home) in body
        services.create_report(alice, alice_home, title="second")
        assert "2 problems reported" in client.get(address).content.decode()

    def test_nothing_when_nothing_waits_and_nothing_for_a_reader(
        self, client: Client, alice: User, reader: User, alice_home: Home, reported: Report
    ) -> None:
        address = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        assert "problem" not in signed(client, reader).get(address).content.decode().lower()
        services.close_report(alice, reported, resolution="resolved")
        assert "problem reported" not in signed(client, alice).get(address).content.decode()

    def test_a_report_made_into_a_task_is_no_longer_waiting(
        self, client: Client, alice: User, alice_home: Home, reported: Report
    ) -> None:
        services.make_task(alice, reported)
        address = reverse("tasks:today", kwargs={"home_id": alice_home.id})
        assert "problem reported" not in signed(client, alice).get(address).content.decode()


class TestHomePage:
    def test_the_home_page_leads_to_the_reports_and_the_labels(
        self, client: Client, alice: User, reader: User, alice_home: Home, reported: Report
    ) -> None:
        address = reverse("homes:detail", kwargs={"home_id": alice_home.id})
        body = signed(client, alice).get(address).content.decode()
        assert url("list", alice_home) in body
        assert "1 report waiting" in body
        assert reverse("labels:list", kwargs={"home_id": alice_home.id}) in body
        body = signed(client, reader).get(address).content.decode()
        assert url("list", alice_home) in body
        assert "waiting" not in body

    def test_a_home_page_of_another_home_shows_nothing_of_these(
        self, client: Client, alice: User, bob_home: Home, alice_home: Home
    ) -> None:
        services.create_report(alice, alice_home, title="Mine only")
        assert (
            signed(client, alice)
            .get(reverse("homes:detail", kwargs={"home_id": bob_home.id}))
            .status_code
            == 404
        )


def test_a_random_report_id_is_a_404(client: Client, alice: User, alice_home: Home) -> None:
    signed(client, alice)
    assert client.get(url("detail", alice_home, report_id=uuid.uuid4())).status_code == 404


def test_the_photo_folder_holds_only_the_files_of_the_home(
    alice: User, reader: User, alice_home: Home, media_root: Path
) -> None:
    services.create_report(reader, alice_home, title="x", photo=upload(image_bytes()))
    names = sorted(p.relative_to(media_root).parts[0] for p in media_root.rglob("*") if p.is_file())
    assert set(names) == {"reports"}
