"""Web views of homes, households and invitations. Rules live in `services`."""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from housecairn.accounts.models import User
from housecairn.accounts.services import email_is_configured
from housecairn.homes import forms, services, sso
from housecairn.homes.models import Home, Invitation, Membership
from housecairn.homes.scoping import (
    WebHomeScopedMixin,
    allow,
    delivery_for,
    homes_for_request,
    invitation_link,
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
        )
        return redirect("homes:detail", home_id=home.id)


class HomeDetailView(WebHomeScopedMixin, DetailView[Home]):
    template_name = "homes/home_detail.html"
    context_object_name = "home"

    def get_object(self, queryset: models.QuerySet[Home] | None = None) -> Home:
        return self.get_home()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["role"] = services.role_of(self.request.user, self.object)
        context["member_count"] = services.members(self.object).count()
        return context


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
            invitation_days=settings.HOUSECAIRN_INVITATION_LIFETIME_DAYS,
            shared_link=self.request.session.pop("housecairn_shared_invitation", None),
        )
        return context


class HomeActionView(WebHomeScopedMixin, View):
    """Base of the household's POST actions: run, then back to the household."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        home = self.get_home()
        try:
            response = self.act(home)
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return redirect("homes:household", home_id=home.id)
        return response or redirect("homes:household", home_id=home.id)

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


class MemberRemoveView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        membership = self.membership(home)
        services.remove_member(self.request.user, membership)
        if membership.user_id == self.request.user.pk:
            messages.success(self.request, _("You left %(home)s.") % {"home": home.name})
            return redirect("homes:list")
        messages.success(self.request, _("Member removed."))
        return None


class LeaveView(HomeActionView):
    def act(self, home: Home) -> HttpResponse | None:
        services.leave_home(self.request.user, home)
        messages.success(self.request, _("You left %(home)s.") % {"home": home.name})
        return redirect("homes:list")


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
        return {
            "invitation": self.invitation,
            "home": self.invitation.home,
            "same_address": user.is_authenticated
            and services.same_address(user.email, self.invitation.email),
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
        form = None if request.user.is_authenticated else self.signup_form()
        return self.render(form=form)

    def signup_form(self, data: Any = None) -> forms.InvitationSignupForm:
        return forms.InvitationSignupForm(data, email=self.invitation.email)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return self.accept(request.user)
        form = self.signup_form(request.POST)
        if not form.is_valid():
            return self.render(form=form)
        try:
            user = services.create_account_for_invitation(
                self.token, password=form.cleaned_data["password1"]
            )
        except ValidationError:
            return self.render(form=None, account_exists=True)
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
