"""Versioned, deterministic text normalization with offset tracking.

NORM_VERSION is stored per-case; any change here invalidates the coverage
matrix (spec §5). normalize() returns the normalized text plus an offset map
(norm index -> raw index) so verify_quotes can map a match in norm_text back
to a raw_text span, and from there to a reporter page via page_map, without
storing per-char maps in the DB.
"""

import re

NORM_VERSION = 1

# OCR junk that appears mid-sentence in CAP scans (e.g. "Queens, ■ jones").
_JUNK = "■□¶•†‡"

_CONFUSABLES = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    " ": " ",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ſ": "s",  # long s, rare post-1800 but free to handle
}

# Line-break hyphenation left by OCR: "board- ing" -> "boarding".
# Conservative: only lowercase letter, hyphen, whitespace, lowercase letter.
_DEHYPHEN = re.compile(r"(?<=[a-z])-\s+(?=[a-z])")


def normalize(raw: str) -> tuple[str, list[int]]:
    """Return (norm_text, offset_map) where offset_map[i] is the raw-text
    index that produced norm_text[i]. Deterministic; pure function of raw."""
    out: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(raw)
    prev_space = True  # leading whitespace is dropped
    while i < n:
        ch = raw[i]
        # de-hyphenation: consume "-<ws>+" between lowercase letters
        if (
            ch == "-"
            and out
            and out[-1].islower()
            and out[-1].isalpha()
        ):
            m = _DEHYPHEN.match(raw, i)
            if m:
                i = m.end()
                continue
        ch = _CONFUSABLES.get(ch, ch)
        if ch in _JUNK:
            i += 1
            continue
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                offsets.append(i)
                prev_space = True
            i += 1
            continue
        out.append(ch.lower())
        offsets.append(i)
        prev_space = False
        i += 1
    # strip trailing space
    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets


def normalize_text(raw: str) -> str:
    """norm_text only (what gets stored and FTS-indexed)."""
    return normalize(raw)[0]


def normalize_cite(cite: str) -> str:
    """Canonical key for citation matching: lowercase, no periods,
    single-spaced. '1 Wend. 16' -> '1 wend 16'."""
    return re.sub(r"\s+", " ", cite.replace(".", " ").lower()).strip()
