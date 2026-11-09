"""`manage.py verify_email`: verify an address on an instance without outgoing email."""

from collections.abc import Callable
from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent, Scope
from housecairn.homes import services
from housecairn.homes.models import Home, Role

pytestmark = pytest.mark.django_db

NO_DELIVERY = services.Delivery()


def run(*args: str) -> str:
    out = StringIO()
    call_command("verify_email", *args, stdout=out)
    return out.getvalue()


def local_account(make_user: Callable[..., User], email: str) -> User:
    """An account whose address was never verified, as after `createsuperuser`."""
    user = make_user(email)
    EmailAddress.objects.filter(user=user).delete()
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
    return user


def record_of(user: User) -> EmailAddress:
    return EmailAddress.objects.get(user=user, email__iexact=user.email)


def test_an_unknown_address_fails_and_creates_nothing(make_user: Callable[..., User]) -> None:
    make_user("ivy@example.com")
    before = EmailAddress.objects.count()
    with pytest.raises(CommandError, match="No account has this address"):
        run("nobody@example.com")
    assert EmailAddress.objects.count() == before
    assert not AuditEvent.objects.filter(action="account.email_verified").exists()


def test_the_address_is_verified(make_user: Callable[..., User]) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    assert "marked verified" in run("ivy@example.com")
    assert record_of(ivy).verified


def test_the_case_is_ignored(make_user: Callable[..., User]) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    run("  IVY@Example.COM ")
    assert record_of(ivy).verified


def test_it_is_idempotent_and_says_so(make_user: Callable[..., User]) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    run("ivy@example.com")
    assert "Nothing to change" in run("ivy@example.com")
    assert "Nothing to change" in run("ivy@example.com", "--primary")
    assert AuditEvent.objects.filter(action="account.email_verified").count() == 1
    assert record_of(ivy).verified


def test_an_already_verified_address_changes_nothing(make_user: Callable[..., User]) -> None:
    ivy = make_user("ivy@example.com")
    EmailAddress.objects.update_or_create(
        user=ivy, email="ivy@example.com", defaults={"verified": True, "primary": True}
    )
    assert "Nothing to change" in run("ivy@example.com")
    assert not AuditEvent.objects.filter(action="account.email_verified").exists()


def test_without_primary_the_primary_address_stays(make_user: Callable[..., User]) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    EmailAddress.objects.create(user=ivy, email="second@example.com", verified=False)
    run("second@example.com")
    second = EmailAddress.objects.get(user=ivy, email="second@example.com")
    assert second.verified
    assert not second.primary
    assert record_of(ivy).primary


def test_primary_makes_it_the_address_of_the_account(make_user: Callable[..., User]) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    EmailAddress.objects.create(user=ivy, email="second@example.com", verified=False)
    assert "verified and primary" in run("second@example.com", "--primary")
    second = EmailAddress.objects.get(user=ivy, email="second@example.com")
    assert second.verified
    assert second.primary
    assert not EmailAddress.objects.get(user=ivy, email="ivy@example.com").primary
    ivy.refresh_from_db()
    assert ivy.email == "second@example.com"


def test_primary_on_an_address_already_verified_only_promotes_it(
    make_user: Callable[..., User],
) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    EmailAddress.objects.create(user=ivy, email="second@example.com", verified=True)
    assert "marked primary" in run("second@example.com", "--primary")
    ivy.refresh_from_db()
    assert ivy.email == "second@example.com"
    assert EmailAddress.objects.get(user=ivy, email="second@example.com").primary


def test_several_accounts_fail_with_their_ids_and_no_address(
    make_user: Callable[..., User],
) -> None:
    ivy = local_account(make_user, "ivy@example.com")
    other = make_user("other@example.com")
    EmailAddress.objects.create(user=other, email="IVY@example.com", verified=False)
    with pytest.raises(CommandError) as raised:
        run("ivy@example.com")
    message = str(raised.value)
    assert str(ivy.pk) in message
    assert str(other.pk) in message
    assert "example.com" not in message
    assert not EmailAddress.objects.filter(verified=True, email__iexact="ivy@example.com").exists()


def test_the_audit_log_of_the_instance_gets_a_line(make_user: Callable[..., User]) -> None:
    from housecairn.audit.labels import label

    ivy = local_account(make_user, "ivy@example.com")
    run("ivy@example.com")
    entry = AuditEvent.objects.get(action="account.email_verified")
    assert entry.scope == Scope.INSTANCE
    assert entry.target_user == ivy
    assert entry.actor is None
    assert entry.detail == {}
    assert label(entry.action, entry.detail) == "Email address verified from the server"


class TestHandedOverInvitation:
    """The reason for the command: a link handed over by hand needs a verified address."""

    def test_refused_without_the_command(
        self, alice: User, alice_home: Home, make_user: Callable[..., User]
    ) -> None:
        _invitation, raw = services.invite(
            alice, alice_home, email="ivy@example.com", role="member", delivery=NO_DELIVERY
        )
        assert raw is not None
        ivy = local_account(make_user, "ivy@example.com")
        with pytest.raises(PermissionDenied, match="Verify this address"):
            services.accept_invitation(ivy, raw)
        assert services.role_of(ivy, alice_home) is None

    def test_accepted_after_the_command(
        self, alice: User, alice_home: Home, make_user: Callable[..., User]
    ) -> None:
        _invitation, raw = services.invite(
            alice, alice_home, email="Ivy@Example.com", role="member", delivery=NO_DELIVERY
        )
        assert raw is not None
        ivy = local_account(make_user, "ivy@example.com")
        run("ivy@example.com")
        services.accept_invitation(ivy, raw)
        assert services.role_of(ivy, alice_home) == Role.MEMBER
