"""Ledger side of the parallel-report merge (spec 2026-10-04 section 6.6)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.duplicates import DUPLICATE_FIELD, RULE_ID, precedence, reconcile
from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.mapper.queue import reasons_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import apply_map_review as amr      # noqa: E402
import draw_audit_sample as das     # noqa: E402

READER = Basis(model="m", prompt_version="v", run_id="r")
USER = Basis(reviewer="marcus", run_id="round-x")
MERGE = Basis(rule_id=RULE_ID, run_id="merge-x")


def _rec(cid, *, relevant=True, polarity="favorable", quotes=1):
    return {"case_id": cid, "cite": f"{cid} X", "year": 1900, "jurisdiction": "N.Y.",
            "relevant": relevant, "polarity": polarity if relevant else None,
            "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "holding_summary": "h",
            "quotes": [{"text": f"q{i}", "supports": ["polarity"], "status": "verified"}
                       for i in range(quotes)],
            "extraction_status": "ok"}


def _ledger(tmp_path, recs):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(r["case_id"], "admit", "", r, "v", READER, cycle="cycle-004") for r in recs],
              note="seed")
    return led


def _judged():
    return tuple(load_domain().judged_fields)


def test_a_duplicate_copy_renders_and_leaves_every_count(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2), _rec(3, polarity="adverse")])
    res = led.apply([Patch(2, "set", DUPLICATE_FIELD, 1, "parallel report of 1", MERGE,
                           cycle="cycle-004")], note="merge")
    assert res.replay_ok and not res.rejected
    v = led.view()
    assert list(v.record(2))[-1] == DUPLICATE_FIELD and v.record(2)[DUPLICATE_FIELD] == 1
    t = v.counts().total
    assert t.human_reviewed + t.machine_only == 2
    fav = v.counts(polarity="favorable").total
    assert fav.human_reviewed + fav.machine_only == 1
    assert sum(c.human_reviewed + c.machine_only for c in v.matrix().cells.values()) == 1
    assert 2 in {r["case_id"] for r in v.records()}       # still in the ledger, out of the counts


def test_reviewed_ids_is_reviewed_for_every_case(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2)])
    led.apply([Patch(2, "set", "polarity", "adverse", "user", USER)], note="review")
    v = led.view()
    assert v.reviewed_ids() == {c for c in v.state.order if v.reviewed(c)} == {2}


def test_precedence_orders_relevant_then_reviewed_then_quotes_then_official(tmp_path):
    led = _ledger(tmp_path, [_rec(1, quotes=1), _rec(2, quotes=3), _rec(3, relevant=False),
                             _rec(4, quotes=1)])
    led.apply([Patch(4, "set", "polarity", "favorable", "user", USER)], note="review")
    v = led.view()
    key = precedence(v, v.reviewed_ids())
    m = lambda cid, official=False: SimpleNamespace(case_id=cid, official=official)   # noqa: E731
    order = sorted([m(9, official=True), m(3), m(1), m(2), m(4), m(8)], key=key)
    assert [x.case_id for x in order] == [4, 2, 1, 3, 9, 8]


def test_reconcile_patches_a_machine_copy_and_lists_disagreements_for_the_user(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2),                    # plain pair: patch 2
                             _rec(4), _rec(5, relevant=False),    # relevance disagreement
                             _rec(6), _rec(7),                    # human value differs
                             _rec(8)])                            # only the winner is in the ledger
    led.apply([Patch(7, "set", "polarity", "adverse", "user", USER)], note="review")
    merges = {2: 1, 5: 4, 7: 6, 99: 8}
    res = reconcile(led.view(), merges, run_id="merge-x", judged=_judged())
    assert [(p.case_id, p.field, p.new, p.basis.rule_id) for p in res.patches] == \
        [(2, DUPLICATE_FIELD, 1, RULE_ID)]
    assert [(u["winner"], u["reason"]) for u in res.for_user] == [(4, "relevant"), (6, "human-value")]
    assert res.for_user[1]["detail"] == {"7": {"polarity": ["adverse", "favorable"]}}
    led.apply(res.patches, note="merge")
    assert reconcile(led.view(), merges, run_id="merge-x", judged=_judged()).patches == []


def test_the_queue_the_audit_frame_and_the_drift_check_treat_a_copy_right(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2)])
    led.apply([Patch(2, "set", DUPLICATE_FIELD, 1, "copy", MERGE, cycle="cycle-004")], note="merge")
    v = led.view()
    kw = {"disagreements": (), "fuzzy_needs_human": False}
    assert reasons_for(dict(v.record(2), under_thirty_days="yes"), **kw) == ()
    assert reasons_for(dict(v.record(1), under_thirty_days="yes"), **kw) != ()
    assert das._in_frame(v, 1) and not das._in_frame(v, 2)
    manifest = {"records": [{"case_id": 2, "record": {k: _rec(2)[k] for k in
                                                       ("relevant", "polarity", "who_was_letting")}}]}
    assert amr.drift_check(manifest, v.state.records) == []


def test_a_relevance_disagreement_group_still_patches_the_other_relevant_copy(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2), _rec(3, relevant=False)])
    res = reconcile(led.view(), {2: 1, 3: 1}, run_id="merge-x", judged=_judged())
    assert [(p.case_id, p.field, p.new) for p in res.patches] == [(2, DUPLICATE_FIELD, 1)]
    assert [(u["winner"], u["reason"]) for u in res.for_user] == [(1, "relevant")]


def test_a_relevance_disagreement_group_leaves_a_differing_human_value_copy_counted(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2), _rec(3, relevant=False)])
    led.apply([Patch(2, "set", "polarity", "adverse", "user", USER)], note="review")
    res = reconcile(led.view(), {2: 1, 3: 1}, run_id="merge-x", judged=_judged())
    assert res.patches == []
    assert [(u["winner"], u["reason"]) for u in res.for_user] == [(1, "relevant")]
