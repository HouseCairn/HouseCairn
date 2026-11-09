import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django.utils import translation

from housecairn.core import translations

SAMPLE = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

#: a.py:1
msgid "Done"
msgstr "Fait"

#, fuzzy
msgid "Postponed"
msgstr "Reporté"

msgctxt "verb"
msgid "Skip"
msgstr ""

msgid "One task"
msgid_plural "%d tasks"
msgstr[0] "Une tâche"
msgstr[1] ""

msgid ""
"Long "
"text"
msgstr ""
"Texte "
"long"

#~ msgid "Old"
#~ msgstr ""
"""


@pytest.fixture
def source_copy(tmp_path: Path, settings: Any) -> Iterator[Path]:
    """A copy of the application's code and catalogs, for the tests that run `makemessages`.

    `makemessages` rewrites the catalogs it works on: on the source tree, two xdist
    workers would rewrite the same `django.po` at once, and a test would edit a tracked
    file. The copy gives each test its own catalogs; the source tree comes out unchanged.
    """
    base = Path(settings.BASE_DIR)
    locale_dirs = [Path(p) for p in settings.LOCALE_PATHS]
    tracked = {path: path.read_bytes() for d in locale_dirs for path in d.rglob("*.po")}
    copy = tmp_path / base.name
    shutil.copytree(base, copy, ignore=shutil.ignore_patterns("__pycache__", "static", "*.mo"))
    settings.BASE_DIR = copy
    settings.LOCALE_PATHS = [copy / d.relative_to(base) for d in locale_dirs]
    yield copy
    assert {path: path.read_bytes() for path in tracked} == tracked
    assert not [path for d in locale_dirs for path in d.rglob("*.pot")]


def test_parser_and_problems(tmp_path: Path) -> None:
    entries = translations.parse_po(SAMPLE)
    assert [e.msgid for e in entries] == ["", "Done", "Postponed", "Skip", "One task", "Long text"]
    assert entries[3].msgctxt == "verb"
    assert entries[5].msgstrs == ["Texte long"]
    path = tmp_path / "django.po"
    path.write_text(SAMPLE, encoding="utf-8")
    assert translations.untranslated(path) == [
        "fuzzy: 'Postponed'",
        "untranslated: 'Skip'",
        "untranslated: 'One task'",
    ]


def test_missing_catalog_is_reported(tmp_path: Path) -> None:
    assert translations.untranslated(tmp_path / "none.po") == ["none.po: catalog is missing"]


def test_shipped_catalogs_are_complete() -> None:
    call_command("check_translations")


def test_command_fails_on_problems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "django.po"
    path.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(translations, "po_files", lambda: iter([("fr", path)]))
    with pytest.raises(CommandError, match="untranslated: 'Skip'"):
        call_command("check_translations")


@pytest.mark.skipif(shutil.which("xgettext") is None, reason="needs GNU gettext")
def test_every_source_string_is_in_the_catalog(source_copy: Path) -> None:
    assert all(path.is_relative_to(source_copy) for _lang, path in translations.po_files())
    before = {p: p.read_bytes() for _lang, p in translations.po_files()}
    call_command("check_translations", "--sources")
    assert {p: p.read_bytes() for _lang, p in translations.po_files()} == before


def test_sources_scan_needs_gettext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="gettext"):
        translations.missing_from_catalog("fr", Path("unused.po"))


def test_catalogs_have_no_dates_or_locations() -> None:
    """Two branches that add a string must merge without a conflict (docs/adr/0013)."""
    catalogs = [path for _lang, path in translations.po_files()]
    catalogs += (Path(settings.BASE_DIR).parents[1] / "docs" / "locale").rglob("*.po")
    assert len(catalogs) > 50  # the application's and the documentation's
    for path in catalogs:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^#:|POT-Creation-Date", text, re.MULTILINE), path


@pytest.mark.skipif(shutil.which("xgettext") is None, reason="needs GNU gettext")
def test_regenerating_the_catalog_changes_nothing(
    source_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(source_copy)
    for language, path in translations.po_files():
        assert path.is_relative_to(source_copy)
        before = path.read_bytes()
        with translations._restored(path):
            call_command(
                "makemessages", locale=[language], ignore_patterns=["static/*"], verbosity=0
            )
            assert path.read_bytes() == before


@pytest.mark.django_db
def test_french_is_served(client: Client) -> None:
    """The compiled catalog is there: `compilemessages` ran, in CI as in the image."""
    response = client.get(reverse("account_login"), HTTP_ACCEPT_LANGUAGE="fr")
    assert response.headers["Content-Language"] == "fr"
    assert '<html lang="fr">' in response.text
    assert "Se connecter" in response.text
    with translation.override("fr"):
        assert translation.gettext("Sign in") == "Se connecter"
