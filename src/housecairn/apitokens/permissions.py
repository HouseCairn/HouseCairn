"""Scope checks for requests authenticated by an API token.

- `read`: safe methods (GET, HEAD, OPTIONS) on regular endpoints;
- `write`: other methods on regular endpoints;
- `events`: only endpoints that declare `token_scope = Scope.EVENTS`, and on
  those, nothing else is accepted.

Session-authenticated requests are not concerned: their rights come from the
user's role in the home, checked by the services.
"""

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.request import Request

from housecairn.apitokens.models import ApiToken, Scope


def required_scope(request: Request, view: Any) -> Scope:
    if getattr(view, "token_scope", None) == Scope.EVENTS:
        return Scope.EVENTS
    if request.method in permissions.SAFE_METHODS:
        return Scope.READ
    return Scope.WRITE


class TokenScopePermission(permissions.BasePermission):
    message = _("This token does not have the scope this request needs.")

    def has_permission(self, request: Request, view: Any) -> bool:
        token = request.auth
        if not isinstance(token, ApiToken):
            return True
        return token.has_scope(required_scope(request, view))
