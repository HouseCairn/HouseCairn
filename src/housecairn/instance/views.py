"""Web screens of the instance administrator, and the page of an instance invitation.

None of them shows a home: invitations, a few counts, the audit log of the
instance (docs/adr/0022, 0023).
"""

from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views import View
from django.views.generic import TemplateView

from housecairn.accounts import services as account_services
from housecairn.accounts.models import User
from housecairn.audit import services as audit
from housecairn.core.help import docs_page_url
from housecairn.homes import services as home_services
from housecairn.homes import sso
from housecairn.homes.forms import InvitationSignupForm
from housecairn.homes.models import Home
from housecairn.homes.scoping import allow
from housecairn.instance import config, emails, registry, services
from housecairn.instance import settings_services as services_settings
from housecairn.instance.forms import InstanceInviteForm, SettingsSectionForm
from housecairn.instance.models import InstanceInvitation
from housecairn.instance.reauth import signed_in_recently

DELIVERY_FAILED = _lazy(
    "The invitation is saved, but the email could not be sent. "
    "Try Send again later, or check the outgoing email settings."
)


class InstanceAdminMixin(LoginRequiredMixin):
    """Administrators only; anyone else signed in gets a 404, as if the page did not exist."""

    request: HttpRequest

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if request.user.is_authenticated and not account_services.is_instance_admin(request.user):
            raise Http404
        response: HttpResponseBase = super().dispatch(request, *args, **kwargs)
        return response


class OverviewView(InstanceAdminMixin, TemplateView):
    template_name = "instance/overview.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        declared = [p.id for p in sso.declared_providers(self.request)]
        email_ready = account_services.email_is_configured()
        context.update(
            invite_form=kwargs.get("invite_form") or InstanceInviteForm(),
            invitations=services.pending_invitations(),
            email_configured=email_ready,
            signup_open=account_services.signup_is_open(),
            accounts=User.objects.count(),
            providers=sso.declared_providers(self.request),
            stale_homes=Home.objects.exclude(required_provider="")
            .exclude(required_provider__in=declared)
            .count(),
        )
        return context


