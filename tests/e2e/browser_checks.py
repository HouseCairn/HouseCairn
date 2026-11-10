"""Browser checks run in CI (`.github/workflows/ui.yml`), against a running instance.

Playwright is not a dependency of the project: the workflow installs a pinned
version for this job only.

    python tests/e2e/browser_checks.py passkey --base http://localhost:8001
    python tests/e2e/browser_checks.py sso --base http://localhost:8001 --provider http://127.0.0.1:8002

No screenshots until the dedicated lot before the public release (docs/adr/0017).
`passkey` replays the sign-in with a virtual authenticator (Chromium's WebAuthn
emulation): it registers a passkey, then signs in through the conditional
(autofill) path and through the fallback button.
What no script can do, the real autofill pop-up of each browser, is listed in
docs/adr/0018. `sso` clicks the provider button of the sign-in page once and checks that
the browser lands on the provider, with no confirmation page of the application in between.
`in-place` (local only, not in the workflow) checks that Done and Undo on Today leave the
page where it was, keep the focus on the row and show the banner above the bar. The
banner of a stock shortage (a long message, French, 360 and 320 px) must still leave the
last button of the page reachable, with script and without: with script the page keeps the
banner's real height, without it the banner is a sticky box that takes its own room.

    python tests/e2e/browser_checks.py in-place --base http://localhost:8001
"""

import argparse
import sys

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

EMAIL = "demo@example.com"
PASSWORD = "correct-horse-battery-staple"  # throwaway account of the CI instance


def sign_in(page: Page, base: str) -> None:
    page.goto(f"{base}/accounts/login/")
    page.fill("input[name=login]", EMAIL)
    page.fill("input[name=password]", PASSWORD)
    page.click("main form:has(input[name=login]) button[type=submit]")
    page.wait_for_url("**/today/")


def sign_out(page: Page, base: str) -> None:
    page.goto(f"{base}/more/")
    page.click("button:has-text('Sign out')")
    page.wait_for_url(f"{base}/")


def say(message: str) -> None:
    sys.stdout.write(message + "\n")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")
    say(f"ok: {message}")


def virtual_authenticator(context: BrowserContext, page: Page) -> None:
    session = context.new_cdp_session(page)
    session.send("WebAuthn.enable")
    session.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )


