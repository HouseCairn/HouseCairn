"""Fail a pull request that changes what users see or configure without touching `docs/`.

The documentation changes with the code (docs/adr/0016, CONTRIBUTING.md). A pull
request is concerned when it changes a view, a URL route, a template, a form, a
serializer, an API module, a static file, the in-app help links, the settings or
the example deployment files (`USER_FACING`). It then must change at least one
file under `docs/`, or carry the `no-docs-needed` label, which only the
maintainer can add (triage permission or more). Pull requests opened by
Dependabot (`PR_AUTHOR`) are exempt: they bump the image of `compose.yaml`,
which changes no screen and no setting.

Pull requests that change nothing user-facing pass: tests, workflows, scripts,
dependencies, documentation itself.

Usage: PR_LABELS=<comma-separated labels> PR_AUTHOR=<login> \
       python scripts/check_docs_updated.py <base-sha> <head-sha>
"""

import os
import re
import subprocess
import sys
from collections.abc import Iterable

LABEL = "no-docs-needed"
# Only the author of the pull request counts, never a label or a branch name, and
# only this one account: no other bot is exempted.
EXEMPT_AUTHOR = "dependabot[bot]"
DOCS_PREFIX = "docs/"
# Files whose change is visible to users or administrators. A module may carry a
# prefix (`api_urls.py`, `contractor_views.py`), and forms, views and API modules
# may be split into packages (`tasks/forms/`). Static files are what the browser
# loads, and `core/help.py` holds the in-app help links to the documentation.
USER_FACING = re.compile(
    r"""^(
        src/housecairn/(?:[^/]+/)?(?:[^/]+_)?(?:views|urls|forms|api|serializers|schema)\.py
      | src/housecairn/[^/]+/(?:forms|views|api)/[^/]+\.py
      | src/housecairn/settings\.py
      | src/housecairn/core/help\.py
      | src/housecairn/static/.+
      | src/housecairn/templates/.+\.html
      | compose\.yaml
      | deploy/[^/]+\.example
      | \.env\.example
    )$""",
    re.VERBOSE,
)


def user_facing(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if USER_FACING.match(path))


def documented(paths: Iterable[str]) -> bool:
    return any(path.startswith(DOCS_PREFIX) for path in paths)


def problems(paths: list[str], labels: Iterable[str], author: str = "") -> list[str]:
    """Why the pull request fails the rule, or an empty list."""
    concerned = user_facing(paths)
    if author == EXEMPT_AUTHOR:
        return []
    if not concerned or documented(paths) or LABEL in {label.strip() for label in labels}:
        return []
    shown = ", ".join(concerned[:5]) + (", ..." if len(concerned) > 5 else "")
    return [
        f"The pull request changes what users see or configure ({shown}) but nothing "
        f"under {DOCS_PREFIX}. Update the documentation in this pull request; if no page is "
        f"concerned, ask the maintainer to add the `{LABEL}` label."
    ]


def changed_paths(base: str, head: str) -> list[str]:
    """Paths changed by the pull request: its head against the merge base with the base."""
    result = subprocess.run(  # noqa: S603
        ["git", "diff", "--name-only", "-z", f"{base}...{head}"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: check_docs_updated.py <base-sha> <head-sha>\n")
        return 2
    paths = changed_paths(args[0], args[1])
    labels = os.environ.get("PR_LABELS", "").split(",")
    author = os.environ.get("PR_AUTHOR", "")
    found = problems(paths, labels, author)
    if found:
        sys.stderr.writelines(f"{line}\n" for line in found)
        return 1
    concerned = user_facing(paths)
    if concerned and author == EXEMPT_AUTHOR and not documented(paths):
        sys.stdout.write(f"Exempted: pull request of {EXEMPT_AUTHOR} ({len(concerned)} files).\n")
    elif concerned and not documented(paths):
        sys.stdout.write(f"Exempted by the `{LABEL}` label ({len(concerned)} user-facing files).\n")
    elif concerned:
        sys.stdout.write(f"{len(concerned)} user-facing files changed, with documentation.\n")
    else:
        sys.stdout.write("No user-facing change.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
