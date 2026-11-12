"""The page of a link is read by the worker, not during the request (docs/adr/0069).

The tasks run at once in the tests (`HOUSECAIRN_TASKS_SYNC`). Here the queue is replaced by
a list, so that a test decides when, and whether, the worker gets to the task. The pages
are served by local servers; the guard is the real one, with a test rule that lets the first
loopback address through (the other loopback addresses stand for the private network).
"""

import datetime
import ipaddress
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.core import netguard
from housecairn.homes.models import Home
from housecairn.projects import links, preview
from housecairn.projects.models import PreviewState, Project, ProjectFile, ProjectLink
from housecairn.projects.views import LINK_POLLS
from tests.netservers import AnyPort, Server, can_bind, serving
from tests.test_project_links import detail, link_url, serve_page

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("media_root"),
    pytest.mark.skipif(not can_bind("127.0.0.2"), reason="needs the 127.0.0.0/8 range"),
]

Queued = list[tuple[tuple[Any, ...], dict[str, Any]]]


REAL_IS_PUBLIC = netguard.is_public
REAL_PUBLIC_PORTS = netguard.PUBLIC_PORTS


def only_first_loopback(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return str(address) == "127.0.0.1"


@pytest.fixture(autouse=True)
def local_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netguard, "is_public", only_first_loopback)
    monkeypatch.setattr(netguard, "PUBLIC_PORTS", AnyPort())


@pytest.fixture(autouse=True)
def enabled(settings: Any) -> None:
    settings.HOUSECAIRN_LINK_PREVIEW_ENABLED = True


@pytest.fixture
def site() -> Iterator[Server]:
    with serving("127.0.0.1") as server:
        yield server


