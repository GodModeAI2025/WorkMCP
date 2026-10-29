"""Small HTML/text helpers (stdlib only)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
_WS_RE = re.compile(r"[ \t\r\f\v]+")


class _Blocks(HTMLParser):
    """Splits HTML into (kind, text) blocks: kind is 'heading', 'item' or 'text'."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._kind = "text"
        self._skip = 0

    def _flush(self) -> None:
        text = _WS_RE.sub(" ", "".join(self._buf)).strip()
        if text:
            self.blocks.append((self._kind, text))
        self._buf = []
        self._kind = "text"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            if tag in _HEADING_TAGS:
                self._kind = "heading"
            elif tag == "li":
                self._kind = "item"

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def html_blocks(markup: str) -> list[tuple[str, str]]:
    parser = _Blocks()
    parser.feed(markup or "")
    parser.close()
    return parser.blocks


def html_to_text(markup: str | None, limit: int | None = None) -> str:
    """Readable plain text: list items become '- ' lines, blocks become lines."""
    if not markup:
        return ""
    if "<" not in markup:
        text = html.unescape(markup).strip()
    else:
        lines = []
        for kind, text in html_blocks(markup):
            lines.append(f"- {text}" if kind == "item" else text)
        text = "\n".join(lines)
    if limit is not None and len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def list_items(markup: str | None) -> list[str]:
    """All <li> texts of an HTML fragment; for plain text: one item per non-empty line."""
    if not markup:
        return []
    if "<" not in markup:
        items = [re.sub(r"^[\-•*·]\s*", "", ln).strip() for ln in html.unescape(markup).splitlines()]
        return [i for i in items if i]
    return [text for kind, text in html_blocks(markup) if kind == "item"]


def sections_by_heading(markup: str, keywords: list[str], max_items: int = 200) -> list[dict[str, Any]]:
    """Collect list items / paragraphs following headings that contain one of ``keywords``.

    Learned from the berufsgraph prototype: BERUFENET content is organised under headings such as
    "Aufgaben und Tätigkeiten"; everything up to the next heading belongs to that section.
    """
    lowered = [k.lower() for k in keywords]
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for kind, text in html_blocks(markup or ""):
        if kind == "heading":
            current = None
            if any(k in text.lower() for k in lowered):
                current = {"ueberschrift": text, "punkte": []}
                out.append(current)
            continue
        if current is not None:
            items = current["punkte"]
            if text not in items and len(items) < max_items:
                items.append(text)
    return out


def truncate(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
