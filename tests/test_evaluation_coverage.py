"""Measure 5: the unread tail as three scenarios from a bands table; the bands builder."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.evaluation.coverage import tail_coverage
import evaluate as ev


def _table():
    rows = []
    # read batches: band 0.30-0.35 yields 20% (2 of 10 per batch), band 0.25-0.30 yields 10%
    for i in range(30):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|N.Y.", "score": 0.32, "cases": 10,
                     "read": True, "relevant": 2, "sha256": "x"})
    for i in range(30, 60):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|N.Y.", "score": 0.27, "cases": 10,
                     "read": True, "relevant": 1, "sha256": "x"})
    # unread: 100 batches of 10 cases at score 0.15
    for i in range(60, 160):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|Ohio", "score": 0.15, "cases": 10,
                     "read": False, "relevant": None, "sha256": "x"})
    return {"run_id": "cycle-004-shard-02", "map_manifest_sha256": "m", "batches": rows}


def test_scenarios_use_per_case_yield_of_the_lowest_read_band_with_enough_cases():
    c = tail_coverage(_table())
    by = {s.name: s for s in c.scenarios}
    # lowest read band with >= 200 cases is 0.25-0.30 at 10%: 1000 unread cases -> 100
    assert by["lowest-read-band"].estimated_relevant == 100
    assert by["half-lowest-read-band"].estimated_relevant == 50
    assert by["observed-11pct"].estimated_relevant == 110
    assert c.envelope.uncertainty.type == "assumption"
    assert any("adaptively" in s for s in c.envelope.limitations)
    bands = {(b.lo, b.hi): b for b in c.bands}
    assert bands[(0.25, 0.30)].read_cases == 300 and bands[(0.25, 0.30)].relevant == 30
    assert bands[(0.15, 0.20)].unread_cases == 1000


def test_a_table_with_no_read_batches_is_unavailable_not_a_crash():
    t = _table(); t["batches"] = [b for b in t["batches"] if not b["read"]]
    c = tail_coverage(t)
    assert c.scenarios == () and "no read batches" in c.envelope.exclusions[0]


def test_build_bands_reads_the_manifest_units_and_batch_scores():
    manifest = {"run_id": "r", "cells": {"1900-1930|N.Y.": {"units": [
        {"unit_id": "r-batch-001", "cases_read": 2, "relevant_accepted": 1, "status": "ok", "failed": False}]}}}
    batches = [{"batch_id": "r-batch-001", "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                "cases": [{"case_id": 1, "rank_score": 0.4}, {"case_id": 2, "rank_score": 0.2}]},
               {"batch_id": "r-batch-002", "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                "cases": [{"case_id": 3, "rank_score": 0.1}]}]
    t = ev.build_bands(manifest, batches, manifest_sha="m", batch_shas={"r-batch-001": "a", "r-batch-002": "b"})
    rows = {r["batch_id"]: r for r in t["batches"]}
    assert rows["r-batch-001"] == {"batch_id": "r-batch-001", "cell": "1900-1930|N.Y.", "score": 0.3,
                                   "cases": 2, "read": True, "relevant": 1, "sha256": "a"}
    assert rows["r-batch-002"]["read"] is False and rows["r-batch-002"]["relevant"] is None
    assert t["map_manifest_sha256"] == "m" and t["run_id"] == "r"
