"""Reading the title and the picture of a page for a link of inspiration (docs/adr/0050).

The address is one a person typed, so the server reads it under the guard of
`core.netguard`: public addresses only, checked on every redirect, a size and a total time
limit, nothing left open. The HTML is parsed, never run, and no resource it names is loaded
except the one picture it designates as its own (`og:image`), fetched under the same guard.

A page that cannot be read gives no preview and no error: the link stays an address. The
reason goes to the log as a short code; the address does not (a link of inspiration says
what a household is planning).
"""

import logging
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from housecairn.core import netguard
from housecairn.core.text import without_control_characters
from housecairn.projects.models import LINK_TITLE_MAX_LENGTH
from housecairn.rooms import conf as rooms_conf

logger = logging.getLogger("housecairn.projects")

# Limits of a preview. They are not settings: they bound what a stranger's server can make
# this one read or wait for (docs/adr/0050).
PAGE_MAX_BYTES = 1024 * 1024  # the head of a page; Open Graph tags come first
IMAGE_MAX_BYTES = 5 * 1024 * 1024
# The whole preview, page and picture together, however slowly the servers answer.
PREVIEW_SECONDS = 10.0
MIN_IMAGE_SECONDS = 1.0
# What the reader of a head looks at; the first of each wins.
_TITLE_PROPERTIES = ("og:title", "twitter:title")
_IMAGE_PROPERTIES = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image")
MAX_IMAGE_ADDRESS = 2048


@dataclass(frozen=True)
class PageInfo:
    title: str = ""
    image_url: str = ""


class _HeadReader(HTMLParser):
    """Collects `<meta>` tags and `<title>` from the head; stops at the body.

    `HTMLParser` only tokenizes: it runs no script, builds no tree, loads nothing, and
    keeps no state beyond the few strings below, whatever the nesting of the page.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.page_title = ""
        self._in_title = False
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done:
            return
        if tag == "body":
            self.done = True
        elif tag == "title" and not self.page_title:
            self._in_title = True
        elif tag == "meta":
            values = {name.lower(): value or "" for name, value in attrs}
            key = (values.get("property") or values.get("name") or "").strip().lower()
            if key and "content" in values and key not in self.meta:
                self.meta[key] = values["content"]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True

    def handle_data(self, data: str) -> None:
        if self._in_title and len(self.page_title) < 4 * LINK_TITLE_MAX_LENGTH:
            self.page_title += data


def clean_title(raw: str) -> str:
    """A title as plain text: control characters out, spaces collapsed, cut to the limit."""
    text = without_control_characters(" ".join(raw.split()))
    return text[:LINK_TITLE_MAX_LENGTH].strip()


def parse(body: bytes, charset: str | None, base_url: str) -> PageInfo:
    """The Open Graph title and picture of a page, else its `<title>`; never raises."""
    try:
        text = body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    reader = _HeadReader()
    try:
        reader.feed(text)
        reader.close()
    except Exception:  # an HTML parser may fail on hostile input; the link stays an address
        logger.info("A page could not be read (parse).")
    title = ""
    for key in _TITLE_PROPERTIES:
        title = clean_title(reader.meta.get(key, ""))
        if title:
            break
    if not title:
        title = clean_title(reader.page_title)
    image = ""
    for key in _IMAGE_PROPERTIES:
        candidate = reader.meta.get(key, "").strip()
        if (
            candidate
            and len(candidate) <= MAX_IMAGE_ADDRESS
            and not any(c.isspace() for c in candidate)
        ):
            image = urljoin(base_url, candidate)
            break
    return PageInfo(title=title, image_url=image)


@dataclass(frozen=True)
class Preview:
    title: str = ""
    image: bytes | None = None


def read(url: str) -> Preview:
    """The preview of a page: its title and the bytes of its picture, if any.

    Everything fails soft. The whole of it, page and picture, shares one time limit.
    """
    started = time.monotonic()
    page = _fetch_page(url)
    if page is None:
        return Preview()
    info = parse(page.body, page.charset, page.url)
    left = PREVIEW_SECONDS - (time.monotonic() - started)
    image = None
    if info.image_url and left >= MIN_IMAGE_SECONDS:
        image = _fetch_image(info.image_url, left)
    return Preview(title=info.title, image=image)


def _fetch_page(url: str) -> netguard.Fetched | None:
    try:
        page = netguard.fetch(
            url,
            max_bytes=PAGE_MAX_BYTES,
            seconds=PREVIEW_SECONDS,
            accept="text/html,application/xhtml+xml;q=0.9",
            truncate=True,
        )
    except netguard.RefusedError as exc:
        logger.info("A link could not be previewed (%s).", exc.reason)
        return None
    if page.content_type not in ("text/html", "application/xhtml+xml"):
        logger.info("A link could not be previewed (type).")
        return None
    return page


def _fetch_image(url: str, seconds: float) -> bytes | None:
    # Any scheme but http(s) is refused by `fetch` itself (`file:`, `data:`, `ftp:`...).
    try:
        found = netguard.fetch(
            url,
            max_bytes=min(IMAGE_MAX_BYTES, rooms_conf.photo_max_bytes()),
            seconds=seconds,
            accept="image/jpeg,image/png,image/webp",
        )
    except netguard.RefusedError as exc:
        logger.info("The picture of a link could not be read (%s).", exc.reason)
        return None
    return found.body


def domain_of(url: str) -> str:
    """The host of an address, lower case, for the audit log: nothing else of the address."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return without_control_characters(host.lower())[:80]
