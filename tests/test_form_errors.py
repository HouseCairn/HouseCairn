"""A refused form says why at the top, and the summary links to the fields in error.

One component (`components/form_errors.html`) is included by every template that draws a
form. The parametrized test posts an invalid form to each screen and reads the page back;
the scan test makes a form added without the component fail (design guide, "Forms").
"""

import re
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.homes.models import Home
from housecairn.projects.models import BudgetLine, Project, Quote
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article
from housecairn.tasks.models import Occurrence, Task

pytest_plugins = (
    "tests.rooms_fixtures",
    "tests.tasks_fixtures",
    "tests.projects_fixtures",
    "tests.stock_fixtures",
)

pytestmark = pytest.mark.django_db

PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": "company",
                "name": "Company SSO",
                "client_id": "housecairn",
                "secret": "not-a-secret",
                "settings": {"server_url": "https://id.example.com"},
            }
        ]
    }
}

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "housecairn" / "templates"


class _Page(HTMLParser):
    """The summary, the ids of the page, the fields in error and the folded sections."""

    def __init__(self) -> None:
        super().__init__()
        self.summary: dict[str, str | None] | None = None
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.invalid = 0
        self.invalid_in_closed_section = 0
        self._in_summary = 0
        self._sections: list[bool] = []  # one flag per open <details>: is it unfolded?

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"] or "")
        if tag == "details":
            self._sections.append("open" in a)
        if "data-form-errors" in a:
            self.summary = a
            self._in_summary = 1
        elif self._in_summary and tag == "div":
            self._in_summary += 1
        if self._in_summary and tag == "a" and (a.get("href") or "").startswith("#"):
            self.links.append((a["href"] or "")[1:])
        if a.get("aria-invalid") == "true":
            self.invalid += 1
            if self._sections and not all(self._sections):
                self.invalid_in_closed_section += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "details" and self._sections:
            self._sections.pop()
        if tag == "div" and self._in_summary:
            self._in_summary -= 1


