"""allauth adapters: sign-up is closed unless the operator opens it."""

from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return bool(settings.HOUSECAIRN_SIGNUP_OPEN)


class SocialAccountAdapter(DefaultSocialAccountAdapter):  # type: ignore[misc]
    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any) -> bool:
        # With single sign-on, the identity provider decides who may sign in.
        return bool(settings.HOUSECAIRN_OIDC_SIGNUP_OPEN)
