# Refactor Stage 2A — Corpus Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ingest and indexing into `corpus_engine`, add the citation-graph stage (CAP `cites_to`, PageRank) with a backfill over the existing corpus, tag every chunk with the embedding run that produced it, add a hosted embedding path for Qwen3-Embedding-4B, and then run the whole build for cycle 004 (Mass., Conn., N.J., Cal., Ohio, D.C., Federal Cases, U.S. Reports, Supreme Court of D.C.).

**Architecture:** `corpus_engine/ingest/` splits into a pure per-zip parser (no database), a writer that owns the single SQLite connection, a parallel driver (parse across cores, one writer), the citation-graph stage, and dedupe. `corpus_engine/indexer/` splits into FTS, chunking, an `Embedder` port with local, hosted, and fake adapters, and the embedding writer. The schema lives only in `corpus_engine/store.py`; the legacy scripts `pipeline/ingest.py` and `pipeline/index.py` become thin wrappers. Every chunk row carries an `embed_run` key so a partition's embedding model is a queryable fact, which Stage 2B's selector engine uses to refuse mixed-model partitions.

**Tech Stack:** Python 3.11, SQLite (FTS5), lxml, numpy, sentence-transformers + transformers (local model and tokenizer), httpx (hosted embeddings), multiprocessing. No new pip dependencies beyond `transformers` if not already pulled in by sentence-transformers.

**Spec:** `docs/adr/0005-citation-graph-from-cap-metadata.md`, `docs/adr/0006-embeddings-qwen3-4b-hosted-bulk-local-query.md`, `docs/adr/0008-corpus-scope-favors-founding-era-depth.md`, `docs/adr/0010-staged-package-refactor-with-a-domain-seam.md`, and `docs/design/2026-09-01-module-interfaces/README.md` (the coverage-fingerprint rule that consumes `embed_run`). Vocabulary: `CONTEXT.md`.

## Global Constraints

- Python 3.11; run everything as `.venv\Scripts\python` from the repo root `C:\Users\marcu\Desktop\Str-corpus`. Tests: `.venv\Scripts\python -m pytest tests -q` (pyproject.toml sets `pythonpath`; bare `pytest` also works).
- **Canonical bytes are LF**; `.gitattributes` pins text files. Write source files with LF.
- **No behavior change without a test first.** Moved functions are moved verbatim; `tests/test_ingest.py` (page maps, era boundaries, normalization) must keep passing against the new module path.
- The schema is defined once, in `corpus_engine/store.py`; no other module carries DDL after Task 1.
- Admission rule for a case at ingest (ADR-0008): admit iff `case.jurisdiction in domain.jurisdictions` **or** the zip's reporter slug is in `domain.reporter_slugs`. The `"U.S."` addition to `TARGET_JURISDICTIONS` made in Stage 1 is removed by this rule.
- Era partition comes from `corpus_engine.store.era_partition(year, domain.era_bounds)`; a case with no parseable year gets `era_partition = None` (unchanged behavior).
- `chunks` keeps `UNIQUE(case_id, seq)`; a re-embed of a case deletes that case's existing chunk rows and inserts the new ones in one transaction, so a case never has chunks from two runs. Partition embedding fingerprint = the set of distinct `embed_run` values over its non-duplicate cases' chunks.
- Existing chunk rows are tagged `embed_run = "qwen3-0.6b-512-int8"` by the migration in Task 1; the new run key is `"qwen3-4b-1024-int8"`. Keys are `<model-short>-<dim>-<quant>`.
- Hosted embedding (ADR-0006) is the only paid inference this stage allows; it needs `OPENROUTER_API_KEY` (or `DEEPINFRA_API_KEY`) from `.env`; the CLI prints a cost estimate and refuses to run without `--confirm`. Budget ceiling for Task 7: **$60**.
- Query-time embeddings are computed locally with the same pinned open weights; before any hosted vectors are trusted, the consistency check (Task 6) must report mean cosine agreement ≥ 0.99 on 1,000 chunks.
- The live corpus `data/db/corpus.db` is ~30 GB; tests use `tests/fixtures/corpus-tiny.db` (copied to tmp_path when a test writes) and synthetic zips built in-test. Tests that need the live DB are marked `live_db` and skip when it is absent.
- Never `fetchall()` a whole-corpus query; stream with cursors.
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```
- Do not run `pipeline/shard.py` in this stage (the coverage table changes in Stage 2B).

---

## File Structure

```
corpus_engine/
  store.py                 (+) cites_to, embed_runs DDL; migrate(conn); pagerank columns; chunks.embed_run
  ingest/
    __init__.py
    parse.py               extract_text_and_pages, parse_year, primary_cite   (moved verbatim)
    rows.py                ZipRows + case_rows_from_zip(): pure per-zip parser with the admission rule
    graph.py               graph_rows_from_zip() (cites_to + pagerank) and backfill_graph()
    dedupe.py              dedupe()                                          (moved verbatim)
    run.py                 ingest(): parallel parse, single writer, ingest_log
  indexer/
    __init__.py
    fts.py                 build_fts()                                       (moved verbatim)
    chunking.py            chunk_offsets() (moved) + embedding_input()
    embedders.py           Embedder protocol; LocalEmbedder, HostedEmbedder, FakeEmbedder
    embed.py               EmbedRun, build_embeddings(), partition_runs()
tools/
  backfill_citation_graph.py
  estimate_embed_cost.py
  embed_consistency_check.py
pipeline/ingest.py, pipeline/index.py     thin wrappers
domains/str-right-to-let/domain.yaml      (+) embedding: run_key, model, revision, dim, chunk_tokens, chunk_overlap, prefix_template
tests/test_store_migrate.py, test_ingest_rows.py, test_ingest_run.py, test_graph.py,
      test_indexer_chunking.py, test_indexer_embed.py, test_embedders.py
tests/fixtures/zips/  (built by tests at runtime under tmp_path; nothing committed)
```

---

### Task 1: Schema in one place, with the Stage 2 additions and an idempotent migration

**Files:**
- Modify: `corpus_engine/store.py` (SCHEMA, add `migrate`)
- Modify: `pipeline/ingest.py:45-73` (delete local SCHEMA; call `store.ensure_schema`), `pipeline/shard.py:35-53` (delete local SCHEMA; call `store.ensure_schema`), `pipeline/index.py:33-57` (delete FTS_SCHEMA/CHUNK_SCHEMA; call `store.ensure_schema` and `store.ensure_fts`)
- Create: `tests/test_store_migrate.py`

**Interfaces:**
- Consumes: `corpus_engine.store.connect`, `ensure_schema` (Stage 1).
- Produces: `store.SCHEMA` now also defines
  - `cites_to(citing_case_id INTEGER, cited_case_id INTEGER, cite TEXT, category TEXT, reporter TEXT, year INTEGER, weight INTEGER, opinion_index INTEGER, PRIMARY KEY (citing_case_id, cited_case_id, cite))` with indexes on `citing_case_id` and `cited_case_id`;
  - `embed_runs(run_key TEXT PRIMARY KEY, model TEXT, revision TEXT, dim INTEGER, quant TEXT, chunk_tokens INTEGER, chunk_overlap INTEGER, prefix_template TEXT, provider TEXT, created TEXT)`;
  - `chunks` and `embed_meta` DDL (moved from index.py) with `chunks.embed_run TEXT`;
  - `cases.pagerank REAL`, `cases.pagerank_pct REAL`.
  - `store.ensure_fts(conn)` creates the two FTS5 virtual tables (moved from index.py FTS_SCHEMA).
  - `store.migrate(conn) -> list[str]`: adds any missing columns via `ALTER TABLE ... ADD COLUMN` (checked with `PRAGMA table_info`), creates missing tables, and, when `chunks.embed_run` is newly added, runs `UPDATE chunks SET embed_run='qwen3-0.6b-512-int8' WHERE embed_run IS NULL` and inserts the matching `embed_runs` row from `embed_meta`. Returns the list of actions taken; empty on a second call.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store_migrate.py
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
        INSERT INTO embed_meta VALUES ('model','Qwen/Qwen3-Embedding-0.6B'),('revision','97b0c614be4d'),
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_store_migrate.py -q`
Expected: FAIL with `AttributeError: module 'corpus_engine.store' has no attribute 'ensure_fts'`

- [ ] **Step 3: Extend store.py**

Append to `SCHEMA` in `corpus_engine/store.py` (keep everything already there; add `pagerank REAL, pagerank_pct REAL,` to the `cases` CREATE after `ocr_confidence REAL, source_sha256 TEXT,`):

```python
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
    chunk_tokens INTEGER, chunk_overlap INTEGER, prefix_template TEXT, provider TEXT, created TEXT
);
```

Add the FTS DDL and `ensure_fts`, and `migrate`:

