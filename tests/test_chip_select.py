"""The multiple choices among the records of a home: search field and chips (docs/adr/0063).

The widget must post what a `<select multiple>` posts, keep that select in the page for the
reader without script, and refuse what the field refused before. The behaviour of the script is
checked in a browser (`tests/e2e/chip_select_checks.py`); the tests here read its source
for the keys it must handle, so that removing one fails the ordinary suite too.
"""

import re
from pathlib import Path

import pytest
from django import forms
from django.test import Client
from django.urls import reverse

from housecairn.accounts.models import User
from housecairn.core.widgets import ChipSelectMultiple
from housecairn.homes.models import Home
from housecairn.projects.models import Project
from housecairn.rooms import services as room_services
from housecairn.rooms.models import Item, Room
from housecairn.stock.forms import ArticleForm
from housecairn.stock.models import Article
from tests.htmlscan import inline_code_problems

pytest_plugins = (
    "tests.rooms_fixtures",
    "tests.tasks_fixtures",
    "tests.projects_fixtures",
    "tests.stock_fixtures",
)

pytestmark = pytest.mark.django_db

STATIC = Path(__file__).resolve().parents[1] / "src" / "housecairn" / "static"
SCRIPT = (STATIC / "js" / "chip-select.js").read_text()


class Sample(forms.Form):
    rooms = forms.ModelMultipleChoiceField(
        queryset=Room.objects.none(), required=False, widget=ChipSelectMultiple
    )


def sample(home: Home, data: dict[str, object] | None = None) -> Sample:
    form = Sample(data)
    form.fields["rooms"].queryset = Room.objects.filter(home=home)  # type: ignore[attr-defined]
    return form


@pytest.fixture
def two_rooms(alice: User, alice_home: Home) -> tuple[Room, Room]:
    return (
        room_services.create_room(alice, alice_home, name="Kitchen"),
        room_services.create_room(alice, alice_home, name="Cellar"),
    )


class TestTheWidget:
    def test_it_renders_the_native_select_without_script(
        self, alice_home: Home, two_rooms: tuple[Room, Room]
    ) -> None:
        html = str(sample(alice_home)["rooms"])
        assert re.search(r'<select name="rooms"[^>]* multiple', html)
        assert "data-chip-select" in html
        assert " hidden" not in html  # the script hides the select, never the page
        for room in two_rooms:
            assert f'<option value="{room.id}">{room.name}</option>' in html

    def test_a_choice_made_is_rendered_selected(
        self, alice_home: Home, two_rooms: tuple[Room, Room]
    ) -> None:
        kitchen, cellar = two_rooms
        html = str(sample(alice_home, {"rooms": [str(kitchen.id)]})["rooms"])
        assert f'<option value="{kitchen.id}" selected>' in html
        assert f'<option value="{cellar.id}">' in html

    def test_it_posts_what_a_select_posts(
        self, alice_home: Home, two_rooms: tuple[Room, Room]
    ) -> None:
        kitchen, cellar = two_rooms
        form = sample(alice_home, {"rooms": [str(kitchen.id), str(cellar.id)]})
        assert form.is_valid()
        assert set(form.cleaned_data["rooms"]) == {kitchen, cellar}
        assert sample(alice_home, {}).is_valid()  # a field that is not required may be empty

    def test_a_value_that_is_not_a_choice_is_refused_as_before(
        self, alice_home: Home, bob_home: Home, bob: User
    ) -> None:
        foreign = room_services.create_room(bob, bob_home, name="Hall")
        for bad in (str(foreign.id), "not-an-id"):
            form = sample(alice_home, {"rooms": [bad]})
            assert not form.is_valid()
            assert "rooms" in form.errors

    def test_the_options_are_grouped_when_the_field_names_a_group(
        self, alice: User, alice_home: Home, two_rooms: tuple[Room, Room]
    ) -> None:
        kitchen, cellar = two_rooms
        room_services.create_item(alice, kitchen, name="Oven")
        room_services.create_item(alice, cellar, name="Boiler")
        room_services.create_item(alice, kitchen, name="Hob")
        form = ArticleForm(
            items=Item.objects.filter(home=alice_home)
            .select_related("room")
            .order_by("room__name", "name"),
            rooms=Room.objects.filter(home=alice_home),
        )
        html = str(form["compatible_items"])
        assert html.index('<optgroup label="Cellar">') < html.index('<optgroup label="Kitchen">')
        assert re.search(
            r'<optgroup label="Kitchen">\s*<option[^>]*>Hob</option>\s*<option[^>]*>Oven', html
        )

    def test_the_label_of_an_option_is_escaped(self, alice: User, alice_home: Home) -> None:
        room_services.create_room(alice, alice_home, name="<b>Loft</b>")
        html = str(sample(alice_home)["rooms"])
        assert "<b>Loft</b>" not in html
        assert "&lt;b&gt;Loft&lt;/b&gt;" in html

    def test_the_script_is_a_file_and_the_page_has_no_inline_code(
        self, alice_home: Home, two_rooms: tuple[Room, Room]
    ) -> None:
        assert inline_code_problems(str(sample(alice_home)["rooms"])) == []


