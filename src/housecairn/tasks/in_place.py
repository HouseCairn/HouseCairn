"""Actions in place: Done, Skip and Undo keep the person where they are (NAV-05, NAV-12).

With JavaScript, the row posts with HTMX and gets back its own markup, plus the undo
banner as an out-of-band swap into the live region of every page (`#undo-region`).
The banner's Undo posts the same way and gets back the region's content, plus the row.
Without it, the same forms post, then the view redirects to `next#occ-<id>`.

The undo banner never lives in the address (docs/developer/design-guide.md, "The bar,
and the browser's back button"): going back would show it again, out of date. On the
redirect path it is kept in the session for the next page only, read once by the
`{% undo_banner %}` tag of `base.html`, like a message.
"""

from typing import Any
from uuid import UUID

from django.http import HttpRequest

from housecairn.homes import services as home_services
from housecairn.homes.scoping import open_homes_for_request
from housecairn.tasks.models import CLOSED_STATUSES, Occurrence

# The session key of the banner waiting for the next page.
SESSION_KEY = "housecairn.undo"

# The hidden field of a form that acts in place, and the forms that send it.
FIELD = "in_place"
ORIGINS = ("row", "banner")


def anchor(occurrence_id: object) -> str:
    """The id of the row of an occurrence, also the fragment of the redirect without script."""
    return f"occ-{occurrence_id}"


def origin(request: HttpRequest) -> str | None:
    """The form of an HTMX request that acts in place (`row` or `banner`), else None.

    None means a plain post: the answer is a redirect.
    """
    if request.headers.get("HX-Request") != "true":
        return None
    sent = request.POST.get(FIELD, "")
    return sent if sent in ORIGINS else None


def remember(request: HttpRequest, occurrence: Occurrence, back: str, notice: str = "") -> None:
    """Keep the banner of `occurrence` for the next page, which `back` is."""
    request.session[SESSION_KEY] = {
        "occurrence": str(occurrence.pk),
        "next": back,
        "notice": notice,
    }


def forget(request: HttpRequest) -> None:
    request.session.pop(SESSION_KEY, None)


def take(request: HttpRequest) -> dict[str, Any] | None:
    """The banner kept for this page, read once; None when there is none or it is stale.

    The occurrence must still be closed, in a home the person may open and write in.
    """
    session = getattr(request, "session", None)
    if session is None or SESSION_KEY not in session:
        return None
    kept = session.pop(SESSION_KEY)
    if not isinstance(kept, dict) or not _is_uuid(kept.get("occurrence")):
        return None
    found = (
        Occurrence.objects.filter(
            pk=kept["occurrence"],
            home__in=open_homes_for_request(request),
            status__in=CLOSED_STATUSES,
        )
        .select_related("home")
        .first()
    )
    if found is None or not home_services.can_write(request.user, found.home):
        return None
    return {
        "undo": found,
        "home": found.home,
        "undo_return": str(kept.get("next") or ""),
        "notice": str(kept.get("notice") or ""),
        "in_place": False,
    }


def _is_uuid(raw: object) -> bool:
    try:
        UUID(str(raw))
    except ValueError:
        return False
    return True
