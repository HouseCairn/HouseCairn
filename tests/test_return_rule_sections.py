"""The return rule in Stock, Projects, Budget, Reports, Labels and Homes, and the budget of
a room (core/navigation.py, docs/developer/design-guide.md, "Return rule").

The journeys are those measured by the navigation review: the budget of a room, a quote
added from a project, a project opened from the budget, the stock replenished; then a
hostile `next` on one route of each app, and deletions.
"""

import re
from collections.abc import Callable
from decimal import Decimal
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.labels import services as label_services
from housecairn.projects import services as project_services
from housecairn.projects.models import Project, Quote
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures", "tests.projects_fixtures")

pytestmark = pytest.mark.django_db

HOSTILE = [
    "https://evil.example.com/",
    "//evil.example.com/",
    "/\\evil.example.com/",
    "javascript:alert(1)",
    "/h/x/?a=1\r\nSet-Cookie: x=1",
]


def back_links(html: str) -> list[tuple[str, str]]:
    """(href, text) of the back links of a page."""
    found = re.findall(r'<a class="back-link" href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)
    return [
        (href.replace("&amp;", "&"), re.sub(r"<[^>]+>", "", text).strip()) for href, text in found
    ]


def href_of(html: str, path: str) -> str:
    """The first link of the page whose address starts with `path`."""
    match = re.search(rf'href="({re.escape(path)}[^"]*)"', html)
    assert match, path
    return match.group(1).replace("&amp;", "&")


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def url(name: str, **kwargs: object) -> str:
    return reverse(name, kwargs=kwargs)


def hidden_next(value: str) -> str:
    return f'<input type="hidden" name="next" value="{value}">'


@pytest.fixture
def room_project(alice: User, alice_home: Home, owner_room: Room) -> Project:
    """A project of the room, 800 planned this year: the room has a budget."""
    project = project_services.create_project(
        alice, alice_home, title="Paint the walls", rooms=[owner_room]
    )
    project_services.create_line(
        alice, project, label="Paint", nature="material", planned=Decimal("800")
    )
    return project


# ---------- the budget of a room (NAV-11) ----------


class TestRoomBudget:
    def test_the_room_page_leads_to_its_budget(
        self, signed_in: Client, alice_home: Home, owner_room: Room, room_project: Project
    ) -> None:
        room_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        html = signed_in.get(room_url).content.decode()
        assert "Budget of the room" in html
        link = href_of(html, url("budget:room", home_id=alice_home.id, room_id=owner_room.id))
        assert query(link)["next"] == [room_url]
        page = signed_in.get(link)
        assert page.status_code == 200
        assert back_links(page.content.decode()) == [(room_url, "Living room")]

    def test_the_budget_by_room_opens_the_budget_of_the_room_in_budget(
        self, signed_in: Client, alice_home: Home, owner_room: Room, room_project: Project
    ) -> None:
        listing = url("budget:rooms", home_id=alice_home.id)
        html = signed_in.get(listing).content.decode()
        link = href_of(html, url("budget:room", home_id=alice_home.id, room_id=owner_room.id))
        assert query(link)["next"] == [listing]
        page = signed_in.get(link)
        body = page.content.decode()
        assert page.context["nav_section"] == "budget"
        assert back_links(body) == [(listing, "Budget")]
        project_url = url("projects:detail", home_id=alice_home.id, project_id=room_project.id)
        assert query(href_of(body, project_url))["next"] == [
            urlsplit(link).path + "?year=" + query(link)["year"][0]
        ]

    def test_open_the_room_keeps_budget_marked_and_comes_back(
        self, signed_in: Client, alice_home: Home, owner_room: Room, room_project: Project
    ) -> None:
        detail = url("budget:room", home_id=alice_home.id, room_id=owner_room.id)
        html = signed_in.get(detail).content.decode()
        assert "Open the room" in html
        room_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        link = href_of(html, room_url)
        assert query(link)["next"] == [detail]
        page = signed_in.get(link)
        assert page.context["nav_section"] == "budget"
        assert back_links(page.content.decode()) == [(detail, "Budget")]

    def test_a_room_of_another_home_has_no_budget_page(
        self, signed_in: Client, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        from housecairn.rooms import services as room_services

        foreign = room_services.create_room(bob, bob_home, name="Cellar")
        assert (
            signed_in.get(url("budget:room", home_id=alice_home.id, room_id=foreign.id)).status_code
            == 404
        )


# ---------- a project opened from the budget, a quote added from a project ----------


class TestProjectFromBudget:
    def test_the_project_opened_from_the_budget_says_budget_and_keeps_it_marked(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        listing = url("budget:projects", home_id=alice_home.id)
        html = signed_in.get(listing).content.decode()
        project_url = url(
            "projects:detail", home_id=alice_home.id, project_id=living_room_project.id
        )
        link = href_of(html, project_url)
        assert query(link)["next"] == [listing]
        page = signed_in.get(link)
        assert page.context["nav_section"] == "budget"
        assert back_links(page.content.decode()) == [(listing, "Budget")]

    def test_an_action_in_place_keeps_the_origin_of_the_project(
        self, signed_in: Client, alice_home: Home, quote: Quote
    ) -> None:
        listing = url("budget:projects", home_id=alice_home.id)
        project_url = url("projects:detail", home_id=alice_home.id, project_id=quote.project_id)
        html = signed_in.get(project_url + "?next=" + quote_path(listing)).content.decode()
        assert hidden_next(listing) in html
        response = signed_in.post(
            url("projects:quote-status", home_id=alice_home.id, quote_id=quote.id),
            {"status": "rejected", "next": listing},
        )
        assert response["Location"] == project_url + "?next=" + quote_path(listing)


def quote_path(path: str) -> str:
    return quote(path, safe="")


class TestQuoteFromProject:
    def test_add_a_quote_carries_the_project_and_comes_back_to_it(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        project_url = url(
            "projects:detail", home_id=alice_home.id, project_id=living_room_project.id
        )
        html = signed_in.get(project_url).content.decode()
        link = href_of(
            html,
            url("projects:quote-create", home_id=alice_home.id, project_id=living_room_project.id),
        )
        assert query(link)["next"] == [project_url]
        form = signed_in.get(link).content.decode()
        assert back_links(form) == [(project_url, "Paint the living room")]
        assert hidden_next(project_url) in form
        response = signed_in.post(
            link, {"amount": "450", "status": "received", "next": project_url}
        )
        assert response.status_code == 302
        assert response["Location"] == project_url

    def test_a_quote_added_from_the_compare_page_goes_back_there(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        compare = url("projects:compare", home_id=alice_home.id)
        response = signed_in.post(
            url("projects:quote-create", home_id=alice_home.id, project_id=living_room_project.id),
            {"amount": "450", "status": "received", "next": compare},
        )
        assert response["Location"] == compare


# ---------- the stock replenished ----------


class TestStockReplenished:
    def test_a_stock_item_opened_from_the_list_carries_it(
        self, signed_in: Client, alice_home: Home, article: Article
    ) -> None:
        listing = url("stock:list", home_id=alice_home.id)
        html = signed_in.get(listing).content.decode()
        link = href_of(html, url("stock:detail", home_id=alice_home.id, article_id=article.id))
        assert query(link)["next"] == [listing]

    def test_a_movement_keeps_where_the_stock_item_was_opened_from(
        self, signed_in: Client, alice_home: Home, article: Article, owner_room: Room
    ) -> None:
        article.rooms.add(owner_room)
        item_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        article_url = url("stock:detail", home_id=alice_home.id, article_id=article.id)
        html = signed_in.get(item_url).content.decode()
        link = href_of(html, article_url)
        assert query(link)["next"] == [item_url]
        page = signed_in.get(link).content.decode()
        assert hidden_next(item_url) in page
        response = signed_in.post(
            url("stock:movement-add", home_id=alice_home.id, article_id=article.id),
            {"kind": "entry", "quantity": "3", "next": item_url},
        )
        assert response["Location"] == article_url + "?next=" + quote_path(item_url) + "#movement"
        again = signed_in.get(response["Location"].split("#")[0]).content.decode()
        assert back_links(again) == [(item_url, "Living room")]
        assert 'id="movement"' in again


# ---------- a hostile next, on one route of each app ----------


@pytest.fixture
def routes(
    alice: User,
    alice_home: Home,
    owner_room: Room,
    article: Article,
    living_room_project: Project,
) -> dict[str, Callable[[], tuple[str, str]]]:
    """App -> (page, the default its back link leads to without a safe next)."""
    label, _created = label_services.create_label(
        alice, alice_home, kind="room", target_id=owner_room.id
    )
    home = alice_home.id
    routes = {
        "stock": lambda: (
            url("stock:edit", home_id=home, article_id=article.id),
            url("stock:detail", home_id=home, article_id=article.id),
        ),
        "projects": lambda: (
            url("projects:edit", home_id=home, project_id=living_room_project.id),
            url("projects:detail", home_id=home, project_id=living_room_project.id),
        ),
        "budget": lambda: (
            url("budget:room", home_id=home, room_id=owner_room.id),
            url("budget:rooms", home_id=home),
        ),
        "reports": lambda: (url("reports:create", home_id=home), url("reports:list", home_id=home)),
        "labels": lambda: (
            url("labels:detail", home_id=home, label_id=label.id),
            url("labels:list", home_id=home),
        ),
        "homes": lambda: (url("homes:edit", home_id=home), url("homes:detail", home_id=home)),
    }
    return routes


class TestHostileNext:
    @pytest.mark.parametrize("app", ["stock", "projects", "budget", "reports", "labels", "homes"])
    def test_a_safe_next_is_followed_and_a_hostile_one_refused(
        self,
        signed_in: Client,
        alice_home: Home,
        routes: dict[str, Callable[[], tuple[str, str]]],
        app: str,
    ) -> None:
        page, default = routes[app]()
        safe = url("tasks:today", home_id=alice_home.id)
        html = signed_in.get(page, {"next": safe}).content.decode()
        assert back_links(html)[0] == (safe, "Today")
        for hostile in HOSTILE:
            html = signed_in.get(page, {"next": hostile}).content.decode()
            assert back_links(html)[0][0] == default
            assert "evil.example.com" not in html
            assert "javascript:alert" not in html


# ---------- deletions ----------


class TestDeletion:
    def test_a_project_deleted_from_the_budget_goes_back_to_the_budget(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        budget = url("budget:projects", home_id=alice_home.id)
        response = signed_in.post(
            url("projects:delete", home_id=alice_home.id, project_id=living_room_project.id),
            {"next": budget},
        )
        assert response["Location"] == budget

    def test_a_project_deleted_from_its_page_lands_on_the_list(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        project_url = url(
            "projects:detail", home_id=alice_home.id, project_id=living_room_project.id
        )
        delete = url("projects:delete", home_id=alice_home.id, project_id=living_room_project.id)
        html = signed_in.get(delete, {"next": url("budget:projects", home_id=alice_home.id)})
        assert hidden_next(url("budget:projects", home_id=alice_home.id)) in html.content.decode()
        response = signed_in.post(delete, {"next": project_url})
        assert response["Location"] == url("projects:list", home_id=alice_home.id)

    def test_a_stock_item_deleted_from_a_room_goes_back_to_the_room(
        self, signed_in: Client, alice_home: Home, article: Article, owner_room: Room
    ) -> None:
        room_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        delete = url("stock:delete", home_id=alice_home.id, article_id=article.id)
        assert signed_in.post(delete, {"next": room_url})["Location"] == room_url

    def test_a_stock_item_deleted_from_its_page_lands_on_the_stock(
        self, signed_in: Client, alice: User, alice_home: Home, article: Article
    ) -> None:
        article_url = url("stock:detail", home_id=alice_home.id, article_id=article.id)
        delete = url("stock:delete", home_id=alice_home.id, article_id=article.id)
        html = signed_in.get(delete, {"next": article_url}).content.decode()
        assert hidden_next(article_url) in html
        response = signed_in.post(delete, {"next": article_url})
        assert response["Location"] == url("stock:list", home_id=alice_home.id)

    def test_a_label_revoked_from_its_object_goes_back_to_it_never_to_itself(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        room_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        label, _created = label_services.create_label(
            alice, alice_home, kind="room", target_id=owner_room.id
        )
        revoke = url("labels:revoke", home_id=alice_home.id, label_id=label.id)
        assert signed_in.post(revoke, {"next": room_url})["Location"] == room_url
        label, _created = label_services.create_label(
            alice, alice_home, kind="room", target_id=owner_room.id
        )
        detail = url("labels:detail", home_id=alice_home.id, label_id=label.id)
        revoke = url("labels:revoke", home_id=alice_home.id, label_id=label.id)
        response = signed_in.post(revoke, {"next": detail})
        assert response["Location"] == url("labels:list", home_id=alice_home.id)

    def test_a_home_deleted_lands_on_the_homes_never_on_a_page_of_it(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        delete = url("homes:delete", home_id=alice_home.id)
        html = signed_in.get(delete, {"next": url("homes:list")}).content.decode()
        assert hidden_next(url("homes:list")) in html
        response = signed_in.post(
            url("homes:delete", home_id=alice_home.id),
            {"confirmation": alice_home.name, "next": url("homes:detail", home_id=alice_home.id)},
        )
        assert response["Location"] == url("homes:list")


# ---------- reports and labels: back to the page they were made from ----------


class TestFromAnObject:
    def test_a_problem_reported_from_an_item_goes_back_to_it(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        item_url = url("rooms:item-detail", home_id=alice_home.id, item_id=owner_item.id)
        html = signed_in.get(item_url).content.decode()
        link = href_of(html, url("reports:create", home_id=alice_home.id))
        assert query(link)["next"] == [item_url]
        assert query(link)["item"] == [str(owner_item.id)]
        response = signed_in.post(
            link, {"title": "It leaks", "place": f"item:{owner_item.id}", "next": item_url}
        )
        assert response["Location"] == item_url

    def test_a_label_made_from_a_room_opens_with_a_way_back_to_it(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        room_url = url("rooms:detail", home_id=alice_home.id, room_id=owner_room.id)
        html = signed_in.get(room_url).content.decode()
        action = re.search(r'action="([^"]*/labels/new/[^"]*)"', html)
        assert action
        create = action.group(1).replace("&amp;", "&")
        assert query(create)["next"] == [room_url]
        response = signed_in.post(create, {"target": f"room:{owner_room.id}"})
        page = signed_in.get(response["Location"]).content.decode()
        assert back_links(page) == [(room_url, "Living room")]


# ---------- homes: what a POST does with `next` ----------

POST_HOSTILE = [
    "https://evil.example.com/",
    "//evil.example.com/",
    "/\\evil.example.com/",
    "javascript:alert(1)",
]


def home_form(**extra: str) -> dict[str, str]:
    return {"name": "Main house", "currency": "EUR", "hemisphere": "north", **extra}


class TestHomePostRedirects:
    def test_edit_follows_a_safe_next(self, signed_in: Client, alice_home: Home) -> None:
        safe = url("tasks:today", home_id=alice_home.id)
        response = signed_in.post(url("homes:edit", home_id=alice_home.id), home_form(next=safe))
        assert response.status_code == 302
        assert response["Location"] == safe

    def test_edit_without_next_lands_on_the_home(self, signed_in: Client, alice_home: Home) -> None:
        response = signed_in.post(url("homes:edit", home_id=alice_home.id), home_form())
        assert response["Location"] == url("homes:detail", home_id=alice_home.id)

    @pytest.mark.parametrize("hostile", POST_HOSTILE)
    def test_edit_refuses_a_hostile_next(
        self, signed_in: Client, alice_home: Home, hostile: str
    ) -> None:
        response = signed_in.post(url("homes:edit", home_id=alice_home.id), home_form(next=hostile))
        assert response["Location"] == url("homes:detail", home_id=alice_home.id)

    def test_create_goes_back_to_its_context_with_added_and_open(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        context = url("tasks:today", home_id=alice_home.id)
        response = signed_in.post(url("homes:create"), home_form(name="Cabin", next=context))
        assert response["Location"] == context
        cabin = Home.objects.get(name="Cabin")
        page = signed_in.get(context)
        texts = [str(m) for m in page.context["messages"]]
        record = url("homes:detail", home_id=cabin.id)
        assert texts == [f'Home added · <a href="{record}">Open</a>']

    def test_create_without_next_opens_the_new_home(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        response = signed_in.post(url("homes:create"), home_form(name="Cabin"))
        cabin = Home.objects.get(name="Cabin")
        assert response["Location"] == url("homes:detail", home_id=cabin.id)

    @pytest.mark.parametrize("hostile", POST_HOSTILE)
    def test_create_refuses_a_hostile_next(
        self, signed_in: Client, alice_home: Home, hostile: str
    ) -> None:
        response = signed_in.post(url("homes:create"), home_form(name="Cabin", next=hostile))
        cabin = Home.objects.get(name="Cabin")
        assert response["Location"] == url("homes:detail", home_id=cabin.id)

    def test_a_household_action_keeps_the_next(
        self, signed_in: Client, alice: User, alice_home: Home
    ) -> None:
        from housecairn.homes import services as home_services

        home_services.invite(
            alice,
            alice_home,
            email="guest@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )
        invitation = alice_home.invitations.get()
        origin = url("homes:detail", home_id=alice_home.id)
        household = url("homes:household", home_id=alice_home.id)
        response = signed_in.post(
            url("homes:invitation-resend", home_id=alice_home.id, invitation_id=invitation.id),
            {"next": origin},
        )
        assert response["Location"] == household + "?next=" + quote_path(origin)

    @pytest.mark.parametrize("hostile", POST_HOSTILE)
    def test_a_household_action_drops_a_hostile_next(
        self, signed_in: Client, alice: User, alice_home: Home, hostile: str
    ) -> None:
        from housecairn.homes import services as home_services

        home_services.invite(
            alice,
            alice_home,
            email="guest@example.com",
            role="member",
            delivery=home_services.Delivery(),
        )
        invitation = alice_home.invitations.get()
        response = signed_in.post(
            url("homes:invitation-resend", home_id=alice_home.id, invitation_id=invitation.id),
            {"next": hostile},
        )
        assert response["Location"] == url("homes:household", home_id=alice_home.id)


# ---------- a hostile next on a POST, one route of each app ----------


@pytest.fixture
def posts(
    alice_home: Home,
    owner_room: Room,
    article: Article,
    living_room_project: Project,
) -> dict[str, tuple[str, dict[str, str]]]:
    """App -> (the address posted to, the form without `next`)."""
    home = alice_home.id
    return {
        "stock": (
            url("stock:movement-add", home_id=home, article_id=article.id),
            {"kind": "entry", "quantity": "3"},
        ),
        "projects": (
            url("projects:quote-create", home_id=home, project_id=living_room_project.id),
            {"amount": "450", "status": "received"},
        ),
        "reports": (url("reports:create", home_id=home), {"title": "It leaks"}),
        "labels": (
            url("labels:create", home_id=home),
            {"target": f"room:{owner_room.id}"},
        ),
    }


class TestHostileNextOnPost:
    @pytest.mark.parametrize("app", ["stock", "projects", "reports", "labels"])
    @pytest.mark.parametrize("hostile", POST_HOSTILE)
    def test_a_post_never_leaves_the_site(
        self,
        signed_in: Client,
        posts: dict[str, tuple[str, dict[str, str]]],
        app: str,
        hostile: str,
    ) -> None:
        address, data = posts[app]
        response = signed_in.post(address, {**data, "next": hostile})
        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("/")
        assert not location.startswith("//")
        assert "\\" not in location
        assert "evil.example.com" not in location
        assert "javascript:" not in location
