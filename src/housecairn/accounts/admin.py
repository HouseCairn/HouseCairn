from typing import Any

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from housecairn.accounts import services
from housecairn.accounts.models import InstanceSetup, User
from housecairn.audit import services as audit


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    """Accounts: the administrator's job. Changes and deletions are audited, and a
    deletion follows the same rules as erasure by the person (last owner, last
    administrator)."""

    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        super().save_model(request, obj, form, change)
        if change:
            audit.record("admin.user_changed", actor=request.user, target=obj)
        else:
            audit.record("account.created", actor=request.user, target=obj, by="administrator")

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
