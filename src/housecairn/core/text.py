"""Small text rules shared by the services."""

import unicodedata


def without_control_characters(value: str) -> str:
    """`value` without the Unicode control (Cc) and format (Cf) characters.

    Bell, escape, the zero-width characters and the bidirectional overrides (U+202E) have no
    place in a name: they hide text, reorder it or break a log line. Tab and line break go too,
    so use this on single-line values only.
    """
    return "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"})
