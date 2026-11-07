"""Keeps `InstanceSetup` in step with accounts created outside OIDC sign-in."""

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from housecairn.accounts import services
from housecairn.accounts.models import User


@receiver(post_save, sender=User, dispatch_uid="housecairn.accounts.record_first_account")
def record_first_account(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    if created and not kwargs.get("raw", False):
        services.record_first_account(instance)
