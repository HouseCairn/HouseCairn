"""A focus ring must contrast with what it is drawn on (WCAG 2.4.7 and 1.4.11, at least 3:1)."""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src" / "housecairn" / "static" / "css"


def tokens() -> dict[str, str]:
    return dict(
        re.findall(r"(--hc-[\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", (CSS / "tokens.css").read_text())
    )


def luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def declarations(selector: str) -> dict[str, str]:
    """The declarations of the rule whose selector is exactly `selector`."""
    css = (CSS / "components.css").read_text()
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, f"no rule for {selector}"
    return dict(re.findall(r"([\w-]+):\s*([^;]+);", match.group(1)))


def resolve(value: str) -> str:
    name = re.fullmatch(r"var\((--hc-[\w-]+)\)", value.strip())
    assert name, value
    return tokens()[name.group(1)]


def test_the_current_chip_ring_shows_on_its_own_background() -> None:
    chip = declarations('.chip[aria-current="page"]')
    ring = declarations('.chip[aria-current="page"]:focus-visible')
    assert "outline-color" in ring
    assert contrast(resolve(ring["outline-color"]), resolve(chip["background"])) >= 3


def test_the_default_ring_is_drawn_outside_on_the_page() -> None:
    """Buttons keep the global ring (focus colour, 2px off): it sits on the page background."""
    assert "outline-offset: 2px" in (CSS / "base.css").read_text()
    assert contrast(tokens()["--hc-color-focus"], tokens()["--hc-color-surface"]) >= 3
