"""Web views of homes, households and invitations. Rules live in `services`."""

from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.accounts.services import email_is_configured
from housecairn.audit import services as audit_services
from housecairn.core import navigation
from housecairn.homes import exports, forms, services, sso
from housecairn.homes.models import Home, Invitation, Membership
from housecairn.homes.scoping import (
    WebHomeScopedMixin,
    allow,
    delivery_for,
    homes_for_request,
    invitation_link,
)
from housecairn.instance.config import get_setting

DELIVERY_FAILED = _lazy(
    "The invitation is saved, but the email could not be sent. "
    "Try Send again later, or ask the administrator to check the outgoing email settings."
)


class HomeListView(WebHomeScopedMixin, ListView[Home]):
    template_name = "homes/home_list.html"
    context_object_name = "homes"

    def get_queryset(self) -> models.QuerySet[Home]:
        # Every home of the user, those locked behind a sign-in provider too:
        # the list says which provider opens them (docs/adr/0021).
        return homes_for_request(self.request).order_by("name")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        providers = sso.signed_in_providers(self.request)
        context["rows"] = [
            {
                "home": home,
                "locked": not services.is_open(home, providers),
                "provider": sso.provider_named(home.required_provider, self.request),
            }
            for home in context["homes"]
        ]
        return context


class HomeCreateView(LoginRequiredMixin, FormView[forms.HomeForm]):
    template_name = "homes/home_form.html"
    form_class = forms.HomeForm

    def form_valid(self, form: forms.HomeForm) -> HttpResponse:
        home = services.create_home(
            self.request.user,  # type: ignore[arg-type]
            name=form.cleaned_data["name"],
            currency=form.cleaned_data["currency"],
            hemisphere=form.cleaned_data["hemisphere"],
        )
        return redirect(
            navigation.after_create(
                self.request,
                reverse("homes:detail", kwargs={"home_id": home.id}),
                "homes:list",
                added=_("Home added"),
                saved=_("Home added."),
            )
        )


class HomeDetailView(WebHomeScopedMixin, DetailView[Home]):
    template_name = "homes/home_detail.html"
    context_object_name = "home"

    def get_object(self, queryset: models.QuerySet[Home] | None = None) -> Home:
        return self.get_home()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["role"] = services.role_of(self.request.user, self.object)
        context["member_count"] = services.members(self.object).count()
        context["can_write"] = services.can_write(self.request.user, self.object)
        return context


class HomeEditView(WebHomeScopedMixin, FormView[forms.HomeForm]):
    """Name, currency and hemisphere of the home, for those who may write in it."""

    template_name = "homes/home_form.html"
    form_class = forms.HomeForm

    def get_form_kwargs(self) -> dict[str, Any]:
        home = self.get_home()
        if not services.can_write(self.request.user, home):
            raise PermissionDenied
        return {**super().get_form_kwargs(), "instance": home}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        return super().get_context_data(home=self.get_home(), editing=True, **kwargs)

    def form_valid(self, form: forms.HomeForm) -> HttpResponse:
        home = self.get_home()
        services.update_home(self.request.user, home, **form.cleaned_data)
        messages.success(self.request, _("Home saved."))
        return redirect(
            navigation.back_url(self.request, reverse("homes:detail", kwargs={"home_id": home.id}))
        )


class HouseholdView(WebHomeScopedMixin, DetailView[Home]):
    """Members of the home and, for owners, invitations and the sign-in rule."""

    template_name = "homes/household.html"
    context_object_name = "home"

    def get_object(self, queryset: models.QuerySet[Home] | None = None) -> Home:
        return self.get_home()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        home = self.object
        owner = services.is_owner(self.request.user, home)
        providers = sso.declared_providers(self.request)
        context.update(
            members=services.members(home),
            is_owner=owner,
            me=self.request.user,
            invitations=services.pending_invitations(home) if owner else [],
            invite_form=kwargs.get("invite_form") or forms.InviteForm(),
            providers=providers,
            provider_form=forms.ProviderForm(
                providers=providers, initial={"provider": home.required_provider}
            ),
            required_provider=sso.provider_named(home.required_provider, self.request)
            if home.required_provider
            else None,
            email_configured=email_is_configured(),
            invitation_days=get_setting("invitation_lifetime_days"),
            shared_link=self.request.session.pop("housecairn_shared_invitation", None),
        )
        return context


