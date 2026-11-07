"""DRF authentication by `Authorization: Bearer hc_...`."""

from django.utils.translation import gettext_lazy as _
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.models import ApiToken


class ApiTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[User, ApiToken] | None:
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed(_("Invalid token header."))
        try:
            raw = header[1].decode("ascii")
        except UnicodeDecodeError as exc:
            raise exceptions.AuthenticationFailed(_("Invalid token header.")) from exc
        token = services.authenticate(raw)
        if token is None:
            raise exceptions.AuthenticationFailed(_("Invalid, expired or revoked token."))
        return token.user, token

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
