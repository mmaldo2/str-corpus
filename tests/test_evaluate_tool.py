"""tools/evaluate.py publish: writes json+md together after validation, --force revisions,
the frozen historical fixture pins agreement numbers, the live smoke validates only."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import evaluate as ev
import apply_map_review as ap
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


def test_load_registry_files_hashes_every_named_file():
    reg = {"rounds": [{"round_id": "s02-3", "kind": "historical", "queue": "s02-3-queue.json",
                       "checker": "s02-3-checker.json", "claude": "s02-3-claude.json",
                       "astra": "s02-3-astra.json", "user": "s02-3-user.json"}]}
    files, hashes = ev.load_registry_files(reg, FIX)
    import hashlib
    for fname in ("s02-3-queue.json", "s02-3-checker.json", "s02-3-claude.json",
                  "s02-3-astra.json", "s02-3-user.json"):
        assert hashes[fname] == hashlib.sha256((FIX / fname).read_bytes()).hexdigest()
    assert set(files) == set(hashes)


def test_load_registry_files_reads_an_audit_html_user_entry_through_read_audit_state(tmp_path):
    import make_map_review as mmr
    queue = {"run_id": "audit-cycle-004", "cap": 1, "titles": {"H": "Audit sample"}, "deferred": [],
             "sections": {"H": [{"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"],
                                 "cite": "9 A. 9", "name": "A v. B", "court": "Ct.", "jur": "N.Y.", "year": 1900}]}}
    (tmp_path / "aq.json").write_text(json.dumps(queue), encoding="utf-8")
    html_path, _ = mmr.build_audit_page(queue, tmp_path / "audit", opinions={9: "she let the room"},
                                        claude=[], astra=[])
    html = html_path.read_text(encoding="utf-8")
    state = [{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "initial_value": True,
             "locked_at": "t", "revised_reason": None, "note": ""},
             {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "initial_value": "favorable",
             "locked_at": "t", "revised_reason": None, "note": ""},
             {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "householder",
             "initial_value": "householder", "locked_at": "t", "revised_reason": None, "note": ""}]
    saved = html.replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps(state) + '</script>')
    html_path.write_text(saved, encoding="utf-8")
    registry = {"rounds": [{"round_id": "audit", "kind": "audit", "queue": "aq.json", "checker": None,
                            "claude": None, "astra": None, "user": "audit.html"}]}
    files, hashes = ev.load_registry_files(registry, tmp_path)
    entries = files["audit.html"]
    assert entries[0]["field"] == "relevant" and entries[0]["initial_value"] is True
    assert entries[1]["field"] == "polarity" and entries[1]["initial_value"] == "favorable"
    assert "audit.html" in hashes and "aq.json" in hashes


def test_load_registry_files_reads_a_non_audit_html_user_entry_through_read_page(tmp_path):
    """The historical rounds' saved-page user entries (s02-1, s02-3) are `kind: historical`,
    not audit, and must keep going through `apply_map_review.read_page` - the branch added
    for the audit page must not change this path."""
    from corpus_engine.domain import load_domain
    fields = tuple(load_domain().judged_fields) + ap.EXTRA_FIELDS
    queue = {"run_id": "r1", "sections": {"A": [{"case_id": 1, "decide_field": fields[0]}]}}
    (tmp_path / "q.json").write_text(json.dumps(queue), encoding="utf-8")
    decisions = [{"case_id": 1, "field": fields[0], "decision": "unsure", "note": "x"}]
    html = ('<html><body><script type="application/json" id="review-state">'
           + json.dumps(decisions) + '</script></body></html>')
    (tmp_path / "u.html").write_text(html, encoding="utf-8")
    registry = {"rounds": [{"round_id": "r1", "kind": "historical", "queue": "q.json", "checker": None,
                            "claude": None, "astra": None, "user": "u.html"}]}
    files, hashes = ev.load_registry_files(registry, tmp_path)
    assert files["u.html"] == [{"case_id": 1, "field": fields[0], "decision": "unsure",
                               "value": None, "note": "x"}]


def _env():
    return {"method_version": "x", "population": "p", "exclusions": [], "uncertainty": {"type": "none", "level": None, "method": "none"}, "limitations": [], "provenance": {"inputs": [], "run_ids": [], "ledger_seqs": {}}}


def _u():
    return {"value": None, "n": 0, "lo": None, "hi": None, "status": "unavailable"}


@pytest.mark.skipif(not (ROOT / "data" / "ledger" / "patches").exists(), reason="no committed ledger here")
def test_live_smoke_validates_and_renders(tmp_path):
    from corpus_engine.evaluation import contract, render
    doc = ev.compute(ev.build_parser().parse_args(["publish", "--out", str(tmp_path / "e"), "--no-store"]))
    assert contract.validate(doc) == []
    md = render.markdown(doc)
    assert "## Headline" in md and doc["ledger"]["counts"]["relevant"]["human_reviewed"] > 0
    assert doc["precision"]["precision"]["status"] in ("ok", "unavailable")


def test_merges_from_file_reads_loser_to_winner_and_tolerates_a_missing_file(tmp_path):
    f = tmp_path / "merges.jsonl"
    f.write_text('{"loser": 5, "winner": 2, "score": 0.9, "method": "m"}\n\n'
                 '{"loser": 7, "winner": 3, "score": 0.8, "method": "m"}\n', encoding="utf-8")
    assert ev.merges_from_file(f) == {5: 2, 7: 3}
    assert ev.merges_from_file(tmp_path / "none.jsonl") == {}
