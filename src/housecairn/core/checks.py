"""System checks for settings Django does not know about (`manage.py check --deploy`)."""

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register  # noqa: A004


@register(Tags.security, deploy=True)
def site_url_with_email(app_configs: Any, **kwargs: Any) -> list[Warning]:
    """Links in emails must not be built from the Host header of a request.

    Without `HOUSECAIRN_SITE_URL`, an invitation or reset link takes the host of
    the request that triggered it. `ALLOWED_HOSTS` limits that to the names the
    instance answers to, but with several names, or a proxy that lets a request
    choose its host, the link can point where the operator did not intend: set
    the public address (docs/administration/variables.md).
    """
    if settings.EMAIL_HOST and not settings.HOUSECAIRN_SITE_URL:
        return [
            Warning(
                "EMAIL_HOST is set but HOUSECAIRN_SITE_URL is not.",
                hint=(
                    "Set HOUSECAIRN_SITE_URL to the public address of the instance, such as "
                    "https://home.example.com: otherwise links in emails take the Host header "
                    "of the request."
                ),
                id="housecairn.W001",
            )
        ]
    return []


@register(Tags.security)
def open_sign_up_needs_email(app_configs: Any, **kwargs: Any) -> list[Error]:
    """Open sign-up verifies addresses by email: it cannot work, nor be safe, without it."""
    from housecairn.accounts.services import email_is_configured

    if settings.HOUSECAIRN_SIGNUP_OPEN and not email_is_configured():
        return [
            Error(
                "HOUSECAIRN_SIGNUP_OPEN needs outgoing email.",
                hint=(
                    "Open sign-up verifies each address by email. Set EMAIL_HOST, or close "
                    "sign-up and invite people instead (docs/administration/sign-up.md)."
                ),
                id="housecairn.E001",
            )
        ]
    return []
