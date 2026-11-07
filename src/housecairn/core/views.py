from importlib import metadata
from typing import Any

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from housecairn.core import services


class IndexView(TemplateView):
    template_name = "core/index.html"


class MoreView(LoginRequiredMixin, TemplateView):
    """Everything that is not a daily gesture, kept out of the navigation bar."""

    template_name = "core/more.html"


class AboutView(TemplateView):
    template_name = "core/about.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        try:
            version = metadata.version("housecairn")
        except metadata.PackageNotFoundError:  # pragma: no cover - run from a bare checkout
            version = "dev"
        context.update(version=version, source_url=settings.HOUSECAIRN_SOURCE_URL)
        return context


@never_cache
@require_safe
def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness and database check, without authentication or details."""
    if services.database_is_available():
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "unavailable"}, status=503)


@cache_control(max_age=3600, public=True)
@require_safe
def manifest(request: HttpRequest) -> JsonResponse:
    """Web app manifest: name, colours and icons, so the app can be added to a home screen."""
    icons = [
        {
            "src": static(f"img/brand/icon-{size}.png"),
            "sizes": f"{size}x{size}",
            "type": "image/png",
        }
        for size in (192, 512)
    ]
    data = {
        "name": "HouseCairn",
        "short_name": "HouseCairn",
        "description": _("What needs doing in the house, where, when, with what and for how much."),
        "lang": request.LANGUAGE_CODE,
        "start_url": reverse("index"),
        "scope": "/",
        "display": "standalone",
        "background_color": "#F7F5F1",
        "theme_color": "#F7F5F1",
        "icons": icons,
    }
    response = JsonResponse(data, content_type="application/manifest+json")
    return response
