import sqlite3
from corpus_engine import store

def test_paths_point_inside_repo(repo_root):
    p = store.paths()
    assert p.root == repo_root
    assert p.db == repo_root / "data" / "db" / "corpus.db"
    assert p.ledger == repo_root / "data" / "ledger"

def test_connect_creates_schema_on_empty_db(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.ensure_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cases", "citations", "ingest_log", "signals", "coverage"} <= names
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 120000

def test_era_partition_matches_ingest_boundaries():
    bounds = [(1860, "pre-1860"), (1900, "1860-1900"), (1930, "1900-1930"),
              (1970, "1930-1970"), (10_000, "1970-2020")]
    assert store.era_partition(1859, bounds) == "pre-1860"
    assert store.era_partition(1860, bounds) == "1860-1900"
    assert store.era_partition(1926, bounds) == "1900-1930"
    assert store.era_partition(2020, bounds) == "1970-2020"
    assert store.era_partition(None, bounds) == "unknown"
