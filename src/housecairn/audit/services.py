"""Writing and reading the audit log (docs/adr/0023)."""

from typing import Any
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import models

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent, Scope

# Keys `detail` may carry. A value is short and says nothing of a home's content.
ALLOWED_DETAIL = frozenset(
    {
        "role",
        "previous_role",
        "provider",
        "count",
        "by",
        "fields",
        "format",
        "setting",
        "old",
        "new",
    }
)


def record(
    action: str,
    *,
    actor: User | AnonymousUser | None = None,
    home_id: UUID | None = None,
    target: User | None = None,
    **detail: Any,
) -> AuditEvent:
    """Add an entry: of the home when `home_id` is given, else of the instance."""
    unknown = set(detail) - ALLOWED_DETAIL
    if unknown:
        raise ValueError(f"Audit detail may not carry: {', '.join(sorted(unknown))}")
    return AuditEvent.objects.create(
        scope=Scope.HOME if home_id else Scope.INSTANCE,
        action=action,
        actor=actor if isinstance(actor, User) else None,
        target_user=target,
        home_id=home_id,
        detail=detail,
    )


def home_log(actor: User | AnonymousUser, home_id: UUID) -> models.QuerySet[AuditEvent]:
    """Entries of a home, for its owners only."""
    from housecairn.homes.models import Membership, Role

    owner = (
        actor.is_authenticated
        and Membership.objects.filter(home_id=home_id, user=actor, role=Role.OWNER).exists()
    )
    if not owner:
        raise PermissionDenied
    return AuditEvent.objects.filter(scope=Scope.HOME, home_id=home_id).select_related(
        "actor", "target_user"
    )


def instance_log(actor: User | AnonymousUser) -> models.QuerySet[AuditEvent]:
    """Entries of the instance, for its administrators only; never a home's."""
    from housecairn.accounts.services import is_instance_admin

    if not is_instance_admin(actor):
        raise PermissionDenied
    return AuditEvent.objects.filter(scope=Scope.INSTANCE).select_related("actor", "target_user")
