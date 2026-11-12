"""Guards of the accounts on a demonstration instance, on the models themselves.

They hold whatever the path: a screen, the API, the administration site, a form of
django-allauth or a command. Outside `reset_demo`, on a demonstration instance:

- no account is created;
- a public account keeps its password, its address, its rights and its active state, and
  is not deleted;
- no address is added to or removed from a public account, and no second factor
  (authenticator app, recovery codes, security key) is added to or removed from it, which
  would lock the other visitors out.
"""

from typing import Any

from django.contrib.auth.hashers import check_password
from django.db.models.signals import pre_delete, pre_save
from django.utils.translation import gettext as _

from housecairn.demo import mode

# The fields of a public account that a visitor could use to take it from the others.
PROTECTED_FIELDS = ("email", "password", "is_active", "is_staff", "is_superuser")


def _account_message() -> str:
    return _("This is a demonstration account: its password, address and access stay as they are.")


def _user_saving(sender: Any, instance: Any, raw: bool = False, **_kwargs: Any) -> None:
    if not mode.guarded() or raw:
        return
    if instance._state.adding:
        raise mode.DemoRefusedError(
            _("This is a demonstration instance: no account can be created on it.")
        )
    before = sender.all_objects if hasattr(sender, "all_objects") else sender._default_manager
    row = before.filter(pk=instance.pk).values(*PROTECTED_FIELDS).first()
    if row is None or not mode.is_demo_address(row["email"]):
        return
    changed = [name for name in PROTECTED_FIELDS if getattr(instance, name) != row[name]]
    # A sign-in may store the same password hashed again, when Django strengthens its
    # hasher: still the public password, so allowed.
    if changed == ["password"] and check_password(mode.PASSWORD, instance.password):
        return
    if changed:
        raise mode.DemoRefusedError(_account_message())


def _user_deleting(sender: Any, instance: Any, **_kwargs: Any) -> None:
    if mode.guarded() and mode.is_demo_address(instance.email):
        raise mode.DemoRefusedError(_account_message())


def _owned_by_demo_account(instance: Any) -> bool:
    user = getattr(instance, "user", None)
    return user is not None and mode.is_demo_address(user.email)


def _account_row_changing(sender: Any, instance: Any, raw: bool = False, **_kwargs: Any) -> None:
    """An address or a second factor of a public account: refused, added or removed."""
    if mode.guarded() and not raw and _owned_by_demo_account(instance):
        raise mode.DemoRefusedError(_account_message())


def connect() -> None:
    from allauth.account.models import EmailAddress
    from allauth.mfa.models import Authenticator
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    pre_save.connect(_user_saving, sender=user_model, dispatch_uid="demo-user-save")
    pre_delete.connect(_user_deleting, sender=user_model, dispatch_uid="demo-user-delete")
    for model in (EmailAddress, Authenticator, SocialAccount):
        uid = f"demo-{model._meta.label_lower}"
        pre_save.connect(_account_row_changing, sender=model, dispatch_uid=f"{uid}-save")
        pre_delete.connect(_account_row_changing, sender=model, dispatch_uid=f"{uid}-delete")
