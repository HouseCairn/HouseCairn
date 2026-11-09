"""Fold the release notes fragments into the release notes page (docs/adr/0016).

Usage:
  python scripts/release_notes.py list                    # the fragments waiting
  python scripts/release_notes.py fold                    # into the Unreleased section
  python scripts/release_notes.py fold --version 0.1.0    # and name it after the version

Each pull request adds its own fragment, `docs/release-notes/unreleased/<category>/
<topic>.md`, with its French catalog under `docs/locale/fr/LC_MESSAGES/` (same path,
`.po`): two pull requests never edit the same file. The release notes page shows
them with the `release-fragments` directive, one per category.

`fold`, run when a version is published, writes the text of every fragment into
`docs/release-notes.md`, in place of the directive of its category (so the page
reads the same), adds its translations to the catalog of the page, and removes the
fragment and its catalog. With `--version`, the Unreleased section takes the name
of the version, loses its directives, and a new, empty Unreleased section with the
directives is added above it. Then run `scripts/build_docs.py --update-catalogs`
and translate the heading of the version in `release-notes.po`.
"""

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_DIR / "docs"
PAGE = DOCS_DIR / "release-notes.md"
FRAGMENTS_DIR = DOCS_DIR / "release-notes" / "unreleased"
LOCALE_DIR = DOCS_DIR / "locale"
LANGUAGES = ("fr",)
UNRELEASED = "## Unreleased"
# The categories, in the order of the page, with their heading.
CATEGORIES = {"new": "### New", "fixed": "### Fixed", "upgrade": "### Upgrade notes"}
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
# A Markdown link or image target: ](target) or ](target "title").
LINK_TARGET = re.compile(r"\]\((?P<target>[^)\s#]+)")


def relinked(text: str, fragment: Path) -> str:
    """The text with its relative links made relative to the release notes page."""
    base = fragment.parent.relative_to(DOCS_DIR).as_posix()

    def replace(match: re.Match[str]) -> str:
        target = match["target"]
        if "://" in target or target.startswith(("/", "mailto:")):
            return match.group(0)
        return "](" + posixpath.normpath(posixpath.join(base, target))

    return LINK_TARGET.sub(replace, text)


def directive(category: str) -> str:
    return f"```{{release-fragments}} {category}\n```\n"


def fragments(category: str, root: Path = FRAGMENTS_DIR) -> list[Path]:
    return sorted((root / category).glob("*.md"))


def body(fragment: Path) -> str:
    """The text of a fragment, without its front matter."""
    text = FRONT_MATTER.sub("", fragment.read_text(encoding="utf-8"))
    return relinked(text.strip("\n"), fragment) + "\n\n"


def catalog_of(fragment: Path, language: str) -> Path:
    name = fragment.relative_to(DOCS_DIR).with_suffix(".po")
    return LOCALE_DIR / language / "LC_MESSAGES" / name


def unreleased_section(page: str) -> tuple[int, int]:
    """Start and end of the Unreleased section: from its heading to the next `## `."""
    start = page.index(f"\n{UNRELEASED}\n") + 1
    following = page.find("\n## ", start + len(UNRELEASED))
    return start, len(page) if following == -1 else following + 1


def folded(page: str, texts: dict[str, list[str]], version: str | None = None) -> str:
    """The page with the texts of the fragments in place of the directives."""
    start, end = unreleased_section(page)
    section = page[start:end]
    for category in CATEGORIES:
        marker = directive(category)
        if marker not in section:
            if texts.get(category):
                raise ValueError(f"No `release-fragments {category}` in the Unreleased section.")
            continue
        kept = "" if version else marker + "\n"
        replacement = "".join(texts.get(category, [])) + kept
        section = section.replace(marker + "\n", replacement, 1)
    if version:
        fresh = UNRELEASED + "\n\n"
        fresh += "".join(f"{CATEGORIES[c]}\n\n{directive(c)}\n" for c in CATEGORIES)
        section = fresh + section.replace(UNRELEASED, f"## {version}", 1)
    return page[:start] + section + page[end:]


def fold(version: str | None) -> int:
    found = {category: fragments(category) for category in CATEGORIES}
    texts = {category: [body(path) for path in paths] for category, paths in found.items()}
    PAGE.write_text(folded(PAGE.read_text(encoding="utf-8"), texts, version), encoding="utf-8")
    for language in LANGUAGES:
        page_catalog = LOCALE_DIR / language / "LC_MESSAGES" / "release-notes.po"
        catalogs = []
        for paths in found.values():
            for path in paths:
                catalog = catalog_of(path, language)
                if catalog.exists():
                    # The same links as in the page, in the msgid and in the translation.
                    text = relinked(catalog.read_text(encoding="utf-8"), path)
                    catalog.write_text(text, encoding="utf-8")
                    catalogs.append(str(catalog))
        if catalogs:
            command = ["msgcat", "--use-first", "--no-wrap", "--no-location", str(page_catalog)]
            subprocess.run([*command, *catalogs, "-o", str(page_catalog)], check=True)  # noqa: S603
    for paths in found.values():
        for path in paths:
            path.unlink()
            for language in LANGUAGES:
                catalog_of(path, language).unlink(missing_ok=True)
    for language in LANGUAGES:
        shutil.rmtree(catalog_of(FRAGMENTS_DIR / "x.md", language).parent, ignore_errors=True)
    count = sum(len(paths) for paths in found.values())
    sys.stdout.write(f"{count} fragments folded into {PAGE.relative_to(REPO_DIR)}.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    fold_parser = commands.add_parser("fold")
    fold_parser.add_argument("--version", help="Name the folded section after this version.")
    args = parser.parse_args(argv)
    if args.command == "list":
        for category in CATEGORIES:
            for path in fragments(category):
                sys.stdout.write(f"{category}: {path.relative_to(REPO_DIR)}\n")
        return 0
    if shutil.which("msgcat") is None:
        sys.stderr.write("GNU gettext (msgcat) is required.\n")
        return 2
    return fold(args.version)


if __name__ == "__main__":
    sys.exit(main())
