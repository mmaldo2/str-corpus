import json
import pytest
from corpus_engine.ledger.types import Basis, Patch, UnknownCase, DuplicateRecord, MissingBasis
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.log import PatchLog, patch_id

REC = {"case_id": 5, "cite": "1 X 1", "year": 1880, "relevant": True, "polarity": "favorable",
       "characterization": "lodging", "holding_summary": "h",
       "quotes": [{"text": "A", "supports": "polarity"}, {"text": "B", "supports": "characterization"}]}

def test_admit_adds_review_default_and_tracks_order_and_cycle():
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "verified", Basis(model="m", prompt_version="v1", run_id="r"), cycle="cycle-001"))
    assert s.order == [5] and s.cycles[5] == "cycle-001" and s.in_file[5] is True
    assert s.records[5]["review"] == {"status": "machine", "flags": [], "notes": []}
    assert list(s.records[5].keys())[-1] == "review"
    with pytest.raises(DuplicateRecord):
        apply_patch(s, Patch(5, "admit", "", REC, "again", Basis(), cycle="cycle-002"))

def test_set_on_judged_field_needs_authority_and_returns_old():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    with pytest.raises(MissingBasis):
        apply_patch(s, Patch(5, "set", "polarity", "adverse", "hunch", Basis(rule_id="x")))
    old = apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-review", Basis(reviewer="mmaldo2")))
    assert old == "favorable" and s.records[5]["polarity"] == "adverse"
    apply_patch(s, Patch(5, "set", "review.status", "human-adjudicated", "x", Basis(rule_id="r")))
    apply_patch(s, Patch(5, "append", "review.notes", "note", "x", Basis(rule_id="r")))
    assert s.records[5]["review"] == {"status": "human-adjudicated", "flags": [], "notes": ["note"]}
    with pytest.raises(UnknownCase):
        apply_patch(s, Patch(6, "set", "polarity", "adverse", "x", Basis(reviewer="m")))

def test_set_none_on_judged_field_needs_no_judging_authority():
    # A retraction to None removes a claim rather than judging the case, so
    # it needs no reviewer/model authority -- unlike setting a real value.
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    old = apply_patch(s, Patch(5, "set", "polarity", None, "retraction", Basis(rule_id="retraction-cascade-v1")))
    assert old == "favorable" and s.records[5]["polarity"] is None
    with pytest.raises(MissingBasis):
        apply_patch(s, Patch(5, "set", "polarity", "adverse", "hunch", Basis(rule_id="retraction-cascade-v1")))

def test_drop_quote_cascades_only_when_asked():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "drop_quote", "quotes", "A", "mismatch", Basis(reviewer="m")), cascade=False)
    assert s.records[5]["polarity"] == "favorable" and len(s.records[5]["quotes"]) == 1
    apply_patch(s, Patch(5, "drop_quote", "quotes", "B", "mismatch", Basis(reviewer="m")), cascade=True)
    assert s.records[5]["characterization"] is None
    assert s.records[5]["polarity"] is None
    assert s.records[5]["holding_summary"] is None
    assert s.records[5]["nulled_fields"] == ["characterization", "polarity", "holding_summary"]

def test_drop_quote_does_not_append_field_twice():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "drop_quote", "quotes", "A", "mismatch", Basis(reviewer="m")), cascade=True)
    apply_patch(s, Patch(5, "drop_quote", "quotes", "B", "mismatch", Basis(reviewer="m")), cascade=True)
    # Sequential cascading nulls fields, but no field appears twice in nulled_fields
    nulled = s.records[5]["nulled_fields"]
    assert len(nulled) == len(set(nulled))  # no duplicates
    assert set(nulled) == {"characterization", "polarity", "holding_summary"}

def test_migrate_appends_v2_fields_at_end():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "migrate", "", {"schema_version": 2, "under_30_days": None}, "v2", Basis(rule_id="schema-v2")))
    keys = list(s.records[5].keys())
    assert keys[-2:] == ["schema_version", "under_30_days"] or keys[-1] == "under_30_days"

def test_patch_log_stamps_and_round_trips(tmp_path):
    log = PatchLog(tmp_path / "patches.jsonl")
    p = Patch(5, "set", "polarity", "adverse", "why", Basis(reviewer="m"))
    [stamped] = log.append([p])
    assert stamped.seq == 1 and stamped.patch_id == patch_id(p) and stamped.at
    assert log.read() == [stamped] and log.head() == 1
    assert json.loads((tmp_path / "patches.jsonl").read_text().splitlines()[0])["seq"] == 1
