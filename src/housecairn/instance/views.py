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
from django.urls import get_script_prefix, reverse
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
from housecairn.homes import quotas, sso
from housecairn.homes import services as home_services
from housecairn.homes.forms import InvitationSignupForm
from housecairn.homes.models import Home
from housecairn.homes.scoping import allow
from housecairn.instance import config, emails, providers, registry, services
from housecairn.instance import settings_services as services_settings
from housecairn.instance.forms import InstanceInviteForm, ProviderForm, SettingsSectionForm
from housecairn.instance.models import InstanceInvitation, OidcProvider
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
        page.object_list = audit.name_people(page.object_list)
        context["page"] = page
        return context


class UsageView(InstanceAdminMixin, TemplateView):
    """Space and files each home takes, against the quotas (docs/adr/0042).

    A home is its identifier and its numbers: no name, no member, no file (docs/adr/0022).
    """

    template_name = "instance/usage.html"
    paginate_by = 50

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        page = Paginator(quotas.by_home(), self.paginate_by).get_page(self.request.GET.get("page"))
        context.update(page=page, limits=quotas.limits())
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


SERVER_SECTION = "server"


def _section_url(section: str) -> str:
    """The sub-page of a section. Both routes carry the name `instance:settings`, so that the
    tab, the help link and the API parity see one screen."""
    return reverse("instance:settings", kwargs={"section": section})


def _section_of(slug: str) -> registry.Section:
    try:
        return registry.Section(slug)
    except ValueError as exc:
        raise Http404 from exc


class SettingsView(InstanceAdminMixin, TemplateView):
    """Index of the settings of the instance, one line per section (docs/adr/0035)."""

    template_name = "instance/settings.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # The old single page linked its sections by `#section`; `?section=` is the same
        # request made by hand or by a bookmark.
        wanted = request.GET.get("section", "")
        if wanted == SERVER_SECTION or wanted in {s.value for s in registry.Section}:
            return redirect(_section_url(wanted))
        response: HttpResponse = super().get(request, *args, **kwargs)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sections = []
        for section in registry.Section:
            states = [config.describe(s.key) for s in registry.in_section(section)]
            sections.append(
                {
                    "label": registry.SECTION_LABELS[section],
                    "url": _section_url(section.value),
                    "count": len(states),
                    "locked": sum(1 for state in states if state.locked),
                }
            )
        context.update(sections=sections, server_url=_section_url(SERVER_SECTION))
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # A form of the old single page, still open in a tab: 307 keeps the method and the
        # body, so that the sub-page answers it as it would have.
        section = request.POST.get("section", "")
        _section_of(section)
        return HttpResponseRedirect(_section_url(section), status=307)


