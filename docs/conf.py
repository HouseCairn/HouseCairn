"""Sphinx configuration of the documentation site (docs/adr/0016).

Build it with `uv run python scripts/build_docs.py`: English at the root of
the site, French under `/fr/`, both strict.
"""

import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS_DIR / "_ext"))

project = "Housecairn"
author = "Robvred"
copyright = "2026 Robvred"  # noqa: A001 (Sphinx setting name)

extensions = ["myst_parser", "housecairn_docs"]

# Markdown (MyST) only; reStructuredText is not used.
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = [
    "_build",
    "_generated",
    "locale",
    # Index of the records for readers browsing the repository on GitHub; the
    # site lists them in developer/decisions.md.
    "adr/README.md",
]
templates_path = ["_templates"]

# Translations (gettext). English is the source; French catalogs are in
# locale/fr/LC_MESSAGES/, one per page. Untranslated strings stay in English.
language = "en"
locale_dirs = ["locale/"]
gettext_compact = False
gettext_uuid = False
gettext_location = False
translation_progress_classes = True

myst_heading_anchors = 3
myst_enable_extensions = ["deflist"]

# Strict build: every reference must resolve (sphinx-build -n -W).
nitpicky = True

html_theme = "furo"
html_title = "Housecairn"
html_static_path = ["_static"]
html_css_files = ["housecairn.css"]
html_baseurl = "https://docs.housecairn.app/"
html_copy_source = False
html_show_sourcelink = False
html_last_updated_fmt = None
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/language.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
    ]
}
html_theme_options = {
    "source_repository": "https://github.com/HouseCairn/housecairn/",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_css_variables": {
        "color-brand-primary": "#1F3A3D",
        "color-brand-content": "#1F3A3D",
    },
    "dark_css_variables": {
        "color-brand-primary": "#C8A27C",
        "color-brand-content": "#C8A27C",
    },
}

# External links, checked by `sphinx-build -b linkcheck` in CI.
linkcheck_timeout = 20
linkcheck_retries = 3
linkcheck_anchors = False
linkcheck_ignore = [
    # The site itself: it does not answer before its first publication, which
    # needs this check to pass (docs/adr/0016).
    r"https://docs\.housecairn\.app(/.*)?$",
    # Placeholders of the examples.
    r"https?://([a-z0-9-]+\.)*example\.com(/.*)?$",
    r"http://(localhost|127\.0\.0\.1)(:\d+)?(/.*)?$",
]
