"""How a person is named on screen and in the API (docs/adr/0045).

One helper for every page: the display name the person chose, then their full name, then the
part of the address before the "@". The whole address is shown only where the address is the
subject (the household list under a name, an invitation, the account itself).
"""

from typing import Any

DISPLAY_NAME_MAX_LENGTH = 60


def person_name(user: Any) -> str:
    """The name to show for `user`; empty for nobody (no account, or one deleted)."""
    if user is None:
        return ""
    chosen = str(getattr(user, "display_name", "") or "").strip()
    if chosen:
        return chosen
    full = str(user.get_full_name() or "").strip()
    if full:
        return full
    email = str(getattr(user, "email", "") or "")
    return email.partition("@")[0]
