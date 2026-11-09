"""Sending a stored photo or quote file back: images inline, documents downloaded (adr 0050)."""

from pathlib import PurePosixPath

from django.http import FileResponse, Http404

from housecairn.projects.models import ProjectFile


def file_response(stored: ProjectFile, *, thumbnail: bool = False) -> FileResponse:
    """The stored file or the thumbnail of an image.

    The type comes from the content found at upload, never from the sender; the name is
    the identifier. `nosniff` stops a browser from guessing another type and the policy
    forbids any script or frame, as for the attachments of tasks (docs/adr/0034).
    """
    if thumbnail and not stored.thumbnail:
        raise Http404
    source = stored.thumbnail if thumbnail else stored.file
    try:
        handle = source.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    extension = ".jpg" if thumbnail else PurePosixPath(stored.file.name).suffix
    response = FileResponse(handle, content_type="image/jpeg" if thumbnail else stored.content_type)
    disposition = "inline" if stored.is_image else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{stored.id}{extension}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
