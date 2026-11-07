from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from housecairn.accounts.models import InstanceSetup, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
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
