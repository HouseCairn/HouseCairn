"""The contact file of a contractor: valid vCard 3.0, escaped, folded, injection-proof."""

import re
import uuid

import pytest

from housecairn.accounts.models import User
from housecairn.homes.models import Home
from housecairn.tasks import services, vcard

pytest_plugins = ("tests.tasks_fixtures", "tests.rooms_fixtures")
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_root", "frozen_today")]

HOSTILE = "line one\r\nBEGIN:VCARD\r\nFN:Hacker\nEND:VCARD\r;TEL:1,2;3\\n"
KNOWN = ("BEGIN", "VERSION", "PRODID", "UID", "FN", "N", "TITLE", "TEL", "EMAIL", "ADR")
KNOWN += ("NOTE", "REV", "END")


def unfold(text: str) -> list[str]:
    assert text.endswith("\r\n")
    assert "\n" not in text.replace("\r\n", "")  # every break is a CRLF
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def card(home: Home, user: User, **fields: object) -> str:
    contractor = services.create_contractor(user, home, **{"name": "Pipes Ltd", **fields})
    return vcard.render(contractor)


class TestFormat:
    def test_a_complete_card(self, alice: User, alice_home: Home) -> None:
        text = card(
            alice_home,
            alice,
            name="Pipes Ltd",
            trade="plumber",
            phone="+33 1 23 45 67 89",
            email="contact@example.com",
            address="1 Main Street\n12345 Springfield",
            note="Call after 5pm",
        )
        lines = unfold(text)
        assert lines[:2] == ["BEGIN:VCARD", "VERSION:3.0"]
        assert lines[-1] == "END:VCARD"
        assert "FN:Pipes Ltd" in lines
        assert "N:Pipes Ltd;;;;" in lines
        assert "TITLE:Plumber" in lines
        assert "TEL;TYPE=WORK,VOICE:+33 1 23 45 67 89" in lines
        assert "EMAIL;TYPE=INTERNET:contact@example.com" in lines
        assert "ADR;TYPE=WORK:;;1 Main Street\\n12345 Springfield;;;;" in lines
        assert "NOTE:Call after 5pm" in lines
        assert any(re.fullmatch(r"REV:\d{8}T\d{6}Z", line) for line in lines)
        assert any(re.fullmatch(r"UID:urn:uuid:[0-9a-f-]{36}", line) for line in lines)

    def test_a_card_with_only_a_name(self, alice: User, alice_home: Home) -> None:
        lines = unfold(card(alice_home, alice))
        assert not [line for line in lines if line.startswith(("TEL", "EMAIL", "ADR", "NOTE"))]

    def test_other_shows_the_text_kept_with_it(self, alice: User, alice_home: Home) -> None:
        lines = unfold(card(alice_home, alice, trade="other", trade_other="Pool maintenance"))
        assert "TITLE:Pool maintenance" in lines


class TestEscaping:
    def test_separators_and_backslashes_are_escaped(self) -> None:
        assert vcard.escape("a;b,c\\d") == "a\\;b\\,c\\\\d"

    def test_line_breaks_are_written_as_n(self) -> None:
        assert vcard.escape("a\r\nb\rc\nd", multiline=True) == "a\\nb\\nc\\nd"

    def test_single_line_values_lose_line_breaks_and_control_characters(self) -> None:
        assert vcard.escape("a\r\nb\x00c\x1b\u202e") == "abc"

    def test_no_value_can_start_a_card_or_a_property(self, alice: User, alice_home: Home) -> None:
        contractor = services.create_contractor(alice, alice_home, name="Safe")
        contractor.name = HOSTILE
        contractor.note = HOSTILE
        contractor.address = HOSTILE
        contractor.trade = "other"
        contractor.trade_other = HOSTILE
        lines = unfold(vcard.render(contractor))
        assert lines.count("BEGIN:VCARD") == 1
        assert lines.count("END:VCARD") == 1
        assert not [line for line in lines if line.startswith(("FN:Hacker", "TEL:1"))]
        assert all(re.split(r"[:;]", line, maxsplit=1)[0] in KNOWN for line in lines), lines
        # The hostile text is all there, as text.
        note = next(line for line in lines if line.startswith("NOTE:"))
        assert "BEGIN:VCARD" in note
        assert "\\n" in note
        assert "\\;TEL:1\\,2\\;3" in note

    def test_a_note_cannot_close_the_card_early(self, alice: User, alice_home: Home) -> None:
        lines = unfold(card(alice_home, alice, note="x\nEND:VCARD\nBEGIN:VCARD\nFN:Other"))
        assert lines.count("END:VCARD") == 1
        assert lines.count("BEGIN:VCARD") == 1
        assert lines.count("FN:Other") == 0


class TestFolding:
    def test_long_lines_are_folded_at_75_octets_on_character_boundaries(
        self, alice: User, alice_home: Home
    ) -> None:
        text = card(alice_home, alice, note="é" * 200)
        for physical in text.split("\r\n")[:-1]:
            assert len(physical.encode()) <= 75
        note = next(line for line in unfold(text) if line.startswith("NOTE:"))
        assert note == "NOTE:" + "é" * 200

    def test_a_short_line_is_left_alone(self) -> None:
        assert vcard.fold("FN:Pipes") == "FN:Pipes"


class TestFilename:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Pipes Ltd", "pipes-ltd.vcf"),
            ("Électricité Dupont", "electricite-dupont.vcf"),
            ("../../etc/passwd", "etcpasswd.vcf"),
            ('a"b\r\nSet-Cookie: x', "ab-set-cookie-x.vcf"),
            ("日本", "contact.vcf"),
            ("", "contact.vcf"),
        ],
    )
    def test_the_name_is_safe(self, name: str, expected: str) -> None:
        contractor = type("C", (), {"name": name, "id": uuid.uuid4()})()
        assert vcard.filename(contractor) == expected  # type: ignore[arg-type]

    def test_it_is_not_too_long(self) -> None:
        contractor = type("C", (), {"name": "x" * 500})()
        assert len(vcard.filename(contractor)) <= 54  # type: ignore[arg-type]
