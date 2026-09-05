import math
from corpus_engine.reader.measure import select_reader, score_candidate
from corpus_engine.reader.model import Budget, ModelPin, Plan, ReadingOutcome, RecordResult, Response, StopReason, Unit, UnitResult


def _out(recs, dropped, spend, cache_hit=False):
    rr = tuple(RecordResult(r["case_id"], r, r.get("extraction_status", "ok"), d, ()) for r, d in zip(recs, dropped))
    u = UnitResult("u", "ok", rr, Response("", 1, 1, spend, {"provider": "P"}, "stop"), cache_hit)
    return ReadingOutcome(Plan("k", (Unit("u", tuple(r["case_id"] for r in recs)),), "cb", ModelPin("m", "f"), Budget(), "w"),
                          [u], [], spend, 1, 1, 2.0, StopReason("done"), {}, "")


_REF = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
        {"case_id": 2, "source": "human", "relevant": True, "polarity": "adverse", "who_was_letting": "commercial_operator"},
        {"case_id": 3, "source": "machine", "relevant": False, "polarity": "irrelevant", "who_was_letting": None}]
_RECS = [{"case_id": 1, "relevant": True, "polarity": "favorable", "who_was_letting": "householder", "quotes": [1, 2, 3], "extraction_status": "ok"},
         {"case_id": 2, "relevant": True, "polarity": "favorable", "who_was_letting": "commercial_operator", "quotes": [1], "extraction_status": "partial"},
         {"case_id": 3, "relevant": False, "polarity": "irrelevant", "quotes": [], "extraction_status": "ok"}]


def test_score_candidate_fields():
    ref = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
           {"case_id": 2, "source": "human", "relevant": True, "polarity": "adverse", "who_was_letting": "commercial_operator"},
           {"case_id": 3, "source": "machine", "relevant": False, "polarity": "irrelevant", "who_was_letting": None}]
    recs = [{"case_id": 1, "relevant": True, "polarity": "favorable", "who_was_letting": "householder", "quotes": [1, 2, 3], "extraction_status": "ok"},
            {"case_id": 2, "relevant": True, "polarity": "favorable", "who_was_letting": "commercial_operator", "quotes": [1], "extraction_status": "partial"},
            {"case_id": 3, "relevant": False, "polarity": "irrelevant", "quotes": [], "extraction_status": "ok"}]
    s = score_candidate(_out(recs, [0, 1, 0], 0.30), ref)
    assert s["fidelity"] == 4 / 5 and s["agreement_human"]["polarity"] == 0.5 and s["agreement_human"]["relevant"] == 1.0
    assert abs(s["agreement_human"]["macro"] - (1.0 + 0.5 + 1.0) / 3) < 1e-9 and s["agreement_machine_irrelevant"] == 1.0
    assert s["accepted"] == 3 and abs(s["cost_per_accepted"] - 0.10) < 1e-9 and s["schema_compliance"] == 1.0


def test_select_reader_rule():
    S = lambda fid, mac, cpa: {"fidelity": fid, "agreement_human": {"macro": mac}, "cost_per_accepted": cpa}
    r = select_reader({"a": S(0.99, 0.90, 0.05), "b": S(0.98, 0.92, 0.01), "c": S(0.90, 0.99, 0.001)})
    assert r["winner"] == "b" and r["eliminated"] == ["c"] and r["shortfall"] is False
    r2 = select_reader({"a": S(0.99, 0.80, 0.05), "b": S(0.98, 0.83, 0.01)})
    assert r2["winner"] == "b" and r2["shortfall"] is True and "highest-agreement" in r2["rule"]
    r3 = select_reader({"a": S(0.5, 0.99, 0.01)})
    assert r3["winner"] is None and r3["eliminated"] == ["a"]


def test_score_candidate_cache_hit_is_unpriced():
    s = score_candidate(_out(_RECS, [0, 1, 0], 0.0, cache_hit=True), _REF)
    assert s["priced"] is False
    assert s["cost_per_accepted"] == math.inf


def test_score_candidate_spend_override_prices_cache_only_rerun():
    s = score_candidate(_out(_RECS, [0, 1, 0], 0.0, cache_hit=True), _REF, spend_usd_override=0.3)
    assert s["priced"] is True
    assert abs(s["cost_per_accepted"] - 0.1) < 1e-9


def test_select_reader_unpriced_never_wins_cost_tiebreak():
    S = lambda mac, cpa, priced: {"fidelity": 0.99, "agreement_human": {"macro": mac}, "cost_per_accepted": cpa, "priced": priced}
    r = select_reader({"a": S(0.90, 0.05, True), "b": S(0.90, 0.0, False)})
    assert r["winner"] == "a" and r["shortfall"] is False
