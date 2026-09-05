"""The one-off that clears `needs-review:<field>` flags older than the decision that
supersedes them. Its clearing rule is apply_reference_review's `_clear_flag` (tested there);
what is its own is WHICH cases it may touch - only those the authorising page actually decided
that field for, and only where the flag is still standing. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


csf = _load("clear_superseded_flags")


def _d(case_id, field, decision, value=None):
    return {"case_id": case_id, "field": field, "decision": decision, "value": value, "note": ""}


RECORDS = {1: {"review": {"flags": ["needs-review:polarity"], "notes": []}},
           2: {"review": {"flags": ["needs-review:polarity"], "notes": []}},
           3: {"review": {"flags": ["needs-review:who_was_letting"], "notes": []}},
           4: {"review": {"flags": [], "notes": []}},
           5: {}}


def test_only_a_decided_field_with_a_standing_flag_is_superseded():
    decisions = [_d(1, "polarity", "adopt", "adverse"),      # decided + flagged -> cleared
                 _d(2, "polarity", "keep", "mixed"),         # keep is not a decision
                 _d(3, "polarity", "set", "adverse"),        # flagged on a different field
                 _d(4, "polarity", "adopt", "adverse"),      # nothing to clear
                 _d(5, "polarity", "adopt", "adverse")]      # no review block at all
    assert csf.superseded(decisions, RECORDS, "polarity") == [1]
    assert csf.superseded(decisions, RECORDS, "who_was_letting") == []


def test_the_patches_clear_that_one_flag_and_change_no_value():
    ps = csf.patches_for([1], RECORDS, "polarity", "mmaldo2", "page.html")
    assert [(p.op, p.field, p.new) for p in ps if p.op == "set"] == [("set", "review.flags", [])]
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == csf.RUN_ID for p in ps)
    assert any(p.op == "append" and p.field == "review.notes" and "page.html" in p.why for p in ps)
