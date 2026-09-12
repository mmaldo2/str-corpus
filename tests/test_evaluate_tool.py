"""tools/evaluate.py publish: writes json+md together after validation, --force revisions,
the frozen historical fixture pins agreement numbers, the live smoke validates only."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import evaluate as ev
from corpus_engine.evaluation.agreement import agreement

FIX = ROOT / "tests" / "fixtures" / "evaluation"


def test_frozen_fixture_pins_round_s02_3_agreement():
    reg = {"rounds": [{"round_id": "s02-3", "kind": "historical", "queue": "q.json", "checker": "c.json", "claude": "cl.json",
                       "astra": "as.json", "user": "u.json", "selection_rule": "A-F", "user_mode": "card_by_card",
                       "apply_run_ids": ["map-cycle-004-shard-02-round-3", "map-cycle-004-shard-02-round-3b"]}], "dispositions": {}}
    files = {n: json.loads((FIX / f).read_text(encoding="utf-8")) for n, f in
             (("q.json", "s02-3-queue.json"), ("c.json", "s02-3-checker.json"), ("cl.json", "s02-3-claude.json"),
              ("as.json", "s02-3-astra.json"), ("u.json", "s02-3-user.json"))}
    a = agreement(reg, files, ledger_run_ids=["map-cycle-004-shard-02-round-3", "map-cycle-004-shard-02-round-3b"])
    ca = a.rounds[0].pairs["claude-astra"]
    # Pinned from reports/review-round-s02-3-threeway.md (192 cards, 141 agree, 51 disagree)
    # corrected by +7: the sheet's scratch script listed seven C cards as disagreements where
    # Claude set relevant False and Astra adopted the checker's False; both are withdrawals and
    # agree on the substantive label (spec §3.4).
    total = sum(s.n for s in ca.values()); agree = sum(round(s.raw.value * s.n) for s in ca.values())
    assert (total, agree) == (192, 148)
    assert a.envelope.method_version == "agreement-1"


def test_publish_writes_json_and_md_together_and_force_keeps_a_revision(tmp_path, monkeypatch):
    calls = []
    fake = {"schema_version": "1", "evaluation_id": "004-1-abcdefab", "generated_at": "t", "cycle": "004", "code": {},
            "ledger": {"reporting_seq": 1, "content_sha256": "0" * 64, "counts": {"relevant": {"human_reviewed": 1, "machine_only": 1},
                       "favorable": {"human_reviewed": 1, "machine_only": 1}, "favorable_householder": {"human_reviewed": 1, "machine_only": 1}}},
            "gold_recovery": {"envelope": _env(), "tiers": {}, "union": {"entries": 0, "resolved": 0, "signaled": 0, "read": 0, "relevant": 0, "relevant_human": 0, "recovery": _u()}, "misses": [], "unresolved": [], "inventory": {"brief-doctrine": {"entries": 0, "resolved": 0}}},
            "precision": {"envelope": _env(), "sampling_seq": 1, "frame_size": 1, "n": 0, "decided": 0, "unresolved": 0, "precision": _u(), "field_accuracy": {}, "joint_correctness": _u(), "confusion": {}, "subgroups": {}, "revisions": {}, "drift": {}},
            "agreement": {"envelope": _env(), "rounds": [], "excluded": [], "unregistered_run_ids": []},
            "coverage": {"envelope": _env(), "bands": [], "scenarios": []}}
    monkeypatch.setattr(ev, "compute", lambda a: fake)
    out = tmp_path / "evaluation-cycle-004"
    assert ev.main(["publish", "--out", str(out)]) == 0
    assert (tmp_path / "evaluation-cycle-004.json").exists() and (tmp_path / "evaluation-cycle-004.md").exists()
    assert ev.main(["publish", "--out", str(out)]) == 1                                  # refuses to overwrite
    assert ev.main(["publish", "--out", str(out), "--force"]) == 0
    assert (tmp_path / "evaluation-cycle-004-rev1.json").exists() and (tmp_path / "evaluation-cycle-004-rev1.md").exists()
    bad = dict(fake); del bad["coverage"]
    monkeypatch.setattr(ev, "compute", lambda a: bad)
    assert ev.main(["publish", "--out", str(tmp_path / "other")]) == 1
    assert not (tmp_path / "other.json").exists() and not (tmp_path / "other.md").exists()


def _env():
    return {"method_version": "x", "population": "p", "exclusions": [], "uncertainty": {"type": "none", "level": None, "method": "none"}, "limitations": [], "provenance": {"inputs": [], "run_ids": [], "ledger_seqs": {}}}


def _u():
    return {"value": None, "n": 0, "lo": None, "hi": None, "status": "unavailable"}


@pytest.mark.skipif(not (ROOT / "data" / "ledger" / "patches.jsonl").exists(), reason="no committed ledger here")
def test_live_smoke_validates_and_renders(tmp_path):
    from corpus_engine.evaluation import contract, render
    doc = ev.compute(ev.build_parser().parse_args(["publish", "--out", str(tmp_path / "e"), "--no-store"]))
    assert contract.validate(doc) == []
    md = render.markdown(doc)
    assert "## Headline" in md and doc["ledger"]["counts"]["relevant"]["human_reviewed"] > 0
    assert doc["precision"]["precision"]["status"] in ("ok", "unavailable")
