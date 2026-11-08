"""Export of a home, deletion of a home, erasure of an account (docs/adr/0023)."""

import io
import json
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from allauth.account.models import EmailAddress
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts import services as account_services
from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.apitokens.models import ApiToken
from housecairn.audit.models import AuditEvent
from housecairn.events.models import Event
from housecairn.homes import exports, services
from housecairn.homes.models import Home, Invitation, Membership, Role

pytestmark = pytest.mark.django_db

NO_DELIVERY = services.Delivery()


def read_zip(response: Any) -> zipfile.ZipFile:
    content = b"".join(response.streaming_content)
    return zipfile.ZipFile(io.BytesIO(content))


@pytest.fixture
def filled(alice: User, alice_home: Home, bob: User, bob_home: Home) -> None:
    Event.objects.create(home=alice_home, kind="battery_low", payload={"room": "kitchen"})
    Event.objects.create(home=bob_home, kind="leak", payload={"room": "bathroom-of-bob"})
    services.invite(
        alice, alice_home, email="guest-a@example.com", role="member", delivery=NO_DELIVERY
    )
    services.invite(bob, bob_home, email="guest-b@example.com", role="member", delivery=NO_DELIVERY)


class TestExport:
    def test_the_archive_holds_the_home_and_nothing_of_another(
        self, client: Client, alice: User, alice_home: Home, bob_home: Home, filled: None
    ) -> None:
        client.force_login(alice)
        response = client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert "attachment" in response["Content-Disposition"]
        archive = read_zip(response)
        assert set(archive.namelist()) == {"export.json", "README.txt"}
        raw = archive.read("export.json").decode()
        data = json.loads(raw)
        assert data["format"] == "housecairn-export"
        assert data["version"] == exports.FORMAT_VERSION
        assert data["home"]["id"] == str(alice_home.id)
        assert data["home"]["name"] == "Main house"
        assert [m["email"] for m in data["members"]] == ["alice@example.com"]
        assert [m["role"] for m in data["members"]] == ["owner"]
        assert [i["email"] for i in data["pending_invitations"]] == ["guest-a@example.com"]
        assert [e["kind"] for e in data["events"]] == ["battery_low"]
        assert data["files"] == []
        # Nothing of the other home, in any form.
        for foreign in (str(bob_home.id), "Flat", "bob@example.com", "guest-b@example.com", "leak"):
            assert foreign not in raw
        # No secret either: the digest of an invitation is not exported.
        assert "digest" not in raw
        assert AuditEvent.objects.filter(action="home.exported", home_id=alice_home.id).exists()

    def test_only_owners_export(
        self,
        client: Client,
        alice_home: Home,
        bob: User,
        add_member: Callable[..., Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        client.force_login(bob)
        url = reverse("homes:export", kwargs={"home_id": alice_home.id})
        assert client.post(url).status_code == 403
        assert not AuditEvent.objects.filter(action="home.exported").exists()

    def test_a_stranger_gets_404_and_get_is_not_allowed(
        self, client: Client, alice: User, bob_home: Home, alice_home: Home
    ) -> None:
        client.force_login(alice)
        assert (
            client.post(reverse("homes:export", kwargs={"home_id": bob_home.id})).status_code == 404
        )
        assert (
            client.get(reverse("homes:export", kwargs={"home_id": alice_home.id})).status_code
            == 405
        )

    def test_api_export_is_for_a_signed_in_owner_only(
        self, client: Client, api_client: APIClient, alice: User, alice_home: Home, bob_home: Home
    ) -> None:
        url = reverse("api-v1:home-export", kwargs={"home_id": alice_home.id})
        client.force_login(alice)
        response = client.post(url)
        assert response.status_code == 200
        assert json.loads(read_zip(response).read("export.json"))["home"]["id"] == str(
            alice_home.id
        )
        assert (
            client.post(reverse("api-v1:home-export", kwargs={"home_id": bob_home.id})).status_code
            == 404
        )
        _token, raw = token_services.issue_token(
            alice, name="all", scopes=["read", "write"], homes=[alice_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.post(url).status_code == 403

    def test_an_app_that_registers_data_and_files_is_exported(
        self, alice: User, alice_home: Home, tmp_path: Any
    ) -> None:
        file = tmp_path / "photo.jpg"
        file.write_bytes(b"\xff\xd8photo")
        exports.register("rooms", lambda home: [{"name": "Kitchen", "home": str(home.id)}])
        exports.register_files(
            lambda home: iter([exports.ExportedFile("rooms/kitchen/photo.jpg", file)])
        )
        try:
            archive, _name = exports.export_home(alice, alice_home)
            zipped = zipfile.ZipFile(archive)
            data = json.loads(zipped.read("export.json"))
            assert data["rooms"] == [{"name": "Kitchen", "home": str(alice_home.id)}]
            assert data["files"] == [{"path": "files/rooms/kitchen/photo.jpg", "size": 7}]
            assert zipped.read("files/rooms/kitchen/photo.jpg") == b"\xff\xd8photo"
        finally:
            exports.EXPORTERS.pop("rooms")
            exports.FILE_SOURCES.pop()

    def test_a_file_cannot_leave_the_archive(self, alice_home: Home, tmp_path: Any) -> None:
        file = tmp_path / "x"
        file.write_bytes(b"x")
        exports.register_files(lambda home: iter([exports.ExportedFile("../../etc/passwd", file)]))
        try:
            with pytest.raises(ValueError, match="leave the archive"):
                exports.build_archive(alice_home)
        finally:
            exports.FILE_SOURCES.pop()


class TestDeleteHome:
    def test_deletion_needs_the_exact_name_and_an_owner(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        url = reverse("homes:delete", kwargs={"home_id": alice_home.id})
        client.force_login(bob)
        assert client.get(url).status_code == 403
        assert client.post(url, {"confirmation": "Main house"}).status_code == 403
        client.force_login(alice)
        assert "Delete this home" in client.get(url).text
        wrong = client.post(url, {"confirmation": "main"})
        assert wrong.status_code == 200
        assert "exact name" in wrong.text
        assert Home.objects.filter(pk=alice_home.pk).exists()

    def test_deletion_removes_everything_of_the_home_and_only_it(
        self, client: Client, alice: User, alice_home: Home, bob_home: Home, filled: None
    ) -> None:
        token, _raw = token_services.issue_token(
            alice, name="ha", scopes=["events"], homes=[alice_home]
        )
        client.force_login(alice)
        response = client.post(
            reverse("homes:delete", kwargs={"home_id": alice_home.id}),
            {"confirmation": " Main house "},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("homes:list")
        assert not Home.all_objects.filter(pk=alice_home.pk).exists()
        assert not Membership.all_objects.filter(home_id=alice_home.pk).exists()
        assert not Invitation.all_objects.filter(home_id=alice_home.pk).exists()
        assert not Event.all_objects.filter(home_id=alice_home.pk).exists()
        assert not AuditEvent.objects.filter(home_id=alice_home.pk).exists()
        assert ApiToken.objects.get(pk=token.pk).revoked_at is not None
        # The other home is untouched.
        assert Home.objects.filter(pk=bob_home.pk).exists()
        assert Event.objects.filter(home=bob_home).count() == 1
        assert Invitation.objects.filter(home=bob_home).count() == 1
        # The instance log keeps that it happened, and names no home.
        entry = AuditEvent.objects.get(action="home.deleted")
        assert entry.scope == "instance"
        assert entry.home_id is None
        assert entry.detail == {}

    def test_api(
        self, client: Client, api_client: APIClient, alice: User, alice_home: Home
    ) -> None:
        url = reverse("api-v1:home-delete-home", kwargs={"home_id": alice_home.id})
        _token, raw = token_services.issue_token(
            alice, name="all", scopes=["read", "write"], homes=[alice_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.post(url, {"confirmation": "Main house"}).status_code == 403
        client.force_login(alice)
        refused = client.post(url, {"confirmation": "nope"}, content_type="application/json")
        assert refused.status_code == 400
        done = client.post(url, {"confirmation": "Main house"}, content_type="application/json")
        assert done.status_code == 204
        assert not Home.all_objects.filter(pk=alice_home.pk).exists()

    def test_files_of_the_home_are_removed(
        self, alice: User, alice_home: Home, settings: Any, tmp_path: Any
    ) -> None:
        settings.MEDIA_ROOT = tmp_path
        directory = exports.media_directory(alice_home)
        directory.mkdir(parents=True)
        (directory / "photo.jpg").write_bytes(b"x")
        other = tmp_path / "homes" / "keep"
        other.mkdir(parents=True)
        from django.test import TestCase

        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_home(alice, alice_home, confirmation="Main house")
        assert not directory.exists()
        assert other.exists()


class TestEraseAccount:
    def test_a_member_leaves_no_trace_and_the_home_stays(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        EmailAddress.objects.create(user=bob, email=bob.email, primary=True, verified=True)
        services.invite(
            alice, alice_home, email="bob2@example.com", role="member", delivery=NO_DELIVERY
        )
        token_services.issue_token(bob, name="t", scopes=["read"], homes=[alice_home])
        account_services.delete_account(bob)
        assert not User.objects.filter(pk=bob.pk).exists()
        assert not Membership.all_objects.filter(user_id=bob.pk).exists()
        assert not ApiToken.objects.filter(user_id=bob.pk).exists()
        assert not EmailAddress.objects.filter(email="bob@example.com").exists()
        assert Home.objects.filter(pk=alice_home.pk).exists()
        entry = AuditEvent.objects.get(action="account.deleted")
        assert entry.actor is None
        assert entry.detail == {"by": "self"}

    def test_the_only_owner_of_a_shared_home_cannot_be_erased(
        self,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> None:
        from django.core.exceptions import ValidationError

        add_member(alice_home, bob, Role.MEMBER)
        assert account_services.homes_blocking_erasure(alice) == [alice_home]
        with pytest.raises(ValidationError, match="only owner"):
            account_services.delete_account(alice)
        assert User.objects.filter(pk=alice.pk).exists()
        # Handing ownership over frees it.
        services.transfer_ownership(
            alice, alice_home, Membership.objects.get(home=alice_home, user=bob)
        )
        account_services.delete_account(alice)
        assert Home.objects.filter(pk=alice_home.pk).exists()
        assert services.role_of(bob, alice_home) == Role.OWNER

    def test_a_home_with_no_other_member_goes_with_the_account(
        self, alice: User, alice_home: Home, bob_home: Home, filled: None
    ) -> None:
        account_services.delete_account(alice)
        assert not Home.all_objects.filter(pk=alice_home.pk).exists()
        assert not Invitation.all_objects.filter(email="guest-a@example.com").exists()
        assert Home.objects.filter(pk=bob_home.pk).exists()
        assert not AuditEvent.objects.filter(home_id=alice_home.pk).exists()

    def test_invitations_to_the_address_are_erased_with_it(
        self, alice: User, alice_home: Home, make_user: Callable[..., User]
    ) -> None:
        carol = make_user("carol@example.com")
        services.invite(
            alice, alice_home, email="carol@example.com", role="member", delivery=NO_DELIVERY
        )
        account_services.delete_account(carol)
        assert not Invitation.all_objects.filter(email__iexact="carol@example.com").exists()

    def test_the_only_administrator_cannot_be_erased(self, make_user: Callable[..., User]) -> None:
        from django.core.exceptions import ValidationError

        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        with pytest.raises(ValidationError, match="only administrator"):
            account_services.delete_account(admin)
        second = make_user("admin2@example.com", is_staff=True, is_superuser=True)
        account_services.delete_account(admin)
        assert not User.objects.filter(pk=admin.pk).exists()
        with pytest.raises(ValidationError):
            account_services.delete_account(second)

    def test_the_web_form_needs_the_address_and_the_password(
        self, client: Client, bob: User
    ) -> None:
        from tests.conftest import PASSWORD

        client.force_login(bob)
        url = reverse("account_delete")
        assert "Delete my account" in client.get(url).text
        for data in (
            {"confirm_email": "other@example.com", "password": PASSWORD},
            {"confirm_email": "bob@example.com", "password": "wrong"},
            {"confirm_email": "bob@example.com"},
        ):
            assert client.post(url, data).status_code == 200
            assert User.objects.filter(pk=bob.pk).exists()
        done = client.post(url, {"confirm_email": "BOB@example.com", "password": PASSWORD})
        assert done.status_code == 302
        assert done["Location"] == reverse("account_login")
        assert not User.objects.filter(pk=bob.pk).exists()
        assert client.get(reverse("homes:list")).status_code == 302

    def test_the_web_form_lists_the_homes_that_block(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        client.force_login(alice)
        page = client.get(reverse("account_delete"))
        assert "Main house" in page.text
        assert "disabled" in page.text

    def test_an_account_without_a_password_confirms_with_the_address_only(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        sso = User.objects.create_user(email="sso@example.com", password=None)
        client.force_login(sso)
        assert 'name="password"' not in client.get(reverse("account_delete")).text
        done = client.post(reverse("account_delete"), {"confirm_email": "sso@example.com"})
        assert done.status_code == 302
        assert not User.objects.filter(pk=sso.pk).exists()

    def test_api(self, client: Client, api_client: APIClient, bob: User, alice_home: Home) -> None:
        from tests.conftest import PASSWORD

        url = reverse("api-v1:account-delete")
        _token, raw = token_services.issue_token(
            bob, name="t", scopes=["read", "write"], homes=[services.create_home(bob, name="B")]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        body = {"confirm_email": "bob@example.com", "password": PASSWORD}
        assert api_client.post(url, body).status_code == 403
        client.force_login(bob)
        assert (
            client.post(url, {**body, "password": "x"}, content_type="application/json").status_code
            == 400
        )
        assert (
            client.post(
                url, {**body, "confirm_email": "z@example.com"}, content_type="application/json"
            ).status_code
            == 400
        )
        assert client.post(url, body, content_type="application/json").status_code == 204
        assert not User.objects.filter(pk=bob.pk).exists()

    def test_the_administrator_deletes_through_the_same_rules(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        add_member: Callable[..., Membership],
        make_user: Callable[..., User],
    ) -> None:
        add_member(alice_home, bob, Role.MEMBER)
        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        client.force_login(admin)
        refused = client.post(
            reverse("admin:accounts_user_delete", args=[alice.pk]), {"post": "yes"}, follow=True
        )
        assert "only owner" in refused.text
        assert "Main house" not in refused.text
        assert User.objects.filter(pk=alice.pk).exists()
        done = client.post(
            reverse("admin:accounts_user_delete", args=[bob.pk]), {"post": "yes"}, follow=True
        )
        assert done.status_code == 200
        assert not User.objects.filter(pk=bob.pk).exists()
        entry = AuditEvent.objects.get(action="admin.user_deleted")
        assert entry.actor == admin
        assert entry.detail == {"by": "administrator"}

    def test_admin_changes_are_audited(
        self, client: Client, make_user: Callable[..., User]
    ) -> None:
        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        client.force_login(admin)
        user = make_user("someone@example.com")
        client.post(
            reverse("admin:accounts_user_change", args=[user.pk]),
            {"is_staff": "on"},
        )
        assert AuditEvent.objects.filter(action="admin.user_changed", target_user=user).exists()
