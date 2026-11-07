"""Single sign-on providers, as far as homes are concerned (docs/adr/0021).

Providers are declared by the instance administrator only (the `OIDC_*`
variables, read by django-allauth). A home can require one of them; whether a
request satisfies that is read from the authentication records django-allauth
keeps in the session, never from anything the client sends.
"""

from dataclasses import dataclass

from allauth.account.authentication import get_authentication_records
from allauth.socialaccount.adapter import get_adapter
from django.http import HttpRequest
from rest_framework.request import Request

from housecairn.apitokens.models import ApiToken


@dataclass(frozen=True)
class Provider:
    id: str
    name: str


def declared_providers(request: HttpRequest | Request | None = None) -> list[Provider]:
    """The providers this instance offers, in declaration order."""
    apps = get_adapter().list_apps(request)
    return [Provider(id=app.provider_id or app.provider, name=app.name) for app in apps]


def provider_named(provider_id: str, request: HttpRequest | Request | None = None) -> Provider:
    """The declared provider with this identifier; a placeholder if it is gone."""
    for provider in declared_providers(request):
        if provider.id == provider_id:
            return provider
    return Provider(id=provider_id, name=provider_id)


def signed_in_providers(request: HttpRequest | Request) -> frozenset[str]:
    """Providers through which this session signed in.

    A request authenticated by an API token has none: a token is not a sign-in
    through a provider, so it never opens a home that requires one.
    """
    if isinstance(getattr(request, "auth", None), ApiToken):
        return frozenset()
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return frozenset()
    session_request = request._request if isinstance(request, Request) else request
    records = get_authentication_records(session_request, user)
    return frozenset(
        record["provider"]
        for record in records
        if isinstance(record, dict)
        and record.get("method") == "socialaccount"
        and isinstance(record.get("provider"), str)
    )
