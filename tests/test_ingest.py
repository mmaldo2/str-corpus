import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from ingest import era_partition, extract_text_and_pages, parse_year
from textnorm import normalize, normalize_cite, normalize_text

PAGE_BREAK_HTML = b"""
<section class="casebody" data-firstpage="126" data-lastpage="128">
  <article class="opinion" data-type="majority">
    <p id="a1">The owner's right to temporarily <a id="p127" href="#p127"
      data-label="127" class="page-label">*127</a>alienate possession of his
      property is an incident of ownership.</p>
    <p id="a2">The lodger takes no estate; he has a mere license to occupy
      the fur<a id="p128" href="#p128" data-label="128"
      class="page-label">*128</a>nished rooms.</p>
  </article>
</section>
"""


def test_page_label_removed_from_text():
    text, pages = extract_text_and_pages(PAGE_BREAK_HTML)
    assert "*127" not in text and "*128" not in text
    assert "127" not in text.split()  # bare label leaked as a word


def test_star_pagination_does_not_break_phrase_matching():
    """The user-flagged failure mode: a *127 mid-phrase must not kill
    phrase-level selector recall."""
    text, _ = extract_text_and_pages(PAGE_BREAK_HTML)
    norm = normalize_text(text)
    assert "temporarily alienate possession" in norm
    # label spliced mid-WORD ("fur*128nished") must rejoin too
    assert "furnished rooms" in norm


def test_page_map_offsets_point_at_following_text():
    text, pages = extract_text_and_pages(PAGE_BREAK_HTML)
    assert [p for _, p in pages] == ["127", "128"]
    off_127 = pages[0][0]
    assert text[off_127:].startswith("alienate")


def test_normalize_offset_map_roundtrip():
    raw = "The  Lodger’s   right — to “let” his board- ing house"
    norm, offsets = normalize(raw)
    assert norm == 'the lodger\'s right - to "let" his boarding house'
    assert len(offsets) == len(norm)
    # every mapped char must exist in raw at that offset (spot-check 'lodger')
    i = norm.index("lodger")
    assert raw[offsets[i]] in ("L", "l")
    # de-hyphenated word maps back inside the raw span of "board- ing"
    j = norm.index("boarding")
    assert raw[offsets[j] : offsets[j] + 6] == "board-"


def test_normalize_strips_ocr_junk():
    assert normalize_text("Queens, ■ Jones") == "queens, jones"


def test_normalize_cite():
    assert normalize_cite("1 Wend. 16") == "1 wend 16"
    assert normalize_cite("172  S.W.2d   704") == "172 s w 2d 704"


def test_era_partition_bounds():
    assert era_partition(1859) == "pre-1860"
    assert era_partition(1860) == "1860-1900"
    assert era_partition(1899) == "1860-1900"
    assert era_partition(1926) == "1900-1930"
    assert era_partition(1969) == "1930-1970"
    assert era_partition(2019) == "1970-2020"


def test_parse_partial_decision_dates():
    assert parse_year("1828-05") == 1828
    assert parse_year("1828") == 1828
    assert parse_year("") == 0