@pytest.fixture
def private_site() -> Iterator[Server]:
    with serving("127.0.0.2") as server:
        server.serve("/", 200, b"internal", "text/html")
        yield server


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> Queued:
    """The worker never comes: what was queued is kept, nothing is run."""
    calls: Queued = []
    monkeypatch.setattr(
        "django_q.tasks.async_task", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    return calls


def run_worker(queued: Queued) -> None:
    """Do what the worker would, for what is waiting."""
    for args, _kwargs in queued:
        assert args[0] == "housecairn.projects.links.read_preview"
        links.read_preview(*args[1:])
    queued.clear()


def age(link: ProjectLink, seconds: int) -> None:
    ProjectLink.objects.filter(pk=link.pk).update(
        preview_started_at=timezone.now() - datetime.timedelta(seconds=seconds)
    )


def status_url(home: Home, link: ProjectLink) -> str:
    return link_url("link-status", home, link_id=link.id)


class TestTheRequestDoesNotWait:
    def test_the_web_saves_the_address_and_reads_nothing(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        address = serve_page(site)
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        shown = signed_in.post(add, {"url": address, "title": ""}, follow=True).text
        assert "Link added." in shown
        assert site.connections == 0
        link = ProjectLink.objects.get()
        assert (link.url, link.title, link.image) == (address, "", None)
        assert link.preview_state == PreviewState.RUNNING
        assert link.preview_started_at is not None
        [(args, kwargs)] = queued
        assert args == ("housecairn.projects.links.read_preview", str(link.pk))
        # The worker stops the task before the deadline after which the reading counts as failed.
        assert kwargs["timeout"] == links.PREVIEW_TASK_SECONDS < links.PREVIEW_DEADLINE_SECONDS
        # A task stopped at its timeout is not given again by django-q2 after its `retry`.
        assert kwargs["ack_failure"] is True
        assert "Reading the page…" in shown
        assert f'hx-get="{status_url(alice_home, link)}?n=1"' in shown

    def test_the_api_saves_the_address_and_reads_nothing(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        api_client.force_authenticate(alice)
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        created = api_client.post(
            base, {"project": str(living_room_project.id), "url": serve_page(site)}, format="json"
        )
        assert created.status_code == 201
        assert created.json()["preview_state"] == "running"
        assert created.json()["title"] == ""
        assert site.connections == 0
        run_worker(queued)
        link_id = created.json()["id"]
        read = api_client.get(f"{base}{link_id}/").json()
        assert (read["preview_state"], read["title"]) == ("done", "Tiles")
        assert read["image_url"]

    def test_the_worker_fills_the_title_and_the_picture(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.preview_state) == ("Tiles", PreviewState.DONE)
        assert link.image is not None
        shown = signed_in.get(detail(alice_home, living_room_project)).text
        assert "Tiles" in shown
        assert "Reading the page" not in shown
        assert "hx-get" not in shown

    def test_the_title_typed_by_the_person_is_kept(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site), title="Mine")
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.preview_state) == ("Mine", PreviewState.DONE)
        assert link.image is not None

    def test_a_page_that_gives_nothing_is_a_reading_that_ended(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        site.serve("/page", 200, b"<html><head></head><body>Hello</body></html>", "text/html")
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.DONE)

    def test_an_answer_that_is_not_a_web_page_is_a_failure_and_says_so(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        site.serve("/page", 200, b"{}", "application/json")
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.FAILED)
        shown = signed_in.get(detail(alice_home, living_room_project)).text
        assert "The page could not be read" in shown

    def test_nothing_is_queued_when_the_instance_does_not_read_pages(
        self, alice: User, living_room_project: Project, settings: Any, queued: Queued
    ) -> None:
        settings.HOUSECAIRN_LINK_PREVIEW_ENABLED = False
        link = links.add_link(alice, living_room_project, url="https://example.com/idea")
        assert link.preview_state == PreviewState.NONE
        assert queued == []

    def test_an_error_while_reading_is_a_failure_and_the_link_stays(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        queued: Queued,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(url: str) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(preview, "read", broken)
        address = serve_page(site)
        link = links.add_link(alice, living_room_project, url=address)
        run_worker(queued)
        link.refresh_from_db()
        assert (link.url, link.preview_state) == (address, PreviewState.FAILED)

    def test_a_link_deleted_meanwhile_is_not_brought_back_nor_given_a_picture(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        links.delete_link(alice, link)
        run_worker(queued)
        assert not ProjectLink.objects.exists()
        assert not ProjectFile.objects.exists()

    def test_a_task_for_a_link_that_is_not_being_read_does_nothing(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        run_worker(queued)
        site.requests.clear()
        links.read_preview(str(link.pk))
        assert site.requests == []


class TestTheProtectionsHoldInTheWorker:
    """The same guard as ever, now around a reading that the worker makes."""

    def test_a_page_on_a_private_address_is_never_called(
        self, alice: User, living_room_project: Project, private_site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=private_site.url("/"))
        assert private_site.connections == 0
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.FAILED)
        assert private_site.connections == 0

    def test_a_picture_on_a_private_address_is_never_called(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        private_site: Server,
        queued: Queued,
    ) -> None:
        from tests.test_project_links import page

        site.serve("/page", 200, page(image=private_site.url("/secret.jpg")))
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image) == ("Tiles", None)
        assert private_site.connections == 0

    def test_a_redirect_to_a_private_address_is_not_followed(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        private_site: Server,
        queued: Queued,
    ) -> None:
        site.serve("/page", 302, b"", "text/html")
        site.routes["/page"] = lambda handler: (
            302,
            {"Location": private_site.url("/")},
            b"",
        )
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.FAILED)
        assert private_site.connections == 0

    @pytest.mark.parametrize(
        "address",
        [
            "http://127.0.0.1:9/page",
            "http://nonexistent-host.invalid/page",
            "http://192.0.2.1/page",
        ],
        ids=["loopback", "name-that-does-not-resolve", "documentation-range"],
    )
    def test_a_page_that_cannot_be_reached_or_is_refused_is_a_failure_and_says_so(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        queued: Queued,
        monkeypatch: pytest.MonkeyPatch,
        address: str,
    ) -> None:
        # The real guard, not the one of the other tests that lets a loopback address through.
        monkeypatch.setattr(netguard, "is_public", REAL_IS_PUBLIC)
        monkeypatch.setattr(netguard, "PUBLIC_PORTS", REAL_PUBLIC_PORTS)
        link = links.add_link(alice, living_room_project, url=address)
        run_worker(queued)
        link.refresh_from_db()
        assert (link.url, link.title, link.preview_state) == (address, "", PreviewState.FAILED)
        shown = signed_in.get(detail(alice_home, living_room_project)).text
        assert "The page could not be read" in shown
        assert "Reading the page" not in shown

    def test_the_time_limit_of_the_reading_is_kept(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        queued: Queued,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import time

        from tests.netservers import trickle

        monkeypatch.setattr(preview, "PREVIEW_SECONDS", 1.0)
        site.routes["/page"] = trickle
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        started = time.monotonic()
        run_worker(queued)
        assert time.monotonic() - started < 4.0
        link.refresh_from_db()
        assert link.preview_state == PreviewState.FAILED
        assert site.wait_idle()

    def test_the_limits_of_use_are_taken_before_anything_is_queued(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
        settings: Any,
    ) -> None:
        settings.ACCOUNT_RATE_LIMITS = {"housecairn_link_preview": "1/m/user"}
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        signed_in.post(add, {"url": serve_page(site)}, follow=True)
        shown = signed_in.post(add, {"url": serve_page(site)}, follow=True).text
        assert "Too many links added in a short time" in shown
        assert len(queued) == 1
        assert ProjectLink.objects.count() == 1


class TestAlwaysAnEnd:
    def test_a_reading_that_ends_never_is_failed_after_its_delay(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        age(link, links.PREVIEW_DEADLINE_SECONDS - 3)
        link.refresh_from_db()
        assert links.expire_preview(link).preview_state == PreviewState.RUNNING
        age(link, links.PREVIEW_DEADLINE_SECONDS + 3)
        link.refresh_from_db()
        assert links.expire_preview(link).preview_state == PreviewState.FAILED

    def test_every_way_to_read_a_link_applies_the_delay(
        self,
        signed_in: Client,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))

        def lose_the_task() -> None:
            ProjectLink.objects.filter(pk=link.pk).update(
                preview_state=PreviewState.RUNNING,
                preview_started_at=timezone.now()
                - datetime.timedelta(seconds=links.PREVIEW_DEADLINE_SECONDS + 3),
            )

        lose_the_task()
        page = signed_in.get(detail(alice_home, living_room_project)).text
        assert "The page could not be read" in page
        assert "hx-get" not in page
        lose_the_task()
        assert "The page could not be read" in signed_in.get(status_url(alice_home, link)).text
        lose_the_task()
        api_client.force_authenticate(alice)
        one = reverse(
            "api-v1:home-project-link-detail",
            kwargs={"home_id": alice_home.id, "link_id": link.id},
        )
        assert api_client.get(one).json()["preview_state"] == "failed"

    def test_a_result_that_comes_after_the_delay_changes_nothing(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        age(link, links.PREVIEW_DEADLINE_SECONDS + 3)
        link.refresh_from_db()
        links.expire_preview(link)
        site.requests.clear()
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.FAILED)
        assert site.requests == []  # a task that comes late reads nothing


class TestTheDeadlines:
    def test_the_documented_deadlines_are_the_ones_in_force(self) -> None:
        # Pinned: the guides, the screens and the API name 30 seconds.
        assert links.PREVIEW_DEADLINE_SECONDS == 30
        assert links.PREVIEW_TASK_SECONDS == 25

    def test_a_reading_is_running_at_29_seconds_and_failed_at_31(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        age(link, 29)
        link.refresh_from_db()
        assert links.expire_preview(link).preview_state == PreviewState.RUNNING
        age(link, 31)
        link.refresh_from_db()
        assert links.expire_preview(link).preview_state == PreviewState.FAILED


class TestATaskGivenAgainAfterTheDeadline:
    """django-q2 gives back a task stopped at its timeout once `retry` has passed."""

    def test_a_task_that_comes_after_the_deadline_reads_nothing_and_leaves_it_failed(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        age(link, links.PREVIEW_DEADLINE_SECONDS + 400)  # nobody read the state meanwhile
        site.requests.clear()
        run_worker(queued)
        link.refresh_from_db()
        assert site.requests == []
        assert (link.title, link.image, link.preview_state) == ("", None, PreviewState.FAILED)

    def test_a_task_given_again_after_a_result_does_nothing(
        self, alice: User, living_room_project: Project, site: Server, queued: Queued
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        [(args, _kwargs)] = queued
        run_worker(queued)
        site.requests.clear()
        links.read_preview(*args[1:])
        assert site.requests == []
        link.refresh_from_db()
        assert link.preview_state == PreviewState.DONE


class TestALateResult:
    def test_a_reading_that_ends_after_the_delay_changes_nothing(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        queued: Queued,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))

        def slow(url: str) -> preview.Preview:
            # The page answers after the deadline: the page of the project already said so.
            age(link, links.PREVIEW_DEADLINE_SECONDS + 3)
            links.expire_preview(ProjectLink.objects.get(pk=link.pk))
            return preview.Preview(title="Late")

        monkeypatch.setattr(preview, "read", slow)
        run_worker(queued)
        link.refresh_from_db()
        assert (link.title, link.preview_state) == ("", PreviewState.FAILED)


class TestTheScreen:
    def test_the_fragment_goes_on_asking_a_few_times_only(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        status = status_url(alice_home, link)
        middle = signed_in.get(status, {"n": LINK_POLLS - 1})
        assert f'hx-get="{status}?n={LINK_POLLS}"' in middle.text
        assert 'hx-trigger="load delay:2s"' in middle.text
        assert 'hx-swap="outerHTML"' in middle.text
        last = signed_in.get(status, {"n": LINK_POLLS})
        assert "hx-get" not in last.text
        assert "Reload this page in a moment" in last.text
        # A silly count is no count.
        assert 'hx-get="' in signed_in.get(status, {"n": "many"}).text
        assert "hx-get" not in signed_in.get(status, {"n": 10**9}).text

    def test_the_fragment_stops_asking_once_the_reading_ended(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        status = status_url(alice_home, link)
        assert "hx-get" in signed_in.get(status).text
        run_worker(queued)
        answer = signed_in.get(status)
        assert "hx-get" not in answer.text
        assert "Tiles" in answer.text
        assert "no-store" in answer["Cache-Control"]
        assert answer.text.lstrip().startswith(f'<li id="link-{link.id}"')

    def test_deleting_from_the_fragment_comes_back_to_the_project_not_to_the_fragment(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        fragment = signed_in.get(status_url(alice_home, link)).text
        delete = link_url("link-delete", alice_home, link_id=link.id)
        assert delete in fragment
        assert "next=" in fragment
        assert status_url(alice_home, link).replace("/", "%2F") not in fragment
        assert detail(alice_home, living_room_project).replace("/", "%2F") in fragment

    def test_without_script_reloading_the_page_shows_the_result(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        signed_in.post(add, {"url": serve_page(site)})
        before = signed_in.get(detail(alice_home, living_room_project)).text
        assert "Reading the page…" in before
        run_worker(queued)
        after = signed_in.get(detail(alice_home, living_room_project)).text
        assert "Reading the page" not in after
        assert "Tiles" in after

    def test_a_reader_follows_the_reading_but_cannot_delete(
        self,
        client: Client,
        reader: User,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        client.force_login(reader)
        answer = client.get(status_url(alice_home, link))
        assert answer.status_code == 200
        assert "Reading the page…" in answer.text
        assert "Delete" not in answer.text

    def test_another_home_has_no_status(
        self,
        client: Client,
        bob: User,
        alice: User,
        alice_home: Home,
        bob_home: Home,
        living_room_project: Project,
        site: Server,
        queued: Queued,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        client.force_login(bob)
        assert client.get(status_url(alice_home, link)).status_code == 404
        assert client.get(link_url("link-status", bob_home, link_id=link.id)).status_code == 404
