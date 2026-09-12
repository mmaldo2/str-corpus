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


def test_union_first_run_names_the_run_that_first_carried_each_hit():
    records = {1: {"relevant": True}, 2: {"relevant": False}, 3: {"relevant": False}, 7: {"relevant": True}}
    hist = {3: [Patch(3, "set", "relevant", False, "round", Basis(reviewer="u", run_id="r-1b"))]}
    g = gold_recovery(_gold(), _View(records, hist, reviewed={1}),
                      signaled={1: True, 2: True, 3: True, 4: False, 7: True},
                      read_units={1: "run-a", 2: "run-a", 3: "run-b", 7: "run-a"})
    assert g.union.first_run == {1: "run-a", 7: "run-a"}


def test_first_run_table_is_rendered_under_the_union_funnel():
    from corpus_engine.evaluation import render
    from corpus_engine.evaluation.types import as_dict
    records = {1: {"relevant": True}, 7: {"relevant": True}}
    g = gold_recovery(_gold(), _View(records, reviewed={1}),
                      signaled={1: True, 7: True},
                      read_units={1: "run-a", 7: "run-a"})
    doc = _minimal_doc(gold_recovery=as_dict(g))
    md = render.markdown(doc)
    assert "| case | first read by |" in md
    assert "| 1 | run-a |" in md and "| 7 | run-a |" in md


def test_gold_recovery_provenance_carries_the_gold_files_hash():
    g = gold_recovery(_gold(), _View({}), signaled={}, read_units={},
                      hashes={"data/gold/gold.jsonl": "cafebabe" * 8})
    entry = next(p for p in g.envelope.provenance.inputs if p[2] == "gold")
    assert entry == ("data/gold/gold.jsonl", "cafebabe" * 8, "gold")


def _minimal_doc(**over):
    from corpus_engine.evaluation.types import as_dict
    from corpus_engine.evaluation.gold import GoldRecovery, TierFunnel
    from corpus_engine.evaluation.precision import Precision
    from corpus_engine.evaluation.agreement import Agreement
    from corpus_engine.evaluation.coverage import Coverage
    from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, UNAVAILABLE

    def env(v):
        return as_dict(Envelope(v, "pop", (), Uncertainty("none", None, "none"), (), Provenance()))
    tf = as_dict(TierFunnel(0, 0, 0, 0, 0, 0, UNAVAILABLE))
    doc = {"schema_version": "1", "evaluation_id": "e", "generated_at": "t", "cycle": "004",
          "code": {"git_revision": "?"},
          "ledger": {"reporting_seq": 1, "content_sha256": "0" * 64,
                     "counts": {"relevant": {"human_reviewed": 0, "machine_only": 0},
                                "favorable": {"human_reviewed": 0, "machine_only": 0},
                                "favorable_householder": {"human_reviewed": 0, "machine_only": 0}}},
          "gold_recovery": as_dict(GoldRecovery(Envelope("g", "pop", (), Uncertainty("sampling", 0.95, "wilson"), (), Provenance()),
                                                {}, TierFunnel(0, 0, 0, 0, 0, 0, UNAVAILABLE), (), (), {"brief-doctrine": {"entries": 0, "resolved": 0}})),
          "precision": as_dict(Precision(Envelope("p", "pop", (), Uncertainty("none", None, "none"), (), Provenance()),
                                         1, 1, 0, 0, 0, UNAVAILABLE, {}, UNAVAILABLE, {}, {}, {}, {})),
          "agreement": as_dict(Agreement(Envelope("a", "pop", (), Uncertainty("sampling", 0.95, "wilson"), (), Provenance()), (), (), ())),
          "coverage": as_dict(Coverage(Envelope("c", "pop", (), Uncertainty("assumption", None, "scenarios"), (), Provenance()), (), ()))}
    doc.update(over)
    return doc


def test_a_machine_relevant_false_patch_is_reader_negative_not_withdrawn():
    gold = [
        {"cite": "1", "cite_norm": "1", "tier": "treatise", "case_id": 1},
        {"cite": "2", "cite_norm": "2", "tier": "treatise", "case_id": 2},
    ]
    hist = {
        1: [Patch(1, "set", "relevant", False, "map", Basis(model="m", run_id="run-a"))],  # machine basis, no reviewer
        2: [Patch(2, "set", "relevant", False, "round", Basis(reviewer="u", run_id="run-b"))],  # reviewer basis
    }
    g = gold_recovery(gold, _View({1: {"relevant": False}, 2: {"relevant": False}}, hist),
                      signaled={1: True, 2: True}, read_units={1: "run-a", 2: "run-b"})
    lost = {m.case_id: m.lost_at for m in g.misses}
    assert lost[1] == "reader-negative"
    assert lost[2] == "withdrawn"
