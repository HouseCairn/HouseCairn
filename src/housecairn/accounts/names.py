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
# Mongolian vowel separator, the Khmer inherent vowels, the combining grapheme joiner.
# Space, format, control, unassigned and bare combining marks are caught by their category.
_BLANK_GLYPHS = frozenset("\u115f\u1160\u3164\uffa0\u2800\u180e\u17b4\u17b5\u034f")
# The ones that fill a line without showing anything, which a name must not start or end with.
FILLERS = "\u3164\u115f\u1160\uffa0\u2800"
_NOT_A_GLYPH = frozenset({"Zs", "Zl", "Zp", "Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me"})
# What a comparison ignores: whatever changes nothing on screen (control, format, combining
# marks, unassigned code points such as the default-ignorable U+2065 or U+FFF0, which
# renderers hide) and the blank glyphs.
_INVISIBLE = frozenset({"Cc", "Cf", "Mn", "Me", "Cn"})


def has_visible_glyph(value: str) -> bool:
    """Whether `value` draws something: a name of spaces and fillers does not."""
    return any(
        char not in _BLANK_GLYPHS and unicodedata.category(char) not in _NOT_A_GLYPH
        for char in value
    )


def _draws_nothing(char: str) -> bool:
    return char in _BLANK_GLYPHS or char.isspace() or unicodedata.category(char) == "Cn"


def trim_fillers(value: str) -> str:
    """`value` without spaces and fillers at either end: "Sam" and "Sam\u3164" look alike.

    Spaces are all of Unicode's (U+3000, U+00A0...). What sits inside the name stays: the
    zero-width non-joiner of a Persian word and the joiners of a composed emoji are part of it.
    """
    start, end = 0, len(value)
    while start < end and _draws_nothing(value[start]):
        start += 1
    while end > start and _draws_nothing(value[end - 1]):
        end -= 1
    return value[start:end]


def _without_invisible(text: str) -> str:
    return "".join(
        c for c in text if c not in _BLANK_GLYPHS and unicodedata.category(c) not in _INVISIBLE
    )


def same_name_key(name: str) -> str:
    """What two names are compared by: what shows on screen, without case or width.

    Decomposed (compatibility forms: full-width letters, ligatures), case-folded, stripped of
    whatever draws nothing (control and format characters, combining marks, the blank glyphs),
    and with any run of spaces read as one. The removal comes before the case folding too:
    folding turns the combining ypogegrammeni U+0345 into a letter, iota. The decomposition
    comes first so that a mark inserted after a letter cannot fuse with it into a letter that
    stays (e + U+0301 is one letter in NFC, and no mark is then left to remove).
    Accents are therefore
    no difference either: a courtesy, since the only cost is an address shown more often.
    Look-alike letters of another alphabet are not caught (docs/adr/0045).
    """
    shown = _without_invisible(unicodedata.normalize("NFKD", name))
    folded = unicodedata.normalize("NFKD", shown.casefold())
    return " ".join(_without_invisible(folded).split())


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
