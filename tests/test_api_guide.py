"""Every command of the guide of the API runs as written against a live instance.

`docs/api/guide.md` gives `curl` commands in ```sh blocks. Each block is run by bash, with
`HC`, `TOKEN` and `HOME_ID` set as the guide asks, against a server started for the test
(under `HOUSECAIRN_URL_PREFIX` too, when it is set: the CI runs this module in both). A
block must end without error, and print what its `# prints:` lines say.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from housecairn.accounts.models import User
from housecairn.apitokens import services as token_services
from housecairn.homes import services as home_services
from housecairn.rooms import services as room_services
from housecairn.tasks import services as task_services

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "api" / "guide.md"
BLOCK = re.compile(r"^```sh\n(.*?)^```", re.S | re.M)

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")


def blocks() -> list[str]:
    return BLOCK.findall(GUIDE.read_text(encoding="utf-8"))


def test_the_guide_has_examples_to_run() -> None:
    found = blocks()
    assert len(found) >= 8
    assert all("$HC" in block for block in found)
    # Never an address written by hand: the base comes from HC, prefix included.
    assert not any(re.search(r"curl[^\n]*\s['\"]?/api/", block) for block in found)


@pytest.fixture
def instance(live_server: Any, tmp_path: Path) -> dict[str, str]:
    owner = User.objects.create_user(email="guide@example.com", password="A-long-pass-phrase-1")
    home = home_services.create_home(owner, name="Guide")
    room_services.create_room(owner, home, name="Kitchen")
    for title in ("Clean the gutters", "Test the alarm", "Check the boiler"):
        task_services.create_task(owner, home, title=title)
    _token, raw = token_services.issue_token(
        owner, name="guide", scopes=["read", "write"], homes=[home]
    )
    return {
        "HC": live_server.url + (settings.HOUSECAIRN_URL_PREFIX or ""),
        "TOKEN": raw,
        "HOME_ID": str(home.id),
        "WORKDIR": str(tmp_path),
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("index", range(len(blocks())))
def test_a_command_of_the_guide_runs_as_written(instance: dict[str, str], index: int) -> None:
    block = blocks()[index]
    env = {**os.environ, **{k: v for k, v in instance.items() if k != "WORKDIR"}}
    result = subprocess.run(  # noqa: S603 - the commands of our own documentation
        ["bash", "-euo", "pipefail", "-c", block],  # noqa: S607
        cwd=instance["WORKDIR"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    shown = f"{block}\n--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}"
    assert result.returncode == 0, shown
    for expected in re.findall(r"^# prints: (.+)$", block, re.M):
        assert expected in result.stdout.split(), f"{block}\n--- stdout\n{result.stdout}"
    if "next" in block:
        # The loop of the pages read every task, two by two.
        assert result.stdout.count('"results"') >= 2
