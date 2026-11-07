from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from django.views.generic import TemplateView

from housecairn.core import services


class IndexView(TemplateView):
    template_name = "core/index.html"


@never_cache
@require_safe
def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness and database check, without authentication or details."""
    if services.database_is_available():
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "unavailable"}, status=503)
