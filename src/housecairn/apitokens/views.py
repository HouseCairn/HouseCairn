"""The screen of API tokens: list, creation (the secret is shown once) and revocation."""

from typing import Any
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView

from housecairn.accounts.models import User
from housecairn.apitokens import services
from housecairn.apitokens.forms import TokenForm
from housecairn.apitokens.models import ApiToken, Scope
from housecairn.core import navigation
from housecairn.homes import services as home_services
from housecairn.homes import sso


@method_decorator(never_cache, name="dispatch")
class TokenListView(LoginRequiredMixin, TemplateView):
    """My tokens: what each can do and where it was last used, never its value."""

    template_name = "apitokens/token_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        user: User = self.request.user  # type: ignore[assignment]
        now = timezone.now()
        rows = [
            {
                "token": token,
                "rights": [Scope(scope).label for scope in token.scopes],
                "homes": sorted(home.name for home in token.homes.all()),
                "expired": token.expires_at is not None and token.expires_at <= now,
            }
            for token in services.tokens_of(user)
        ]
        # Every person with a home may create a token: a home that requires a provider is
        # offered on the form, disabled until the session signs in through it.
        return super().get_context_data(
            rows=rows, has_homes=services.token_homes(user).exists(), **kwargs
        )


@method_decorator(never_cache, name="dispatch")
class TokenCreateView(LoginRequiredMixin, FormView[TokenForm]):
    """The form, then the page that shows the new secret once: there is no page to open it again."""

    template_name = "apitokens/token_form.html"
    form_class = TokenForm
    request: HttpRequest

    def get_form_kwargs(self) -> dict[str, Any]:
        return {
            **super().get_form_kwargs(),
            "user": self.request.user,
            "signed_in_with": sso.signed_in_providers(self.request),
            "providers": sso.declared_providers(self.request),
        }

    def form_valid(self, form: TokenForm) -> HttpResponse:
        user: User = self.request.user  # type: ignore[assignment]
        data = form.cleaned_data
        try:
            token, raw = services.create_token(
                user,
                name=data["name"],
                scopes=data["scopes"],
                homes=data["homes"],
                lifetime_days=data["lifetime_days"],
                signed_in_with=sso.signed_in_providers(self.request),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        except home_services.SsoRequiredError as exc:
            provider = sso.provider_named(exc.provider_id, self.request)
            form.add_error(
                "homes",
                _(
                    "%(home)s opens only after signing in through %(provider)s: continue with "
                    "it, then create the token."
                )
                % {"home": exc.home.name, "provider": provider.name},
            )
            return self.form_invalid(form)
        response = TemplateResponse(
            self.request, "apitokens/token_created.html", {"created": token, "secret": raw}
        )
        response["Cache-Control"] = "no-store"
        return response


@method_decorator(never_cache, name="dispatch")
class TokenRevokeView(LoginRequiredMixin, View):
    """Revoke after a confirmation page; the token stops working with its next request."""

    request: HttpRequest

    def get_token(self, token_id: UUID) -> ApiToken:
        user: User = self.request.user  # type: ignore[assignment]
        found: ApiToken = get_object_or_404(services.tokens_of(user), pk=token_id)
        return found

    def get(self, request: HttpRequest, token_id: UUID) -> HttpResponse:
        token = self.get_token(token_id)
        return TemplateResponse(
            request,
            "apitokens/token_revoke.html",
            {
                "token": token,
                "cancel_url": navigation.back_url(request, reverse("api-tokens:list")),
            },
        )

    def post(self, request: HttpRequest, token_id: UUID) -> HttpResponse:
        token = self.get_token(token_id)
        services.revoke_token(request.user, token)  # type: ignore[arg-type]
        messages.success(request, _("Token revoked: it no longer works."))
        return redirect(
            navigation.after_delete(request, reverse("api-tokens:list"), gone=[token.id])
        )
