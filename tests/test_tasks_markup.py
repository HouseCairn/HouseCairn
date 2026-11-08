"""The procedure of a task, in Markdown, shown safely (docs/adr/0031)."""

import re
from html.parser import HTMLParser

import pytest
from hypothesis import given
from hypothesis import strategies as st

from housecairn.tasks import markup
from housecairn.tasks.templatetags.tasks_extras import markdown

ALLOWED_TAGS = {
    "p", "em", "strong", "code", "pre", "a", "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "br",
}  # fmt: skip


class Collect(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs))


def parsed(html: str) -> Collect:
    collector = Collect()
    collector.feed(html)
    return collector


def test_the_usual_markup_is_rendered() -> None:
    html = markup.render(
        "# Steps\n\n1. **Switch off** the _boiler_\n2. Call `Acme`\n\n- one\n- two"
    )
    assert "<h1>Steps</h1>" in html
    assert "<ol>" in html
    assert "<strong>Switch off</strong>" in html
    assert "<em>boiler</em>" in html
    assert "<code>Acme</code>" in html
    assert "<ul>" in html


def test_html_is_escaped_not_run() -> None:
    html = markup.render('<script>alert(1)</script> <img src="http://x/y.png" onerror="boom()">')
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    block = markup.render('<div onclick="x()">hi</div>\n\n<iframe src=//evil></iframe>')
    assert "<div" not in block
    assert "<iframe" not in block


def test_images_load_nothing() -> None:
    html = markup.render("![logo](https://example.com/logo.png) ![x](data:image/png;base64,AAAA)")
    assert "<img" not in html
    assert "src=" not in html


def test_a_web_link_is_kept_with_safe_attributes() -> None:
    html = markup.render("[manual](https://example.com/manual?a=1&b=2) and <https://example.org>")
    links = parsed(html).links
    assert [link["href"] for link in links] == [
        "https://example.com/manual?a=1&b=2",
        "https://example.org",
    ]
    assert all(link["rel"] == "noopener noreferrer nofollow" for link in links)


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<b>x</b>",
        "vbscript:x",
        "file:///etc/passwd",
        "mailto:a@example.com",
        "/relative/path",
        "//evil.example.com",
        "ftp://example.com/x",
    ],
)
def test_other_links_keep_their_words_and_lose_their_address(target: str) -> None:
    html = markup.render(f"[click here]({target}) after")
    assert "<a" not in html
    assert "</a>" not in html
    assert "click here" in html
    assert "after" in html
    assert "href" not in html


def test_nested_links_and_emphasis_close_properly() -> None:
    html = markup.render("**[bad](javascript:x) and [good](https://example.com/a)**")
    assert html.count("<a ") == 1
    assert html.count("</a>") == 1
    assert "<strong>" in html
    assert "</strong>" in html


def test_empty_and_the_template_filter() -> None:
    assert markup.render("") == ""
    assert str(markdown("**x**")) == "<p><strong>x</strong></p>\n"


@given(st.text(max_size=300))
def test_whatever_is_written_only_safe_tags_and_addresses_come_out(text: str) -> None:
    """For any text: only the allowed tags, only http(s) links, no image, no script."""
    html = markup.render(text)
    found = parsed(html)
    assert set(found.tags) <= ALLOWED_TAGS
    for link in found.links:
        assert str(link["href"]).lower().startswith(("http://", "https://"))
        assert not re.search(r"[\"'<>]", str(link["href"]))


@given(st.text(alphabet=st.sampled_from(list("<>[]()!*_`#\"'&:/\\ \njavascrip=x")), max_size=80))
def test_hostile_looking_characters_never_make_an_active_tag(text: str) -> None:
    html = markup.render(text)
    assert not re.search(
        r"<(script|img|iframe|object|embed|svg|style|form|input|link|meta)\b", html, re.I
    )
