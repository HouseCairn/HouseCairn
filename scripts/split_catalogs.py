"""Split the single application catalog into one catalog per app (docs/adr/0013).

Usage (needs GNU gettext, run from the repository root):
  uv run python scripts/split_catalogs.py

The former catalog, `src/housecairn/locale/<language>/LC_MESSAGES/django.po`, is
split by the project's `makemessages`: every app catalog starts from the former
catalog merged with the app's own (the former one wins, it is the newer), then
`makemessages` keeps in each only the strings of that app, with their
translations, and drops the catalog of an app that has no string. The former
catalog is then removed.

It can be run again at any time, for instance after merging a branch that
still added strings to the former catalog: the strings of that catalog go to
the catalog of their app, and the former catalog goes again. Without a former
catalog it only regenerates the app catalogs.

It fails unless the pairs of msgid and translation are the same before and
after: the former catalog against all the app catalogs together (a string used
by two apps is in both, with the same translation).
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "housecairn.settings")
# Only `makemessages` runs: no secret key is needed, as for `compilemessages` (Dockerfile).
os.environ.setdefault("DEBUG", "true")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from housecairn.core import translations  # noqa: E402

Pair = tuple[str | None, str, str | None, tuple[str, ...], bool]
APPS_DIR = Path(settings.BASE_DIR)
FORMER_DIR = APPS_DIR / "locale"


def pairs(*catalogs: Path) -> set[Pair]:
    """Every entry of the catalogs, header excluded: msgid, plural, translations, fuzzy."""
    found = set()
    for path in catalogs:
        for entry in translations.parse_po(path.read_text(encoding="utf-8")):
            if entry.msgid:
                found.add(
                    (
                        entry.msgctxt,
                        entry.msgid,
                        entry.msgid_plural,
                        tuple(entry.msgstrs),
                        entry.fuzzy,
                    )
                )
    return found


def apps() -> list[str]:
    return sorted(path.parent.name for path in APPS_DIR.glob("*/apps.py"))


def seed(former: Path, language: str) -> None:
    """Start every app catalog from the former catalog, merged with the app's own."""
    for app in apps():
        target = translations.catalog_path(APPS_DIR / app / "locale", language)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            command = ["msgcat", "--use-first", "--no-wrap", "--no-location", str(former)]
            command += [str(target), "-o", str(target)]
            subprocess.run(command, check=True)  # noqa: S603
        else:
            shutil.copyfile(former, target)


def drop_catalogs_without_strings(language: str) -> None:
    """`makemessages` left a template (`django.pot`) next to each catalog with strings."""
    for app in apps():
        locale_dir = APPS_DIR / app / "locale"
        template = locale_dir / "django.pot"
        if template.exists():
            template.unlink()
        elif locale_dir.exists():
            translations.catalog_path(locale_dir, language).unlink(missing_ok=True)
            for directory in sorted(locale_dir.rglob("*"), reverse=True):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            if not any(locale_dir.iterdir()):
                locale_dir.rmdir()


def show(title: str, entries: set[Pair]) -> None:
    sys.stderr.write(f"{title} ({len(entries)}):\n")
    sys.stderr.writelines(
        f"- {entry[1]!r} -> {entry[3]!r}\n" for entry in sorted(entries, key=repr)
    )


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    if shutil.which("msgcat") is None:
        sys.stderr.write("GNU gettext (msgcat, xgettext) is required.\n")
        return 2
    status = 0
    for language in translations.languages():
        former = translations.catalog_path(FORMER_DIR, language)
        before = pairs(former) if former.exists() else pairs(*translations.app_catalogs(language))
        if former.exists():
            seed(former, language)
        translations.run_makemessages(language, keep_pot=True)
        drop_catalogs_without_strings(language)
        former.unlink(missing_ok=True)
        catalogs = translations.app_catalogs(language)
        after = pairs(*catalogs)
        names = ", ".join(translations.app_of(path) for path in catalogs)
        if before == after:
            sys.stdout.write(
                f"{language}: {len(after)} translations, the same before and after, "
                f"in {len(catalogs)} catalogs ({names}).\n"
            )
        else:
            show(f"{language}: lost", before - after)
            show(f"{language}: gained", after - before)
            status = 1
    if FORMER_DIR.exists():
        shutil.rmtree(FORMER_DIR)
    return status


if __name__ == "__main__":
    sys.exit(main())
