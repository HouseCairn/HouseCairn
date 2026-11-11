import json
from importlib import metadata
from typing import Any, cast

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import get_script_prefix, reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_safe
from django.views.defaults import bad_request as default_bad_request
from django.views.generic import TemplateView

from housecairn.core import more, services
from housecairn.instance.config import instance_name


class IndexView(TemplateView):
    """The one home of the application (docs/developer/design-guide.md, Today).

    Signed in, it is Today: Today of the current home, or all the homes of the person
    together when they chose "All homes" in the selector (and before they chose a home).
    The welcome page is for a signed-out visitor and for an account with no home to open.
    """

    template_name = "core/index.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            from housecairn.homes import current
            from housecairn.tasks.views import MyHomeView

            chosen = current.for_request(request)
            if chosen.all_homes:
                return cast(HttpResponse, MyHomeView.as_view()(request))
            if chosen.home is not None:
                return redirect("tasks:today", home_id=chosen.home.pk)
        return super().get(request, *args, **kwargs)


class MoreView(LoginRequiredMixin, TemplateView):
    """Everything that is not a daily gesture, kept out of the navigation bar."""

    template_name = "core/more.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from housecairn.homes import current

        # The Home group is about the home being viewed; More has none in its address,
        # so it is the current home (docs/developer/design-guide.md, "Current home").
        home = current.for_request(self.request).home
        home_id = home.pk if home else None
        from housecairn.reports.services import waiting_for

        return super().get_context_data(
            groups=more.for_page(
                self.request.user, home_id, "more", waiting_for(self.request, home_id)
            ),
            **kwargs,
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
        # Under a path prefix, the installed application stays in it (docs/adr/0055).
        "scope": get_script_prefix(),
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


def bad_request(request: HttpRequest, exception: Exception) -> HttpResponse:
    """The 400 page; for a host name the instance refuses, it says what to change.

    Any other 400 is Django's own page, unchanged. Here the page gets only the sentence
    of `HOUSECAIRN_DISALLOWED_HOST_HINT` (empty: the generic one): not the `Host` header
    that was refused, not `ALLOWED_HOSTS`, not the message of the exception.
    """
    if not isinstance(exception, DisallowedHost):
        return default_bad_request(request, exception)
    return render(
        request,
        "400.html",
        {"disallowed_host": True, "host_hint": settings.HOUSECAIRN_DISALLOWED_HOST_HINT},
        status=400,
    )
