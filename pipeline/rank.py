"""Re-score and re-pack an existing run's batches with a ranker. Never touches signals or coverage."""
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                            # noqa: E402
from corpus_engine.domain import load_domain                               # noqa: E402
from corpus_engine.ranker import load_ranker                               # noqa: E402
from corpus_engine.ranker.labels import load_heldout                       # noqa: E402
from corpus_engine.selector.engine import gold_ids, already_read_ids       # noqa: E402
from corpus_engine.selector.packing import pack_batches                    # noqa: E402


def rerank(conn, run_id: str, *, ranker_id: str | None, runs_dir: Path, ledger_dir: Path, domain=None,
          out_dir: Path | None = None, log=print, heldout_path: Path | None = None) -> dict:
    domain = domain or load_domain()
    ranker = load_ranker(domain, conn, ranker_id)
    exclude = already_read_ids(runs_dir, ledger_dir); gold = gold_ids(domain)
    out = out_dir or (runs_dir / run_id / "batches"); ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size, ranker=ranker, ts=ts)
    mp = out.parent / "shard-manifest.json"
    manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"run_id": run_id}
    # I-1: the held-out slice may not cover every jurisdiction in the packed pool (it was
    # frozen before the cycle-004 jurisdiction expansion) - record the gap as a manifest
    # field rather than leaving it a paragraph in a report (final-review-report.md I-1).
    hpath = heldout_path if heldout_path is not None else (ROOT / domain.ranking.heldout)
    pool_jurisdictions = {jur for jur, in conn.execute(
        """SELECT DISTINCT c.jurisdiction FROM rankings r JOIN cases c ON c.case_id = r.case_id
           WHERE r.run_id = ? AND r.ranker_id = ?""", (run_id, ranker.ranker_id))}
    heldout_jurisdictions = {l.jurisdiction for l in load_heldout(hpath)}
    uncovered = sorted(pool_jurisdictions - heldout_jurisdictions)
    if uncovered:
        log(f"WARN rerank: held-out slice ({hpath}) has no coverage for jurisdictions {', '.join(uncovered)}")
    manifest["ranker"] = {"ranker_id": ranker.ranker_id, "digest": ranker.digest(), "reranked_at": ts,
                          "heldout_uncovered_jurisdictions": uncovered}
    mp.write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    cases = sum(len(json.loads(f.read_text(encoding="utf-8"))["cases"]) for f in out.glob("batch-*.json"))
    log(f"{ranker.ranker_id}: {n} batches, {cases} cases -> {out} ({len(exclude)} already-read excluded)")
    return {"ranker_id": ranker.ranker_id, "batches": n, "cases": cases, "excluded": len(exclude)}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--run-id", required=True); ap.add_argument("--ranker", default=None); ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(); conn = store.connect(); store.ensure_schema(conn); store.migrate(conn)
    p = store.paths()
    rerank(conn, a.run_id, ranker_id=a.ranker, runs_dir=p.runs, ledger_dir=p.ledger, out_dir=Path(a.out_dir) if a.out_dir else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
