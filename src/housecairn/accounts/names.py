"""How a person is named on screen and in the API (docs/adr/0045).

One helper for every page: the display name the person chose, then their full name, then the
part of the address before the "@". The whole address is shown only where the address is the
subject (the household list under a name, an invitation, the account itself).
"""

import unicodedata
from collections.abc import Iterable
from typing import Any

DISPLAY_NAME_MAX_LENGTH = 60

# Letters and symbols that draw nothing: the Hangul fillers, the blank Braille pattern, the
# Mongolian vowel separator. Space, format, control, unassigned and bare combining marks
# are caught by their category.
_BLANK_GLYPHS = frozenset("\u115f\u1160\u3164\uffa0\u2800\u180e\u17b4\u17b5")
# The ones that fill a line without showing anything, which a name must not start or end
# with, and which tell nothing apart when two names are compared.
FILLERS = "\u3164\u115f\u1160\uffa0\u2800"
_NOT_A_GLYPH = frozenset({"Zs", "Zl", "Zp", "Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me"})


def has_visible_glyph(value: str) -> bool:
    """Whether `value` draws something: a name of spaces and fillers does not."""
    return any(
        char not in _BLANK_GLYPHS and unicodedata.category(char) not in _NOT_A_GLYPH
        for char in value
    )


def trim_fillers(value: str) -> str:
    """`value` without spaces and fillers at either end: "Sam" and "Sam\u3164" look alike."""
    return value.strip(f"{FILLERS} \t\n\r")


def same_name_key(name: str) -> str:
    """What two names are compared by: no case, no filler, since neither shows on screen."""
    return "".join(c for c in name.casefold() if c not in FILLERS).strip()


def looks_like_an_address(value: str) -> bool:
    """An "@" in any width (full-width, small) is there: the name would pass for an address."""
    return "@" in unicodedata.normalize("NFKC", value)


def person_name(user: Any) -> str:
    """The name to show for `user`; empty for nobody (no account, or one deleted)."""
    if user is None:
        return ""
    chosen = trim_fillers(str(getattr(user, "display_name", "") or ""))
    if chosen:
        return chosen
    full = str(user.get_full_name() or "").strip()
    if full:
        return full
    email = str(getattr(user, "email", "") or "")
    return email.partition("@")[0]


def labels(users: Iterable[Any]) -> dict[Any, str]:
    """The name of each person for a list, by primary key.

    Two people of the same name (compared without case or filler characters) are told
    apart by their address in brackets, since in a list there is nothing else to choose by
    (docs/adr/0045).
    """
    people = list(users)
    shown = {user.pk: person_name(user) for user in people}
    count: dict[str, int] = {}
    for name in shown.values():
        count[same_name_key(name)] = count.get(same_name_key(name), 0) + 1
    out: dict[Any, str] = {}
    for user in people:
        name, email = shown[user.pk], str(getattr(user, "email", "") or "")
        out[user.pk] = f"{name} ({email})" if count[same_name_key(name)] > 1 and email else name
    return out
