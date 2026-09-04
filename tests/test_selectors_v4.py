from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.selector.ports import LedgerSeedResolver

def test_v4_selectors_present_and_seeds_resolve():
    dom = load_domain(); sels = {s.label: s for s in load_selectors(dom)}
    assert sels["citation-graph-38@v1"].kind == "citation_graph" and sels["citation-graph-38@v1"].params == {"seed_set": "both", "direction": "both"}
    fb = sels["relevance-feedback-39@v1"]
    assert fb.kind == "relevance_feedback" and fb.params["seed_set"] == "ledger-favorable-reviewed" and fb.params["top_k"] == 250
    ss = LedgerSeedResolver(dom).resolve("both")
    assert len(ss.case_ids) >= 50 and len(ss.hash) == 16
