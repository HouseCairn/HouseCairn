"""Contractors: the record, the single field of a task, the contact file (docs/adr/0045)."""

import json
import zipfile
from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.audit.models import AuditEvent
from housecairn.homes import exports
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.tasks import services
from housecairn.tasks.models import Contractor, Task
from tests.data_support import export_data

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

FULL = {
    "name": "Pipes Ltd",
    "trade": "plumber",
    "phone": "+33 1 23 45 67 89",
    "email": "contact@example.com",
    "address": "1 Main Street\n12345 Springfield",
    "note": "Call after 5pm",
}


def web(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"tasks:contractor-{name}", kwargs={"home_id": home.id, **kwargs})


@pytest.fixture
def contractor(alice: User, alice_home: Home) -> Contractor:
    return services.create_contractor(alice, alice_home, **FULL)


class TestRecord:
    def test_every_field_is_kept(self, contractor: Contractor) -> None:
        contractor.refresh_from_db()
        assert (contractor.trade, contractor.phone, contractor.email) == (
            "plumber",
            "+33 1 23 45 67 89",
            "contact@example.com",
        )
        assert contractor.address == "1 Main Street\n12345 Springfield"
        assert contractor.trade_label == "Plumber"

    def test_only_the_name_is_required(self, alice: User, alice_home: Home) -> None:
        bare = services.create_contractor(alice, alice_home, name="Neighbour")
        assert (bare.trade, bare.phone, bare.email, bare.address) == ("", "", "", "")
        assert bare.trade_label == ""
        with pytest.raises(ValidationError):
            services.create_contractor(alice, alice_home, name="")

    def test_other_says_which_trade(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError) as caught:
            services.create_contractor(alice, alice_home, name="x", trade="other")
        assert "trade_other" in caught.value.message_dict
        made = services.create_contractor(
            alice, alice_home, name="x", trade="other", trade_other="Pool maintenance"
        )
        assert made.trade_label == "Pool maintenance"

    def test_the_text_of_other_goes_when_the_trade_is_a_listed_one(
        self, alice: User, alice_home: Home
    ) -> None:
        made = services.create_contractor(
            alice, alice_home, name="x", trade="other", trade_other="Pool maintenance"
        )
        services.update_contractor(alice, made, trade="painter")
        made.refresh_from_db()
        assert (made.trade, made.trade_other) == ("painter", "")

    def test_an_unknown_trade_is_refused(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.create_contractor(alice, alice_home, name="x", trade="wizard")

    @pytest.mark.parametrize("phone", ["javascript:alert(1)", "abc", "12", "+33<1>", "1;2"])
    def test_a_phone_is_a_phone(self, alice: User, alice_home: Home, phone: str) -> None:
        with pytest.raises(ValidationError):
            services.create_contractor(alice, alice_home, name="x", phone=phone)

    def test_an_email_is_an_email(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValidationError):
            services.create_contractor(alice, alice_home, name="x", email="not an address")

    def test_free_text_loses_control_characters(self, alice: User, alice_home: Home) -> None:
        made = services.create_contractor(
            alice,
            alice_home,
            name="Pi\x07pes\r\nLtd\u202e",
            address="1 Main\x1b[31m Street\r\n12345",
            note="a\u200bb",
        )
        assert made.name == "Pipes Ltd"
        assert made.address == "1 Main[31m Street\n12345"
        assert made.note == "ab"

    def test_the_audit_log_names_the_contractor_and_the_fields(
        self, alice: User, alice_home: Home
    ) -> None:
        made = services.create_contractor(alice, alice_home, name="Pipes Ltd", note="secret")
        services.update_contractor(alice, made, phone="0123456789")
        services.delete_contractor(alice, made)
        events = AuditEvent.objects.filter(action__startswith="contractor.").order_by("created_at")
        assert [e.action for e in events] == [
            "contractor.created",
            "contractor.updated",
            "contractor.deleted",
        ]
        assert events[1].detail["fields"] == ["phone"]
        assert "secret" not in json.dumps([e.detail for e in events])

    def test_a_reader_cannot_write(self, reader: User, alice_home: Home) -> None:
        with pytest.raises(PermissionDenied):
            services.create_contractor(reader, alice_home, name="x")

    def test_naming_finds_a_contractor_whatever_the_case_or_makes_one(
        self, alice: User, alice_home: Home, contractor: Contractor
    ) -> None:
        assert services.contractor_named(alice, alice_home, " pipes  LTD ") == contractor
        made = services.contractor_named(alice, alice_home, "New One")
        assert made is not None
        assert made.name == "New One"
        assert services.contractor_named(alice, alice_home, "   ") is None
        assert services.contractors_of(alice_home).count() == 2

    def test_naming_never_borrows_a_contractor_of_another_home(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home
    ) -> None:
        theirs = services.create_contractor(bob, bob_home, name="Shared Name")
        mine = services.contractor_named(alice, alice_home, "Shared Name")
        assert mine is not None
        assert mine != theirs
        assert mine.home_id == alice_home.id


TASK_FORM = {
    "title": "Service the boiler",
    "priority": "normal",
    "repeats": "on",
    "repeat_from": "fixed",  # without a date: refused by the service, after the form passed
    "repeat_interval": "1",
    "repeat_unit": "year",
    "hide_days_before": "0",
    "contractor_name": "Brand New Ltd",
}


class TestRefusedFormLeavesNothing:
    def test_a_refused_new_task_creates_no_contractor_and_no_audit_line(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        response = signed_in.post(
            reverse("tasks:create", kwargs={"home_id": alice_home.id}), TASK_FORM
        )
        assert response.status_code == 200  # the form again, with its error
        assert not Contractor.objects.filter(name="Brand New Ltd").exists()
        assert not AuditEvent.objects.filter(action__startswith="contractor.").exists()
        assert not Task.objects.exists()

    def test_a_refused_edit_creates_no_contractor_and_no_audit_line(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        task = services.create_task(alice, alice_home, title="Service the boiler")
        before = AuditEvent.objects.count()
        response = signed_in.post(
            reverse("tasks:edit", kwargs={"home_id": alice_home.id, "task_id": task.id}), TASK_FORM
        )
        assert response.status_code == 200
        assert not Contractor.objects.filter(name="Brand New Ltd").exists()
        assert AuditEvent.objects.count() == before

    def test_an_accepted_form_still_creates_both(self, signed_in: Client, alice_home: Home) -> None:
        data = {**TASK_FORM, "repeats": ""}
        response = signed_in.post(reverse("tasks:create", kwargs={"home_id": alice_home.id}), data)
        assert response.status_code == 302
        assert Task.objects.get().contractor == Contractor.objects.get(name="Brand New Ltd")


class TestScreens:
    def test_the_list_and_the_sheet(
        self, signed_in: Client, alice_home: Home, alice: User, contractor: Contractor
    ) -> None:
        page = signed_in.get(reverse("tasks:contractors", kwargs={"home_id": alice_home.id})).text
        assert "Pipes Ltd" in page
        assert "Plumber" in page
        sheet = signed_in.get(web("detail", alice_home, contractor_id=contractor.id)).text
        for expected in (
            "Plumber",
            "+33 1 23 45 67 89",
            "contact@example.com",
            "1 Main Street<br>12345 Springfield",
            "Call after 5pm",
            "Download the contact (.vcf)",
        ):
            assert expected in sheet
        assert 'href="tel:%2B33%201%2023%2045%2067%2089"' in sheet
        assert 'href="mailto:contact%40example.com"' in sheet

    def test_the_sheet_lists_the_linked_tasks(
        self, signed_in: Client, alice_home: Home, alice: User, contractor: Contractor
    ) -> None:
        services.create_task(alice, alice_home, title="Service the boiler", contractor=contractor)
        services.create_task(alice, alice_home, title="Unrelated")
        sheet = signed_in.get(web("detail", alice_home, contractor_id=contractor.id)).text
        assert "Service the boiler" in sheet
        assert "Unrelated" not in sheet

    def test_what_a_contractor_says_is_escaped(
        self, signed_in: Client, alice_home: Home, alice: User
    ) -> None:
        made = services.create_contractor(
            alice, alice_home, name="<script>alert(1)</script>", note="<img src=x onerror=y>"
        )
        sheet = signed_in.get(web("detail", alice_home, contractor_id=made.id)).text
        assert "<script>alert(1)</script>" not in sheet
        assert "<img src=x" not in sheet

    def test_create_edit_and_delete(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(
            web("create", alice_home), {"name": "Pipes Ltd", "trade": "plumber"}
        )
        assert response.status_code == 302
        made = Contractor.objects.get(name="Pipes Ltd")
        edit = web("edit", alice_home, contractor_id=made.id)
        assert 'name="trade_other"' in signed_in.get(edit).text
        signed_in.post(
            edit, {"name": "Pipes", "trade": "other", "trade_other": "Pool", "phone": "0123456789"}
        )
        made.refresh_from_db()
        assert (made.name, made.trade_label, made.phone) == ("Pipes", "Pool", "0123456789")
        refused = signed_in.post(edit, {"name": "Pipes", "trade": "other"})
        assert refused.status_code == 200
        assert "Say which trade" in refused.text
        delete = web("delete", alice_home, contractor_id=made.id)
        assert signed_in.get(delete).status_code == 200
        assert signed_in.post(delete).status_code == 302
        assert not Contractor.objects.filter(pk=made.pk).exists()

    def test_a_bad_phone_is_shown_on_the_form(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(web("create", alice_home), {"name": "x", "phone": "javascript:1"})
        assert response.status_code == 200
        assert not Contractor.objects.filter(name="x").exists()

    def test_the_task_page_links_to_the_sheet(
        self, signed_in: Client, alice_home: Home, alice: User, contractor: Contractor
    ) -> None:
        task = services.create_task(alice, alice_home, title="Service", contractor=contractor)
        page = signed_in.get(
            reverse("tasks:detail", kwargs={"home_id": alice_home.id, "task_id": task.id})
        ).text
        assert web("detail", alice_home, contractor_id=contractor.id) in page
        assert "Plumber" in page


class TestContactFile:
    def test_headers_and_content(
        self, signed_in: Client, alice_home: Home, contractor: Contractor
    ) -> None:
        response = signed_in.get(web("vcard", alice_home, contractor_id=contractor.id))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/vcard; charset=utf-8"
        assert response["Content-Disposition"] == 'attachment; filename="pipes-ltd.vcf"'
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "no-store" in response["Cache-Control"]
        body = response.content.decode()
        assert body.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
        assert "FN:Pipes Ltd" in body

    def test_a_hostile_note_stays_inside_its_line(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        made = services.create_contractor(
            alice,
            alice_home,
            name="Evil\r\nBEGIN:VCARD",
            note="x\r\nEND:VCARD\r\nBEGIN:VCARD\r\nFN:Hacker;a,b",
        )
        body = signed_in.get(web("vcard", alice_home, contractor_id=made.id)).content.decode()
        lines = body.replace("\r\n ", "").split("\r\n")
        assert lines.count("BEGIN:VCARD") == 1
        assert lines.count("END:VCARD") == 1
        assert "FN:Hacker;a,b" not in lines

    def test_a_reader_can_download_it(
        self, client: Client, reader: User, alice_home: Home, contractor: Contractor
    ) -> None:
        client.force_login(reader)
        assert client.get(web("vcard", alice_home, contractor_id=contractor.id)).status_code == 200

    def test_the_method_is_get(
        self, signed_in: Client, alice_home: Home, contractor: Contractor
    ) -> None:
        assert (
            signed_in.post(web("vcard", alice_home, contractor_id=contractor.id)).status_code == 405
        )


class TestIsolationAndRoles:
    def addresses(self, home: Home, contractor: Contractor) -> list[tuple[str, str]]:
        kwargs = {"contractor_id": contractor.id}
        return [
            ("get", web("detail", home, **kwargs)),
            ("get", web("edit", home, **kwargs)),
            ("post", web("edit", home, **kwargs)),
            ("get", web("delete", home, **kwargs)),
            ("post", web("delete", home, **kwargs)),
            ("get", web("vcard", home, **kwargs)),
        ]

    @pytest.mark.parametrize("who", ["bob", "site_admin"])
    def test_a_stranger_gets_a_404_everywhere_even_for_the_contact_file(
        self,
        client: Client,
        request: pytest.FixtureRequest,
        who: str,
        alice_home: Home,
        contractor: Contractor,
    ) -> None:
        client.force_login(request.getfixturevalue(who))
        for method, address in self.addresses(alice_home, contractor):
            response = getattr(client, method)(address, {"name": "x"})
            assert response.status_code == 404, (method, address)
        assert (
            client.get(reverse("tasks:contractors", kwargs={"home_id": alice_home.id})).status_code
            == 404
        )
        assert client.get(web("create", alice_home)).status_code == 404
        assert Contractor.objects.filter(pk=contractor.pk).exists()

    def test_the_sheet_of_one_home_is_a_404_through_another_home_of_the_same_person(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        contractor: Contractor,
        add_member: Callable[..., object],
    ) -> None:
        other = home_services.create_home(alice, name="Cottage")
        client.force_login(alice)
        for method, address in self.addresses(other, contractor):
            assert getattr(client, method)(address, {"name": "x"}).status_code == 404, address

    def test_a_reader_reads_and_changes_nothing(
        self, client: Client, reader: User, alice_home: Home, contractor: Contractor
    ) -> None:
        client.force_login(reader)
        listing = reverse("tasks:contractors", kwargs={"home_id": alice_home.id})
        assert client.get(listing).status_code == 200
        assert client.get(web("detail", alice_home, contractor_id=contractor.id)).status_code == 200
        assert "Add a contractor" not in client.get(listing).text
        sheet = client.get(web("detail", alice_home, contractor_id=contractor.id)).text
        assert web("edit", alice_home, contractor_id=contractor.id) not in sheet
        for name in ("create",):
            assert client.get(web(name, alice_home)).status_code == 403
            assert client.post(web(name, alice_home), {"name": "x"}).status_code == 403
        for name in ("edit", "delete"):
            address = web(name, alice_home, contractor_id=contractor.id)
            assert client.get(address).status_code == 403
            assert client.post(address, {"name": "x"}).status_code == 403
        contractor.refresh_from_db()
        assert contractor.name == "Pipes Ltd"

    def test_a_member_writes(
        self, client: Client, member: User, alice_home: Home, contractor: Contractor
    ) -> None:
        client.force_login(member)
        assert client.post(web("create", alice_home), {"name": "By member"}).status_code == 302
        assert Contractor.objects.filter(name="By member", home=alice_home).exists()


class TestApi:
    def url(self, name: str, home: Home, **kwargs: object) -> str:
        return reverse(f"api-v1:home-contractor-{name}", kwargs={"home_id": home.id, **kwargs})

    def test_crud_with_the_new_fields(
        self, api_client: APIClient, alice: User, alice_home: Home
    ) -> None:
        api_client.force_authenticate(alice)
        created = api_client.post(self.url("list", alice_home), FULL, format="json")
        assert created.status_code == 201
        body = created.json()
        assert (body["trade"], body["trade_label"], body["phone"]) == (
            "plumber",
            "Plumber",
            "+33 1 23 45 67 89",
        )
        assert body["address"] == FULL["address"]
        detail = self.url("detail", alice_home, contractor_id=body["id"])
        patched = api_client.patch(
            detail, {"trade": "other", "trade_other": "Pool"}, format="json"
        ).json()
        assert patched["trade_label"] == "Pool"
        assert api_client.patch(detail, {"trade": "wizard"}, format="json").status_code == 400
        assert api_client.patch(detail, {"phone": "x;y"}, format="json").status_code == 400
        assert (
            api_client.patch(
                detail, {"trade": "other", "trade_other": ""}, format="json"
            ).status_code
            == 400
        )

    def test_the_contact_file(
        self, api_client: APIClient, alice: User, alice_home: Home, contractor: Contractor
    ) -> None:
        api_client.force_authenticate(alice)
        response = api_client.get(self.url("vcard", alice_home, contractor_id=contractor.id))
        assert response.status_code == 200
        assert response["Content-Type"] == "text/vcard; charset=utf-8"
        assert response["Content-Disposition"].startswith("attachment;")
        assert response.content.decode().startswith("BEGIN:VCARD\r\nVERSION:3.0")

    def test_the_tasks_of_a_contractor(
        self, api_client: APIClient, alice: User, alice_home: Home, contractor: Contractor
    ) -> None:
        services.create_task(alice, alice_home, title="Linked", contractor=contractor)
        services.create_task(alice, alice_home, title="Free")
        api_client.force_authenticate(alice)
        rows = api_client.get(
            reverse("api-v1:home-task-list", kwargs={"home_id": alice_home.id}),
            {"contractor": str(contractor.id)},
        ).json()["results"]
        assert [r["title"] for r in rows] == ["Linked"]

    def test_a_token_of_another_home_sees_nothing(
        self,
        api_client: APIClient,
        bob: User,
        bob_home: Home,
        alice_home: Home,
        contractor: Contractor,
    ) -> None:
        _token, secret = token_services.issue_token(
            bob, name="t", scopes=["read"], homes=[bob_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
        address = self.url("vcard", alice_home, contractor_id=contractor.id)
        assert api_client.get(address).status_code in (403, 404)
        assert api_client.get(
            self.url("detail", alice_home, contractor_id=contractor.id)
        ).status_code in (403, 404)


class TestExportAndErasure:
    def test_the_export_holds_the_new_fields_of_this_home_only(
        self, alice: User, bob: User, alice_home: Home, bob_home: Home, contractor: Contractor
    ) -> None:
        services.create_contractor(bob, bob_home, name="Theirs", phone="0123456789")
        archive, _name = exports.export_home(alice, alice_home)
        data = export_data(zipfile.ZipFile(archive))
        [row] = data["contractors"]
        assert row["name"] == "Pipes Ltd"
        assert (row["trade"], row["phone"], row["email"]) == (
            "plumber",
            "+33 1 23 45 67 89",
            "contact@example.com",
        )
        assert row["address"] == FULL["address"]
        assert "trade_other" in row

    def test_erasing_the_home_erases_its_contractors(
        self, alice: User, alice_home: Home, contractor: Contractor
    ) -> None:
        home_services.delete_home(alice, alice_home, confirmation=alice_home.name)
        assert not Contractor.objects.filter(pk=contractor.pk).exists()
        assert not Task.objects.filter(home_id=alice_home.pk).exists()
