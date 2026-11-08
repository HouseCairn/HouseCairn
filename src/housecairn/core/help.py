"""Help link of each screen: the page of the documentation site that describes it.

Every named web route is either given a documentation page here or listed as
not being a screen; `tests/test_help_links.py` enforces it, and checks that the
pages exist in the built site (docs/adr/0016).
"""

from django.conf import settings
from django.http import HttpRequest
from django.utils import translation

# Route name -> page of the documentation site (a directory, as published).
HELP_PAGES: dict[str, str] = {
    "index": "screens/start-page/",
    "account_login": "screens/sign-in/",
    "homes:list": "screens/homes/",
    "homes:create": "screens/new-home/",
    "homes:detail": "screens/home/",
    "homes:household": "screens/household/",
    "homes:invite": "screens/household/",
    "homes:invitation-resend": "screens/household/",
    "homes:invitation-revoke": "screens/household/",
    "homes:required-provider": "screens/household/",
    "homes:leave": "screens/member/",
    "homes:unlock": "screens/household/",
    "homes:audit": "screens/audit/",
    "homes:export": "screens/home/",
    "homes:delete": "screens/home/",
    "account_delete": "screens/account/",
    "instance:overview": "screens/instance/",
    "instance:invite": "screens/instance/",
    "instance:invitation-resend": "screens/instance/",
    "instance:invitation-revoke": "screens/instance/",
    "instance:unlock": "screens/instance/",
    "instance:audit": "screens/instance/",
    "instance:settings": "screens/instance-settings/",
    "instance-invitation": "screens/instance-invitation/",
    "homes:member": "screens/member/",
    "homes:member-role": "screens/member/",
    "homes:member-remove": "screens/member/",
    "homes:transfer": "screens/member/",
    "invitation": "screens/invitation/",
    "rooms": "screens/rooms/",
    "rooms:list": "screens/rooms/",
    "rooms:create": "screens/room-form/",
    "rooms:detail": "screens/room/",
    "rooms:edit": "screens/room-form/",
    "rooms:memory": "screens/room-memory/",
    "rooms:delete": "screens/room/",
    "rooms:move": "screens/rooms/",
    "rooms:item-create": "screens/item-form/",
    "rooms:item-detail": "screens/item/",
    "rooms:item-edit": "screens/item-form/",
    "rooms:item-delete": "screens/item/",
    "rooms:room-photo-add": "screens/photo-form/",
    "rooms:item-photo-add": "screens/photo-form/",
    "rooms:photo": "screens/photo-form/",
    "rooms:photo-thumbnail": "screens/photo-form/",
    "rooms:photo-delete": "screens/photo-form/",
    "rooms:search": "screens/search/",
    "tasks": "screens/tasks/",
    "tasks:list": "screens/tasks/",
    "tasks:create": "screens/task-form/",
    "tasks:detail": "screens/task/",
    "tasks:edit": "screens/task-form/",
    "tasks:delete": "screens/task/",
    "tasks:complete": "screens/task/",
    "tasks:undo": "screens/task/",
    "tasks:skip": "screens/task/",
    "tasks:postpone": "screens/task/",
    "tasks:occurrence-edit": "screens/task/",
    "tasks:attachment-add": "screens/task-files/",
    "tasks:attachment": "screens/task-files/",
    "tasks:attachment-thumbnail": "screens/task-files/",
    "tasks:attachment-delete": "screens/task-files/",
    "more": "screens/more/",
    "about": "screens/about/",
}
# Other routes of django-allauth (sign-up, password, email addresses,
# two-factor authentication, single sign-on): the account pages.
HELP_PREFIXES: dict[str, str] = {
    "account_": "screens/account/",
    "mfa_": "screens/account/",
    "socialaccount_": "screens/account/",
    "openid_connect_": "screens/account/",
}
# Routes that are not screens of the interface: the API, its schema and
# explorer, the health check, the web app manifest, and Django's administration site.
NOT_SCREENS: tuple[str, ...] = ("api-", "healthz", "manifest", "admin:")

# Languages published by the documentation site, and their path.
DOCS_LANGUAGES: dict[str, str] = {"en": "", "fr": "fr/"}


def help_page(route: str) -> str | None:
    """Documentation page of the route, or None if it is not a screen."""
    if route in HELP_PAGES:
        return HELP_PAGES[route]
    for prefix, page in HELP_PREFIXES.items():
        if route.startswith(prefix):
            return page
    return None


def help_url(route: str, language: str | None) -> str | None:
    page = help_page(route)
    if page is None:
        return None
    code = (language or settings.LANGUAGE_CODE).split("-")[0].lower()
    prefix = DOCS_LANGUAGES.get(code, "")
    return f"{settings.HOUSECAIRN_DOCS_URL}/{prefix}{page}"


def docs_page_url(page: str, language: str | None) -> str:
    """Address of a page of the documentation site, in the language of the interface."""
    code = (language or settings.LANGUAGE_CODE).split("-")[0].lower()
    return f"{settings.HOUSECAIRN_DOCS_URL}/{DOCS_LANGUAGES.get(code, '')}{page}"


def help_link(request: HttpRequest) -> dict[str, str | None]:
    """Template context: `help_url`, in the language of the interface."""
    match = request.resolver_match
    if match is None or not match.view_name:
        return {"help_url": None}
    return {"help_url": help_url(match.view_name, translation.get_language())}
