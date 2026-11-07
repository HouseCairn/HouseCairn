"""Scripts that build and check the documentation site (scripts/, docs/adr/0016)."""

import json
from pathlib import Path

import pytest

from scripts import check_docs_design, check_docs_site, check_docs_updated

# check_docs_updated: the documentation changes with the code


def test_view_without_docs_fails() -> None:
    found = check_docs_updated.problems(
        ["src/housecairn/homes/views.py", "tests/test_homes.py"], []
    )
    assert len(found) == 1
    assert "no-docs-needed" in found[0]


@pytest.mark.parametrize(
    "path",
    [
        "src/housecairn/homes/views.py",
        "src/housecairn/homes/urls.py",
        "src/housecairn/homes/api.py",
        "src/housecairn/urls.py",
        "src/housecairn/settings.py",
        "src/housecairn/templates/homes/home_list.html",
        "src/housecairn/templates/account/login.html",
        "compose.yaml",
        "deploy/production.env.example",
    ],
)
def test_user_facing_files_need_docs(path: str) -> None:
    assert check_docs_updated.user_facing([path]) == [path]
    assert check_docs_updated.problems([path], []) != []


@pytest.mark.parametrize(
    "paths",
    [
        # Dependabot: dependencies, workflows, the Dockerfile.
        ["pyproject.toml", "uv.lock"],
        [".github/workflows/ci.yml", "Dockerfile", ".github/dependabot.yml"],
        # Tests, scripts, models and services are not user-facing by themselves.
        ["tests/test_homes.py", "scripts/check_signoff.py"],
        ["src/housecairn/homes/services.py", "src/housecairn/homes/models.py"],
        ["src/housecairn/locale/fr/LC_MESSAGES/django.po"],
        ["docs/screens/home.md"],
        [],
    ],
)
def test_other_changes_pass(paths: list[str]) -> None:
    assert check_docs_updated.problems(paths, []) == []


def test_docs_change_satisfies_the_rule() -> None:
    paths = ["src/housecairn/homes/views.py", "docs/screens/home.md"]
    assert check_docs_updated.problems(paths, []) == []


def test_label_is_the_escape_hatch() -> None:
    paths = ["src/housecairn/homes/views.py"]
    assert check_docs_updated.problems(paths, ["bug", "no-docs-needed"]) == []
    assert check_docs_updated.problems(paths, ["no-docs-needed-really"]) != []
    assert check_docs_updated.problems(paths, [""]) != []


def test_dependabot_is_exempt_for_its_own_pull_requests() -> None:
    paths = ["compose.yaml"]
    assert check_docs_updated.problems(paths, [], "") != []
    assert check_docs_updated.problems(paths, [], "dependabot[bot]") == []


@pytest.mark.parametrize(
    "author",
    ["Robvred", "dependabot", "dependabot[bot]-fork", "renovate[bot]", "github-actions[bot]"],
)
def test_no_other_author_is_exempt(author: str) -> None:
    assert check_docs_updated.problems(["compose.yaml"], [], author) != []


def test_main_reads_the_author(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_docs_updated, "changed_paths", lambda base, head: ["compose.yaml"])
    monkeypatch.setenv("PR_LABELS", "")
    monkeypatch.setenv("PR_AUTHOR", "dependabot[bot]")
    assert check_docs_updated.main(["base", "head"]) == 0
    assert "Exempted" in capsys.readouterr().out
    monkeypatch.setenv("PR_AUTHOR", "Robvred")
    assert check_docs_updated.main(["base", "head"]) == 1
    monkeypatch.delenv("PR_AUTHOR")
    assert check_docs_updated.main(["base", "head"]) == 1


def test_main_reads_labels_and_diff(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        check_docs_updated, "changed_paths", lambda base, head: ["src/housecairn/homes/views.py"]
    )
    monkeypatch.setenv("PR_LABELS", "")
    assert check_docs_updated.main(["base", "head"]) == 1
    assert "nothing under docs/" in capsys.readouterr().err
    monkeypatch.setenv("PR_LABELS", "enhancement,no-docs-needed")
    assert check_docs_updated.main(["base", "head"]) == 0
    assert check_docs_updated.main(["only-one-argument"]) == 2


# check_docs_site: no external resource, links, API coverage

SCHEMA = {
    "paths": {
        "/api/v1/homes/": {"get": {"operationId": "homes_list"}},
        "/api/v1/homes/{id}/": {
            "get": {"operationId": "homes_retrieve"},
            "patch": {"operationId": "homes_partial_update"},
            "parameters": [],
        },
    }
}
PAGE = """<!doctype html><html><head>
<link rel="stylesheet" href="_static/site.css">
<link rel="canonical" href="https://docs.example.com/page/">
<link rel="alternate" hreflang="fr" href="https://docs.example.com/fr/page/">
<script src="_static/site.js" defer></script></head>
<body><h1 id="title">Title</h1>
<a href="https://example.org/">outgoing link</a>
<a href="#title">same page</a> <a href="other/#section">other page</a>
{extra}</body></html>"""
OTHER = '<!doctype html><html><body><h2 id="section">Section</h2></body></html>'


