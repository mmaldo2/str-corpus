import pytest
from corpus_engine.ledger import open_ledger, TierCount, NotTraditionEvidence
from corpus_engine.domain import load_domain

def test_counts_and_matrix_on_the_real_ledger(repo_root):
    v = open_ledger(domain=load_domain()).view()
    c = v.counts()
    # favorable 368 -> 367 after the retraction cascade backfill
    # (tools/apply_retraction_cascade.py): 11 records left unsupported by the
    # bootstrap's cascade=False replay got a judged field nulled and flagged
    # needs-review, including 7664513 (was favorable polarity). The backfill
    # patches carry a rule-only basis (Basis(rule_id="retraction-cascade-v1"))
    # -- a retraction to None is not a human judgment of the record and needs
    # no reviewer -- so the tier split stayed 150/560 through that backfill.
    #
    # 710 -> 693 relevant after the reference v2 adjudication
    # (tools/apply_reference_review.py): of the 18 cases the user adjudicated
    # `irrelevant` on the review page, 17 were still in the relevant population
    # (1262336 was already relevant:false). All 17 were human-reviewed, so the
    # whole drop lands on that tier and machine_only is unchanged. Favorable
    # holds at 367 -- 11 records gained the label and 12 lost it, one of the 12
    # being 1262336, which was outside the counted population either way.
    assert c.total == TierCount(human_reviewed=811, machine_only=1905)   # 634/2161 after round 3b; round 4 decided 256 of 258 (79 left the population)
    pol = v.counts(by=("polarity",))
    assert pol[("favorable",)].human_reviewed + pol[("favorable",)].machine_only == 1228   # 1267 after round 3b; round 4 removed 39 favorable as irrelevant
    hh = v.counts(polarity="favorable", who_was_letting="householder")
    assert hh.total.human_reviewed + hh.total.machine_only == 303    # 317 after round 3b; round 4   # 138 before reference v2
    m = v.matrix()
    pre = {k: t for k, t in m.cells.items() if k[0] == "pre-1860" and k[2] == "householder"}
    assert sum(t.human_reviewed + t.machine_only for t in pre.values()) == 14   # 15 after admission; round 4 removed one pre-1860 householder as irrelevant
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
