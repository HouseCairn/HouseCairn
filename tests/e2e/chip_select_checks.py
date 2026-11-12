"""Browser check of the multiple-choice field (docs/adr/0063), run by `.github/workflows/ui.yml`.

    python tests/e2e/chip_select_checks.py --base http://localhost:8001

It signs in as the forms account of the CI instance, which has the rooms Kitchen, Cellar and
Attic and the items Oven and Hob (Kitchen) and Boiler (Cellar), and drives the form of a new stock
item, which has two such fields: the equipment it fits and the rooms it is used in.

- with script, at 375 and 1280 px: the field is a combobox named by its label; the arrow keys,
  Enter, Escape and Backspace do what the pattern says; a choice becomes a chip with a button
  "Remove ...", reachable and usable from the keyboard; the targets are 44 px high; the page does
  not scroll sideways; the focus is visible; the form posts what was chosen and the edit page
  shows it again;
- without script: the native select, its options grouped by room, posts the same form.

axe-core is not a dependency of the project, so the roles and the references that its rules would
check (a combobox controlling an existing listbox, options inside it, a name for every button, an
active descendant that exists) are asserted here.
"""

import argparse
import sys
import time
from typing import Any

from browser_checks import FORMS_EMAIL, check, sign_in
from playwright.sync_api import Browser, Page, sync_playwright

EQUIPMENT = "#id_compatible_items"
ROOMS = "#id_rooms"


def new_stock_item(page: Page, base: str) -> str:
    page.goto(f"{base}/tasks/")
    home = page.url.split("/h/")[1].split("/")[0]
    page.goto(f"{base}/h/{home}/stock/new/")
    return home


def box(page: Page, field: str) -> Any:
    """The chip field that holds the search field `field`."""
    return page.locator(f".chip-select:has({field})")


def listbox_of(page: Page, field: str) -> Any:
    return box(page, field).locator("[role=listbox]")


def chips_of(page: Page, field: str) -> list[str]:
    return [
        t.strip() for t in box(page, field).locator(".chip-select__chip-text").all_inner_texts()
    ]


def status_of(page: Page, field: str) -> str:
    return box(page, field).locator("[role=status]").inner_text().strip()


def wait_status(page: Page, field: str, expected: str) -> None:
    page.wait_for_function(
        "([selector, text]) => document.querySelector(selector + ' [role=status]')"
        ".textContent.trim() === text",
        arg=[f".chip-select:has({field})", expected],
        timeout=3000,
    )


