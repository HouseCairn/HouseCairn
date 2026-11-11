from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from housecairn.apitokens import services
from housecairn.apitokens.models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin[ApiToken]):
    """Listing and revocation only: tokens are issued by their owner."""

    list_display = ("name", "prefix", "user", "scopes", "expires_at", "revoked_at", "last_used_at")
    list_filter = ("revoked_at",)
    search_fields = ("name", "prefix", "user__email")
    readonly_fields = (
        "id",
        "user",
        "name",
        "prefix",
        "scopes",
        "signed_in_provider",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "created_at",
    )
    # Neither the secret nor the homes the token opens: an administrator may list and
    # revoke tokens, and learns nothing of any home (docs/adr/0022).
    exclude = ("digest", "homes")
    actions = ("revoke",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ApiToken | None = None) -> bool:
        # Revoke instead: a deletion page would list the homes of the token.
        return False

    @admin.action(description=_("Revoke selected tokens"))
    def revoke(self, request: HttpRequest, queryset: QuerySet[ApiToken]) -> None:
        for token in queryset:
            services.revoke_token(request.user, token)  # type: ignore[arg-type]
