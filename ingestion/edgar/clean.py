"""Convert EDGAR filing HTML (including inline XBRL) into readable plain text."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "table",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "hr",
}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
_SPACES = re.compile(r"[ \t    ]+")


def html_to_text(html: str) -> str:
    """Strip markup, hidden XBRL data, scripts and styles; keep table rows as lines."""
    if "<" not in html:
        return _normalize(html)

    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "head", "title", "noscript"]):
        tag.decompose()
    # Inline XBRL puts machine-readable data in a hidden <ix:header> block.
    for tag in soup.find_all(lambda t: isinstance(t, Tag) and t.name.lower() == "ix:header"):
        tag.decompose()
    for tag in soup.find_all(style=_HIDDEN_STYLE):
        tag.decompose()

    # Render each table row as one line: "Net sales | 391,035 | 383,285"
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        tr.replace_with(soup.new_string("\n" + " | ".join(cells) + "\n" if cells else "\n"))

    # Line breaks after block elements, so inline spans stay on one line.
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")

    return _normalize(soup.get_text())


def _normalize(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    out: list[str] = []
    for line in lines:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()
