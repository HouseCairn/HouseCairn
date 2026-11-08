"""Helpers shared by the API modules of tasks."""

import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
)
from rest_framework import exceptions
from rest_framework.request import Request

_FAR = datetime.date(9999, 12, 31)


def _date_param(request: Request, name: str) -> datetime.date | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise exceptions.ValidationError({name: ["Not a valid date (YYYY-MM-DD)."]}) from None


DATE_PARAMS = [
    OpenApiParameter("due_before", OpenApiTypes.DATE, description="Due on or before this date."),
    OpenApiParameter("due_after", OpenApiTypes.DATE, description="Due on or after this date."),
]