class SettingsSectionView(InstanceAdminMixin, TemplateView):
    """The settings of one section, each paired with its variable, with one Save button."""

    template_name = "instance/settings_section.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        self.slug: str = kwargs["section"]
        self.section: registry.Section | None = None
        if self.slug != SERVER_SECTION:
            self.section = _section_of(self.slug)
        response: HttpResponseBase = super().dispatch(request, *args, **kwargs)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["docs_settings_url"] = docs_page_url("administration/settings/", get_language())
        if self.section is None:
            context.update(
                title=_("Server"),
                server_rows=_server_rows(),
                server=True,
            )
            return context
        section = self.section
        form: SettingsSectionForm = kwargs.get("bound") or SettingsSectionForm(section)
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
        context.update(
            title=registry.SECTION_LABELS[section],
            save_label=registry.SECTION_SAVE_LABELS[section],
            form=form,
            items=items,
            test_email=section is registry.Section.EMAIL,
            server=False,
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.section is None:
            raise Http404
        section = self.section
        url = _section_url(self.slug)
        if (response := _reauthenticate_to(request, url)) is not None:
            return response
        actor: User = request.user  # type: ignore[assignment]
        reset_key = request.POST.get("reset", "")
        if reset_key:
            return self._reset(request, actor, section, reset_key)
        if "test_email" in request.POST:
            return self._test_email(request, actor)
        # Only the fields of this section are read: a field of another section that comes
        # with the request is not one of the form's, and is dropped.
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
            return self.render_to_response(self.get_context_data(bound=form), status=409)
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
                return redirect(url)
        return self.render_to_response(self.get_context_data(bound=form), status=422)

    def _reset(
        self, request: HttpRequest, actor: User, section: registry.Section, key: str
    ) -> HttpResponse:
        setting = registry.SETTINGS.get(key)
        if setting is None or setting.section is not section:
            # Another section's key, or none: refused, so that a page only acts on its own.
            raise Http404
        try:
            services_settings.reset(actor, key)
        except ValidationError as exc:
            messages.error(request, " ".join(m for ms in exc.message_dict.values() for m in ms))
        else:
            messages.success(request, _("Default restored."))
        return redirect(_section_url(self.slug))

    def _test_email(self, request: HttpRequest, actor: User) -> HttpResponse:
        if self.section is not registry.Section.EMAIL:
            raise Http404
        if not allow(request, "housecairn_settings_test"):
            messages.error(request, _("Too many tests in a short time. Try again later."))
        else:
            ok, text = services_settings.check_email(actor)
            (messages.success if ok else messages.error)(request, text)
        return redirect(_section_url(self.slug))


def _reauthenticate_to(request: HttpRequest, url: str) -> HttpResponse | None:
    if signed_in_recently(request):
        return None
    messages.warning(
        request, _("Confirm your sign-in to change settings, then make the change again.")
    )
    return redirect(f"{reverse('account_reauthenticate')}?{urlencode({'next': url})}")


def _form_errors(form: ProviderForm, exc: ValidationError) -> None:
    for key, errors in exc.message_dict.items():
        for error in errors:
            form.add_error(key if key in form.fields else None, error)


def _test_issuer(request: HttpRequest, form: ProviderForm) -> None:
    """The test button: checks the issuer typed in the form; saves nothing."""
    if not allow(request, "housecairn_settings_test"):
        messages.error(request, _("Too many tests in a short time. Try again later."))
        return
    ok, text = providers.check(request.user, str(form.data.get("issuer", "")))  # type: ignore[arg-type]
    (messages.success if ok else messages.error)(request, text)


class ProvidersView(InstanceAdminMixin, TemplateView):
    """The sign-in providers: those of the variables, read only, and those of the interface."""

    template_name = "instance/providers.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(
            providers=providers.describe_all(),
            form=kwargs.get("form") or ProviderForm(),
            callback_base=self.request.build_absolute_uri(f"{get_script_prefix()}accounts/oidc/"),
            variables=providers.ENVIRONMENT_VARIABLES,
            docs_url=docs_page_url("administration/oidc/", get_language()),
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = ProviderForm(request.POST)
        if "test" in request.POST:
            _test_issuer(request, form)
            form.is_valid()
            return self.render_to_response(self.get_context_data(form=form))
        if (response := _reauthenticate_to(request, reverse("instance:providers"))) is not None:
            return response
        if form.is_valid():
            try:
                provider = providers.create(request.user, form.data_for_service())  # type: ignore[arg-type]
            except ValidationError as exc:
                _form_errors(form, exc)
            else:
                messages.success(request, _("Provider added."))
                return redirect("instance:provider", slug=provider.slug)
        return self.render_to_response(self.get_context_data(form=form), status=422)


class ProviderView(InstanceAdminMixin, TemplateView):
    """One provider of the interface: change, test, delete. One set by variables is a 404."""

    template_name = "instance/provider.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        self.provider = OidcProvider.objects.filter(slug=kwargs["slug"]).first()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        if self.provider is None:
            raise Http404
        context = super().get_context_data(**kwargs)
        initial = {f: getattr(self.provider, f) for f in providers.EDITABLE}
        context.update(
            provider=self.provider,
            state=providers.describe(self.provider),
            form=kwargs.get("form") or ProviderForm(initial=initial, editing=True),
            callback=self.request.build_absolute_uri(
                reverse("openid_connect_callback", kwargs={"provider_id": self.provider.slug})
            ),
            docs_url=docs_page_url("administration/oidc/", get_language()),
        )
        return context

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if self.provider is None:
            raise Http404
        here = reverse("instance:provider", kwargs={"slug": self.provider.slug})
        form = ProviderForm(request.POST, editing=True)
        if "test" in request.POST:
            _test_issuer(request, form)
            form.is_valid()
            return self.render_to_response(self.get_context_data(form=form))
        if (response := _reauthenticate_to(request, here)) is not None:
            return response
        actor: User = request.user  # type: ignore[assignment]
        if "delete" in request.POST:
            try:
                providers.delete(actor, self.provider)
            except ValidationError as exc:
                for message in exc.messages:
                    messages.error(request, message)
                return redirect(here)
            messages.success(request, _("Provider deleted."))
            return redirect("instance:providers")
        if form.is_valid():
            had_secret = bool(self.provider.secret)
            try:
                changed = providers.update(actor, self.provider, form.data_for_service())
            except ValidationError as exc:
                _form_errors(form, exc)
            else:
                self.provider.refresh_from_db()
                if had_secret and not self.provider.secret:
                    messages.warning(
                        request,
                        _(
                            "Provider saved. The new issuer cleared the client secret: "
                            "enter it again before you enable the provider."
                        ),
                    )
                else:
                    messages.success(
                        request, _("Provider saved.") if changed else _("Nothing to change.")
                    )
                return redirect(here)
        return self.render_to_response(self.get_context_data(form=form), status=422)


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
