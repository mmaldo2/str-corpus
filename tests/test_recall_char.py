import json, sqlite3
from corpus_engine.selector.engine import attribution

def test_attribution_reproduces_cycle_003_recall_report(repo_root, golden_dir):
    want = json.loads((golden_dir / "recall-cycle-003.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    gold = [json.loads(l) for l in (repo_root / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [g["case_id"] for g in gold if g.get("case_id")]
    attr = attribution(conn, ids)
    for tier, sel in (("brief-letting", lambda g: g.get("tier") == "brief" and g.get("domain") == "letting"),
                      ("brief-all", lambda g: g.get("tier") == "brief"), ("treatise", lambda g: g.get("tier") == "treatise")):
        entries = [g for g in gold if sel(g)]; in_corpus = [g for g in entries if g.get("case_id")]
        hits = [g for g in in_corpus if attr[g["case_id"]]]
        assert (len(entries), len(in_corpus), len(hits)) == (want["tiers"][tier]["total"], want["tiers"][tier]["resolved_in_corpus"], want["tiers"][tier]["signaled"]), tier
    letting = [g for g in gold if g.get("tier") == "brief" and g.get("domain") == "letting" and g.get("case_id")]
    got_hits = sorted([{"case_id": g["case_id"], "selectors": sorted({f"{r.selector_id}@v{r.selector_version}" for r in attr[g["case_id"]]})} for g in letting if attr[g["case_id"]]], key=lambda h: h["case_id"])
    assert got_hits == want["hits"] and sorted(g["case_id"] for g in letting if not attr[g["case_id"]]) == want["misses"]
