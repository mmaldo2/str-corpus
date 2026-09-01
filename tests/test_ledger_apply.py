import json
import pytest
from corpus_engine.ledger import open_ledger, Basis, Patch, MissingBasis
from corpus_engine.domain import load_domain

def _rec(cid, year, pol="favorable", relevant=True):
    return {"case_id": cid, "cite": f"{cid} X", "year": year, "relevant": relevant, "polarity": pol,
            "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "holding_summary": "h",
            "quotes": [{"text": "q", "supports": "polarity"}], "extraction_status": "ok"}

def test_apply_then_view_renders_sorted_snapshot(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    reader = Basis(model="m", prompt_version="v1", run_id="r1")
    res = led.apply([Patch(2, "admit", "", _rec(2, 1900), "verified", reader, cycle="cycle-001"),
                     Patch(1, "admit", "", _rec(1, 1850), "verified", reader, cycle="cycle-001"),
                     Patch(3, "admit", "", _rec(3, 1900, relevant=False), "verified", reader, cycle="cycle-001")],
                    note="seed")
    assert res.replay_ok and len(res.applied) == 3
    v = led.view()
    rendered = v.render()["cycle-001.jsonl"].decode()
    ids = [json.loads(l)["case_id"] for l in rendered.splitlines()]
    assert ids == [1, 2]                      # sorted by year; relevant:false not in file
    assert (tmp_path / "cycle-001.jsonl").read_bytes() == v.render()["cycle-001.jsonl"]
    assert (tmp_path / "patches.jsonl").exists()

def test_apply_is_atomic_and_idempotent(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    bad = [Patch(1, "set", "review.status", "human-adjudicated", "x", Basis(reviewer="m")),
           Patch(1, "set", "polarity", "adverse", "hunch", Basis(rule_id="r"))]
    with pytest.raises(MissingBasis):
        led.apply(bad, note="should not write")
    assert led.view().record(1)["review"]["status"] == "machine"
    good = [Patch(1, "set", "polarity", "adverse", "re-review", Basis(reviewer="m"))]
    led.apply(good, note="once")
    res = led.apply(good, note="twice")
    assert res.applied == [] and len(res.skipped) == 1
    assert led.view().record(1)["polarity"] == "adverse"
    assert led.view().reviewed(1) is True

def test_view_as_of_replays_history(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    led.apply([Patch(1, "set", "polarity", "adverse", "x", Basis(reviewer="m"))], note="flip")
    assert led.view(as_of=1).record(1)["polarity"] == "favorable"
    assert led.view().record(1)["polarity"] == "adverse"
    assert [p.field for p in led.view().history(1)] == ["", "polarity"]
