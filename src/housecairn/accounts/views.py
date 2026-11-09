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

from housecairn.accounts import forms, provider_names, services
from housecairn.accounts.models import DisplayNameSource, User


def needs_email(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Answer 404 when the instance cannot send email, otherwise run the view."""

    @wraps(view)
    def guarded(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not services.email_is_configured():
            raise Http404("Outgoing email is not configured.")
        return view(request, *args, **kwargs)

    return guarded


class LoginView(allauth_views.LoginView):  # type: ignore[misc]
    """allauth's sign-in page, which opens the session before the page can ask for anything.

    The page fetches a passkey challenge as soon as it loads (docs/adr/0018), and that
    request writes the challenge in the session. Without a session yet, it would create
    one: if the person signs in with a password before the challenge answers, the late
    answer would hand the browser that new, signed-out session instead of the one of the
    sign-in (tests/test_session_race.py). With the session opened here, the late answer
    finds it replaced by the sign-in and sets no cookie.
    """

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.session.session_key is None:
            request.session.create()
        response: HttpResponse = super().get(request, *args, **kwargs)
        return response


login = LoginView.as_view()
email_addresses = needs_email(allauth_views.email)
password_reset = needs_email(allauth_views.password_reset)
password_reset_done = needs_email(allauth_views.password_reset_done)


class AccountDeleteView(LoginRequiredMixin, FormView[forms.DeleteAccountForm]):
    """Erase the account: the right to erasure, with the last-owner rule (docs/adr/0023)."""

    template_name = "accounts/delete.html"
    form_class = forms.DeleteAccountForm

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "user": self.request.user, "request": self.request}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["blocking"] = services.homes_blocking_erasure(user)  # type: ignore[arg-type]
        context["last_admin"] = services.is_last_instance_admin(user)  # type: ignore[arg-type]
        return context

    def form_valid(self, form: forms.DeleteAccountForm) -> HttpResponse:
        try:
            services.delete_account(self.request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        logout(self.request)
        messages.success(self.request, _("Your account was deleted."))
        return redirect("account_login")


class ProfileView(LoginRequiredMixin, FormView[forms.ProfileForm]):
    """How the person is named to the others (docs/adr/0045)."""

    template_name = "accounts/profile.html"
    form_class = forms.ProfileForm

    def get_initial(self) -> dict[str, Any]:
        return {"display_name": self.request.user.display_name}  # type: ignore[union-attr]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from housecairn.instance.providers import provider_label

        context = super().get_context_data(**kwargs)
        user: User = self.request.user  # type: ignore[assignment]
        by_provider = user.display_name_source == DisplayNameSource.OIDC
        context["linked"] = provider_names.has_provider(user)
        context["by_provider"] = by_provider
        context["taken_from"] = (
            provider_label(user.display_name_provider)
            if by_provider and user.display_name_provider and user.display_name
            else ""
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if "use_provider" not in request.POST:
            return super().post(request, *args, **kwargs)
        user: User = request.user  # type: ignore[assignment]
        if not provider_names.has_provider(user):
            return redirect("profile")
        if provider_names.use_provider_name(user):
            messages.success(request, _("Your display name is now the one of your provider."))
        else:
            messages.success(
                request,
                _("Your display name will be taken from your provider at your next sign-in."),
            )
        return redirect("profile")

    def form_valid(self, form: forms.ProfileForm) -> HttpResponse:
        try:
            services.set_display_name(
                self.request.user,  # type: ignore[arg-type]
                form.cleaned_data["display_name"],
            )
        except ValidationError as exc:
            form.add_error("display_name", exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Profile saved."))
        return redirect("profile")


class SignupView(allauth_views.SignupView):  # type: ignore[misc]
    """allauth's sign-up page, whose form also gets the request (for the proof of work)."""

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "request": self.request}
