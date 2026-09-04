import sqlite3
from corpus_engine import store

V1_CASES = """CREATE TABLE cases (case_id INTEGER PRIMARY KEY, name TEXT, name_abbreviation TEXT, cite TEXT,
 court TEXT, jurisdiction TEXT, decision_date TEXT, decision_year INTEGER, era_partition TEXT, reporter TEXT,
 volume TEXT, file_name TEXT, first_page TEXT, last_page TEXT, raw_text TEXT, norm_text TEXT, page_map TEXT,
 norm_version INTEGER, ocr_confidence REAL, source_sha256 TEXT, cl_cluster_id INTEGER, is_duplicate_of INTEGER)"""
V1_CHUNKS = """CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, seq INTEGER,
 char_start INTEGER, char_end INTEGER, embedding BLOB, embed_scale REAL, UNIQUE (case_id, seq))"""

def _v1_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(V1_CASES + ";" + V1_CHUNKS + """;
        CREATE TABLE embed_meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO embed_meta VALUES ('model','Qwen/Qwen3-Embedding-0.6B'),('revision','97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3'),
          ('dim','512'),('chunk_tokens','400'),('chunk_overlap','40'),('quant','int8-symmetric-pervector');
        INSERT INTO cases (case_id, norm_text) VALUES (1, 'x');
        INSERT INTO chunks (case_id, seq, char_start, char_end, embedding, embed_scale) VALUES (1, 0, 0, 1, x'00', 1.0);
    """)
    conn.commit()
    return conn

def test_fresh_schema_has_stage2_tables(tmp_path):
    conn = store.connect(tmp_path / "t.db"); store.ensure_schema(conn); store.ensure_fts(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"cases", "citations", "ingest_log", "signals", "coverage", "chunks", "embed_meta", "cites_to", "embed_runs", "fts_raw", "fts_porter"} <= names
    cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
    assert {"pagerank", "pagerank_pct"} <= cols
    assert "embed_run" in {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}

def test_migrate_tags_existing_chunks_and_is_idempotent(tmp_path):
    conn = _v1_db(tmp_path / "v1.db")
    actions = store.migrate(conn)
    assert any("chunks.embed_run" in a for a in actions) and any("cites_to" in a for a in actions)
    assert conn.execute("SELECT embed_run FROM chunks").fetchone()[0] == "qwen3-0.6b-512-int8"
    row = conn.execute("SELECT model, dim, chunk_tokens FROM embed_runs WHERE run_key='qwen3-0.6b-512-int8'").fetchone()
    assert row == ("Qwen/Qwen3-Embedding-0.6B", 512, 400)
    assert store.migrate(conn) == []

def test_migrate_adds_tokens_used_to_an_existing_embed_runs_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "v1-embed-runs.db")
    conn.executescript("""
        CREATE TABLE embed_runs (run_key TEXT PRIMARY KEY, model TEXT, revision TEXT, dim INTEGER, quant TEXT,
            chunk_tokens INTEGER, chunk_overlap INTEGER, prefix_template TEXT, provider TEXT, created TEXT);
        INSERT INTO embed_runs (run_key, model) VALUES ('k', 'm');
    """)
    conn.commit()
    actions = store.migrate(conn)
    assert "added embed_runs.tokens_used" in actions
    assert conn.execute("SELECT tokens_used FROM embed_runs WHERE run_key='k'").fetchone() == (None,)
    assert store.migrate(conn) == []
