"""What each audit action says, in the language of the person reading the log."""

from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

LABELS: dict[str, Promise] = {
    # Home scope.
    "home.created": _("Home created"),
    "member.role_changed": _("Role changed to %(role)s"),
    "member.removed": _("Member removed"),
    "member.left": _("Member left"),
    "ownership.transferred": _("Ownership transferred"),
    "invitation.sent": _("Invitation sent (%(role)s)"),
    "invitation.resent": _("Invitation sent again"),
    "invitation.revoked": _("Invitation revoked"),
    "invitation.accepted": _("Invitation accepted (%(role)s)"),
    "sso.required": _("Sign-in through %(provider)s required"),
    "sso.lifted": _("Sign-in requirement removed"),
    "home.exported": _("Home exported"),
    # Instance scope.
    "instance_invitation.sent": _("Instance invitation sent"),
    "instance_invitation.resent": _("Instance invitation sent again"),
    "instance_invitation.revoked": _("Instance invitation revoked"),
    "instance_invitation.accepted": _("Instance invitation accepted"),
    "account.created": _("Account created"),
    "account.deleted": _("Account deleted"),
    "home.deleted": _("A home was deleted"),
    "homes.unlocked": _("Sign-in requirement removed from %(count)s homes"),
    "settings.changed": _("Setting %(setting)s changed from %(old)s to %(new)s"),
    "settings.secret_changed": _("Secret setting %(setting)s changed"),
    "settings.reset": _("Setting %(setting)s reset to its default"),
    "admin.user_changed": _("Account changed in the administration site"),
    "admin.user_deleted": _("Account deleted in the administration site"),
}


def label(action: str, detail: dict[str, Any]) -> str:
    """The sentence for an entry; an unknown action is shown as its code."""
    from housecairn.homes.models import Role

    template = LABELS.get(action)
    if template is None:
        return action
    values = dict(detail)
    for key in ("role", "previous_role"):
        if key in values and values[key] in Role.values:
            values[key] = Role(values[key]).label
    try:
        return str(template) % values
    except (KeyError, TypeError):
        return str(template).split(" (")[0].split(" %(")[0]
