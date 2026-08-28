import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from textnorm import normalize_text
from verify_quotes import page_for_offset, verify_quote

RAW = (
    "The owner's right to temporarily alienate possession of his property "
    "is an incident of ownership. The lodger takes no estate; he has a mere "
    "license to occupy the furnished rooms."
)
CASE = {
    "raw_text": RAW,
    "norm_text": normalize_text(RAW),
    "page_map": [[0, "126"], [60, "127"]],
}


def test_exact_quote_verifies_with_page():
    v = verify_quote("a mere license to occupy the furnished rooms", CASE)
    assert v["status"] == "verified"
    assert v["reporter_page"] == "127"
    s, e = v["raw_span"]
    assert RAW[s:e] == "a mere license to occupy the furnished rooms"


def test_quote_with_curly_quotes_and_case_still_verifies():
    # mapper copied from a differently-normalized surface: still exact after norm
    v = verify_quote("The Lodger takes no estate", CASE)
    assert v["status"] == "verified"


def test_ocr_noisy_quote_passes_fuzzy():
    v = verify_quote("a mere licence to occupy the furnisbed rooms", CASE)
    assert v["status"] == "verified-fuzzy"
    assert v["reporter_page"] in ("126", "127")


def test_fabricated_quote_fails():
    v = verify_quote("short-term rentals are deeply rooted in tradition", CASE)
    assert v["status"] == "failed"


def test_page_for_offset():
    assert page_for_offset(CASE["page_map"], 0) == "126"
    assert page_for_offset(CASE["page_map"], 59) == "126"
    assert page_for_offset(CASE["page_map"], 60) == "127"
