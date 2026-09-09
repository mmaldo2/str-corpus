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


def pool_case_ids(runs_dir: Path, run_id: str) -> set[int]:
    """Every case packed into `run_id`'s batches.

    The batch files are the record of what that run's pool WAS. `rankings` rows say what was
    scored, which is the same set only until the next re-pack; `signals` says what the
    selectors ever hit, which is far more."""
    from corpus_engine.mapper.cells import load_batches
    batches_dir = Path(runs_dir) / run_id / "batches"
    if not batches_dir.is_dir():
        raise SystemExit(f"no source pool: {batches_dir} does not exist")
    return {int(c["case_id"]) for b in load_batches(batches_dir) for c in (b.get("cases") or ())}


def heldout_for(ranker, domain) -> Path:
    """The held-out slice this ranker was JUDGED on, for the jurisdiction-coverage check.

    The loaded model's own `manifest.json` is the authority (`heldout.path`, written by
    `tools/train_ranker.py`), because the question the check answers is "does the slice this
    ranker's average precision was measured on cover the jurisdictions in the pool it is about
    to order?". `ranking.heldout_v2` then `ranking.heldout` are the fallbacks, in that order, so
    a model trained before the manifest carried a path (v1) is still checked against the CURRENT
    slice rather than against the four-jurisdiction v1 one, which would WARN about six
    jurisdictions the corpus has covered since the cycle-004 expansion and stamp all six into
    the tracked shard manifest."""
    m = getattr(ranker, "manifest", None) or {}
    rel = (m.get("heldout") or {}).get("path")
    return ROOT / (rel or domain.ranking.heldout_v2 or domain.ranking.heldout)


def _refuse_overwrite(out: Path, run_id: str, from_run: str | None, force: bool) -> None:
    """`pack_batches` unlinks every `batch-*.json` in its output directory before writing, and
    `runs/*/batches` is gitignored, so a re-rank aimed at the wrong run destroys a pool that
    `admit_map` (`_unit_for`), `--retry-lost` and `pool_case_ids` all still read. The live
    command names two adjacent run ids on one line; transposing them is one keystroke."""
    if from_run and from_run == run_id:
        raise SystemExit(f"--from-run and --run-id are both {run_id!r}: a run cannot be its own "
                         f"source pool - the re-pack would delete the batches it reads from")
    if force:
        return
    manifest = out.parent / "map-manifest.json"
    if manifest.exists():
        raise SystemExit(f"{manifest} exists: {run_id!r} has already been MAPPED, and a re-pack "
                         f"would replace the batch files that map's manifest addresses. Pass "
                         f"--force only if that is really what you want.")
    existing = sorted(p.name for p in out.glob("batch-*.json"))
    if existing:
        raise SystemExit(f"{out} already holds {len(existing)} batch file(s) ({existing[0]} ...) "
                         f"and a re-pack deletes every one of them first. Pass --force to "
                         f"re-pack this run, or check that --run-id is the run you meant.")


def rerank(conn, run_id: str, *, ranker_id: str | None, runs_dir: Path, ledger_dir: Path, domain=None,
          out_dir: Path | None = None, log=print, heldout_path: Path | None = None,
          from_run: str | None = None, exclude_read: bool = True, force: bool = False) -> dict:
    domain = domain or load_domain()
    out = out_dir or (runs_dir / run_id / "batches")
    _refuse_overwrite(out, run_id, from_run, force)
    ranker = load_ranker(domain, conn, ranker_id)
    exclude = already_read_ids(runs_dir, ledger_dir) if exclude_read else set(); gold = gold_ids(domain)
    restrict = pool_case_ids(runs_dir, from_run) if from_run else None
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size,
                     ranker=ranker, ts=ts, restrict_ids=restrict)
    mp = out.parent / "shard-manifest.json"
    manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"run_id": run_id}
    cases = sum(len(json.loads(f.read_text(encoding="utf-8"))["cases"]) for f in out.glob("batch-*.json"))
    # I-1: the held-out slice may not cover every jurisdiction in the packed pool (it was
    # frozen before the cycle-004 jurisdiction expansion) - record the gap as a manifest
    # field rather than leaving it a paragraph in a report (final-review-report.md I-1).
    hpath = heldout_path if heldout_path is not None else heldout_for(ranker, domain)
    pool_jurisdictions = {jur for jur, in conn.execute(
        """SELECT DISTINCT c.jurisdiction FROM rankings r JOIN cases c ON c.case_id = r.case_id
           WHERE r.run_id = ? AND r.ranker_id = ?""", (run_id, ranker.ranker_id))}
    heldout_jurisdictions = {l.jurisdiction for l in load_heldout(hpath)}
    uncovered = sorted(pool_jurisdictions - heldout_jurisdictions)
    if uncovered:
        log(f"WARN rerank: held-out slice ({hpath}) has no coverage for jurisdictions {', '.join(uncovered)}")
    manifest["ranker"] = {"ranker_id": ranker.ranker_id, "digest": ranker.digest(), "reranked_at": ts,
                          "heldout_uncovered_jurisdictions": uncovered}
    if restrict is not None:
        # Provenance for a shard that is a subset of another shard: which run it came from,
        # how big that pool was, and exactly which of its cases were left out for having been
        # read already. The ids are written out rather than counted, so this file alone is
        # enough to re-derive the shard.
        left_out = sorted(restrict & exclude)
        manifest["source"] = {"run_id": from_run, "pool_cases": len(restrict),
                              "excluded_read": len(left_out), "excluded_case_ids": left_out,
                              "packed_cases": cases}
    mp.write_bytes((json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    log(f"{ranker.ranker_id}: {n} batches, {cases} cases -> {out} ({len(exclude)} already-read excluded)")
    return {"ranker_id": ranker.ranker_id, "batches": n, "cases": cases, "excluded": len(exclude)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rank.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ranker", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--from-run", default=None,
                    help="re-score and re-pack only the cases packed into this earlier run; "
                         "its batch files are the record of its pool")
    ap.add_argument("--exclude-read", dest="exclude_read", action="store_true", default=True,
                    help="leave out every case already read - this is ALREADY the default and "
                         "the flag turns nothing on; --include-read is the real switch")
    ap.add_argument("--force", action="store_true",
                    help="re-pack even though the target run already holds batch files or a "
                         "map manifest; the existing batch files are deleted first")
    ap.add_argument("--include-read", dest="exclude_read", action="store_false",
                    help="pack already-read cases too; only for a diagnostic re-pack")
    return ap


def main() -> int:
    a = build_parser().parse_args()
    conn = store.connect(); store.ensure_schema(conn); store.migrate(conn)
    p = store.paths()
    rerank(conn, a.run_id, ranker_id=a.ranker, runs_dir=p.runs, ledger_dir=p.ledger,
           out_dir=Path(a.out_dir) if a.out_dir else None, from_run=a.from_run,
           exclude_read=a.exclude_read, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
