"""The saved review page IS the record (same mechanism as pipeline/make_review.py), so this
tool has one job: turn the decision state embedded in that page into ledger patches with the
user as basis, and refuse anything it cannot read. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTESTED = ROOT / "tests" / "fixtures" / "reference-contested-tiny.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arr = _load("apply_reference_review")
mrr = _load("make_reference_review")


def saved_page(tmp_path, decisions) -> str:
    """A page in exactly the state the artifact capability republishes it in: the empty
    state array replaced by the decisions, everything else byte-identical."""
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    html = html_path.read_text(encoding="utf-8")
    payload = json.dumps(decisions).replace("<", "\u003c")
    return html.replace('id="review-state">[]<', f'id="review-state">{payload}<')


def _d(case_id, field, decision, value=None, note=""):
    return {"case_id": case_id, "field": field, "decision": decision, "value": value, "note": note}


def test_read_state_returns_the_decisions_a_saved_page_carries(tmp_path):
    decisions = [_d(65116, "polarity", "adopt", "favorable"), _d(65116, "who_was_letting", "keep", "unclear")]
    got = arr.read_state(saved_page(tmp_path, decisions))
    assert [(d["case_id"], d["field"], d["decision"], d["value"]) for d in got] == [
        (65116, "polarity", "adopt", "favorable"), (65116, "who_was_letting", "keep", "unclear")]


def test_read_state_refuses_an_unsaved_page_and_a_bad_decision(tmp_path):
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    with pytest.raises(ValueError, match="no decisions"):
        arr.read_state(html_path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no review-state"):
        arr.read_state("<html>nothing here</html>")
    with pytest.raises(ValueError, match="decision"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "maybe", "favorable")]))
    with pytest.raises(ValueError, match="value"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "set", "pro-tenant")]))
    with pytest.raises(ValueError, match="field"):
        arr.read_state(saved_page(tmp_path, [_d(1, "duration_of_occupancy", "keep", "weeks")]))


def test_patches_for_covers_the_four_decisions():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True},
               2: {"polarity": "mixed", "who_was_letting": "unclear", "relevant": True},
               3: {"polarity": "adverse", "who_was_letting": "householder", "relevant": True},
               4: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "polarity", "keep", "favorable"),
                 _d(2, "polarity", "adopt", "adverse", note="clearly a tenant-protection holding"),
                 _d(3, "who_was_letting", "set", "non_resident_owner"),
                 _d(4, "polarity", "unsure")]
    ps = arr.patches_for(decisions, records, "mmaldo2")
    by_case = {}
    for p in ps:
        by_case.setdefault(p.case_id, []).append((p.op, p.field, p.new))
    assert 1 not in by_case                                        # keep -> no patch at all
    assert ("set", "polarity", "adverse") in by_case[2]
    assert ("append", "review.notes", "user note: clearly a tenant-protection holding") in by_case[2]
    assert ("set", "review.status", "human-adjudicated") in by_case[2]
    assert ("set", "who_was_letting", "non_resident_owner") in by_case[3]
    assert ("append", "review.flags", "needs-review:polarity") in by_case[4]
    assert not any(op == "set" and f == "polarity" for op, f, _v in by_case[4])
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == "reference-v2" for p in ps)
    assert all(p.basis.kind() == "human" for p in ps)


def test_adopting_irrelevant_on_polarity_clears_the_whole_record():
    records = {9: {"polarity": "mixed", "who_was_letting": "commercial_operator", "relevant": True}}
    ps = arr.patches_for([_d(9, "polarity", "adopt", "irrelevant")], records, "mmaldo2")
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert ("relevant", False) in sets and ("polarity", None) in sets and ("who_was_letting", None) in sets
    assert ("review.status", "human-adjudicated") in sets


def test_irrelevant_wins_over_a_value_decision_on_the_same_case():
    """A case the reviewer put out of the corpus carries no who_was_letting, even where the
    same page also carries a who_was_letting value for it (5 of the 71 real cases do). Without
    this the later field would re-set what `irrelevant` just nulled."""
    records = {9: {"polarity": "mixed", "who_was_letting": "unclear", "relevant": True}}
    ps = arr.patches_for([_d(9, "polarity", "adopt", "irrelevant"),
                          _d(9, "who_was_letting", "adopt", "non_resident_owner")], records, "u")
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert ("who_was_letting", None) in sets
    assert ("who_was_letting", "non_resident_owner") not in sets
    assert any(p.op == "append" and p.field == "review.notes" and "irrelevant" in p.new for p in ps)


def test_patch_order_follows_the_field_order_flag():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "who_was_letting", "set", "householder"), _d(1, "polarity", "set", "adverse")]
    fields = [p.field for p in arr.patches_for(decisions, records, "u") if p.op == "set"]
    assert fields.index("polarity") < fields.index("who_was_letting")
    fields2 = [p.field for p in arr.patches_for(decisions, records, "u",
                                                field_order=("who_was_letting", "polarity")) if p.op == "set"]
    assert fields2.index("who_was_letting") < fields2.index("polarity")


def test_null_spellings_become_none():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    ps = arr.patches_for([_d(1, "polarity", "set", "null")], records, "u")
    assert ("polarity", None) in [(p.field, p.new) for p in ps if p.op == "set"]


def test_the_users_saved_page_is_readable_and_maps_onto_the_ledger():
    """The real input, guarded so a later edit to either the page or the reader is caught."""
    saved = ROOT / "data" / "reader" / "review" / "reference-v1" / "saved-2026-09-05.html"
    if not saved.exists():
        pytest.skip("the user's saved page is not on disk")
    decisions = arr.read_state(saved.read_text(encoding="utf-8"))
    assert len(decisions) == 82
    tally = {}
    for d in decisions:
        tally[(d["field"], d["decision"])] = tally.get((d["field"], d["decision"]), 0) + 1
    assert tally == {("polarity", "adopt"): 37, ("polarity", "keep"): 4,
                     ("who_was_letting", "adopt"): 36, ("who_was_letting", "keep"): 2,
                     ("who_was_letting", "set"): 1, ("who_was_letting", "unsure"): 2}