def read(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


Case = tuple[str, Callable[[dict[str, Any]], str], dict[str, Any]]

# Every screen that shows a form in the page, with an invalid post. A form sent with an
# error comes back as the page itself (200, or 422), never as a redirect.
CASES: list[Case] = [
    ("room-create", lambda c: reverse("rooms:create", args=[c["home"].id]), {"kind": "other"}),
    (
        "room-edit",
        lambda c: reverse("rooms:edit", args=[c["home"].id, c["room"].id]),
        {"kind": "other", "name": ""},
    ),
    (
        "item-create",
        lambda c: reverse("rooms:item-create", args=[c["home"].id, c["room"].id]),
        {"name": ""},
    ),
    (
        "item-edit",
        lambda c: reverse("rooms:item-edit", args=[c["home"].id, c["item"].id]),
        {"name": ""},
    ),
    (
        "room-photo",
        lambda c: reverse("rooms:room-photo-add", args=[c["home"].id, c["room"].id]),
        {},
    ),
    ("task-create", lambda c: reverse("tasks:create", args=[c["home"].id]), {"title": ""}),
    (
        "task-edit",
        lambda c: reverse("tasks:edit", args=[c["home"].id, c["task"].id]),
        {"title": ""},
    ),
    (
        "task-edit-folded",
        lambda c: reverse("tasks:edit", args=[c["home"].id, c["task"].id]),
        {"title": "A task", "repeats": "on", "repeat_interval": "0", "repeat_unit": "months"},
    ),
    ("task-templates", lambda c: reverse("tasks:templates", args=[c["home"].id]), {}),
    (
        "task-attachment",
        lambda c: reverse("tasks:attachment-add", args=[c["home"].id, c["task"].id]),
        {},
    ),
    (
        "task-postpone",
        lambda c: reverse("tasks:postpone", args=[c["home"].id, c["task"].id, c["occurrence"].id]),
        {"until": "not a date"},
    ),
    (
        "task-completion",
        lambda c: reverse(
            "tasks:occurrence-edit", args=[c["home"].id, c["task"].id, c["occurrence"].id]
        ),
        {"completed_on": "not a date"},
    ),
    (
        "contractor-create",
        lambda c: reverse("tasks:contractor-create", args=[c["home"].id]),
        {"name": ""},
    ),
    ("preferences", lambda c: reverse("display-preferences"), {"horizon_days": "-4"}),
    ("project-create", lambda c: reverse("projects:create", args=[c["home"].id]), {"title": ""}),
    (
        "project-edit-folded",
        lambda c: reverse("projects:edit", args=[c["home"].id, c["project"].id]),
        {"title": "A project", "season": "custom"},
    ),
    # Forms of the project page: a refused one comes back as the page itself, not as a redirect.
    (
        "project-task-add",
        lambda c: reverse("projects:task-add", args=[c["home"].id, c["project"].id]),
        {"title": ""},
    ),
    (
        "project-link-add",
        lambda c: reverse("projects:link-add", args=[c["home"].id, c["project"].id]),
        {"url": "javascript:alert(1)"},
    ),
    (
        "project-photo-add",
        lambda c: reverse("projects:file-add", args=[c["home"].id, c["project"].id]),
        {},
    ),
    (
        "line-create",
        lambda c: reverse("projects:line-create", args=[c["home"].id, c["project"].id]),
        {"label": ""},
    ),
    (
        "quote-create",
        lambda c: reverse("projects:quote-create", args=[c["home"].id, c["project"].id]),
        {"contractor_name": ""},
    ),
    ("envelope", lambda c: reverse("projects:envelope", args=[c["home"].id]), {"amount": "x"}),
    ("article-create", lambda c: reverse("stock:create", args=[c["home"].id]), {"name": ""}),
    (
        "supplier-create",
        lambda c: reverse("stock:supplier-create", args=[c["home"].id, c["article"].id]),
        {"name": ""},
    ),
    ("report-create", lambda c: reverse("reports:create", args=[c["home"].id]), {"title": ""}),
    ("home-create", lambda c: reverse("homes:create"), {"name": ""}),
    ("home-edit", lambda c: reverse("homes:edit", args=[c["home"].id]), {"name": ""}),
    (
        "household-invite",
        lambda c: reverse("homes:invite", args=[c["home"].id]),
        {"email": "not an address", "role": "member"},
    ),
    (
        "household-provider",
        lambda c: reverse("homes:required-provider", args=[c["home"].id]),
        {"provider": "unknown"},
    ),
    ("instance-invite", lambda c: reverse("instance:invite"), {"email": "not an address"}),
    ("home-import", lambda c: reverse("homes:import", args=[c["home"].id]), {}),
    ("home-restore", lambda c: reverse("homes:restore"), {}),
    ("profile", lambda c: reverse("profile"), {"display_name": "x" * 300}),
    ("notification-channel", lambda c: reverse("notifications:add"), {"name": "", "url": ""}),
    ("api-token", lambda c: reverse("api-tokens:new"), {"name": ""}),
]


# Refused for a reason that belongs to no field (the files together): the summary says it,
# with no link.
NO_FIELD = {"home-import"}


@pytest.fixture
def context(
    alice: Any,
    alice_home: Home,
    owner_room: Room,
    owner_item: Item,
    owner_task: Task,
    owner_occurrence: Occurrence,
    living_room_project: Project,
    article: Article,
    labour_line: BudgetLine,
    quote: Quote,
    settings: Any,
) -> dict[str, Any]:
    settings.HOUSECAIRN_NOTIFICATIONS_ENABLED = True  # the screen shows its forms
    settings.SOCIALACCOUNT_PROVIDERS = PROVIDERS  # the household offers the sign-in rule
    settings.EMAIL_HOST = "smtp.example.com"  # the instance can invite
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    alice.is_staff = alice.is_superuser = True  # an instance administrator
    alice.save()
    return {
        "home": alice_home,
        "room": owner_room,
        "item": owner_item,
        "task": owner_task,
        "occurrence": owner_occurrence,
        "project": living_room_project,
        "article": article,
    }


@pytest.mark.parametrize(("name", "url", "data"), CASES, ids=[c[0] for c in CASES])
def test_a_refused_form_gets_the_summary(
    name: str,
    url: Callable[[dict[str, Any]], str],
    data: dict[str, Any],
    signed_in: Client,
    context: dict[str, Any],
) -> None:
    response = signed_in.post(url(context), data)
    assert response.status_code in (200, 422), f"{name}: the form was not refused"
    page = read(response.content.decode())
    assert page.summary is not None, f"{name}: no summary of the errors"
    assert page.summary.get("role") == "alert"
    assert page.summary.get("tabindex") == "-1"
    assert "autofocus" in page.summary
    if name in NO_FIELD:
        assert not page.links
        return
    assert page.links, f"{name}: the summary links to no field"
    missing = [target for target in page.links if target not in page.ids]
    assert not missing, f"{name}: the summary links to ids the page does not have: {missing}"
    assert page.invalid, f"{name}: no field is marked aria-invalid"
    assert page.invalid_in_closed_section == 0, f"{name}: a field in error is in a folded section"


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_summary_counts_the_errors(language: str, signed_in: Client, alice_home: Home) -> None:
    signed_in.post(reverse("profile"), {"language": language})
    response = signed_in.post(reverse("rooms:create", args=[alice_home.id]), {"kind": "other"})
    html = response.content.decode()
    title = re.search(r'class="form-errors-title">([^<]*)<', html)
    assert title is not None
    assert re.search(r"\d", title.group(1))


def test_nothing_is_drawn_for_a_form_without_error(signed_in: Client, alice_home: Home) -> None:
    html = signed_in.get(reverse("rooms:create", args=[alice_home.id])).content.decode()
    assert "data-form-errors" not in html


# Forms that report an error in the banner of the page they redirect to (the action is in
# place, on a page that already shows the record), not in a page of their own.
BANNER_FORMS = {"stock/article_detail.html", "tasks/_materials.html"}

FORM_RENDERING = re.compile(
    r"\.as_p\b|\{\{\s*field\b|_field\.html|label_tag|\{\{\s*\w*form\.\w+\s*\}\}"
)


def test_every_template_that_draws_a_form_includes_the_summary() -> None:
    """A template that renders form fields includes the component, or is listed above."""
    partials = {"tasks/_field.html", "tasks/_duration_field.html", "tasks/_material_line.html"}
    # Included inside a form that carries the summary itself.
    inside = {"tasks/_materials_form.html", "instance/_provider_form.html"}
    problems = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        name = path.relative_to(TEMPLATES).as_posix()
        text = path.read_text(encoding="utf-8")
        if name in partials | inside | BANNER_FORMS or name.startswith("components/"):
            continue
        if "<form" not in text:
            continue
        if not FORM_RENDERING.search(text):
            continue
        if "components/form_errors.html" not in text:
            problems.append(name)
    assert not problems, f"these templates draw a form without the summary: {problems}"
    assert "components/form_errors.html" in (TEMPLATES / "instance/_provider_form.html").read_text()


def test_the_sign_in_forms_of_allauth_get_the_summary(alice: Any) -> None:
    """Allauth draws its fields through one element, overridden to include the summary."""
    response = Client().post(
        reverse("account_login"), {"login": "alice@example.com", "password": "x"}
    )
    page = read(response.content.decode())
    assert page.summary is not None