def with_script(browser: Browser, base: str, width: int) -> str:
    label = f"{width} px"
    context = browser.new_context(viewport={"width": width, "height": 800})
    page = context.new_page()
    sign_in(page, base, FORMS_EMAIL)
    home = new_stock_item(page, base)
    name = f"Valve {int(time.time())}-{width}"

    combo = page.get_by_role("combobox", name="Compatible items")
    check(combo.count() == 1, f"{label}: the field is a combobox named by its label")
    check(
        page.locator(f"{EQUIPMENT}-native").is_hidden(),
        f"{label}: the native select is hidden, and the search field has the id of the field",
    )
    check(
        page.locator("input[type=checkbox][name=compatible_items]").count() == 0,
        f"{label}: no boxes",
    )
    check(
        page.get_attribute(EQUIPMENT, "aria-expanded") == "false",
        f"{label}: the list starts closed",
    )

    # ArrowDown opens the list and moves to the first suggestion.
    combo.focus()
    page.keyboard.press("ArrowDown")
    options = listbox_of(page, EQUIPMENT).locator("[role=option]")
    check(
        page.get_attribute(EQUIPMENT, "aria-expanded") == "true",
        f"{label}: ArrowDown opens the list",
    )
    check(options.count() == 3, f"{label}: the three items are suggested")
    active = page.get_attribute(EQUIPMENT, "aria-activedescendant")
    check(
        bool(active) and page.locator(f"#{active}").get_attribute("role") == "option",
        f"{label}: the active descendant is an option of the list",
    )
    check(
        page.get_attribute(EQUIPMENT, "aria-controls")
        == listbox_of(page, EQUIPMENT).get_attribute("id"),
        f"{label}: the combobox controls the listbox",
    )
    page.keyboard.press("Escape")
    check(
        listbox_of(page, EQUIPMENT).is_hidden()
        and page.get_attribute(EQUIPMENT, "aria-expanded") == "false",
        f"{label}: Escape closes the list",
    )

    # Typing narrows the list; the result is announced; ArrowDown and Enter pick.
    page.keyboard.type("ov")
    check(options.count() == 1, f"{label}: typing narrows the suggestions")
    wait_status(page, EQUIPMENT, "1 result")
    check(True, f"{label}: the number of results is announced")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    check(
        chips_of(page, EQUIPMENT) == ["Kitchen · Oven"],
        f"{label}: Enter turns the suggestion into a chip",
    )
    check(combo.input_value() == "", f"{label}: the search field is emptied")
    check(
        page.evaluate("document.activeElement.id") == "id_compatible_items",
        f"{label}: the focus stays in the search field",
    )
    check(
        page.get_by_role("button", name="Remove Kitchen · Oven").count() == 1,
        f"{label}: the chip has a button 'Remove Kitchen · Oven'",
    )

    # A typed search with no arrow key picks its first match on Enter, and never submits.
    page.keyboard.type("boil")
    page.keyboard.press("Enter")
    check(
        chips_of(page, EQUIPMENT) == ["Kitchen · Oven", "Cellar · Boiler"] and "/new/" in page.url,
        f"{label}: Enter on a typed search picks the first match without submitting",
    )

    # Backspace in the empty field removes the last chip.
    page.keyboard.press("Backspace")
    check(
        chips_of(page, EQUIPMENT) == ["Kitchen · Oven"], f"{label}: Backspace removes the last chip"
    )

    # A chip is removed from the keyboard: Shift+Tab reaches its button, Enter presses it.
    page.keyboard.press("Shift+Tab")
    check(
        page.evaluate("document.activeElement.getAttribute('aria-label')")
        == "Remove Kitchen · Oven",
        f"{label}: Shift+Tab reaches the button of the chip",
    )
    page.keyboard.press("Enter")
    check(chips_of(page, EQUIPMENT) == [], f"{label}: Enter on the button removes the chip")
    check(
        page.evaluate("document.activeElement.id") == "id_compatible_items",
        f"{label}: the focus goes back to the search field",
    )

    # Choose two, with the mouse or the finger for one and the keyboard for the other.
    combo.click()
    box(page, EQUIPMENT).locator("[role=option]", has_text="Hob").click()
    page.keyboard.type("boiler")
    page.keyboard.press("Enter")
    check(
        chips_of(page, EQUIPMENT) == ["Kitchen · Hob", "Cellar · Boiler"],
        f"{label}: a click and a key each add a chip",
    )
    page.keyboard.press("Escape")

    # The rooms field is the same component.
    rooms = page.get_by_role("combobox", name="Rooms")
    rooms.click()
    box(page, ROOMS).locator("[role=option]", has_text="Cellar").click()
    check(chips_of(page, ROOMS) == ["Cellar"], f"{label}: the rooms field works the same way")
    page.keyboard.press("Escape")

    # Measures.
    # The focus is in the rooms field, the last one used.
    outline = (
        box(page, ROOMS)
        .locator(".chip-select__box")
        .evaluate("e => [getComputedStyle(e).outlineWidth, getComputedStyle(e).outlineStyle]")
    )
    check(outline[0] == "3px" and outline[1] != "none", f"{label}: the focus is visible")
    remove = box(page, EQUIPMENT).locator(".chip-select__remove").first.bounding_box()
    check(
        remove is not None and remove["height"] >= 44 and remove["width"] >= 44,
        f"{label}: the button of a chip is at least 44 px",
    )
    combo.click()
    option = box(page, EQUIPMENT).locator("[role=option]").first.bounding_box()
    check(option is not None and option["height"] >= 44, f"{label}: a suggestion is at least 44 px")
    check(
        page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ),
        f"{label}: the page does not scroll sideways",
    )
    unnamed = page.evaluate(
        "[...document.querySelectorAll('.chip-select button')]"
        ".filter(b => !(b.getAttribute('aria-label') || b.textContent.trim())).length"
    )
    check(unnamed == 0, f"{label}: every button of the field has a name")
    outside = page.evaluate(
        "[...document.querySelectorAll('.chip-select [role=listbox] > *')]"
        ".filter(e => e.getAttribute('role') !== 'option').length"
    )
    check(outside == 0, f"{label}: the listbox holds options only")
    page.keyboard.press("Escape")

    # Submit: the same values as a select would post.
    page.fill("#id_name", name)
    page.click("form.card button[type=submit]")
    page.wait_for_url(lambda url: "/new/" not in url)
    check("/stock/" in page.url, f"{label}: the form is saved")
    page.goto(page.url.rstrip("/") + "/edit/")
    check(
        chips_of(page, EQUIPMENT) == ["Kitchen · Hob", "Cellar · Boiler"]
        and chips_of(page, ROOMS) == ["Cellar"],
        f"{label}: the edit page shows the choices saved as chips",
    )
    context.close()
    return home


def without_script(browser: Browser, base: str) -> None:
    label = "no script"
    cookies_context = browser.new_context()
    cookies_page = cookies_context.new_page()
    sign_in(cookies_page, base, FORMS_EMAIL)
    cookies = cookies_context.cookies()
    cookies_context.close()
    context = browser.new_context(viewport={"width": 375, "height": 800}, java_script_enabled=False)
    context.add_cookies(cookies)
    page = context.new_page()
    new_stock_item(page, base)
    select = page.locator(f"select{EQUIPMENT}")
    check(
        select.is_visible() and select.get_attribute("multiple") is not None,
        f"{label}: the native multiple select shows",
    )
    check(
        page.locator(f"select{EQUIPMENT} optgroup").count() == 2,
        f"{label}: its options are grouped by room",
    )
    check(page.locator(".chip-select__input").count() == 0, f"{label}: no search field is drawn")
    check(
        page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ),
        f"{label}: the page does not scroll sideways",
    )
    name = f"Gasket {int(time.time())}"
    select.select_option(label=["Oven", "Boiler"])
    page.locator(f"select{ROOMS}").select_option(label=["Attic"])
    page.fill("#id_name", name)
    page.click("form.card button[type=submit]")
    page.wait_for_url(lambda url: "/new/" not in url)
    page.goto(page.url.rstrip("/") + "/edit/")
    chosen = page.locator(f"select{EQUIPMENT} option:checked").all_inner_texts()
    check(
        chosen == ["Oven", "Boiler"] or sorted(chosen) == ["Boiler", "Oven"],
        f"{label}: the form posts the choices",
    )
    check(
        page.locator(f"select{ROOMS} option:checked").all_inner_texts() == ["Attic"],
        f"{label}: the room is saved too",
    )
    context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="address of the running instance")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (375, 1280):
            with_script(browser, base, width)
        without_script(browser, base)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
