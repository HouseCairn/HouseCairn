"""Design tokens: `design/tokens.json` is the source, CSS variables are generated."""

import json
import re
from pathlib import Path

from django.conf import settings

TOKENS_PATH = settings.REPO_DIR / "design" / "tokens.json"
CSS_PATH = settings.BASE_DIR / "static" / "css" / "tokens.css"

_NAME = re.compile(r"^[a-z0-9-]+$")


def load_tokens(path: Path = TOKENS_PATH) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[str, dict[str, str]] = {}
    for group, values in data.items():
        if group.startswith("$"):
            continue
        if not isinstance(values, dict) or not _NAME.match(group):
            raise ValueError(f"Invalid token group: {group!r}")
        for name, value in values.items():
            if not _NAME.match(name) or not isinstance(value, str):
                raise ValueError(f"Invalid token: {group}.{name}")
        groups[group] = values
    return groups


def render_css(tokens: dict[str, dict[str, str]]) -> str:
    lines = [
        "/* Generated from design/tokens.json by `manage.py build_design_tokens`. */",
        "/* Do not edit by hand. */",
        ":root {",
    ]
    for group, values in tokens.items():
        for name, value in values.items():
            lines.append(f"  --hc-{group}-{name}: {value};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def expected_css() -> str:
    return render_css(load_tokens())
