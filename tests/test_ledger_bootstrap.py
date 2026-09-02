import hashlib, json
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.bootstrap import patches_from_artifacts
from corpus_engine.domain import load_domain

def test_bootstrap_reproduces_all_three_ledgers_byte_for_byte(repo_root, golden_dir, tmp_path):
    want = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["ledger"]
    led = open_ledger(tmp_path, domain=load_domain())
    res = led.apply(patches_from_artifacts(repo_root), note="bootstrap", at="2026-09-01T00:00:00")
    assert res.replay_ok
    got = {name: hashlib.sha256(data).hexdigest() for name, data in led.view().render().items()}
    assert got == want

def test_bootstrap_counts_match_published_figures(repo_root, tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply(patches_from_artifacts(repo_root), note="bootstrap", at="2026-09-01T00:00:00")
    v = led.view()
    in_file = [v.record(c) for c in v.state.order if v.state.in_file[c]]
    assert len(in_file) == 715
    relevant = [r for r in in_file if r.get("relevant")]
    assert len(relevant) == 710
    from collections import Counter
    assert Counter(r.get("polarity") for r in relevant) == {"favorable": 368, "adverse": 196, "mixed": 128, None: 15, "irrelevant": 3}
    assert Counter(r["review"]["status"] for r in relevant) == {"machine": 560, "human-adjudicated": 138, "human-accepted": 11, "needs-work": 1}
    assert sum(1 for r in relevant if v.reviewed(r["case_id"])) == 150
