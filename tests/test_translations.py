import shutil
from pathlib import Path

import pytest
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
def test_every_source_string_is_in_the_catalog() -> None:
    before = {p: p.read_bytes() for _lang, p in translations.po_files()}
    call_command("check_translations", "--sources")
    assert {p: p.read_bytes() for _lang, p in translations.po_files()} == before


def test_sources_scan_needs_gettext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="gettext"):
        translations.missing_from_catalog("fr", Path("unused.po"))


@pytest.mark.django_db
def test_french_is_served(client: Client) -> None:
    response = client.get(reverse("index"), HTTP_ACCEPT_LANGUAGE="fr")
    assert response.headers["Content-Language"] == "fr"
    assert '<html lang="fr">' in response.text
    with translation.override("fr"):
        assert translation.gettext("Sign in") == "Se connecter"
