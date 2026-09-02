import json
import pytest
from corpus_engine.ledger import open_ledger, Basis, Patch, MissingBasis
from corpus_engine.ledger.fold import State, apply_patch
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

def test_drop_quote_alone_does_not_count_as_reviewed(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    led.apply([Patch(1, "drop_quote", "quotes", "q", "mismatch", Basis(reviewer="m"))], note="drop")
    assert led.view().reviewed(1) is False
    led.apply([Patch(1, "set", "review.status", "human-adjudicated", "x", Basis(reviewer="m"))], note="status")
    assert led.view().reviewed(1) is True

def test_view_as_of_replays_history(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    led.apply([Patch(1, "set", "polarity", "adverse", "x", Basis(reviewer="m"))], note="flip")
    assert led.view(as_of=1).record(1)["polarity"] == "favorable"
    assert led.view().record(1)["polarity"] == "adverse"
    assert [p.field for p in led.view().history(1)] == ["", "polarity"]

def test_apply_validates_on_a_fresh_replay_not_a_mutated_trial(tmp_path):
    # A caller that builds its trial state by shallow-copying a cached view's
    # dicts (the old, wrong pattern from the three pipeline scripts) mutates
    # the record dicts the ledger's memoized head view still points at, since
    # a shallow dict copy shares the nested record dicts, not new ones. apply()
    # must not trust that possibly-mutated cached view for its own validation
    # pass -- it must re-replay from the log, the only truth.
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850, pol="unclear"), "v",
                     Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    trial = State(records=dict(led.view().state.records), order=list(led.view().state.order),
                  cycles=dict(led.view().state.cycles), in_file=dict(led.view().state.in_file))
    patch = Patch(1, "set", "polarity", "favorable", "x", Basis(reviewer="m"))
    apply_patch(trial, patch)                  # mutates the shared record dict in place
    led.apply([patch], note="t")
    assert led.view().history(1)[-1].old == "unclear"
