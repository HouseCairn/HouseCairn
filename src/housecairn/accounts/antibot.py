"""Anti-robot check of open sign-up: a proof of work, no third-party service (docs/adr/0024).

The page gets a random challenge, kept in the visitor's session; the browser
finds a number such that SHA-256 of `challenge:number` starts with a given count
of zero bits, which costs a second or so of computation; the server checks it
with one hash. A robot that signs up in bulk pays that for each account, and a
challenge works once (it leaves the session when checked), so a solution cannot
be replayed. It stops nothing a patient attacker with a CPU wants; it makes bulk
sign-up cost something, next to the rate limit and the verification of the
address by email, which are the real barriers.
"""

import hashlib
import secrets
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest

SESSION_KEY = "housecairn_signup_challenge"
# A challenge is valid for this long: the page was opened, the form filled in.
MAX_AGE_SECONDS = 30 * 60
MAX_SOLUTION_LENGTH = 12


def issue(request: HttpRequest) -> dict[str, Any]:
    """A new challenge for this visitor, replacing the previous one."""
    challenge = secrets.token_hex(16)
    bits = int(settings.HOUSECAIRN_SIGNUP_POW_BITS)
    request.session[SESSION_KEY] = {"challenge": challenge, "bits": bits, "at": time.time()}
    return {"challenge": challenge, "bits": bits}


def leading_zero_bits(digest: bytes) -> int:
    value = int.from_bytes(digest, "big")
    return len(digest) * 8 - value.bit_length()


def check(request: HttpRequest, solution: str) -> bool:
    """Whether `solution` solves the challenge of this session; the challenge is used up."""
    pending = request.session.pop(SESSION_KEY, None)
    if not isinstance(pending, dict):
        return False
    if time.time() - float(pending.get("at", 0)) > MAX_AGE_SECONDS:
        return False
    if not (solution.isascii() and solution.isdigit()) or len(solution) > MAX_SOLUTION_LENGTH:
        return False
    digest = hashlib.sha256(f"{pending['challenge']}:{solution}".encode("ascii")).digest()
    return leading_zero_bits(digest) >= int(pending["bits"])


def solve(challenge: str, bits: int) -> str:
    """What the browser does, for tests and tools: the first number that works."""
    counter = 0
    while True:
        digest = hashlib.sha256(f"{challenge}:{counter}".encode("ascii")).digest()
        if leading_zero_bits(digest) >= bits:
            return str(counter)
        counter += 1