class InstanceActionView(InstanceAdminMixin, View):
    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            self.act()
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
        except home_services.DeliveryFailedError:
            messages.warning(request, DELIVERY_FAILED)
        return redirect("instance:overview")

    def act(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def invitation(self) -> InstanceInvitation:
        invitation: InstanceInvitation = get_object_or_404(
            InstanceInvitation.objects.all(), id=self.kwargs["invitation_id"]
        )
        return invitation


class InviteView(InstanceActionView):
    def act(self) -> None:
        if not account_services.email_is_configured():
            raise ValidationError(
                _("This instance cannot send email: create the account in the administration site.")
            )
        form = InstanceInviteForm(self.request.POST)
        if not form.is_valid():
            raise ValidationError([e for errors in form.errors.values() for e in errors])
        if not allow(self.request, "housecairn_instance_invite"):
            raise ValidationError(_("Too many invitations in a short time. Try again later."))
        services.invite(
            self.request.user,  # type: ignore[arg-type]
            email=form.cleaned_data["email"],
            send=emails.sender_for(self.request),
        )
        messages.success(self.request, _("Invitation sent."))


class ResendView(InstanceActionView):
    def act(self) -> None:
        if not account_services.email_is_configured():
            raise ValidationError(_("This instance cannot send email."))
        if not allow(self.request, "housecairn_instance_invite"):
            raise ValidationError(_("Too many invitations in a short time. Try again later."))
        services.resend(
            self.request.user,  # type: ignore[arg-type]
            self.invitation(),
            send=emails.sender_for(self.request),
        )
        messages.success(self.request, _("Invitation sent again."))


class RevokeView(InstanceActionView):
    def act(self) -> None:
        services.revoke(self.request.user, self.invitation())  # type: ignore[arg-type]
        messages.success(self.request, _("Invitation revoked."))


class UnlockView(InstanceActionView):
    def act(self) -> None:
        count = services.unlock_removed_providers(
            self.request.user,  # type: ignore[arg-type]
            declared=[p.id for p in sso.declared_providers(self.request)],
        )
        messages.success(
            self.request,
            _("Sign-in requirement removed from %(count)s homes.") % {"count": count},
        )


class AuditView(InstanceAdminMixin, TemplateView):
    template_name = "instance/audit.html"
    paginate_by = 50

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        log = audit.instance_log(self.request.user)
        page = Paginator(log, self.paginate_by).get_page(self.request.GET.get("page"))
        context["page"] = page
        return context


class InstanceInvitationView(View):
    """The page an instance invitation link opens: create the account, or sign in.

    Every link that opens nothing (unknown, used, revoked, expired) gets the
    same page, and opening links is rate limited per client address.
    """

    http_method_names = ["get", "post"]

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not allow(request, "housecairn_invitation"):
            return TemplateResponse(request, "429.html", status=429).render()
        invitation = services.find(kwargs["token"])
        if invitation is None:
            return TemplateResponse(request, "homes/invitation_invalid.html", status=404).render()
        self.invitation = invitation
        self.token: str = kwargs["token"]
        return super().dispatch(request, *args, **kwargs)

    def render(self, **extra: Any) -> HttpResponse:
        user = self.request.user
        context = {
            "invitation": self.invitation,
            "same_address": user.is_authenticated
            and home_services.same_address(user.email, self.invitation.email),
            "account_exists": False,
            "providers": sso.declared_providers(self.request),
            "next_url": self.request.path,
            **extra,
        }
        return TemplateResponse(self.request, "instance/invitation.html", context).render()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = None if request.user.is_authenticated else self.signup_form()
        return self.render(form=form)

    def signup_form(self, data: Any = None) -> InvitationSignupForm:
        return InvitationSignupForm(data, email=self.invitation.email)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return self.accept(request.user)
        form = self.signup_form(request.POST)
        if not form.is_valid():
            return self.render(form=form)
        try:
            user = services.create_account(self.token, password=form.cleaned_data["password1"])
        except ValidationError:
            return self.render(form=None, account_exists=True)
        except InstanceInvitation.DoesNotExist as exc:
            raise Http404 from exc
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Welcome to HouseCairn. Add your first home."))
        return HttpResponseRedirect(reverse("homes:create"))

    def accept(self, user: User) -> HttpResponse:
        try:
            services.accept(user, self.token)
        except PermissionDenied:
            return self.render()
        except InstanceInvitation.DoesNotExist as exc:
            raise Http404 from exc
        messages.success(self.request, _("Invitation accepted. You can add a home."))
        return redirect("homes:list")


def _reauthenticate(request: HttpRequest) -> HttpResponse | None:
    """Send the administrator to confirm their sign-in, then back here (nothing is replayed).

    The submitted values are not kept: a secret typed in the form must not be stored in
    the session while the person re-authenticates.
    """
    if signed_in_recently(request):
        return None
    messages.warning(
        request, _("Confirm your sign-in to change settings, then make the change again.")
    )
    query = urlencode({"next": reverse("instance:settings")})
    return redirect(f"{reverse('account_reauthenticate')}?{query}")


def _server_rows() -> list[dict[str, Any]]:
    """What the environment alone decides, without any secret."""
    from django.conf import settings

    # The engine only: the address and credentials of a database stay in the variable.
    engine = str(settings.DATABASES["default"]["ENGINE"]).rsplit(".", 1)[-1]
    values: dict[str, str] = {
        "SECRET_KEY": _("set") if settings.SECRET_KEY else _("not set"),
        "ALLOWED_HOSTS": ", ".join(settings.ALLOWED_HOSTS) or "-",
        "CSRF_TRUSTED_ORIGINS": ", ".join(settings.CSRF_TRUSTED_ORIGINS) or "-",
        "DATABASE_URL": engine,
        "HOUSECAIRN_DATA_DIR": str(settings.DATA_DIR),
        "HOUSECAIRN_BEHIND_TLS_PROXY": _("yes")
        if settings.HOUSECAIRN_BEHIND_TLS_PROXY
        else _("no"),
        "HOUSECAIRN_FORWARDED_ALLOW_IPS": ", ".join(settings.HOUSECAIRN_FORWARDED_ALLOW_IPS),
        "DEBUG": _("yes") if settings.DEBUG else _("no"),
        "HOUSECAIRN_TASK_WORKERS": str(settings.Q_CLUSTER["workers"]),
        "HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL": (
            _("set") if settings.HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL else _("not set")
        ),
    }
    return [
        {"env": env, "label": label, "value": values[env]}
        for env, label in registry.SERVER_VARIABLES
    ]


class SettingsView(InstanceAdminMixin, TemplateView):
    """The settings of the instance, by section, each paired with its variable (docs/adr/0031)."""

    template_name = "instance/settings.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        bound: dict[registry.Section, SettingsSectionForm] = kwargs.get("bound", {})
        sections = []
        for section in registry.Section:
            form = bound.get(section) or SettingsSectionForm(section)
            items = []
            for setting in registry.in_section(section):
                state = config.describe(setting.key)
                items.append(
                    {
                        "state": state,
                        "setting": setting,
                        "field": form[setting.key] if setting.key in form.fields else None,
                        "shown": _display(state),
                        "default": _display_default(setting),
                    }
                )
            sections.append(
                {
                    "id": section.value,
                    "label": registry.SECTION_LABELS[section],
                    "form": form,
                    "items": items,
                    "test_email": section is registry.Section.EMAIL,
                }
            )
        context.update(
            sections=sections,
            server_rows=_server_rows(),
            docs_settings_url=docs_page_url("administration/settings/", get_language()),
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            section = registry.Section(request.POST.get("section", ""))
        except ValueError as exc:
            raise Http404 from exc
        if (response := _reauthenticate(request)) is not None:
            return response
        actor: User = request.user  # type: ignore[assignment]
        reset_key = request.POST.get("reset", "")
        if reset_key:
            return self._reset(request, actor, section, reset_key)
        if "test_email" in request.POST:
            return self._test_email(request, actor)
        form = SettingsSectionForm(section, request.POST)
        locked_sent = [
            setting
            for setting in registry.in_section(section)
            if setting.key in request.POST and config.is_locked(setting.key)
        ]
        if locked_sent:
            # The screen never sends a locked setting (its field has no name): a form older
            # than the variable, or a forged request. Refused by name, nothing is saved.
            form.is_valid()
            for setting in locked_sent:
                form.add_error(None, services_settings.locked_message(setting))
            return self.render_to_response(self.get_context_data(bound={section: form}), status=409)
        if form.is_valid():
            try:
                changed = services_settings.update(actor, form.changes())
            except ValidationError as exc:
                for key, errors in exc.message_dict.items():
                    for error in errors:
                        form.add_error(key if key in form.fields else None, error)
            else:
                messages.success(
                    request,
                    _("Settings saved.") if changed else _("Nothing to change."),
                )
                return redirect(f"{reverse('instance:settings')}#{section.value}")
        return self.render_to_response(self.get_context_data(bound={section: form}), status=422)

    def _reset(
        self, request: HttpRequest, actor: User, section: registry.Section, key: str
    ) -> HttpResponse:
        try:
            services_settings.reset(actor, key)
        except ValidationError as exc:
            messages.error(request, " ".join(m for ms in exc.message_dict.values() for m in ms))
        else:
            messages.success(request, _("Default restored."))
        return redirect(f"{reverse('instance:settings')}#{section.value}")

    def _test_email(self, request: HttpRequest, actor: User) -> HttpResponse:
        if not allow(request, "housecairn_settings_test"):
            messages.error(request, _("Too many tests in a short time. Try again later."))
        else:
            ok, text = services_settings.check_email(actor)
            (messages.success if ok else messages.error)(request, text)
        return redirect(f"{reverse('instance:settings')}#email")


def _display(state: config.State) -> str:
    """The effective value as text; a secret is only 'set' or 'not set'."""
    if state.setting.secret:
        return _("set") if state.is_set else _("not set")
    return _display_value(state.value)


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return _("yes") if value else _("no")
    if isinstance(value, list):
        return ", ".join(value) or _("(none)")
    return str(value) if value not in ("", None) else _("(none)")


def _display_default(setting: registry.Setting) -> str:
    return _display_value(setting.default)
