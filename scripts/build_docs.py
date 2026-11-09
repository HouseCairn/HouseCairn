"""Build the documentation site, strictly, in English and French (docs/adr/0016).

Usage:
  python scripts/build_docs.py                    # site in docs/_build/site
  python scripts/build_docs.py --update-catalogs  # refresh docs/locale/fr catalogs
  python scripts/build_docs.py --linkcheck        # check the external links

The English site is at the root of docs/_build/site, the French one under
fr/. Any Sphinx warning fails the build (-W -n), and so does a French catalog
that lags behind its page. Run it with the `docs` dependency group:
`uv run --group docs python scripts/build_docs.py`.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from housecairn.core.translations import parse_po

REPO_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_DIR / "docs"
BUILD_DIR = DOCS_DIR / "_build"
SITE_DIR = BUILD_DIR / "site"
GETTEXT_DIR = BUILD_DIR / "gettext"
LOCALE_DIR = DOCS_DIR / "locale"
BASE_URL = "https://docs.housecairn.app/"
TRANSLATIONS = {"fr": "fr/"}
POT_CREATION_DATE = re.compile(r'^"POT-Creation-Date:[^\n]*\\n"\n', re.MULTILINE)
STRICT = ["-W", "--keep-going", "-n", "-q"]
# The decision records are in English only (docs/adr/0016): no catalog for them.
UNTRANSLATED_DIRS = ("adr",)


def sphinx(builder: str, output: Path, *options: str, name: str | None = None) -> None:
    # Pickled environments stay outside the published site.
    doctrees = BUILD_DIR / "doctrees" / (name or builder)
    command = [sys.executable, "-m", "sphinx", "-b", builder, *STRICT, "-d", str(doctrees)]
    command += list(options)
    command += [str(DOCS_DIR), str(output)]
    print("$", " ".join(command[2:]), flush=True)  # noqa: T201
    subprocess.run(command, check=True, cwd=REPO_DIR)  # noqa: S603


def catalog_keys(path: Path) -> set[tuple[str | None, str]]:
    return {entry.key for entry in parse_po(path.read_text(encoding="utf-8")) if entry.msgid}


def stale_catalogs(language: str) -> list[str]:
    """Pages whose catalog misses one of their strings, or keeps a removed one."""
    problems = []
    for template in sorted(GETTEXT_DIR.rglob("*.pot")):
        name = template.relative_to(GETTEXT_DIR).with_suffix(".po")
        if name.parts[0] in UNTRANSLATED_DIRS:
            continue
        catalog = LOCALE_DIR / language / "LC_MESSAGES" / name
        if not catalog.exists():
            problems.append(f"{catalog.relative_to(REPO_DIR)}: missing")
            continue
        expected, present = catalog_keys(template), catalog_keys(catalog)
        if expected - present:
            problems.append(f"{catalog.relative_to(REPO_DIR)}: {len(expected - present)} new")
        if present - expected:
            problems.append(f"{catalog.relative_to(REPO_DIR)}: {len(present - expected)} removed")
    return problems


def drop_creation_dates(language: str) -> None:
    """Remove `POT-Creation-Date`: it changes at every run and conflicts between branches."""
    for path in (LOCALE_DIR / language / "LC_MESSAGES").rglob("*.po"):
        text = path.read_text(encoding="utf-8")
        stripped = POT_CREATION_DATE.sub("", text)
        if stripped != text:
            path.write_text(stripped, encoding="utf-8")


def count_pages(root: Path, exclude: Path | None = None) -> int:
    pages = [p for p in root.rglob("index.html") if exclude is None or exclude not in p.parents]
    return len(pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation site.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--update-catalogs", action="store_true")
    group.add_argument("--linkcheck", action="store_true")
    args = parser.parse_args(argv)

    if args.linkcheck:
        sphinx("linkcheck", BUILD_DIR / "linkcheck")
        return 0

    sphinx("gettext", GETTEXT_DIR)
    if args.update_catalogs:
        for language in TRANSLATIONS:
            command = [sys.executable, "-m", "sphinx_intl", "update", "-p", str(GETTEXT_DIR)]
            command += ["-d", str(LOCALE_DIR), "-l", language, "-w", "0"]
            subprocess.run(command, check=True, cwd=REPO_DIR)  # noqa: S603
            for directory in UNTRANSLATED_DIRS:
                shutil.rmtree(LOCALE_DIR / language / "LC_MESSAGES" / directory, ignore_errors=True)
            drop_creation_dates(language)
        return 0
    problems = [p for language in TRANSLATIONS for p in stale_catalogs(language)]
    if problems:
        sys.stderr.write(
            "Translation catalogs out of date; run "
            "`python scripts/build_docs.py --update-catalogs`:\n"
        )
        sys.stderr.writelines(f"- {problem}\n" for problem in problems)
        return 1

    shutil.rmtree(SITE_DIR, ignore_errors=True)
    sphinx("dirhtml", SITE_DIR, "-D", "language=en", name="en")
    counts = {"en": count_pages(SITE_DIR, exclude=SITE_DIR / "fr")}
    for language, prefix in TRANSLATIONS.items():
        output = SITE_DIR / prefix
        options = ["-D", f"language={language}", "-D", f"html_baseurl={BASE_URL}{prefix}"]
        sphinx("dirhtml", output, *options, name=language)
        counts[language] = count_pages(output)
    summary = ", ".join(f"{language}: {count} pages" for language, count in counts.items())
    print(f"Site built without warnings in {SITE_DIR.relative_to(REPO_DIR)} ({summary}).")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