def make_site(tmp_path: Path, extra: str = "", css: str = "body { color: black; }") -> Path:
    site = tmp_path / "site"
    (site / "_static").mkdir(parents=True)
    (site / "other").mkdir()
    (site / "index.html").write_text(PAGE.format(extra=extra), encoding="utf-8")
    (site / "other" / "index.html").write_text(OTHER, encoding="utf-8")
    (site / "_static" / "site.css").write_text(css, encoding="utf-8")
    (site / "_static" / "site.js").write_text("", encoding="utf-8")
    for prefix in ("", "fr/"):
        reference = site / prefix / "api" / "reference"
        reference.mkdir(parents=True)
        ids = "".join(f'<div id="operation-{op}"></div>' for op in operation_ids())
        (reference / "index.html").write_text(f"<html><body>{ids}</body></html>", encoding="utf-8")
    return site


def operation_ids() -> list[str]:
    return check_docs_site.operation_ids(SCHEMA)


def schema_file(tmp_path: Path) -> Path:
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return path


def test_clean_site_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = make_site(tmp_path)
    assert check_docs_site.external_resources(site) == []
    assert check_docs_site.broken_links(site) == []
    assert check_docs_site.main([str(site), str(schema_file(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "External resources: 0" in out
    assert "3/3 operations documented" in out


@pytest.mark.parametrize(
    "extra",
    [
        '<script src="https://cdn.example.net/lib.js"></script>',
        '<script src="//cdn.example.net/lib.js"></script>',
        '<link rel="stylesheet" href="https://fonts.example.net/css?family=Font">',
        '<link rel="preload" href="https://fonts.example.net/font.woff2" as="font">',
        '<link rel="icon" href="HTTP://example.net/favicon.ico">',
        '<img src="https://img.example.net/pixel.png">',
        '<img src="local.png" srcset="local.png 1x, https://img.example.net/2x.png 2x">',
        '<iframe src="https://example.net/embed"></iframe>',
        '<video poster="https://example.net/poster.png"></video>',
        '<object data="https://example.net/file.pdf"></object>',
        '<div style="background: url(https://example.net/bg.png)"></div>',
        '<style>@import "https://fonts.example.net/css";</style>',
        '<svg><image href="https://example.net/image.svg"></image></svg>',
        '<base href="https://example.net/">',
        '<meta http-equiv="refresh" content="0; url=https://example.net/elsewhere">',
        '<META HTTP-EQUIV="Refresh" CONTENT="5;URL=\'//example.net/x\'">',
    ],
)
def test_external_resource_is_found(tmp_path: Path, extra: str) -> None:
    site = make_site(tmp_path, extra)
    assert len(check_docs_site.external_resources(site)) == 1
    assert check_docs_site.main([str(site), str(schema_file(tmp_path))]) == 1


def test_external_resource_in_css_is_found(tmp_path: Path) -> None:
    css = "@font-face { src: url('https://fonts.example.net/f.woff2'); }"
    site = make_site(tmp_path, css=css)
    assert check_docs_site.external_resources(site) == [
        "_static/site.css: https://fonts.example.net/f.woff2"
    ]


@pytest.mark.parametrize(
    "script",
    [
        'fetch("https://example.net/collect", {method: "POST"});',
        "fetch( 'https://example.net/a' )",
        "fetch(`//example.net/a`)",
        'import("https://cdn.example.net/module.js");',
        'const socket = new WebSocket("wss://example.net/socket");',
        'new EventSource("https://example.net/events")',
        'const r = new XMLHttpRequest(); r.open("GET", "https://example.net/x");',
    ],
)
def test_external_call_in_script_is_found(tmp_path: Path, script: str) -> None:
    site = make_site(tmp_path)
    (site / "_static" / "site.js").write_text(script, encoding="utf-8")
    assert len(check_docs_site.external_resources(site)) == 1
    assert check_docs_site.main([str(site), str(schema_file(tmp_path))]) == 1


@pytest.mark.parametrize(
    "script",
    [
        'fetch("searchindex.json");',
        'fetch(DOCUMENTATION_OPTIONS.URL_ROOT + "searchindex.json")',
        'import("./module.js")',
        'new WebSocket(location.origin.replace("http", "ws"))',
        'const url = "https://example.net/docs"; link.href = url;',
    ],
)
def test_local_or_dynamic_calls_in_script_pass(tmp_path: Path, script: str) -> None:
    site = make_site(tmp_path)
    (site / "_static" / "site.js").write_text(script, encoding="utf-8")
    assert check_docs_site.external_resources(site) == []


def test_relative_refresh_and_base_are_not_external(tmp_path: Path) -> None:
    extra = '<meta http-equiv="refresh" content="0; url=other/"><meta charset="utf-8">'
    site = make_site(tmp_path, extra)
    assert check_docs_site.external_resources(site) == []


def test_outgoing_links_are_not_resources(tmp_path: Path) -> None:
    site = make_site(tmp_path, '<a href="https://example.net/">elsewhere</a>')
    assert check_docs_site.external_resources(site) == []


def test_broken_links_are_found(tmp_path: Path) -> None:
    extra = '<a href="missing/">gone</a> <a href="other/#nowhere">anchor</a> <img src="nope.png">'
    site = make_site(tmp_path, extra)
    found = check_docs_site.broken_links(site)
    assert len(found) == 3
    assert any("no such anchor" in line for line in found)
    assert check_docs_site.main([str(site), str(schema_file(tmp_path))]) == 1


def test_missing_api_operation_is_found(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    page = site / "fr" / "api" / "reference" / "index.html"
    page.write_text(page.read_text().replace('id="operation-homes_list"', ""), encoding="utf-8")
    total, missing = check_docs_site.missing_operations(site, schema_file(tmp_path))
    assert total == 3
    assert missing == ["fr: homes_list"]


def test_missing_site_is_an_error(tmp_path: Path) -> None:
    assert check_docs_site.main([str(tmp_path / "nothing")]) == 2


# check_docs_design: contrast, focus and the pages of the site

WHITE = (255.0, 255.0, 255.0, 1.0)
BLACK = (0.0, 0.0, 0.0, 1.0)


def test_contrast_matches_wcag() -> None:
    assert check_docs_design.contrast(BLACK, WHITE) == pytest.approx(21.0)
    assert check_docs_design.contrast(WHITE, WHITE) == pytest.approx(1.0)
    # Slate on the page background of the tokens (docs/adr/0017).
    slate = (31.0, 58.0, 61.0, 1.0)
    page = (247.0, 245.0, 241.0, 1.0)
    assert check_docs_design.contrast(slate, page) == pytest.approx(11.14, abs=0.01)


def test_translucent_layers_are_blended() -> None:
    half_black = (0.0, 0.0, 0.0, 0.5)
    grey = check_docs_design.flatten([half_black])
    assert grey[:3] == pytest.approx((127.5, 127.5, 127.5))
    # Nearest layer first: an opaque layer hides what is under it.
    assert check_docs_design.flatten([BLACK, WHITE]) == BLACK


def test_large_text() -> None:
    assert check_docs_design.is_large(24, 400)
    assert check_docs_design.is_large(18.66, 700)
    assert not check_docs_design.is_large(18.66, 600)
    assert not check_docs_design.is_large(16, 800)


def _sample(color: tuple[float, ...], size: float = 16, **extra: object) -> dict[str, object]:
    return {
        "element": "p",
        "text": "text",
        "color": list(color),
        "layers": [list(WHITE)],
        "unknown": False,
        "size": size,
        "weight": 400,
        **extra,
    }


def test_text_failures() -> None:
    grey = (150.0, 150.0, 150.0, 1.0)  # 2.96:1 on white
    mid = (118.0, 118.0, 118.0, 1.0)  # 4.54:1 on white
    failures, unknown = check_docs_design.text_failures(
        "light /",
        [
            _sample(BLACK),
            _sample(mid),
            _sample(grey),
            _sample(grey, size=32),
            _sample(grey, unknown=True),
        ],
    )
    assert [(f.ratio < 3, f.needed) for f in failures] == [(True, 4.5), (True, 3.0)]
    assert unknown == 1
    assert "light /: p 'text': 2.96:1 (needs 4.5:1)" in str(failures[0])


@pytest.mark.parametrize(
    ("focus", "problem"),
    [
        ({"style": "solid", "width": 3, "color": list(BLACK)}, None),
        ({"style": "none", "width": 0, "color": list(BLACK)}, "no visible focus outline"),
        ({"style": "solid", "width": 1, "color": list(BLACK)}, "no visible focus outline"),
        ({"style": "solid", "width": 3, "color": [230, 230, 230, 1]}, "(needs 3:1)"),
    ],
)
def test_focus_must_be_visible(focus: dict[str, object], problem: str | None) -> None:
    found = check_docs_design.focus_problem(
        "light /", {"element": "a", "layers": [list(WHITE)], **focus}
    )
    assert (found is None) if problem is None else (found is not None and problem in found)


def test_pages_of_the_site(tmp_path: Path) -> None:
    for page in ("", "guides/", "fr/", "fr/guides/", "_static/x/"):
        (tmp_path / page).mkdir(parents=True, exist_ok=True)
        (tmp_path / page / "index.html").write_text("<p>x</p>", encoding="utf-8")
    assert sorted(check_docs_design.pages_of(tmp_path)) == ["", "fr/", "fr/guides/", "guides/"]


def test_design_check_needs_a_site(tmp_path: Path) -> None:
    assert check_docs_design.main([str(tmp_path)]) == 2
