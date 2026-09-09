"""Corpus store: repo paths, SQLite connection policy, schema, era partitions.

Every other module gets its paths and connections from here; nothing else
re-declares ROOT or opens corpus.db directly (ADR-0010).
"""
from __future__ import annotations
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    root: Path
    db: Path
    raw: Path
    runs: Path
    ledger: Path
    adjudications: Path
    gold: Path
    domains: Path


def paths(root: Path = ROOT) -> Paths:
    return Paths(root=root, db=root / "data" / "db" / "corpus.db", raw=root / "data" / "raw",
                 runs=root / "runs", ledger=root / "data" / "ledger",
                 adjudications=root / "data" / "adjudications", gold=root / "data" / "gold",
                 domains=root / "domains")


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id INTEGER PRIMARY KEY,
    name TEXT, name_abbreviation TEXT,
    cite TEXT,
    court TEXT, jurisdiction TEXT,
    decision_date TEXT, decision_year INTEGER, era_partition TEXT,
    reporter TEXT, volume TEXT, file_name TEXT,
    first_page TEXT, last_page TEXT,
    raw_text TEXT, norm_text TEXT,
    page_map TEXT,
    norm_version INTEGER,
    ocr_confidence REAL, source_sha256 TEXT,
    pagerank REAL, pagerank_pct REAL,
    cl_cluster_id INTEGER,
    is_duplicate_of INTEGER REFERENCES cases(case_id)
);
CREATE TABLE IF NOT EXISTS citations (
    case_id INTEGER REFERENCES cases(case_id),
    cite TEXT, cite_norm TEXT, type TEXT,
    PRIMARY KEY (case_id, cite)
);
CREATE INDEX IF NOT EXISTS idx_citations_norm ON citations(cite_norm);
CREATE INDEX IF NOT EXISTS idx_cases_partition ON cases(era_partition, jurisdiction);
CREATE TABLE IF NOT EXISTS ingest_log (
    zip_key TEXT PRIMARY KEY,
    n_cases_total INTEGER, n_cases_ingested INTEGER,
    norm_version INTEGER, ts TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES cases(case_id),
    selector_id TEXT, selector_version INTEGER,
    matched_text TEXT, char_span_start INTEGER, char_span_end INTEGER,
    chunk_id INTEGER, cosine REAL,
    era_partition TEXT, jurisdiction TEXT,
    run_id TEXT, ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_case ON signals(case_id);
CREATE INDEX IF NOT EXISTS idx_signals_selector ON signals(selector_id, selector_version);
CREATE TABLE IF NOT EXISTS coverage (
    selector_id TEXT, selector_version INTEGER,
    era_partition TEXT, jurisdiction TEXT,
    run_id TEXT, ts TEXT, n_signals INTEGER,
    PRIMARY KEY (selector_id, selector_version, era_partition, jurisdiction)
);
CREATE TABLE IF NOT EXISTS coverage_v2 (
    selector_id TEXT, selector_version INTEGER, partition_key TEXT, fingerprint TEXT,
    run_id TEXT, ts TEXT, n_signals INTEGER,
    PRIMARY KEY (selector_id, selector_version, partition_key, fingerprint)
);
CREATE TABLE IF NOT EXISTS cites_to (
    citing_case_id INTEGER, cited_case_id INTEGER, cite TEXT,
    category TEXT, reporter TEXT, year INTEGER, weight INTEGER, opinion_index INTEGER,
    PRIMARY KEY (citing_case_id, cited_case_id, cite)
);
CREATE INDEX IF NOT EXISTS idx_cites_to_citing ON cites_to(citing_case_id);
CREATE INDEX IF NOT EXISTS idx_cites_to_cited ON cites_to(cited_case_id);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES cases(case_id),
    seq INTEGER,
    char_start INTEGER, char_end INTEGER,
    embedding BLOB,
    embed_scale REAL,
    embed_run TEXT,
    UNIQUE (case_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_chunks_case ON chunks(case_id);
CREATE TABLE IF NOT EXISTS embed_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS embed_runs (
    run_key TEXT PRIMARY KEY, model TEXT, revision TEXT, dim INTEGER, quant TEXT,
    chunk_tokens INTEGER, chunk_overlap INTEGER, prefix_template TEXT, provider TEXT, created TEXT,
    tokens_used INTEGER
);
CREATE TABLE IF NOT EXISTS graph_log (zip_key TEXT PRIMARY KEY, ts TEXT);
CREATE TABLE IF NOT EXISTS rankings (
    run_id TEXT, ranker_id TEXT, case_id INTEGER, score REAL, ts TEXT,
    PRIMARY KEY (run_id, ranker_id, case_id)
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_porter USING fts5(
    norm_text, content='cases', content_rowid='case_id', tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS fts_raw USING fts5(
    norm_text, content='cases', content_rowid='case_id', tokenize='unicode61');
"""

LEGACY_EMBED_RUN = "qwen3-0.6b-512-int8"
# Revision the pre-refactor pipeline recorded for the legacy 0.6B run when it embedded
# the corpus (see the migrate() legacy-run insert below, and selectors.yaml's comment on
# embed_meta). pipeline/index.py's --legacy-0.6b comparison run must reuse this exact
# constant so it never records the literal string "main" under the already-claimed
# LEGACY_EMBED_RUN key.
LEGACY_EMBED_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"  # full sha, exactly as the live embed_meta recorded it


def connect(db_path: Path | None = None, *, busy_timeout_ms: int = 120_000,
            wal: bool = True) -> sqlite3.Connection:
    """One connection policy for the whole engine: long busy_timeout because
    shard and embed contend for the writer lock; WAL so readers never block."""
    conn = sqlite3.connect(db_path or paths().db)
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def ensure_fts(conn: sqlite3.Connection) -> None:
    conn.executescript(FTS_SCHEMA)
    conn.commit()


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Bring an older corpus.db up to the current schema. Idempotent; returns
    the actions taken so a run log can record them."""
    actions: list[str] = []
    before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    chunks_had_run = "chunks" in before and "embed_run" in _columns(conn, "chunks")
    for table, col, decl in (("cases", "pagerank", "REAL"), ("cases", "pagerank_pct", "REAL"),
                             ("chunks", "embed_run", "TEXT"), ("embed_runs", "tokens_used", "INTEGER")):
        if table in before and col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            actions.append(f"added {table}.{col}")
    conn.executescript(SCHEMA)          # creates any missing tables/indexes
    after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    actions += [f"created {t}" for t in sorted(after - before)]
    if "chunks" in before and not chunks_had_run:
        meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
        conn.execute("UPDATE chunks SET embed_run=? WHERE embed_run IS NULL", (LEGACY_EMBED_RUN,))
        conn.execute("""INSERT OR IGNORE INTO embed_runs
            (run_key, model, revision, dim, quant, chunk_tokens, chunk_overlap, prefix_template, provider, created)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (LEGACY_EMBED_RUN, meta.get("model"), meta.get("revision"), int(meta.get("dim", 512)),
             meta.get("quant"), int(meta.get("chunk_tokens", 0)), int(meta.get("chunk_overlap", 0)),
             "", "local", "migrated"))
        actions.append(f"tagged existing chunks as {LEGACY_EMBED_RUN}")
    conn.commit()
    return actions


def env_value(name: str) -> str | None:
    """Environment variable first, then the repo's `.env` line `NAME=value`.
    Never logs or prints the value (secrets: API keys)."""
    val = os.environ.get(name)
    if not val:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith(f"{name}="):
                    val = line.split("=", 1)[1].strip()
    return val or None


def case_partitions(conn, case_ids) -> dict[int, tuple[str, str]]:
    """`{case_id: (era_partition, jurisdiction)}` for the live (non-duplicate) cases among
    `case_ids`, read in chunks of 500 so a 30,000-id list is one bounded query per chunk.

    One function, two callers on purpose: the two held-out slices must be stratified on
    exactly the same facts, and the re-read's batch planner must group cases into the same
    cells the map used."""
    ids = sorted({int(c) for c in case_ids})
    out: dict[int, tuple[str, str]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, era, jur, dup in conn.execute(
                f"SELECT case_id, era_partition, jurisdiction, is_duplicate_of "
                f"FROM cases WHERE case_id IN ({ph})", chunk):
            if dup is None:
                out[int(cid)] = (era, jur)
    return out


def era_partition(year: int | None, bounds) -> str:
    """bounds: [(upper_exclusive_year, label), ...] ascending, last is a sentinel."""
    if year is None:
        return "unknown"
    for upper, label in bounds:
        if year < upper:
            return label
    return bounds[-1][1]
