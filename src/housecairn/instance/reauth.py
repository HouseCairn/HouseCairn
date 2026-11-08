"""A recent sign-in, asked before an instance setting changes (docs/adr/0031).

Recent means a sign-in or re-authentication within `ACCOUNT_REAUTHENTICATION_TIMEOUT`
(five minutes by default). An account with no password, no authenticator and no passkey
(single sign-on only) cannot re-authenticate here: django-allauth does the same, so it
counts as recent and the identity provider's own session policy applies.
"""

import time

from allauth.account import app_settings
from allauth.account.internal.flows.login import get_authentication_records
from allauth.account.internal.flows.reauthentication import get_reauthentication_flows
from django.http import HttpRequest


def signed_in_recently(request: HttpRequest) -> bool:
    user = request.user
    if not user.is_authenticated:
        return False
    if not get_reauthentication_flows(user):
        return True
    records = get_authentication_records(request, user)
    if not records:
        return False
    last = max(float(r.get("at", 0)) for r in records)
    return bool(time.time() - last < app_settings.REAUTHENTICATION_TIMEOUT)
