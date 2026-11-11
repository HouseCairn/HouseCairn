"""Back links and breadcrumbs of the screens that wrote them by hand, or had none.

Each screen follows the design guide ("Back link and breadcrumbs"): the back link names
its target and leads to the safe `next`, else to the parent in the tree; a page of More
leads to More, on a phone only; a form has its breadcrumbs on a computer. Every address
comes from `reverse`, so the same tests hold under `HOUSECAIRN_URL_PREFIX`.
"""

import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client, override_settings
from django.urls import get_script_prefix, reverse, set_script_prefix

from housecairn.accounts.models import User
from housecairn.accounts.names import person_name
from housecairn.homes.models import Home, Membership, Role
from housecairn.notifications import services as notification_services
from housecairn.notifications.models import Channel
from housecairn.projects.models import BudgetLine, Project, Quote
from housecairn.rooms.models import Item, Photo, Room
from housecairn.stock import services as stock_services
from housecairn.stock.models import Article, Supplier
from housecairn.tasks import services as task_services
from housecairn.tasks.models import Contractor
from tests.rooms_support import image_bytes, upload
from tests.test_breadcrumbs import trail
from tests.test_home_sso import PROVIDERS, signed_in_through
from tests.test_instance_providers import declare
from tests.test_instance_settings import recent

