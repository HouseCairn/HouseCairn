"""API v1 of the library of task templates (docs/adr/0049)."""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from housecairn.tasks import task_templates


def _text(text: task_templates.Text | None) -> dict[str, str] | None:
    return None if text is None else {"en": text.en, "fr": text.fr}


def library_data() -> dict[str, Any]:
    found = task_templates.library()
    return {
        "version": 1,
        "equipment": [{"id": e.id, "name": _text(e.name)} for e in found.equipment],
        "templates": [
            {
                "id": t.id,
                "equipment": t.equipment,
                "title": _text(t.title),
                "item_kind": t.item_kind,
                "room_kinds": list(t.room_kinds),
                "every": {"interval": t.interval, "unit": t.unit},
                "season": t.season,
                "minutes": t.minutes,
                "materials": [_text(m) for m in t.materials],
                "procedure": _text(t.procedure),
                "region": t.region,
                "note": _text(t.note),
                "source": {"title": t.source_title, "url": t.source_url},
            }
            for t in found.templates
        ],
    }


class TemplateLibraryView(APIView):
    """The library of task templates shipped with this version, in English and in French.

    Any person signed in, and any token with the `read` scope: the library is the same for
    everyone and holds nothing of a home. `POST /api/v1/homes/<id>/tasks/from-templates/`
    turns templates into tasks of a home.
    """

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(library_data())