```python
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_porter USING fts5(
    norm_text, content='cases', content_rowid='case_id', tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS fts_raw USING fts5(
    norm_text, content='cases', content_rowid='case_id', tokenize='unicode61');
"""

LEGACY_EMBED_RUN = "qwen3-0.6b-512-int8"


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
                             ("chunks", "embed_run", "TEXT")):
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
```

- [ ] **Step 4: Run to verify pass, then delete the duplicate DDL in the three scripts**

Run: `.venv\Scripts\python -m pytest tests/test_store_migrate.py -q` — Expected: 2 passed.

In `pipeline/ingest.py` delete the `SCHEMA = """..."""` block and replace `conn.executescript(SCHEMA)` in `main()` with `store.ensure_schema(conn)` (add `from corpus_engine import store`). In `pipeline/shard.py` delete its `SCHEMA` block and replace its `conn.executescript(SCHEMA)` with `store.ensure_schema(conn)`. In `pipeline/index.py` delete `FTS_SCHEMA` and `CHUNK_SCHEMA`; `build_fts` calls `store.ensure_fts(conn)` instead of `conn.executescript(FTS_SCHEMA)`; `build_embeddings` calls `store.ensure_schema(conn)` instead of `conn.executescript(CHUNK_SCHEMA)`.

Run: `.venv\Scripts\python -m pytest tests -q` — Expected: all pass (47 + 2). Run `grep -n "CREATE TABLE" pipeline/*.py` — Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/store.py pipeline/ingest.py pipeline/shard.py pipeline/index.py tests/test_store_migrate.py
git commit -m "store: single schema with cites_to, embed_runs, chunk run tags; idempotent migrate()"
```

---

### Task 2: Pure per-zip parser with the admission rule

**Files:**
- Create: `corpus_engine/ingest/__init__.py`, `corpus_engine/ingest/parse.py`, `corpus_engine/ingest/rows.py`, `tests/test_ingest_rows.py`, `tests/helpers/capzip.py`
- Modify: `pipeline/ingest.py` (import `extract_text_and_pages`, `parse_year`, `primary_cite` from the package; delete local copies), `tests/test_ingest.py:1-12` (import path)

**Interfaces:**
- Consumes: `pipeline/textnorm.py` `normalize_text`, `normalize_cite`, `NORM_VERSION` (via `corpus_engine.textnorm_version` for the version and a sibling bridge for the functions, see Step 3); `corpus_engine.store.era_partition`; `corpus_engine.domain.Domain`.
- Produces:
  - `corpus_engine.ingest.parse`: `extract_text_and_pages(html_bytes) -> (str, list[tuple[int, str]])`, `parse_year(decision_date) -> int`, `primary_cite(citations) -> str` (verbatim moves).
  - `corpus_engine.ingest.rows`: `@dataclass(frozen=True) class ZipRows: slug: str; vol: str; n_total: int; cases: list[tuple]; citations: list[tuple]; cites_to: list[tuple]; pagerank: list[tuple]` and `case_rows_from_zip(zip_path: Path, domain: Domain) -> ZipRows`. `cases` tuples are in the exact column order of the `INSERT INTO cases` in Task 3; `citations` are `(case_id, cite, cite_norm, type)`; `cites_to` are `(citing_case_id, cited_case_id, cite, category, reporter, year, weight, opinion_index)`; `pagerank` are `(case_id, raw, percentile)`. Admission: `cm["jurisdiction"]["name"] in domain.jurisdictions or slug in domain.reporter_slugs`, where `slug = zip_path.parent.name`, `vol = zip_path.stem`.
  - `tests/helpers/capzip.py`: `make_cap_zip(path, slug, vol, cases: list[dict]) -> Path` building a static.case.law-shaped zip (`metadata/CasesMetadata.json`, `metadata/VolumeMetadata.json`, `html/<file_name>.html`).

- [ ] **Step 1: Write the zip helper and the failing tests**

```python
# tests/helpers/__init__.py   (empty)
# tests/helpers/capzip.py
import json, zipfile
from pathlib import Path

def make_cap_zip(path: Path, slug: str, vol: str, cases: list[dict]) -> Path:
    """cases: dicts with id, name, decision_date, jurisdiction (name), citations ([{cite,type}]),
    html (casebody html string), optional cites_to, analysis, first_page."""
    meta = []
    with zipfile.ZipFile(path, "w") as zf:
        for c in cases:
            fn = f"{c['id']:04d}-01"
            meta.append({
                "id": c["id"], "name": c["name"], "name_abbreviation": c.get("abbr", c["name"]),
                "decision_date": c["decision_date"], "docket_number": "", "first_page": c.get("first_page", "1"),
                "last_page": "9", "citations": c["citations"], "court": {"name": c.get("court", "Test Ct.")},
                "jurisdiction": {"id": 0, "name": c["jurisdiction"]}, "cites_to": c.get("cites_to", []),
                "analysis": c.get("analysis", {"ocr_confidence": 0.9, "sha256": "x", "pagerank": {"raw": 0.1, "percentile": 0.5}}),
                "last_updated": "", "provenance": {}, "file_name": fn, "first_page_order": 1, "last_page_order": 9,
            })
            zf.writestr(f"html/{fn}.html", c["html"])
        zf.writestr("metadata/CasesMetadata.json", json.dumps(meta))
        zf.writestr("metadata/VolumeMetadata.json", json.dumps({"volume_number": vol, "jurisdictions": []}))
    return path

HTML = ('<section class="casebody"><p>Page one text <a id="p2" class="page-label" data-label="2">*2</a>'
        'continues on page two about lodgers.</p></section>')
```

```python
# tests/test_ingest_rows.py
from corpus_engine.domain import load_domain
from corpus_engine.ingest.rows import case_rows_from_zip
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, jur, cite="1 Test 1", **kw):
    d = {"id": cid, "name": f"Case {cid}", "decision_date": "1855-03-01", "jurisdiction": jur,
         "citations": [{"cite": cite, "type": "official"}], "html": HTML}
    d.update(kw); return d

def test_admission_by_jurisdiction_or_reporter_slug(tmp_path):
    dom = load_domain()
    (tmp_path / "mass").mkdir(); (tmp_path / "f-cas").mkdir(); (tmp_path / "wyo").mkdir()
    zm = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass."), _case(2, "Wyo.", "2 Test 2")])
    zf = make_cap_zip(tmp_path / "f-cas" / "3.zip", "f-cas", "3", [_case(3, "U.S.", "3 F. Cas. 3")])
    zw = make_cap_zip(tmp_path / "wyo" / "4.zip", "wyo", "4", [_case(4, "U.S.", "4 Wyo. 4")])
    assert [r[0] for r in case_rows_from_zip(zm, dom).cases] == [1]          # Wyo. not in domain
    assert [r[0] for r in case_rows_from_zip(zf, dom).cases] == [3]          # slug allowlist admits U.S.
    assert case_rows_from_zip(zw, dom).cases == []                           # U.S. outside the allowlist
    assert case_rows_from_zip(zm, dom).n_total == 2

def test_rows_carry_text_pages_graph_and_pagerank(tmp_path):
    dom = load_domain(); (tmp_path / "mass").mkdir()
    z = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(
        7, "Mass.", cites_to=[{"cite": "9 Mass. 9", "case_ids": [9, 10], "category": "reporters:state",
                               "reporter": "Mass.", "year": 1810, "weight": 2, "opinion_index": 0}],
        analysis={"ocr_confidence": 0.7, "sha256": "abc", "pagerank": {"raw": 1e-7, "percentile": 0.42}})])
    rows = case_rows_from_zip(z, dom)
    case = rows.cases[0]
    assert case[0] == 7 and case[3] == "1 Test 1" and case[8] == "pre-1860" and case[9] == "mass" and case[10] == "1"
    assert "lodgers" in case[14] and case[16].startswith('[[0, "1"], [') and case[17] == 1
    assert rows.citations == [(7, "1 Test 1", "1 test 1", "official")]
    assert rows.cites_to == [(7, 9, "9 Mass. 9", "reporters:state", "Mass.", 1810, 2, 0),
                             (7, 10, "9 Mass. 9", "reporters:state", "Mass.", 1810, 2, 0)]
    assert rows.pagerank == [(7, 1e-7, 0.42)]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_rows.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_engine.ingest'`

- [ ] **Step 3: Move the parser and write rows.py**

`corpus_engine/ingest/parse.py`: copy `BLOCK_TAGS`, `parse_year`, `extract_text_and_pages`, `primary_cite` from `pipeline/ingest.py` unchanged (imports: `re`, `from lxml import html as lxml_html`). Add `corpus_engine/textnorm_bridge.py`:

```python
"""Bridge to pipeline/textnorm.py until textnorm moves into the package (Stage 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION, normalize, normalize_text, normalize_cite  # noqa: E402,F401
```

