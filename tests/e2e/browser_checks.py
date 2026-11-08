"""Browser checks run in CI (`.github/workflows/ui.yml`), against a running instance.

Playwright is not a dependency of the project: the workflow installs a pinned
version for this job only.

    python tests/e2e/browser_checks.py capture --base http://localhost:8000 --out shots
    python tests/e2e/browser_checks.py passkey --base http://localhost:8001
    python tests/e2e/browser_checks.py sso --base http://localhost:8001 --provider http://127.0.0.1:8002

`capture` takes the screenshots attached to the workflow run: the same screens on a
phone and on a desktop, in English and French. `passkey` replays the sign-in with a
virtual authenticator (Chromium's WebAuthn emulation): it registers a passkey, then
signs in through the conditional (autofill) path and through the fallback button.
What no script can do, the real autofill pop-up of each browser, is listed in
docs/adr/0018. `sso` clicks the provider button of the sign-in page once and checks that
the browser lands on the provider, with no confirmation page of the application in between.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

EMAIL = "demo@example.com"
PASSWORD = "correct-horse-battery-staple"  # throwaway account of the CI instance

DEVICES = {
    "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "scale": 2},
    "desktop": {"viewport": {"width": 1280, "height": 800}, "is_mobile": False, "scale": 1},
}
# (name, path, needs sign-in)
SCREENS = [
    ("login", "/accounts/login/", False),
    ("signup", "/accounts/signup/", False),
    ("password-reset", "/accounts/password/reset/", False),
    ("welcome", "/", False),
    ("home", "/", True),
    ("homes", "/h/", True),
    ("more", "/more/", True),
    ("security", "/accounts/2fa/", True),
    ("security-keys", "/accounts/2fa/webauthn/", True),
    ("api-docs", "/api/docs/", True),
    ("about", "/about/", True),
    ("not-found", "/no/such/page/", False),
    # Homes and household (docs/adr/0020): addresses found once signed in.
    ("new-home", "/h/new/", True),
    ("home-page", "{home}", True),
    ("household", "{home}household/", True),
    ("member", "{member}", True),
    ("invitation", "{invitation}", False),
    ("invitation-invalid", "/invitations/hci_no-longer-valid/", False),
    # Accounts, data and administration (docs/adr/0022 and 0023).
    ("password-change", "/accounts/password/change/", True),
    ("email-addresses", "/accounts/email/", True),
    ("account-delete", "/accounts/delete/", True),
    ("home-audit", "{home}audit/", True),
    ("home-delete", "{home}delete/", True),
    ("instance", "/instance/", True),
    ("instance-audit", "/instance/audit/", True),
    ("instance-settings", "/instance/settings/", True),
    ("instance-providers", "/instance/providers/", True),
    ("instance-provider", "/instance/providers/company/", True),
    ("instance-invitation", "{instance_invitation}", False),
    # Rooms, items and photos (docs/adr/0029, 0030).
    ("rooms", "{home}rooms/", True),
    ("rooms-reorder", "{home}rooms/?reorder=1", True),
    ("room", "{room}", True),
    ("room-form", "{home}rooms/new/", True),
    ("room-memory", "{room}memory/", True),
    ("item", "{item}", True),
    ("item-form", "{room}items/new/", True),
    ("photo-form", "{room}photos/new/", True),
    ("search", "{home}search/?q=stove", True),
    # Tasks, occurrences and attachments (docs/adr/0031 to 0034).
    ("tasks", "{home}tasks/", True),
    ("tasks-done", "{home}tasks/?status=done", True),
    ("task", "{task}", True),
    ("task-form", "{home}tasks/new/", True),
    ("task-edit", "{task}edit/", True),
    ("task-postpone", "{task}postpone/", True),
    # Today, My home, History and the display preferences (docs/adr/0037).
    ("today", "{home}today/", True),
    ("history", "{home}history/", True),
    ("my-home", "/me/", True),
    ("display-preferences", "/me/preferences/", True),
    ("task-files", "{task}attachments/new/", True),
]
NOT_FOUND = {"not-found", "invitation-invalid"}


def resolve(page: Page, base: str, path: str, invitations: tuple[str, str]) -> str:
    """Fill in the addresses of the demonstration data, read through the API."""
    invitation, instance_invitation = invitations
    if "{invitation}" in path:
        return path.replace("{invitation}", f"/invitations/{invitation}/")
    if "{instance_invitation}" in path:
        return path.replace("{instance_invitation}", f"/join/{instance_invitation}/")
    placeholders = ("{home}", "{member}", "{room}", "{item}", "{task}")
    if not any(placeholder in path for placeholder in placeholders):
        return path
    homes = page.request.get(f"{base}/api/v1/homes/").json()["results"]
    home = next(h for h in homes if h["name"] == "Main house")
    home_path = f"/h/{home['id']}/"
    if "{member}" in path:
        members = page.request.get(f"{base}/api/v1/homes/{home['id']}/members/").json()
        other = next(m for m in members["results"] if m["user"]["email"] != EMAIL)
        return f"{home_path}household/members/{other['id']}/"
    if "{task}" in path:
        tasks = page.request.get(f"{base}/api/v1/homes/{home['id']}/tasks/?status=open").json()
        task = next(
            t for t in tasks["results"] if t["title"] == "Change the smoke detector battery"
        )
        occurrence = task["open_occurrence"]
        return path.replace("{task}", f"{home_path}tasks/{task['id']}/").replace(
            "postpone/", f"occurrences/{occurrence}/postpone/"
        )
    if "{room}" in path or "{item}" in path:
        rooms = page.request.get(f"{base}/api/v1/homes/{home['id']}/rooms/").json()["results"]
        room = next(r for r in rooms if r["name"] == "Living room")
        items = page.request.get(f"{base}/api/v1/homes/{home['id']}/items/").json()["results"]
        item = next(i for i in items if i["name"] == "Wood stove")
        path = path.replace("{room}", f"{home_path}rooms/{room['id']}/")
        path = path.replace("{item}", f"{home_path}items/{item['id']}/")
        return path
    return path.replace("{home}", home_path)


def sign_in(page: Page, base: str) -> None:
    page.goto(f"{base}/accounts/login/")
    page.fill("input[name=login]", EMAIL)
    page.fill("input[name=password]", PASSWORD)
    page.click("main form:has(input[name=login]) button[type=submit]")
    page.wait_for_url(f"{base}/h/")


def sign_out(page: Page, base: str) -> None:
    page.goto(f"{base}/more/")
    page.click("button:has-text('Sign out')")
    page.wait_for_url(f"{base}/")


def capture(browser: Browser, base: str, out: Path, invitations: tuple[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for device, options in DEVICES.items():
        for language in ("en", "fr"):
            # One sign-in per device and language, reused by the signed-in
            # screens: signing in for each screen would hit the sign-in rate limit.
            session: Any = None
            for name, path, authenticated in SCREENS:
                context = browser.new_context(
                    viewport=options["viewport"],
                    is_mobile=options["is_mobile"],
                    has_touch=options["is_mobile"],
                    device_scale_factor=options["scale"],
                    locale=language,
                    extra_http_headers={"Accept-Language": language},
                    storage_state=session if authenticated else None,
                )
                page = context.new_page()
                if authenticated and session is None:
                    sign_in(page, base)
                    session = context.storage_state()
                path = resolve(page, base, path, invitations)
                response = page.goto(f"{base}{path}")
                say(f"{device}-{language}-{name}")
                page.wait_for_load_state("networkidle")
                expected = 404 if name in NOT_FOUND else 200
                if response is None or response.status != expected:
                    raise SystemExit(f"{name}: unexpected status for {path}")
                page.screenshot(path=str(out / f"{device}-{language}-{name}.png"), full_page=True)
                context.close()
    say(f"{len(list(out.glob('*.png')))} screenshots in {out}")


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
    page.wait_for_url(f"{base}/h/", timeout=15000)
    check(True, "conditional (autofill) passkey sign-in reached the homes page")
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
    page.wait_for_url(f"{base}/h/", timeout=15000)
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
    parser.add_argument("mode", choices=["capture", "passkey", "sso"])
    parser.add_argument("--base", required=True, help="address of the running instance")
    parser.add_argument("--out", type=Path, default=Path("shots"))
    parser.add_argument("--provider", help="address of the stub identity provider (sso mode)")
    parser.add_argument(
        "--invitation-file",
        type=Path,
        help="file holding the secret of a pending invitation of the demonstration data",
    )
    parser.add_argument(
        "--instance-invitation-file",
        type=Path,
        help="file holding the secret of a pending invitation to the instance",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        if args.mode == "capture":
            invitation = args.invitation_file.read_text().strip() if args.invitation_file else ""
            instance_file = args.instance_invitation_file
            instance_invitation = instance_file.read_text().strip() if instance_file else ""
            capture(browser, base, args.out, (invitation, instance_invitation))
        elif args.mode == "sso":
            sso(browser, base, args.provider.rstrip("/"))
        else:
            passkey(browser, base)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
