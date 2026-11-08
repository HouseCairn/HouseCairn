"""Small text rules shared by the services."""

import unicodedata

# Joiners that build composed emoji (family, heart on fire) and shape Persian, Arabic and
# Indic scripts: they stay, but only between two visible characters.
_JOINERS = {"\u200c", "\u200d"}
_BLACK_FLAG = "\U0001f3f4"
_TAG_FIRST, _TAG_CANCEL = 0xE0020, 0xE007F
# The longest tag sequence of a regional flag is a few letters and the cancel tag.
_MAX_FLAG_TAGS = 8
# Line and paragraph separators (Zl, Zp) break a single line as a line feed does.
_LINE_BREAKS = {"\u2028", "\u2029"}


def _is_visible(char: str) -> bool:
    """A character that shows something: not a control, a format, a space or a separator."""
    return unicodedata.category(char) not in {"Cc", "Cf", "Zs", "Zl", "Zp", "Cn"}


def _is_tag(char: str) -> bool:
    return _TAG_FIRST <= ord(char) <= _TAG_CANCEL


def without_control_characters(value: str) -> str:
    """`value` without the control (Cc) and the invisible or reordering format (Cf) characters.

    Bell, escape, the zero-width space, the byte order mark, the bidirectional overrides and
    isolates (U+202A to U+202E, U+2066 to U+2069) and the line and paragraph separators
    (U+2028, U+2029) have no place in a name: they hide text, reorder it or break a line.
    Tab and line break go too, so use this on single-line values only.

    Two kinds of format character stay, since they carry meaning, and only where they do:

    - the joiners (U+200C, U+200D) between two visible characters (composed emoji, scripts);
    - the tag characters (U+E0020 to U+E007F) of a regional flag: after the black flag
      (U+1F3F4) and up to the cancel tag (U+E007F). Tags anywhere else are invisible text
      and go, as does a flag sequence that is never closed.
    """
    out: list[str] = []
    i, size = 0, len(value)
    while i < size:
        char = value[i]
        if char == _BLACK_FLAG:
            out.append(char)
            end = i + 1
            while end < size and _is_tag(value[end]) and end - i <= _MAX_FLAG_TAGS + 1:
                end += 1
                if ord(value[end - 1]) == _TAG_CANCEL:
                    out.extend(value[i + 1 : end])
                    i = end - 1
                    break
            i += 1
            continue
        if char in _JOINERS:
            before_ok = bool(out) and _is_visible(out[-1])
            after_ok = i + 1 < size and _is_visible(value[i + 1])
            if before_ok and after_ok:
                out.append(char)
        elif char not in _LINE_BREAKS and unicodedata.category(char) not in {"Cc", "Cf"}:
            out.append(char)
        i += 1
    return "".join(out)
