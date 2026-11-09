"""Sphinx configuration of the documentation site (docs/adr/0016).

Build it with `uv run python scripts/build_docs.py`: English at the root of
the site, French under `/fr/`, both strict.
"""

import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS_DIR / "_ext"))

project = "HouseCairn"
author = "Robvred"
copyright = "2026 Robvred"  # noqa: A001 (Sphinx setting name)

extensions = ["myst_parser", "sphinx_copybutton", "housecairn_docs"]

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
    # How to write a release notes fragment, for contributors.
    "release-notes/unreleased/README.md",
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
myst_enable_extensions = ["deflist", "colon_fence"]

# Strict build: every reference must resolve (sphinx-build -n -W).
nitpicky = True

html_theme = "furo"
html_title = "HouseCairn"
# The look of the application (docs/adr/0016, "Design"): the generated design
# tokens, the self-hosted fonts and the brand files are copied from the
# application, never duplicated, so the site cannot drift from it.
APP_STATIC = "../src/housecairn/static/"
html_static_path = [
    "_static",
    APP_STATIC + "css/tokens.css",
    APP_STATIC + "fonts/Manrope-latin-variable.woff2",
    APP_STATIC + "fonts/Manrope-OFL.txt",
    APP_STATIC + "fonts/JetBrainsMono-latin-variable.woff2",
    APP_STATIC + "fonts/JetBrainsMono-OFL.txt",
    APP_STATIC + "img/brand/housecairn-logo.svg",
    APP_STATIC + "img/brand/favicon-32.png",
    APP_STATIC + "img/brand/apple-touch-icon.png",
    "../design/brand/housecairn-logo-fond-sombre.svg",
]
html_css_files = ["tokens.css", "housecairn.css"]
html_js_files = ["housecairn.js"]
html_favicon = APP_STATIC + "img/brand/favicon.svg"
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
# Furo's colours come from the tokens (docs/_static/housecairn.css sets them
# from the --hc-* variables); only the options below are not CSS.
html_theme_options = {
    "source_repository": "https://github.com/HouseCairn/housecairn/",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_logo": "housecairn-logo.svg",
    "dark_logo": "housecairn-logo-fond-sombre.svg",
    "sidebar_hide_name": True,
    # The edit and issue links are at the bottom of each page (_templates/page.html).
    "top_of_page_buttons": [],
}
# Code colours with AA contrast on the code background of each theme.
pygments_style = "a11y-light"
pygments_dark_style = "a11y-dark"

# Copy button on code blocks (sphinx-copybutton, docs/adr/0016): shell prompts
# and console output are not copied.
copybutton_exclude = ".linenos, .gp, .go"

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
