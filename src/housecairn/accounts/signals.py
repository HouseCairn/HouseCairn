"""Keeps `InstanceSetup` in step with accounts created outside OIDC sign-in."""

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest

from housecairn.accounts import services
from housecairn.accounts.models import User


@receiver(post_save, sender=User, dispatch_uid="housecairn.accounts.record_first_account")
def record_first_account(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    if created and not kwargs.get("raw", False):
        services.record_first_account(instance)


@receiver(user_logged_in, dispatch_uid="housecairn.accounts.note_sign_in")
def note_sign_in(sender: Any, request: HttpRequest | None, user: User, **kwargs: Any) -> None:
    if request is not None:
        secret = services.note_sign_in(request, user)
        if secret:
            # The middleware sets the cookie on the response of this request.
            request.housecairn_new_device = secret  # type: ignore[attr-defined]