```python
# corpus_engine/ingest/rows.py
"""Pure per-zip parsing: a static.case.law volume zip in, row tuples out.
No database access, so it runs in worker processes (Task 3)."""
from __future__ import annotations
import io, json, zipfile
from dataclasses import dataclass, field
from pathlib import Path
from corpus_engine.domain import Domain
from corpus_engine.ingest.parse import extract_text_and_pages, parse_year, primary_cite
from corpus_engine.store import era_partition
from corpus_engine.textnorm_bridge import NORM_VERSION, normalize_cite, normalize_text

CASE_COLUMNS = ("case_id", "name", "name_abbreviation", "cite", "court", "jurisdiction",
                "decision_date", "decision_year", "era_partition", "reporter", "volume",
                "file_name", "first_page", "last_page", "raw_text", "norm_text",
                "page_map", "norm_version", "ocr_confidence", "source_sha256")


@dataclass(frozen=True)
class ZipRows:
    slug: str
    vol: str
    n_total: int
    cases: list[tuple] = field(default_factory=list)
    citations: list[tuple] = field(default_factory=list)
    cites_to: list[tuple] = field(default_factory=list)
    pagerank: list[tuple] = field(default_factory=list)


def admitted(cm: dict, slug: str, domain: Domain) -> bool:
    return cm["jurisdiction"]["name"] in domain.jurisdictions or slug in domain.reporter_slugs


def graph_rows(cm: dict) -> tuple[list[tuple], list[tuple]]:
    cid = cm["id"]
    ct = []
    for c in cm.get("cites_to") or []:
        for cited in c.get("case_ids") or []:
            ct.append((cid, int(cited), c.get("cite"), c.get("category"), c.get("reporter"),
                       c.get("year"), c.get("weight"), c.get("opinion_index")))
    pr = (cm.get("analysis") or {}).get("pagerank") or {}
    prs = [(cid, pr.get("raw"), pr.get("percentile"))] if pr else []
    return ct, prs


def case_rows_from_zip(zip_path: Path, domain: Domain) -> ZipRows:
    slug, vol = zip_path.parent.name, zip_path.stem
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        meta_name = next((n for n in names if n.endswith("CasesMetadata.json")), None)
        if not meta_name:
            return ZipRows(slug, vol, 0)
        cases_meta = json.load(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8"))
        out = ZipRows(slug, vol, len(cases_meta))
        for cm in cases_meta:
            if not admitted(cm, slug, domain):
                continue
            html_name = next((n for n in names if n.endswith(f"html/{cm['file_name']}.html")), None)
            if html_name is None:
                continue
            raw_text, page_labels = extract_text_and_pages(zf.read(html_name))
            page_map = [[0, cm.get("first_page")]] + [[off, label] for off, label in page_labels]
            year = parse_year(cm.get("decision_date", ""))
            analysis = cm.get("analysis") or {}
            out.cases.append((
                cm["id"], cm.get("name"), cm.get("name_abbreviation"), primary_cite(cm.get("citations", [])),
                (cm.get("court") or {}).get("name"), cm["jurisdiction"]["name"],
                cm.get("decision_date"), year, era_partition(year, domain.era_bounds) if year else None,
                slug, vol, cm["file_name"], cm.get("first_page"), cm.get("last_page"),
                raw_text, normalize_text(raw_text), json.dumps(page_map), NORM_VERSION,
                analysis.get("ocr_confidence"), analysis.get("sha256")))
            out.citations.extend((cm["id"], c["cite"], normalize_cite(c["cite"]), c.get("type"))
                                 for c in cm.get("citations", []))
            ct, prs = graph_rows(cm)
            out.cites_to.extend(ct); out.pagerank.extend(prs)
        return out
```

Then in `pipeline/ingest.py`: delete `BLOCK_TAGS`, `era_partition`, `parse_year`, `extract_text_and_pages`, `primary_cite`, and replace with `from corpus_engine.ingest.parse import extract_text_and_pages, parse_year, primary_cite` and `from corpus_engine.store import era_partition as _era` plus a local `def era_partition(year: int) -> str: return _era(year, ERA_BOUNDS)` so `tests/test_ingest.py`'s existing calls keep working. In `tests/test_ingest.py` change the import of `extract_text_and_pages`/`parse_year` to `from corpus_engine.ingest.parse import ...` (keep `era_partition` imported from `ingest` if the test uses it; check the file).

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_rows.py tests/test_ingest.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ingest corpus_engine/textnorm_bridge.py tests/helpers tests/test_ingest_rows.py tests/test_ingest.py pipeline/ingest.py
git commit -m "ingest: pure per-zip parser with the jurisdiction-or-reporter admission rule; graph and pagerank rows"
```

---

### Task 3: Parallel ingest driver with a single writer; dedupe moved

**Files:**
- Create: `corpus_engine/ingest/run.py`, `corpus_engine/ingest/dedupe.py`, `tests/test_ingest_run.py`
- Modify: `pipeline/ingest.py` (main becomes a wrapper over `corpus_engine.ingest.run.ingest`)

**Interfaces:**
- Consumes: `case_rows_from_zip`, `ZipRows`, `CASE_COLUMNS` (Task 2); `store.connect`, `ensure_schema`, `migrate`; `Domain`.
- Produces:
  - `corpus_engine.ingest.dedupe.dedupe(conn) -> int` (verbatim move of `pipeline/ingest.py:dedupe`).
  - `corpus_engine.ingest.run.write_rows(conn, rows: ZipRows) -> None` (INSERT OR REPLACE cases/citations; INSERT OR IGNORE cites_to; UPDATE cases SET pagerank, pagerank_pct) and `ingest(conn, zips: list[Path], domain: Domain, *, workers: int = 6, log=print) -> IngestReport(zips_done: int, cases_ingested: int, errors: list[tuple[str, str]])`. Skips zips whose `zip_key` is in `ingest_log` at the current `NORM_VERSION`; parses in a `multiprocessing.Pool(workers)` via `imap_unordered` over a top-level worker `_parse(args)` that returns `ZipRows` or an error tuple; the main process is the only writer and commits per zip plus the `ingest_log` row. `workers=1` runs in-process (used by tests and for debugging).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingest_run.py
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ingest.dedupe import dedupe
from corpus_engine.ingest.run import ingest
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, jur, cite, ctype="official"):
    return {"id": cid, "name": f"Case {cid}", "decision_date": "1880-01-01", "jurisdiction": jur,
            "citations": [{"cite": cite, "type": ctype}], "html": HTML}

def test_ingest_two_zips_with_workers_and_resume(tmp_path):
    dom = load_domain()
    (tmp_path / "mass").mkdir(); (tmp_path / "ne").mkdir()
    z1 = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass.", "1 Mass. 1")])
    z2 = make_cap_zip(tmp_path / "ne" / "2.zip", "ne", "2", [_case(2, "Mass.", "2 N.E. 2"), _case(3, "Ill.", "2 N.E. 3")])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    rep = ingest(conn, [z1, z2], dom, workers=2, log=lambda *_: None)
    assert (rep.zips_done, rep.cases_ingested, rep.errors) == (2, 2, [])
    assert conn.execute("SELECT count(*) FROM cases").fetchone()[0] == 2         # Ill. excluded
    assert conn.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 2
    assert conn.execute("SELECT pagerank_pct FROM cases WHERE case_id=1").fetchone()[0] == 0.5
    rep2 = ingest(conn, [z1, z2], dom, workers=1, log=lambda *_: None)
    assert rep2.zips_done == 0                                                     # resume skips both

def test_dedupe_prefers_official_copy(tmp_path):
    dom = load_domain(); (tmp_path / "mass").mkdir(); (tmp_path / "ne").mkdir()
    z1 = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, "Mass.", "5 Mass. 5")])
    z2 = make_cap_zip(tmp_path / "ne" / "2.zip", "ne", "2", [_case(2, "Mass.", "5 Mass. 5", ctype="parallel")])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    ingest(conn, [z1, z2], dom, workers=1, log=lambda *_: None)
    assert dedupe(conn) == 1
    assert conn.execute("SELECT is_duplicate_of FROM cases WHERE case_id=2").fetchone()[0] == 1
    assert conn.execute("SELECT is_duplicate_of FROM cases WHERE case_id=1").fetchone()[0] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_run.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_engine.ingest.dedupe'`

- [ ] **Step 3: Implement dedupe (verbatim move) and run.py**

`corpus_engine/ingest/dedupe.py`: copy `dedupe(conn)` from `pipeline/ingest.py` unchanged (`import sqlite3`).

