"""Check that every commit of a pull request is signed off by its author (DCO).

Each commit must carry a `Signed-off-by: Name <email>` trailer whose address is
the commit author's address, as `git commit -s` writes it. Merge commits are
skipped: they only bring in commits that are checked on their own branch
(docs/adr/0014).

Usage: python scripts/check_signoff.py <base-sha> <head-sha>
"""

import re
import subprocess
import sys
from dataclasses import dataclass

_SIGNOFF = re.compile(r"^Signed-off-by: *(?P<name>.+?) *<(?P<email>[^<>\s]+)> *$", re.MULTILINE)
_FIELD = "\x1f"
_RECORD = "\x1e"


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author_email: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.splitlines()[0] if self.message else ""


def signoff_emails(message: str) -> set[str]:
    """Addresses of the `Signed-off-by` trailers of a commit message, lowercased."""
    return {m["email"].lower() for m in _SIGNOFF.finditer(message)}


def is_signed_off(commit: Commit) -> bool:
    return commit.author_email.lower() in signoff_emails(commit.message)


def parse_log(output: str) -> list[Commit]:
    commits = []
    for record in output.split(_RECORD):
        if not record.strip():
            continue
        sha, parents, email, message = record.lstrip("\n").split(_FIELD, 3)
        commits.append(Commit(sha, tuple(parents.split()), email, message.strip()))
    return commits


def read_commits(base: str, head: str) -> list[Commit]:
    fmt = _FIELD.join(["%H", "%P", "%ae", "%B"]) + _RECORD
    result = subprocess.run(  # noqa: S603 - fixed program, arguments are commit names
        ["git", "log", f"--format={fmt}", f"{base}..{head}"],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_log(result.stdout)


def unsigned(commits: list[Commit]) -> list[Commit]:
    """Commits that need a sign-off and lack one from their author."""
    return [c for c in commits if len(c.parents) < 2 and not is_signed_off(c)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: check_signoff.py <base-sha> <head-sha>\n")
        return 2
    commits = read_commits(args[0], args[1])
    missing = unsigned(commits)
    if missing:
        sys.stderr.write(
            "These commits have no Signed-off-by line matching their author's address:\n"
        )
        for commit in missing:
            sys.stderr.write(f"- {commit.sha[:12]} {commit.subject}\n")
        sys.stderr.write(
            "Sign them off with `git commit --amend -s` or `git rebase --signoff`, "
            "then force-push your branch (see CONTRIBUTING.md).\n"
        )
        return 1
    sys.stdout.write(f"All {len(commits)} commit(s) are signed off.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