class HomeAuditView(WebHomeScopedMixin, DetailView[Home]):
    """What happened in the home: roles, invitations, sign-in rule, export. Owners only."""

    template_name = "homes/audit.html"
    context_object_name = "home"
    paginate_by = 50

    def get_object(self, queryset: models.QuerySet[Home] | None = None) -> Home:
        return self.get_home()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        entries = audit_services.home_log(self.request.user, self.object.id)
        context["is_owner"] = True  # the log is for owners only: the tab bar shows its own tab
        page = Paginator(entries, self.paginate_by).get_page(self.request.GET.get("page"))
        page.object_list = audit_services.name_people(page.object_list)
        context["page"] = page
        return context


class HomeExportView(WebHomeScopedMixin, View):
    """Download everything of the home as one archive. Owners only."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        home = self.get_home()
        archive, name = exports.export_home(request.user, home)
        return FileResponse(
            archive, as_attachment=True, filename=name, content_type="application/zip"
        )


class HomeDeleteView(WebHomeScopedMixin, FormView[forms.DeleteHomeForm]):
    """Delete the home for good, after typing its name. Owners only."""

    template_name = "homes/delete.html"
    form_class = forms.DeleteHomeForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        home = self.get_home()
        if not services.is_owner(self.request.user, home):
            raise PermissionDenied
        context["home"] = home
        context["member_count"] = services.members(home).count()
        return context

    def form_valid(self, form: forms.DeleteHomeForm) -> HttpResponse:
        home = self.get_home()
        try:
            services.delete_home(
                self.request.user, home, confirmation=form.cleaned_data["confirmation"]
            )
        except ValidationError as exc:
            form.add_error("confirmation", exc)
            return self.form_invalid(form)
        messages.success(self.request, _("The home was deleted."))
        return redirect(navigation.after_delete(self.request, reverse("homes:list"), [home.id]))


class HomeActionView(WebHomeScopedMixin, View):
    """Base of the household's POST actions: run, then back to the household."""

    http_method_names = ["post"]

    def locked_ok(self) -> bool:
        """Whether this action is allowed on a home whose sign-in requirement is not met."""
        return False

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        home = self.get_home(allow_locked=self.locked_ok())
        try:
            response = self.act(home)
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return self.household(home)
        except services.DeliveryFailedError:
            messages.warning(request, DELIVERY_FAILED)
            return self.household(home)
        return response or self.household(home)

    def household(self, home: Home) -> HttpResponse:
        """The household again, still knowing where it was opened from (an action in place)."""
        page = reverse("homes:household", kwargs={"home_id": home.id})
        return redirect(navigation.stay(self.request, page))

    def act(self, home: Home) -> HttpResponse | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def membership(self, home: Home) -> Membership:
        membership: Membership = get_object_or_404(
            Membership.objects.filter(home=home), id=self.kwargs["member_id"]
        )
        return membership

    def invitation(self, home: Home) -> Invitation:
        invitation: Invitation = get_object_or_404(
            Invitation.objects.filter(home=home), id=self.kwargs["invitation_id"]
        )
        return invitation


def _share_link(request: HttpRequest, raw: str | None) -> None:
    """Show a link once, on the next household page, when it was not emailed."""
    if raw is not None:
        request.session["housecairn_shared_invitation"] = invitation_link(request, raw)


class InviteView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        if not services.is_owner(self.request.user, home):
            raise PermissionDenied
        form = forms.InviteForm(self.request.POST)
        if not form.is_valid():
            raise ValidationError([e for errors in form.errors.values() for e in errors])
        if not allow(self.request, "housecairn_invite"):
            raise ValidationError(_("Too many invitations in a short time. Try again later."))
        _invitation, raw = services.invite(
            self.request.user,
            home,
            email=form.cleaned_data["email"],
            role=form.cleaned_data["role"],
            delivery=delivery_for(self.request),
        )
        _share_link(self.request, raw)
        messages.success(
            self.request,
            _("Invitation sent.") if raw is None else _("Invitation created: share its link."),
        )
        return None