```python
# corpus_engine/ingest/run.py
"""Parallel ingest: parse zips across processes, write from one process."""
from __future__ import annotations
import multiprocessing as mp
import sqlite3, time, zipfile, json
from dataclasses import dataclass, field
from pathlib import Path
from corpus_engine.domain import Domain, load_domain
from corpus_engine.ingest.rows import CASE_COLUMNS, ZipRows, case_rows_from_zip
from corpus_engine.textnorm_bridge import NORM_VERSION


@dataclass
class IngestReport:
    zips_done: int = 0
    cases_ingested: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _parse(args: tuple[str, str]) -> ZipRows | tuple[str, str]:
    zip_path, domain_name = args
    try:
        return case_rows_from_zip(Path(zip_path), load_domain(domain_name))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        p = Path(zip_path)
        return (f"{p.parent.name}/{p.stem}", f"{type(e).__name__}: {e}")


def write_rows(conn: sqlite3.Connection, rows: ZipRows) -> None:
    conn.executemany(
        f"INSERT OR REPLACE INTO cases ({','.join(CASE_COLUMNS)}) VALUES ({','.join('?' * len(CASE_COLUMNS))})",
        rows.cases)
    conn.executemany("INSERT OR REPLACE INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)", rows.citations)
    conn.executemany("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", rows.cites_to)
    conn.executemany("UPDATE cases SET pagerank=?, pagerank_pct=? WHERE case_id=?",
                     [(raw, pct, cid) for cid, raw, pct in rows.pagerank])


def ingest(conn: sqlite3.Connection, zips: list[Path], domain: Domain, *, workers: int = 6, log=print) -> IngestReport:
    done = {r[0] for r in conn.execute("SELECT zip_key FROM ingest_log WHERE norm_version=?", (NORM_VERSION,))}
    todo = [z for z in zips if f"{z.parent.name}/{z.stem}" not in done]
    log(f"{len(zips)} zips; {len(done)} already ingested; {len(todo)} to do; workers={workers}")
    rep = IngestReport()
    args = [(str(z), domain.name) for z in todo]
    if workers <= 1:
        results = map(_parse, args)
    else:
        pool = mp.Pool(workers)
        results = pool.imap_unordered(_parse, args, chunksize=4)
    try:
        for i, res in enumerate(results, 1):
            if isinstance(res, tuple):
                rep.errors.append(res); log(f"[{i}/{len(todo)}] ERROR {res[0]}: {res[1]}"); continue
            write_rows(conn, res)
            conn.execute("INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?)",
                         (f"{res.slug}/{res.vol}", res.n_total, len(res.cases), NORM_VERSION,
                          time.strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
            rep.zips_done += 1; rep.cases_ingested += len(res.cases)
            if i % 200 == 0 or i == len(todo):
                log(f"[{i}/{len(todo)}] {res.slug}/{res.vol}: {len(res.cases)}/{res.n_total} cases")
    finally:
        if workers > 1:
            pool.close(); pool.join()
    return rep
```

`Domain` needs `name` (it has it). `pipeline/ingest.py` `main()` becomes: parse the same args plus `--workers` (default 6); `conn = store.connect(db); store.ensure_schema(conn); store.migrate(conn)`; build `zips` as before; `rep = ingest(conn, zips, load_domain(), workers=args.workers)`; then `dedupe` unless `--skip-dedupe`; print the same summary lines. Delete `ingest_zip`, `TARGET_JURISDICTIONS`, and `ERA_BOUNDS` from the script (the admission rule now lives in the package). Keep `RAW_DIR`, `DEFAULT_DB`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_run.py tests/test_ingest.py -q` — Expected: all pass (on Windows, `mp.Pool` requires the worker to be importable; `_parse` is module-level, and pytest runs under `if __name__` protection, so this works).
Run: `.venv\Scripts\python pipeline\ingest.py --help` — Expected: usage with `--workers`.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ingest tests/test_ingest_run.py pipeline/ingest.py
git commit -m "ingest: parallel parse with one writer, resume via ingest_log; dedupe moved; script is a wrapper"
```

---

### Task 4: Citation-graph backfill over the existing corpus

**Files:**
- Create: `corpus_engine/ingest/graph.py`, `tools/backfill_citation_graph.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: `graph_rows` (Task 2), `store.connect/migrate`.
- Produces: `corpus_engine.ingest.graph.graph_rows_from_zip(zip_path) -> tuple[list[tuple], list[tuple]]` (metadata only, no HTML read; every case in the zip, admitted or not — rows for non-ingested citing cases are harmless and are filtered at query time by joining `cases`); `backfill_graph(conn, raw_dir: Path, *, workers: int = 6, log=print) -> tuple[int, int]` (zips processed, cites_to rows inserted) over every zip named in `ingest_log`, skipping zips already present in a new `graph_log(zip_key PRIMARY KEY, ts)` table (add to `store.SCHEMA` in this task); `tools/backfill_citation_graph.py` CLI (`--workers`, `--db`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
from corpus_engine import store
from corpus_engine.ingest.graph import graph_rows_from_zip, backfill_graph
from tests.helpers.capzip import make_cap_zip, HTML

def _case(cid, cites):
    return {"id": cid, "name": f"C{cid}", "decision_date": "1900-01-01", "jurisdiction": "Mass.",
            "citations": [{"cite": f"{cid} Mass. {cid}", "type": "official"}], "html": HTML,
            "cites_to": [{"cite": f"{c} Mass. {c}", "case_ids": [c], "category": "reporters:state",
                          "reporter": "Mass.", "year": 1850, "weight": 1, "opinion_index": 0} for c in cites],
            "analysis": {"ocr_confidence": 0.8, "sha256": "s", "pagerank": {"raw": 0.2, "percentile": 0.9}}}

def test_graph_rows_are_metadata_only(tmp_path):
    (tmp_path / "mass").mkdir()
    z = make_cap_zip(tmp_path / "mass" / "1.zip", "mass", "1", [_case(1, [2, 3]), _case(2, [])])
    ct, pr = graph_rows_from_zip(z)
    assert [(a, b) for a, b, *_ in ct] == [(1, 2), (1, 3)]
    assert pr == [(1, 0.2, 0.9), (2, 0.2, 0.9)]

def test_backfill_populates_cites_to_and_pagerank_and_is_resumable(tmp_path):
    (tmp_path / "raw" / "mass").mkdir(parents=True)
    z = make_cap_zip(tmp_path / "raw" / "mass" / "1.zip", "mass", "1", [_case(1, [2]), _case(2, [])])
    conn = store.connect(tmp_path / "c.db"); store.ensure_schema(conn)
    conn.execute("INSERT INTO cases (case_id, jurisdiction) VALUES (1,'Mass.'),(2,'Mass.')")
    conn.execute("INSERT INTO ingest_log VALUES ('mass/1', 2, 2, 1, 'ts')"); conn.commit()
    assert backfill_graph(conn, tmp_path / "raw", workers=1, log=lambda *_: None) == (1, 1)
    assert conn.execute("SELECT cited_case_id FROM cites_to WHERE citing_case_id=1").fetchone()[0] == 2
    assert conn.execute("SELECT pagerank_pct FROM cases WHERE case_id=2").fetchone()[0] == 0.9
    assert backfill_graph(conn, tmp_path / "raw", workers=1, log=lambda *_: None) == (0, 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_graph.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_engine.ingest.graph'`

- [ ] **Step 3: Implement**

Add to `store.SCHEMA`: `CREATE TABLE IF NOT EXISTS graph_log (zip_key TEXT PRIMARY KEY, ts TEXT);`

```python
# corpus_engine/ingest/graph.py
"""Citation-graph stage (ADR-0005): cites_to + PageRank from CAP volume metadata."""
from __future__ import annotations
import io, json, multiprocessing as mp, sqlite3, time, zipfile
from pathlib import Path
from corpus_engine.ingest.rows import graph_rows


def graph_rows_from_zip(zip_path: Path) -> tuple[list[tuple], list[tuple]]:
    with zipfile.ZipFile(zip_path) as zf:
        meta_name = next((n for n in zf.namelist() if n.endswith("CasesMetadata.json")), None)
        if not meta_name:
            return [], []
        cases_meta = json.load(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8"))
    ct_all, pr_all = [], []
    for cm in cases_meta:
        ct, pr = graph_rows(cm)
        ct_all.extend(ct); pr_all.extend(pr)
    return ct_all, pr_all


def _worker(zip_path: str):
    try:
        return zip_path, graph_rows_from_zip(Path(zip_path))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        return zip_path, (f"{type(e).__name__}: {e}",)


def backfill_graph(conn: sqlite3.Connection, raw_dir: Path, *, workers: int = 6, log=print) -> tuple[int, int]:
    done = {r[0] for r in conn.execute("SELECT zip_key FROM graph_log")}
    keys = [r[0] for r in conn.execute("SELECT zip_key FROM ingest_log") if r[0] not in done]
    paths = [str(raw_dir / f"{k}.zip") for k in keys]
    log(f"{len(keys)} zips to backfill; workers={workers}")
    n_zips = n_rows = 0
    results = map(_worker, paths) if workers <= 1 else mp.Pool(workers).imap_unordered(_worker, paths, chunksize=8)
    for i, (zp, res) in enumerate(results, 1):
        key = f"{Path(zp).parent.name}/{Path(zp).stem}"
        if isinstance(res, tuple) and len(res) == 1:
            log(f"[{i}/{len(keys)}] ERROR {key}: {res[0]}"); continue
        ct, pr = res
        conn.executemany("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", ct)
        conn.executemany("UPDATE cases SET pagerank=?, pagerank_pct=? WHERE case_id=?", [(a, b, c) for c, a, b in pr])
        conn.execute("INSERT OR REPLACE INTO graph_log VALUES (?,?)", (key, time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.commit()
        n_zips += 1; n_rows += len(ct)
        if i % 500 == 0 or i == len(keys):
            log(f"[{i}/{len(keys)}] {n_rows} cites_to rows so far")
    return n_zips, n_rows
```

