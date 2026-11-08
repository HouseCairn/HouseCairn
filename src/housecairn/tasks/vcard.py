"""The contact file (.vcf) of a contractor, as vCard 3.0 (RFC 2426, docs/adr/0045).

3.0 and not 4.0: Apple Contacts, Google Contacts, Android, Outlook and Thunderbird all read it,
and Apple and Google write it themselves, while 4.0 is read with gaps by some of them. Nothing
here needs what 4.0 adds. Every value is escaped as the RFC says and cleaned of control
characters, so that a name or a note can never start a line of its own.
"""

import datetime
import unicodedata

from django.utils.text import slugify

from housecairn.tasks.models import Contractor

CONTENT_TYPE = "text/vcard; charset=utf-8"
PRODID = "-//HouseCairn//Contractor//EN"
FOLD_AT = 75  # octets per line, the break excluded (RFC 2426, section 2.6)


def _clean(value: str, *, keep_newlines: bool) -> str:
    """No carriage return, no control or invisible character; newlines only where asked."""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        char
        for char in text
        if (char == "\n" and keep_newlines)
        or unicodedata.category(char) not in {"Cc", "Cf", "Zl", "Zp"}
    )


def escape(value: str, *, multiline: bool = False) -> str:
    """A text value: backslash, semicolon and comma escaped, a line break written as \\n."""
    text = _clean(value, keep_newlines=multiline)
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    """Cut a line into pieces of at most 75 octets, each continuation starting with a space."""
    pieces: list[str] = []
    current, size = "", 0
    limit = FOLD_AT
    for char in line:
        width = len(char.encode())
        if size + width > limit:
            pieces.append(current)
            current, size, limit = " ", 1, FOLD_AT
        current += char
        size += width
    pieces.append(current)
    return "\r\n".join(pieces)


def render(contractor: Contractor) -> str:
    """The vCard of a contractor, with CRLF line ends."""
    name = escape(contractor.name)
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"PRODID:{PRODID}",
        f"UID:urn:uuid:{contractor.id}",
        f"FN:{name}",
        f"N:{name};;;;",
    ]
    if contractor.trade_label:
        lines.append(f"TITLE:{escape(contractor.trade_label)}")
    if contractor.phone:
        lines.append(f"TEL;TYPE=WORK,VOICE:{escape(contractor.phone)}")
    if contractor.email:
        lines.append(f"EMAIL;TYPE=INTERNET:{escape(contractor.email)}")
    if contractor.address.strip():
        lines.append(f"ADR;TYPE=WORK:;;{escape(contractor.address.strip(), multiline=True)};;;;")
    if contractor.note.strip():
        lines.append(f"NOTE:{escape(contractor.note.strip(), multiline=True)}")
    revised = contractor.updated_at.astimezone(datetime.UTC)
    lines.append(f"REV:{revised:%Y%m%dT%H%M%SZ}")
    lines.append("END:VCARD")
    return "".join(f"{fold(line)}\r\n" for line in lines)


def filename(contractor: Contractor) -> str:
    """A file name that is safe anywhere: ASCII letters, digits and hyphens, then .vcf."""
    stem = slugify(contractor.name)[:50].strip("-") or "contact"
    return f"{stem}.vcf"
