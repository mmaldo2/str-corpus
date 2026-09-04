"""Shard stage (spec §7) — thin wrapper over corpus_engine.selector.engine.

Reads selectors/selectors.yaml, diffs against the fingerprinted coverage
matrix (coverage_v2), runs only (selector-version x partition) units not yet
covered, emits signals with full provenance, groups signal-bearing cases into
bounded batches homogeneous by era x jurisdiction. All of that logic now
lives in corpus_engine.selector.{model,coverage,ports,runners,packing,engine};
this script is only the CLI: argument parsing, opening the store, migrating
legacy coverage rows, and printing the plan/report summary.

Usage:
    python pipeline/shard.py --run-id cycle-001-shard-01 [--dry-run]
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.embed import partition_runs  # noqa: E402
from corpus_engine.ranker import load_ranker  # noqa: E402
from corpus_engine.selector.coverage import migrate_coverage  # noqa: E402
from corpus_engine.selector.engine import plan, shard  # noqa: E402
from corpus_engine.selector.model import load_selectors  # noqa: E402
from corpus_engine.selector.ports import LedgerSeedResolver, LocalQueryEmbedder  # noqa: E402

EMBED_KINDS = {"embedding", "relevance_feedback"}


class _Stamp:
    def __init__(self, run_id: str, ts: str):
        self.run_id = run_id
        self.ts = ts


def mixed_embed_runs(conn) -> set[str]:
    """Union of embed_run values tagged on any non-duplicate case's chunks, across every
    partition. More than one member means a re-embed is only partially done — this legacy
    shard (Stage 2A) has no notion of per-partition run selection, unlike Stage 2B's engine,
    which fingerprints coverage per partition and handles a mixed embedding state directly
    (see corpus_engine.selector.ports.fingerprint's mixed_embedding_model skip)."""
    union: set[str] = set()
    for run_set in partition_runs(conn).values():
        union |= run_set
    return union


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batches-only", action="store_true")
    ap.add_argument("--exclude-mapped", action="store_true")
    ap.add_argument("--ranker", default=None)
    ap.add_argument("--no-rank", action="store_true")
    args = ap.parse_args()

    if args.batches_only:
        # Fail closed: under the legacy shard this flag meant "regroup existing signals,
        # run no selectors" — cheap and largely read-only. Under the selector engine the
        # same invocation would run every planned unit against the live 79 GB DB (hours of
        # runners, writes to signals/coverage_v2, a rewritten batch directory). A printed
        # note is not a guard when the change turns a read into a large write.
        sys.exit("--batches-only is no longer supported under the selector engine; "
                 "re-run without it (batching always follows sharding)")
    if args.exclude_mapped:
        print("note: --exclude-mapped is a no-op under the selector engine "
              "(already-read exclusion is always applied); ignoring")

    domain = load_domain()
    conn = store.connect()
    store.ensure_schema(conn)
    store.migrate(conn)
    migrate_coverage(conn, {s.key: s for s in load_selectors(domain, include_retired=True)})

    seeds = LedgerSeedResolver(domain)
    sels = load_selectors(domain)
    by_key = {s.key: s for s in sels}

    runs = partition_runs(conn)
    pl = plan(conn, domain, seeds=seeds, embedder=None, selectors=sels, runs=runs)

    embedder = None
    if not args.dry_run and any(by_key[u.key].kind in EMBED_KINDS for u in pl.units):
        embedder = LocalQueryEmbedder(conn)

    ranker = None if args.dry_run else (None if args.no_rank else load_ranker(domain, conn, args.ranker))

    stamp = _Stamp(args.run_id, time.strftime("%Y-%m-%dT%H:%M:%S"))
    report = shard(conn, domain, args.run_id, seeds=seeds, embedder=embedder, dry_run=args.dry_run, stamp=stamp,
                   runs=runs, plan_=pl, ranker=ranker)

    print(f"{len(sels)} active selectors; {len(pl.units)} plan units; {len(pl.skips)} skips")
    if args.dry_run:
        print("ranking: skipped (dry run)")
        print(f"dry run: no writes; {report.cases_batched} cases would batch "
              f"({report.excluded_already_read} already-read excluded)")
    else:
        print(f"ranker: {ranker.ranker_id if ranker else 'none (legacy order)'}")
        total_signals = sum(report.signals_written.values())
        print(f"{total_signals} new signals")
        print(f"{report.batches_written} batches -> {report.batch_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
