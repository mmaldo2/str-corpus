import json, sqlite3
from corpus_engine.textnorm_version import NORM_VERSION  # created in this task, see Step 3

def test_fixture_corpus_is_self_contained(fixture_db, repo_root):
    conn = sqlite3.connect(fixture_db)
    n = conn.execute("SELECT count(*) FROM cases").fetchone()[0]
    assert 150 <= n <= 600
    assert conn.execute("SELECT count(*) FROM cases WHERE norm_version != ?", (NORM_VERSION,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM fts_raw").fetchone()[0] == n
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] > 0
    meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
    assert "model" in meta and "revision" in meta
    b1 = json.loads((repo_root / "tests/fixtures/batches/cycle-003-shard-01/batch-001.json").read_text(encoding="utf-8"))
    ids = [c["case_id"] for c in b1["cases"]]
    q = f"SELECT count(*) FROM cases WHERE case_id IN ({','.join('?'*len(ids))})"
    assert conn.execute(q, ids).fetchone()[0] == len(ids)


def test_fixture_db_is_a_session_copy_not_the_tracked_file(fixture_db, repo_root):
    """Tests open the fixture with store.connect (WAL) and some write to it; the tracked file
    and its directory must never see a -wal/-shm or a write (spec 2026-10-04 section 3)."""
    tracked = repo_root / "tests" / "fixtures" / "corpus-tiny.db"
    assert fixture_db != tracked
    assert fixture_db.parent != tracked.parent
    assert fixture_db.stat().st_size == tracked.stat().st_size
