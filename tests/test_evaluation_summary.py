"""Composition into one Evaluation, the JSON contract, and the markdown report."""
import json
from pathlib import Path
from corpus_engine.evaluation import contract, render, summary
from corpus_engine.evaluation.types import UNAVAILABLE, Estimate, Envelope, Uncertainty, Provenance
from corpus_engine.evaluation.gold import GoldRecovery, TierFunnel
from corpus_engine.evaluation.precision import Precision
from corpus_engine.evaluation.agreement import Agreement
from corpus_engine.evaluation.coverage import Coverage, Band, Scenario


def _env(v="x-1"):
    return Envelope(v, "pop", ("ex",), Uncertainty("none", None, "none"), ("lim",), Provenance())


class _Counts:
    def __init__(self, h, m):
        self.total = type("T", (), {"human_reviewed": h, "machine_only": m})()


class _View:
    def counts(self, **f):
        if f.get("who_was_letting"): return _Counts(161, 236)
        if f.get("polarity"): return _Counts(754, 1200)
        return _Counts(1509, 2842)


def _inputs():
    tf = TierFunnel(5, 4, 3, 3, 1, 1, Estimate(0.25, 4, 0.05, 0.7, "ok"))
    gold = GoldRecovery(_env("gold-recovery-1"), {"brief-letting": tf, "treatise": tf}, tf, (), (), {"brief-doctrine": {"entries": 1, "resolved": 1}})
    prec = Precision(_env("precision-1"), 100, 2842, 150, 0, 0, UNAVAILABLE, {"polarity": UNAVAILABLE, "who_was_letting": UNAVAILABLE}, UNAVAILABLE, {}, {}, {}, {})
    agr = Agreement(_env("agreement-1"), (), (), ())
    cov = Coverage(_env("coverage-1"), (Band(0.25, 0.30, 300, 30, 0),), (Scenario("lowest-read-band", "a", 100),))
    return summary.Inputs(gold, prec, agr, cov)


def test_evaluate_composes_counts_and_validates_against_the_schema():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=51234, content_sha256="ab" * 32,
                          code={"git_revision": "deadbeef", "command": "tools/evaluate.py publish", "python": "3.12", "packages": {}})
    doc = summary.to_json(ev)
    assert doc["schema_version"] == "1" and doc["cycle"] == "004"
    assert doc["evaluation_id"] == "004-51234-abababab"
    assert doc["ledger"]["counts"]["relevant"] == {"human_reviewed": 1509, "machine_only": 2842}
    assert doc["ledger"]["counts"]["favorable_householder"]["human_reviewed"] == 161
    assert doc["precision"]["precision"]["status"] == "unavailable"
    assert doc["coverage"]["scenarios"][0]["estimated_relevant"] == 100
    assert contract.validate(doc) == []
    json.dumps(doc)                                     # serialisable


def test_validate_names_missing_and_mistyped_keys():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=1, content_sha256="0" * 64, code={})
    doc = summary.to_json(ev)
    del doc["gold_recovery"]["tiers"]
    doc["coverage"]["scenarios"] = "not a list"
    problems = contract.validate(doc)
    assert "gold_recovery.tiers" in problems and "coverage.scenarios" in problems


def test_markdown_has_the_headline_table_and_one_section_per_measure():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=1, content_sha256="0" * 64, code={})
    md = render.markdown(summary.to_json(ev))
    assert md.startswith("# Evaluation of the corpus")
    assert "| measure | headline | denominator | uncertainty |" in md
    for h in ("## 1. Gold recovery", "## 2. Machine-tier precision", "## 3. Field accuracy", "## 4. Reviewer agreement", "## 5. Unread-tail coverage", "## Rounds registry"):
        assert h in md
    assert "unavailable" in md and "4,351" in md      # counts formatted with thousands separators


def test_ledger_content_hash_is_over_lf_bytes_in_a_fixed_order(tmp_path):
    (tmp_path / "patches.jsonl").write_bytes(b'{"a":1}\r\n')
    (tmp_path / "cycle-001.jsonl").write_bytes(b'{"b":2}\n')
    h1 = summary.ledger_content_sha256(tmp_path)
    (tmp_path / "patches.jsonl").write_bytes(b'{"a":1}\n')
    assert summary.ledger_content_sha256(tmp_path) == h1        # CRLF and LF hash the same
