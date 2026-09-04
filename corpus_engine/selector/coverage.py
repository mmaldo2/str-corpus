from __future__ import annotations
import sqlite3
from corpus_engine.selector.model import Partition, Selector, SelectorKey
from corpus_engine.store import LEGACY_EMBED_RUN

LEXICAL_FP = {"fts_phrase": "fts:v1", "fts_near": "fts:v1", "regex": "regex:v1"}


def partition_key(era: str, jurisdiction: str) -> str:
    return Partition(era, jurisdiction).key


def migrate_coverage(conn: sqlite3.Connection, selectors_by_key: dict[SelectorKey, Selector]) -> int:
    """Migrate legacy coverage rows to coverage_v2 with fingerprints derived by kind.

    Fingerprints: lexical (fts_phrase/fts_near → "fts:v1", regex → "regex:v1"),
    embedding (embed → "embed:<run>|engine:v1"), or unknown ("unknown:v1" when
    the selector key is absent — e.g., retired selectors not in selectors_by_key).

    Callers should pass selectors_by_key with include_retired=True to capture all
    selector types, including retired embedding selectors. Otherwise missing keys
    get "unknown:v1" (visibly wrong in the table, never matches live fingerprints).

    Returns count of rows copied. Idempotent: rows already present are skipped.
    """
    if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coverage'").fetchone():
        return 0
    n = 0
    for sid, ver, era, jur, run_id, ts, n_sig in conn.execute(
            "SELECT selector_id, selector_version, era_partition, jurisdiction, run_id, ts, n_signals FROM coverage"):
        sel = selectors_by_key.get((sid, ver))
        if sel is None:
            fp = "unknown:v1"
        else:
            fp = LEXICAL_FP.get(sel.kind) or f"embed:{LEGACY_EMBED_RUN}|engine:v1"
        cur = conn.execute("INSERT OR IGNORE INTO coverage_v2 VALUES (?,?,?,?,?,?,?)",
                           (sid, ver, partition_key(era, jur), fp, run_id, ts, n_sig))
        n += cur.rowcount
    conn.commit()
    return n


def covered(conn, key: SelectorKey, pkey: str, fingerprint: str) -> bool:
    return conn.execute("SELECT 1 FROM coverage_v2 WHERE selector_id=? AND selector_version=? AND partition_key=? AND fingerprint=?",
                        (key[0], key[1], pkey, fingerprint)).fetchone() is not None


def mark_covered(conn, key: SelectorKey, pkey: str, fingerprint: str, run_id: str, ts: str, n_signals: int) -> None:
    conn.execute("INSERT OR REPLACE INTO coverage_v2 VALUES (?,?,?,?,?,?,?)", (key[0], key[1], pkey, fingerprint, run_id, ts, n_signals))


def coverage_rows(conn) -> list[tuple]:
    return conn.execute("SELECT selector_id, selector_version, partition_key, fingerprint, run_id, ts, n_signals FROM coverage_v2 ORDER BY 1,2,3,4").fetchall()
