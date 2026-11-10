"""Local browser check: no table makes a page scroll sideways at 360 or 375 px (UX-02).

Not run in CI and no screenshot: it needs a running instance and the Playwright of the
`docs` group (`uv sync --group docs`, `uv run playwright install --only-shell chromium`).

    python tests/e2e/table_widths.py --base http://localhost:8001 --home <home id> \
        --project <project id> [--project <another project id>] --room <room id>

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
WIDTHS = (360, 375)

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
    }
    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in WIDTHS:
            page = browser.new_page(viewport={"width": width, "height": 800})
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