```python
# tools/backfill_citation_graph.py
"""Populate cites_to and PageRank for every ingested volume (ADR-0005). Resumable.
    .venv\Scripts\python tools\backfill_citation_graph.py --workers 6"""
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
```

- [ ] **Step 4: Run to verify pass; then run the backfill on the live corpus**

Run: `.venv\Scripts\python -m pytest tests/test_graph.py tests/test_store_migrate.py -q` — Expected: pass.

Run: `.venv\Scripts\python tools\backfill_citation_graph.py --workers 6` (reads 9,206 zips' metadata; expect 10-30 minutes; it is resumable). Expected final lines: a tuple like `(9206, N)` with N in the millions, and `cases with pagerank:` close to the 1.9M ingested rows.

Then record the outcome in `reports/handoff-cycle-004.md` under "Order of work" item 6 (one line: date, zips processed, cites_to rows).

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/store.py corpus_engine/ingest/graph.py tools/backfill_citation_graph.py tests/test_graph.py reports/handoff-cycle-004.md
git commit -m "ingest: citation-graph stage from CAP metadata; backfill tool run over the existing corpus"
```

---

### Task 5: Indexer package: FTS, chunking with metadata prefix, the Embedder port, tagged embedding writer

**Files:**
- Create: `corpus_engine/indexer/__init__.py`, `corpus_engine/indexer/fts.py`, `corpus_engine/indexer/chunking.py`, `corpus_engine/indexer/embedders.py`, `corpus_engine/indexer/embed.py`, `tests/test_indexer_chunking.py`, `tests/test_embedders.py`, `tests/test_indexer_embed.py`
- Modify: `pipeline/index.py` (wrapper), `domains/str-right-to-let/domain.yaml` (embedding block), `corpus_engine/domain.py` (`Domain.embedding: EmbeddingSpec`)

**Interfaces:**
- Consumes: `store.ensure_fts`, `ensure_schema`, `migrate`; `Domain`.
- Produces:
  - `domain.yaml` gains
    ```yaml
    embedding:
      run_key: qwen3-4b-1024-int8
      model: Qwen/Qwen3-Embedding-4B
      revision: main            # pinned to a commit sha by tools/estimate_embed_cost.py --pin (Task 6)
      dim: 1024
      quant: int8-symmetric-pervector
      chunk_tokens: 400
      chunk_overlap: 40
      prefix_template: "{name} | {court} | {year}\n"
      hosted_provider: openrouter   # openrouter | deepinfra
      hosted_model_id: qwen/qwen3-embedding-4b
    ```
    and `Domain.embedding` is `EmbeddingSpec(run_key, model, revision, dim, quant, chunk_tokens, chunk_overlap, prefix_template, hosted_provider, hosted_model_id)` (frozen dataclass in `corpus_engine/domain.py`).
  - `corpus_engine.indexer.fts.build_fts(conn, log=print) -> None` (verbatim move; uses `store.ensure_fts`).
  - `corpus_engine.indexer.chunking.chunk_offsets(tokenizer, text, chunk_tokens, chunk_overlap) -> list[tuple[int,int]]` (moved; the two constants become parameters) and `embedding_input(prefix_template, case_meta: dict, span_text: str) -> str` returning `prefix_template.format(**case_meta) + span_text` with missing keys rendered as "".
  - `corpus_engine.indexer.embedders`: `class Embedder(Protocol): name: str; dim: int; def encode(self, texts: list[str]) -> np.ndarray` (float32, shape `(n, dim)`, already truncated to `dim`, NOT normalized); `LocalEmbedder(model, revision, dim, device=None)` (sentence-transformers, fp16 on CUDA, `padding_side="left"`, exposes `.tokenizer`); `HostedEmbedder(provider, model_id, dim, api_key, *, batch=64, concurrency=4, timeout=120)` (POST `{base}/embeddings` with `{"model": model_id, "input": texts}`; base = `https://openrouter.ai/api/v1` or `https://api.deepinfra.com/v1/openai`; truncates each vector to `dim`; retries 429/5xx with backoff 2/8/30 s; raises `EmbedError` after 4 failures; counts `usage.total_tokens` when present into `.tokens_used`); `FakeEmbedder(dim=16)` (deterministic: sha256 of the text seeds a numpy RNG; `.tokenizer` is a whitespace tokenizer object with the same `__call__(..., return_offsets_mapping=True)` shape as HF fast tokenizers); `tokenizer_for(model, revision)` loads `transformers.AutoTokenizer` (used by the hosted path).
  - `corpus_engine.indexer.embed`: `@dataclass(frozen=True) class EmbedRun: run_key, model, revision, dim, quant, chunk_tokens, chunk_overlap, prefix_template, provider` with `from_spec(spec: EmbeddingSpec, provider: str)`; `quantize(vecs) -> (int8 array, scales)` (normalize rows, per-vector symmetric int8, exactly as `pipeline/index.py` does); `build_embeddings(conn, embedder, tokenizer, run: EmbedRun, *, batch_size=64, limit=0, partitions: list[tuple[str,str]] | None = None, log=print) -> int` (returns chunks written; selects non-duplicate cases with non-empty `norm_text` whose chunks are NOT tagged `run.run_key` (so cases embedded under another run are re-embedded and their old chunks deleted in the same transaction as the new insert); restricted to `(era_partition, jurisdiction)` pairs when `partitions` is given; producer thread tokenizes, main thread encodes and writes, flushing only at case boundaries as today; records the run in `embed_runs` and mirrors it into `embed_meta` for the legacy readers); `partition_runs(conn) -> dict[tuple[str,str], set[str]]` mapping each `(era_partition, jurisdiction)` to the set of `embed_run` values over its non-duplicate cases' chunks (empty set = unembedded).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_indexer_chunking.py
from corpus_engine.indexer.chunking import chunk_offsets, embedding_input
from corpus_engine.indexer.embedders import FakeEmbedder

def test_chunk_offsets_cover_text_with_overlap():
    tok = FakeEmbedder().tokenizer
    text = " ".join(f"w{i}" for i in range(1000))
    spans = chunk_offsets(tok, text, 400, 40)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert len(spans) == 3 and spans[1][0] < spans[0][1]        # overlap
    assert chunk_offsets(tok, "", 400, 40) == []

def test_embedding_input_prefix_with_missing_keys():
    meta = {"name": "Howth v. Franklin", "court": "Tex.", "year": 1858}
    assert embedding_input("{name} | {court} | {year}\n", meta, "body") == "Howth v. Franklin | Tex. | 1858\nbody"
    assert embedding_input("{name} | {court} | {year}\n", {"name": "X"}, "body") == "X |  | \nbody"
```

```python
# tests/test_embedders.py
import json, numpy as np, pytest
from corpus_engine.indexer.embedders import FakeEmbedder, HostedEmbedder, EmbedError

def test_fake_embedder_is_deterministic_and_dim_correct():
    e = FakeEmbedder(dim=16)
    a = e.encode(["lodger", "boarder"]); b = e.encode(["lodger"])
    assert a.shape == (2, 16) and a.dtype == np.float32 and np.allclose(a[0], b[0]) and not np.allclose(a[0], a[1])

class _Resp:
    def __init__(self, status, payload): self.status_code = status; self._p = payload; self.text = json.dumps(payload)
    def json(self): return self._p

def test_hosted_embedder_truncates_retries_and_counts_tokens(monkeypatch):
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json["input"])
        if len(calls) == 1:
            return _Resp(429, {"error": "slow down"})
        return _Resp(200, {"data": [{"embedding": [0.5] * 2560} for _ in json["input"]], "usage": {"total_tokens": 7}})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    monkeypatch.setattr("corpus_engine.indexer.embedders.time.sleep", lambda s: None)
    e = HostedEmbedder("openrouter", "qwen/qwen3-embedding-4b", 1024, api_key="k", batch=2, concurrency=1)
    v = e.encode(["a", "b", "c"])
    assert v.shape == (3, 1024) and e.tokens_used == 14 and len(calls) == 3

def test_hosted_embedder_gives_up_after_four_failures(monkeypatch):
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", lambda *a, **k: _Resp(500, {"error": "x"}))
    monkeypatch.setattr("corpus_engine.indexer.embedders.time.sleep", lambda s: None)
    with pytest.raises(EmbedError):
        HostedEmbedder("deepinfra", "m", 8, api_key="k").encode(["a"])
