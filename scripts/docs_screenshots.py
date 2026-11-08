"""Take the screenshots of the documentation site (docs/adr/0016).

Starts HouseCairn on a throwaway demonstration database, with generated data
only (a demonstration account at example.com and made-up homes), then takes
every screen in English and French, on a computer and on a phone, with
Playwright's Chromium. The images go to docs/_generated/screenshots/, where
the pages read them: `<screen>-<device>.png` in English and
`<screen>-<device>.fr.png` in French (Sphinx's figure_language_filename).

Usage: python scripts/docs_screenshots.py
Needs the `docs` dependency group and the browser:
  uv sync --locked --group docs
  uv run playwright install --only-shell chromium
"""

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_DIR / "docs" / "_generated" / "screenshots"
DEMO_EMAIL = "demo@example.com"
DEMO_HOMES = ("Example house", "Example cottage")
LANGUAGES = {"en": "en-GB", "fr": "fr-FR"}
DEVICES: dict[str, dict[str, Any]] = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def demo_environment(data_dir: Path, port: int) -> dict[str, str]:
    return {
        **os.environ,
        "DEBUG": "true",
        "HOUSECAIRN_DATA_DIR": str(data_dir),
        "DATABASE_URL": f"sqlite:///{data_dir / 'demo.sqlite3'}",
        "ALLOWED_HOSTS": "127.0.0.1",
        "SECRET_KEY": secrets.token_urlsafe(50),
        "HOUSECAIRN_TASKS_SYNC": "true",
        "PYTHONPATH": str(REPO_DIR / "src"),
        "HOUSECAIRN_SCREENSHOT_PORT": str(port),
    }


SEED = """
from housecairn.accounts.models import User
from housecairn.homes import services
from housecairn.homes.models import Membership, Role
import os, sys
user = User.objects.create_user(email=sys.argv[1], password=os.environ["DEMO_PASSWORD"])
homes = [services.create_home(user, name=name) for name in sys.argv[2:]]
other = User.objects.create_user(email="sam@example.com", password=None)
Membership.objects.create(home=homes[0], user=other, role=Role.MEMBER)
_invitation, raw = services.invite(
    user, homes[0], email="guest@example.com", role=Role.READ_ONLY,
    delivery=services.Delivery(),
)
print(homes[0].id)
print(raw)
"""


def manage(env: dict[str, str], *args: str) -> None:
    command = [sys.executable, str(REPO_DIR / "manage.py"), *args]
    subprocess.run(command, check=True, cwd=REPO_DIR, env=env, stdout=subprocess.DEVNULL)  # noqa: S603


def seed(env: dict[str, str]) -> tuple[str, str]:
    """Create the demonstration account, homes, a second member and an invitation.

    Generated data only. Returns the identifier of the first home, whose pages
    are reached by address, and the secret of the pending invitation, whose
    page is one of the screens.
    """
    manage(env, "migrate", "--noinput")
    command = [sys.executable, "-c", f"import django; django.setup()\n{SEED}", DEMO_EMAIL]
    command += DEMO_HOMES
    seed_env = {**env, "DJANGO_SETTINGS_MODULE": "housecairn.settings"}
    result = subprocess.run(  # noqa: S603
        command, check=True, cwd=REPO_DIR, env=seed_env, capture_output=True, text=True
    )
    home_id, invitation = result.stdout.strip().splitlines()[-2:]
    return home_id, invitation


@contextmanager
def server(env: dict[str, str], port: int, log: Path) -> Any:
    command = [sys.executable, str(REPO_DIR / "manage.py"), "runserver", "--noreload"]
    command.append(f"127.0.0.1:{port}")
    with log.open("wb") as server_log:
        process = subprocess.Popen(  # noqa: S603
            command, cwd=REPO_DIR, env=env, stdout=server_log, stderr=subprocess.STDOUT
        )
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{url}/healthz", timeout=2):  # noqa: S310
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise SystemExit("The demonstration server did not start.")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def shoot(page: Any, name: str, language: str, device: str) -> None:
    suffix = "" if language == "en" else f".{language}"
    path = OUTPUT_DIR / f"{name}-{device}{suffix}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"Screenshot written: {path.relative_to(REPO_DIR)}")  # noqa: T201


def open_page(page: Any, url: str) -> None:
    """Go to a known address and check that this page, not another, answered."""
    response = page.goto(url)
    if response is None or not response.ok:
        status = "no response" if response is None else response.status
        raise RuntimeError(f"{url}: {status}")
    page.wait_for_url(url)


def report_failure(page: Any, device: str, log: Path) -> None:
    """Say where the page was when a step failed, and keep an image of it."""
    path = OUTPUT_DIR / f"failure-{device}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"Failed on {page.url!r}, title {page.title()!r}; image: {path.name}", file=sys.stderr)  # noqa: T201
    lines = log.read_text(errors="replace").splitlines()[-30:] if log.exists() else []
    print("Last lines of the demonstration server:", *lines, sep="\n", file=sys.stderr)  # noqa: T201


def signed_in_screens(
    page: Any, base_url: str, password: str, home_id: str, language: str, device: str
) -> None:
    page.goto(f"{base_url}/accounts/login/")
    shoot(page, "sign-in", language, device)
    page.fill("input[name=login]", DEMO_EMAIL)
    page.fill("input[name=password]", password)
    page.click("form[action$='/accounts/login/'] button[type=submit]")
    page.wait_for_url(f"{base_url}/h/")
    shoot(page, "homes", language, device)
    # Pages are reached by address, not by the text of a link: the navigation
    # grows with the application, the addresses do not.
    home_url = f"{base_url}/h/{home_id}/"
    open_page(page, home_url)
    shoot(page, "home", language, device)
    page.goto(f"{base_url}/")
    shoot(page, "start-page", language, device)
    page.goto(f"{base_url}/more/")
    shoot(page, "more", language, device)
    page.goto(f"{base_url}/about/")
    shoot(page, "about", language, device)
    page.goto(f"{base_url}/h/new/")
    shoot(page, "new-home", language, device)
    open_page(page, f"{home_url}household/")
    shoot(page, "household", language, device)
    page.locator("a[href*='/household/members/']").nth(1).click()
    page.wait_for_url("**/household/members/*/")
    shoot(page, "member", language, device)


def take_all(base_url: str, password: str, home_id: str, invitation: str, log: Path) -> int:
    # Imported here: only the docs dependency group provides Playwright.
    from playwright.sync_api import sync_playwright

    taken = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for language, locale in LANGUAGES.items():
            for device, options in DEVICES.items():
                context = browser.new_context(locale=locale, color_scheme="light", **options)
                page = context.new_page()
                try:
                    signed_in_screens(page, base_url, password, home_id, language, device)
                except Exception:
                    report_failure(page, device, log)
                    raise
                context.close()
                # The invitation page, as the invited person sees it: signed out.
                context = browser.new_context(locale=locale, color_scheme="light", **options)
                page = context.new_page()
                page.goto(f"{base_url}/invitations/{invitation}/")
                shoot(page, "invitation", language, device)
                taken += 10
                context.close()
        browser.close()
    return taken


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUTPUT_DIR.glob("*.png"):
        old.unlink()
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="housecairn-demo-") as directory:
        port = free_port()
        env = {**demo_environment(Path(directory), port), "DEMO_PASSWORD": password}
        home_id, invitation = seed(env)
        log = Path(directory) / "server.log"
        with server(env, port, log) as base_url:
            taken = take_all(base_url, password, home_id, invitation, log)
    print(f"{taken} screenshots in {OUTPUT_DIR.relative_to(REPO_DIR)}.")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
