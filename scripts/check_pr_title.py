"""Check that a pull request title follows Conventional Commits.

Pull requests are merged by squash, so their title becomes the commit message
on `main`, which the release tooling reads (docs/adr/0014).

Usage: PR_TITLE="feat: add yearly recurrence" python scripts/check_pr_title.py
"""

import os
import re
import sys

TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
MAX_LENGTH = 100
_PATTERN = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
    r"(?P<breaking>!)?"
    r": (?P<subject>\S.*)$"
)


def problems(title: str) -> list[str]:
    """Return what is wrong with `title`, or an empty list."""
    found: list[str] = []
    if title != title.strip():
        found.append("the title starts or ends with whitespace")
    if len(title) > MAX_LENGTH:
        found.append(f"the title is longer than {MAX_LENGTH} characters")
    match = _PATTERN.match(title.strip())
    if match is None:
        found.append(
            'the title must look like "type: subject" or "type(scope): subject", '
            "with a lowercase type, an optional lowercase scope and a colon followed "
            "by one space"
        )
    elif match["type"] not in TYPES:
        found.append(f"unknown type {match['type']!r}; use one of: {', '.join(TYPES)}")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    title = args[0] if args else os.environ.get("PR_TITLE", "")
    found = problems(title)
    if found:
        sys.stderr.write(f"Pull request title {title!r} is not a Conventional Commit:\n")
        for problem in found:
            sys.stderr.write(f"- {problem}\n")
        sys.stderr.write("Example: feat(schedule): add yearly recurrence\n")
        return 1
    sys.stdout.write(f"Pull request title is a Conventional Commit: {title}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
