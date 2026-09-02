import re

from lxml import html as lxml_html

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "blockquote", "section",
              "article", "aside", "div", "tr"}


def parse_year(decision_date: str) -> int:
    m = re.match(r"(\d{4})", decision_date or "")
    return int(m.group(1)) if m else 0


def extract_text_and_pages(html_bytes: bytes) -> tuple[str, list[tuple[int, str]]]:
    """Extract casebody text in document order. Page-label anchors are
    excluded from the text; each contributes (offset, label) to the page map.
    Block-level boundaries become newlines."""
    # static.case.law HTML is UTF-8 without a charset declaration; lxml's
    # byte-level encoding guess mangles em-dashes etc., so decode explicitly.
    doc = lxml_html.fromstring(html_bytes.decode("utf-8"))
    body = doc if doc.get("class") == "casebody" else doc
    parts: list[str] = []
    pages: list[tuple[int, str]] = []
    length = 0

    def emit(s: str) -> None:
        nonlocal length
        if s:
            parts.append(s)
            length += len(s)

    def walk(el) -> None:
        cls = el.get("class") or ""
        if el.tag == "a" and "page-label" in cls:
            pages.append((length, el.get("data-label") or el.text_content().strip("*")))
            if el.tail:
                emit(el.tail)
            return
        if el.text:
            emit(el.text)
        for child in el:
            walk(child)
        if el.tag in BLOCK_TAGS:
            emit("\n")
        if el.tail:
            emit(el.tail)

    walk(body)
    # No post-processing: page offsets index into exactly this string.
    return "".join(parts), pages


def primary_cite(citations: list[dict]) -> str:
    for c in citations:
        if c.get("type") == "official":
            return c["cite"]
    return citations[0]["cite"] if citations else ""
