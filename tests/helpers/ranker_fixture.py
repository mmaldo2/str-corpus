"""A ranking fixture: corpus-tiny.db (328 cases, 0.6B chunks) + the cycle-003 signals for
those cases, migrated to the current schema. Signals keep their original run_id."""
import shutil, sqlite3
from pathlib import Path
from corpus_engine import store

def make_ranker_db(tmp_path: Path, fixture_db: Path, repo_root: Path) -> sqlite3.Connection:
    p = tmp_path / "rank.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); store.ensure_schema(conn); store.migrate(conn)
    ids = {r[0] for r in conn.execute("SELECT case_id FROM cases")}
    sig = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    rows = [r for r in sig.execute(
        """SELECT case_id, selector_id, selector_version, matched_text, char_span_start, char_span_end,
                  chunk_id, cosine, era_partition, jurisdiction, run_id, ts FROM signals""") if r[0] in ids]
    conn.executemany("""INSERT INTO signals (case_id, selector_id, selector_version, matched_text, char_span_start,
                        char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    return conn
