from django.http import HttpRequest

from housecairn.accounts.adapters import AccountAdapter
from housecairn.accounts.services import email_is_configured


def signup(request: HttpRequest) -> dict[str, bool]:
    """Whether templates may offer local sign-up, and what needs outgoing email."""
    return {
        "local_signup_open": AccountAdapter(request).is_open_for_signup(request),
        "email_configured": email_is_configured(),
    }
