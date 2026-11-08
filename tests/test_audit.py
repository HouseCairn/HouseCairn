"""The audit log: sensitive operations recorded, seen by the right people only (docs/adr/0023)."""

from collections.abc import Callable

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.audit.models import AuditEvent
from housecairn.homes import services
from housecairn.homes.models import Home, Membership, Role

pytestmark = pytest.mark.django_db

NO_DELIVERY = services.Delivery()


def actions(home: Home) -> list[str]:
    return list(
        AuditEvent.objects.filter(home_id=home.id)
        .order_by("created_at", "id")
        .values_list("action", flat=True)
    )


class TestRecording:
    def test_operations_of_a_home_are_recorded(
        self, alice: User, bob: User, alice_home: Home, add_member: Callable[..., Membership]
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        services.change_role(alice, membership, Role.READ_ONLY)
        services.set_required_provider(
            alice, alice_home, "", declared=[], signed_in_with=frozenset()
        )
        services.invite(
            alice, alice_home, email="new@example.com", role="member", delivery=NO_DELIVERY
        )
        invitation = alice_home.invitations.get()
        services.resend_invitation(alice, invitation, delivery=NO_DELIVERY)
        services.revoke_invitation(alice, invitation)
        services.transfer_ownership(alice, alice_home, membership)
        services.leave_home(alice, alice_home)
        assert actions(alice_home) == [
            "home.created",
            "member.role_changed",
            "sso.lifted",
            "invitation.sent",
            "invitation.resent",
            "invitation.revoked",
            "ownership.transferred",
            "member.left",
        ]
        changed = AuditEvent.objects.get(action="member.role_changed")
        assert changed.detail == {"role": "read_only", "previous_role": "member"}
        assert changed.actor == alice
        assert changed.target_user == bob

    def test_an_accepted_invitation_and_a_removal(
        self, alice: User, bob: User, alice_home: Home, make_user: Callable[..., User]
    ) -> None:
        _inv, raw = services.invite(
            alice, alice_home, email="carol@example.com", role="read_only", delivery=NO_DELIVERY
        )
        carol = make_user("carol@example.com")
        services.accept_invitation(carol, raw or "")
        membership = Membership.objects.get(home=alice_home, user=carol)
        services.remove_member(alice, membership)
        assert actions(alice_home)[-2:] == ["invitation.accepted", "member.removed"]

    def test_an_entry_carries_no_content(self, alice: User, alice_home: Home) -> None:
        with pytest.raises(ValueError, match="may not carry"):
            audit.record("home.created", actor=alice, home_id=alice_home.id, name="Villa Secrète")
        with pytest.raises(ValueError, match="may not carry"):
            audit.record("home.created", actor=alice, home_id=alice_home.id, email="x@example.com")

    def test_a_home_entry_needs_its_home_and_an_instance_entry_none(self) -> None:
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            AuditEvent.objects.create(scope="home", action="x")
        with pytest.raises(IntegrityError), transaction.atomic():
            AuditEvent.objects.create(
                scope="instance", action="x", home_id="00000000-0000-0000-0000-000000000001"
            )

    def test_the_entries_do_not_keep_the_person_after_erasure(
        self, alice: User, alice_home: Home
    ) -> None:
        alice_home_id = alice_home.id
        services.erase_home(alice_home)
        assert not AuditEvent.objects.filter(home_id=alice_home_id).exists()


class TestVisibility:
    def test_only_owners_read_their_homes_log(
        self,
        client: Client,
        alice: User,
        bob: User,
        alice_home: Home,
        bob_home: Home,
        add_member: Callable[..., Membership],
        make_user: Callable[..., User],
    ) -> None:
        carol = make_user("carol@example.com")
        add_member(alice_home, carol, Role.MEMBER)
        url = reverse("homes:audit", kwargs={"home_id": alice_home.id})
        client.force_login(alice)
        page = client.get(url)
        assert page.status_code == 200
        assert "Home created" in page.text
        client.force_login(carol)
        assert client.get(url).status_code == 403
        client.force_login(bob)
        assert client.get(url).status_code == 404
        # Bob's own log never shows Alice's entries.
        own = client.get(reverse("homes:audit", kwargs={"home_id": bob_home.id}))
        assert "alice@example.com" not in own.text

    def test_the_log_of_the_instance_holds_no_home_entry(
        self, client: Client, alice: User, alice_home: Home, make_user: Callable[..., User]
    ) -> None:
        admin = make_user("admin@example.com", is_staff=True, is_superuser=True)
        audit.record("account.created", actor=admin, by="administrator")
        assert AuditEvent.objects.filter(scope="home").exists()
        client.force_login(admin)
        page = client.get(reverse("instance:audit"))
        assert "Account created" in page.text
        assert "Home created" not in page.text
        assert alice.email not in page.text
        assert {e.scope for e in audit.instance_log(admin)} == {"instance"}

    def test_api_is_for_owners_and_never_for_tokens(
        self, client: Client, api_client: APIClient, alice: User, bob: User, alice_home: Home
    ) -> None:
        from housecairn.apitokens import services as tokens

        url = reverse("api-v1:home-audit", kwargs={"home_id": alice_home.id})
        client.force_login(alice)
        body = client.get(url).json()
        assert [e["action"] for e in body["results"]] == ["home.created"]
        assert body["results"][0]["label"] == "Home created"
        client.force_login(bob)
        assert client.get(url).status_code == 404
        _token, raw = tokens.issue_token(
            alice, name="all", scopes=["read", "write"], homes=[alice_home]
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert api_client.get(url).status_code == 403

    def test_the_audit_service_refuses_non_owners(
        self, alice_home: Home, bob: User, alice: User
    ) -> None:
        from django.core.exceptions import PermissionDenied

        with pytest.raises(PermissionDenied):
            audit.home_log(bob, alice_home.id)
        with pytest.raises(PermissionDenied):
            audit.instance_log(alice)
        assert audit.home_log(alice, alice_home.id).count() == 1


def test_an_unknown_action_is_shown_as_its_code() -> None:
    from housecairn.audit.labels import label

    assert label("something.new", {}) == "something.new"
    assert label("member.role_changed", {"role": "owner"}) == "Role changed to Owner"
    assert label("member.role_changed", {}) == "Role changed to"