```

```python
# tests/test_indexer_embed.py
import shutil, sqlite3
from corpus_engine import store
from corpus_engine.indexer.embed import EmbedRun, build_embeddings, partition_runs, quantize
from corpus_engine.indexer.embedders import FakeEmbedder
import numpy as np

RUN_A = EmbedRun("fake-a-16-int8", "fake", "r", 16, "int8-symmetric-pervector", 60, 10, "{name}\n", "test")
RUN_B = EmbedRun("fake-b-16-int8", "fake", "r", 16, "int8-symmetric-pervector", 60, 10, "{name}\n", "test")

def _db(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); store.migrate(conn)
    conn.execute("DELETE FROM chunks"); conn.commit()
    return conn

def test_quantize_round_trips_direction():
    v = np.random.default_rng(0).standard_normal((3, 16)).astype(np.float32)
    q8, s = quantize(v)
    back = q8.astype(np.float32) * s[:, None]
    vn = v / np.linalg.norm(v, axis=1, keepdims=True)
    assert np.all((back * vn).sum(axis=1) > 0.99)

def test_build_embeddings_tags_runs_resumes_and_replaces(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db); e = FakeEmbedder(dim=16)
    n = build_embeddings(conn, e, e.tokenizer, RUN_A, log=lambda *_: None)          # all cases, fake embedder is fast
    assert n > 0 and conn.execute("SELECT DISTINCT embed_run FROM chunks").fetchall() == [("fake-a-16-int8",)]
    assert conn.execute("SELECT run_key FROM embed_runs").fetchall() == [("fake-a-16-int8",)]
    assert build_embeddings(conn, e, e.tokenizer, RUN_A, log=lambda *_: None) == 0             # resume: nothing left under A
    cases_a = {r[0] for r in conn.execute("SELECT DISTINCT case_id FROM chunks")}
    build_embeddings(conn, e, e.tokenizer, RUN_B, limit=5, log=lambda *_: None)                # re-embeds 5 cases under B
    runs = conn.execute("SELECT embed_run, count(DISTINCT case_id) FROM chunks GROUP BY 1").fetchall()
    assert dict(runs)["fake-b-16-int8"] == 5 and dict(runs)["fake-a-16-int8"] == len(cases_a) - 5
    pr = partition_runs(conn)
    assert any(len(v) == 2 for v in pr.values()) or len(pr) > 1          # a mixed partition exists now
    dup = conn.execute("SELECT case_id FROM chunks GROUP BY case_id, seq HAVING count(*) > 1").fetchall()
    assert dup == []                                                        # never two runs for one (case, seq)

def test_partitions_filter_limits_scope(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db); e = FakeEmbedder(dim=16)
    part = conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone()
    build_embeddings(conn, e, e.tokenizer, RUN_A, partitions=[tuple(part)], log=lambda *_: None)
    got = conn.execute("""SELECT DISTINCT c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id=ch.case_id""").fetchall()
    assert got == [tuple(part)]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_indexer_chunking.py tests/test_embedders.py tests/test_indexer_embed.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_engine.indexer'`

- [ ] **Step 3: Implement**

`corpus_engine/domain.py`: add

```python
@dataclass(frozen=True)
class EmbeddingSpec:
    run_key: str; model: str; revision: str; dim: int; quant: str
    chunk_tokens: int; chunk_overlap: int; prefix_template: str
    hosted_provider: str; hosted_model_id: str
```

and a `embedding: EmbeddingSpec` field on `Domain`, loaded from `cfg["embedding"]` (`EmbeddingSpec(**cfg["embedding"])`). Add the YAML block above to `domains/str-right-to-let/domain.yaml`.

```python
# corpus_engine/indexer/fts.py
from corpus_engine import store
def build_fts(conn, log=print) -> None:
    store.ensure_fts(conn)
    for table in ("fts_porter", "fts_raw"):
        conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')"); conn.commit()
        n = conn.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH 'the'").fetchone()[0]
        log(f"{table}: rebuilt ({n} docs match 'the')")
```

```python
# corpus_engine/indexer/chunking.py
from __future__ import annotations

def chunk_offsets(tokenizer, text: str, chunk_tokens: int, chunk_overlap: int) -> list[tuple[int, int]]:
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False)
    offsets = enc["offset_mapping"]
    if not offsets:
        return []
    spans, step, i = [], chunk_tokens - chunk_overlap, 0
    while i < len(offsets):
        window = offsets[i:i + chunk_tokens]
        spans.append((window[0][0], window[-1][1]))
        if i + chunk_tokens >= len(offsets):
            break
        i += step
    return spans


class _Safe(dict):
    def __missing__(self, key): return ""


def embedding_input(prefix_template: str, case_meta: dict, span_text: str) -> str:
    return prefix_template.format_map(_Safe({k: ("" if v is None else v) for k, v in case_meta.items()})) + span_text
```

```python
# corpus_engine/indexer/embedders.py
"""The Embedder port and its adapters: local pinned weights, hosted open weights, and a
deterministic fake for tests (ADR-0006)."""
from __future__ import annotations
import hashlib, re, time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol
import httpx
import numpy as np


class EmbedError(RuntimeError): ...


class Embedder(Protocol):
    name: str
    dim: int
    def encode(self, texts: list[str]) -> np.ndarray: ...


class _WhitespaceTokenizer:
    """Stand-in with the HF fast-tokenizer call shape the chunker needs."""
    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False):
        return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}


class FakeEmbedder:
    def __init__(self, dim: int = 16):
        self.name, self.dim, self.tokenizer = f"fake-{dim}", dim, _WhitespaceTokenizer()
    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            out[i] = np.random.default_rng(seed).standard_normal(self.dim)
        return out


def tokenizer_for(model: str, revision: str):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model, revision=revision)


class LocalEmbedder:
    def __init__(self, model: str, revision: str, dim: int, device: str | None = None):
        import torch
        from sentence_transformers import SentenceTransformer
        dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_obj = SentenceTransformer(model, revision=revision, device=dev,
                                             model_kwargs={"torch_dtype": torch.float16} if dev == "cuda" else {},
                                             tokenizer_kwargs={"padding_side": "left"})
        self.tokenizer, self.name, self.dim = self.model_obj.tokenizer, f"local:{model}@{revision}", dim
    def encode(self, texts: list[str]) -> np.ndarray:
        v = self.model_obj.encode(texts, batch_size=64, convert_to_numpy=True, normalize_embeddings=False, show_progress_bar=False)
        return v[:, :self.dim].astype(np.float32)
    def encode_query(self, text: str) -> np.ndarray:
        return self.model_obj.encode([text], prompt_name="query", convert_to_numpy=True)[0][:self.dim].astype(np.float32)


BASES = {"openrouter": "https://openrouter.ai/api/v1", "deepinfra": "https://api.deepinfra.com/v1/openai"}


class HostedEmbedder:
    def __init__(self, provider: str, model_id: str, dim: int, api_key: str, *, batch: int = 64,
                 concurrency: int = 4, timeout: int = 120):
        self.base, self.model_id, self.dim, self.key = BASES[provider], model_id, dim, api_key
        self.batch, self.concurrency, self.timeout = batch, concurrency, timeout
        self.name, self.tokens_used = f"hosted:{provider}:{model_id}", 0

    def _one(self, texts: list[str]) -> np.ndarray:
        for attempt, delay in enumerate((2, 8, 30, 0)):
            r = httpx.post(f"{self.base}/embeddings", json={"model": self.model_id, "input": texts},
                           headers={"Authorization": f"Bearer {self.key}"}, timeout=self.timeout)
            if r.status_code == 200:
                p = r.json()
                self.tokens_used += int((p.get("usage") or {}).get("total_tokens") or 0)
                return np.asarray([d["embedding"][:self.dim] for d in p["data"]], dtype=np.float32)
            if r.status_code in (429,) or r.status_code >= 500:
                if attempt == 3:
                    break
                time.sleep(delay); continue
            raise EmbedError(f"{r.status_code}: {r.text[:200]}")
        raise EmbedError("embedding request failed after 4 attempts")

    def encode(self, texts: list[str]) -> np.ndarray:
        batches = [texts[i:i + self.batch] for i in range(0, len(texts), self.batch)]
        with ThreadPoolExecutor(self.concurrency) as ex:
            parts = list(ex.map(self._one, batches))
        return np.concatenate(parts) if parts else np.empty((0, self.dim), dtype=np.float32)
```

