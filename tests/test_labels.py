"""QR labels: opaque codes, opening, printing, roles, isolation (docs/adr/0047)."""

import base64
import re
import uuid
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.audit.models import AuditEvent
from housecairn.homes import services as home_services
from housecairn.homes.models import Home
from housecairn.labels import printing, qr, services
from housecairn.labels.models import CODE_LENGTH, Label, LabelKind, is_code_shaped, new_code
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Room
from housecairn.stock.models import Article

pytest_plugins = ("tests.rooms_fixtures", "tests.stock_fixtures")
pytestmark = pytest.mark.django_db

URI_MARK = re.compile(rb"/S /URI")
PAGE_MARK = re.compile(rb"/Type /Page\b(?!s)")


def make(actor: User, home: Home, target: Room | Item | Article) -> Label:
    kind = {Room: "room", Item: "item", Article: "article"}[type(target)]
    label, _created = services.create_label(actor, home, kind=kind, target_id=target.id)
    return label


def open_code(client: Client, code: str) -> HttpResponse:
    return client.get(reverse("label-open", kwargs={"code": code}))


def labels_in(pdf: bytes) -> int:
    """How many QR labels a PDF holds: each one carries a link to the address its code opens."""
    return len(URI_MARK.findall(pdf))


class TestCodes:
    def test_a_code_is_128_random_bits_in_22_characters(self) -> None:
        code = new_code()
        assert len(code) == CODE_LENGTH == 22
        assert len(base64.urlsafe_b64decode(code + "==")) == 16
        assert is_code_shaped(code)

    def test_codes_do_not_repeat(self) -> None:
        assert len({new_code() for _ in range(2000)}) == 2000

    @pytest.mark.parametrize("value", ["", "a" * 21, "a" * 23, "a" * 21 + "/", "é" * 22, "a b" * 8])
    def test_anything_else_is_not_code_shaped(self, value: str) -> None:
        assert not is_code_shaped(value)

    def test_a_code_names_nothing_of_what_it_opens(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        label = make(alice, alice_home, owner_item)
        for secret in (str(owner_item.id), str(alice_home.id), owner_item.name, alice_home.name):
            assert secret.lower() not in label.code.lower()
        assert str(owner_item.id).replace("-", "") not in label.code

    def test_the_address_holds_the_code_and_nothing_else(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        label = make(alice, alice_home, owner_item)
        assert services.address("https://home.example.com/", label) == (
            f"https://home.example.com/l/{label.code}/"
        )


class TestMaking:
    def test_each_kind_of_object_has_a_label(
        self, alice: User, alice_home: Home, owner_room: Room, owner_item: Item, article: Article
    ) -> None:
        labels = [make(alice, alice_home, t) for t in (owner_room, owner_item, article)]
        assert [label.kind for label in labels] == ["room", "item", "article"]
        assert [label.target_id for label in labels] == [owner_room.id, owner_item.id, article.id]
        assert (labels[0].name, labels[0].place) == ("Living room", "")
        assert (labels[1].name, labels[1].place) == ("Boiler", "Living room")
        assert (labels[2].name, labels[2].place) == ("Boiler filter", "Garage")

    def test_making_it_again_returns_the_active_one(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        first, created = services.create_label(
            alice, alice_home, kind="item", target_id=owner_item.id
        )
        again, created_again = services.create_label(
            alice, alice_home, kind="item", target_id=owner_item.id
        )
        assert (created, created_again, again.id) == (True, False, first.id)
        assert Label.objects.count() == 1

    def test_a_reader_makes_none(self, alice_home: Home, reader: User, owner_item: Item) -> None:
        with pytest.raises(PermissionDenied):
            services.create_label(reader, alice_home, kind="item", target_id=owner_item.id)
        assert Label.objects.count() == 0

    def test_a_member_of_another_home_makes_none(
        self, alice_home: Home, bob: User, owner_item: Item
    ) -> None:
        with pytest.raises(PermissionDenied):
            services.create_label(bob, alice_home, kind="item", target_id=owner_item.id)

    def test_an_object_of_another_home_or_a_bad_kind_is_refused(
        self,
        alice: User,
        alice_home: Home,
        foreign_item: Item,
        foreign_article: Article,
        owner_item: Item,
    ) -> None:
        for kind, target in (
            ("item", foreign_item.id),
            ("article", foreign_article.id),
            ("room", foreign_item.room_id),
            ("item", uuid.uuid4()),
            ("article", owner_item.id),  # right home, wrong kind
            ("widget", owner_item.id),
        ):
            with pytest.raises(ValidationError):
                services.create_label(alice, alice_home, kind=kind, target_id=target)
        assert Label.objects.count() == 0

    def test_a_deleted_object_cannot_be_labelled(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        room_services.delete_item(alice, owner_item)
        with pytest.raises(ValidationError):
            services.create_label(alice, alice_home, kind="item", target_id=owner_item.id)

    def test_the_database_allows_one_active_label_per_object(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        from django.db import IntegrityError, transaction

        make(alice, alice_home, owner_item)
        with pytest.raises(IntegrityError), transaction.atomic():
            Label.objects.create(home=alice_home, kind="item", item=owner_item)

    def test_a_label_has_exactly_one_target_of_its_kind(
        self, alice_home: Home, owner_item: Item, owner_room: Room
    ) -> None:
        from django.db import IntegrityError, transaction

        for fields in (
            {"kind": "item", "room": owner_room},
            {"kind": "room", "room": owner_room, "item": owner_item},
            {"kind": "item"},
        ):
            with pytest.raises(IntegrityError), transaction.atomic():
                Label.objects.create(home=alice_home, **fields)


class TestRevoking:
    def test_revoking_keeps_the_row_and_stops_the_sticker(
        self, alice: User, alice_home: Home, owner_item: Item, client: Client
    ) -> None:
        label = make(alice, alice_home, owner_item)
        services.revoke_label(alice, label)
        label.refresh_from_db()
        assert label.revoked_at is not None
        assert services.labels_of(alice_home).count() == 0
        client.force_login(alice)
        assert open_code(client, label.code).status_code == 404
        # The object can have a new label; the old code is never reused.
        fresh, created = services.create_label(
            alice, alice_home, kind="item", target_id=owner_item.id
        )
        assert created
        assert fresh.code != label.code

    def test_regenerating_replaces_the_code(
        self, alice: User, alice_home: Home, owner_item: Item, client: Client
    ) -> None:
        old = make(alice, alice_home, owner_item)
        new = services.regenerate_label(alice, old)
        assert new.code != old.code
        assert new.target_id == owner_item.id
        client.force_login(alice)
        assert open_code(client, old.code).status_code == 404
        assert open_code(client, new.code).status_code == 302
        assert Label.objects.filter(revoked_at__isnull=True).count() == 1

    def test_a_reader_cannot_revoke_or_regenerate(
        self, alice: User, alice_home: Home, reader: User, owner_item: Item
    ) -> None:
        label = make(alice, alice_home, owner_item)
        with pytest.raises(PermissionDenied):
            services.revoke_label(reader, label)
        with pytest.raises(PermissionDenied):
            services.regenerate_label(reader, label)
        label.refresh_from_db()
        assert label.revoked_at is None

    def test_revoking_is_recorded_with_the_name_only(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        label = make(alice, alice_home, owner_item)
        services.revoke_label(alice, label)
        services.regenerate_label(alice, make(alice, alice_home, owner_item))
        events = AuditEvent.objects.filter(action__startswith="label.").order_by("created_at")
        assert [(e.action, e.detail) for e in events] == [
            ("label.revoked", {"title": "Boiler"}),
            ("label.regenerated", {"title": "Boiler"}),
        ]
        assert label.code not in str([e.detail for e in events])


class TestOpening:
    def test_signed_out_goes_to_sign_in_and_back(self, client: Client) -> None:
        code = new_code()
        response = open_code(client, code)
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("account_login"))
        assert f"next=/l/{code}/" in response["Location"]

    def test_a_member_goes_to_the_page_of_the_object(
        self,
        alice: User,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        article: Article,
        client: Client,
    ) -> None:
        client.force_login(alice)
        expected = {
            owner_room: reverse(
                "rooms:detail", kwargs={"home_id": alice_home.id, "room_id": owner_room.id}
            ),
            owner_item: reverse(
                "rooms:item-detail", kwargs={"home_id": alice_home.id, "item_id": owner_item.id}
            ),
            article: reverse(
                "stock:detail", kwargs={"home_id": alice_home.id, "article_id": article.id}
            ),
        }
        for target, address in expected.items():
            response = open_code(client, make(alice, alice_home, target).code)
            assert (response.status_code, response["Location"]) == (302, address)

    def test_a_reader_scans_too(
        self, alice: User, alice_home: Home, reader: User, owner_item: Item, client: Client
    ) -> None:
        label = make(alice, alice_home, owner_item)
        client.force_login(reader)
        assert open_code(client, label.code).status_code == 302

    def test_every_reason_for_nothing_gives_the_same_answer(
        self,
        alice: User,
        alice_home: Home,
        bob: User,
        owner_item: Item,
        owner_room: Room,
        client: Client,
    ) -> None:
        """Unknown, revoked, deleted and foreign codes cannot be told apart by their answer."""
        revoked = make(alice, alice_home, owner_item)
        services.revoke_label(alice, revoked)
        deleted_room = room_services.create_room(alice, alice_home, name="Gone")
        deleted = make(alice, alice_home, deleted_room)
        room_services.delete_room(alice, deleted_room)
        foreign = make(alice, alice_home, owner_room)
        client.force_login(bob)  # a member of another home
        codes = [
            new_code(),  # never issued
            revoked.code,
            deleted.code,
            foreign.code,  # alive, but not bob's home
            "short",
            "..%2F..",
            "a" * 22,
            "é" * 22,
        ]
        answers = []
        for code in codes:
            response = open_code(client, code)
            # The anti-forgery token of the page is the only thing that varies.
            page = re.sub(rb"X-CSRFToken[^}]*", b"", response.content)
            answers.append((response.status_code, page, dict(response.headers)))
        assert {a[0] for a in answers} == {404}
        assert len({a[1] for a in answers}) == 1
        assert len({tuple(sorted(a[2].items())) for a in answers}) == 1
        # The same person, a member of the home, still gets the page for the live one.
        client.force_login(alice)
        assert open_code(client, foreign.code).status_code == 302
        for dead in (revoked.code, deleted.code):
            assert open_code(client, dead).status_code == 404

    def test_an_instance_administrator_who_is_not_a_member_gets_nothing(
        self, alice: User, alice_home: Home, site_admin: User, owner_item: Item, client: Client
    ) -> None:
        label = make(alice, alice_home, owner_item)
        client.force_login(site_admin)
        assert open_code(client, label.code).status_code == 404

    def test_a_member_of_a_locked_home_is_told_which_sign_in_it_needs(
        self,
        alice: User,
        alice_home: Home,
        owner_item: Item,
        client: Client,
        settings: Any,
    ) -> None:
        settings.SOCIALACCOUNT_PROVIDERS = {
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
        label = make(alice, alice_home, owner_item)
        alice_home.required_provider = "company"
        alice_home.save()
        client.force_login(alice)
        response = open_code(client, label.code)
        assert response.status_code == 403
        assert b"Company SSO" in response.content


class TestMatrixAndSvg:
    def test_the_matrix_is_square_with_the_three_finder_patterns(self) -> None:
        rows = qr.matrix("https://home.example.com/l/" + "a" * 22 + "/")
        size = len(rows)
        assert size >= 21
        assert size % 4 == 1
        assert all(len(r) == size for r in rows)
        finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            seen = [
                "".join("1" if rows[top + r][left + c] else "0" for c in range(7)) for r in range(7)
            ]
            assert seen == finder

    def test_the_same_text_gives_the_same_code(self) -> None:
        assert qr.matrix("x" * 40) == qr.matrix("x" * 40)
        assert qr.matrix("x" * 40) != qr.matrix("y" * 40)

    def test_the_svg_is_inline_and_loads_nothing(self) -> None:
        svg = qr.svg("https://home.example.com/l/abc/", title='a "quoted" <name>')
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        for forbidden in ("http", "href", "src=", "<script", "<image", "style="):
            assert forbidden not in svg.replace("https://home.example.com/l/abc/", "")
        assert "&quot;quoted&quot;" in svg
        assert "&lt;name&gt;" in svg


class TestPrinting:
    def sample(self, alice: User, alice_home: Home, count: int) -> list[Label]:
        room = room_services.create_room(alice, alice_home, name="Hall")
        return [
            make(alice, alice_home, room_services.create_item(alice, room, name=f"Lamp {i}"))
            for i in range(count)
        ]

    def test_the_sheet_holds_one_qr_per_label_and_24_to_a_page(
        self, alice: User, alice_home: Home
    ) -> None:
        labels = self.sample(alice, alice_home, 25)
        pdf = services.render_pdf("https://home.example.com", labels, "a4-3x8")
        assert pdf.startswith(b"%PDF-")
        assert labels_in(pdf) == 25
        assert len(PAGE_MARK.findall(pdf)) == 2
        for label in labels:
            assert f"https://home.example.com/l/{label.code}/".encode() in pdf

    def test_the_roll_has_one_label_per_page_of_62_mm(self, alice: User, alice_home: Home) -> None:
        labels = self.sample(alice, alice_home, 3)
        pdf = services.render_pdf("https://home.example.com", labels, "roll-62")
        assert labels_in(pdf) == 3
        assert len(PAGE_MARK.findall(pdf)) == 3
        box = re.search(rb"/MediaBox \[ 0 0 ([0-9.]+) ([0-9.]+) \]", pdf)
        assert box is not None
        assert round(float(box.group(1)) / 72 * 25.4) == 62  # points to millimetres

    def test_a_label_carries_its_name_and_where_it_is(self, alice: User, alice_home: Home) -> None:
        from reportlab.pdfgen.canvas import Canvas

        drawn: list[str] = []
        original = Canvas.drawString

        def spy(self: Canvas, x: float, y: float, text: str, *args: Any, **kwargs: Any) -> None:
            drawn.append(text)
            original(self, x, y, text, *args, **kwargs)

        room = room_services.create_room(alice, alice_home, name="Cellar")
        item = room_services.create_item(alice, room, name="Water meter")
        label = make(alice, alice_home, item)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Canvas, "drawString", spy)
            services.render_pdf("https://home.example.com", [label], "a4-3x8")
        assert "Water meter" in drawn
        assert "Cellar" in drawn

    def test_text_the_font_cannot_set_is_replaced_and_the_name_is_cut(self) -> None:
        assert printing.printable("Chaudière Œuvre", limit=50) == "Chaudière Œuvre"
        assert printing.printable("日本 gas", limit=50) == "?? gas"
        assert printing.printable("a\nb\x07c\u202e d", limit=50) == "a b c d"
        assert printing.printable("x" * 200, limit=10) == "x" * 10

    def test_a_very_long_name_stays_on_its_label(self, alice: User, alice_home: Home) -> None:
        room = room_services.create_room(alice, alice_home, name="R" * 120)
        item = room_services.create_item(alice, room, name="Word " * 24)
        pdf = services.render_pdf(
            "https://home.example.com", [make(alice, alice_home, item)], "a4-3x8"
        )
        assert labels_in(pdf) == 1

    def test_the_limits(self, alice: User, alice_home: Home) -> None:
        (one,) = self.sample(alice, alice_home, 1)
        with pytest.raises(ValidationError):
            services.render_pdf("https://home.example.com", [], "a4-3x8")
        with pytest.raises(ValidationError):
            services.render_pdf("https://home.example.com", [one] * 201, "a4-3x8")
        with pytest.raises(ValidationError):
            services.render_pdf("https://home.example.com", [one], "poster")
        assert (
            labels_in(services.render_pdf("https://home.example.com", [one] * 200, "a4-3x8")) == 200
        )

    def test_a_writer_gets_a_label_made_for_each_object_ticked(
        self, alice: User, alice_home: Home, owner_item: Item, owner_room: Room
    ) -> None:
        found = services.labels_to_print(
            alice,
            alice_home,
            [("item", owner_item.id), ("room", owner_room.id), ("item", owner_item.id)],
        )
        assert [label.kind for label in found] == ["item", "room"]  # a repeat counts once
        assert Label.objects.count() == 2

    def test_a_reader_prints_the_labels_that_exist_and_makes_none(
        self, alice: User, alice_home: Home, reader: User, owner_item: Item, owner_room: Room
    ) -> None:
        make(alice, alice_home, owner_item)
        assert len(services.labels_to_print(reader, alice_home, [("item", owner_item.id)])) == 1
        with pytest.raises(PermissionDenied):
            services.labels_to_print(reader, alice_home, [("room", owner_room.id)])
        assert Label.objects.count() == 1

    def test_a_selection_over_the_ceiling_makes_no_label(
        self, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        room = room_services.create_room(alice, alice_home, name="Cellar")
        items = [
            room_services.create_item(alice, room, name=f"Shelf {number}")
            for number in range(printing.MAX_LABELS + 1)
        ]
        with pytest.raises(ValidationError):
            services.labels_to_print(alice, alice_home, [("item", item.id) for item in items])
        assert Label.objects.count() == 0
        # A repeated box counts once: the ceiling is on the objects, not on the ticks.
        found = services.labels_to_print(
            alice, alice_home, [("item", owner_item.id)] * (printing.MAX_LABELS + 5)
        )
        assert len(found) == 1


class TestScreens:
    @pytest.fixture
    def label(self, alice: User, alice_home: Home, owner_item: Item) -> Label:
        return make(alice, alice_home, owner_item)

    def url(self, name: str, home: Home, **kwargs: object) -> str:
        return reverse(f"labels:{name}", kwargs={"home_id": home.id, **kwargs})

    def test_the_list_offers_every_object_with_a_checkbox(
        self,
        signed_in: Client,
        alice_home: Home,
        owner_room: Room,
        owner_item: Item,
        article: Article,
        label: Label,
    ) -> None:
        body = signed_in.get(self.url("list", alice_home)).content.decode()
        for kind, target in (("room", owner_room), ("item", owner_item), ("article", article)):
            assert f'value="{kind}:{target.id}"' in body
        assert "Boiler filter" in body
        assert "Living room" in body
        assert self.url("detail", alice_home, label_id=label.id) in body

    def test_the_detail_shows_the_code_inline_and_the_address(
        self, signed_in: Client, alice_home: Home, label: Label
    ) -> None:
        body = signed_in.get(self.url("detail", alice_home, label_id=label.id)).content.decode()
        assert "<svg" in body
        assert f"/l/{label.code}/" in body
        assert self.url("regenerate", alice_home, label_id=label.id) in body

    def test_a_reader_sees_the_label_but_not_the_buttons_that_change_it(
        self, client: Client, alice_home: Home, reader: User, label: Label
    ) -> None:
        client.force_login(reader)
        response = client.get(self.url("detail", alice_home, label_id=label.id))
        body = response.content.decode()
        assert response.status_code == 200
        assert "<svg" in body
        assert "/regenerate/" not in body
        assert "/revoke/" not in body
        assert "No label yet" not in client.get(self.url("list", alice_home)).content.decode()

    def test_a_reader_cannot_change_a_label(
        self, client: Client, alice_home: Home, reader: User, label: Label
    ) -> None:
        client.force_login(reader)
        for name in ("regenerate", "revoke"):
            assert client.post(self.url(name, alice_home, label_id=label.id)).status_code == 403
        assert (
            client.post(
                self.url("create", alice_home), {"target": f"room:{uuid.uuid4()}"}
            ).status_code
            == 403
        )
        label.refresh_from_db()
        assert label.revoked_at is None
        assert Label.objects.count() == 1

    def test_regenerating_and_revoking_from_the_screen(
        self, signed_in: Client, alice_home: Home, label: Label
    ) -> None:
        response = signed_in.post(self.url("regenerate", alice_home, label_id=label.id))
        fresh = Label.objects.get(revoked_at__isnull=True)
        assert fresh.id != label.id
        assert response["Location"] == self.url("detail", alice_home, label_id=fresh.id)
        signed_in.post(self.url("revoke", alice_home, label_id=fresh.id))
        assert Label.objects.filter(revoked_at__isnull=True).count() == 0

    def test_making_one_from_the_page_of_an_object(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        response = signed_in.post(
            self.url("create", alice_home), {"target": f"room:{owner_room.id}"}
        )
        label = Label.objects.get()
        assert response["Location"] == self.url("detail", alice_home, label_id=label.id)
        for bad in ("room", "room:nonsense", "", f"widget:{owner_room.id}"):
            assert (
                signed_in.post(self.url("create", alice_home), {"target": bad}).status_code == 302
            )
        assert Label.objects.count() == 1

    def test_printing_from_the_screen_gives_a_pdf(
        self, signed_in: Client, alice_home: Home, owner_item: Item, owner_room: Room
    ) -> None:
        response = signed_in.post(
            self.url("print", alice_home),
            {"target": [f"item:{owner_item.id}", f"room:{owner_room.id}"], "layout": "a4-3x8"},
        )
        pdf = b"".join(response.streaming_content) if response.streaming else response.content
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert "attachment" in response["Content-Disposition"]
        assert response["Cache-Control"] == "private, no-store"
        assert labels_in(pdf) == 2

    def test_printing_goes_back_to_the_list_with_a_message_when_it_cannot(
        self, client: Client, alice_home: Home, reader: User, owner_room: Room
    ) -> None:
        client.force_login(reader)
        for data in (
            {"target": f"room:{owner_room.id}"},  # a reader makes none
            {},  # nothing chosen
            {"target": "garbage"},
            {"target": f"room:{owner_room.id}", "layout": "poster"},
        ):
            response = client.post(self.url("print", alice_home), data)
            assert (response.status_code, response["Location"]) == (
                302,
                self.url("list", alice_home),
            )

    def test_the_page_of_an_object_offers_its_label(
        self,
        alice: User,
        signed_in: Client,
        client: Client,
        alice_home: Home,
        owner_item: Item,
        reader: User,
    ) -> None:
        address = reverse(
            "rooms:item-detail", kwargs={"home_id": alice_home.id, "item_id": owner_item.id}
        )
        body = signed_in.get(address).content.decode()
        assert "Make a QR label" in body
        label = make(alice, alice_home, owner_item)
        body = signed_in.get(address).content.decode()
        assert self.url("detail", alice_home, label_id=label.id) in body
        client.force_login(reader)
        body = client.get(address).content.decode()
        assert "Make a QR label" not in body

    def test_the_pages_of_a_room_and_a_stock_item_offer_them_too(
        self, signed_in: Client, alice_home: Home, owner_room: Room, article: Article
    ) -> None:
        room = signed_in.get(
            reverse("rooms:detail", kwargs={"home_id": alice_home.id, "room_id": owner_room.id})
        ).content.decode()
        stock = signed_in.get(
            reverse("stock:detail", kwargs={"home_id": alice_home.id, "article_id": article.id})
        ).content.decode()
        assert "Make a QR label" in room
        assert "Make a QR label" in stock


class TestIsolation:
    @pytest.fixture
    def theirs(self, bob: User, bob_home: Home, foreign_item: Item) -> Label:
        return make(bob, bob_home, foreign_item)

    def test_another_homes_label_is_not_reachable_by_any_screen(
        self, signed_in: Client, alice_home: Home, bob_home: Home, theirs: Label
    ) -> None:
        def go(home: Home, name: str, **kw: object) -> int:
            return signed_in.get(
                reverse(f"labels:{name}", kwargs={"home_id": home.id, **kw})
            ).status_code

        assert go(bob_home, "list") == 404
        assert go(bob_home, "detail", label_id=theirs.id) == 404
        # Through one's own home, the label of another home does not exist either.
        assert go(alice_home, "detail", label_id=theirs.id) == 404
        for name in ("regenerate", "revoke"):
            address = reverse(
                f"labels:{name}", kwargs={"home_id": alice_home.id, "label_id": theirs.id}
            )
            assert signed_in.post(address).status_code == 404
        theirs.refresh_from_db()
        assert theirs.revoked_at is None

    def test_printing_cannot_reach_an_object_of_another_home(
        self,
        signed_in: Client,
        alice_home: Home,
        foreign_item: Item,
        theirs: Label,
    ) -> None:
        response = signed_in.post(
            reverse("labels:print", kwargs={"home_id": alice_home.id}),
            {"target": f"item:{foreign_item.id}"},
        )
        assert response.status_code == 302
        assert Label.objects.filter(home=alice_home).count() == 0

    def test_the_list_shows_this_home_only(
        self, signed_in: Client, alice_home: Home, theirs: Label, foreign_item: Item
    ) -> None:
        body = signed_in.get(
            reverse("labels:list", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert foreign_item.name not in body
        assert theirs.code not in body

    def test_two_homes_hold_their_own_labels(
        self, alice: User, alice_home: Home, owner_item: Item, theirs: Label
    ) -> None:
        mine = make(alice, alice_home, owner_item)
        assert list(services.labels_of(alice_home)) == [mine]
        assert services.get_label(alice_home, theirs.id) is None


class TestErasure:
    def test_deleting_a_home_deletes_its_labels_and_only_its(
        self, alice: User, alice_home: Home, owner_item: Item, bob: User, bob_home: Home
    ) -> None:
        from django.test import TestCase

        make(alice, alice_home, owner_item)
        kept = make(
            bob,
            bob_home,
            room_services.create_item(
                bob, room_services.create_room(bob, bob_home, name="Hall"), name="Lamp"
            ),
        )
        with TestCase.captureOnCommitCallbacks(execute=True):
            home_services.delete_home(alice, alice_home, confirmation="Main house")
        assert list(Label.objects.all()) == [kept]


def test_the_kinds_are_the_three_objects() -> None:
    assert set(LabelKind.values) == {"room", "item", "article"}