pytest_plugins = (
    "tests.rooms_fixtures",
    "tests.stock_fixtures",
    "tests.projects_fixtures",
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _script_prefix(settings: Any) -> Iterator[None]:
    """The prefix of the instance before any address is built, whatever ran before.

    The addresses expected are built with `reverse` before the first request of the test;
    another module may have left the script prefix at `/`.
    """
    previous = get_script_prefix()
    set_script_prefix((settings.FORCE_SCRIPT_NAME or "") + "/")
    yield
    set_script_prefix(previous)


def url(name: str, **kwargs: object) -> str:
    return reverse(name, kwargs=kwargs or None)


def back_links(html: str) -> list[tuple[str, str, bool]]:
    """(href, text, phone only) of each back link of a page."""
    found = re.findall(r'<a class="back-link" href="([^"]*)"([^>]*)>(.*?)</a>', html, re.S)
    return [
        (
            href.replace("&amp;", "&"),
            re.sub(r"<[^>]+>", "", text).strip(),
            "data-phone-only" in attributes,
        )
        for href, attributes, text in found
    ]


def h1(html: str) -> str:
    found = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert found
    return re.sub(r"<[^>]+>", "", found.group(1)).strip()


def secondary_buttons(html: str) -> list[tuple[str, str]]:
    found = re.findall(r'<a class="button button-secondary" href="([^"]*)">(.*?)</a>', html, re.S)
    return [(href.replace("&amp;", "&"), text.strip()) for href, text in found]


@pytest.fixture
def more() -> str:
    return url("more")


# ---------- the confirmation pages of the household ----------


class TestConfirmationOfTheHousehold:
    def test_leaving_names_the_household_and_cancel_leads_back_to_it(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        household = url("homes:household", home_id=alice_home.id)
        html = signed_in.get(url("homes:leave", home_id=alice_home.id)).text
        assert back_links(html) == [(household, "Household and roles", False)]
        assert "Cancel" not in [text for _, text, _ in back_links(html)]
        assert secondary_buttons(html) == [(household, "Cancel")]

    def test_with_next_the_link_and_cancel_follow_the_origin(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        origin = url("homes:detail", home_id=alice_home.id)
        page = url("homes:leave", home_id=alice_home.id)
        html = signed_in.get(page, {"next": origin}).text
        assert back_links(html) == [(origin, alice_home.name, False)]
        assert secondary_buttons(html) == [(origin, "Cancel")]

    def test_removing_a_member_names_the_member(
        self,
        signed_in: Client,
        alice_home: Home,
        bob: User,
        add_member: Callable[[Home, User, Role], Membership],
    ) -> None:
        membership = add_member(alice_home, bob, Role.MEMBER)
        kwargs = {"home_id": alice_home.id, "member_id": membership.id}
        member = url("homes:member", **kwargs)
        html = signed_in.get(url("homes:member-remove", **kwargs)).text
        assert back_links(html) == [(member, person_name(bob), False)]
        assert secondary_buttons(html) == [(member, "Cancel")]

    def test_a_hostile_next_is_not_followed(self, signed_in: Client, alice_home: Home) -> None:
        household = url("homes:household", home_id=alice_home.id)
        html = signed_in.get(
            url("homes:leave", home_id=alice_home.id), {"next": "https://evil.example.com/"}
        ).text
        assert back_links(html) == [(household, "Household and roles", False)]
        assert secondary_buttons(html) == [(household, "Cancel")]


# ---------- pages of More, Me ----------


class TestCalendarFeeds:
    def test_the_feeds_lead_back_to_more_on_a_phone(self, signed_in: Client, more: str) -> None:
        html = signed_in.get(url("calendar:feeds")).text
        assert back_links(html) == [(more, "More", True)]

    def test_with_next_they_lead_back_to_the_origin(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        origin = url("rooms:list", home_id=alice_home.id)
        html = signed_in.get(url("calendar:feeds"), {"next": origin}).text
        assert back_links(html) == [(origin, "Rooms", False)]


@pytest.fixture
def channel(alice: User) -> Iterator[Channel]:
    with override_settings(HOUSECAIRN_NOTIFICATIONS_ENABLED=True):
        yield notification_services.add_channel(
            alice, name="Phone", url="tgram://123456789:fixture-not-a-token/987654"
        )


class TestNotificationChannel:
    def test_a_channel_leads_back_to_the_notifications_or_to_the_origin(
        self, client: Client, alice: User, alice_home: Home, channel: Channel
    ) -> None:
        recent(client, alice)
        page = url("notifications:channel", channel_id=channel.id)
        origin = url("rooms:list", home_id=alice_home.id)
        with override_settings(HOUSECAIRN_NOTIFICATIONS_ENABLED=True):
            html = client.get(page).text
            with_next = client.get(page, {"next": origin}).text
        assert back_links(html) == [(url("notifications:index"), "Notifications", False)]
        assert back_links(with_next) == [(origin, "Rooms", False)]


class TestDeleteAccount:
    def test_the_deletion_leads_back_to_security_and_sign_in_or_to_the_origin(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        html = signed_in.get(url("account_delete")).text
        assert back_links(html) == [(url("more-security"), "Security and sign-in", False)]
        origin = url("rooms:list", home_id=alice_home.id)
        html = signed_in.get(url("account_delete"), {"next": origin}).text
        assert back_links(html) == [(origin, "Rooms", False)]


# ---------- pages of More, Home and Help ----------


class TestMyHomes:
    def test_the_list_is_titled_like_its_entry_of_more(self, signed_in: Client, more: str) -> None:
        html = signed_in.get(url("homes:list")).text
        assert h1(html) == "My homes"
        assert "<title>My homes" in html
        assert back_links(html) == [(more, "More", True)]

    def test_a_home_locked_by_a_provider_leads_back_to_my_homes(
        self, client: Client, alice: User, alice_home: Home, settings: object
    ) -> None:
        settings.SOCIALACCOUNT_PROVIDERS = PROVIDERS  # type: ignore[attr-defined]
        alice_home.required_provider = "company"
        alice_home.save()
        signed_in_through(client, alice, None)
        response = client.get(url("homes:detail", home_id=alice_home.id))
        assert response.status_code == 403
        assert back_links(response.text) == [(url("homes:list"), "My homes", False)]

    def test_with_next_the_locked_home_leads_back_to_the_origin(
        self, client: Client, alice: User, alice_home: Home, settings: object
    ) -> None:
        settings.SOCIALACCOUNT_PROVIDERS = PROVIDERS  # type: ignore[attr-defined]
        alice_home.required_provider = "company"
        alice_home.save()
        signed_in_through(client, alice, None)
        origin = url("more")
        response = client.get(url("homes:detail", home_id=alice_home.id), {"next": origin})
        assert back_links(response.text) == [(origin, "More", True)]


class TestAbout:
    def test_about_leads_back_to_more_on_a_phone_for_a_signed_in_person_only(
        self, client: Client, alice: User, more: str
    ) -> None:
        # More needs an account: a visitor reading About has nowhere to go back to.
        assert back_links(client.get(url("about")).text) == []
        client.force_login(alice)
        html = client.get(url("about")).text
        assert back_links(html) == [(more, "More", True)]

    def test_with_next_it_leads_back_to_the_origin(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        origin = url("rooms:list", home_id=alice_home.id)
        html = signed_in.get(url("about"), {"next": origin}).text
        assert back_links(html) == [(origin, "Rooms", False)]


# ---------- the administration of the instance ----------


@pytest.fixture
def admin(client: Client, make_user: Callable[..., User]) -> Client:
    recent(client, make_user("admin@example.com", is_staff=True, is_superuser=True))
    return client


class TestInstanceAdministration:
    def test_a_provider_leads_back_to_the_providers_or_to_the_origin(
        self, admin: Client, more: str
    ) -> None:
        declare(User.objects.get(email="admin@example.com"))
        page = url("instance:provider", slug="company")
        providers = url("instance:providers")
        assert back_links(admin.get(page).text) == [(providers, "Sign-in providers", False)]
        assert back_links(admin.get(page, {"next": more}).text) == [(more, "More", True)]
        # An origin without a label keeps the default, named.
        overview = url("instance:overview")
        html = admin.get(page, {"next": overview}).text
        assert back_links(html) == [(providers, "Sign-in providers", False)]

    def test_a_section_of_the_settings_leads_back_to_the_settings_or_to_the_origin(
        self, admin: Client, more: str
    ) -> None:
        page = reverse("instance:settings", kwargs={"section": "server"})
        settings_page = url("instance:settings")
        html = admin.get(page).text
        assert back_links(html) == [(settings_page, "Instance settings", False)]
        assert back_links(admin.get(page, {"next": more}).text) == [(more, "More", True)]


# ---------- the photo form ----------


class TestPhotoForm:
    def test_the_form_names_the_room_and_shows_its_breadcrumbs(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        room = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        html = signed_in.get(
            url("rooms:room-photo-add", home_id=alice_home.id, room_id=owner_room.id)
        ).text
        assert back_links(html) == [(room, owner_room.name, False)]
        assert trail(html) == [
            (url("rooms:list", home_id=alice_home.id), "Rooms"),
            (room, owner_room.name),
            (None, "Add a photo"),
        ]

    def test_the_form_of_an_item_names_the_item(
        self, signed_in: Client, alice_home: Home, owner_room: Room, owner_item: Item
    ) -> None:
        item = url("rooms:item-detail", home_id=alice_home.id, item_id=owner_item.id)
        html = signed_in.get(
            url("rooms:item-photo-add", home_id=alice_home.id, item_id=owner_item.id)
        ).text
        assert back_links(html) == [(item, owner_item.name, False)]
        assert [label for _, label in trail(html)] == [
            "Rooms",
            owner_room.name,
            owner_item.name,
            "Add a photo",
        ]

    def test_with_next_the_link_and_the_form_once_sent_lead_back_to_the_origin(
        self, signed_in: Client, alice_home: Home, owner_room: Room, media_root: object
    ) -> None:
        origin = url("budget:rooms", home_id=alice_home.id)
        form = url("rooms:room-photo-add", home_id=alice_home.id, room_id=owner_room.id)
        html = signed_in.get(form, {"next": origin}).text
        assert back_links(html) == [(origin, "Budget", False)]
        assert f'<input type="hidden" name="next" value="{origin}">' in html
        response = signed_in.post(
            form,
            {
                "file": upload(image_bytes("PNG")),
                "caption": "",
                "category": "general",
                "next": origin,
            },
        )
        assert response.status_code == 302
        assert response["Location"] == origin
        assert Photo.objects.filter(room=owner_room).count() == 1
        # Without next, the room.
        response = signed_in.post(
            form, {"file": upload(image_bytes("PNG")), "caption": "", "category": "general"}
        )
        assert response.status_code == 302
        assert response["Location"] == url(
            "rooms:detail", home_id=alice_home.id, room_id=owner_room.id
        )


# ---------- breadcrumbs of the forms added to FORM_TITLES ----------


@pytest.fixture
def contractor(alice: User, alice_home: Home) -> Contractor:
    return task_services.create_contractor(alice, alice_home, name="Plumber B")


@pytest.fixture
def supplier(alice: User, article: Article) -> Supplier:
    return stock_services.create_supplier(alice, article, name="Acme", last_price=Decimal("4.2"))


class TestFormBreadcrumbs:
    def test_quote_forms(
        self, signed_in: Client, alice_home: Home, living_room_project: Project, quote: Quote
    ) -> None:
        projects = url("projects:list", home_id=alice_home.id)
        project = url("projects:detail", home_id=alice_home.id, project_id=living_room_project.id)
        for page, title in [
            (
                url(
                    "projects:quote-create",
                    home_id=alice_home.id,
                    project_id=living_room_project.id,
                ),
                "Add a quote",
            ),
            (
                url("projects:quote-edit", home_id=alice_home.id, quote_id=quote.id),
                "Edit the quote",
            ),
        ]:
            html = signed_in.get(page).text
            assert trail(html) == [
                (projects, "Projects"),
                (project, living_room_project.title),
                (None, title),
            ]
            # A form keeps its back link on a computer.
            assert back_links(html) == [(project, living_room_project.title, False)]

    def test_budget_line_forms(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        labour_line: BudgetLine,
    ) -> None:
        for page, title in [
            (
                url(
                    "projects:line-create",
                    home_id=alice_home.id,
                    project_id=living_room_project.id,
                ),
                "Add a budget line",
            ),
            (
                url("projects:line-edit", home_id=alice_home.id, line_id=labour_line.id),
                "Edit the budget line",
            ),
        ]:
            html = signed_in.get(page).text
            assert [label for _, label in trail(html)] == [
                "Projects",
                living_room_project.title,
                title,
            ]

    def test_the_annual_envelope(self, signed_in: Client, alice_home: Home) -> None:
        projects = url("projects:list", home_id=alice_home.id)
        html = signed_in.get(url("projects:envelope", home_id=alice_home.id)).text
        assert trail(html) == [(projects, "Projects"), (None, "Annual envelope")]
        assert back_links(html) == [(projects, "Projects", False)]

    def test_contractor_forms(
        self, signed_in: Client, alice_home: Home, contractor: Contractor
    ) -> None:
        contractors = url("tasks:contractors", home_id=alice_home.id)
        create = signed_in.get(url("tasks:contractor-create", home_id=alice_home.id)).text
        assert [label for _, label in trail(create)][-2:] == ["Contractors", "Add a contractor"]
        assert (contractors, "Contractors") in trail(create)
        edit = signed_in.get(
            url("tasks:contractor-edit", home_id=alice_home.id, contractor_id=contractor.id)
        ).text
        assert [label for _, label in trail(edit)][-3:] == [
            "Contractors",
            contractor.name,
            "Edit the contractor",
        ]

    def test_supplier_forms(
        self, signed_in: Client, alice_home: Home, article: Article, supplier: Supplier
    ) -> None:
        detail = url("stock:detail", home_id=alice_home.id, article_id=article.id)
        for page, title in [
            (
                url("stock:supplier-create", home_id=alice_home.id, article_id=article.id),
                "Add a supplier",
            ),
            (
                url("stock:supplier-edit", home_id=alice_home.id, supplier_id=supplier.id),
                "Edit the supplier",
            ),
        ]:
            html = signed_in.get(page).text
            assert trail(html)[-2:] == [(detail, article.name), (None, title)]
            assert [label for _, label in trail(html)][:2] == ["Rooms", "Stock"]

    def test_import_and_template_forms(self, signed_in: Client, alice_home: Home) -> None:
        for page, title in [
            (url("homes:import", home_id=alice_home.id), "Import tables"),
            (url("tasks:templates", home_id=alice_home.id), "Add from a template"),
        ]:
            html = signed_in.get(page).text
            assert trail(html)[-1] == (None, title)
