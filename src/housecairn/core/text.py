"""Small text rules shared by the services."""

import unicodedata

# Format characters (Cf) that carry meaning and stay: the joiners that build composed emoji
# (family, heart on fire) and shape Persian, Arabic and Indic scripts, and the tag characters
# that spell a regional flag (England, Scotland, Wales).
_KEPT_FORMAT = {"\u200c", "\u200d"}
_KEPT_FORMAT_RANGES = ((0xE0020, 0xE007F),)


def _is_dropped(char: str) -> bool:
    category = unicodedata.category(char)
    if category == "Cc":
        return True
    if category != "Cf":
        return False
    if char in _KEPT_FORMAT:
        return False
    return not any(low <= ord(char) <= high for low, high in _KEPT_FORMAT_RANGES)


def without_control_characters(value: str) -> str:
    """`value` without the control (Cc) and the invisible or reordering format (Cf) characters.

    Bell, escape, the zero-width space, the byte order mark and the bidirectional overrides and
    isolates (U+202A to U+202E, U+2066 to U+2069) have no place in a name: they hide text,
    reorder it or break a log line. The joiners (U+200C, U+200D) and the tag characters
    (U+E0020 to U+E007F) stay, since composed emoji and several scripts need them. Tab and line
    break go too, so use this on single-line values only.
    """
    return "".join(c for c in value if not _is_dropped(c))
