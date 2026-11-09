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
    page.wait_for_url(f"{base}/me/")


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
    page.wait_for_url(f"{base}/me/", timeout=15000)
    check(True, "conditional (autofill) passkey sign-in reached My home")
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
    page.wait_for_url(f"{base}/me/", timeout=15000)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["passkey", "sso"])
    parser.add_argument("--base", required=True, help="address of the running instance")
    parser.add_argument("--provider", help="address of the stub identity provider (sso mode)")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        if args.mode == "sso":
            sso(browser, base, args.provider.rstrip("/"))
        else:
            passkey(browser, base)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