class InvitationResendView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        if not allow(self.request, "housecairn_invite"):
            raise ValidationError(_("Too many invitations in a short time. Try again later."))
        _invitation, raw = services.resend_invitation(
            self.request.user,
            self.invitation(home),
            delivery=delivery_for(self.request),
        )
        _share_link(self.request, raw)
        messages.success(
            self.request,
            _("Invitation sent again.") if raw is None else _("New link created: share it."),
        )
        return None


class InvitationRevokeView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        services.revoke_invitation(self.request.user, self.invitation(home))
        messages.success(self.request, _("Invitation revoked."))
        return None


class MemberView(WebHomeScopedMixin, DetailView[Membership]):
    """One member: their role and, for owners, what can be changed."""

    template_name = "homes/member.html"
    context_object_name = "membership"

    def get_object(self, queryset: models.QuerySet[Membership] | None = None) -> Membership:
        home = self.get_home()
        membership: Membership = get_object_or_404(
            Membership.objects.filter(home=home).select_related("user", "home"),
            id=self.kwargs["member_id"],
        )
        return membership

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        membership = self.object
        context.update(
            home=membership.home,
            is_owner=services.is_owner(self.request.user, membership.home),
            is_me=membership.user_id == self.request.user.pk,
            role_form=forms.RoleForm(initial={"role": membership.role}),
        )
        return context


class MemberRoleView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        form = forms.RoleForm(self.request.POST)
        if not form.is_valid():
            raise ValidationError(_("Choose a role."))
        services.change_role(self.request.user, self.membership(home), form.cleaned_data["role"])
        messages.success(self.request, _("Role changed."))
        return None


class ConfirmedActionView(HomeActionView):
    """A POST action that is first confirmed on a page of its own (GET)."""

    http_method_names = ["get", "post"]
    confirm_template = "homes/confirm.html"

    def confirmation(self, home: Home) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        home = self.get_home(allow_locked=self.locked_ok())
        return TemplateResponse(
            request, self.confirm_template, {"home": home, **self.confirmation(home)}
        ).render()


class MemberRemoveView(ConfirmedActionView):
    def _is_me(self) -> bool:
        return Membership.objects.filter(
            id=self.kwargs["member_id"], user=self.request.user
        ).exists()

    def locked_ok(self) -> bool:
        # Leaving never needs the provider: nobody is held in a home.
        return self._is_me()

    def confirmation(self, home: Home) -> dict[str, Any]:
        membership = self.membership(home)
        me = membership.user_id == self.request.user.pk
        return {
            "title": _("Leave this home?") if me else _("Remove this member?"),
            "text": _(
                "You will lose access to %(home)s. Someone has to invite you again to return."
            )
            % {"home": home.name}
            if me
            else _("%(who)s will lose access to %(home)s.")
            % {"who": person_name(membership.user), "home": home.name},
            "action": reverse("homes:member-remove", args=[home.id, membership.id]),
            "button": _("Leave") if me else _("Remove"),
            "back": reverse("homes:member", args=[home.id, membership.id]),
        }

    def act(self, home: Home) -> HttpResponse | None:
        membership = self.membership(home)
        services.remove_member(self.request.user, membership)
        if membership.user_id == self.request.user.pk:
            messages.success(self.request, _("You left %(home)s.") % {"home": home.name})
            return redirect("homes:list")
        messages.success(self.request, _("Member removed."))
        return None


class LeaveView(ConfirmedActionView):
    def locked_ok(self) -> bool:
        return True

    def confirmation(self, home: Home) -> dict[str, Any]:
        return {
            "title": _("Leave this home?"),
            "text": _(
                "You will lose access to %(home)s. Someone has to invite you again to return."
            )
            % {"home": home.name},
            "action": reverse("homes:leave", args=[home.id]),
            "button": _("Leave"),
            "back": reverse("homes:household", args=[home.id]),
        }

    def act(self, home: Home) -> HttpResponse | None:
        services.leave_home(self.request.user, home)
        messages.success(self.request, _("You left %(home)s.") % {"home": home.name})
        return redirect("homes:list")


