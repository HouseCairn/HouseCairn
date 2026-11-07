from django.http import HttpRequest

from housecairn.accounts.adapters import AccountAdapter


def signup(request: HttpRequest) -> dict[str, bool]:
    """Whether templates may offer local sign-up."""
    return {"local_signup_open": AccountAdapter(request).is_open_for_signup(request)}
