"""The language a person chose in their display preferences (docs/adr/0042)."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.utils import translation

from housecairn.tasks.models import DisplayPreference


class PersonLanguageMiddleware:
    """A signed-in person's own language wins over the cookie, the browser and the default.

    It runs after authentication, so after the locale middleware has chosen from the
    request; it only overrides that choice, from the next page on, when the person saved one.
    A request authenticated by an API token is not known here: it keeps the language it asks for.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            chosen = (
                DisplayPreference.objects.filter(user_id=user.pk)
                .values_list("language", flat=True)
                .first()
            )
            if chosen:
                translation.activate(chosen)
                request.LANGUAGE_CODE = translation.get_language()
        return self.get_response(request)
