"""allauth adapters: sign-up is closed unless the operator opens it (docs/adr/0007)."""

import logging
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.http import HttpRequest
from django.template.response import TemplateResponse

from housecairn.accounts import services
from housecairn.accounts.models import User
from housecairn.accounts.services import Decision

logger = logging.getLogger("housecairn.security")


class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return bool(settings.HOUSECAIRN_SIGNUP_OPEN)

    def is_safe_url(self, url: str | None) -> bool:
        # allauth 65.21 parses `next` with urlparse before Django checks it, and
        # urlparse raises ValueError on an address such as "//[" (a server error
        # on the sign-in page). Such an address is simply not safe.
        try:
            return bool(super().is_safe_url(url))
        except ValueError:
            return False


def provider_identity(sociallogin: SocialLogin) -> tuple[str | None, bool]:
    """The address the identity provider asserts, and whether it says it is verified.

    Read from the claims themselves (userinfo, else the ID token), and only a
    JSON `true` counts as verified: a string such as "false" must not. Claims
    that are not a JSON object are ignored, so that a provider returning
    something else is refused rather than failing the sign-in.
    """
    data: Any = sociallogin.account.extra_data
    data = data if isinstance(data, dict) else {}
    candidates = (data.get("userinfo"), data.get("id_token"), data)
    claims: dict[str, Any] = next((c for c in candidates if isinstance(c, dict) and c), {})
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        return None, False
    return email.strip(), claims.get("email_verified") is True


def refuse(request: HttpRequest) -> ImmediateHttpResponse:
    logger.info("OIDC sign-in refused: no matching account and sign-up is closed")
    response = TemplateResponse(request, "accounts/oidc_signup_refused.html", status=403)
    return ImmediateHttpResponse(response.render())


class SocialAccountAdapter(DefaultSocialAccountAdapter):  # type: ignore[misc]
    """Called by allauth only for an identity that has no account yet."""

    def is_open_for_signup(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        if services.oidc_signup_decision(*provider_identity(sociallogin)) is Decision.REFUSED:
            raise refuse(request)
        return True

    def save_user(self, request: HttpRequest, sociallogin: SocialLogin, form: Any = None) -> User:
        email, verified = provider_identity(sociallogin)
        user: User = sociallogin.user
        decision = services.oidc_signup_decision(email, verified)
        if decision is Decision.BOOTSTRAP_ADMIN:
            try:
                return services.create_first_admin(
                    user, lambda: self._save_bootstrap(request, sociallogin, form, email)
                )
            except services.FirstAccountTakenError:
                # Someone else was first: the regular rules apply from now on.
                decision = services.oidc_signup_decision(email, verified)
        if decision is not Decision.MEMBER:
            raise refuse(request)
        user.is_staff = False
        user.is_superuser = False
        saved: User = super().save_user(request, sociallogin, form)
        # The provider vouched for the address: an invitation to the instance for it is used.
        if email and verified:
            from housecairn.instance.services import accept_for_identity

            accept_for_identity(saved)
        return saved

    def _save_bootstrap(
        self, request: HttpRequest, sociallogin: SocialLogin, form: Any, email: str | None
    ) -> User:
        saved: User = super().save_user(request, sociallogin, form)
        # The sign-up form could change the address: a pinned administrator
        # keeps the verified address the provider asserted.
        if settings.HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL and not (
            email and services.same_address(saved.email, email)
        ):
            raise refuse(request)
        return saved
