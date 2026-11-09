"""Links of inspiration and the preview of their page (docs/adr/0050).

The pages are served by local servers; the guard is the real one, with a test rule that lets
the first loopback address through (the other loopback addresses stand for the private
network a link must never reach).
"""

import ipaddress
import logging
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent
from housecairn.core import netguard
from housecairn.homes.models import Home
from housecairn.projects import links, preview, services
from housecairn.projects.models import MAX_LINKS_PER_PROJECT, Project, ProjectFile, ProjectLink
from tests.netservers import AnyPort, Server, can_bind, serving
from tests.rooms_support import image_bytes, upload

pytest_plugins = ("tests.rooms_fixtures", "tests.projects_fixtures")
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("media_root"),
    pytest.mark.skipif(not can_bind("127.0.0.2"), reason="needs the 127.0.0.0/8 range"),
]

LOOPBACK = "127.0.0.1"
OTHER = "127.0.0.2"
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b"<script>alert(1)</script></svg>"
)


def only_first_loopback(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return str(address) == LOOPBACK


@pytest.fixture(autouse=True)
def local_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netguard, "is_public", only_first_loopback)
    monkeypatch.setattr(netguard, "PUBLIC_PORTS", AnyPort())


@pytest.fixture
def enabled(settings: object) -> None:
    settings.HOUSECAIRN_LINK_PREVIEW_ENABLED = True  # type: ignore[attr-defined]


@pytest.fixture
def site() -> Iterator[Server]:
    with serving(LOOPBACK) as server:
        yield server


@pytest.fixture
def private_site() -> Iterator[Server]:
    """A server the guard must never reach."""
    with serving(OTHER) as server:
        server.serve("/", 200, b"internal", "text/html")
        server.serve("/secret.jpg", 200, image_bytes(), "image/jpeg")
        yield server


def page(*, title: str = "Tiles", image: str = "/cover.jpg", extra: str = "") -> bytes:
    return (
        "<!doctype html><html><head>"
        f'<title>Fallback title</title><meta property="og:title" content="{title}">'
        f'<meta property="og:image" content="{image}">{extra}'
        "</head><body><h1>Hello</h1></body></html>"
    ).encode()


def serve_page(site: Server, body: bytes | None = None, image: bytes | None = None) -> str:
    site.serve("/page", 200, body or page())
    site.serve("/cover.jpg", 200, image if image is not None else image_bytes(), "image/jpeg")
    return site.url("/page")


def detail(home: Home, project: Project) -> str:
    return reverse("projects:detail", kwargs={"home_id": home.id, "project_id": project.id})


def link_url(name: str, home: Home, **kwargs: object) -> str:
    return reverse(f"projects:{name}", kwargs={"home_id": home.id, **kwargs})


