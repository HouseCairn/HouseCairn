from django.contrib import admin

from housecairn.homes.models import Home, Membership


class MembershipInline(admin.TabularInline[Membership, Home]):
    model = Membership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Home)
class HomeAdmin(admin.ModelAdmin[Home]):
    list_display = ("name", "currency", "created_at")
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (MembershipInline,)
