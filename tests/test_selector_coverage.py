import shutil, sqlite3
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.coverage import covered, mark_covered, migrate_coverage
from corpus_engine.selector.model import load_selectors

def test_migration_copies_legacy_rows_with_kind_fingerprints(tmp_path, repo_root):
    src = repo_root / "tests/fixtures/cycle-003-signals.db"; p = tmp_path / "s.db"; shutil.copy(src, p)
    conn = store.connect(p); store.ensure_schema(conn)
    conn.execute("INSERT INTO cases (case_id, era_partition, jurisdiction, is_duplicate_of) SELECT case_id, era_partition, jurisdiction, is_duplicate_of FROM cases_meta")
    conn.execute("INSERT INTO chunks (case_id, seq, char_start, char_end, embedding, embed_scale, embed_run) SELECT case_id, 0, 0, 1, x'00', 1.0, 'qwen3-0.6b-512-int8' FROM cases_meta")
    conn.commit()
    sels = {s.key: s for s in load_selectors(load_domain())}
    n_legacy = conn.execute("SELECT count(*) FROM coverage").fetchone()[0]
    assert migrate_coverage(conn, sels) == n_legacy
    assert migrate_coverage(conn, sels) == 0
    fps = {r[0] for r in conn.execute("SELECT DISTINCT fingerprint FROM coverage_v2")}
    assert "fts:v1" in fps and any(f.startswith("embed:qwen3-0.6b-512-int8|engine:v1") for f in fps)
    key = next(k for k in sels if sels[k].kind == "fts_phrase")
    assert covered(conn, key, "1860-1900|N.Y.", "fts:v1") is True
    assert covered(conn, key, "1860-1900|N.Y.", "fts:v2") is False

def test_mark_and_covered_round_trip(tmp_path):
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    mark_covered(conn, ("x", 1), "pre-1860|Tex.", "fts:v1", "r1", "2026-01-01T00:00:00", 3); conn.commit()
    assert covered(conn, ("x", 1), "pre-1860|Tex.", "fts:v1") and not covered(conn, ("x", 2), "pre-1860|Tex.", "fts:v1")
