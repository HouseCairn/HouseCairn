"""Sending a stored label photo: as an image, inline, never as something a browser could run."""

from django.http import FileResponse, Http404

from housecairn.rooms.files import EXTENSIONS
from housecairn.stock.models import Article


def label_response(article: Article) -> FileResponse:
    """The stored image of the label.

    The content type comes from the content found at upload, never from the sender; the
    name is the identifier. `nosniff` stops a browser from guessing another type, and
    the sandboxed, script-free policy applies if the address is opened as a page.
    """
    try:
        handle = article.label.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    response = FileResponse(handle, content_type=article.label_content_type)
    suffix = EXTENSIONS.get(article.label_content_type, "")
    response["Content-Disposition"] = f'inline; filename="{article.id}{suffix}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response