```python
# corpus_engine/indexer/embed.py
"""Embedding writer: chunk each case, embed through an Embedder, store int8 vectors tagged
with the run that produced them. A case belongs to exactly one run at a time."""
from __future__ import annotations
import queue, sqlite3, threading, time
from dataclasses import dataclass
import numpy as np
from corpus_engine.domain import EmbeddingSpec
from corpus_engine.indexer.chunking import chunk_offsets, embedding_input


@dataclass(frozen=True)
class EmbedRun:
    run_key: str; model: str; revision: str; dim: int; quant: str
    chunk_tokens: int; chunk_overlap: int; prefix_template: str; provider: str

    @staticmethod
    def from_spec(spec: EmbeddingSpec, provider: str) -> "EmbedRun":
        return EmbedRun(spec.run_key, spec.model, spec.revision, spec.dim, spec.quant, spec.chunk_tokens,
                        spec.chunk_overlap, spec.prefix_template, provider)


def quantize(vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
    scales = np.abs(vecs).max(axis=1) / 127.0
    return np.round(vecs / scales[:, None]).astype(np.int8), scales.astype(np.float32)


def register_run(conn: sqlite3.Connection, run: EmbedRun) -> None:
    conn.execute("""INSERT OR IGNORE INTO embed_runs VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (run.run_key, run.model, run.revision, run.dim, run.quant, run.chunk_tokens, run.chunk_overlap,
                  run.prefix_template, run.provider, time.strftime("%Y-%m-%dT%H:%M:%S")))
    for k, v in {"model": run.model, "revision": run.revision, "dim": str(run.dim), "chunk_tokens": str(run.chunk_tokens),
                 "chunk_overlap": str(run.chunk_overlap), "quant": run.quant, "run_key": run.run_key}.items():
        conn.execute("INSERT OR REPLACE INTO embed_meta VALUES (?,?)", (k, v))
    conn.commit()


def partition_runs(conn: sqlite3.Connection) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for era, jur in conn.execute("SELECT DISTINCT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL"):
        out[(era, jur)] = set()
    for era, jur, run in conn.execute("""SELECT DISTINCT c.era_partition, c.jurisdiction, ch.embed_run
                                          FROM chunks ch JOIN cases c ON c.case_id = ch.case_id WHERE c.is_duplicate_of IS NULL"""):
        out.setdefault((era, jur), set()).add(run)
    return out


def build_embeddings(conn: sqlite3.Connection, embedder, tokenizer, run: EmbedRun, *, batch_size: int = 64,
                     limit: int = 0, partitions=None, log=print) -> int:
    register_run(conn, run)
    where = ["c.is_duplicate_of IS NULL", "c.norm_text != ''",
             "c.case_id NOT IN (SELECT case_id FROM chunks WHERE embed_run = ?)"]
    params: list = [run.run_key]
    if partitions:
        where.append("(" + " OR ".join("(c.era_partition=? AND c.jurisdiction=?)" for _ in partitions) + ")")
        for e, j in partitions:
            params += [e, j]
    q = f"SELECT c.case_id FROM cases c WHERE {' AND '.join(where)} ORDER BY c.case_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    todo = [r[0] for r in conn.execute(q, params)]
    log(f"{len(todo)} cases to chunk+embed under {run.run_key} via {embedder.name}")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    qu: queue.Queue = queue.Queue(maxsize=4000)

    def producer():
        rc = sqlite3.connect(db_path); rc.execute("PRAGMA busy_timeout=120000")
        for cid in todo:
            row = rc.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
            if not row or not row[0]:
                qu.put(("CASE_DONE", cid)); continue
            meta = {"name": row[1], "court": row[2], "year": row[3]}
            for seq, (s, e) in enumerate(chunk_offsets(tokenizer, row[0], run.chunk_tokens, run.chunk_overlap)):
                qu.put((cid, seq, s, e, embedding_input(run.prefix_template, meta, row[0][s:e])))
            qu.put(("CASE_DONE", cid))
        qu.put(None)

    threading.Thread(target=producer, daemon=True).start()
    texts, rows, done_cases, written = [], [], [], 0

    def flush():
        nonlocal written
        if not texts:
            return
        q8, scales = quantize(embedder.encode(texts))
        case_ids = sorted({r[0] for r in rows})
        conn.executemany("DELETE FROM chunks WHERE case_id=?", [(c,) for c in case_ids])
        conn.executemany("INSERT INTO chunks (case_id, seq, char_start, char_end, embedding, embed_scale, embed_run) VALUES (?,?,?,?,?,?,?)",
                         [(cid, seq, s, e, q8[i].tobytes(), float(scales[i]), run.run_key) for i, (cid, seq, s, e) in enumerate(rows)])
        conn.commit()
        written += len(rows); texts.clear(); rows.clear()

    n_done = 0
    while True:
        item = qu.get()
        if item is None:
            break
        if item[0] == "CASE_DONE":
            n_done += 1
            if len(texts) >= batch_size * 8:
                flush()
            if n_done % 1000 == 0:
                flush(); log(f"{n_done}/{len(todo)} cases, {written} chunks written")
            continue
        cid, seq, s, e, text = item
        texts.append(text); rows.append((cid, seq, s, e))
    flush()
    log(f"done: {written} chunks under {run.run_key}")
    return written
```

