import json
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

from housecairn.core import more, services
from housecairn.instance.config import instance_name


class IndexView(TemplateView):
    template_name = "core/index.html"


class MoreView(LoginRequiredMixin, TemplateView):
    """Everything that is not a daily gesture, kept out of the navigation bar."""

    template_name = "core/more.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from housecairn.homes.scoping import open_homes_for_request

        # The Home group is about the home being viewed; More has none in its address,
        # so it is the person's only home, if they have exactly one.
        homes = list(open_homes_for_request(self.request).values_list("id", flat=True)[:2])
        home_id = homes[0] if len(homes) == 1 else None
        return super().get_context_data(
            groups=more.for_page(self.request.user, home_id, "more"), **kwargs
        )


class SecurityView(LoginRequiredMixin, TemplateView):
    """Security and sign-in: second factor, password, addresses; deleting the account last."""

    template_name = "core/security.html"


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
def manifest(request: HttpRequest) -> HttpResponse:
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
        # The name of the instance (docs/adr/0042); JSON escapes it.
        "name": instance_name(),
        "short_name": instance_name(),
        "description": _("What needs doing in the house, where, when, with what and for how much."),
        "lang": request.LANGUAGE_CODE,
        "start_url": reverse("index"),
        "scope": "/",
        "display": "standalone",
        "background_color": "#F7F5F1",
        "theme_color": "#F7F5F1",
        "icons": icons,
    }
    # Escaped like `json_script`: the name of the instance is chosen by an administrator.
    body = json.dumps(data).translate(
        {ord("<"): "\\u003c", ord(">"): "\\u003e", ord("&"): "\\u0026"}
    )
    return HttpResponse(body, content_type="application/manifest+json")
