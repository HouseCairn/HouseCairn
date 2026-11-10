"""Local browser check: no table makes a page scroll sideways at 320, 360 or 375 px (UX-02).

Not run in CI and no screenshot: it needs a running instance and the Playwright of the
`docs` group (`uv sync --group docs`, `uv run playwright install --only-shell chromium`).

    python tests/e2e/table_widths.py --base http://localhost:8001 --home <home id> \
        --project <project id> [--project <another project id>] --room <room id>

The browser asks for French, the longest wording. The data set needs a project that is over
budget by a very large amount (100 billion or more, e.g. a dozen accepted quotes of
9,000,000,000 on one line): at 320 px the "Budget dépassé de ..." pill of the Budget screens is
then wider than its card unless it wraps. Give it as the last `--project`: the first one is the
project sheet, whose header pill is not in a table. The account needs at least one API token
(More, API tokens): without one the list is not a table, and the page checks nothing.

For each Budget view, the project sheet and the other screens that hold a table, it checks
that the page is not wider than the viewport, then lists every table and how it is boxed
(`stack`: cards on a phone, `scroll`: its own scrolling container, `plain`: neither), so a
table that overflows without the common component shows up in the report.
"""

import argparse
import sys

from playwright.sync_api import sync_playwright

EMAIL = "demo@example.com"
PASSWORD = "correct-horse-battery-staple"  # throwaway account of a local instance
WIDTHS = (320, 360, 375)

TABLES_JS = """() => [...document.querySelectorAll('table')].map((t) => ({
  width: Math.round(t.getBoundingClientRect().width),
  box: t.closest('.table-scroll') ? 'scroll'
    : (t.classList.contains('table-stack') ? 'stack' : 'plain'),
}))"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--project", required=True, action="append")
    parser.add_argument("--room", required=True)
    args = parser.parse_args()
    home = f"{args.base}/h/{args.home}"
    compared = "&".join(f"p={p}" for p in args.project)
    pages = {
        "budget overview": f"{home}/budget/",
        "budget rooms": f"{home}/budget/rooms/",
        "budget room": f"{home}/budget/rooms/{args.room}/",
        "budget projects": f"{home}/budget/projects/",
        "budget tasks": f"{home}/budget/tasks/",
        "project sheet": f"{home}/projects/{args.project[0]}/",
        "projects compare": f"{home}/projects/compare/?{compared}",
        "calendar month": f"{args.base}/calendar/month/",
        "calendar year": f"{args.base}/calendar/year/",
        "api tokens": f"{args.base}/me/tokens/",
    }
    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in WIDTHS:
            page = browser.new_page(viewport={"width": width, "height": 800}, locale="fr-FR")
            page.goto(f"{args.base}/accounts/login/")
            page.fill("input[name=login]", EMAIL)
            page.fill("input[name=password]", PASSWORD)
            page.click("main form:has(input[name=login]) button[type=submit]")
            page.wait_for_url("**/today/")
            for name, url in pages.items():
                response = page.goto(url)
                scroll_width, client_width = page.evaluate(
                    "() => [document.documentElement.scrollWidth,"
                    " document.documentElement.clientWidth]"
                )
                tables = page.evaluate(TABLES_JS)
                ok = scroll_width <= client_width
                if name == "api tokens":
                    # Under 56 rem a cell with no label is not drawn: Revoke must stay visible.
                    ok = (
                        ok
                        and bool(tables)
                        and page.locator("a[href*='/revoke/']").first.is_visible()
                    )
                failures += not ok
                status = response.status if response else "?"
                sys.stdout.write(
                    f"{'ok  ' if ok else 'FAIL'} {width} px {name} [{status}] "
                    f"scrollWidth={scroll_width} clientWidth={client_width} tables={tables}\n"
                )
            page.close()
        browser.close()
    if failures:
        raise SystemExit(f"FAILED: {failures} page(s) scroll sideways")


if __name__ == "__main__":
    main()
