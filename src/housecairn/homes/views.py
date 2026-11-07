from typing import Any

from django.db import models
from django.views.generic import DetailView, ListView

from housecairn.homes import services
from housecairn.homes.models import Home
from housecairn.homes.scoping import WebHomeScopedMixin


class HomeListView(WebHomeScopedMixin, ListView[Home]):
    template_name = "homes/home_list.html"
    context_object_name = "homes"

    def get_queryset(self) -> models.QuerySet[Home]:
        return self.get_homes().order_by("name")


class HomeDetailView(WebHomeScopedMixin, DetailView[Home]):
    template_name = "homes/home_detail.html"
    context_object_name = "home"

    def get_object(self, queryset: models.QuerySet[Home] | None = None) -> Home:
        return self.get_home()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["role"] = services.role_of(self.request.user, self.object)
        return context
