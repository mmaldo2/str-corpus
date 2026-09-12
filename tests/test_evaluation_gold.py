"""Measure 1: gold recovery over the eligible frame with a per-stage funnel."""
from corpus_engine.evaluation.gold import gold_recovery
from corpus_engine.ledger.types import Basis, Patch


class _View:
    """The slice of LedgerView the measure reads: records, history, reviewed."""
    def __init__(self, records, history=None, reviewed=()):
        self.state = type("S", (), {})(); self.state.records = records
        self._h = history or {}; self._r = set(reviewed)
    def history(self, cid): return self._h.get(cid, [])
    def reviewed(self, cid): return cid in self._r


def _gold():
    return [
        {"cite": "1 A. 1", "cite_norm": "1 a 1", "tier": "brief", "domain": "letting", "case_id": 1},
        {"cite": "2 A. 2", "cite_norm": "2 a 2", "tier": "brief", "domain": "letting", "case_id": 2},
        {"cite": "3 A. 3", "cite_norm": "3 a 3", "tier": "brief", "domain": "letting", "case_id": 3},
        {"cite": "4 A. 4", "cite_norm": "4 a 4", "tier": "brief", "domain": "letting", "case_id": 4},
        {"cite": "5 A. 5", "cite_norm": "5 a 5", "tier": "brief", "domain": "letting", "case_id": None},
        {"cite": "6 A. 6", "cite_norm": "6 a 6", "tier": "brief", "domain": "doctrine", "case_id": 6},
        {"cite": "7 A. 7", "cite_norm": "7 a 7", "tier": "treatise", "domain": None, "case_id": 7},
        {"cite": "7 A. 7", "cite_norm": "7 a 7", "tier": "treatise", "domain": None, "case_id": 7},  # duplicate
    ]


def test_funnel_places_every_miss_at_the_stage_it_was_lost():
    records = {1: {"relevant": True}, 2: {"relevant": False}, 3: {"relevant": False}, 7: {"relevant": True}}
    hist = {3: [Patch(3, "set", "relevant", False, "round", Basis(reviewer="u", run_id="r-1b"))]}
    g = gold_recovery(_gold(), _View(records, hist, reviewed={1}),
                      signaled={1: True, 2: True, 3: True, 4: False, 7: True},
                      read_units={1: "run-a", 2: "run-a", 3: "run-b", 7: "run-a"})
    bl = g.tiers["brief-letting"]
    assert (bl.entries, bl.resolved, bl.signaled, bl.read, bl.relevant, bl.relevant_human) == (5, 4, 3, 3, 1, 1)
    assert bl.recovery.value == 0.25 and bl.recovery.n == 4
    tr = g.tiers["treatise"]
    assert (tr.entries, tr.resolved, tr.relevant) == (1, 1, 1)          # the duplicate row counted once
    assert g.union.resolved == 5 and g.union.relevant == 2
    lost = {m.case_id: m.lost_at for m in g.misses}
    assert lost == {2: "reader-negative", 3: "withdrawn", 4: "unsignaled"}
    assert [u["cite"] for u in g.unresolved] == ["5 A. 5"]
    assert g.inventory["brief-doctrine"]["entries"] == 1
    assert "recovery" in g.envelope.population and g.envelope.uncertainty.method == "wilson"
    w = next(m for m in g.misses if m.case_id == 3)
    assert "u" in w.detail and "r-1b" in w.detail


def test_read_but_unread_and_read_failed_are_distinct():
    gold = [{"cite": "1", "cite_norm": "1", "tier": "treatise", "case_id": 1},
            {"cite": "2", "cite_norm": "2", "tier": "treatise", "case_id": 2}]
    g = gold_recovery(gold, _View({}), signaled={1: True, 2: True}, read_units={2: "read-failed"})
    lost = {m.case_id: m.lost_at for m in g.misses}
    assert lost == {1: "unread", 2: "read-failed"}