class TestPreview:
    def test_the_title_and_the_picture_of_the_page_are_kept(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert link.title == "Tiles"
        assert link.image is not None
        assert link.image.is_image
        assert Path(link.image.file.path).is_file()
        assert Path(link.image.thumbnail.path).is_file()
        assert sorted(site.requests) == ["/cover.jpg", "/page"]

    def test_the_title_of_the_page_is_the_fallback(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        body = b"<html><head><title>  Just   a title </title></head><body>x</body></html>"
        link = links.add_link(alice, living_room_project, url=serve_page(site, body))
        assert (link.title, link.image) == ("Just a title", None)

    def test_a_relative_picture_is_resolved_against_the_page(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        site.serve("/dir/page", 200, page(image="../cover.jpg"))
        site.serve("/cover.jpg", 200, image_bytes(), "image/jpeg")
        link = links.add_link(alice, living_room_project, url=site.url("/dir/page"))
        assert link.image is not None

    def test_the_title_typed_by_the_person_wins(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site), title="Mine")
        assert link.title == "Mine"
        assert link.image is not None

    def test_the_picture_loses_its_metadata(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        from PIL import Image

        link = links.add_link(
            alice, living_room_project, url=serve_page(site, image=image_bytes(gps=True))
        )
        assert link.image is not None
        with Image.open(link.image.file.path) as stored:
            assert not stored.getexif()
            assert b"secret" not in Path(link.image.file.path).read_bytes()

    def test_nothing_of_the_page_is_loaded_but_the_designated_picture(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        extra = (
            '<script src="/evil.js"></script><link rel="stylesheet" href="/style.css">'
            '<link rel="icon" href="/favicon.ico"><meta http-equiv="refresh" content="0;url=/r">'
        )
        body = page(extra=extra).replace(
            b"<h1>Hello</h1>", b'<img src="/pixel.png"><iframe src="/frame"></iframe>'
        )
        links.add_link(alice, living_room_project, url=serve_page(site, body))
        assert sorted(site.requests) == ["/cover.jpg", "/page"]

    def test_only_the_head_of_a_page_is_read(self) -> None:
        body = b"<html><head><title>Head</title></head><body><title>Body</title></body></html>"
        assert preview.parse(body, None, "http://example.com/").title == "Head"
        late = b'<html><body><meta property="og:title" content="Late"><title>T</title>'
        assert preview.parse(late, None, "http://example.com/").title == ""

    def test_a_page_in_another_encoding(self) -> None:
        body = "<head><title>Caf\u00e9 et th\u00e9</title>".encode("iso-8859-1")
        assert (
            preview.parse(body, "iso-8859-1", "http://example.com/").title
            == "Caf\u00e9 et th\u00e9"
        )
        assert preview.parse(body, "no-such-charset", "http://example.com/").title != ""


class TestHostilePages:
    def test_a_hostile_title_is_plain_text_of_a_bounded_length(self) -> None:
        raw = "<script>alert(1)</script>\u202e\x00\x07 " + "A" * 1000
        body = f'<head><meta property="og:title" content="{raw}">'.encode()
        title = preview.parse(body, None, "http://example.com/").title
        assert len(title) <= 200
        assert "\x00" not in title
        assert "\x07" not in title
        assert "\u202e" not in title

    def test_markup_in_a_title_is_escaped_on_the_page(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        body = page(title="&lt;script&gt;alert(1)&lt;/script&gt;<b>")
        links.add_link(alice, living_room_project, url=serve_page(site, body))
        html = signed_in.get(detail(alice_home, living_room_project)).content.decode()
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    @pytest.mark.parametrize(
        "body",
        [
            b"<head>" + b"<div>" * 50000 + b"<meta property='og:title' content='Deep'>",
            b"<head><!-- never closed <meta property='og:title' content='Hidden'>",
            b"<head><meta property=og:title content='" + b"x" * 200000,
            b"<head>" + b"<meta name=a content=b>" * 20000 + b"<title>Many</title>",
            b"\xff\xfe\x00<head><title>\xc3\x28</title>",
            b"<head><title>" + b"<" * 100000,
            b"",
        ],
    )
    def test_a_hostile_page_never_raises(self, body: bytes) -> None:
        info = preview.parse(body, "utf-8", "http://example.com/")
        assert len(info.title) <= 200

    @pytest.mark.parametrize("charset", ["idna", "undefined", "rot13", "no-such-charset", "zlib"])
    def test_a_charset_that_cannot_decode_text_never_raises(self, charset: str) -> None:
        # The charset is the remote server's word: `idna` and `undefined` raise a
        # UnicodeError even with errors="replace", `rot13` and `zlib` are no text encoding.
        body = b"<head><title>Plain</title>"
        assert preview.parse(body, charset, "http://example.com/").title == "Plain"

    @pytest.mark.parametrize("charset", ["idna", "undefined"])
    def test_a_hostile_charset_keeps_the_link_on_the_web(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
        charset: str,
    ) -> None:
        site.serve("/page", 200, page(), f"text/html; charset={charset}")
        site.serve("/cover.jpg", 200, image_bytes(), "image/jpeg")
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        response = signed_in.post(add, {"url": site.url("/page"), "title": ""})
        assert response.status_code == 302
        assert ProjectLink.objects.get().url == site.url("/page")

    @pytest.mark.parametrize("charset", ["idna", "undefined"])
    def test_a_hostile_charset_keeps_the_link_in_the_api(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
        charset: str,
    ) -> None:
        site.serve("/page", 200, page(), f"text/html; charset={charset}")
        site.serve("/cover.jpg", 200, image_bytes(), "image/jpeg")
        api_client.force_authenticate(alice)
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        sent = {"project": str(living_room_project.id), "url": site.url("/page")}
        created = api_client.post(base, sent, format="json")
        assert created.status_code == 201, created.content
        assert ProjectLink.objects.get().url == site.url("/page")

    def test_a_hostile_picture_address_is_ignored(self) -> None:
        for address in ("javascript:alert(1)", "data:image/png;base64,AAAA", "x" * 5000, "a b"):
            body = f'<head><meta property="og:image" content="{address}">'.encode()
            image = preview.parse(body, None, "http://example.com/").image_url
            assert " " not in image
            assert len(image) <= preview.MAX_IMAGE_ADDRESS


class TestGuardedPreview:
    def test_a_page_on_a_private_address_is_not_read(
        self, alice: User, living_room_project: Project, private_site: Server, enabled: None
    ) -> None:
        link = links.add_link(alice, living_room_project, url=private_site.url("/"))
        assert (link.title, link.image) == ("", None)
        assert private_site.connections == 0

    def test_a_picture_on_a_private_address_is_not_read(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        private_site: Server,
        enabled: None,
    ) -> None:
        site.serve("/page", 200, page(image=private_site.url("/secret.jpg")))
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert link.title == "Tiles"
        assert link.image is None
        assert private_site.connections == 0

    def test_a_picture_redirected_to_a_private_address_is_not_read(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        private_site: Server,
        enabled: None,
    ) -> None:
        site.serve("/page", 200, page())
        site.redirect("/cover.jpg", private_site.url("/secret.jpg"))
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert link.image is None
        assert private_site.connections == 0

    def test_a_page_redirected_to_a_private_address_is_not_read(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        private_site: Server,
        enabled: None,
    ) -> None:
        site.redirect("/page", private_site.url("/"))
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert (link.title, link.image) == ("", None)
        assert private_site.connections == 0

    @pytest.mark.parametrize(
        "image",
        [
            "file:///etc/passwd",
            "ftp://example.com/a.jpg",
            "gopher://example.com/a",
            "//example.com",
        ],
    )
    def test_a_picture_that_is_not_http_is_not_read(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        image: str,
    ) -> None:
        site.serve("/page", 200, page(image=image))
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert (link.title, link.image) == ("Tiles", None)
        assert site.requests == ["/page"]

    def test_an_svg_picture_is_refused(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site, image=SVG))
        assert link.title == "Tiles"
        assert link.image is None
        assert not ProjectFile.objects.exists()

    def test_something_that_is_not_a_picture_is_refused(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        link = links.add_link(
            alice, living_room_project, url=serve_page(site, image=b"<html>not an image</html>")
        )
        assert link.image is None

    def test_an_enormous_picture_is_not_kept(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(preview, "IMAGE_MAX_BYTES", 100)
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert (link.title, link.image) == ("Tiles", None)

    def test_a_page_that_is_not_html_gives_no_preview(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        site.serve("/page", 200, b'{"a": 1}', "application/json")
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert (link.title, link.image) == ("", None)

    def test_a_slow_page_does_not_hold_the_request_for_ever(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import time

        from tests.netservers import trickle

        monkeypatch.setattr(preview, "PREVIEW_SECONDS", 1.0)
        site.routes["/page"] = trickle
        started = time.monotonic()
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert time.monotonic() - started < 4.0
        assert link.url == site.url("/page")
        assert site.wait_idle()
        assert not [t for t in threading.enumerate() if isinstance(t, threading.Timer)]

    @pytest.mark.parametrize(
        "content_type", ["text/plain", "application/octet-stream", "image/png"]
    )
    def test_a_page_of_another_type_gives_no_preview_at_all(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        content_type: str,
    ) -> None:
        # The tags are there and the title is readable: only the type of the answer says no.
        site.serve("/page", 200, page(), content_type)
        site.serve("/cover.jpg", 200, image_bytes(), "image/jpeg")
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        assert (link.title, link.image) == ("", None)
        assert site.requests == ["/page"]

    def test_the_picture_gets_only_the_time_the_page_left(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import time

        from tests.netservers import trickle

        def slow_page(handler: object) -> tuple[int, dict[str, str], bytes]:
            time.sleep(1.2)
            return 200, {"Content-Type": "text/html"}, page()

        monkeypatch.setattr(preview, "PREVIEW_SECONDS", 3.0)
        site.routes["/page"] = slow_page
        site.routes["/cover.jpg"] = trickle
        started = time.monotonic()
        link = links.add_link(alice, living_room_project, url=site.url("/page"))
        elapsed = time.monotonic() - started
        # The ten seconds are one budget for page and picture: 1.2 s for the page, so about
        # 1.8 s for the picture. A picture given the whole budget again would end at 4.2 s.
        assert elapsed < 3.6, elapsed
        assert (link.title, link.image) == ("Tiles", None)
        assert site.wait_idle()
        assert not [t for t in threading.enumerate() if isinstance(t, threading.Timer)]


class TestFallback:
    @pytest.mark.parametrize("status", [404, 500, 403])
    def test_a_failing_page_leaves_the_address(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        status: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        site.serve("/secret-path", status, b"no")
        address = site.url("/secret-path?token=abc123")
        with caplog.at_level(logging.INFO, logger="housecairn.projects"):
            link = links.add_link(alice, living_room_project, url=address)
        assert (link.url, link.title, link.image) == (address, "", None)
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "status" in logged
        for hidden in ("secret-path", "abc123", str(site.port), LOOPBACK):
            assert hidden not in logged

    def test_a_refused_address_is_logged_by_reason_only(
        self,
        alice: User,
        living_room_project: Project,
        private_site: Server,
        enabled: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="housecairn.projects"):
            links.add_link(alice, living_room_project, url=private_site.url("/"))
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "address" in logged
        assert OTHER not in logged
        assert str(private_site.port) not in logged

    def test_an_unreachable_server_leaves_the_address(
        self, alice: User, living_room_project: Project, enabled: None
    ) -> None:
        with serving(LOOPBACK) as gone:
            address = gone.url("/page")
        link = links.add_link(alice, living_room_project, url=address)
        assert (link.url, link.title, link.image) == (address, "", None)

    def test_a_quota_that_is_full_keeps_the_link_without_its_picture(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        settings: object,
    ) -> None:
        services.add_file(alice, living_room_project, upload=upload(image_bytes()))
        settings.HOUSECAIRN_HOME_MAX_FILES = 1  # type: ignore[attr-defined]
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert (link.title, link.image) == ("Tiles", None)
        assert ProjectFile.objects.count() == 1


class TestSetting:
    def test_off_by_default_a_link_is_its_address(
        self, alice: User, living_room_project: Project, site: Server
    ) -> None:
        address = serve_page(site)
        link = links.add_link(alice, living_room_project, url=address)
        assert (link.url, link.title, link.image) == (address, "", None)
        assert site.connections == 0

    def test_the_setting_is_in_the_registry_and_off(self) -> None:
        from housecairn.instance import registry
        from housecairn.instance.config import get_setting

        setting = registry.SETTINGS["link_preview_enabled"]
        assert setting.env == "HOUSECAIRN_LINK_PREVIEW_ENABLED"
        assert setting.default is False
        assert setting.section is registry.Section.PROJECTS
        assert get_setting("link_preview_enabled") is False

    def test_the_page_says_whether_pages_are_read(
        self,
        signed_in: Client,
        alice_home: Home,
        living_room_project: Project,
        settings: object,
    ) -> None:
        shown = signed_in.get(detail(alice_home, living_room_project)).content.decode()
        assert "does not read the pages" in shown
        settings.HOUSECAIRN_LINK_PREVIEW_ENABLED = True  # type: ignore[attr-defined]
        shown = signed_in.get(detail(alice_home, living_room_project)).content.decode()
        assert "reads the page once" in shown


class TestValidation:
    @pytest.mark.parametrize(
        "address",
        [
            "",
            "   ",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "ftp://example.com/",
            "data:text/html,x",
            "https://",
            "https://user:pass@example.com/",
            "https://exa mple.com/",
            "https://example.com/\nx",
            "https://example.com/" + "a" * 500,
        ],
    )
    def test_only_a_web_address(
        self, alice: User, living_room_project: Project, address: str
    ) -> None:
        with pytest.raises(ValidationError):
            links.add_link(alice, living_room_project, url=address)
        assert not ProjectLink.objects.exists()

    def test_at_most_thirty_links(self, alice: User, living_room_project: Project) -> None:
        for number in range(MAX_LINKS_PER_PROJECT):
            links.add_link(alice, living_room_project, url=f"https://example.com/{number}")
        with pytest.raises(ValidationError):
            links.add_link(alice, living_room_project, url="https://example.com/one-more")


class TestRolesAndIsolation:
    def test_a_reader_reads_the_links_and_adds_none(
        self,
        client: Client,
        reader: User,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
    ) -> None:
        link = links.add_link(alice, living_room_project, url="https://example.com/idea")
        with pytest.raises(PermissionDenied):
            links.add_link(reader, living_room_project, url="https://example.com/no")
        with pytest.raises(PermissionDenied):
            links.delete_link(reader, link)
        client.force_login(reader)
        shown = client.get(detail(alice_home, living_room_project)).content.decode()
        assert "https://example.com/idea" in shown
        assert "Add the link" not in shown
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        assert client.post(add, {"url": "https://example.com/no"}).status_code == 403
        delete = link_url("link-delete", alice_home, link_id=link.id)
        assert client.post(delete).status_code == 403
        assert ProjectLink.objects.count() == 1

    def test_a_member_adds_and_deletes(
        self, member: User, alice_home: Home, living_room_project: Project
    ) -> None:
        link = links.add_link(member, living_room_project, url="https://example.com/m")
        links.delete_link(member, link)
        assert not ProjectLink.objects.exists()

    def test_another_home_sees_nothing_and_changes_nothing(
        self,
        bob: User,
        client: Client,
        alice: User,
        alice_home: Home,
        bob_home: Home,
        living_room_project: Project,
        foreign_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        links.add_link(alice, living_room_project, url="https://unique-shop.test/idea")
        client.force_login(bob)
        assert client.get(detail(alice_home, living_room_project)).status_code == 404
        # Bob's own home, Alice's identifiers.
        add = link_url("link-add", bob_home, project_id=living_room_project.id)
        assert client.post(add, {"url": "https://example.com/x"}).status_code == 404
        delete = link_url("link-delete", bob_home, link_id=link.id)
        assert client.post(delete).status_code == 404
        assert client.get(delete).status_code == 404
        assert link.image is not None
        picture = link_url("file-thumbnail", bob_home, file_id=link.image.id)
        assert client.get(picture).status_code == 404
        shown = client.get(detail(bob_home, foreign_project)).content.decode()
        assert "unique-shop.test" not in shown
        assert "Tiles" not in shown
        assert ProjectLink.objects.filter(id=link.id).exists()


class TestScreens:
    def test_add_show_and_delete(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        address = serve_page(site)
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        response = signed_in.post(add, {"url": address, "title": ""}, follow=True)
        shown = response.content.decode()
        assert "Link added." in shown
        link = ProjectLink.objects.get()
        assert link.image is not None
        assert "Tiles" in shown
        thumbnail = link_url("file-thumbnail", alice_home, file_id=link.image.id)
        assert thumbnail in shown
        # The page never points to the remote picture, nor loads anything from the other site.
        assert site.url("/cover.jpg") not in shown
        assert 'src="http' not in shown
        picture = signed_in.get(thumbnail)
        assert picture.status_code == 200
        assert picture["Content-Type"] == "image/jpeg"
        assert picture["X-Content-Type-Options"] == "nosniff"
        path = Path(link.image.file.path)
        assert path.is_file()
        confirm = link_url("link-delete", alice_home, link_id=link.id)
        assert signed_in.get(confirm).status_code == 200
        from django.test import TestCase

        with TestCase.captureOnCommitCallbacks(execute=True):
            assert signed_in.post(confirm, follow=True).status_code == 200
        assert not ProjectLink.objects.exists()
        assert not path.exists()
        assert signed_in.get(thumbnail).status_code == 404

    def test_a_bad_address_is_said_and_nothing_is_added(
        self, signed_in: Client, alice_home: Home, living_room_project: Project
    ) -> None:
        add = link_url("link-add", alice_home, project_id=living_room_project.id)
        shown = signed_in.post(add, {"url": "javascript:alert(1)"}, follow=True).content.decode()
        assert "Give the address of a web page" in shown
        assert not ProjectLink.objects.exists()

    def test_the_picture_of_a_link_is_not_a_photo(
        self,
        signed_in: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert link.image is not None
        shown = signed_in.get(detail(alice_home, living_room_project)).content.decode()
        assert "No photo yet." in shown
        assert not services.photos_of(alice_home).exists()
        delete = link_url("file-delete", alice_home, file_id=link.image.id)
        assert signed_in.post(delete).status_code == 404
        assert ProjectLink.objects.get().image_id == link.image.id

    def test_the_picture_does_not_count_as_a_photo_of_the_project(
        self,
        alice: User,
        living_room_project: Project,
        site: Server,
        enabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from housecairn.projects import services as project_services

        monkeypatch.setattr(project_services, "MAX_PHOTOS_PER_PROJECT", 1)
        links.add_link(alice, living_room_project, url=serve_page(site))
        services.add_file(alice, living_room_project, upload=upload(image_bytes()))

    def test_deleting_the_project_erases_the_pictures(
        self, alice: User, living_room_project: Project, site: Server, enabled: None
    ) -> None:
        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert link.image is not None
        path = Path(link.image.file.path)
        thumbnail = Path(link.image.thumbnail.path)
        from django.test import TestCase

        with TestCase.captureOnCommitCallbacks(execute=True):
            services.delete_project(alice, living_room_project)
        assert not ProjectLink.objects.exists()
        assert not path.exists()
        assert not thumbnail.exists()
        assert ProjectLink.all_objects.get().deleted_at is not None


class TestAudit:
    def test_only_the_domain_is_written(
        self, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        link = links.add_link(
            alice,
            living_room_project,
            url="https://Shop.Example.com:8443/bathroom/tiles?secret=1234#frag",
            title="Very private title",
        )
        links.delete_link(alice, link)
        events = list(
            AuditEvent.objects.filter(action__startswith="project_link").order_by(
                "created_at", "id"
            )
        )
        assert [e.action for e in events] == ["project_link.added", "project_link.deleted"]
        for event in events:
            assert event.detail == {"title": "Paint the living room", "domain": "shop.example.com"}
        raw = repr([e.detail for e in AuditEvent.objects.filter(home_id=alice_home.id)])
        for hidden in ("secret=1234", "tiles", "frag", "Very private", "8443"):
            assert hidden not in raw


class TestApi:
    def test_create_read_and_delete(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        api_client.force_authenticate(alice)
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        created = api_client.post(
            base, {"project": str(living_room_project.id), "url": serve_page(site)}, format="json"
        )
        assert created.status_code == 201, created.content
        data = created.json()
        assert data["title"] == "Tiles"
        assert data["image_url"]
        assert data["thumbnail_url"]
        assert "cover.jpg" not in data["image_url"]
        assert api_client.get(data["thumbnail_url"]).status_code == 200
        content = api_client.get(data["image_url"])
        assert content.status_code == 200
        assert content["X-Content-Type-Options"] == "nosniff"
        listed = api_client.get(base, {"project": str(living_room_project.id)}).json()["results"]
        assert [row["id"] for row in listed] == [data["id"]]
        # The picture of a link is not a photo of the project.
        files = reverse("api-v1:home-project-file-list", kwargs={"home_id": alice_home.id})
        assert api_client.get(files).json()["results"] == []
        picture = data["image_url"].split("/api/v1", 1)[1].removesuffix("content/")
        assert api_client.delete("/api/v1" + picture).status_code == 404
        detail_url = reverse(
            "api-v1:home-project-link-detail",
            kwargs={"home_id": alice_home.id, "link_id": data["id"]},
        )
        assert api_client.delete(detail_url).status_code == 204
        assert api_client.get(detail_url).status_code == 404
        assert not ProjectFile.objects.exists()

    def test_a_bad_address_is_a_400(
        self, api_client: APIClient, alice: User, alice_home: Home, living_room_project: Project
    ) -> None:
        api_client.force_authenticate(alice)
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "https://u:p@example.com/"):
            sent = {"project": str(living_room_project.id), "url": bad}
            assert api_client.post(base, sent, format="json").status_code == 400, bad
        assert not ProjectLink.objects.exists()

    def test_a_reader_cannot_add_and_another_home_sees_nothing(
        self,
        api_client: APIClient,
        reader: User,
        bob: User,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
    ) -> None:
        link = links.add_link(alice, living_room_project, url="https://example.com/a")
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        api_client.force_authenticate(reader)
        assert api_client.get(base).json()["results"][0]["id"] == str(link.id)
        sent = {"project": str(living_room_project.id), "url": "https://example.com/b"}
        assert api_client.post(base, sent, format="json").status_code == 403
        detail_url = reverse(
            "api-v1:home-project-link-detail", kwargs={"home_id": alice_home.id, "link_id": link.id}
        )
        assert api_client.delete(detail_url).status_code == 403
        api_client.force_authenticate(bob)
        assert api_client.get(base).status_code == 404
        assert api_client.delete(detail_url).status_code == 404
        assert ProjectLink.objects.count() == 1

    def test_the_preview_is_off_unless_the_instance_allows_it(
        self,
        api_client: APIClient,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
    ) -> None:
        api_client.force_authenticate(alice)
        base = reverse("api-v1:home-project-link-list", kwargs={"home_id": alice_home.id})
        sent = {"project": str(living_room_project.id), "url": serve_page(site)}
        data = api_client.post(base, sent, format="json").json()
        assert (data["title"], data["image_url"], data["thumbnail_url"]) == ("", None, None)
        assert site.connections == 0


class TestDataOfTheHome:
    def test_the_export_has_the_links_and_their_pictures(
        self,
        client: Client,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        import io
        import json
        import zipfile

        link = links.add_link(alice, living_room_project, url=serve_page(site))
        links.add_link(alice, living_room_project, url="https://example.com/plain")
        client.force_login(alice)
        response = client.post(reverse("homes:export", kwargs={"home_id": alice_home.id}))
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        data = json.loads(archive.read("export.json"))
        rows = {row["id"]: row for row in data["project_links"]}
        assert len(rows) == 2
        assert rows[str(link.id)]["title"] == "Tiles"
        assert rows[str(link.id)]["image"] == str(link.image_id)
        listed = {f["id"]: f for f in data["project_files"]}
        assert listed[str(link.image_id)]["file"] in archive.namelist()

    def test_erasing_the_home_erases_the_pictures_and_the_rows(
        self,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
        media_root: Path,
    ) -> None:
        from django.test import TestCase

        from housecairn.homes import services as home_services

        link = links.add_link(alice, living_room_project, url=serve_page(site))
        assert link.image is not None
        assert Path(link.image.file.path).is_file()
        with TestCase.captureOnCommitCallbacks(execute=True):
            home_services.delete_home(alice, alice_home, confirmation="Main house")
        assert not ProjectLink.all_objects.exists()
        assert not (media_root / "projects" / str(alice_home.id)).exists()

    def test_erasing_the_account_erases_the_links(
        self,
        alice: User,
        alice_home: Home,
        living_room_project: Project,
        site: Server,
        enabled: None,
    ) -> None:
        from django.test import TestCase

        from housecairn.accounts import services as account_services

        links.add_link(alice, living_room_project, url=serve_page(site))
        with TestCase.captureOnCommitCallbacks(execute=True):
            account_services.delete_account(alice)
        assert not ProjectLink.all_objects.exists()
        assert not ProjectFile.all_objects.exists()


@pytest.mark.django_db(transaction=True)
def test_the_migration_of_links_is_reversible() -> None:
    assert "projects_projectlink" in connection.introspection.table_names()
    call_command("migrate", "projects", "0001", verbosity=0)
    assert "projects_projectlink" not in connection.introspection.table_names()
    assert "projects_project" in connection.introspection.table_names()
    call_command("migrate", "projects", verbosity=0)
    assert "projects_projectlink" in connection.introspection.table_names()
