"""The proof-of-work worker (static/js/pow-worker.js) ignores what is not for it.

The worker script runs under Node.js in a bare context that stands in for a worker
scope: nothing else of the application is involved.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parent.parent / "src/housecairn/static/js/pow-worker.js"
CHALLENGE = "0123456789abcdef0123456789abcdef"

RUNNER = textwrap.dedent(
    """
    const fs = require('fs')
    const vm = require('vm')
    const { webcrypto } = require('crypto')
    const [path, payload] = process.argv.slice(1)
    const posted = []
    const scope = {
      crypto: webcrypto,
      location: { origin: 'https://app.example.com' },
      postMessage: (message) => posted.push(message),
    }
    vm.runInNewContext(fs.readFileSync(path, 'utf8'), {
      self: scope, TextEncoder, Uint8Array, Math, String, Number, Object, RegExp,
    })
    const event = JSON.parse(payload)
    scope.onmessage(event).then(() => console.log(JSON.stringify(posted)))
    """
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def run(origin: str | None, data: object) -> list[str]:
    event: dict[str, object] = {"data": data}
    if origin is not None:
        event["origin"] = origin
    done = subprocess.run(  # noqa: S603 - fixed program, test-controlled arguments
        ["node", "-e", RUNNER, str(WORKER), json.dumps(event)],  # noqa: S607 - node from PATH
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(done.stdout)


class TestWorker:
    @pytest.mark.parametrize("origin", ["", "https://app.example.com"])
    def test_the_page_gets_its_solution(self, origin: str) -> None:
        posted = run(origin, {"challenge": CHALLENGE, "bits": 8})
        assert len(posted) == 1
        assert posted[0].isdigit()

    def test_the_solution_is_the_one_the_server_accepts(self) -> None:
        from housecairn.accounts import antibot

        posted = run("", {"challenge": CHALLENGE, "bits": 8})
        assert posted == [antibot.solve(CHALLENGE, 8)]

    @pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://app.example.com"])
    def test_another_origin_is_ignored(self, origin: str) -> None:
        assert run(origin, {"challenge": CHALLENGE, "bits": 8}) == []

    @pytest.mark.parametrize(
        "data",
        [
            None,
            "text",
            42,
            [],
            {},
            {"challenge": CHALLENGE},
            {"bits": 8},
            {"challenge": 12345678, "bits": 8},
            {"challenge": CHALLENGE, "bits": "8"},
            {"challenge": CHALLENGE, "bits": 8.5},
            {"challenge": CHALLENGE, "bits": 7},
            {"challenge": CHALLENGE, "bits": 25},
            {"challenge": CHALLENGE, "bits": -1},
            {"challenge": "", "bits": 8},
            {"challenge": "short", "bits": 8},
            {"challenge": "x" * 200, "bits": 8},
            {"challenge": "has space and: colon", "bits": 8},
        ],
    )
    def test_a_malformed_message_is_ignored(self, data: object) -> None:
        assert run("", data) == []
