"""Sending the stored photo of a report: as an image, inline, never as something to run."""

from django.http import FileResponse, Http404

from housecairn.reports.models import Report
from housecairn.rooms.files import EXTENSIONS


def photo_response(report: Report, *, thumbnail: bool = False) -> FileResponse:
    """The stored photo or its thumbnail. The type comes from the content found at upload,
    the name is the identifier; `nosniff` and a policy that forbids any script apply."""
    stored = report.thumbnail if thumbnail else report.photo
    if not stored:
        raise Http404
    content_type = "image/jpeg" if thumbnail else report.photo_content_type
    try:
        handle = stored.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(handle, content_type=content_type)
    suffix = ".jpg" if thumbnail else EXTENSIONS.get(content_type, "")
    response["Content-Disposition"] = f'inline; filename="{report.id}{suffix}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
