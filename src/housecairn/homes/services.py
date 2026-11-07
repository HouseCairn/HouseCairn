"""Business rules about homes and memberships (docs/adr/0002, 0006).

Web views and API views call these functions; neither holds rules of its own.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import models, transaction

from housecairn.accounts.models import User
from housecairn.homes.models import WRITE_ROLES, Home, Membership, Role

AnyUser = User | AnonymousUser


def homes_for(user: AnyUser, *, restrict_to: Iterable[UUID] | None = None) -> models.QuerySet[Home]:
    """Homes the user belongs to; optionally only those in `restrict_to`.

    This is the single entry point that limits every query to the user's homes.
    """
    if not user.is_authenticated or not user.is_active:
        return Home.objects.none()
    member_of = Membership.objects.filter(user=user).values("home_id")
    homes = Home.objects.filter(id__in=member_of)
    if restrict_to is not None:
        homes = homes.filter(id__in=list(restrict_to))
    return homes


def role_of(user: AnyUser, home: Home) -> Role | None:
    if not user.is_authenticated:
        return None
    membership = Membership.objects.filter(user=user, home=home).first()
    return Role(membership.role) if membership else None


def can_write(user: AnyUser, home: Home) -> bool:
    return role_of(user, home) in WRITE_ROLES


@transaction.atomic
def create_home(owner: User, *, name: str, currency: str = "EUR") -> Home:
    home: Home = Home.objects.create(name=name, currency=currency)
    Membership.objects.create(home=home, user=owner, role=Role.OWNER)
    return home


def update_home(actor: AnyUser, home: Home, **changes: Any) -> Home:
    if not can_write(actor, home):
        raise PermissionDenied
    allowed = {"name", "currency"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Cannot change: {', '.join(sorted(unknown))}")
    for field, value in changes.items():
        setattr(home, field, value)
    home.full_clean()
    home.save(update_fields=[*changes, "updated_at"])
    return home
