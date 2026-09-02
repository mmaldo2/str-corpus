import pytest
from corpus_engine.ledger import open_ledger, TierCount, NotTraditionEvidence
from corpus_engine.domain import load_domain

def test_counts_and_matrix_on_the_real_ledger(repo_root):
    v = open_ledger(domain=load_domain()).view()
    c = v.counts()
    # 150/560 -> 158/552 and favorable 368 -> 367 after the retraction cascade
    # backfill (tools/apply_retraction_cascade.py): 11 records left unsupported
    # by the bootstrap's cascade=False replay got a judged field nulled and
    # routed to human review, including 7664513 (was favorable polarity).
    assert c.total == TierCount(human_reviewed=158, machine_only=552)
    pol = v.counts(by=("polarity",))
    assert pol[("favorable",)].human_reviewed + pol[("favorable",)].machine_only == 367
    hh = v.counts(polarity="favorable", who_was_letting="householder")
    assert hh.total.human_reviewed + hh.total.machine_only == 138
    m = v.matrix()
    pre = {k: t for k, t in m.cells.items() if k[0] == "pre-1860" and k[2] == "householder"}
    assert sum(t.human_reviewed + t.machine_only for t in pre.values()) == 2
    assert ("pre-1860", "south", "householder", "nights") in m.empty_cells(minimum=3, tier="either")
    assert "| era |" in m.render_markdown()

def test_seed_set_and_manifest(repo_root):
    v = open_ledger(domain=load_domain()).view()
    s = v.seed_set()
    assert len(s.case_ids) > 50 and len(s.hash) == 64
    m = v.manifest("cycle-003")
    assert len(m) >= 168 and all(e["cycle"] == "cycle-003" for e in m)
    assert (repo_root / "data/ledger/manifest/cycle-003.jsonl").exists()

def test_argument_ledger_has_no_matrix(tmp_path):
    led = open_ledger(tmp_path, name="argument", domain=load_domain())
    with pytest.raises(NotTraditionEvidence):
        led.view().matrix()

@pytest.mark.xfail(strict=True, reason="ADR-0002 manifest backfill: relevant:false reads live only in runs/ until admitted")
def test_manifest_accounts_for_every_case_read(repo_root):
    import json
    v = open_ledger(domain=load_domain()).view()
    n_read = sum(len(json.loads(f.read_text(encoding="utf-8")))
                 for f in (repo_root / "runs/cycle-003-shard-01/verified").glob("*.json"))
    assert len(v.manifest("cycle-003")) == n_read
