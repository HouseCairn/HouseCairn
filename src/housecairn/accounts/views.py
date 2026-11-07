"""Guards on allauth views that need outgoing email (docs/adr/0007)."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from allauth.account import views as allauth_views
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.generic import FormView

from housecairn.accounts import forms, services
from housecairn.homes.scoping import allow


def needs_email(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Answer 404 when the instance cannot send email, otherwise run the view."""

    @wraps(view)
    def guarded(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not services.email_is_configured():
            raise Http404("Outgoing email is not configured.")
        return view(request, *args, **kwargs)

    return guarded


email_addresses = needs_email(allauth_views.email)
password_reset = needs_email(allauth_views.password_reset)
password_reset_done = needs_email(allauth_views.password_reset_done)


class AccountDeleteView(LoginRequiredMixin, FormView[forms.DeleteAccountForm]):
    """Erase the account: the right to erasure, with the last-owner rule (docs/adr/0023)."""

    template_name = "accounts/delete.html"
    form_class = forms.DeleteAccountForm

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["blocking"] = services.homes_blocking_erasure(user)  # type: ignore[arg-type]
        context["last_admin"] = services.is_last_instance_admin(user)  # type: ignore[arg-type]
        return context

    def form_valid(self, form: forms.DeleteAccountForm) -> HttpResponse:
        if not allow(self.request, "housecairn_delete_account"):
            form.add_error(None, _("Too many attempts. Try again later."))
            return self.form_invalid(form)
        try:
            services.delete_account(self.request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        logout(self.request)
        messages.success(self.request, _("Your account was deleted."))
        return redirect("account_login")


class SignupView(allauth_views.SignupView):  # type: ignore[misc]
    """allauth's sign-up page, whose form also gets the request (for the proof of work)."""

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "request": self.request}