def passkey(browser: Browser, base: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    virtual_authenticator(context, page)

    # The page itself: no passkey button, the autofill token on the address field.
    page.goto(f"{base}/accounts/login/")
    check(page.locator("#passkey_login").count() == 0, "no element #passkey_login")
    check("Sign in with a passkey" not in page.content(), "no 'Sign in with a passkey' text")
    check(
        page.get_attribute("input[name=login]", "autocomplete") == "username webauthn",
        "address field has autocomplete='username webauthn'",
    )

    # Register a passkey (a discoverable credential) while signed in with the password.
    sign_in(page, base)
    page.goto(f"{base}/accounts/2fa/webauthn/add/")
    if "reauthenticate" in page.url:
        page.fill("input[name=password]", PASSWORD)
        page.click("main form button[type=submit]")
        page.wait_for_load_state()
    page.check("input[type=checkbox]")
    page.click("button:has-text('Add')")
    page.wait_for_url("**/recovery-codes/")
    check(True, "passkey registered")
    sign_out(page, base)

    # Conditional mediation: opening the sign-in page signs in with no click at all.
    page.goto(f"{base}/accounts/login/")
    page.wait_for_url("**/today/", timeout=15000)
    check(True, "conditional (autofill) passkey sign-in reached Today")
    sign_out(page, base)

    # Fallback: a browser without conditional mediation gets a button once an address is typed.
    page.add_init_script("PublicKeyCredential.isConditionalMediationAvailable = async () => false")
    page.goto(f"{base}/accounts/login/")
    offer = page.locator(".passkey-offer button")
    page.wait_for_function("document.querySelector('.passkey-offer')")
    check(not offer.is_visible(), "no offer before an address is typed")
    page.fill("input[name=login]", "someone@example.com")
    check(offer.is_visible(), "offer shown once an address is typed, whatever the address")
    offer.click()
    page.wait_for_url("**/today/", timeout=15000)
    check(True, "fallback button signs in with the passkey")
    context.close()


def sso(browser: Browser, base: str, provider: str) -> None:
    """One click from the sign-in page to the provider (a stub that serves the discovery)."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    navigations: list[str] = []
    page.on(
        "request",
        lambda request: (
            navigations.append(f"{request.method} {request.url}")
            if request.is_navigation_request()
            else None
        ),
    )
    page.goto(f"{base}/accounts/login/")
    button = page.locator("form button:has-text('Continue with Company SSO')")
    check(button.count() == 1, "one provider button on the sign-in page")
    navigations.clear()
    button.click()
    page.wait_for_url(f"{provider}/authorize*", timeout=15000)
    check(True, "one click reached the provider")
    check(
        navigations[0].startswith("POST ") and "/accounts/oidc/" in navigations[0],
        f"the click posts to the provider login ({navigations[0]})",
    )
    check(
        not any("/accounts/oidc/" in n and n.startswith("GET ") for n in navigations),
        "no confirmation page between the button and the provider",
    )
    check("state=" in page.url and "code_challenge=" in page.url, "state and PKCE are sent")
    page.close()


def reach_the_end_of_the_list(page: Page, row_id: str) -> None:
    """The banner of Undo must not cover the last button of the page (NAV-05).

    Mark a row done, go to the bottom, and compare the last button of `main` with the
    banner: not one pixel of the button may be under it (a click on its edge would miss).
    """
    page.locator(f"#{row_id} button.button-done").click()
    page.wait_for_selector("#undo-region .undo-banner button")
    last_button_is_reachable(page)
    page.locator("#undo-region .undo-banner button").click()
    page.wait_for_selector(f"#{row_id}:not(.task-row-closed) button.button-done")
    page.evaluate("window.scrollTo(0, 0)")


def last_button_is_reachable(page: Page) -> None:
    """With the banner shown, go to the bottom: nothing covers the last button of `main`."""
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(200)
    covered = page.evaluate(
        """() => {
            const buttons = [...document.querySelectorAll('main a.button, main button')]
                .filter((el) => el.offsetParent !== null && !el.closest('#undo-region'));
            const last = buttons[buttons.length - 1];
            if (!last) return 'no button in main';
            const box = last.getBoundingClientRect();
            const banner = document.querySelector('#undo-region .undo-banner');
            if (!banner) return '';
            const over = banner.getBoundingClientRect();
            const hidden = Math.round(box.bottom - over.top);
            return hidden > 0 ? hidden + ' px of the button under the banner' : '';
        }"""
    )
    check(covered == "", f"the last button of the page is not covered by the banner ({covered})")
    outside = page.evaluate(
        """() => {
            const banner = document.querySelector('#undo-region .undo-banner');
            if (!banner) return '';
            const box = banner.getBoundingClientRect();
            const out = Math.max(-box.top, box.bottom - window.innerHeight);
            return out > 0 ? Math.round(out) + ' px of the banner out of the view' : '';
        }"""
    )
    check(outside == "", f"the banner stays in the view ({outside})")
    last = page.evaluate_handle(
        """() => {
            const buttons = [...document.querySelectorAll('main a.button, main button')]
                .filter((el) => el.offsetParent !== null && !el.closest('#undo-region'));
            return buttons[buttons.length - 1];
        }"""
    ).as_element()
    if last is not None:
        # A trial click runs every check of a real click (visible, stable, receives the
        # events at its centre) without pressing: a banner over the button refuses it.
        last.click(trial=True, timeout=2000)
        check(True, "the last button of the page takes the click")


def in_place(browser: Browser, base: str) -> None:
    """Done and Undo keep the person where they are (NAV-05). Local only, not in CI.

    Needs the demo account with a home holding at least 15 open tasks due today:

        uv run python manage.py shell -c "
        from housecairn.accounts.models import User
        from housecairn.homes import services as homes
        from housecairn.tasks import services as tasks
        user = User.objects.create_user(email='demo@example.com', password='...')
        home = homes.create_home(user, name='Main house')
        for n in range(20):
            tasks.create_task(user, home, title=f'Task {n + 1}', due_on=tasks.today())
        article = stock.create_article(user, home, name='Rien en stock', unit='piece')
        task = tasks.create_task(user, home, title='Stock task', due_on=tasks.today())
        materials.add_material(user, task, article, Decimal('2'))
        "

    (with `from decimal import Decimal`, `from housecairn.stock import services as stock` and
    `from housecairn.tasks import materials` in the imports above.)
    """
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    errors: list[str] = []
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    sign_in(page, base)
    rows = page.locator("li.task-row:has(button.button-done)")
    check(rows.count() >= 15, "Today lists at least 15 open tasks")
    row = rows.nth(12)
    row_id = row.get_attribute("id") or ""
    check(row_id.startswith("occ-"), "a row is named after its occurrence")
    row.scroll_into_view_if_needed()
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(200)
    before = page.evaluate("window.scrollY")
    check(before > 300, f"the page is scrolled down ({before} px)")
    address = page.url
    row.locator("button.button-done").click()
    page.wait_for_selector(f"#{row_id}.task-row-closed")
    page.wait_for_selector("#undo-region .undo-banner button")
    after = page.evaluate("window.scrollY")
    check(abs(after - before) <= 1, f"Done does not move the page ({before} -> {after} px)")
    check(page.url == address, "Done leaves the address as it was")
    focused = page.evaluate(
        "document.activeElement.closest('li') && document.activeElement.closest('li').id"
    )
    check(focused == row_id, "the focus stays on the row")
    banner = page.locator("#undo-region .undo-banner").bounding_box()
    bar = page.locator("nav.nav").bounding_box()
    check(
        banner is not None and bar is not None and banner["y"] + banner["height"] <= bar["y"],
        "the banner sits above the bar at the bottom",
    )
    check(
        "Marked done." in (page.locator("#undo-region").text_content() or ""),
        "the live region says what happened",
    )
    page.locator("#undo-region .undo-banner button").click()
    page.wait_for_selector(f"#{row_id}:not(.task-row-closed) button.button-done")
    check(abs(page.evaluate("window.scrollY") - before) <= 1, "Undo does not move the page")
    check(
        page.evaluate("document.activeElement.classList.contains('button-done')")
        and page.evaluate("document.activeElement.closest('li').id") == row_id,
        "after Undo the focus is on the Done button of the row",
    )
    check("Undone." in (page.locator("#undo-region").text_content() or ""), "Undo is announced")
    check(page.url == address, "Undo leaves the address as it was")
    reach_the_end_of_the_list(page, row_id)
    check(not errors, f"no error in the console (CSP included): {errors}")
    context.close()
    for width in (360, 320):
        stock_shortage_banner(browser, base, width)
    for width in (360, 320):
        stock_shortage_banner(browser, base, width, script=False)


def stock_shortage_banner(browser: Browser, base: str, width: int, script: bool = True) -> None:
    """The banner of a stock shortage, in French, must not hide the end of Today (NAV-05).

    The message is long: on a narrow screen the banner is three or four lines high. With
    script the room kept for it follows its real height; without script Done is a form
    post and a redirect, the session gives the banner back on the next page, and the banner
    takes its own room (a sticky box at the end of the page).
    """
    label = f"{width} px{'' if script else ', no script'}"
    context = browser.new_context(
        viewport={"width": width, "height": 812}, locale="fr-FR", java_script_enabled=script
    )
    page = context.new_page()
    sign_in(page, base)
    row = page.locator("li.task-row:has-text('Stock task')")
    check(row.count() == 1, f"{label}: Today lists the task that needs an empty stock item")
    row_id = row.get_attribute("id") or ""
    page.locator(f"#{row_id} button.button-done").click()
    if not script:
        page.wait_for_url("**/today/**")
    page.wait_for_selector("#undo-region .undo-banner button")
    text = page.locator("#undo-region").text_content() or ""
    check("Stock insuffisant" in text, f"{label}: the banner says the stock is short")
    box = page.locator("#undo-region .undo-banner").bounding_box()
    say(f"{label}: the banner is {box['height'] if box else 0:.0f} px high")
    last_button_is_reachable(page)
    page.locator("#undo-region .undo-banner button").click()
    if not script:
        page.wait_for_url("**/today/**")
    page.wait_for_selector(f"#{row_id}:not(.task-row-closed) button.button-done")
    context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["passkey", "sso", "in-place"])
    parser.add_argument("--base", required=True, help="address of the running instance")
    parser.add_argument("--provider", help="address of the stub identity provider (sso mode)")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        if args.mode == "sso":
            sso(browser, base, args.provider.rstrip("/"))
        elif args.mode == "in-place":
            in_place(browser, base)
        else:
            passkey(browser, base)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
