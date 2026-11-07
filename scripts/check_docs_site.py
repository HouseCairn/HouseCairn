"""Check the built documentation site (docs/adr/0016).

1. No external resource: no script, style, font, image, frame or other
   resource loaded from another host, in the HTML and CSS of the site. Links
   (<a href>) to other sites are allowed.
2. Internal links: every relative link or resource of a page points to a file
   of the site, and its #anchor, if any, to an element of that page.
3. API coverage: the API reference of each language documents every
   operation of the OpenAPI schema the site was built from.

Usage: python scripts/check_docs_site.py [<site directory>] [<schema>]
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE = REPO_DIR / "docs" / "_build" / "site"
DEFAULT_SCHEMA = REPO_DIR / "docs" / "_generated" / "openapi.json"
LANGUAGE_PREFIXES = {"en": "", "fr": "fr/"}
API_PAGE = "api/reference/index.html"
MAX_LINES = 50
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# Attributes that make the browser fetch something, per element.
RESOURCE_ATTRIBUTES = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "frame": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "audio": ("src",),
    "video": ("src", "poster"),
    "track": ("src",),
    "input": ("src",),
    "image": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
}
# <link rel="..."> values that load something; others (canonical, alternate,
# index, search, next, prev...) only name another page.
LOADING_RELS = frozenset(
    {
        "stylesheet",
        "icon",
        "shortcut",
        "apple-touch-icon",
        "mask-icon",
        "manifest",
        "preload",
        "prefetch",
        "modulepreload",
        "preconnect",
        "dns-prefetch",
        "prerender",
    }
)
CSS_EXTERNAL = re.compile(
    r"""(?:url\(\s*['"]?|@import\s+['"])\s*((?:https?:)?//[^'")\s]+)""", re.IGNORECASE
)


def is_external(url: str) -> bool:
    url = url.strip().lower()
    return url.startswith(("http://", "https://", "//"))


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.resources: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        for name in ("id", "name"):
            if values.get(name):
                self.ids.add(values[name])
        if "style" in values:
            self.styles.append(values["style"])
        if tag == "style":
            self._in_style = True
        for attribute in RESOURCE_ATTRIBUTES.get(tag, ()):
            if values.get(attribute):
                for url in _urls(attribute, values[attribute]):
                    self.resources.append((f"<{tag} {attribute}>", url))
        if tag == "link" and values.get("href"):
            rels = set(values.get("rel", "").lower().split())
            if rels & LOADING_RELS:
                self.resources.append((f"<link rel={values.get('rel')}>", values["href"]))
            else:
                self.links.append(values["href"])
        if tag in ("a", "area") and values.get("href"):
            self.links.append(values["href"])

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)


def _urls(attribute: str, value: str) -> list[str]:
    if attribute == "srcset":
        return [part.strip().split()[0] for part in value.split(",") if part.strip()]
    return [value]


def parse(path: Path) -> _Page:
    page = _Page()
    page.feed(path.read_text(encoding="utf-8"))
    page.close()
    return page


def external_resources(site: Path) -> list[str]:
    """`file: element url` for every resource of the site loaded from another host."""
    found = []
    for path in sorted(site.rglob("*.html")):
        page = parse(path)
        name = path.relative_to(site)
        found += [f"{name}: {what} {url}" for what, url in page.resources if is_external(url)]
        for css in page.styles:
            found += [f"{name}: inline style {url}" for url in CSS_EXTERNAL.findall(css)]
    for path in sorted(site.rglob("*.css")):
        css = path.read_text(encoding="utf-8")
        found += [f"{path.relative_to(site)}: {url}" for url in CSS_EXTERNAL.findall(css)]
    return found


def broken_links(site: Path) -> list[str]:
    """`file: url` for every relative link or resource that leads nowhere."""
    site = site.resolve()
    pages = {path.resolve(): parse(path) for path in sorted(site.rglob("*.html"))}
    broken = []
    for path, page in pages.items():
        for url in [*page.links, *(url for _, url in page.resources)]:
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or url.startswith(("mailto:", "data:")):
                continue
            target = path if not parts.path else (path.parent / unquote(parts.path)).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists() or site not in target.parents:
                broken.append(f"{path.relative_to(site)}: {url}")
                continue
            anchor = unquote(parts.fragment)
            if anchor and target.suffix == ".html":
                ids = pages[target].ids if target in pages else parse(target).ids
                if anchor not in ids:
                    broken.append(f"{path.relative_to(site)}: {url} (no such anchor)")
    return broken


def operation_ids(schema: dict[str, Any]) -> list[str]:
    ids = []
    for path, item in schema.get("paths", {}).items():
        for method in HTTP_METHODS:
            if method in item:
                ids.append(str(item[method].get("operationId", f"{method}-{path}")))
    return ids


def missing_operations(site: Path, schema_path: Path) -> tuple[int, list[str]]:
    """Number of operations, and `language: operation` missing from each reference."""
    expected = operation_ids(json.loads(schema_path.read_text(encoding="utf-8")))
    missing = []
    for language, prefix in LANGUAGE_PREFIXES.items():
        page = site / prefix / API_PAGE
        ids = parse(page).ids if page.exists() else set()
        missing += [f"{language}: {op}" for op in expected if f"operation-{op}" not in ids]
    return len(expected), missing


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    site = Path(args[0]) if args else DEFAULT_SITE
    schema = Path(args[1]) if len(args) > 1 else DEFAULT_SCHEMA
    if not (site / "index.html").exists():
        sys.stderr.write(f"No site in {site}: build it first (scripts/build_docs.py).\n")
        return 2
    failed = False
    pages = len(list(site.rglob("*.html")))

    external = external_resources(site)
    if external:
        failed = True
        sys.stderr.write("External resources in the site (docs/adr/0016):\n")
        sys.stderr.writelines(f"- {line}\n" for line in external[:MAX_LINES])
    else:
        sys.stdout.write(f"External resources: 0 in {pages} HTML files and their CSS.\n")

    broken = broken_links(site)
    if broken:
        failed = True
        sys.stderr.write("Broken internal links:\n")
        sys.stderr.writelines(f"- {line}\n" for line in broken[:MAX_LINES])
        sys.stderr.write(f"({len(broken)} in total)\n")
    else:
        sys.stdout.write(f"Internal links: all resolve, in {pages} HTML files.\n")

    total, missing = missing_operations(site, schema)
    if missing or total == 0:
        failed = True
        sys.stderr.write(f"API reference: operations missing (of {total}):\n")
        sys.stderr.writelines(f"- {line}\n" for line in missing)
    else:
        languages = ", ".join(LANGUAGE_PREFIXES)
        sys.stdout.write(f"API reference: {total}/{total} operations documented ({languages}).\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
