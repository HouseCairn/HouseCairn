"""Actions in place and the browser's back button (NAV-05, NAV-12).

Done, Skip and Undo answer an HTMX row with the row and the undo banner, and a plain
post with a redirect to `next#occ-<id>`; the banner never lives in the address. Creation
forms are sent with `no-store` and a one-time token against a second sending.
"""

import re
import threading
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.core.middleware import FORM_TOKEN_FIELD
from housecairn.homes.models import Home
from housecairn.stock import services as stock_services
from housecairn.stock.models import Article
from housecairn.tasks import materials, services
from housecairn.tasks.models import Occurrence, Status, Task

pytest_plugins = ("tests.tasks_fixtures", "tests.stock_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

HTMX = {"HTTP_HX_REQUEST": "true"}


def url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"tasks:{name}", kwargs={"home_id": home.id, **kwargs})


def act(name: str, home: Home, occurrence: Occurrence) -> str:
    return url(name, home, task_id=occurrence.task_id, occurrence_id=occurrence.id)


def token_of(page: str) -> str:
    marker = f'name="{FORM_TOKEN_FIELD}" value="'
    assert marker in page
    return page.split(marker, 1)[1].split('"', 1)[0]


class TestDoneInPlace:
    def test_htmx_gets_the_row_and_the_banner_not_a_page(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        today = url("today", alice_home)
        response = signed_in.post(
            act("complete", alice_home, owner_occurrence),
            {"next": today, "in_place": "row"},
            **HTMX,
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "<html" not in body
        assert body.lstrip().startswith(f'<li id="occ-{owner_occurrence.id}"')
        assert "task-row-closed" in body
        assert 'class="row" href="' in body
        assert "autofocus" in body
        assert '<div id="undo-region" hx-swap-oob="innerHTML">' in body
        assert "Marked done." in body
        undo = act("undo", alice_home, owner_occurrence)
        assert f'hx-post="{undo}"' in body
        assert 'name="in_place" value="banner"' in body
        owner_occurrence.refresh_from_db()
        assert owner_occurrence.status == Status.DONE
        # Nothing is kept for a later page: the banner came with the answer.
        assert "Marked done." not in signed_in.get(today).content.decode()

    def test_skip_in_place(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        response = signed_in.post(
            act("skip", alice_home, owner_occurrence),
            {"next": url("list", alice_home), "in_place": "row"},
            **HTMX,
        )
        assert response.status_code == 200
        assert "Skipped." in response.content.decode()
        owner_occurrence.refresh_from_db()
        assert owner_occurrence.status == Status.SKIPPED

    def test_the_rows_post_in_place(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        for page in (url("today", alice_home), url("list", alice_home)):
            content = signed_in.get(page).content.decode()
            assert f'id="occ-{owner_occurrence.id}"' in content
            assert f'hx-post="{act("complete", alice_home, owner_occurrence)}"' in content
            assert 'hx-target="closest li" hx-swap="outerHTML"' in content
            assert 'name="in_place" value="row"' in content
            assert 'id="undo-region" class="undo-region" aria-live="polite"' in content

    def test_without_script_a_redirect_to_the_row_and_no_state_in_the_address(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        listing = f"{url('list', alice_home)}?status=open"
        response = signed_in.post(
            act("complete", alice_home, owner_occurrence),
            {"next": listing, "in_place": "row"},  # no HX-Request: the script did not run
        )
        assert response.status_code == 302
        assert response["Location"] == f"{listing}#occ-{owner_occurrence.id}"
        assert "undo" not in response["Location"]
        page = signed_in.get(listing).content.decode()
        assert "Marked done." in page
        assert act("undo", alice_home, owner_occurrence) in page
        assert 'name="in_place" value="banner"' not in page  # a plain form, as the page
        # Read once: back on the page later, the banner is gone, as a message would be.
        assert "Marked done." not in signed_in.get(listing).content.decode()

    def test_an_old_undo_address_shows_nothing(
        self, signed_in: Client, alice: User, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        services.complete(alice, owner_occurrence)
        page = signed_in.get(f"{url('list', alice_home)}?undo={owner_occurrence.id}")
        assert "Marked done." not in page.content.decode()

    def test_a_second_done_in_place_says_so_and_changes_nothing(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        data = {"next": url("today", alice_home), "in_place": "row"}
        signed_in.post(act("complete", alice_home, owner_occurrence), data, **HTMX)
        again = signed_in.post(act("complete", alice_home, owner_occurrence), data, **HTMX)
        assert again.status_code == 200
        assert "already closed" in again.content.decode()


class TestUndo:
    def test_undo_from_the_banner_in_place(
        self, signed_in: Client, alice_home: Home, owner_task: Task, owner_occurrence: Occurrence
    ) -> None:
        today = url("today", alice_home)
        signed_in.post(
            act("complete", alice_home, owner_occurrence),
            {"next": today, "in_place": "row"},
            **HTMX,
        )
        response = signed_in.post(
            act("undo", alice_home, owner_occurrence),
            {"next": today, "in_place": "banner"},
            **HTMX,
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert body.lstrip().startswith('<div class="undo-banner"><span>Undone.</span></div>')
        assert f'<li id="occ-{owner_occurrence.id}" hx-swap-oob="true"' in body
        assert 'class="button-small button-done" autofocus' in body
        owner_occurrence.refresh_from_db()
        assert owner_occurrence.status == Status.PLANNED
        assert services.open_occurrence_of(owner_task) == owner_occurrence

    def test_undo_without_script_comes_back_to_the_row_without_undo_state(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        listing = url("list", alice_home)
        signed_in.post(act("complete", alice_home, owner_occurrence), {"next": listing})
        signed_in.get(listing)  # the banner is shown, then forgotten
        response = signed_in.post(act("undo", alice_home, owner_occurrence), {"next": listing})
        assert response["Location"] == f"{listing}#occ-{owner_occurrence.id}"
        page = signed_in.get(listing).content.decode()
        assert "Undone." in page
        assert "Marked done." not in page
        # The browser's back button reloads the list: no stale banner, no second Undo.
        assert "Marked done." not in signed_in.get(listing).content.decode()


class TestStock:
    def test_done_then_undo_in_place_takes_then_gives_back_the_stock(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        owner_task: Task,
        owner_occurrence: Occurrence,
        article: Article,
    ) -> None:
        stock_services.record_movement(alice, article, kind="entry", quantity=Decimal("4"))
        materials.add_material(alice, owner_task, article, Decimal("1"))
        today = url("today", alice_home)
        row = {"next": today, "in_place": "row"}
        signed_in.post(act("complete", alice_home, owner_occurrence), row, **HTMX)
        assert stock_services.quantity_of(article) == Decimal("3")
        # A double tap: the second Done is refused and takes nothing more.
        signed_in.post(act("complete", alice_home, owner_occurrence), row, **HTMX)
        assert stock_services.quantity_of(article) == Decimal("3")
        signed_in.post(
            act("undo", alice_home, owner_occurrence),
            {"next": today, "in_place": "banner"},
            **HTMX,
        )
        assert stock_services.quantity_of(article) == Decimal("4")

    @pytest.mark.django_db(transaction=True)
    def test_two_done_at_once_take_the_stock_once(
        self, alice: User, alice_home: Home, owner_task: Task, article: Article
    ) -> None:
        """On PostgreSQL, two connections: the second waits for the row lock, then is refused."""
        if connection.vendor != "postgresql":
            pytest.skip("a row lock needs PostgreSQL; SQLite runs one write at a time")
        stock_services.record_movement(alice, article, kind="entry", quantity=Decimal("4"))
        materials.add_material(alice, owner_task, article, Decimal("1"))
        occurrence = services.open_occurrence_of(owner_task)
        assert occurrence is not None
        address = act("complete", alice_home, occurrence)
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def tap() -> None:
            client = Client()
            client.force_login(alice)
            try:
                barrier.wait(timeout=10)
                codes.append(
                    client.post(
                        address, {"next": url("today", alice_home), "in_place": "row"}, **HTMX
                    ).status_code
                )
            finally:
                connections.close_all()

        threads = [threading.Thread(target=tap) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert codes == [200, 200]
        assert stock_services.quantity_of(article) == Decimal("3")


class TestCreationForms:
    def test_a_creation_form_is_not_stored(self, signed_in: Client, alice_home: Home) -> None:
        for address in (url("create", alice_home), reverse("rooms:create", args=[alice_home.id])):
            response = signed_in.get(address)
            assert response.status_code == 200
            assert response["Cache-Control"] == "no-store"
        assert "no-store" not in signed_in.get(url("today", alice_home)).get("Cache-Control", "")

    def test_the_forms_of_a_creation_page_do_not_restore_their_input(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        forms = (
            url("create", alice_home),
            reverse("rooms:create", args=[alice_home.id]),
            reverse("projects:create", args=[alice_home.id]),
        )
        for address in forms:
            page = signed_in.get(address).content.decode()
            posts = re.findall(r"<form\b[^>]*\bmethod=\"post\"[^>]*>", page, re.IGNORECASE)
            assert posts, address
            assert all('autocomplete="off"' in tag for tag in posts), address

    def test_a_second_sending_is_refused(
        self, signed_in: Client, alice_home: Home, owner_occurrence: Occurrence
    ) -> None:
        today = url("today", alice_home)
        page = signed_in.get(f"{url('create', alice_home)}?next={today}").content.decode()
        data = {
            "title": "Bleed the radiators",
            "priority": "normal",
            "repeat_mode": "once",
            "repeat_unit": "month",
            "repeat_interval": "1",
            "hide_days_before": "0",
            "next": today,
            FORM_TOKEN_FIELD: token_of(page),
        }
        # A browser's post is read by the CSRF check first; the test client skips that
        # check, so the form goes urlencoded, which the middleware reads itself.
        body = urlencode(data)
        form = "application/x-www-form-urlencoded"
        first = signed_in.post(url("create", alice_home), body, content_type=form)
        assert first.status_code == 302
        second = signed_in.post(url("create", alice_home), body, content_type=form, follow=True)
        assert Task.objects.filter(home=alice_home, title="Bleed the radiators").count() == 1
        assert second.redirect_chain[0][0] == today
        assert "already sent" in second.content.decode()

    def test_a_form_sent_with_an_error_gets_a_new_token(
        self, signed_in: Client, alice_home: Home
    ) -> None:
        page = signed_in.get(url("create", alice_home)).content.decode()
        sent = signed_in.post(
            url("create", alice_home), {"title": "", FORM_TOKEN_FIELD: token_of(page)}
        )
        assert sent.status_code == 200
        assert sent["Cache-Control"] == "no-store"
        assert token_of(sent.content.decode()) != token_of(page)
