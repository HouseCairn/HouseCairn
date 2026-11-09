"""The QR code of a label, as a matrix of modules (docs/adr/0047).

Encoded by ReportLab's own encoder, so that the server needs no second library: the same
matrix is drawn on screen (an inline SVG, no image file) and in the PDF. Error
correction level Q restores up to a quarter of the code, for a sticker that gets scuffed.
"""

from functools import lru_cache

from django.utils.safestring import SafeString, mark_safe
from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel

# Modules of white around the code: the 4 the standard asks for.
QUIET_ZONE = 4


@lru_cache(maxsize=512)
def matrix(text: str) -> tuple[tuple[bool, ...], ...]:
    """The modules of the code for `text`, row by row; True is a dark module."""
    code = QRCode(None, QRErrorCorrectLevel.Q)
    code.addData(text)
    code.make()
    size = code.moduleCount
    # `modules` holds the finished matrix; the encoder's accessors are untyped.
    return tuple(tuple(bool(code.modules[r][c]) for c in range(size)) for r in range(size))


def svg(text: str, *, title: str) -> SafeString:
    """An inline SVG of the code. `title` is the accessible name; it is escaped here."""
    from django.utils.html import escape

    rows = matrix(text)
    size = len(rows)
    total = size + 2 * QUIET_ZONE
    path: list[str] = []
    for y, row in enumerate(rows):
        x = 0
        while x < size:
            if not row[x]:
                x += 1
                continue
            start = x
            while x < size and row[x]:
                x += 1
            path.append(f"M{start + QUIET_ZONE} {y + QUIET_ZONE}h{x - start}v1h-{x - start}z")
    return mark_safe(  # noqa: S308 - built from integers and an escaped title
        f'<svg class="qr-code" viewBox="0 0 {total} {total}" '
        f'role="img" aria-label="{escape(title)}" shape-rendering="crispEdges">'
        f'<rect width="{total}" height="{total}" fill="#fff"/>'
        f'<path d="{"".join(path)}" fill="#000"/></svg>'
    )
