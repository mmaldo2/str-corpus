import pytest
from corpus_engine.ledger.types import Basis, Patch, TierCount, UNSET

def test_basis_kinds_and_judging_authority():
    assert Basis(reviewer="mmaldo2").kind() == "human"
    assert Basis(model="m", prompt_version="v1", run_id="r").kind() == "reader"
    assert Basis(rule_id="slice-of-life").kind() == "rule"
    assert Basis().kind() == "none"
    assert Basis(reviewer="x").can_judge()
    assert Basis(model="m", prompt_version="v1", run_id="r").can_judge()
    assert not Basis(model="m").can_judge()
    assert not Basis(rule_id="r").can_judge()

def test_patch_round_trips_through_json():
    p = Patch(case_id=1, op="set", field="polarity", new="adverse", why="re-review",
              basis=Basis(reviewer="mmaldo2"), seq=7, at="2026-09-01T00:00:00", patch_id="abc", old="favorable")
    assert Patch.from_json(p.to_json()) == p
    q = Patch(case_id=1, op="admit", field="", new={"case_id": 1}, why="x", basis=Basis())
    assert q.old is UNSET and "old" not in q.to_json()

def test_tier_count_cannot_be_blended():
    t = TierCount(human_reviewed=138, machine_only=572)
    assert t.as_claim("relevant cases") == "710 relevant cases (138 human-reviewed, 572 machine-only; lower bound)"
    with pytest.raises(TypeError):
        int(t)
    with pytest.raises(TypeError):
        t + t
