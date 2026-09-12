# tests/test_threeway_sheet.py
"""tools/threeway_sheet.py: agree/disagree per card (one-field) or per field (audit)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import threeway_sheet as tw


def _d(cid, field, decision, value=None, note="n"):
    d = {"case_id": cid, "field": field, "decision": decision, "note": note}
    if value is not None: d["value"] = value
    return d


def test_one_field_mode_agreed_set_resolves_adopt_and_lists_disagreements_first():
    queue = {"run_id": "r", "sections": {"A": [
        {"case_id": 1, "decide_field": "polarity", "cite": "1 A. 1", "values": {"polarity": "favorable"}},
        {"case_id": 2, "decide_field": "polarity", "cite": "2 A. 2", "values": {"polarity": "favorable"}},
        {"case_id": 3, "decide_field": "polarity", "cite": "3 A. 3", "values": {"polarity": "mixed"}}]}}
    checker = {"1": {"values": {"polarity": "adverse"}}}
    claude = [_d(1, "polarity", "set", "adverse"), _d(2, "polarity", "keep"), _d(3, "relevant", "set", False)]
    astra = [_d(1, "polarity", "adopt"), _d(2, "polarity", "set", "adverse"), _d(3, "relevant", "set", False)]
    md, agreed = tw.build(queue, checker, claude, astra, label="round x")
    assert "agree on 2; disagree on 1" in md
    assert md.index("## Disagreements") < md.index("## Agreements")
    assert "| 2 | 2 A. 2 |" in md.split("## Agreements")[0]          # the disagreement row
    assert [(d["case_id"], d["decision"], d.get("value")) for d in agreed] == [(1, "set", "adverse"), (3, "set", False)]


def test_per_field_mode_compares_each_field_and_applies_nothing():
    queue = {"run_id": "audit", "sections": {"H": [
        {"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9"}]}}
    claude = [_d(9, "relevant", "set", True), _d(9, "polarity", "set", "adverse"), _d(9, "who_was_letting", "set", "householder")]
    astra = [_d(9, "relevant", "set", True), _d(9, "polarity", "set", "adverse"), _d(9, "who_was_letting", "set", "unclear")]
    md, agreed = tw.build(queue, {}, claude, astra, label="audit", per_field=True)
    assert agreed == []
    assert "| 9 | 9 A. 9 | who_was_letting | householder | unclear |" in md
    assert "fields agree 2; disagree 1" in md
