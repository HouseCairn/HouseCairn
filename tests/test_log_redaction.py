"""The secret of a calendar feed stays out of the logs (docs/adr/0052)."""

import datetime
import io
import logging
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from gunicorn.config import Config

from housecairn import entrypoint
from housecairn.calendar import feeds
from housecairn.core import log_redaction
from housecairn.core.gunicorn_logging import Logger

SECRET = "s3cr3t_Tok-en0123456789abcdefghijklmnopqrstu"


class TestRedact:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (f"GET /calendar/feed/{SECRET}.ics HTTP/1.1", "GET /calendar/feed/***.ics HTTP/1.1"),
            (f"Not Found: /calendar/feed/{SECRET}.ics", "Not Found: /calendar/feed/***.ics"),
            (f"/calendar/feed/{SECRET}.ics?x=1", "/calendar/feed/***.ics?x=1"),
            (
                f"https://h.example.com/calendar/feed/{SECRET}.ics",
                "https://h.example.com/calendar/feed/***.ics",
            ),
            (f"/CALENDAR/FEED/{SECRET}.ICS", "/CALENDAR/FEED/***.ICS"),
            (f"%2Fcalendar%2Ffeed%2F{SECRET}%2Eics", "%2Fcalendar%2Ffeed%2F***%2Eics"),
            (
                f"a /calendar/feed/{SECRET}.ics and /calendar/feed/{SECRET[::-1]}.ics",
                "a /calendar/feed/***.ics and /calendar/feed/***.ics",
            ),
            ("GET /calendar/week/ HTTP/1.1", "GET /calendar/week/ HTTP/1.1"),
            ("/calendar/feeds/", "/calendar/feeds/"),
        ],
    )
    def test_the_secret_segment_is_masked_and_nothing_else(self, text: str, expected: str) -> None:
        assert log_redaction.redact(text) == expected

    def test_masking_twice_changes_nothing(self) -> None:
        once = log_redaction.redact(f"/calendar/feed/{SECRET}.ics")
        assert log_redaction.redact(once) == once

    def test_the_route_is_the_one_the_pattern_masks(self) -> None:
        # If the route moves, this fails and the pattern has to follow.
        path = reverse("calendar:feed", kwargs={"token": SECRET})
        assert log_redaction.redact(path) == path.replace(SECRET, "***")


class TestDjangoRequestLog:
    @staticmethod
    def captured(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
        """The real console handler of the settings, writing to a buffer."""
        (handler,) = [h for h in logging.getLogger().handlers if h.get_name() == "console"]
        assert isinstance(handler, logging.StreamHandler)
        stream = io.StringIO()
        monkeypatch.setattr(handler, "stream", stream)
        return stream

    @pytest.mark.django_db
    def test_a_4xx_on_a_feed_address_is_logged_without_the_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stream = self.captured(monkeypatch)
        cache.clear()
        client = Client()
        for _ in range(70):  # 404 for an unknown secret, then 429 past the limit
            client.get(reverse("calendar:feed", kwargs={"token": SECRET}))
        written = stream.getvalue()
        assert "/calendar/feed/***.ics" in written
        assert "Not Found" in written
        assert "Too Many Requests" in written
        assert SECRET not in written

    @pytest.mark.django_db
    def test_a_valid_secret_that_is_limited_is_not_written_either(
        self, monkeypatch: pytest.MonkeyPatch, alice: Any, alice_home: Any
    ) -> None:
        _feed, raw = feeds.create_feed(alice, alice_home)
        stream = self.captured(monkeypatch)
        cache.clear()
        client = Client()
        codes = [
            client.get(reverse("calendar:feed", kwargs={"token": raw})).status_code
            for _ in range(70)
        ]
        assert 429 in codes
        assert raw not in stream.getvalue()
        assert "/calendar/feed/***.ics" in stream.getvalue()

    def test_the_filter_leaves_other_records_alone(self) -> None:
        record = logging.LogRecord("x", logging.WARNING, "f", 1, "Not Found: %s", ("/a/b",), None)
        assert log_redaction.RedactFeedAddresses().filter(record)
        assert record.getMessage() == "Not Found: /a/b"
        assert record.args == ("/a/b",)


class _Resp:
    status = "200 OK"
    headers: list[tuple[str, str]] = []
    sent = 12


class _Req:
    headers = [("REFERER", f"https://h.example.com/calendar/feed/{SECRET}.ics")]


class TestGunicornAccessLog:
    @staticmethod
    def line(capsys: pytest.CaptureFixture[str], **config: str) -> str:
        cfg = Config()
        cfg.set("accesslog", "-")
        for name, value in config.items():
            cfg.set(name, value)
        logger = Logger(cfg)
        environ = {
            "REMOTE_ADDR": "192.0.2.7",
            "REQUEST_METHOD": "GET",
            "RAW_URI": f"/calendar/feed/{SECRET}.ics?x=1",
            "PATH_INFO": f"/calendar/feed/{SECRET}.ics",
            "QUERY_STRING": "x=1",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_REFERER": f"https://h.example.com/calendar/feed/{SECRET}.ics",
        }
        logger.access(_Resp(), _Req(), environ, datetime.timedelta(milliseconds=5))
        return capsys.readouterr().out

    def test_the_default_access_line_has_no_secret(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = self.line(capsys)
        assert 'GET /calendar/feed/***.ics?x=1 HTTP/1.1" 200' in out
        assert SECRET not in out

    def test_a_custom_format_is_covered_too(self, capsys: pytest.CaptureFixture[str]) -> None:
        out = self.line(
            capsys,
            access_log_format="%(U)s %(r)s %(f)s %({referer}i)s %({raw_uri}e)s %({path_info}e)s",
        )
        assert SECRET not in out
        assert out.count("/calendar/feed/***.ics") == 6

    def test_the_web_server_uses_that_logger(self) -> None:
        assert "--logger-class=housecairn.core.gunicorn_logging.Logger" in entrypoint.web_command()
