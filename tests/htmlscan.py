"""Case-insensitive inline script and style detection, shared by page tests."""

from html.parser import HTMLParser


class _Scanner(HTMLParser):
    """Collect script tags, style tags and risky attributes (HTMLParser lowercases names)."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self.style_tags = 0
        self.style_attributes = 0
        self.event_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.scripts.append(dict(attrs))
        elif tag == "style":
            self.style_tags += 1
        for name, _ in attrs:
            if name == "style":
                self.style_attributes += 1
            elif name.startswith("on"):
                self.event_handlers.append(name)

    handle_startendtag = handle_starttag


def inline_code_problems(html: str) -> list[str]:
    """Return what breaks the strict CSP: inline scripts, style tags or attributes, on* handlers.

    A script is accepted when it loads a file (``src``) or is a JSON data block.
    """
    scanner = _Scanner()
    scanner.feed(html)
    scanner.close()
    problems = [
        f"inline script: {attrs}"
        for attrs in scanner.scripts
        if "src" not in attrs and (attrs.get("type") or "").lower() != "application/json"
    ]
    problems += ["style tag"] * scanner.style_tags
    problems += ["style attribute"] * scanner.style_attributes
    problems += [f"event handler: {name}" for name in scanner.event_handlers]
    return problems


def script_tags(html: str) -> list[dict[str, str | None]]:
    """Return the attributes of every script tag, whatever the case of the markup."""
    scanner = _Scanner()
    scanner.feed(html)
    scanner.close()
    return scanner.scripts