class TestTheScript:
    """The keys a keyboard needs; the browser check does the rest."""

    @pytest.mark.parametrize("key", ["ArrowDown", "ArrowUp", "Enter", "Escape", "Backspace"])
    def test_it_handles_the_key(self, key: str) -> None:
        assert f'"{key}"' in SCRIPT

    @pytest.mark.parametrize(
        "attribute",
        [
            'role: "combobox"',
            'role: "listbox"',
            'role: "option"',
            '"aria-expanded"',
            '"aria-controls"',
            '"aria-activedescendant"',
            '"aria-live"',
        ],
    )
    def test_it_sets_the_combobox_attributes(self, attribute: str) -> None:
        assert attribute in SCRIPT

    def test_the_select_stays_the_thing_that_is_submitted(self) -> None:
        assert "option.selected = true" in SCRIPT
        assert "entry.option.selected = false" in SCRIPT
        assert "select.hidden = true" in SCRIPT

    def test_it_writes_no_html_from_data(self) -> None:
        assert "innerHTML" not in SCRIPT
        assert "insertAdjacentHTML" not in SCRIPT

    def test_the_style_hides_the_select_only_once_the_script_has_run(self) -> None:
        css = (STATIC / "css" / "chip-select.css").read_text()
        assert ".chip-select select[hidden] {" in css
        assert not re.search(r"\.chip-select select\s*\{", css)  # that would hide the fallback

    def test_the_style_has_a_target_of_44_px(self) -> None:
        css = (STATIC / "css" / "chip-select.css").read_text()
        for selector in (".chip-select__remove", ".chip-select__option", ".chip-select__chip"):
            block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
            assert block, selector
            assert "var(--hc-layout-touch-target)" in block.group(1), selector
        assert "var(--hc-layout-touch-target-lg)" in css  # the field itself
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css.split("*/", 1)[1])  # tokens only


class TestTheStockItemForm:
    def test_the_page_offers_chips_and_a_select_not_boxes(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        html = signed_in.get(
            reverse("stock:create", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert 'src="/static/js/chip-select.js"' in html or "chip-select.js" in html
        assert html.count("data-chip-select") == 2  # compatible items and rooms
        assert 'type="checkbox" name="compatible_items"' not in html
        assert f'<optgroup label="{owner_item.room.name}">' in html
        assert f'<option value="{owner_item.id}">{owner_item.name}</option>' in html

    def test_two_items_and_a_room_are_saved(
        self, signed_in: Client, alice: User, alice_home: Home, owner_item: Item
    ) -> None:
        other = room_services.create_item(alice, owner_item.room, name="Radiator")
        response = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {
                "name": "Valve",
                "compatible_items": [str(owner_item.id), str(other.id)],
                "rooms": [str(owner_item.room.id)],
            },
        )
        assert response.status_code == 302
        article = Article.objects.get(name="Valve")
        assert set(article.compatible_items.all()) == {owner_item, other}
        assert list(article.rooms.all()) == [owner_item.room]

    def test_the_choices_made_come_back_selected_when_the_form_is_refused(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        response = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {"name": "", "compatible_items": [str(owner_item.id)]},
        )
        assert response.status_code == 200
        assert f'<option value="{owner_item.id}" selected>' in response.content.decode()

    def test_a_room_of_another_home_is_refused(
        self, signed_in: Client, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        foreign = room_services.create_room(bob, bob_home, name="Hall")
        response = signed_in.post(
            reverse("stock:create", kwargs={"home_id": alice_home.id}),
            {"name": "Valve", "rooms": [str(foreign.id)]},
        )
        assert response.status_code == 200
        assert not Article.objects.filter(name="Valve").exists()

    def test_the_form_reads_with_the_names_and_never_an_address(
        self, signed_in: Client, alice_home: Home, owner_item: Item
    ) -> None:
        html = signed_in.get(
            reverse("stock:create", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert "@example.com" not in html


class TestTheProjectForm:
    def test_the_page_offers_chips_and_a_select_not_boxes(
        self, signed_in: Client, alice_home: Home, owner_room: Room
    ) -> None:
        html = signed_in.get(
            reverse("projects:create", kwargs={"home_id": alice_home.id})
        ).content.decode()
        assert "chip-select.js" in html
        assert html.count("data-chip-select") == 1
        assert 'type="checkbox" name="rooms"' not in html
        assert f'<option value="{owner_room.id}">{owner_room.name}</option>' in html

    def test_two_rooms_are_saved(
        self, signed_in: Client, alice: User, alice_home: Home, owner_room: Room
    ) -> None:
        other = room_services.create_room(alice, alice_home, name="Attic")
        response = signed_in.post(
            reverse("projects:create", kwargs={"home_id": alice_home.id}),
            {
                "title": "Insulate",
                "status": "planned",
                "priority": "normal",
                "rooms": [str(owner_room.id), str(other.id)],
            },
        )
        assert response.status_code == 302
        assert set(Project.objects.get(title="Insulate").rooms.all()) == {owner_room, other}

    def test_a_room_of_another_home_is_refused(
        self, signed_in: Client, alice_home: Home, bob: User, bob_home: Home
    ) -> None:
        foreign = room_services.create_room(bob, bob_home, name="Hall")
        response = signed_in.post(
            reverse("projects:create", kwargs={"home_id": alice_home.id}),
            {"title": "Insulate", "rooms": [str(foreign.id)]},
        )
        assert response.status_code == 200
        assert not Project.objects.filter(title="Insulate").exists()
