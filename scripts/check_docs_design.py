"""Check the accessibility of the built documentation site (docs/adr/0016, "Design").

Serves the built site on 127.0.0.1 and opens it in Playwright's Chromium:

1. Contrast (WCAG 2.2 AA, success criterion 1.4.3): on every page, in English
   and French, in the light and the dark theme, every visible text against the
   background it is drawn on: 4.5:1, or 3:1 for large text (24 px, or 18.66 px
   bold). The browser reports the computed colours; the ratio is computed here.
2. Focus (2.4.7, 1.4.11): from the top of the home page, the Tab key reaches
   the skip link first, and every focused element shows an outline of at least
   2 px with 3:1 against the page, in both themes.
3. Motion (2.3.3): with `prefers-reduced-motion: reduce`, nothing on the home
   page has a transition or an animation.

No screenshots until the dedicated lot before the public release (docs/adr/0016).

Usage: python scripts/check_docs_design.py [<site>]
Needs the `docs` dependency group and the browser:
`uv run playwright install --only-shell chromium`.
"""

import argparse
import functools
import http.server
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE = REPO_DIR / "docs" / "_build" / "site"
LANGUAGES = {"en": "", "fr": "fr/"}
THEMES = ("light", "dark")
DEVICES: dict[str, dict[str, Any]] = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
}
TEXT_RATIO = 4.5
LARGE_TEXT_RATIO = 3.0
NON_TEXT_RATIO = 3.0
MAX_TABS = 40
MAX_LINES = 50

Colour = tuple[float, float, float, float]

# Every visible element with its own text: its colour, the background layers
# under it (nearest first), its size and weight. A background image on the way
# (other than none) makes the background unknown: reported, never guessed.
TEXT_SAMPLES_JS = """
() => {
  const parse = (c) => {
    const m = c.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    if (el.closest('[aria-hidden="true"], .visually-hidden, script, style, noscript')) continue;
    const style = getComputedStyle(el);
    if (style.visibility !== 'visible' || el.getClientRects().length === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    // Moved out of the page until it is focused (the skip link).
    if (rect.bottom + window.scrollY <= 0 || rect.right + window.scrollX <= 0) continue;
    // Clipped to nothing (screen-reader-only text).
    if (style.clip === 'rect(0px, 0px, 0px, 0px)' || style.clipPath === 'inset(50%)') continue;
    let opacity = 1;
    const layers = [];
    let unknown = false;
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      opacity *= Number(s.opacity);
      if (s.backgroundImage && s.backgroundImage !== 'none') unknown = true;
      const bg = parse(s.backgroundColor);
      if (bg && bg[3] > 0) {
        layers.push(bg);
        if (bg[3] >= 1) break;
      }
    }
    if (opacity < 0.05) continue;
    const fg = parse(style.color);
    fg[3] *= opacity;
    let name = el.tagName.toLowerCase();
    if (el.className && typeof el.className === 'string') {
      name += '.' + el.className.trim().split(/\\s+/).join('.');
    }
    out.push({
      element: name,
      text: node.textContent.trim().slice(0, 40),
      color: fg,
      layers: layers,
      unknown: unknown,
      size: parseFloat(style.fontSize),
      weight: Number(style.fontWeight) || 400,
    });
  }
  return out;
}
"""

