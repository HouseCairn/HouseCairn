"""Links of inspiration of a project, with a preview read once (docs/adr/0050).

A link is an address, a title and, when the page gave one, a picture stored like a photo of
the project. Reading the page happens when the link is added, outside any transaction, and
only if the instance allows it (`link_preview_enabled`, docs/adr/0035). Any failure leaves
the plain address: adding a link never fails because a page could not be read.
"""

import logging
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _
from rest_framework.request import Request

from housecairn.audit import services as audit
from housecairn.homes.scoping import allow
from housecairn.instance.config import get_setting
from housecairn.projects import preview
from housecairn.projects.models import MAX_LINKS_PER_PROJECT, Project, ProjectFile, ProjectLink
from housecairn.projects.services import (
    AnyUser,
    _erase_files,
    _require_write,
    save_stored,
)
from housecairn.rooms import images
from housecairn.tasks import files as task_files

logger = logging.getLogger("housecairn.projects")

MAX_URL_LENGTH = 500


def preview_enabled() -> bool:
    return bool(get_setting("link_preview_enabled"))


def preview_allowed(request: HttpRequest | Request, project: Project) -> bool:
    """Take one use of the preview limits (per person and per home) before a link is added.

    Only an addition that makes the server read a page counts: with previews off nothing
    leaves the server. A person who cannot write is refused first and uses nothing.
    False: the limit is reached, and the caller must neither read nor add anything.
    """
    _require_write(request.user, project.home)
    if not preview_enabled():
        return True
    return allow(request, "housecairn_link_preview", key=str(project.home_id))


def clean_url(raw: str) -> str:
    """The address, trimmed, http or https only and without credentials; ValidationError."""
    text = raw.strip() if isinstance(raw, str) else ""
    invalid = ValidationError(
        {"url": _("Give the address of a web page, such as https://example.com.")}
    )
    if not text or len(text) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in text):
        raise invalid
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        raise invalid from None
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise invalid
    if parts.username is not None or parts.password is not None:
        raise ValidationError({"url": _("The address cannot hold a user name or a password.")})
    return text


def add_link(actor: AnyUser, project: Project, *, url: str, title: str = "") -> ProjectLink:
    """Add a link. The page is read first (a few seconds at most), then the link is saved.

    A title given by the person is kept; otherwise the one the page gave, if any.
    """
    _require_write(actor, project.home)
    address = clean_url(url)
    given = preview.clean_title(title) if isinstance(title, str) else ""
    if ProjectLink.objects.filter(project=project).count() >= MAX_LINKS_PER_PROJECT:
        raise ValidationError(
            _("At most %(max)d links for a project."), params={"max": MAX_LINKS_PER_PROJECT}
        )
    found = preview.read(address) if preview_enabled() else preview.Preview()
    return _save(actor, project, address, given or found.title, found.image)


@transaction.atomic
def _save(
    actor: AnyUser, project: Project, address: str, title: str, picture: bytes | None
) -> ProjectLink:
    link = ProjectLink(home=project.home, project=project, url=address, title=title)
    link.full_clean(exclude=["image"])
    link.save()
    if picture is not None:
        link.image = _store_picture(project, link, picture)
        if link.image is not None:
            link.save(update_fields=["image", "updated_at"])
    audit.record_object(
        "project_link.added",
        actor=actor,
        home_id=project.home_id,
        title=project.title,
        domain=preview.domain_of(address),
    )
    return link


def _store_picture(project: Project, link: ProjectLink, data: bytes) -> ProjectFile | None:
    """Check, clean and store the picture the page designated; None if it cannot be.

    The same rules as a photo (docs/adr/0030): the type is found by decoding, SVG and every
    other format are refused, the picture is written again without metadata, and the quotas
    of the home count it. A refusal leaves the link without a picture, not without a link.
    """
    try:
        processed = images.process(data)
        stored = ProjectFile(
            home=project.home,
            project=project,
            name=task_files.clean_name(link.title or "link") or "link",
            content_type=processed.content_type,
            is_image=True,
            size_bytes=len(processed.data),
            width=processed.width,
            height=processed.height,
        )
        with transaction.atomic():
            save_stored(stored, processed.data, processed.thumbnail, processed.extension)
    except ValidationError:
        logger.info("The picture of a link could not be kept (invalid).")
        return None
    return stored


@transaction.atomic
def delete_link(actor: AnyUser, link: ProjectLink) -> None:
    """Soft-delete the link and erase its picture from the disk."""
    _require_write(actor, link.home)
    doomed = [link.image] if link.image is not None else []
    link.soft_delete()
    for stored in doomed:
        stored.soft_delete()
    _erase_files(doomed)
    audit.record_object(
        "project_link.deleted",
        actor=actor,
        home_id=link.home_id,
        title=link.project.title,
        domain=preview.domain_of(link.url),
    )
