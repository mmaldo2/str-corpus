"""The audit apply: explicit set patches on all three fields, drift refusal, outcomes file."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import apply_map_review as ap
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger as real_open_ledger
from corpus_engine.ledger.types import Basis, Patch


def _rec(cid, **o):
    r = {"case_id": cid, "cite": f"{cid} A. 1", "name": "n", "court": "c", "jurisdiction": "N.Y.", "year": 1900,
         "era_partition": "1900-1930", "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
         "characterization": None, "under_thirty_days": None, "owner_freedom_characterization": None,
         "restriction_nature": None, "duration_of_occupancy": None, "quotes": [], "holding_summary": "h",
         "extraction_status": "ok", "review": {"status": "machine", "flags": ["needs-review:polarity"], "notes": []}}
    r.update(o); return r


def _manifest(records):
    return {"ledger_head_seq": 1, "frame_size": 3, "seed": 1, "n": len(records),
            "records": [{"case_id": r["case_id"], "record": {k: r[k] for k in ("relevant", "polarity", "who_was_letting")}}
                        for r in records]}


def _entry(cid, f, v, initial=None, reason=None, decision="set"):
    return {"case_id": cid, "field": f, "decision": decision, "value": v, "initial_value": v if initial is None else initial,
            "locked_at": "t", "revised_reason": reason, "note": ""}


def test_audit_patches_confirm_equal_values_with_reviewer_provenance_and_withdraw(tmp_path):
    dom = load_domain(); led = real_open_ledger(tmp_path / "ledger", domain=dom)
    recs = [_rec(1), _rec(2, polarity="mixed"), _rec(3)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    view = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "favorable"), _entry(1, "who_was_letting", "householder"),
               _entry(2, "relevant", True), _entry(2, "polarity", "adverse", initial="mixed", reason="the holding"), _entry(2, "who_was_letting", "unclear"),
               _entry(3, "relevant", False)]
    patches = ap.audit_patches(entries, view.state.records, "mmaldo2", run_id="audit-cycle-004")
    sets = [(p.case_id, p.field, p.new) for p in patches if p.op == "set" and p.field in ("relevant", "polarity", "who_was_letting")]
    assert (1, "relevant", True) in sets and (1, "polarity", "favorable") in sets and (1, "who_was_letting", "householder") in sets
    assert (2, "polarity", "adverse") in sets and (3, "relevant", False) in sets and (3, "polarity", None) in sets
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == "audit-cycle-004" for p in patches)
    real_open_ledger(tmp_path / "ledger", domain=dom).apply(patches, note="audit")
    after = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    prov1 = after.provenance(1)
    assert prov1["relevant"] == "human" and prov1["polarity"] == "human" and prov1["who_was_letting"] == "human"
    assert after.reviewed(1) and after.reviewed(3) and after.record(3)["relevant"] is False
    assert after.record(1)["review"]["flags"] == []                            # needs-review:polarity cleared
    notes = "\n".join(after.record(2)["review"]["notes"])
    assert "revised after reveal from 'mixed'" in notes and "the holding" in notes and "blind reading" in notes


def test_drift_check_names_changed_records():
    recs = {1: _rec(1), 2: _rec(2, polarity="adverse")}
    man = _manifest([_rec(1), _rec(2)])                                     # draw-time polarity favorable on both
    assert ap.drift_check(man, recs) == [2]


def test_main_refuses_assisted_by_and_drift_and_writes_outcomes(tmp_path, monkeypatch):
    import sys as _sys
    dom = load_domain(); ledger_dir = tmp_path / "ledger"; led = real_open_ledger(ledger_dir, domain=dom)
    recs = [_rec(1), _rec(2)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    out = tmp_path / "audit"; out.mkdir()
    (out / "sample-manifest.json").write_text(json.dumps(_manifest(recs)), encoding="utf-8")
    queue = {"run_id": "audit-cycle-004", "sections": {"H": [{"case_id": 1, "decide_fields": ["relevant", "polarity", "who_was_letting"]},
                                                              {"case_id": 2, "decide_fields": ["relevant", "polarity", "who_was_letting"]}]}}
    (out / "audit-queue.json").write_text(json.dumps(queue), encoding="utf-8")
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "favorable"), _entry(1, "who_was_letting", "householder"),
               _entry(2, "relevant", None, decision="unresolved")]
    import make_map_review as mmr
    html_path, _ = mmr.build_audit_page(dict(queue, cap=2, titles={"H": "t"}, deferred=[],
                                             sections={"H": [dict(c, cite="x") for c in queue["sections"]["H"]]}),
                                        out / "page", opinions={1: "a", 2: "b"}, claude=[], astra=[], checker={})
    html = html_path.read_text(encoding="utf-8").replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps(entries) + '</script>')
    saved = out / "saved.html"; saved.write_text(html, encoding="utf-8")
    for n in ("claude", "astra"):
        (out / f"{n}.json").write_text(json.dumps([{"case_id": 1, "field": "relevant", "decision": "set", "value": True, "note": n}]), encoding="utf-8")
    monkeypatch.setattr(ap, "open_ledger", lambda *a, **kw: real_open_ledger(ledger_dir, domain=kw.get("domain") or dom))
    base = ["apply_map_review.py", "--audit", "--saved", str(saved), "--queue", str(out / "audit-queue.json"),
            "--sample", str(out / "sample-manifest.json"), "--claude", str(out / "claude.json"), "--astra", str(out / "astra.json"),
            "--run-id", "audit-cycle-004", "--outcomes", str(out / "outcomes.json")]
    monkeypatch.setattr(_sys, "argv", base + ["--assisted-by", "x"])
    with pytest.raises(SystemExit) as e:
        ap.main()
    assert e.value.code == 2
    # drift: change record 1 after the draw
    real_open_ledger(ledger_dir, domain=dom).apply([Patch(1, "set", "polarity", "adverse", "later", Basis(model="m", prompt_version="v", run_id="later"))], note="later")
    monkeypatch.setattr(_sys, "argv", base)
    with pytest.raises(SystemExit) as e:
        ap.main()
    assert "drift" in str(e.value.code)
    monkeypatch.setattr(_sys, "argv", base + ["--allow-drift", "1"])
    assert ap.main() == 0
    oc = json.loads((out / "outcomes.json").read_text(encoding="utf-8"))
    assert oc["run_id"] == "audit-cycle-004" and oc["drift"]["changed"] == [1] and oc["drift"]["disposition"] == "allowed: 1"
    r1 = oc["records"]["1"]
    assert r1["status"] == "decided" and r1["user_final"] == {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"}
    assert r1["draw_time"]["polarity"] == "favorable" and r1["claude"]["relevant"] is True and r1["checker"] is None
    assert oc["records"]["2"]["status"] == "unresolved"
    assert oc["applied_seq_range"][0] <= oc["applied_seq_range"][1]


def test_main_refuses_decisions_outside_sample_manifest(tmp_path, monkeypatch):
    import sys as _sys
    dom = load_domain(); ledger_dir = tmp_path / "ledger"; led = real_open_ledger(ledger_dir, domain=dom)
    recs = [_rec(1), _rec(2)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    out = tmp_path / "audit"; out.mkdir()
    (out / "sample-manifest.json").write_text(json.dumps(_manifest(recs)), encoding="utf-8")
    queue = {"run_id": "audit-cycle-004", "sections": {"H": [{"case_id": 1, "decide_fields": ["relevant", "polarity", "who_was_letting"]},
                                                              {"case_id": 2, "decide_fields": ["relevant", "polarity", "who_was_letting"]}]}}
    (out / "audit-queue.json").write_text(json.dumps(queue), encoding="utf-8")
    (out / "decisions.json").write_text(json.dumps([_entry(99, "relevant", True)]), encoding="utf-8")
    monkeypatch.setattr(ap, "open_ledger", lambda *a, **kw: real_open_ledger(ledger_dir, domain=kw.get("domain") or dom))
    argv = ["apply_map_review.py", "--audit", "--decisions", str(out / "decisions.json"), "--queue", str(out / "audit-queue.json"),
            "--sample", str(out / "sample-manifest.json"), "--run-id", "audit-cycle-004", "--outcomes", str(out / "outcomes.json")]
    monkeypatch.setattr(_sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        ap.main()
    assert "outside the sample" in str(e.value.code)


def test_mirror_to_keepers_copies_only_entries_of_merged_copies():
    records = {1: _rec(1, duplicate_of=9), 2: _rec(2)}
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "favorable"), _entry(2, "relevant", True)]
    mirrored, pairs = ap.mirror_to_keepers(entries, records)
    assert pairs == [(1, 9)]
    assert [(e["case_id"], e["field"]) for e in mirrored] == [(9, "relevant"), (9, "polarity")]
    assert all(e["decision"] == "set" for e in mirrored)
    assert ap.mirror_to_keepers([_entry(2, "relevant", True)], records) == ([], [])


def test_audit_patches_on_entries_plus_mirror_reach_copy_and_keeper(tmp_path):
    dom = load_domain(); led = real_open_ledger(tmp_path / "ledger", domain=dom)
    recs = [_rec(1), _rec(2), _rec(9), _rec(10)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    records = dict(real_open_ledger(tmp_path / "ledger", domain=dom).view().state.records)
    records[1] = dict(records[1], duplicate_of=9); records[2] = dict(records[2], duplicate_of=10)
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "adverse", initial="favorable", reason="r"),
               _entry(1, "who_was_letting", "householder"), _entry(2, "relevant", False)]
    mirrored, pairs = ap.mirror_to_keepers(entries, records)
    patches = ap.audit_patches(entries + mirrored, records, "mmaldo2", run_id="audit-cycle-004")
    sets = [(p.case_id, p.field, p.new) for p in patches if p.op == "set"]
    for cid in (1, 9):
        assert (cid, "relevant", True) in sets and (cid, "polarity", "adverse") in sets
        assert (cid, "who_was_letting", "householder") in sets
    for cid in (2, 10):
        assert (cid, "relevant", False) in sets and (cid, "polarity", None) in sets
