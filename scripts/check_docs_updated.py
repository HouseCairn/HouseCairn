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

The release notes are written in fragments (docs/release-notes/unreleased/README.md):
a pull request adds its own file and never edits the release notes page nor its
catalog (`COMMON_NOTES`), on which two pull requests would conflict. Only the fold
of the fragments at a release (scripts/release_notes.py), which removes them, edits
these files; a correction of a published entry needs the `release-notes-edit` label.
The rule applies once the base branch has the fragments directory.

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
COMMON_NOTES = ("docs/release-notes.md", "docs/locale/fr/LC_MESSAGES/release-notes.po")
FRAGMENTS_DIR = "docs/release-notes/unreleased/"
FRAGMENTS_README = FRAGMENTS_DIR + "README.md"
NOTES_LABEL = "release-notes-edit"
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


def notes_problems(
    paths: Iterable[str], deleted: Iterable[str], labels: set[str], fragments_on_base: bool
) -> list[str]:
    """A pull request that edits the shared release notes instead of adding a fragment."""
    edited = sorted(path for path in paths if path in COMMON_NOTES)
    folded = any(
        path.startswith(FRAGMENTS_DIR) and path.endswith(".md") and path != FRAGMENTS_README
        for path in deleted
    )
    if not fragments_on_base or not edited or folded or NOTES_LABEL in labels:
        return []
    return [
        f"The pull request edits {', '.join(edited)}. Add a release notes fragment instead, "
        f"`{FRAGMENTS_DIR}<category>/<topic>.md` with its own catalog (see {FRAGMENTS_README}): "
        f"two pull requests then never conflict. To correct a published entry, ask the "
        f"maintainer to add the `{NOTES_LABEL}` label."
    ]


def problems(
    paths: list[str],
    labels: Iterable[str],
    author: str = "",
    deleted: Iterable[str] = (),
    fragments_on_base: bool = True,
) -> list[str]:
    """Why the pull request fails the rules, or an empty list."""
    if author == EXEMPT_AUTHOR:
        return []
    labels = {label.strip() for label in labels}
    found = notes_problems(paths, deleted, labels, fragments_on_base)
    concerned = user_facing(paths)
    if not concerned or documented(paths) or LABEL in labels:
        return found
    shown = ", ".join(concerned[:5]) + (", ..." if len(concerned) > 5 else "")
    return [
        f"The pull request changes what users see or configure ({shown}) but nothing "
        f"under {DOCS_PREFIX}. Update the documentation in this pull request; if no page is "
        f"concerned, ask the maintainer to add the `{LABEL}` label.",
        *found,
    ]


def changed_paths(base: str, head: str, diff_filter: str | None = None) -> list[str]:
    """Paths changed by the pull request: its head against the merge base with the base."""
    command = ["git", "diff", "--name-only", "-z", f"{base}...{head}"]
    if diff_filter:
        command.append(f"--diff-filter={diff_filter}")
    result = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    return [path for path in result.stdout.split("\0") if path]


def exists_on(ref: str, path: str) -> bool:
    command = ["git", "cat-file", "-e", f"{ref}:{path}"]
    return subprocess.run(command, check=False, capture_output=True).returncode == 0  # noqa: S603


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("Usage: check_docs_updated.py <base-sha> <head-sha>\n")
        return 2
    paths = changed_paths(args[0], args[1])
    labels = os.environ.get("PR_LABELS", "").split(",")
    author = os.environ.get("PR_AUTHOR", "")
    deleted = changed_paths(args[0], args[1], diff_filter="D")
    found = problems(paths, labels, author, deleted, exists_on(args[0], FRAGMENTS_README))
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
