"""Populate cites_to and PageRank for every ingested volume (ADR-0005). Resumable.
    .venv\\Scripts\\python tools\\backfill_citation_graph.py --workers 6"""
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.ingest.graph import backfill_graph  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6); ap.add_argument("--db", default=None)
    a = ap.parse_args()
    conn = store.connect(Path(a.db) if a.db else None); store.ensure_schema(conn); print("migrate:", store.migrate(conn))
    print(backfill_graph(conn, store.paths().raw, workers=a.workers))
    print("cases with pagerank:", conn.execute("SELECT count(*) FROM cases WHERE pagerank IS NOT NULL").fetchone()[0])
