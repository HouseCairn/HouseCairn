"""Sending a stored photo: as an image, inline, never as something a browser could run."""

from django.http import FileResponse, Http404

from housecairn.rooms.models import Photo

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def photo_response(photo: Photo, *, thumbnail: bool = False) -> FileResponse:
    """The stored image or its thumbnail.

    The content type comes from the content found at upload, never from the
    sender; the name is the identifier. `nosniff` stops a browser from guessing
    another type, and the sandboxed, script-free policy applies if the address is
    opened as a page.
    """
    stored = photo.thumbnail if thumbnail else photo.image
    content_type = "image/jpeg" if thumbnail else photo.content_type
    try:
        handle = stored.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(handle, content_type=content_type)
    suffix = ".jpg" if thumbnail else EXTENSIONS.get(content_type, "")
    response["Content-Disposition"] = f'inline; filename="{photo.id}{suffix}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
