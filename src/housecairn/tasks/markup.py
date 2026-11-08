"""Safe rendering of a task's procedure, written in Markdown (docs/adr/0031).

The text is untrusted input shown to every member of the home. Raw HTML is not
parsed (it is escaped as text), images are not rendered (no resource is loaded
from anywhere), and a link is kept only if it is `http` or `https`: anything else
(`javascript:`, `data:`, `file:`) is shown as plain text.
"""

from typing import Any

from django.utils.safestring import SafeString, mark_safe
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

_SCHEMES = ("http://", "https://")


class _SafeRenderer(RendererHTML):
    def link_open(self, tokens: Any, idx: int, options: OptionsDict, env: EnvType) -> str:
        token: Token = tokens[idx]
        href = str(token.attrGet("href") or "")
        if not href.lower().startswith(_SCHEMES):
            # Not a web address: keep the words, drop the link and its closing tag.
            token.attrs = {}
            token.meta = {"dropped": True}
            return ""
        token.attrs = {"href": href, "rel": "noopener noreferrer nofollow"}
        return super().renderToken(tokens, idx, options, env)

    def link_close(self, tokens: Any, idx: int, options: OptionsDict, env: EnvType) -> str:
        opening = next(
            token
            for token in reversed(tokens[:idx])
            if token.type == "link_open" and token.level == tokens[idx].level
        )
        if opening.meta.get("dropped"):
            return ""
        return super().renderToken(tokens, idx, options, env)


_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}, renderer_cls=_SafeRenderer)
_markdown.disable(["image"])


def render(text: str) -> SafeString:
    """The HTML of the Markdown `text`, safe to put in a page."""
    html: str = _markdown.render(text or "")
    return mark_safe(html)  # noqa: S308 - html is off, see the module
