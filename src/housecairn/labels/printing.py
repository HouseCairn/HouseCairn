"""The sheet of labels, as a PDF made on the server (docs/adr/0047).

Two layouts: an A4 sheet of 3 by 8 labels (the 63.5 by 33.9 mm format of the common
adhesive sheets) and a 62 mm roll for a label printer (one label per page, the length
the label needs). Each label carries the QR code, the name of the object and where it is.
The text is set in Helvetica, which every PDF reader has: nothing is embedded, nothing is
fetched. A character Helvetica has no glyph for is printed as "?" and the QR code still
opens the right page.
"""

import io
import unicodedata
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from housecairn.labels import qr

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
# A sheet or a roll holds as many labels as one request may ask for.
MAX_LABELS = 200
MAX_NAME_CHARACTERS = 120


@dataclass(frozen=True)
class Layout:
    code: str
    title: object  # a lazy translation
    columns: int
    rows: int
    page: tuple[float, float]
    label: tuple[float, float]
    left: float
    top: float
    gap: float  # between two columns
    qr_side: float
    name_size: float
    place_size: float

    @property
    def per_page(self) -> int:
        return self.columns * self.rows


A4_3X8 = Layout(
    code="a4-3x8",
    title=_("A4 sheet, 3 by 8 labels (63.5 by 33.9 mm)"),
    columns=3,
    rows=8,
    page=A4,
    label=(63.5 * mm, 33.9 * mm),
    left=7.2 * mm,
    top=15.1 * mm,
    gap=2.5 * mm,
    qr_side=27 * mm,
    name_size=8.5,
    place_size=7,
)
ROLL_62 = Layout(
    code="roll-62",
    title=_("62 mm roll, one label per page (label printer)"),
    columns=1,
    rows=1,
    page=(62 * mm, 40 * mm),
    label=(62 * mm, 40 * mm),
    left=0,
    top=0,
    gap=0,
    qr_side=32 * mm,
    name_size=10,
    place_size=8,
)
LAYOUTS: dict[str, Layout] = {layout.code: layout for layout in (A4_3X8, ROLL_62)}
DEFAULT_LAYOUT = A4_3X8.code


@dataclass(frozen=True)
class Sticker:
    """What one label shows and where its code leads."""

    name: str
    place: str
    url: str


def printable(text: str, *, limit: int) -> str:
    """Text Helvetica can set: one line, no control character, cut at `limit`, and "?" for
    a character its encoding (Windows Latin-1) does not have."""
    flat = " ".join(
        "".join(" " if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} else c for c in text)
        .strip()
        .split()
    )[:limit]
    return flat.encode("cp1252", errors="replace").decode("cp1252")


def _lines(text: str, font: str, size: float, width: float, maximum: int) -> list[str]:
    lines: list[str] = simpleSplit(text, font, size, width)
    if len(lines) > maximum:
        lines = lines[:maximum]
        lines[-1] = lines[-1].rstrip()[:-1] + "…" if lines[-1] else "…"
    return lines


def _draw_code(canvas: Canvas, url: str, x: float, y: float, side: float) -> None:
    rows = qr.matrix(url)
    total = len(rows) + 2 * qr.QUIET_ZONE
    module = side / total
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(x, y, side, side, stroke=0, fill=1)
    canvas.setFillColorRGB(0, 0, 0)
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            if not row[c]:
                c += 1
                continue
            start = c
            while c < len(row) and row[c]:
                c += 1
            canvas.rect(
                x + (start + qr.QUIET_ZONE) * module,
                y + side - (r + qr.QUIET_ZONE + 1) * module,
                (c - start) * module,
                module,
                stroke=0,
                fill=1,
            )


def _draw_label(canvas: Canvas, layout: Layout, sticker: Sticker, x: float, y: float) -> None:
    """One label whose lower left corner is at (x, y)."""
    width, height = layout.label
    padding = 1.5 * mm
    side = min(layout.qr_side, height - 2 * padding)
    _draw_code(canvas, sticker.url, x + padding, y + (height - side) / 2, side)
    bottom = y + (height - side) / 2
    canvas.linkURL(sticker.url, (x + padding, bottom, x + padding + side, bottom + side))
    text_x = x + padding + side + 1.5 * mm
    text_width = x + width - padding - text_x
    top = y + height - padding
    canvas.setFillColorRGB(0, 0, 0)
    cursor = top - layout.name_size
    for line in _lines(sticker.name, FONT_BOLD, layout.name_size, text_width, 3):
        canvas.setFont(FONT_BOLD, layout.name_size)
        canvas.drawString(text_x, cursor, line)
        cursor -= layout.name_size * 1.2
    if sticker.place:
        cursor -= layout.place_size * 0.3
        canvas.setFillColorRGB(0.25, 0.25, 0.25)
        for line in _lines(sticker.place, FONT, layout.place_size, text_width, 2):
            canvas.setFont(FONT, layout.place_size)
            canvas.drawString(text_x, cursor, line)
            cursor -= layout.place_size * 1.2


def render(stickers: list[Sticker], layout: Layout) -> bytes:
    """The PDF of `stickers` in `layout`; an empty list is a mistake of the caller."""
    if not stickers or len(stickers) > MAX_LABELS:
        raise ValueError(f"Between 1 and {MAX_LABELS} labels.")
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=layout.page, pageCompression=1)
    canvas.setTitle("HouseCairn labels")
    canvas.setAuthor("HouseCairn")
    canvas.setCreator("HouseCairn")
    page_height = layout.page[1]
    for index, sticker in enumerate(stickers):
        slot = index % layout.per_page
        if index and slot == 0:
            canvas.showPage()
        column, row = slot % layout.columns, slot // layout.columns
        x = layout.left + column * (layout.label[0] + layout.gap)
        y = page_height - layout.top - (row + 1) * layout.label[1]
        _draw_label(canvas, layout, sticker, x, y)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
