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
    # prompt_version must name a known codebook (fold.supported_fields raises on an
    # unrecognised non-empty version per review finding 1) -- "mapper-v1" here is just a
    # real value, not the thing under test.
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="mapper-v1", run_id="r"), cycle="cycle-001")], note="seed")
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

def test_apply_honors_patch_cascade_flag_through_the_log(tmp_path):
    # cascade is now an explicit Patch field, replayed straight through
    # apply()'s validation loop and Ledger._replay -- no why-prefix sniffing.
    led = open_ledger(tmp_path, domain=load_domain())
    # prompt_version must name a known codebook (fold.supported_fields raises on an
    # unrecognised non-empty version per review finding 1) -- "mapper-v1" here is just a
    # real value, not the thing under test.
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="mapper-v1", run_id="r"), cycle="cycle-001"),
               Patch(2, "admit", "", _rec(2, 1850), "v", Basis(model="m", prompt_version="mapper-v1", run_id="r"), cycle="cycle-001")],
              note="seed")
    led.apply([Patch(1, "drop_quote", "quotes", "q", "mismatch", Basis(reviewer="m"), cascade=False)], note="no cascade")
    rec1 = led.view().record(1)
    assert rec1["polarity"] == "favorable" and rec1["characterization"] == "lodging"
    assert "nulled_fields" not in rec1
    led.apply([Patch(2, "drop_quote", "quotes", "q", "mismatch", Basis(reviewer="m"), cascade=True)], note="cascade")
    rec2 = led.view().record(2)
    assert rec2["polarity"] is None and rec2["characterization"] is None and rec2["holding_summary"] is None
    assert set(rec2["nulled_fields"]) == {"polarity", "characterization", "holding_summary"}


def test_a_reader_patch_over_a_human_decision_is_rejected_through_apply(tmp_path, monkeypatch):
    """D2 end to end through `apply`, which is where the slice will meet it (review finding
    1 and 2): the seqs the append will assign are stamped before the trial fold, so the rule
    is live in the validation and in `--dry-run`; the refusal reaches the caller as
    `rejected`; the patch is not in `applied`; and the human value stands.

    A scratch ledger numbers its patches from 1, so the real baseline (42984) would
    grandfather everything here - the constant is moved to 0 so these patches are above it,
    exactly as slice 3's will be against the real log."""
    monkeypatch.setattr("corpus_engine.ledger.fold.PROTECTION_FROM_SEQ", 0)
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v",
                     Basis(model="m", prompt_version="mapper-v1", run_id="r"),
                     cycle="cycle-001")], note="seed")
    led.apply([Patch(1, "set", "polarity", "adverse", "round 1", Basis(reviewer="mmaldo2"))],
              note="review")
    reader = Basis(model="claude-opus-5@claude-cli", prompt_version="mapper-v3:f92016681314",
                   run_id="cycles-001-003-reread")
    p = Patch(1, "set", "polarity", "favorable", "re-read", reader)

    dry = led.apply([p], note="re-read", dry_run=True)       # the only pre-flight a tool has
    assert dry.applied == [] and len(dry.rejected) == 1
    assert led.view().record(1)["polarity"] == "adverse"     # and nothing was written

    res = led.apply([p], note="re-read")
    assert res.applied == [] and res.replay_ok               # not reported as applied
    assert len(res.rejected) == 1 and res.skipped == []
    assert res.rejected[0]["field"] == "polarity" and res.rejected[0]["attempted"] == "favorable"
    assert res.rejected[0]["standing"] == "adverse" and res.rejected[0]["historical"] is False
    assert res.rejected[0]["by_rule"] == "reviewer-protection"
    v = led.view()
    assert v.record(1)["polarity"] == "adverse"              # the human's value stands
    assert v.record(1)["review"]["flags"] == ["needs-review:polarity"]
    assert v.conflicts(1)[1][0]["at"] == v.as_of
    # The patch IS in the log: append-only, and the replay refuses it the same way every time.
    assert [q.op for q in v.history(1)] == ["admit", "set", "set"]
    assert (tmp_path / "cycle-001.jsonl").read_bytes() == v.render()["cycle-001.jsonl"]


def test_provisional_seqs_are_the_seqs_the_append_assigns(tmp_path, monkeypatch):
    """The mechanism behind the test above: without the stamping, `seq` is 0 for every
    not-yet-appended patch and D2 reads it as pre-baseline history."""
    from corpus_engine.ledger.log import provisional_seqs
    monkeypatch.setattr("corpus_engine.ledger.fold.PROTECTION_FROM_SEQ", 0)
    led = open_ledger(tmp_path, domain=load_domain())
    ps = [Patch(1, "admit", "", _rec(1, 1850), "v",
                Basis(model="m", prompt_version="mapper-v1", run_id="r"), cycle="cycle-001"),
          Patch(1, "set", "polarity", "adverse", "round 1", Basis(reviewer="m"))]
    assert [p.seq for p in ps] == [0, 0]
    assert [p.seq for p in provisional_seqs(ps, led.log.head())] == [1, 2]
    res = led.apply(ps, note="seed")
    assert [p.seq for p in res.applied] == [1, 2]
    assert [p.seq for p in provisional_seqs(ps, led.log.head())] == [3, 4]
