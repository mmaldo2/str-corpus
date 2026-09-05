"""Guards on tools/make_reference_review.py: the reference-adjudication page has to
carry every contested case and, above all, has to be *savable* - the two markers must be
replaced by real values, because an unreplaced marker is a page that silently loses the
user's decisions. Imported by path because tools/ is scripts, not a package."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "reference-contested-tiny.json"

_spec = importlib.util.spec_from_file_location(
    "make_reference_review", ROOT / "tools" / "make_reference_review.py")
mrr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mrr)


def _build(tmp_path):
    stem = tmp_path / "review-queue-reference-test"
    html_path, md_path, _ = mrr.build_pages(FIXTURE, stem)
    return (html_path.read_text(encoding="utf-8"),
            md_path.read_text(encoding="utf-8"),
            json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_both_files_are_written_with_the_sections_and_every_case(tmp_path):
    html, md, doc = _build(tmp_path)
    assert (tmp_path / "review-queue-reference-test.html").exists()
    assert (tmp_path / "review-queue-reference-test.md").exists()

    assert "<title>Reference adjudication v1</title>" in html
    assert "Polarity" in html and "Who was letting" in html          # both section headers
    for case in doc["contested"]:
        assert str(case["case_id"]) in html, case["case_id"]


def test_the_save_markers_are_replaced_so_the_page_can_republish_itself(tmp_path):
    html, _, _ = _build(tmp_path)
    # the literals may only survive inside JS string concatenation (the page rebuilds
    # them at save time); the *marker* forms must be gone.
    assert '"__REVIEW_STATE__"' not in html
    assert '"__TEMPLATE_B64__"' not in html
    assert 'id="review-state">[]<' in html
    assert 'const TB64 = "' in html and len(html.split('const TB64 = "')[1]) > 1000
    assert "claude.use('artifact')" in html and "art.publish(" in html


def test_the_file_is_content_only_and_committable(tmp_path):
    _build(tmp_path)
    raw = (tmp_path / "review-queue-reference-test.html").read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    low = raw.decode("utf-8").lower()
    for tag in ("<!doctype", "<html", "<head", "<body"):
        assert tag not in low, tag          # the Artifact tool supplies the skeleton
    assert len(raw) < 16 * 1024 * 1024


def test_the_markdown_lists_every_case_once_per_contested_field(tmp_path):
    _, md, doc = _build(tmp_path)
    lines = [ln for ln in md.splitlines() if ln.startswith("- [ ] ")]
    expected = sum(len(c["contested_fields"]) for c in doc["contested"])
    assert len(lines) == expected
    for case in doc["contested"]:
        hits = [ln for ln in lines if f"[{case['case_id']}]" in ln]
        assert len(hits) == len(case["contested_fields"]), case["case_id"]


def test_a_case_contested_on_both_fields_appears_in_both_sections_cross_linked(tmp_path):
    _, _, doc = _build(tmp_path)
    data = mrr.build_items(doc)
    both = [c["case_id"] for c in doc["contested"] if len(c["contested_fields"]) == 2]
    assert both, "fixture must contain a case contested on both fields"
    for cid in both:
        a = [i for i in data["A"] if i["case_id"] == cid]
        b = [i for i in data["B"] if i["case_id"] == cid]
        assert len(a) == 1 and len(b) == 1
        assert a[0]["other"] == "B" and b[0]["other"] == "A"
    # every item carries all five candidates, in the pinned order
    for sec in ("A", "B"):
        for item in data[sec]:
            assert [c["label"] for c in item["cands"]] == [lab for _, lab in mrr.CANDIDATES]
            assert item["maj"] != item["ref"]
