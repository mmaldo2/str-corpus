"""Held-out measurement of the reranker against the shipped default (spec §6). Applies the bar."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                        # noqa: E402
from corpus_engine.domain import load_domain                                           # noqa: E402
from corpus_engine.ranker import load_ranker                                           # noqa: E402
from corpus_engine.ranker.evaluate import compare, evaluate_scores                     # noqa: E402
from corpus_engine.ranker.labels import check_heldout, load_heldout                    # noqa: E402
from corpus_engine.ranker.reranker import QwenReranker                                 # noqa: E402
if __name__ == "__main__":
    dom = load_domain(); hpath = ROOT / dom.ranking.heldout; check_heldout(dom, hpath); held = load_heldout(hpath)
    conn = store.connect(); ids = [l.case_id for l in held]
    base = load_ranker(dom, conn, dom.ranking.default); rr = QwenReranker.from_domain(dom)
    t0 = time.time(); sr = rr.score(conn, "heldout", ids); secs = time.time() - t0
    mb = evaluate_scores(held, base.score(conn, "heldout", ids)); mr = evaluate_scores(held, sr); d = compare(mb, mr)
    bar = dom.ranking.bar_ap_delta
    clears = d["ap_all"] >= bar and d["ap_reviewed"] >= bar
    out = ROOT / "data" / "ranker" / f"reranker-{rr.revision[:7]}"; out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_bytes(json.dumps({"ranker_id": rr.ranker_id, "digest": rr.digest(), "model": rr.model, "revision": rr.revision,
        "query": rr.query, "heldout_n": len(held), "seconds": round(secs, 1), "baseline": base.ranker_id,
        "metrics": {"baseline": mb, "reranker": mr, "delta": d}, "bar_ap_delta": bar, "clears_bar": clears}, indent=1, sort_keys=True).encode("utf-8"))
    print(f"baseline {base.ranker_id}: ap_all={mb['ap_all']:.4f} ap_reviewed={mb['ap_reviewed']:.4f}")
    print(f"reranker {rr.ranker_id}: ap_all={mr['ap_all']:.4f} ap_reviewed={mr['ap_reviewed']:.4f} ({len(held)} pairs in {secs:.0f}s)")
    print("delta", d, "| BAR", bar, "->", "CLEARS: set ranking.default to reranker" if clears else "does not clear: default unchanged")