FOCUS_JS = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const s = getComputedStyle(el);
  const parse = (c) => {
    const m = c.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const layers = [];
  for (let a = el.parentElement; a; a = a.parentElement) {
    const bg = parse(getComputedStyle(a).backgroundColor);
    if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] >= 1) break; }
  }
  let name = el.tagName.toLowerCase();
  if (el.className && typeof el.className === 'string' && el.className.trim()) {
    name += '.' + el.className.trim().split(/\\s+/).join('.');
  }
  const label = (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30);
  return {
    element: name + ' "' + label + '"',
    style: s.outlineStyle,
    width: parseFloat(s.outlineWidth) || 0,
    color: parse(s.outlineColor),
    layers: layers,
  };
}
"""

MOTION_JS = """
() => {
  const moves = (v) => v.split(',').some((d) => parseFloat(d) > 0);
  const name = (el) => {
    const c = typeof el.className === 'string' ? el.className.trim() : '';
    return el.tagName.toLowerCase() + (c ? '.' + c.split(/\\s+/).join('.') : '');
  };
  return [...document.querySelectorAll('body *')].filter((el) => {
    const s = getComputedStyle(el);
    return moves(s.transitionDuration)
      || (s.animationName !== 'none' && moves(s.animationDuration));
  }).map(name);
}
"""


def luminance(colour: Colour) -> float:
    """Relative luminance (WCAG 2.2) of an sRGB colour, alpha ignored."""

    def channel(value: float) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def blend(top: Colour, bottom: Colour) -> Colour:
    """`top` drawn over an opaque `bottom`."""
    alpha = top[3]
    mixed = [top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3)]
    return (mixed[0], mixed[1], mixed[2], 1.0)


def flatten(layers: list[Colour], page: Colour = (255.0, 255.0, 255.0, 1.0)) -> Colour:
    """The opaque colour of background layers listed nearest first."""
    result = page
    for layer in reversed(layers):
        result = blend(layer, result)
    return result


def contrast(foreground: Colour, background: Colour) -> float:
    """WCAG contrast ratio of a (possibly translucent) colour on an opaque one."""
    lighter, darker = sorted(
        (luminance(blend(foreground, background)), luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def is_large(size_px: float, weight: float) -> bool:
    """Large text of WCAG: 18 pt (24 px), or 14 pt (18.66 px) bold."""
    return size_px >= 24 or (size_px >= 18.66 and weight >= 700)


@dataclass
class Failure:
    where: str
    element: str
    text: str
    ratio: float
    needed: float

    def __str__(self) -> str:
        return (
            f"{self.where}: {self.element} {self.text!r}: "
            f"{self.ratio:.2f}:1 (needs {self.needed}:1)"
        )


def text_failures(where: str, samples: list[dict[str, Any]]) -> tuple[list[Failure], int]:
    """Failures among the text samples of a page, and the number of unknown backgrounds."""
    failures = []
    unknown = 0
    for sample in samples:
        if sample["unknown"]:
            unknown += 1
            continue
        background = flatten([tuple(layer) for layer in sample["layers"]])
        ratio = contrast(tuple(sample["color"]), background)
        needed = LARGE_TEXT_RATIO if is_large(sample["size"], sample["weight"]) else TEXT_RATIO
        if ratio < needed - 0.005:
            failures.append(Failure(where, sample["element"], sample["text"], ratio, needed))
    return failures, unknown


def focus_problem(where: str, focus: dict[str, Any]) -> str | None:
    """Why the focus of an element is not visible enough, or None."""
    if focus["style"] in ("none", "hidden") or focus["width"] < 2 or focus["color"] is None:
        return f"{where}: {focus['element']}: no visible focus outline"
    ratio = contrast(tuple(focus["color"]), flatten([tuple(c) for c in focus["layers"]]))
    if ratio < NON_TEXT_RATIO - 0.005:
        return f"{where}: {focus['element']}: focus outline {ratio:.2f}:1 (needs 3:1)"
    return None


@contextmanager
def serve(site: Path) -> Iterator[str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

    handler = functools.partial(Quiet, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def pages_of(site: Path) -> list[str]:
    """Address of every page of the site, relative to its root."""
    pages = []
    for path in sorted(site.rglob("index.html")):
        relative = path.parent.relative_to(site).as_posix()
        if relative.startswith(("_static", "_images", "_sources")):
            continue
        pages.append("" if relative == "." else relative + "/")
    return pages


def open_page(browser: Any, theme: str, device: str, **options: Any) -> Any:
    context = browser.new_context(color_scheme=theme, **DEVICES[device], **options)
    # Furo reads the chosen theme from localStorage before the first paint.
    context.add_init_script(f"localStorage.setItem('theme', '{theme}')")
    return context


def load(page: Any, url: str) -> None:
    page.goto(url)
    page.wait_for_load_state("load")
    page.evaluate("document.fonts.ready.then(() => true)")


def check(site: Path) -> int:
    # Imported here: only the docs dependency group provides Playwright.
    from playwright.sync_api import sync_playwright

    pages = pages_of(site)
    failures: list[Failure] = []
    unknown = 0
    checked = 0
    focus_problems: list[str] = []
    focus_count = 0
    motion: list[str] = []

    with serve(site) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for theme in THEMES:
            context = open_page(browser, theme, "desktop")
            page = context.new_page()
            for address in pages:
                load(page, base + address)
                samples = page.evaluate(TEXT_SAMPLES_JS)
                found, unknown_here = text_failures(f"{theme} /{address}", samples)
                failures += found
                unknown += unknown_here
                checked += len(samples)

            for prefix in LANGUAGES.values():
                load(page, base + prefix)
                for _ in range(MAX_TABS):
                    page.keyboard.press("Tab")
                    focus = page.evaluate(FOCUS_JS)
                    if focus is None:
                        continue
                    focus_count += 1
                    if focus_count == 1 and "skip-to-content" not in focus["element"]:
                        focus_problems.append(
                            f"{theme} /{prefix}: first Tab stop is {focus['element']}, "
                            "not the skip link"
                        )
                    problem = focus_problem(f"{theme} /{prefix}", focus)
                    if problem:
                        focus_problems.append(problem)
            context.close()

        context = open_page(browser, "light", "desktop", reduced_motion="reduce")
        page = context.new_page()
        load(page, base)
        motion = page.evaluate(MOTION_JS)
        context.close()
        browser.close()

    failed = False
    if failures:
        failed = True
        sys.stderr.write(f"Contrast below WCAG 2.2 AA ({len(failures)}):\n")
        sys.stderr.writelines(f"- {line}\n" for line in failures[:MAX_LINES])
    else:
        sys.stdout.write(
            f"Contrast (WCAG 2.2 AA, 4.5:1 and 3:1 for large text): 0 failures in "
            f"{checked} text elements of {len(pages)} pages, light and dark themes "
            f"({unknown} on a background image, not measured).\n"
        )
    if focus_problems or focus_count == 0:
        failed = True
        sys.stderr.write(f"Keyboard focus ({focus_count} stops):\n")
        sys.stderr.writelines(f"- {line}\n" for line in focus_problems[:MAX_LINES])
    else:
        sys.stdout.write(
            f"Keyboard focus: skip link first, {focus_count} Tab stops with a visible "
            "outline (2 px or more, 3:1 or more), light and dark, en and fr.\n"
        )
    if motion:
        failed = True
        sys.stderr.write("Motion despite prefers-reduced-motion: reduce:\n")
        sys.stderr.writelines(f"- {line}\n" for line in motion[:MAX_LINES])
    else:
        sys.stdout.write("Reduced motion: no transition or animation when it is asked for.\n")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the design of the built site.")
    parser.add_argument("site", nargs="?", type=Path, default=DEFAULT_SITE)
    args = parser.parse_args(argv)
    if not (args.site / "index.html").exists():
        sys.stderr.write(f"No site in {args.site}: build it first (scripts/build_docs.py).\n")
        return 2
    return check(args.site.resolve())


if __name__ == "__main__":
    sys.exit(main())
