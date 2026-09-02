"""Ingest static.case.law volume zips into SQLite.

Reads metadata/CasesMetadata.json + html/<file>.html from each zip in
data/raw/<slug>/, keeps only cases in the target jurisdictions, extracts text
from the HTML casebody with page-label anchors REMOVED (their offsets become
the page_map), normalizes per textnorm, assigns era partitions, and records
typed citations for gold-set resolution and parallel-publication dedupe.

Parsing runs in a multiprocessing pool (see corpus_engine.ingest.run); this
script is a thin CLI wrapper that resolves zip paths, drives the ingest, and
runs the final dedupe pass.

Dedupe runs as a final pass: cases sharing any normalized citation string are
one case; the copy from an official-type citation's own reporter wins, others
get is_duplicate_of set. Duplicates stay in the DB (auditability) but shard
queries exclude them.

Usage:
    python pipeline/ingest.py [--limit-volumes N] [--db PATH] [--workers N]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_DB = ROOT / "data" / "db" / "corpus.db"

sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.ingest.dedupe import dedupe  # noqa: E402
from corpus_engine.ingest.run import ingest  # noqa: E402
from corpus_engine.store import era_partition as _era  # noqa: E402

ERA_BOUNDS = list(load_domain().era_bounds)


def era_partition(year: int) -> str:
    return _era(year, ERA_BOUNDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--limit-volumes", type=int, default=0)
    ap.add_argument("--reporter", help="only ingest this reporter slug")
    ap.add_argument("--skip-dedupe", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    actions = store.migrate(conn)
    for a in actions:
        print(f"migrate: {a}")

    zips = sorted(
        RAW_DIR.glob(f"{args.reporter}/*.zip") if args.reporter else RAW_DIR.glob("*/*.zip")
    )
    if args.limit_volumes:
        zips = zips[: args.limit_volumes]

    ingest(conn, zips, load_domain(), workers=args.workers)

    if not args.skip_dedupe:
        n = dedupe(conn)
        conn.commit()
        print(f"dedupe: {n} duplicate pairs resolved")

    total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    dupes = conn.execute(
        "SELECT COUNT(*) FROM cases WHERE is_duplicate_of IS NOT NULL"
    ).fetchone()[0]
    print(f"cases: {total} ({dupes} marked duplicate)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
