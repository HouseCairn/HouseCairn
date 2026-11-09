from typing import Any

from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext as _

from housecairn.accounts import services
from housecairn.accounts.models import InstanceSetup, User
from housecairn.audit import services as audit

# Models other apps put on the administration site. None of them stays: each one
# either holds a secret or lets an administrator take an account over (docs/adr/0022).
#   allauth.account    EmailAddress: add a verified address, then reset the password
#   allauth.mfa        Authenticator: the TOTP secret and the recovery codes
#   allauth.socialaccount  SocialAccount: link an identity to any account;
#                      SocialApp: the provider's client secret, or another provider;
#                      SocialToken: the provider's access and refresh tokens
#   django_q           Schedule: names any function to run; Success, Failure, OrmQ:
#                      keep the arguments and results of every task
#   django.contrib.auth  Group: permissions that mean nothing here (an administrator
#                      is_staff and is_superuser)
# Sessions are not registered by Django and ApiToken is read-only (apitokens.admin).
_UNREGISTERED = (
    "account.EmailAddress",
    "account.EmailConfirmation",
    "mfa.Authenticator",
    "socialaccount.SocialAccount",
    "socialaccount.SocialApp",
    "socialaccount.SocialToken",
    "usersessions.UserSession",
    "django_q.Schedule",
    "django_q.Success",
    "django_q.Failure",
    "django_q.OrmQ",
    "auth.Group",
)
for _label in _UNREGISTERED:
    try:
        _model = apps.get_model(_label)
    except LookupError:
        continue
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)


class AccountAdminForm(forms.ModelForm[User]):
    """Refuses to switch off, or to take the role from, the only administrator (ADR 0041)."""

    class Meta:
        model = User
        fields = ("is_active", "is_staff", "is_superuser")

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        user = User.objects.filter(pk=self.instance.pk).first()
        still_admin = all(
            cleaned.get(name, getattr(user, name, False))
            for name in ("is_active", "is_staff", "is_superuser")
        )
        if user is not None and not still_admin and services.is_last_instance_admin(user):
            raise ValidationError(
                _(
                    "This is the only administrator of the instance: make another account "
                    "an administrator first."
                )
            )
        return cleaned


@admin.register(User)
class UserAdmin(admin.ModelAdmin[User]):
    """Accounts: what an administrator may do, and no more.

    An administrator switches an account on or off, grants or withdraws the
    administrator role, and deletes an account by the same rules as erasure by the
    person (last owner, last administrator). Every change is audited. There is no
    password, no address and no credential here, and no way to add an account (an
    account is created by an instance invitation): being able to set either would
    be taking the account over (docs/adr/0022).
    """

    form = AccountAdminForm
    ordering = ("email",)
    list_display = ("email", "display_name", "is_staff", "is_active")
    search_fields = ("email", "display_name", "first_name", "last_name")
    fields = (
        "email",
        "display_name",
        "display_name_source",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
        "last_login",
        "date_joined",
    )
    readonly_fields = (
        "email",
        "display_name",
        "display_name_source",
        "first_name",
        "last_name",
        "last_login",
        "date_joined",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        super().save_model(request, obj, form, change)
        if form.changed_data:
            audit.record(
                "admin.user_changed",
                actor=request.user,
                target=obj,
                fields=sorted(form.changed_data),
            )

    def delete_model(self, request: HttpRequest, obj: User) -> None:
        self._delete(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        for user in list(queryset):
            self._delete(request, user)

    def get_deleted_objects(
        self, objs: Any, request: HttpRequest
    ) -> tuple[list[str], dict[str, int], set[str], list[Any]]:
        """The confirmation page lists the account only.

        Django would list everything that goes with it, memberships included,
        which names the homes of the person: the administrator reads no home.
        """
        verbose = self.opts.verbose_name
        listed = [f"{verbose}: {obj}" for obj in objs]
        return listed, {str(self.opts.verbose_name_plural): len(listed)}, set(), []

    def _delete(self, request: HttpRequest, user: User) -> None:
        try:
            services.delete_account(user, by_admin=request.user)  # type: ignore[arg-type]
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, f"{user.email}: {message}")


@admin.register(InstanceSetup)
class InstanceSetupAdmin(admin.ModelAdmin[InstanceSetup]):
    """Audit record of the first account: read-only."""

    list_display = ("method", "first_user", "created_at")
    readonly_fields = ("method", "first_user", "created_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: InstanceSetup | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: InstanceSetup | None = None) -> bool:
        return False