Note the flush happens only at case boundaries (a case's chunks are contiguous in the queue), so the DELETE-then-INSERT per case is atomic per commit. `pipeline/index.py` becomes a wrapper: `fts` → `build_fts`; `embed` → build a `LocalEmbedder` from `domain.embedding` (or `--legacy-0.6b` to use the old model/dim/run key for a comparison run), `tokenizer = embedder.tokenizer`, `build_embeddings(...)`; add `--hosted` (uses `HostedEmbedder` with the key from `.env` and `tokenizer_for(spec.model, spec.revision)`), `--partitions "era|jur,era|jur"`, `--confirm` (required with `--hosted`; prints the Task 6 estimate first and refuses without it). Read `.env` with the same loader as `pipeline/citator_prescreen.py:load_token` (copy the function into `corpus_engine/store.py` as `env_value(name)`).

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_indexer_chunking.py tests/test_embedders.py tests/test_indexer_embed.py tests/test_domain.py -q` — Expected: all pass.
Run: `.venv\Scripts\python -m pytest tests -q` — Expected: green.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/indexer corpus_engine/domain.py corpus_engine/store.py domains/str-right-to-let/domain.yaml pipeline/index.py tests/test_indexer_chunking.py tests/test_embedders.py tests/test_indexer_embed.py
git commit -m "indexer: FTS, chunking with metadata prefix, Embedder port (local/hosted/fake), run-tagged embedding writer"
```

---

### Task 6: Cost estimate, revision pin, and the hosted-vs-local consistency check

**Files:**
- Create: `tools/estimate_embed_cost.py`, `tools/embed_consistency_check.py`, `tests/test_embed_estimate.py`
- Modify: `corpus_engine/indexer/embed.py` (add `estimate_tokens`)

**Interfaces:**
- Consumes: `tokenizer_for`, `LocalEmbedder`, `HostedEmbedder`, `partition_runs`, `Domain.embedding`.
- Produces: `corpus_engine.indexer.embed.estimate_tokens(conn, tokenizer, run: EmbedRun, *, sample: int = 500, partitions=None) -> tuple[int, int]` = (cases to embed, estimated total tokens) from a random sample of the pending cases' chunk inputs scaled to the population; `tools/estimate_embed_cost.py` prints cases, tokens, and USD at `$0.01 per 1M tokens`, and with `--pin` resolves `domain.embedding.revision` "main" to the current commit sha via `huggingface_hub.HfApi().model_info(model, revision).sha` and writes it back into `domain.yaml`; `tools/embed_consistency_check.py` embeds `--n 1000` random chunk inputs both through `LocalEmbedder` (needs the GPU and ~8 GB VRAM for the 4B in fp16) and `HostedEmbedder`, reports mean and 5th-percentile cosine between the two, and exits non-zero below 0.99 mean.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embed_estimate.py
import shutil
from corpus_engine import store
from corpus_engine.indexer.embed import EmbedRun, estimate_tokens
from corpus_engine.indexer.embedders import FakeEmbedder

def test_estimate_scales_sample_to_population(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    conn.execute("DELETE FROM chunks"); conn.commit()
    run = EmbedRun("fake-16", "fake", "r", 16, "int8", 60, 10, "{name}\n", "test")
    cases, tokens = estimate_tokens(conn, FakeEmbedder().tokenizer, run, sample=20)
    assert cases == conn.execute("SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL AND norm_text != ''").fetchone()[0]
    assert tokens > cases * 100
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_embed_estimate.py -q` — Expected: FAIL with ImportError on `estimate_tokens`.

- [ ] **Step 3: Implement**

Add to `corpus_engine/indexer/embed.py`:

```python
def estimate_tokens(conn, tokenizer, run: EmbedRun, *, sample: int = 500, partitions=None) -> tuple[int, int]:
    import random
    where = ["is_duplicate_of IS NULL", "norm_text != ''", "case_id NOT IN (SELECT case_id FROM chunks WHERE embed_run = ?)"]
    params: list = [run.run_key]
    if partitions:
        where.append("(" + " OR ".join("(era_partition=? AND jurisdiction=?)" for _ in partitions) + ")")
        for e, j in partitions:
            params += [e, j]
    ids = [r[0] for r in conn.execute(f"SELECT case_id FROM cases WHERE {' AND '.join(where)}", params)]
    if not ids:
        return 0, 0
    pick = random.Random(0).sample(ids, min(sample, len(ids)))
    total = 0
    for cid in pick:
        text, name, court, year = conn.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
        for s, e in chunk_offsets(tokenizer, text, run.chunk_tokens, run.chunk_overlap):
            total += len(tokenizer(embedding_input(run.prefix_template, {"name": name, "court": court, "year": year}, text[s:e]),
                                   add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"])
    return len(ids), int(total * len(ids) / len(pick))
```

```python
# tools/estimate_embed_cost.py
"""Estimate hosted-embedding cost for the pending cases; optionally pin the model revision.
    .venv\Scripts\python tools\estimate_embed_cost.py [--partitions "pre-1860|Mass.,..."] [--pin]"""
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.embed import EmbedRun, estimate_tokens  # noqa: E402
from corpus_engine.indexer.embedders import tokenizer_for  # noqa: E402

USD_PER_M = 0.01

def parse_partitions(s):
    return [tuple(p.split("|")) for p in s.split(",")] if s else None

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--partitions"); ap.add_argument("--pin", action="store_true"); a = ap.parse_args()
    dom = load_domain(); spec = dom.embedding
    if a.pin and spec.revision == "main":
        from huggingface_hub import HfApi
        sha = HfApi().model_info(spec.model, revision="main").sha
        y = (dom.root / "domain.yaml"); txt = y.read_bytes().decode("utf-8")
        y.write_bytes(txt.replace("revision: main", f"revision: {sha}", 1).encode("utf-8")); print("pinned", sha)
        dom = load_domain(); spec = dom.embedding
    conn = store.connect(); store.migrate(conn)
    cases, tokens = estimate_tokens(conn, tokenizer_for(spec.model, spec.revision), EmbedRun.from_spec(spec, spec.hosted_provider),
                                    partitions=parse_partitions(a.partitions))
    print(f"{cases} cases, ~{tokens:,} tokens, ~${tokens / 1e6 * USD_PER_M:.2f} at ${USD_PER_M}/M")
```

```python
# tools/embed_consistency_check.py
"""ADR-0006 gate: hosted vectors must agree with the local pinned model before they are trusted.
    .venv\Scripts\python tools\embed_consistency_check.py --n 1000"""
import argparse, random, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.indexer.chunking import chunk_offsets, embedding_input  # noqa: E402
from corpus_engine.indexer.embedders import HostedEmbedder, LocalEmbedder  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=1000); a = ap.parse_args()
    spec = load_domain().embedding; conn = store.connect()
    key = store.env_value("OPENROUTER_API_KEY" if spec.hosted_provider == "openrouter" else "DEEPINFRA_API_KEY")
    local = LocalEmbedder(spec.model, spec.revision, spec.dim)
    hosted = HostedEmbedder(spec.hosted_provider, spec.hosted_model_id, spec.dim, key)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases WHERE is_duplicate_of IS NULL AND norm_text != '' ORDER BY random() LIMIT ?", (a.n,))]
    texts = []
    for cid in ids:
        text, name, court, year = conn.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
        s, e = chunk_offsets(local.tokenizer, text, spec.chunk_tokens, spec.chunk_overlap)[0]
        texts.append(embedding_input(spec.prefix_template, {"name": name, "court": court, "year": year}, text[s:e]))
    L, H = local.encode(texts), hosted.encode(texts)
    L /= np.linalg.norm(L, axis=1, keepdims=True); H /= np.linalg.norm(H, axis=1, keepdims=True)
    cos = (L * H).sum(axis=1)
    print(f"n={len(cos)} mean={cos.mean():.4f} p5={np.percentile(cos, 5):.4f} min={cos.min():.4f} tokens={hosted.tokens_used}")
    sys.exit(0 if cos.mean() >= 0.99 else 1)
```

- [ ] **Step 4: Run to verify pass; pin the revision; estimate**

Run: `.venv\Scripts\python -m pytest tests/test_embed_estimate.py -q` — Expected: 1 passed.
Run: `.venv\Scripts\python tools\estimate_embed_cost.py --pin` — Expected: `pinned <sha>` then a line like `1301147 cases, ~1,900,000,000 tokens, ~$19.00 at $0.01/M` (the existing four states; the new states are not ingested yet). Commit the pinned `domain.yaml`.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/indexer/embed.py tools/estimate_embed_cost.py tools/embed_consistency_check.py tests/test_embed_estimate.py domains/str-right-to-let/domain.yaml
git commit -m "indexer: token/cost estimate, revision pin, hosted-vs-local consistency check"
```

---

### Task 7: Run the cycle-004 corpus build

This task runs the tools built above against the live corpus. It spends money once (hosted embedding, ceiling $60) and hours of wall-clock (ingest, FTS rebuild, dedupe). Each step is resumable; record every printed summary in `reports/build-cycle-004.md`.

**Files:**
- Create: `reports/build-cycle-004.md`
- Modify: `reports/handoff-cycle-004.md` (item 10 marked done with figures), `.env` (keys already present; never committed)

**Interfaces:**
- Consumes: `pipeline/ingest.py --workers`, `pipeline/index.py fts|embed --hosted --confirm --partitions`, `tools/backfill_citation_graph.py`, `tools/estimate_embed_cost.py`, `tools/embed_consistency_check.py`.

- [ ] **Step 1: Migrate and ingest the new volumes**

Run: `.venv\Scripts\python pipeline\ingest.py --workers 6 2>&1 | tee runs\ingest-cycle-004.log`
Expected: "… already ingested; 5,888 to do"; several hours; final `cases: N (M marked duplicate)` with N about 2.9M rows. Errors are logged per zip and do not stop the run. Record the last three lines in `reports/build-cycle-004.md`.

- [ ] **Step 2: Rebuild FTS and backfill the graph for the new volumes**

Run: `.venv\Scripts\python pipeline\index.py fts 2>&1 | tee runs\index-fts-cycle-004.log` — Expected: both tables rebuilt; doc counts near the unique-case count.
Run: `.venv\Scripts\python tools\backfill_citation_graph.py --workers 6` — Expected: only the newly ingested zips are processed (graph_log resume).

- [ ] **Step 3: Consistency gate and cost estimate**

Run: `.venv\Scripts\python tools\embed_consistency_check.py --n 1000` — Expected: `mean>=0.99`; exit 0. If it fails, stop: the hosted path is not trusted; report the numbers and do not proceed to Step 4.
Run: `.venv\Scripts\python tools\estimate_embed_cost.py` — Expected: a total for ALL pending cases under the 4B run key (new states plus the four old ones, since none are tagged `qwen3-4b-1024-int8` yet), roughly `~$40-55`. If above $60, stop and report.

- [ ] **Step 4: Embed new partitions first, then backfill the old ones**

Run (new states and the federal set):
`.venv\Scripts\python pipeline\index.py embed --hosted --confirm --partitions "<comma-separated era|jur for Mass., Conn., N.J., Cal., Ohio, D.C., U.S. across the five eras>" 2>&1 | tee runs\embed-4b-new.log`
Expected: progress lines every 1,000 cases; hours, not days.
Then the backfill of the existing four states:
`.venv\Scripts\python pipeline\index.py embed --hosted --confirm 2>&1 | tee runs\embed-4b-backfill.log`
Expected: every remaining case re-embedded under `qwen3-4b-1024-int8`; when done, `partition_runs` shows exactly one run everywhere:

```
.venv\Scripts\python -c "from corpus_engine import store; from corpus_engine.indexer.embed import partition_runs; pr=partition_runs(store.connect()); print({k:v for k,v in pr.items() if v!={'qwen3-4b-1024-int8'}})"
```
Expected: `{}`.

- [ ] **Step 5: Record and commit**

Write `reports/build-cycle-004.md` with: date, zips ingested and errors, cases by jurisdiction (`SELECT jurisdiction, count(*) FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1`), cites_to row count, cases with pagerank, the consistency-check line, the cost estimate, the hosted tokens used and USD, and the final `partition_runs` summary. Update `reports/handoff-cycle-004.md` item 10 to "done, see reports/build-cycle-004.md".

```bash
git add reports/build-cycle-004.md reports/handoff-cycle-004.md
git commit -m "cycle 004 corpus build: ingest, FTS, citation graph, Qwen3-4B hosted embedding with backfill"
```

---

## Follow-on

Stage 2B (separate plan, same date): the selector engine per the approved hybrid, consuming `partition_runs` for the coverage fingerprint, `cites_to` for the citation-graph selector, and `LocalEmbedder.encode_query` for query-time vectors. Stage 2C: candidate ranking (classifier, convex fusion, trigram side-index, optional reranker).