class UnlockView(HomeActionView):
    """Stop requiring a sign-in provider the instance no longer offers."""

    def locked_ok(self) -> bool:
        return True

    def act(self, home: Home) -> HttpResponse | None:
        services.lift_unavailable_requirement(
            self.request.user,
            home,
            declared=[p.id for p in sso.declared_providers(self.request)],
        )
        messages.success(self.request, _("Sign-in requirement removed."))
        return redirect("homes:household", home_id=home.id)


class TransferView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        services.transfer_ownership(
            self.request.user,
            home,
            self.membership(home),
        )
        messages.success(self.request, _("Ownership transferred. You are now a member."))
        return None


class RequiredProviderView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        providers = sso.declared_providers(self.request)
        form = forms.ProviderForm(self.request.POST, providers=providers)
        if not form.is_valid():
            raise ValidationError(_("Choose a sign-in provider."))
        services.set_required_provider(
            self.request.user,
            home,
            form.cleaned_data["provider"],
            declared=[p.id for p in providers],
            signed_in_with=sso.signed_in_providers(self.request),
        )
        messages.success(self.request, _("Sign-in requirement saved."))
        return None


class InvitationView(View):
    """The page an invitation link opens: join, or create an account to join.

    Every link that opens nothing (unknown, used, revoked, expired) gets the
    same page, and opening links is rate limited per client address.
    """

    http_method_names = ["get", "post"]

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not allow(request, "housecairn_invitation"):
            return TemplateResponse(request, "429.html", status=429).render()
        invitation = services.find_invitation(kwargs["token"])
        if invitation is None:
            return TemplateResponse(request, "homes/invitation_invalid.html", status=404).render()
        self.invitation = invitation
        self.token: str = kwargs["token"]
        return super().dispatch(request, *args, **kwargs)

    def context(self, **extra: Any) -> dict[str, Any]:
        user = self.request.user
        same_address = user.is_authenticated and services.same_address(
            user.email, self.invitation.email
        )
        return {
            "invitation": self.invitation,
            "home": self.invitation.home,
            "same_address": same_address,
            # A link handed over by hand proves nothing: the account verifies the
            # address first (docs/adr/0020).
            "needs_verification": same_address
            and not self.invitation.delivered_by_email
            and not services.has_verified_address(user, self.invitation.email),  # type: ignore[arg-type]
            "email_configured": email_is_configured(),
            "account_exists": False,
            "providers": sso.declared_providers(self.request),
            "next_url": self.request.path,
            **extra,
        }

    def render(self, **extra: Any) -> HttpResponse:
        return TemplateResponse(
            self.request, "homes/invitation.html", self.context(**extra)
        ).render()

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        form = self.signup_form() if self.may_create_account() else None
        return self.render(form=form)

    def may_create_account(self) -> bool:
        """Only a link that went by email creates an account (docs/adr/0020)."""
        return not self.request.user.is_authenticated and self.invitation.delivered_by_email

    def signup_form(self, data: Any = None) -> forms.InvitationSignupForm:
        return forms.InvitationSignupForm(data, email=self.invitation.email)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return self.accept(request.user)
        if not self.may_create_account():
            # The same page as a visit: it says nothing about accounts.
            return self.render(form=None)
        form = self.signup_form(request.POST)
        if not form.is_valid():
            return self.render(form=form)
        try:
            user = services.create_account_for_invitation(
                self.token, password=form.cleaned_data["password1"]
            )
        except ValidationError:
            return self.render(form=None, account_exists=True)
        except PermissionDenied:
            return self.render(form=None)
        except Invitation.DoesNotExist as exc:
            raise Http404 from exc
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Welcome to %(home)s.") % {"home": self.invitation.home.name})
        return HttpResponseRedirect(
            reverse("homes:detail", kwargs={"home_id": self.invitation.home_id})
        )

    def accept(self, user: User) -> HttpResponse:
        try:
            membership = services.accept_invitation(user, self.token)
        except PermissionDenied:
            return self.render()
        except Invitation.DoesNotExist as exc:
            raise Http404 from exc
        messages.success(self.request, _("You joined %(home)s.") % {"home": membership.home.name})
        return redirect("homes:detail", home_id=membership.home_id)
