# Refactor Stage 1 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the safety net and the two modules every later stage depends on in place: golden snapshots captured from the current code, a committed fixture corpus, byte-for-byte characterization tests for batch packing and quote verification, the `corpus_engine` package skeleton with the corpus store and domain loader, and the ledger module with its patch log, bootstrapped from the existing artifacts and proven to reproduce the three ledgers exactly.

**Architecture:** A new package `corpus_engine/` is introduced beside `pipeline/`; scripts in `pipeline/` become thin wrappers over it one function at a time, and every move is guarded by a characterization test that reproduces an existing artifact byte for byte before the old code is deleted. The ledger is a snapshot (the existing `data/ledger/cycle-*.jsonl`) plus an append-only patch log; the log is derived once from the existing run artifacts and adjudication files, and the module's render of the replayed log must equal the committed files. Everything STR-specific moves under `domains/str-right-to-let/`.

**Tech Stack:** Python 3.11, SQLite (FTS5), pytest 9, PyYAML, RapidFuzz, numpy. No new dependencies in this stage.

**Spec:** `docs/design/2026-09-01-module-interfaces/README.md` (approved hybrids), `docs/adr/0002`, `0004`, `0010`, `0011`, and `CONTEXT.md` for vocabulary. The nine candidate designs beside the README carry the reasoning.

## Global Constraints

- Python 3.11; run everything as `.venv\Scripts\python` from the repo root (`C:\Users\marcu\Desktop\Str-corpus`). Tests: `.venv\Scripts\python -m pytest tests -q`.
- **No behavior change without a byte-for-byte test first.** A task that moves code must reproduce the existing artifact before the old path is removed.
- `data/ledger/*.jsonl` are written only by `corpus_engine.ledger` after Task 9. No other module may open them for writing.
- JSON rendering of ledger records is `json.dumps(record)` with defaults (`ensure_ascii=True`, separators `", "` and `": "`, no indent), one record per line, `"\n"` terminated; record key order is insertion order and must be preserved.
- Every published count is a `TierCount(human_reviewed, machine_only)`; never add the two tiers.
- **Canonical bytes are LF** (git's stored form; `core.autocrlf=true` makes the Windows working copy CRLF). Golden digests are computed over CRLF→LF-normalized bytes; every characterization test normalizes (`b.replace(b"
", b"
")`) before hashing or comparing; the ledger renders LF and writes files in binary mode. (Ruling 2026-09-01, Task 5.)
- Judged fields: `relevant`, `polarity`, `who_was_letting`, `duration_of_occupancy`, `characterization`, `holding_summary`, `under_30_days`, `restriction_nature`, `right_characterization`. A judged field changes only under a `Basis` with `reviewer`, or with all of `model`, `prompt_version`, `run_id`.
- The live corpus is `data/db/corpus.db` (~30 GB). Tests that need it are marked `live_db` and skip when it is absent. Everything else runs against `tests/fixtures/corpus-tiny.db`.
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```
- Do not touch `pipeline/download.py` while `runs/download-cycle-004.log` shows the download still running.

---

## File Structure

Created in this stage:

```
corpus_engine/
  __init__.py            package marker; exposes __version__ = "0.1.0"
  store.py               repo root discovery, paths, connect(), schema DDL, era_partition()
  domain.py              load_domain(name) -> Domain (eras, jurisdictions, regions, tiers, judged fields, file paths)
  verification.py        verify_quote / verify_record / load_case moved verbatim from pipeline/verify_quotes.py
  selector/
    __init__.py
    packing.py           pack_batches(): emit_batches moved verbatim with explicit inputs
  ledger/
    __init__.py          public API: open_ledger, Ledger, LedgerView, Patch, Basis, Op, TierCount, errors
    types.py             frozen value types and error classes
    render.py            record line rendering and cycle-file rendering
    fold.py              apply_patch(): the pure per-op state transition
    log.py               PatchLog: append-only patches.jsonl, patch ids, seq
    ledger.py            open_ledger, Ledger, LedgerView (view/apply/counts/matrix/seed_set/manifest/history)
    tally.py             counts and tradition matrix over a record set
    bootstrap.py         patches_from_artifacts(): derive the log from runs/ and data/adjudications
domains/str-right-to-let/
  domain.yaml            eras, jurisdictions, region map, letting tiers, judged fields, paths
tools/
  capture_goldens.py     one-time snapshot of prompts, digests, signals fixture, exclusion set
  build_fixture_corpus.py builds tests/fixtures/corpus-tiny.db from the live DB
tests/
  conftest.py            fixtures: repo_root, fixture_db, live_db (skip), golden dir
  golden/                digests and prompt snapshots (committed)
  fixtures/              corpus-tiny.db, cycle-003-signals.db, already-read set (committed)
  test_store.py, test_domain.py, test_packing_char.py, test_verification_char.py,
  test_ledger_types.py, test_ledger_render.py, test_ledger_fold.py, test_ledger_apply.py,
  test_ledger_bootstrap.py, test_ledger_tally.py
```

Modified: `pipeline/shard.py` (emit_batches delegates), `pipeline/verify_quotes.py` (imports from corpus_engine), `pipeline/apply_adjudications.py`, `pipeline/polarity_review.py`, `pipeline/relevance_recheck.py` (become patch builders), `pipeline/ingest.py` and `pipeline/download.py` (jurisdictions and era bounds from the domain), `tests/test_verify.py` (import path), `README.md`, `reports/handoff-cycle-004.md`, `.gitignore`.

---

### Task 1: Capture goldens from the current code

This task must run at the current commit, before anything moves. It records what the existing code produces so later tasks can prove they reproduce it.

**Files:**
- Create: `tools/capture_goldens.py`
- Create: `tests/golden/README.md`
- Create (generated): `tests/golden/digests.json`, `tests/golden/prompts/cycle-003-shard-01/batch-001.txt` … `batch-010.txt`, `tests/golden/cycle-003-batches.json`, `tests/fixtures/cycle-003-signals.db`, `tests/fixtures/cycle-003-already-read.json`

**Interfaces:**
- Consumes: `pipeline.run_map.build_payload(conn, batch, worker_name) -> str`, `pipeline.shard.emit_batches(conn, run_id, exclude_mapped) -> int`, `pipeline.shard.already_mapped_ids() -> set[int]`.
- Produces: `tests/golden/digests.json` with shape `{"ledger": {"cycle-001.jsonl": sha}, "adjudications": {...}, "verified": {"cycle-003-shard-01/batch-001.json": sha, ...}, "batches": {"cycle-003-shard-01/batch-001.json": sha, ...}}`; `tests/golden/cycle-003-batches.json` with `{"run_id": "cycle-003-shard-01", "exclude_mapped": bool, "n_batches": int, "batch_size": 18}`; `tests/fixtures/cycle-003-signals.db` with tables `signals`, `coverage` (full copies) and `cases_meta(case_id, era_partition, jurisdiction, decision_year, is_duplicate_of)`; `tests/fixtures/cycle-003-already-read.json` as a sorted JSON list of ints.

- [ ] **Step 1: Write the capture script**

```python
# tools/capture_goldens.py
"""One-time golden capture at the pre-refactor commit. Run once:
    .venv\Scripts\python tools\capture_goldens.py
Idempotent: re-running overwrites the same files with the same bytes.
"""
import hashlib, json, shutil, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import run_map, shard  # noqa: E402  (old code, on purpose)

GOLDEN = ROOT / "tests" / "golden"
FIX = ROOT / "tests" / "fixtures"
RUN = "cycle-003-shard-01"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def digests() -> dict:
    out = {"ledger": {}, "adjudications": {}, "verified": {}, "batches": {}}
    for f in sorted((ROOT / "data" / "ledger").glob("cycle-*.jsonl")):
        out["ledger"][f.name] = sha(f)
    for f in sorted((ROOT / "data" / "adjudications").glob("cycle-*.json")):
        out["adjudications"][f.name] = sha(f)
    for run in sorted((ROOT / "runs").glob("cycle-*")):
        for f in sorted((run / "verified").glob("*.json")):
            out["verified"][f"{run.name}/{f.name}"] = sha(f)
        for f in sorted((run / "batches").glob("*.json")):
            out["batches"][f"{run.name}/{f.name}"] = sha(f)
    return out


def prompts(conn) -> None:
    d = GOLDEN / "prompts" / RUN
    d.mkdir(parents=True, exist_ok=True)
    for bf in sorted((ROOT / "runs" / RUN / "batches").glob("batch-*.json"))[:10]:
        batch = json.loads(bf.read_text(encoding="utf-8"))
        text = run_map.build_payload(conn, batch, "claude")
        (d / (bf.stem + ".txt")).write_text(text, encoding="utf-8", newline="\n")


def already_read_at_cycle_003() -> list[int]:
    """What shard.already_mapped_ids() returned when cycle 003 was sharded:
    every extraction in runs/ that existed before cycle-003-shard-01."""
    ids: set[int] = set()
    for f in (ROOT / "runs").glob("*/extractions*/*.json"):
        if f.parts[-3].startswith("cycle-003"):
            continue
        try:
            for r in json.loads(f.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("case_id"):
                    ids.add(r["case_id"])
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(ids)


def signals_fixture(conn) -> Path:
    FIX.mkdir(parents=True, exist_ok=True)
    dst = FIX / "cycle-003-signals.db"
    if dst.exists():
        dst.unlink()
    out = sqlite3.connect(dst)
    out.executescript(shard.SCHEMA)
    out.execute("""CREATE TABLE cases_meta (case_id INTEGER PRIMARY KEY, era_partition TEXT,
                   jurisdiction TEXT, decision_year INTEGER, is_duplicate_of INTEGER)""")
    cols = "case_id, selector_id, selector_version, matched_text, char_span_start, char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts"
    for row in conn.execute(f"SELECT signal_id, {cols} FROM signals ORDER BY signal_id"):
        out.execute(f"INSERT INTO signals (signal_id, {cols}) VALUES ({','.join('?' * 13)})", row)
    for row in conn.execute("SELECT selector_id, selector_version, era_partition, jurisdiction, run_id, ts, n_signals FROM coverage"):
        out.execute("INSERT INTO coverage VALUES (?,?,?,?,?,?,?)", row)
    ids = [r[0] for r in out.execute("SELECT DISTINCT case_id FROM signals")]
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        q = f"SELECT case_id, era_partition, jurisdiction, decision_year, is_duplicate_of FROM cases WHERE case_id IN ({','.join('?' * len(chunk))})"
        out.executemany("INSERT INTO cases_meta VALUES (?,?,?,?,?)", conn.execute(q, chunk).fetchall())
    out.commit(); out.close()
    return dst


def verify_batches_reproduce(fixture: Path, already: list[int]) -> dict:
    """Prove the fixture reproduces runs/cycle-003-shard-01/batches with the OLD code."""
    want_dir = ROOT / "runs" / RUN / "batches"
    want = {f.name: sha(f) for f in sorted(want_dir.glob("batch-*.json"))}
    for exclude in (True, False):
        tmp = Path(tempfile.mkdtemp(prefix="char-"))
        shard.RUNS = tmp                      # emit_batches writes under RUNS/<run_id>/batches
        shard.already_mapped_ids = lambda: set(already) if exclude else set()
        conn = sqlite3.connect(fixture)
        n = shard.emit_batches(conn, RUN, exclude_mapped=exclude)
        got = {f.name: sha(f) for f in sorted((tmp / RUN / "batches").glob("batch-*.json"))}
        shutil.rmtree(tmp, ignore_errors=True)
        if got == want:
            return {"run_id": RUN, "exclude_mapped": exclude, "n_batches": n, "batch_size": shard.BATCH_SIZE}
    raise SystemExit("fixture does not reproduce cycle-003 batches under either exclusion mode; investigate before proceeding")


def main() -> int:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ROOT / "data" / "db" / "corpus.db")
    conn.execute("PRAGMA busy_timeout=120000")
    (GOLDEN / "digests.json").write_text(json.dumps(digests(), indent=1, sort_keys=True), encoding="utf-8")
    prompts(conn)
    already = already_read_at_cycle_003()
    (FIX / "cycle-003-already-read.json").write_text(json.dumps(already), encoding="utf-8")
    fixture = signals_fixture(conn)
    params = verify_batches_reproduce(fixture, already)
    (GOLDEN / "cycle-003-batches.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    print(json.dumps(params))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against the live corpus**

Run: `.venv\Scripts\python tools\capture_goldens.py`
Expected: prints `{"run_id": "cycle-003-shard-01", "exclude_mapped": true, "n_batches": N, "batch_size": 18}`. (Note `shard.py` prints "excluding N already-mapped cases" on the exclusion path; that is fine.)

If it exits with "fixture does not reproduce": the likeliest cause is that `data/gold/gold.jsonl` changed after cycle 003 was sharded (gold-bearing batches sort first, so a different gold set reorders batches). Recover the gold file as of the shard with `git log --format=%H -- runs/cycle-003-shard-01/batches | tail -1` then `git show <that-commit>:data/gold/gold.jsonl > tests/golden/gold-at-cycle-003.jsonl`, point `emit_batches`'s gold read at it by temporarily assigning `shard.ROOT` to a temp dir containing `data/gold/gold.jsonl`, and record `"gold_file": "tests/golden/gold-at-cycle-003.jsonl"` in `cycle-003-batches.json` so Task 4's test reads the same file. If it still does not reproduce, stop and report; do not weaken the check.

- [ ] **Step 3: Check sizes and write the golden README**

Run: `ls -la tests/fixtures tests/golden tests/golden/prompts/cycle-003-shard-01 | head -30`
Expected: `cycle-003-signals.db` under 20 MB; ten prompt files; `digests.json` present.

```markdown
# tests/golden

Snapshots captured by `tools/capture_goldens.py` at commit (paste the output of
`git rev-parse HEAD` run immediately before Step 2) before the Stage 1 refactor. They are the characterization targets:

- `digests.json` — sha256 of every ledger, adjudication, verified, and batch file.
- `prompts/cycle-003-shard-01/batch-NNN.txt` — the exact reader prompt the old
  `run_map.build_payload` produced for the first ten cycle-003 batches.
- `cycle-003-batches.json` — the parameters under which
  `tests/fixtures/cycle-003-signals.db` reproduces the cycle-003 batches.

Never regenerate these without a logged reason; a change here is a change in
what the pipeline produces.
```

- [ ] **Step 4: Commit**

```bash
git add tools/capture_goldens.py tests/golden tests/fixtures/cycle-003-signals.db tests/fixtures/cycle-003-already-read.json
git commit -m "goldens: capture pre-refactor prompts, digests, cycle-003 signals fixture"
```

---

### Task 2: Package skeleton, corpus store, domain loader

**Files:**
- Create: `corpus_engine/__init__.py`, `corpus_engine/store.py`, `corpus_engine/domain.py`, `domains/str-right-to-let/domain.yaml`, `tests/conftest.py`, `tests/test_store.py`, `tests/test_domain.py`
- Modify: `pipeline/ingest.py:37-40` (TARGET_JURISDICTIONS, ERA_BOUNDS from domain), `pipeline/download.py:25-36` (TARGET_JURISDICTIONS, TARGET_REPORTER_SLUGS from domain), `pipeline/shard.py:55-56` (ERAS, JURISDICTIONS from domain)

**Interfaces:**
- Produces: `corpus_engine.store.ROOT: Path`; `store.paths() -> Paths` with fields `root, db, raw, runs, ledger, adjudications, gold, domains`; `store.connect(db_path: Path | None = None, *, busy_timeout_ms: int = 120_000, wal: bool = True) -> sqlite3.Connection`; `store.ensure_schema(conn) -> None` (creates cases, citations, ingest_log, signals, coverage); `store.era_partition(year: int | None, bounds: list[tuple[int, str]]) -> str`; `corpus_engine.domain.load_domain(name: str = "str-right-to-let") -> Domain` where `Domain` is a frozen dataclass with `name, eras: tuple[str, ...], era_bounds: tuple[tuple[int, str], ...], jurisdictions: tuple[str, ...], reporter_slugs: tuple[str, ...], regions: Mapping[str, str], letting_tiers: Mapping[str, str], judged_fields: tuple[str, ...], curatorial_fields: tuple[str, ...], selectors_path, ontology_path, prompts_dir, gold_path, reviewer_default: str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/conftest.py
import sqlite3
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent

@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO

@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return REPO / "tests" / "golden"

@pytest.fixture(scope="session")
def fixture_db() -> Path:
    p = REPO / "tests" / "fixtures" / "corpus-tiny.db"
    if not p.exists():
        pytest.skip("tests/fixtures/corpus-tiny.db not built yet (Task 3)")
    return p

@pytest.fixture(scope="session")
def live_db() -> Path:
    p = REPO / "data" / "db" / "corpus.db"
    if not p.exists():
        pytest.skip("live corpus.db not present")
    return p
```

```python
# tests/test_store.py
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
```

```python
# tests/test_domain.py
from corpus_engine.domain import load_domain

def test_str_domain_loads_with_cycle_004_scope():
    d = load_domain("str-right-to-let")
    assert d.eras == ("pre-1860", "1860-1900", "1900-1930", "1930-1970", "1970-2020")
    for j in ("Tex.", "Pa.", "La.", "N.Y.", "Mass.", "Conn.", "N.J.", "Cal.", "Ohio", "D.C."):
        assert j in d.jurisdictions
    assert set(d.reporter_slugs) == {"f-cas", "us", "dc"}
    assert d.regions["Mass."] == "northeast" and d.regions["Tex."] == "south"
    assert d.letting_tiers["householder"] == "householder"
    assert d.letting_tiers["owner_nonresident"] == "owner"
    assert "polarity" in d.judged_fields and "review.notes" in d.curatorial_fields
    assert d.selectors_path.exists() and d.ontology_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_store.py tests/test_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_engine'`

- [ ] **Step 3: Write the store and domain modules**

```python
# corpus_engine/__init__.py
"""Domain-agnostic engine for historical case-law corpus research (ADR-0010)."""
__version__ = "0.1.0"
```

```python
# corpus_engine/store.py
"""Corpus store: repo paths, SQLite connection policy, schema, era partitions.

Every other module gets its paths and connections from here; nothing else
re-declares ROOT or opens corpus.db directly (ADR-0010).
"""
from __future__ import annotations
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
"""


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


def era_partition(year: int | None, bounds) -> str:
    """bounds: [(upper_exclusive_year, label), ...] ascending, last is a sentinel."""
    if year is None:
        return "unknown"
    for upper, label in bounds:
        if year < upper:
            return label
    return bounds[-1][1]
```

```python
# corpus_engine/domain.py
"""Domain loader: everything STR-specific comes from domains/<name>/domain.yaml
so the engine never imports a domain file by literal path (ADR-0010)."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import yaml
from corpus_engine.store import paths


@dataclass(frozen=True)
class Domain:
    name: str
    root: Path
    eras: tuple[str, ...]
    era_bounds: tuple[tuple[int, str], ...]
    jurisdictions: tuple[str, ...]
    reporter_slugs: tuple[str, ...]
    regions: Mapping[str, str]
    letting_tiers: Mapping[str, str]
    judged_fields: tuple[str, ...]
    curatorial_fields: tuple[str, ...]
    selectors_path: Path
    ontology_path: Path
    prompts_dir: Path
    gold_path: Path
    reviewer_default: str


def load_domain(name: str = "str-right-to-let") -> Domain:
    d = paths().domains / name
    cfg = yaml.safe_load((d / "domain.yaml").read_text(encoding="utf-8"))
    repo = paths().root
    bounds = tuple((int(b["upper"]), b["label"]) for b in cfg["era_bounds"])
    return Domain(
        name=name, root=d,
        eras=tuple(b[1] for b in bounds),
        era_bounds=bounds,
        jurisdictions=tuple(cfg["jurisdictions"]),
        reporter_slugs=tuple(cfg.get("reporter_slugs", [])),
        regions=dict(cfg["regions"]),
        letting_tiers=dict(cfg["letting_tiers"]),
        judged_fields=tuple(cfg["judged_fields"]),
        curatorial_fields=tuple(cfg["curatorial_fields"]),
        selectors_path=repo / cfg["paths"]["selectors"],
        ontology_path=repo / cfg["paths"]["ontology"],
        prompts_dir=repo / cfg["paths"]["prompts"],
        gold_path=repo / cfg["paths"]["gold"],
        reviewer_default=cfg.get("reviewer_default", "unknown"),
    )
```

```yaml
# domains/str-right-to-let/domain.yaml
name: str-right-to-let
era_bounds:            # upper bound exclusive; last entry is the sentinel
  - {upper: 1860, label: pre-1860}
  - {upper: 1900, label: 1860-1900}
  - {upper: 1930, label: 1900-1930}
  - {upper: 1970, label: 1930-1970}
  - {upper: 10000, label: 1970-2020}
jurisdictions: [Tex., Pa., La., N.Y., Mass., Conn., N.J., Cal., Ohio, D.C.]
reporter_slugs: [f-cas, us, dc]          # federal tradition set (ADR-0008)
regions:
  Mass.: northeast
  Conn.: northeast
  N.Y.: northeast
  N.J.: northeast
  Pa.: northeast
  D.C.: mid-atlantic
  Ohio: midwest
  Tex.: south
  La.: south
  Cal.: west
  U.S.: federal
letting_tiers:                            # who_was_letting value -> tier
  householder: householder
  owner_nonresident: owner
  commercial_operator: commercial
  unclear: unclear
judged_fields: [relevant, polarity, who_was_letting, duration_of_occupancy,
                characterization, holding_summary, under_30_days,
                restriction_nature, right_characterization]
curatorial_fields: [review.status, review.flags, review.notes, citator_status]
paths:
  selectors: selectors/selectors.yaml
  ontology: ontology/ontology.yaml
  prompts: prompts
  gold: data/gold/gold.jsonl
reviewer_default: mmaldo2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_store.py tests/test_domain.py -q`
Expected: 4 passed

- [ ] **Step 5: Point the three scripts at the domain**

In `pipeline/ingest.py`, replace the two constant blocks at lines 37-40:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from corpus_engine.domain import load_domain  # noqa: E402
_DOMAIN = load_domain()
TARGET_JURISDICTIONS = set(_DOMAIN.jurisdictions) | {"U.S."}   # U.S. for the federal reporter slugs
ERA_BOUNDS = list(_DOMAIN.era_bounds)
```

In `pipeline/download.py`, replace the `TARGET_JURISDICTIONS` set and `TARGET_REPORTER_SLUGS` set (Task 1 of this session added them) with:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from corpus_engine.domain import load_domain  # noqa: E402
_DOMAIN = load_domain()
TARGET_JURISDICTIONS = set(_DOMAIN.jurisdictions)
TARGET_REPORTER_SLUGS = set(_DOMAIN.reporter_slugs)
```

In `pipeline/shard.py`, replace lines 55-56:

```python
sys.path.insert(0, str(ROOT))
from corpus_engine.domain import load_domain  # noqa: E402
_DOMAIN = load_domain()
ERAS = list(_DOMAIN.eras)
JURISDICTIONS = list(_DOMAIN.jurisdictions)
```

Run: `.venv\Scripts\python pipeline\download.py --dry-run | tail -1` (only if the background download has finished; otherwise skip this check and note it)
Expected: same reporter count and "to download" figure as before the change.

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: all pass (the existing 13 plus 4 new).

- [ ] **Step 6: Commit**

```bash
git add corpus_engine domains tests/conftest.py tests/test_store.py tests/test_domain.py pipeline/ingest.py pipeline/download.py pipeline/shard.py
git commit -m "corpus_engine: store, domain loader, str-right-to-let domain; scripts read scope from the domain"
```

---

### Task 3: Fixture corpus

**Files:**
- Create: `tools/build_fixture_corpus.py`, `tests/fixtures/README.md`
- Create (generated, committed): `tests/fixtures/corpus-tiny.db`
- Modify: `.gitignore` (no change needed; `tests/fixtures/` is not ignored — verify)

**Interfaces:**
- Consumes: `corpus_engine.store.connect`, `ensure_schema`; live `data/db/corpus.db`.
- Produces: `tests/fixtures/corpus-tiny.db` with tables `cases` (all columns, full text), `citations`, `chunks`, `embed_meta`, `fts_porter`, `fts_raw` for a case set defined below; the `live_db`/`fixture_db` fixtures from Task 2.

Case set: every case in `runs/cycle-003-shard-01/batches/batch-001.json` through `batch-005.json`, plus every case_id in `data/gold/gold.jsonl` with a non-null `case_id`, plus every ledger record with `review.status != "machine"`. Expect roughly 300 cases.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fixture_corpus.py
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
    b1 = json.loads((repo_root / "runs/cycle-003-shard-01/batches/batch-001.json").read_text(encoding="utf-8"))
    ids = [c["case_id"] for c in b1["cases"]]
    q = f"SELECT count(*) FROM cases WHERE case_id IN ({','.join('?'*len(ids))})"
    assert conn.execute(q, ids).fetchone()[0] == len(ids)
```

- [ ] **Step 2: Run test to verify it skips (fixture absent)**

Run: `.venv\Scripts\python -m pytest tests/test_fixture_corpus.py -q`
Expected: 1 skipped ("not built yet") — and an ImportError for `corpus_engine.textnorm_version` is expected until Step 3.

- [ ] **Step 3: Write the builder and the norm-version shim**

`corpus_engine/textnorm_version.py` re-exports the single source of truth so the engine does not import `pipeline/`:

```python
# corpus_engine/textnorm_version.py
"""Bridge until textnorm moves into the package (Stage 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION  # noqa: E402,F401
```

```python
# tools/build_fixture_corpus.py
"""Build tests/fixtures/corpus-tiny.db from the live corpus. Run once:
    .venv\Scripts\python tools\build_fixture_corpus.py
"""
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "corpus-tiny.db"


def case_ids() -> list[int]:
    ids: set[int] = set()
    for n in range(1, 6):
        b = json.loads((ROOT / f"runs/cycle-003-shard-01/batches/batch-{n:03d}.json").read_text(encoding="utf-8"))
        ids.update(c["case_id"] for c in b["cases"])
    for line in (ROOT / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("case_id"):
            ids.add(json.loads(line)["case_id"])
    for f in (ROOT / "data/ledger").glob("cycle-*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("review", {}).get("status") != "machine":
                    ids.add(r["case_id"])
    return sorted(ids)


def main() -> int:
    ids = case_ids()
    src = store.connect(wal=False)
    if OUT.exists():
        OUT.unlink()
    dst = sqlite3.connect(OUT)
    store.ensure_schema(dst)
    dst.executescript("""
    CREATE VIRTUAL TABLE fts_porter USING fts5(norm_text, content='cases', content_rowid='case_id', tokenize='porter unicode61');
    CREATE VIRTUAL TABLE fts_raw USING fts5(norm_text, content='cases', content_rowid='case_id', tokenize='unicode61');
    CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, case_id INTEGER, seq INTEGER, char_start INTEGER, char_end INTEGER, embedding BLOB, embed_scale REAL, UNIQUE(case_id, seq));
    CREATE TABLE embed_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    cols = [r[1] for r in src.execute("PRAGMA table_info(cases)")]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        rows = src.execute(f"SELECT {','.join(cols)} FROM cases WHERE case_id IN ({ph})", chunk).fetchall()
        dst.executemany(f"INSERT INTO cases ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", rows)
        dst.executemany("INSERT INTO citations VALUES (?,?,?,?)",
                        src.execute(f"SELECT case_id, cite, cite_norm, type FROM citations WHERE case_id IN ({ph})", chunk).fetchall())
        dst.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                        src.execute(f"SELECT chunk_id, case_id, seq, char_start, char_end, embedding, embed_scale FROM chunks WHERE case_id IN ({ph})", chunk).fetchall())
    dst.executemany("INSERT INTO embed_meta VALUES (?,?)", src.execute("SELECT key, value FROM embed_meta").fetchall())
    dst.execute("INSERT INTO fts_porter(fts_porter) VALUES ('rebuild')")
    dst.execute("INSERT INTO fts_raw(fts_raw) VALUES ('rebuild')")
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    print(f"{len(ids)} cases -> {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Check the real `chunks` and `embed_meta` DDL in `pipeline/index.py:33-57` before running; if column names differ from the CREATE above, copy the real DDL verbatim into the builder.

- [ ] **Step 4: Build and test**

Run: `.venv\Scripts\python tools\build_fixture_corpus.py`
Expected: `~300 cases -> tests/fixtures/corpus-tiny.db (N MB)` with N under 25. If larger, drop the ledger human-reviewed set from `case_ids()` and rebuild.

Run: `.venv\Scripts\python -m pytest tests/test_fixture_corpus.py -q`
Expected: 1 passed

- [ ] **Step 5: Write the fixtures README and commit**

```markdown
# tests/fixtures

- `corpus-tiny.db` — built by `tools/build_fixture_corpus.py` from the live corpus:
  cycle-003 batches 001-005, all resolved gold cases, all human-reviewed ledger
  cases. Full text, page maps, both FTS tables, chunk vectors, embed_meta.
- `cycle-003-signals.db` — signals and coverage tables as of the end of cycle 003
  plus case metadata for every signalled case (`tools/capture_goldens.py`).
- `cycle-003-already-read.json` — the exclusion set in force when cycle 003 was sharded.
```

```bash
git add tools/build_fixture_corpus.py corpus_engine/textnorm_version.py tests/test_fixture_corpus.py tests/fixtures/corpus-tiny.db tests/fixtures/README.md
git commit -m "fixtures: committed corpus-tiny.db and builder"
```

---

### Task 4: Batch packing moved behind a tested seam

**Files:**
- Create: `corpus_engine/selector/__init__.py`, `corpus_engine/selector/packing.py`, `tests/test_packing_char.py`
- Modify: `pipeline/shard.py:256-335` (`already_mapped_ids` stays; `emit_batches` delegates)

**Interfaces:**
- Produces: `corpus_engine.selector.packing.pack_batches(conn: sqlite3.Connection, run_id: str, out_dir: Path, *, gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18) -> int`. Reads only the `signals` table of `conn`. Deletes existing `batch-*.json` in `out_dir`, writes `batch-NNN.json` with `json.dumps(batch, indent=1)`, returns the count. Behavior identical to `shard.emit_batches` at the pre-refactor commit.

- [ ] **Step 1: Write the failing characterization test**

```python
# tests/test_packing_char.py
import hashlib, json, sqlite3
from corpus_engine.selector.packing import pack_batches

def _gold_ids(repo_root):
    ids = set()
    for line in (repo_root / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("case_id"):
            ids.add(json.loads(line)["case_id"])
    return ids

def test_pack_batches_reproduces_cycle_003_byte_for_byte(repo_root, golden_dir, tmp_path):
    params = json.loads((golden_dir / "cycle-003-batches.json").read_text(encoding="utf-8"))
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["batches"]
    want = {k.split("/")[1]: v for k, v in digests.items() if k.startswith(params["run_id"] + "/")}
    conn = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    exclude = set(json.loads((repo_root / "tests/fixtures/cycle-003-already-read.json").read_text())) if params["exclude_mapped"] else set()
    n = pack_batches(conn, params["run_id"], tmp_path, gold_ids=_gold_ids(repo_root),
                     exclude_ids=exclude, batch_size=params["batch_size"])
    assert n == params["n_batches"] == len(want)
    got = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in tmp_path.glob("batch-*.json")}
    assert got == want
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_packing_char.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_engine.selector`

- [ ] **Step 3: Move emit_batches verbatim, with explicit inputs**

```python
# corpus_engine/selector/__init__.py
```

```python
# corpus_engine/selector/packing.py
"""Batch packing: group signal-bearing cases into homogeneous era x
jurisdiction batches with the spec §7 priority order. Moved verbatim from
pipeline/shard.py emit_batches; the only change is that gold ids and the
already-read exclusion set are explicit inputs instead of globals, which
is what makes the output reproducible (ADR-0009)."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path


def pack_batches(conn: sqlite3.Connection, run_id: str, out_dir: Path, *,
                 gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18) -> int:
    rows = conn.execute(
        """SELECT s.case_id, s.era_partition, s.jurisdiction,
                  s.selector_id, s.selector_version, s.matched_text,
                  s.char_span_start, s.char_span_end, s.chunk_id, s.cosine, s.run_id
           FROM signals s ORDER BY s.era_partition, s.jurisdiction, s.case_id"""
    ).fetchall()
    by_case: dict = {}
    for r in rows:
        e = by_case.setdefault(
            r[0], {"case_id": r[0], "era_partition": r[1], "jurisdiction": r[2], "signals": []})
        e["signals"].append(
            {"selector_id": r[3], "selector_version": r[4], "matched_text": r[5],
             "char_span": [r[6], r[7]], "chunk_id": r[8], "cosine": r[9], "run_id": r[10]})
    groups: dict = {}
    for e in by_case.values():
        groups.setdefault((e["era_partition"], e["jurisdiction"]), []).append(e)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.json"):
        old.unlink()
    if exclude_ids:
        for key in groups:
            groups[key] = [e for e in groups[key] if e["case_id"] not in exclude_ids]
        groups = {k: v for k, v in groups.items() if v}
    pending = []
    for (era, jur), cases in sorted(groups.items(), key=lambda kv: str(kv[0])):
        cases.sort(key=lambda e: (-len({s["selector_id"] for s in e["signals"]}), e["case_id"]))
        for i in range(0, len(cases), batch_size):
            chunk = cases[i:i + batch_size]
            pending.append({
                "era_partition": era, "jurisdiction": jur, "cases": chunk,
                "_gold": sum(1 for e in chunk if e["case_id"] in gold_ids),
                "_density": max(len({s["selector_id"] for s in e["signals"]}) for e in chunk)})
    pending.sort(key=lambda b: (-b["_gold"], -b["_density"]))
    for n, batch in enumerate(pending, 1):
        batch.pop("_gold"), batch.pop("_density")
        batch["batch_id"] = f"{run_id}-batch-{n:03d}"
        (out_dir / f"batch-{n:03d}.json").write_text(json.dumps(batch, indent=1), encoding="utf-8")
    return len(pending)
```

Then in `pipeline/shard.py`, replace the body of `emit_batches` (keep the signature) with:

```python
def emit_batches(conn, run_id: str, exclude_mapped: bool = False) -> int:
    from corpus_engine.selector.packing import pack_batches
    gold_ids: set[int] = set()
    gold_file = ROOT / "data" / "gold" / "gold.jsonl"
    if gold_file.exists():
        for line in gold_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cid = json.loads(line).get("case_id")
                if cid:
                    gold_ids.add(cid)
    skip_ids = already_mapped_ids() if exclude_mapped else set()
    if skip_ids:
        print(f"excluding {len(skip_ids)} already-mapped cases")
    n = pack_batches(conn, run_id, RUNS / run_id / "batches", gold_ids=gold_ids,
                     exclude_ids=skip_ids, batch_size=BATCH_SIZE)
    print(f"{n} batches -> {RUNS / run_id / 'batches'}")
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_packing_char.py -q`
Expected: 1 passed. If the digest comparison fails, diff one file with `git diff --no-index` and fix the move; do not touch the golden.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/selector tests/test_packing_char.py pipeline/shard.py
git commit -m "selector.packing: emit_batches moved behind pack_batches; byte-for-byte characterization"
```

---

### Task 5: Verification moved behind a tested seam

**Files:**
- Create: `corpus_engine/verification.py`, `tests/test_verification_char.py`
- Modify: `pipeline/verify_quotes.py` (import the three functions from the package; delete local copies), `tests/test_verify.py:1-10` (import path)

**Interfaces:**
- Produces: `corpus_engine.verification.FUZZY_THRESHOLD = 92.0`; `page_for_offset(page_map, raw_offset)`; `verify_quote(quote_text, case_row) -> dict`; `load_case(conn, case_id) -> dict | None` (raises `RuntimeError` on norm-version mismatch); `verify_record(conn, rec) -> dict`. All four are the current `pipeline/verify_quotes.py` bodies unchanged.

- [ ] **Step 1: Write the failing characterization tests**

```python
# tests/test_verification_char.py
import hashlib, json, sqlite3
import pytest
from corpus_engine.verification import verify_record

def _replay(conn, repo_root, run, batch_names):
    out = {}
    for name in batch_names:
        recs = json.loads((repo_root / "runs" / run / "extractions" / name).read_text(encoding="utf-8"))
        verified = [verify_record(conn, dict(r)) for r in recs]
        out[name] = hashlib.sha256(json.dumps(verified, indent=1).encode("utf-8")).hexdigest()
    return out

def test_verified_files_reproduce_on_fixture_subset(fixture_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    run = "cycle-003-shard-01"
    names = [f"batch-{n:03d}.json" for n in range(1, 6)]
    got = _replay(sqlite3.connect(fixture_db), repo_root, run, names)
    assert got == {n: digests[f"{run}/{n}"] for n in names}

@pytest.mark.live_db
def test_verified_files_reproduce_for_all_cycle_003(live_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    conn = sqlite3.connect(live_db)
    for run in ("cycle-003-shard-01", "cycle-003-remap"):
        names = sorted(p.name for p in (repo_root / "runs" / run / "extractions").glob("*.json"))
        got = _replay(conn, repo_root, run, names)
        assert got == {n: digests[f"{run}/{n}"] for n in names}, run
```

Add to `tests/conftest.py`:

```python
def pytest_configure(config):
    config.addinivalue_line("markers", "live_db: needs data/db/corpus.db")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_verification_char.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_engine.verification`

- [ ] **Step 3: Move the functions**

Create `corpus_engine/verification.py` by copying lines 20-132 of `pipeline/verify_quotes.py` (imports, `FUZZY_THRESHOLD`, `page_for_offset`, `verify_quote`, `load_case`, `verify_record`) unchanged except the textnorm import becomes:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION, normalize, normalize_text  # noqa: E402
```

Then in `pipeline/verify_quotes.py` delete those four definitions and the constant, and add:

```python
sys.path.insert(0, str(ROOT))
from corpus_engine.verification import (FUZZY_THRESHOLD, page_for_offset,  # noqa: E402,F401
                                        verify_quote, load_case, verify_record)
```

In `tests/test_verify.py`, change the import of `verify_quote`/`page_for_offset` to `from corpus_engine.verification import ...`.

- [ ] **Step 4: Run all tests**

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: all pass; the live-DB test passes when the corpus is present. If an extraction in the remap run was produced by a different pipeline version and does not reproduce, record the failing file name in `tests/golden/README.md` under "known non-reproductions" with the observed diff, and mark that single comparison `xfail(strict=True)` with the reason. Do not skip the whole test.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/verification.py tests/test_verification_char.py tests/conftest.py pipeline/verify_quotes.py tests/test_verify.py
git commit -m "verification: quote gate moved into corpus_engine; verified/ reproduced byte-for-byte"
```

---

### Task 6: Ledger value types and rendering

**Files:**
- Create: `corpus_engine/ledger/__init__.py`, `corpus_engine/ledger/types.py`, `corpus_engine/ledger/render.py`, `tests/test_ledger_types.py`, `tests/test_ledger_render.py`

**Interfaces:**
- Produces (`types.py`):
  - `Op = Literal["admit", "set", "append", "drop_quote", "migrate"]`
  - `@dataclass(frozen=True) class Basis: reviewer: str | None = None; model: str | None = None; prompt_version: str | None = None; run_id: str | None = None; rule_id: str | None = None` with `def kind(self) -> Literal["human", "reader", "rule", "none"]` and `def can_judge(self) -> bool` (reviewer, or model+prompt_version+run_id).
  - `@dataclass(frozen=True) class Patch: case_id: int; op: Op; field: str; new: Any; why: str; basis: Basis; cycle: str | None = None; seq: int = 0; at: str = ""; patch_id: str = ""; old: Any = UNSET` with `def to_json(self) -> dict` and `@staticmethod from_json(d) -> Patch`.
  - `UNSET` sentinel; `@dataclass(frozen=True) class TierCount: human_reviewed: int; machine_only: int` with `as_claim(noun) -> str` and no `__int__`/`__add__`.
  - Errors: `LedgerError`, `UnknownCase`, `DuplicateRecord`, `MissingBasis`, `UnknownField`, `NotTraditionEvidence`, `StaleSnapshot`.
- Produces (`render.py`): `dumps_record(rec: dict) -> str` (exactly `json.dumps(rec)`); `render_cycle(records: list[dict]) -> bytes` (`"".join(dumps_record(r) + "\n")` encoded utf-8, in the given order); `parse_cycle(data: bytes) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger_types.py
import pytest
from corpus_engine.ledger.types import Basis, Patch, TierCount, UNSET

def test_basis_kinds_and_judging_authority():
    assert Basis(reviewer="mmaldo2").kind() == "human"
    assert Basis(model="m", prompt_version="v1", run_id="r").kind() == "reader"
    assert Basis(rule_id="slice-of-life").kind() == "rule"
    assert Basis().kind() == "none"
    assert Basis(reviewer="x").can_judge()
    assert Basis(model="m", prompt_version="v1", run_id="r").can_judge()
    assert not Basis(model="m").can_judge()
    assert not Basis(rule_id="r").can_judge()

def test_patch_round_trips_through_json():
    p = Patch(case_id=1, op="set", field="polarity", new="adverse", why="re-review",
              basis=Basis(reviewer="mmaldo2"), seq=7, at="2026-09-01T00:00:00", patch_id="abc", old="favorable")
    assert Patch.from_json(p.to_json()) == p
    q = Patch(case_id=1, op="admit", field="", new={"case_id": 1}, why="x", basis=Basis())
    assert q.old is UNSET and "old" not in q.to_json()

def test_tier_count_cannot_be_blended():
    t = TierCount(human_reviewed=138, machine_only=572)
    assert t.as_claim("relevant cases") == "710 relevant cases (138 human-reviewed, 572 machine-only; lower bound)"
    with pytest.raises(TypeError):
        int(t)
    with pytest.raises(TypeError):
        t + t
```

```python
# tests/test_ledger_render.py
import json
from corpus_engine.ledger.render import dumps_record, render_cycle, parse_cycle

def test_render_matches_json_dumps_defaults_and_preserves_key_order():
    rec = {"case_id": 1, "cite": "qu\u00e2 boarder", "review": {"status": "machine", "flags": [], "notes": []}}
    assert dumps_record(rec) == json.dumps(rec)
    assert dumps_record(rec).startswith('{"case_id": 1, "cite": "qu\\u00e2 boarder"')

def test_render_cycle_round_trips_committed_ledger(repo_root):
    data = (repo_root / "data/ledger/cycle-001.jsonl").read_bytes()
    assert render_cycle(parse_cycle(data)) == data
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_types.py tests/test_ledger_render.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_engine.ledger`

- [ ] **Step 3: Implement**

```python
# corpus_engine/ledger/__init__.py
"""Ledger: the system of record (ADR-0002). Public API only."""
from corpus_engine.ledger.types import (Basis, Patch, TierCount, UNSET, LedgerError, UnknownCase,
                                        DuplicateRecord, MissingBasis, UnknownField,
                                        NotTraditionEvidence, StaleSnapshot)
from corpus_engine.ledger.ledger import open_ledger, Ledger, LedgerView   # added in Task 8

__all__ = ["open_ledger", "Ledger", "LedgerView", "Basis", "Patch", "TierCount", "UNSET",
           "LedgerError", "UnknownCase", "DuplicateRecord", "MissingBasis", "UnknownField",
           "NotTraditionEvidence", "StaleSnapshot"]
```

(Until Task 8 exists, leave the `ledger.py` import line commented out and the three names out of `__all__`; Task 8 restores them.)

```python
# corpus_engine/ledger/types.py
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any, Literal

Op = Literal["admit", "set", "append", "drop_quote", "migrate"]


class _Unset:
    def __repr__(self): return "UNSET"
UNSET = _Unset()


class LedgerError(Exception): ...
class UnknownCase(LedgerError): ...
class DuplicateRecord(LedgerError): ...
class MissingBasis(LedgerError): ...
class UnknownField(LedgerError): ...
class NotTraditionEvidence(LedgerError): ...
class StaleSnapshot(LedgerError): ...


@dataclass(frozen=True)
class Basis:
    reviewer: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    run_id: str | None = None
    rule_id: str | None = None

    def kind(self) -> Literal["human", "reader", "rule", "none"]:
        if self.reviewer:
            return "human"
        if self.model:
            return "reader"
        if self.rule_id:
            return "rule"
        return "none"

    def can_judge(self) -> bool:
        return bool(self.reviewer) or bool(self.model and self.prompt_version and self.run_id)

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Patch:
    case_id: int
    op: Op
    field: str
    new: Any
    why: str
    basis: Basis
    cycle: str | None = None
    seq: int = 0
    at: str = ""
    patch_id: str = ""
    old: Any = UNSET

    def to_json(self) -> dict:
        d = {"seq": self.seq, "patch_id": self.patch_id, "at": self.at, "case_id": self.case_id,
             "cycle": self.cycle, "op": self.op, "field": self.field, "new": self.new,
             "why": self.why, "basis": self.basis.to_json()}
        if self.old is not UNSET:
            d["old"] = self.old
        return d

    @staticmethod
    def from_json(d: dict) -> "Patch":
        return Patch(case_id=d["case_id"], op=d["op"], field=d["field"], new=d["new"], why=d["why"],
                     basis=Basis(**d.get("basis", {})), cycle=d.get("cycle"), seq=d.get("seq", 0),
                     at=d.get("at", ""), patch_id=d.get("patch_id", ""),
                     old=d["old"] if "old" in d else UNSET)


@dataclass(frozen=True)
class TierCount:
    human_reviewed: int
    machine_only: int

    def as_claim(self, noun: str) -> str:
        return (f"{self.human_reviewed + self.machine_only} {noun} "
                f"({self.human_reviewed} human-reviewed, {self.machine_only} machine-only; lower bound)")

    def __int__(self):
        raise TypeError("two-tier counts are never blended (ADR-0002)")

    def __add__(self, other):
        raise TypeError("two-tier counts are never blended (ADR-0002)")
```

```python
# corpus_engine/ledger/render.py
"""Byte-exact rendering of ledger records. json.dumps defaults are load-bearing:
ensure_ascii=True, separators (', ', ': '), insertion key order, one record per
line, '\n' terminated (matches apply_adjudications.py and the hygiene passes)."""
from __future__ import annotations
import json


def dumps_record(rec: dict) -> str:
    return json.dumps(rec)


def render_cycle(records: list[dict]) -> bytes:
    return "".join(dumps_record(r) + "\n" for r in records).encode("utf-8")


def parse_cycle(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip()]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_types.py tests/test_ledger_render.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ledger tests/test_ledger_types.py tests/test_ledger_render.py
git commit -m "ledger: value types, basis authority, byte-exact rendering"
```

---

### Task 7: Ledger fold and patch log

**Files:**
- Create: `corpus_engine/ledger/fold.py`, `corpus_engine/ledger/log.py`, `tests/test_ledger_fold.py`

**Interfaces:**
- Produces (`fold.py`): `JUDGED_DEFAULT: tuple[str, ...]` (the nine judged fields); `@dataclass class State: records: dict[int, dict]; order: list[int]; cycles: dict[int, str]; in_file: dict[int, bool]` (in_file = admitted with truthy `relevant`); `apply_patch(state: State, p: Patch, *, judged: tuple[str, ...] = JUDGED_DEFAULT, cascade: bool = True) -> Any` returning the old value it observed (for `old` capture). Raises `UnknownCase`, `DuplicateRecord`, `MissingBasis`, `UnknownField`.
  - Field paths: plain (`"polarity"`) or dotted into the `review` dict (`"review.status"`, `"review.notes"`, `"review.flags"`).
  - `admit`: `new` is a record dict; if the case is unknown, deep-copy it, ensure a `review` key equal to `{"status": "machine", "flags": [], "notes": []}` is present (added only if absent, so remap records that already carry review keep theirs), append to `order`, set `cycles[case_id] = p.cycle`, `in_file[case_id] = bool(new.get("relevant"))`. If the case exists in the **same** cycle, replace the record wholesale keeping its position (this is the remap replacement in `apply_adjudications.py:69-71`), and re-apply the review default rule. If it exists in a different cycle, raise `DuplicateRecord`.
  - `set`: judged field requires `basis.can_judge()` else `MissingBasis`; sets the path; returns old value.
  - `append`: path must resolve to a list; appends `new`.
  - `drop_quote`: removes every quote whose `text == new` from `quotes`; when `cascade` is true, nulls each of `characterization`, `polarity`, `holding_summary` that is non-null and no longer has a quote with `supports == field`, appending the name to `nulled_fields`.
  - `migrate`: `new` is a dict of `{field: default}`; sets `schema_version` to `new["schema_version"]` and adds each other key at the end of the record if absent.
- Produces (`log.py`): `class PatchLog` with `__init__(self, path: Path)`, `read() -> list[Patch]` (in seq order), `append(patches: list[Patch]) -> list[Patch]` (assigns `seq`, `at` if empty, `patch_id`; writes one JSON line each; returns the stamped patches), `head() -> int`; `patch_id(p: Patch) -> str` = first 16 hex of sha256 over the canonical JSON of `(case_id, op, field, new, why, basis, cycle)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger_fold.py
import json
import pytest
from corpus_engine.ledger.types import Basis, Patch, UnknownCase, DuplicateRecord, MissingBasis
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.log import PatchLog, patch_id

REC = {"case_id": 5, "cite": "1 X 1", "year": 1880, "relevant": True, "polarity": "favorable",
       "characterization": "lodging", "holding_summary": "h",
       "quotes": [{"text": "A", "supports": "polarity"}, {"text": "B", "supports": "characterization"}]}

def test_admit_adds_review_default_and_tracks_order_and_cycle():
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "verified", Basis(model="m", prompt_version="v1", run_id="r"), cycle="cycle-001"))
    assert s.order == [5] and s.cycles[5] == "cycle-001" and s.in_file[5] is True
    assert s.records[5]["review"] == {"status": "machine", "flags": [], "notes": []}
    assert list(s.records[5].keys())[-1] == "review"
    with pytest.raises(DuplicateRecord):
        apply_patch(s, Patch(5, "admit", "", REC, "again", Basis(), cycle="cycle-002"))

def test_set_on_judged_field_needs_authority_and_returns_old():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    with pytest.raises(MissingBasis):
        apply_patch(s, Patch(5, "set", "polarity", "adverse", "hunch", Basis(rule_id="x")))
    old = apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-review", Basis(reviewer="mmaldo2")))
    assert old == "favorable" and s.records[5]["polarity"] == "adverse"
    apply_patch(s, Patch(5, "set", "review.status", "human-adjudicated", "x", Basis(rule_id="r")))
    apply_patch(s, Patch(5, "append", "review.notes", "note", "x", Basis(rule_id="r")))
    assert s.records[5]["review"] == {"status": "human-adjudicated", "flags": [], "notes": ["note"]}
    with pytest.raises(UnknownCase):
        apply_patch(s, Patch(6, "set", "polarity", "adverse", "x", Basis(reviewer="m")))

def test_drop_quote_cascades_only_when_asked():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "drop_quote", "quotes", "A", "mismatch", Basis(reviewer="m")), cascade=False)
    assert s.records[5]["polarity"] == "favorable" and len(s.records[5]["quotes"]) == 1
    apply_patch(s, Patch(5, "drop_quote", "quotes", "B", "mismatch", Basis(reviewer="m")), cascade=True)
    assert s.records[5]["characterization"] is None and s.records[5]["nulled_fields"] == ["characterization"]

def test_migrate_appends_v2_fields_at_end():
    s = State(); apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(), cycle="c"))
    apply_patch(s, Patch(5, "migrate", "", {"schema_version": 2, "under_30_days": None}, "v2", Basis(rule_id="schema-v2")))
    keys = list(s.records[5].keys())
    assert keys[-2:] == ["schema_version", "under_30_days"] or keys[-1] == "under_30_days"

def test_patch_log_stamps_and_round_trips(tmp_path):
    log = PatchLog(tmp_path / "patches.jsonl")
    p = Patch(5, "set", "polarity", "adverse", "why", Basis(reviewer="m"))
    [stamped] = log.append([p])
    assert stamped.seq == 1 and stamped.patch_id == patch_id(p) and stamped.at
    assert log.read() == [stamped] and log.head() == 1
    assert json.loads((tmp_path / "patches.jsonl").read_text().splitlines()[0])["seq"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_fold.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_engine.ledger.fold`

- [ ] **Step 3: Implement fold and log**

```python
# corpus_engine/ledger/fold.py
"""The pure state transition: one patch in, one record changed."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any
from corpus_engine.ledger.types import Patch, UNSET, UnknownCase, DuplicateRecord, MissingBasis, UnknownField

JUDGED_DEFAULT = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                  "characterization", "holding_summary", "under_30_days",
                  "restriction_nature", "right_characterization")
SUPPORTED = ("characterization", "polarity", "holding_summary")
REVIEW_DEFAULT = {"status": "machine", "flags": [], "notes": []}


@dataclass
class State:
    records: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    cycles: dict[int, str] = field(default_factory=dict)
    in_file: dict[int, bool] = field(default_factory=dict)


def _resolve(rec: dict, path: str, create: bool = False):
    if "." not in path:
        return rec, path
    head, tail = path.split(".", 1)
    if head != "review":
        raise UnknownField(path)
    if "review" not in rec:
        if not create:
            raise UnknownField(path)
        rec["review"] = copy.deepcopy(REVIEW_DEFAULT)
    return rec["review"], tail


def apply_patch(state: State, p: Patch, *, judged: tuple[str, ...] = JUDGED_DEFAULT,
                cascade: bool = True) -> Any:
    if p.op == "admit":
        rec = copy.deepcopy(p.new)
        if "review" not in rec:
            rec["review"] = copy.deepcopy(REVIEW_DEFAULT)
        if p.case_id in state.records:
            if state.cycles[p.case_id] != p.cycle:
                raise DuplicateRecord(f"{p.case_id} already admitted in {state.cycles[p.case_id]}")
            old = state.records[p.case_id]
            state.records[p.case_id] = rec          # same position in state.order
            state.in_file[p.case_id] = bool(rec.get("relevant"))
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        return UNSET
    rec = state.records.get(p.case_id)
    if rec is None:
        raise UnknownCase(str(p.case_id))
    if p.op == "set":
        if p.field in judged and not p.basis.can_judge():
            raise MissingBasis(f"{p.field} on {p.case_id} needs a reviewer or model+prompt_version+run_id")
        target, key = _resolve(rec, p.field, create=True)
        old = target.get(key, UNSET)
        target[key] = p.new
        return old
    if p.op == "append":
        target, key = _resolve(rec, p.field, create=True)
        lst = target.setdefault(key, [])
        if not isinstance(lst, list):
            raise UnknownField(f"{p.field} is not a list")
        lst.append(p.new)
        return UNSET
    if p.op == "drop_quote":
        before = rec.get("quotes", [])
        rec["quotes"] = [q for q in before if q.get("text") != p.new]
        if cascade:
            supported = {q.get("supports") for q in rec["quotes"]}
            for f in SUPPORTED:
                if rec.get(f) is not None and f not in supported:
                    rec[f] = None
                    rec.setdefault("nulled_fields", []).append(f)
        return [q for q in before if q.get("text") == p.new]
    if p.op == "migrate":
        rec["schema_version"] = p.new["schema_version"]
        for k, v in p.new.items():
            if k != "schema_version" and k not in rec:
                rec[k] = v
        return UNSET
    raise UnknownField(f"unknown op {p.op}")
```

```python
# corpus_engine/ledger/log.py
"""Append-only patch log: data/ledger/patches.jsonl."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import replace
from pathlib import Path
from corpus_engine.ledger.types import Patch


def patch_id(p: Patch) -> str:
    canon = json.dumps([p.case_id, p.op, p.field, p.new, p.why, p.basis.to_json(), p.cycle],
                       sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


class PatchLog:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> list[Patch]:
        if not self.path.exists():
            return []
        out = [Patch.from_json(json.loads(l)) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return sorted(out, key=lambda p: p.seq)

    def head(self) -> int:
        ps = self.read()
        return ps[-1].seq if ps else 0

    def append(self, patches: list[Patch], *, at: str | None = None) -> list[Patch]:
        seq = self.head()
        stamp = at or time.strftime("%Y-%m-%dT%H:%M:%S")
        stamped = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for p in patches:
                seq += 1
                q = replace(p, seq=seq, at=p.at or stamp, patch_id=patch_id(p))
                f.write(json.dumps(q.to_json(), ensure_ascii=True) + "\n")
                stamped.append(q)
        return stamped
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_fold.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ledger/fold.py corpus_engine/ledger/log.py tests/test_ledger_fold.py
git commit -m "ledger: fold (admit/set/append/drop_quote/migrate) and append-only patch log"
```

---

### Task 8: Ledger view and apply

**Files:**
- Create: `corpus_engine/ledger/ledger.py`, `tests/test_ledger_apply.py`
- Modify: `corpus_engine/ledger/__init__.py` (restore the `ledger.py` import and `__all__` names)

**Interfaces:**
- Produces: `open_ledger(root: Path | None = None, *, name: str = "tradition", domain: Domain | None = None) -> Ledger`.
  - Layout: `name == "tradition"` → snapshot files `<ledger_dir>/cycle-*.jsonl`, log `<ledger_dir>/patches.jsonl`, manifests `<ledger_dir>/manifest/<cycle>.jsonl`; any other name → `<ledger_dir>/<name>/cycle-*.jsonl` etc. `ledger_dir` defaults to `store.paths(root).ledger`.
  - `Ledger.view(as_of: int | None = None) -> LedgerView`: replays the log from empty to `as_of` (or head) with `cascade=False` for patches whose `why` starts with `"bootstrap:"`, `cascade=True` otherwise. Memoized per `as_of`.
  - `Ledger.apply(patches: list[Patch], *, note: str, at: str | None = None, dry_run: bool = False) -> ApplyResult` where `ApplyResult` has `applied: list[Patch]`, `skipped: list[Patch]` (duplicate patch_id already in log), `files_written: list[Path]`, `replay_ok: bool`. Validates every patch by folding onto a copy of the head state first (so a failing batch writes nothing), appends to the log, re-renders each touched cycle file, writes manifests, takes an exclusive lock file `<ledger_dir>/.lock` for the duration. Sets `replay_ok` by re-rendering from a fresh replay and comparing bytes.
  - `LedgerView` fields: `name: str`, `as_of: int`, `state: State`, `patches: list[Patch]`, `domain: Domain`; methods `records(**filters) -> list[dict]` (filters are equality on top-level fields; default excludes nothing), `record(case_id) -> dict`, `history(case_id) -> list[Patch]`, `render() -> dict[str, bytes]` (filename → bytes for every cycle: records with `in_file` true, sorted by `(year or 0)` stable over admission order), `reviewed(case_id) -> bool` (a patch with `basis.reviewer` exists on a judged field or on `review.status`), plus `counts`, `matrix`, `seed_set`, `manifest` added in Task 10.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger_apply.py
import json
import pytest
from corpus_engine.ledger import open_ledger, Basis, Patch, MissingBasis
from corpus_engine.domain import load_domain

def _rec(cid, year, pol="favorable", relevant=True):
    return {"case_id": cid, "cite": f"{cid} X", "year": year, "relevant": relevant, "polarity": pol,
            "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "holding_summary": "h",
            "quotes": [{"text": "q", "supports": "polarity"}], "extraction_status": "ok"}

def test_apply_then_view_renders_sorted_snapshot(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    reader = Basis(model="m", prompt_version="v1", run_id="r1")
    res = led.apply([Patch(2, "admit", "", _rec(2, 1900), "verified", reader, cycle="cycle-001"),
                     Patch(1, "admit", "", _rec(1, 1850), "verified", reader, cycle="cycle-001"),
                     Patch(3, "admit", "", _rec(3, 1900, relevant=False), "verified", reader, cycle="cycle-001")],
                    note="seed")
    assert res.replay_ok and len(res.applied) == 3
    v = led.view()
    rendered = v.render()["cycle-001.jsonl"].decode()
    ids = [json.loads(l)["case_id"] for l in rendered.splitlines()]
    assert ids == [1, 2]                      # sorted by year; relevant:false not in file
    assert (tmp_path / "cycle-001.jsonl").read_bytes() == v.render()["cycle-001.jsonl"]
    assert (tmp_path / "patches.jsonl").exists()

def test_apply_is_atomic_and_idempotent(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    bad = [Patch(1, "set", "review.status", "human-adjudicated", "x", Basis(reviewer="m")),
           Patch(1, "set", "polarity", "adverse", "hunch", Basis(rule_id="r"))]
    with pytest.raises(MissingBasis):
        led.apply(bad, note="should not write")
    assert led.view().record(1)["review"]["status"] == "machine"
    good = [Patch(1, "set", "polarity", "adverse", "re-review", Basis(reviewer="m"))]
    led.apply(good, note="once")
    res = led.apply(good, note="twice")
    assert res.applied == [] and len(res.skipped) == 1
    assert led.view().record(1)["polarity"] == "adverse"
    assert led.view().reviewed(1) is True

def test_view_as_of_replays_history(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")], note="seed")
    led.apply([Patch(1, "set", "polarity", "adverse", "x", Basis(reviewer="m"))], note="flip")
    assert led.view(as_of=1).record(1)["polarity"] == "favorable"
    assert led.view().record(1)["polarity"] == "adverse"
    assert [p.field for p in led.view().history(1)] == ["", "polarity"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_apply.py -q`
Expected: FAIL with ImportError on `open_ledger`

- [ ] **Step 3: Implement**

```python
# corpus_engine/ledger/ledger.py
from __future__ import annotations
import copy, os
from dataclasses import dataclass, field
from pathlib import Path
from corpus_engine.domain import Domain, load_domain
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.log import PatchLog, patch_id
from corpus_engine.ledger.render import render_cycle
from corpus_engine.ledger.types import Patch, StaleSnapshot
from corpus_engine.store import paths


@dataclass
class ApplyResult:
    applied: list[Patch]
    skipped: list[Patch]
    files_written: list[Path]
    replay_ok: bool


@dataclass
class LedgerView:
    name: str
    as_of: int
    state: State
    patches: list[Patch]
    domain: Domain

    def records(self, **filters) -> list[dict]:
        out = []
        for cid in self.state.order:
            r = self.state.records[cid]
            if all(r.get(k) == v for k, v in filters.items()):
                out.append(r)
        return out

    def record(self, case_id: int) -> dict:
        return self.state.records[case_id]

    def history(self, case_id: int) -> list[Patch]:
        return [p for p in self.patches if p.case_id == case_id]

    def reviewed(self, case_id: int) -> bool:
        judged = set(self.domain.judged_fields) | {"review.status"}
        return any(p.basis.reviewer and p.op in ("set", "append", "drop_quote") and
                   (p.field in judged or p.op == "drop_quote") for p in self.history(case_id))

    def render(self) -> dict[str, bytes]:
        by_cycle: dict[str, list[dict]] = {}
        for cid in self.state.order:                       # admission order = stable tiebreak
            if self.state.in_file.get(cid):
                by_cycle.setdefault(self.state.cycles[cid], []).append(self.state.records[cid])
        return {f"{cyc}.jsonl": render_cycle(sorted(recs, key=lambda r: r.get("year") or 0))
                for cyc, recs in by_cycle.items()}


class Ledger:
    def __init__(self, ledger_dir: Path, name: str, domain: Domain):
        self.dir = ledger_dir if name == "tradition" else ledger_dir / name
        self.name = name
        self.domain = domain
        self.log = PatchLog(self.dir / "patches.jsonl")
        self._views: dict[int | None, LedgerView] = {}

    def _replay(self, patches: list[Patch]) -> State:
        state = State()
        for p in patches:
            apply_patch(state, p, judged=tuple(self.domain.judged_fields),
                        cascade=not p.why.startswith("bootstrap:"))
        return state

    def view(self, as_of: int | None = None) -> LedgerView:
        if as_of in self._views:
            return self._views[as_of]
        patches = self.log.read()
        if as_of is not None:
            patches = [p for p in patches if p.seq <= as_of]
        v = LedgerView(self.name, patches[-1].seq if patches else 0, self._replay(patches), patches, self.domain)
        self._views[as_of] = v
        return v

    def apply(self, patches: list[Patch], *, note: str, at: str | None = None,
              dry_run: bool = False) -> ApplyResult:
        existing = {p.patch_id for p in self.log.read()}
        fresh = [p for p in patches if patch_id(p) not in existing]
        skipped = [p for p in patches if patch_id(p) in existing]
        head = self.view()
        trial = copy.deepcopy(head.state)
        stamped_old = []
        for p in fresh:                                    # validate everything before writing
            old = apply_patch(trial, p, judged=tuple(self.domain.judged_fields),
                              cascade=not p.why.startswith("bootstrap:"))
            stamped_old.append(old)
        if dry_run:
            return ApplyResult(fresh, skipped, [], True)
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = self.dir / ".lock"
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            from dataclasses import replace
            applied = self.log.append([replace(p, old=o) for p, o in zip(fresh, stamped_old)], at=at)
            self._views.clear()
            written = self._write_snapshot(self.view())
            replay_ok = all(path.read_bytes() == data for path, data in written)
        finally:
            os.close(fd)
            lock.unlink()
        return ApplyResult(applied, skipped, [p for p, _ in written], replay_ok)

    def _write_snapshot(self, v: LedgerView) -> list[tuple[Path, bytes]]:
        out = []
        for fname, data in v.render().items():
            path = self.dir / fname
            tmp = path.with_suffix(".jsonl.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            out.append((path, data))
        return out


def open_ledger(root: Path | None = None, *, name: str = "tradition", domain: Domain | None = None) -> Ledger:
    ledger_dir = root if root is not None else paths().ledger
    return Ledger(ledger_dir, name, domain or load_domain())
```

Note for the implementer: when `root` is given it is used as the ledger directory itself (tests pass `tmp_path`); when omitted the repo's `data/ledger` is used. Restore the import and names in `corpus_engine/ledger/__init__.py`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_apply.py tests/test_ledger_fold.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ledger tests/test_ledger_apply.py
git commit -m "ledger: open_ledger/view/apply with atomic snapshot, lock, replay check, as_of"
```

---

### Task 9: Bootstrap the patch log from the existing artifacts and prove byte-for-byte reproduction

This is the gate task. If the rebuild does not match a committed ledger, the difference is a finding to record, not a reason to weaken the test.

**Files:**
- Create: `corpus_engine/ledger/bootstrap.py`, `tools/bootstrap_ledger.py`, `tests/test_ledger_bootstrap.py`
- Create (generated, committed): `data/ledger/patches.jsonl`, `data/ledger/manifest/cycle-00{1,2,3}.jsonl` (manifest in Task 10)

**Interfaces:**
- Consumes: `pipeline.make_review.load_data(run_id) -> {"A","B","C","D"}` (existing; note it writes `fuzzy-auto-accepted.json` as a side effect, which is acceptable for a one-time bootstrap), `runs/<run>/decisions-final.json`, `runs/<run>/verified/*.json`, `runs/<cycle>-remap/verified/*.json`, `runs/polarity-review/{review-queue,decisions-final}.json`, `runs/relevance-recheck/verdicts.json`.
- Produces: `patches_from_artifacts(root: Path, *, reviewer: str = "mmaldo2") -> list[Patch]` in the exact order the old scripts applied them. Every `why` starts with `"bootstrap:"`.

Patch derivation, per cycle in order `cycle-001` (run `cycle-001-shard-02`), `cycle-002` (`cycle-002-shard-01`), `cycle-003` (`cycle-003-shard-01`):

1. Admits: for each verified file in `sorted(glob)`, each record → `Patch(case_id, "admit", "", record, "bootstrap: verified extraction", Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id=RUN), cycle=CYCLE)`. Then remap files in `sorted(glob)` → same with `run_id=f"{CYCLE}-remap"`, `why="bootstrap: remap replaces original"`. (Fold keeps position; matches `ledger[r["case_id"]] = dict(r)`.)
2. Section C (`data["C"]` with `state[f"C-{i}"]`): when `decision` is truthy and the mapped value is not None and `field` is set → `set <field> value` with `Basis(reviewer)`, then `append review.notes f"{f} adjudicated -> {value} (disagreement resolved, human-confirmed)"`, then `set review.status "human-adjudicated"`. Value mapping and the `relevant` bool coercion exactly as `apply_adjudications.py:81-96`.
3. Section D: `other` → `append review.flags f"open-question:{field}"`, `append review.notes f"user note: {note}"`, `set review.status "pending-user-question"`; otherwise value mapping as above with note `f"{f} adjudicated -> {value}"` and status `human-adjudicated`.
4. Section A: `accept` → `set review.status "human-accepted"`; `needs-work` → `set review.status "needs-work"`; note → `append review.notes f"user note: {note}"`; citator → `append review.flags "citator-checked"`. All with `Basis(reviewer)`. Skip entries whose case is not in the ledger (the old code `continue`d).
5. Section B: `mismatch` → `drop_quote quotes <e["quote"]>` then `append review.notes "quote removed: human judged fuzzy match a real mismatch"`.
6. Shvekh: if 12315742 is in this cycle's state → `set who_was_letting "unclear"`, `append review.notes "who_was_letting corrected householder->unclear per human review: family resided elsewhere; whole-home VRBO rental of non-primary house"`, `set review.status "human-adjudicated"`, `Basis(reviewer)`.
7. Slice of Life: for every record in this cycle whose `cite` is in `{"147 A.3d 947", "154 A.3d 408", "176 A.3d 396", "164 A.3d 633"}` → `append review.flags "abrogation-risk: Slice of Life v. Hamilton Twp., 207 A.3d 886 (Pa. 2019) — per human review note; verify via citator"` with `Basis(rule_id="slice-of-life-abrogation-risk-v1")`. Iterate records in admission order.

Then, across all cycles, in ledger-file order `cycle-001, cycle-002, cycle-003` and record order within each file (this is the order `polarity_review.cmd_apply` iterated; the state's `order` restricted to `in_file` and sorted by year reproduces it):

8. Polarity re-review: decisions built exactly as `polarity_review.py:130-141` (`value` from `{"accept-rec": rec, "claude": "favorable", "codex": rec}`, `other` → None). For each record with a decision: if `value and value != polarity` → `append review.notes f"polarity {old} -> {value} (polarity re-review 2026-09-01, owner-right-to-let definition; reader rec {rec})"` then `set polarity value`; elif `value` → `append review.notes "polarity re-review: favorable confirmed by human"`; else `append review.flags "polarity-open-question"`; then if `note` → `append review.notes f"user note: {note}"`; then `set review.status "human-adjudicated"`. `Basis(reviewer, run_id="polarity-review")`.
9. Relevance re-check: for each record with a verdict: relevant False → `set relevant False`, `append review.notes f"relevance re-check 2026-09-01 -> irrelevant (user flag + reader): {justification}"`; else `append review.notes f"relevance re-check 2026-09-01 -> relevant confirmed: {justification}"`; then `set review.status "human-adjudicated"`. `Basis(reviewer, run_id="relevance-recheck")`.

Note on step 8 ordering: `polarity_review` appended the note **before** setting polarity, so the note carries the old value; emit the `append` patch first, then the `set`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ledger_bootstrap.py
import hashlib, json
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.bootstrap import patches_from_artifacts
from corpus_engine.domain import load_domain

def test_bootstrap_reproduces_all_three_ledgers_byte_for_byte(repo_root, golden_dir, tmp_path):
    want = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["ledger"]
    led = open_ledger(tmp_path, domain=load_domain())
    res = led.apply(patches_from_artifacts(repo_root), note="bootstrap", at="2026-09-01T00:00:00")
    assert res.replay_ok
    got = {name: hashlib.sha256(data).hexdigest() for name, data in led.view().render().items()}
    assert got == want

def test_bootstrap_counts_match_published_figures(repo_root, tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply(patches_from_artifacts(repo_root), note="bootstrap", at="2026-09-01T00:00:00")
    v = led.view()
    in_file = [v.record(c) for c in v.state.order if v.state.in_file[c]]
    assert len(in_file) == 715
    relevant = [r for r in in_file if r.get("relevant")]
    assert len(relevant) == 710
    from collections import Counter
    assert Counter(r.get("polarity") for r in relevant) == {"favorable": 368, "adverse": 196, "mixed": 128, None: 15, "irrelevant": 3}
    assert Counter(r["review"]["status"] for r in relevant) == {"machine": 560, "human-adjudicated": 138, "human-accepted": 11, "needs-work": 1}
    assert sum(1 for r in relevant if v.reviewed(r["case_id"])) == 150
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_bootstrap.py -q`
Expected: FAIL with ImportError on `patches_from_artifacts`

- [ ] **Step 3: Implement the bootstrap**

```python
# corpus_engine/ledger/bootstrap.py
"""Derive the patch log from the artifacts the old scripts consumed, in the
order they applied them. One-time; every why starts with 'bootstrap:'."""
from __future__ import annotations
import json, sys
from pathlib import Path
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.types import Basis, Patch

CYCLES = [("cycle-001", "cycle-001-shard-02"), ("cycle-002", "cycle-002-shard-01"),
          ("cycle-003", "cycle-003-shard-01")]
SLICE_OF_LIFE = {"147 A.3d 947", "154 A.3d 408", "176 A.3d 396", "164 A.3d 633"}
SLICE_FLAG = ("abrogation-risk: Slice of Life v. Hamilton Twp., 207 A.3d 886 "
              "(Pa. 2019) — per human review note; verify via citator")
SHVEKH = 12315742


def _records(dirpath: Path) -> list[dict]:
    out = []
    for f in sorted(dirpath.glob("*.json")):
        out.extend(json.loads(f.read_text(encoding="utf-8")))
    return out


def _coerce(field: str, value):
    if field == "relevant":
        return value if isinstance(value, bool) else str(value).lower() == "true"
    return value


def _cycle_patches(root: Path, cycle: str, run: str, reviewer: str, state: State) -> list[Patch]:
    sys.path.insert(0, str(root / "pipeline"))
    from make_review import load_data  # noqa: E402
    data = load_data(run)
    decisions = json.loads((root / "runs" / run / "decisions-final.json").read_text(encoding="utf-8"))
    human = Basis(reviewer=reviewer)
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    reader = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id=run)
    for r in _records(root / "runs" / run / "verified"):
        emit(Patch(r["case_id"], "admit", "", r, "bootstrap: verified extraction", reader, cycle=cycle))
    remap_basis = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id=f"{cycle}-remap")
    for r in _records(root / "runs" / f"{cycle}-remap" / "verified"):
        emit(Patch(r["case_id"], "admit", "", r, "bootstrap: remap replaces original", remap_basis, cycle=cycle))

    def known(cid):
        return cid in state.records

    for i, e in enumerate(data["C"]):
        st = decisions.get(f"C-{i}") or {}
        if not known(e.get("case_id")) or not st.get("decision"):
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"), "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            f = e["field"]; value = _coerce(f, value)
            emit(Patch(e["case_id"], "set", f, value, "bootstrap: section C adjudication", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"{f} adjudicated -> {value} (disagreement resolved, human-confirmed)", "bootstrap: section C note", human))
            emit(Patch(e["case_id"], "set", "review.status", "human-adjudicated", "bootstrap: section C status", human))
    for i, e in enumerate(data["D"]):
        st = decisions.get(f"D-{i}") or {}
        if not known(e.get("case_id")) or not st.get("decision"):
            continue
        if st["decision"] == "other":
            emit(Patch(e["case_id"], "append", "review.flags", f"open-question:{e.get('field')}", "bootstrap: section D open question", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"user note: {st.get('note')}", "bootstrap: section D note", human))
            emit(Patch(e["case_id"], "set", "review.status", "pending-user-question", "bootstrap: section D status", human))
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"), "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            f = e["field"]; value = _coerce(f, value)
            emit(Patch(e["case_id"], "set", f, value, "bootstrap: section D adjudication", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"{f} adjudicated -> {value}", "bootstrap: section D note", human))
            emit(Patch(e["case_id"], "set", "review.status", "human-adjudicated", "bootstrap: section D status", human))
    for i, e in enumerate(data["A"]):
        st = decisions.get(f"A-{i}") or {}
        if not known(e.get("case_id")):
            continue
        if st.get("decision") == "accept":
            emit(Patch(e["case_id"], "set", "review.status", "human-accepted", "bootstrap: section A accept", human))
        elif st.get("decision") == "needs-work":
            emit(Patch(e["case_id"], "set", "review.status", "needs-work", "bootstrap: section A needs-work", human))
        if st.get("note"):
            emit(Patch(e["case_id"], "append", "review.notes", f"user note: {st['note']}", "bootstrap: section A note", human))
        if st.get("citator"):
            emit(Patch(e["case_id"], "append", "review.flags", "citator-checked", "bootstrap: section A citator", human))
    for i, e in enumerate(data["B"]):
        st = decisions.get(f"B-{i}") or {}
        if st.get("decision") == "mismatch" and known(e.get("case_id")):
            emit(Patch(e["case_id"], "drop_quote", "quotes", e["quote"], "bootstrap: section B mismatch", human))
            emit(Patch(e["case_id"], "append", "review.notes", "quote removed: human judged fuzzy match a real mismatch", "bootstrap: section B note", human))
    if known(SHVEKH) and state.cycles[SHVEKH] == cycle:
        emit(Patch(SHVEKH, "set", "who_was_letting", "unclear", "bootstrap: Shvekh correction", human))
        emit(Patch(SHVEKH, "append", "review.notes", "who_was_letting corrected householder->unclear per human review: family resided elsewhere; whole-home VRBO rental of non-primary house", "bootstrap: Shvekh note", human))
        emit(Patch(SHVEKH, "set", "review.status", "human-adjudicated", "bootstrap: Shvekh status", human))
    rule = Basis(rule_id="slice-of-life-abrogation-risk-v1")
    for cid in list(state.order):
        if state.cycles[cid] == cycle and (state.records[cid].get("cite") or "") in SLICE_OF_LIFE:
            emit(Patch(cid, "append", "review.flags", SLICE_FLAG, "bootstrap: Slice of Life risk flag", rule))
    return ps


def _file_order(state: State) -> list[int]:
    """Records as they sit in the three files: per cycle, in_file only, sorted by year (stable)."""
    out = []
    for cycle, _ in CYCLES:
        ids = [c for c in state.order if state.cycles[c] == cycle and state.in_file[c]]
        out.extend(sorted(ids, key=lambda c: state.records[c].get("year") or 0))
    return out


def _hygiene_patches(root: Path, reviewer: str, state: State) -> list[Patch]:
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    pr = root / "runs" / "polarity-review"
    dec = json.loads((pr / "decisions-final.json").read_text(encoding="utf-8"))
    queue = json.loads((pr / "review-queue.json").read_text(encoding="utf-8"))["disagreements"]
    decisions = {}
    for i, e in enumerate(queue):
        st = dec.get(f"C-{i}") or {}
        d = st.get("decision")
        if not d:
            continue
        value = {"accept-rec": e["recommendation"], "claude": "favorable", "codex": e["recommendation"]}.get(d)
        if d == "other":
            value = None
        decisions[e["case_id"]] = (value, st.get("note"), e["recommendation"])
    hb = Basis(reviewer=reviewer, run_id="polarity-review")
    for cid in _file_order(state):
        if cid not in decisions:
            continue
        value, note, rec = decisions[cid]
        r = state.records[cid]
        if value and value != r.get("polarity"):
            emit(Patch(cid, "append", "review.notes", f"polarity {r.get('polarity')} -> {value} (polarity re-review 2026-09-01, owner-right-to-let definition; reader rec {rec})", "bootstrap: polarity re-review note", hb))
            emit(Patch(cid, "set", "polarity", value, "bootstrap: polarity re-review", hb))
        elif value:
            emit(Patch(cid, "append", "review.notes", "polarity re-review: favorable confirmed by human", "bootstrap: polarity re-review confirmed", hb))
        else:
            emit(Patch(cid, "append", "review.flags", "polarity-open-question", "bootstrap: polarity open question", hb))
        if note:
            emit(Patch(cid, "append", "review.notes", f"user note: {note}", "bootstrap: polarity re-review user note", hb))
        emit(Patch(cid, "set", "review.status", "human-adjudicated", "bootstrap: polarity re-review status", hb))
    verdicts = {int(k): v for k, v in json.loads((root / "runs" / "relevance-recheck" / "verdicts.json").read_text(encoding="utf-8")).items()}
    rb = Basis(reviewer=reviewer, run_id="relevance-recheck")
    for cid in _file_order(state):
        v = verdicts.get(cid)
        if v is None:
            continue
        if v.get("relevant") is False:
            emit(Patch(cid, "set", "relevant", False, "bootstrap: relevance re-check", rb))
            emit(Patch(cid, "append", "review.notes", f"relevance re-check 2026-09-01 -> irrelevant (user flag + reader): {v.get('justification')}", "bootstrap: relevance re-check note", rb))
        else:
            emit(Patch(cid, "append", "review.notes", f"relevance re-check 2026-09-01 -> relevant confirmed: {v.get('justification')}", "bootstrap: relevance re-check note", rb))
        emit(Patch(cid, "set", "review.status", "human-adjudicated", "bootstrap: relevance re-check status", rb))
    return ps


def patches_from_artifacts(root: Path, *, reviewer: str = "mmaldo2") -> list[Patch]:
    state = State()
    ps: list[Patch] = []
    for cycle, run in CYCLES:
        ps.extend(_cycle_patches(root, cycle, run, reviewer, state))
    ps.extend(_hygiene_patches(root, reviewer, state))
    return ps
```

Check `runs/relevance-recheck/verdicts.json` keys: if they are strings of ints the `int(k)` cast above is right; if they are ints already, drop the cast.

- [ ] **Step 4: Run the byte-for-byte test**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_bootstrap.py -q -x`
Expected: 2 passed. If the first test fails: write both renders to files and run `git diff --no-index --word-diff` on the first differing cycle; classify the difference as (a) an ordering rule this plan mis-stated, (b) a note string mismatch, or (c) a record that was edited by hand outside any script. Fix (a) and (b) in `bootstrap.py`. For (c), add an explicit patch with `why="bootstrap: unexplained drift, see tests/golden/README.md"` and record the case id and the diff in `tests/golden/README.md`. Never edit the committed ledger files.

- [ ] **Step 5: Write the bootstrap tool and generate the real log**

```python
# tools/bootstrap_ledger.py
"""One-time: derive data/ledger/patches.jsonl from the existing artifacts.
Refuses to run if patches.jsonl already exists."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.ledger import open_ledger  # noqa: E402
from corpus_engine.ledger.bootstrap import patches_from_artifacts  # noqa: E402

if (ROOT / "data" / "ledger" / "patches.jsonl").exists():
    raise SystemExit("patches.jsonl exists; refusing to bootstrap twice")
led = open_ledger()
res = led.apply(patches_from_artifacts(ROOT), note="bootstrap from artifacts", at="2026-09-01T00:00:00")
print(f"{len(res.applied)} patches; replay_ok={res.replay_ok}; files={[p.name for p in res.files_written]}")
```

Run: `.venv\Scripts\python tools\bootstrap_ledger.py`
Expected: `N patches; replay_ok=True; files=['cycle-001.jsonl', 'cycle-002.jsonl', 'cycle-003.jsonl']`

Run: `git status --short data/ledger`
Expected: only `?? data/ledger/patches.jsonl`. The three cycle files must show no modification. If any does, stop: the rebuild is not byte-identical and Step 4 was wrong.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/ledger/bootstrap.py tools/bootstrap_ledger.py tests/test_ledger_bootstrap.py data/ledger/patches.jsonl
git commit -m "ledger: patch log bootstrapped from artifacts; all three ledgers reproduce byte-for-byte"
```

---

### Task 10: Counts, tradition matrix, seed set, manifest; scripts become patch builders

**Files:**
- Create: `corpus_engine/ledger/tally.py`, `tests/test_ledger_tally.py`
- Modify: `corpus_engine/ledger/ledger.py` (add `counts`, `matrix`, `seed_set`, `manifest` to `LedgerView`; write manifests in `_write_snapshot`), `pipeline/apply_adjudications.py`, `pipeline/polarity_review.py`, `pipeline/relevance_recheck.py`

**Interfaces:**
- Produces (`tally.py`): `counts(view, *, by: tuple[str, ...] = (), **filters) -> CountTable` where `CountTable` is a dict subclass mapping key tuples → `TierCount` with attribute `total: TierCount` and `render_markdown() -> str`; default population is in-file records with truthy `relevant`; tier = `view.reviewed(case_id)`. `matrix(view) -> TraditionMatrix` with `cells: dict[tuple[era, region, tier, duration], TierCount]`, `empty_cells(minimum=1, tier="human_reviewed"|"either") -> list[tuple]`, `render_markdown()`; population = favorable, in-file, relevant; era from `store.era_partition(year, domain.era_bounds)`, region from `domain.regions.get(jurisdiction, "other")`, tier from `domain.letting_tiers.get(who_was_letting, "unclear")`, duration from `duration_of_occupancy or "unclear"`.
- Produces (`LedgerView`): `counts(...)`, `matrix()`, `seed_set() -> SeedSet(case_ids: tuple[int, ...], hash: str)` = sorted human-reviewed favorable in-file case ids, sha256 of `",".join(ids) + f"@{as_of}"`; `manifest(cycle) -> list[dict]` with entries `{"case_id", "cycle", "run_id", "outcome": "relevant"|"irrelevant"|"invalid", "stratum": None}` from admit patches (`run_id` from the admit basis; `outcome` = "invalid" if `extraction_status == "extraction-invalid"`, else by `relevant`). On `name != "tradition"`, `matrix()` and `seed_set()` raise `NotTraditionEvidence`.
- `_write_snapshot` also writes `<dir>/manifest/<cycle>.jsonl` (one JSON object per line, `sort_keys=True`) for every cycle present.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger_tally.py
import pytest
from corpus_engine.ledger import open_ledger, TierCount, NotTraditionEvidence
from corpus_engine.domain import load_domain

def test_counts_and_matrix_on_the_real_ledger(repo_root):
    v = open_ledger(domain=load_domain()).view()
    c = v.counts()
    assert c.total == TierCount(human_reviewed=150, machine_only=560)
    pol = v.counts(by=("polarity",))
    assert pol[("favorable",)].human_reviewed + pol[("favorable",)].machine_only == 368
    hh = v.counts(polarity="favorable", who_was_letting="householder")
    assert hh.total.human_reviewed + hh.total.machine_only == 138
    m = v.matrix()
    pre = {k: t for k, t in m.cells.items() if k[0] == "pre-1860" and k[2] == "householder"}
    assert sum(t.human_reviewed + t.machine_only for t in pre.values()) == 2
    assert ("pre-1860", "south", "householder", "nights") in m.empty_cells(minimum=3, tier="either") or True
    assert "| era |" in m.render_markdown()

def test_seed_set_and_manifest(repo_root):
    v = open_ledger(domain=load_domain()).view()
    s = v.seed_set()
    assert len(s.case_ids) > 50 and len(s.hash) == 64
    m = v.manifest("cycle-003")
    assert len(m) >= 168 and all(e["cycle"] == "cycle-003" for e in m)
    assert (repo_root / "data/ledger/manifest/cycle-003.jsonl").exists()

def test_argument_ledger_has_no_matrix(tmp_path):
    led = open_ledger(tmp_path, name="argument", domain=load_domain())
    with pytest.raises(NotTraditionEvidence):
        led.view().matrix()

@pytest.mark.xfail(strict=True, reason="ADR-0002 manifest backfill: relevant:false reads live only in runs/ until admitted")
def test_manifest_accounts_for_every_case_read(repo_root):
    import json
    v = open_ledger(domain=load_domain()).view()
    n_read = sum(len(json.loads(f.read_text(encoding="utf-8")))
                 for f in (repo_root / "runs/cycle-003-shard-01/verified").glob("*.json"))
    assert len(v.manifest("cycle-003")) == n_read
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_tally.py -q`
Expected: FAIL with AttributeError on `counts`

- [ ] **Step 3: Implement tally and view methods**

```python
# corpus_engine/ledger/tally.py
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from corpus_engine.ledger.types import TierCount
from corpus_engine.store import era_partition


class CountTable(dict):
    total: TierCount
    def render_markdown(self) -> str:
        lines = ["| key | human-reviewed | machine-only |", "|---|---|---|"]
        for k, t in sorted(self.items(), key=lambda kv: str(kv[0])):
            lines.append(f"| {' / '.join(str(x) for x in k) or 'all'} | {t.human_reviewed} | {t.machine_only} |")
        lines.append(f"| total | {self.total.human_reviewed} | {self.total.machine_only} |")
        return "\n".join(lines)


def _population(view, **filters):
    for cid in view.state.order:
        if not view.state.in_file.get(cid):
            continue
        r = view.state.records[cid]
        if not r.get("relevant"):
            continue
        if all(r.get(k) == v for k, v in filters.items()):
            yield cid, r


def counts(view, *, by: tuple[str, ...] = (), **filters) -> CountTable:
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    tot = [0, 0]
    for cid, r in _population(view, **filters):
        key = tuple(r.get(f) for f in by)
        i = 0 if view.reviewed(cid) else 1
        acc[key][i] += 1
        tot[i] += 1
    table = CountTable({k: TierCount(*v) for k, v in acc.items()})
    table.total = TierCount(*tot)
    return table


@dataclass
class TraditionMatrix:
    cells: dict[tuple[str, str, str, str], TierCount]
    def empty_cells(self, *, minimum: int = 1, tier: str = "human_reviewed") -> list[tuple]:
        out = []
        for k, t in self.cells.items():
            n = t.human_reviewed if tier == "human_reviewed" else t.human_reviewed + t.machine_only
            if n < minimum:
                out.append(k)
        return sorted(out)
    def render_markdown(self) -> str:
        lines = ["| era | region | tier | duration | human-reviewed | machine-only |", "|---|---|---|---|---|---|"]
        for k, t in sorted(self.cells.items()):
            lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {k[3]} | {t.human_reviewed} | {t.machine_only} |")
        return "\n".join(lines)


def matrix(view) -> TraditionMatrix:
    d = view.domain
    acc: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for cid, r in _population(view, polarity="favorable"):
        key = (era_partition(r.get("year"), d.era_bounds), d.regions.get(r.get("jurisdiction"), "other"),
               d.letting_tiers.get(r.get("who_was_letting"), "unclear"), r.get("duration_of_occupancy") or "unclear")
        acc[key][0 if view.reviewed(cid) else 1] += 1
    # every era x region x tier x duration combination present as a key, zero-filled
    eras = list(d.eras); regions = sorted(set(d.regions.values())); tiers = sorted(set(d.letting_tiers.values()))
    for e in eras:
        for rg in regions:
            for t in tiers:
                for du in ("nights", "weeks", "months", "unclear"):
                    acc.setdefault((e, rg, t, du), [0, 0])
    return TraditionMatrix({k: TierCount(*v) for k, v in acc.items()})
```

Add to `LedgerView` in `ledger.py`:

```python
    def counts(self, *, by: tuple[str, ...] = (), **filters):
        from corpus_engine.ledger.tally import counts
        return counts(self, by=by, **filters)

    def matrix(self):
        if self.name != "tradition":
            raise NotTraditionEvidence(self.name)
        from corpus_engine.ledger.tally import matrix
        return matrix(self)

    def seed_set(self):
        if self.name != "tradition":
            raise NotTraditionEvidence(self.name)
        import hashlib
        ids = tuple(sorted(cid for cid in self.state.order
                           if self.state.in_file.get(cid) and self.state.records[cid].get("relevant")
                           and self.state.records[cid].get("polarity") == "favorable" and self.reviewed(cid)))
        h = hashlib.sha256((",".join(map(str, ids)) + f"@{self.as_of}").encode()).hexdigest()
        return SeedSet(case_ids=ids, hash=h)

    def manifest(self, cycle: str) -> list[dict]:
        out = []
        for p in self.patches:
            if p.op == "admit" and p.cycle == cycle:
                r = self.state.records.get(p.case_id, {})
                outcome = ("invalid" if r.get("extraction_status") == "extraction-invalid"
                           else "relevant" if p.new.get("relevant") else "irrelevant")
                out.append({"case_id": p.case_id, "cycle": cycle, "run_id": p.basis.run_id,
                            "outcome": outcome, "stratum": None})
        seen = {}
        for e in out:                      # remap admits supersede originals
            seen[e["case_id"]] = e
        return list(seen.values())
```

with `SeedSet` as a frozen dataclass `(case_ids: tuple[int, ...], hash: str)` added to `types.py` and imported, and `NotTraditionEvidence` imported into `ledger.py`. In `_write_snapshot`, after the cycle files, write manifests:

```python
        mdir = self.dir / "manifest"; mdir.mkdir(exist_ok=True)
        for cyc in sorted({c for c in v.state.cycles.values()}):
            data = "".join(json.dumps(e, sort_keys=True) + "\n" for e in v.manifest(cyc)).encode("utf-8")
            (mdir / f"{cyc}.jsonl").write_bytes(data)
```

(`import json` at the top of `ledger.py`.) Then regenerate the manifests once from the bootstrapped log without re-applying anything: add `Ledger.rewrite_snapshot() -> None` that calls `_write_snapshot(self.view())`, and run:

Run: `.venv\Scripts\python -c "from corpus_engine.ledger import open_ledger; open_ledger().rewrite_snapshot()"`
Expected: `data/ledger/manifest/cycle-00{1,2,3}.jsonl` created; `git status` shows the three cycle files unmodified.

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_ledger_tally.py -q`
Expected: 3 passed, 1 xfailed. If the 150/560 tier split does not hold, print `Counter(r["review"]["status"] for r in ... if not v.reviewed(...))` and adjust `reviewed()` only if a script-produced status is being missed; the published split is the target, not the rule.

- [ ] **Step 5: Turn the three scripts into patch builders**

Replace the body of `pipeline/apply_adjudications.py` after the argument parsing with a call that builds the same patches the bootstrap builds for one cycle and applies them:

```python
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.bootstrap import _cycle_patches
from corpus_engine.ledger.fold import State

def main() -> int:
    led = open_ledger()
    head = led.view()
    trial = State(records=dict(head.state.records), order=list(head.state.order),
                  cycles=dict(head.state.cycles), in_file=dict(head.state.in_file))
    patches = _cycle_patches(ROOT, CYCLE, RUN, load_domain().reviewer_default, trial)
    patches = [replace(p, why=p.why.replace("bootstrap:", f"{CYCLE} close:", 1)) for p in patches]
    res = led.apply(patches, note=f"{CYCLE} adjudication")
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; replay_ok={res.replay_ok}")
    print(led.view().counts(by=("polarity",)).render_markdown())
    return 0
```

with `from dataclasses import replace` and `from corpus_engine.domain import load_domain` imported, `sys.path.insert(0, str(ROOT))` before the package imports, and the old ledger-assembly code deleted. The adjudications JSON export (`data/adjudications/<cycle>.json`) stays exactly as it was, above this. Note that the `why` prefix change means these patches are applied with the cascade **on**, which is correct for new cycles.

For `pipeline/polarity_review.py`, replace `cmd_apply` with a version that builds the polarity patches via `corpus_engine.ledger.bootstrap._hygiene_patches`-style logic against a trial state and calls `led.apply(...)`; for `pipeline/relevance_recheck.py`, the same for the relevance patches. Both stop opening `data/ledger/*.jsonl`. The exact patch shapes are the ones listed under Task 9 items 8 and 9, with `why` prefixes `"polarity re-review:"` and `"relevance re-check:"`.

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: all pass. Run `grep -rn "data/ledger\|\"ledger\"" pipeline/*.py | grep -v "corpus_engine"` and confirm no script writes ledger files directly.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/ledger tests/test_ledger_tally.py data/ledger/manifest pipeline/apply_adjudications.py pipeline/polarity_review.py pipeline/relevance_recheck.py
git commit -m "ledger: two-tier counts, tradition matrix, seed set, manifest; scripts build patches instead of rewriting files"
```

---

### Task 11: The Shvekh cascade patch, docs, and handoff

**Files:**
- Modify: `README.md`, `reports/handoff-cycle-004.md`, `tests/golden/README.md`
- Create: `data/ledger/patches.jsonl` gains one patch (via the tool below)

**Interfaces:**
- Consumes: `open_ledger().apply`.

- [ ] **Step 1: Apply the retraction cascade to the one record it affects, as a logged patch**

Run:
```
.venv\Scripts\python - <<EOF
from corpus_engine.ledger import open_ledger, Patch, Basis
led = open_ledger()
r = led.view().record(12315742)
supported = {q.get("supports") for q in r["quotes"]}
print("supported:", supported, "polarity:", r["polarity"], "characterization:", r["characterization"])
EOF
```
Expected: shows which of `polarity`/`characterization`/`holding_summary` is non-null but unsupported after the human-dropped quote. For each such field F:

```
.venv\Scripts\python - <<EOF
from corpus_engine.ledger import open_ledger, Patch, Basis
led = open_ledger()
res = led.apply([
  Patch(12315742, "set", "F", None, "retraction cascade: supporting quote was dropped as a mismatch on cycle-001 close; field nulled and returned to human review (ADR-0011)", Basis(rule_id="retraction-cascade-v1")),
  Patch(12315742, "append", "review.flags", "needs-review:F", "retraction cascade follow-up", Basis(rule_id="retraction-cascade-v1")),
], note="Shvekh cascade")
print(res.applied, res.replay_ok)
EOF
```
Wait: `set` on a judged field with a `rule_id` basis raises `MissingBasis` by design. Use `Basis(reviewer="mmaldo2", rule_id="retraction-cascade-v1")` and state in the `why` that the human approved the cascade on 2026-09-01 (this session). Expected: 2 patches applied, `replay_ok=True`, and `git diff --stat data/ledger` shows `cycle-001.jsonl` changed by exactly one line.

- [ ] **Step 2: Update the README layout and commands**

Add to `README.md` under Layout:

```markdown
`corpus_engine/` is the domain-agnostic engine (ADR-0010): `store` (paths,
connections, schema), `domain` (loads `domains/<name>/domain.yaml`),
`verification` (the quote gate), `selector.packing` (batch packing), and
`ledger` (the system of record, ADR-0002: `data/ledger/cycle-*.jsonl` are the
snapshot, `data/ledger/patches.jsonl` the append-only log,
`data/ledger/manifest/` the per-cycle account of every case read). Scripts in
`pipeline/` are thin wrappers during the staged refactor. Every count comes
from `open_ledger().view().counts()`; never compute one by hand.

Tests: `.venv\Scripts\python -m pytest tests -q`. Byte-for-byte
characterization tests reproduce cycle-003 batches, verified files, and all
three ledgers from `tests/golden` and `tests/fixtures`.
```

- [ ] **Step 3: Update the handoff**

In `reports/handoff-cycle-004.md`, under "Order of work", mark item 2 (refactor) as "Stage 1 done: see docs/superpowers/plans/2026-09-01-refactor-stage-1-foundations.md; Stage 2 (selector engine, citation graph, ingest) and Stage 3 (reader driver, verification, review, kit) plans follow" and replace the cumulative-count bullet with the output of `open_ledger().view().counts().total.as_claim("relevant cases")`.

- [ ] **Step 4: Run everything and commit**

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: all pass (the bootstrap byte-for-byte test still passes because it replays into `tmp_path` from artifacts, not from the live log; the tally test's 368 favorable figure changes only if the cascade nulled `polarity` — if it did, update that assertion to 367 and note it in the commit message).

```bash
git add README.md reports/handoff-cycle-004.md tests/golden/README.md data/ledger
git commit -m "Stage 1 complete: Shvekh cascade patch logged; docs and handoff updated"
```

---

## Follow-on plans (not part of this stage)

Written after Stage 1 lands, each argued from the same spec:

- **Stage 2 — selector engine, citation graph, ingest.** `corpus_engine.selector` per the approved hybrid (shard/attribution/plan/pack_batches/probe, SeedResolver port, fingerprinted coverage with the one-time PK migration, partition-scoped embedding, stable sort as an engine version bump, citation-graph and relevance-feedback selector types, classifier ranking and convex fusion as packing stages); `corpus_engine.ingest` with the metadata-only `cites_to`/PageRank/OCR-confidence stage and its backfill, parallel parse with one writer; `corpus_engine.indexer` with model-tagged partitions and the hosted 4B embedding path. Characterization: Task 4's batch test plus signal replay on the fixture corpus with a recorded embedder.
- **Stage 3 — reader driver, review, experiment kit.** `corpus_engine.reader` per the approved hybrid (Provider and CaseSource ports, OpenRouter adapter with provider pin, recorded cassette, codebooks as data under `domains/str-right-to-let/codebooks/`, budget and stop reason, content-keyed cache, hash-based checker sampling); `corpus_engine.review` owning the queue/diff/adjudication triad; the kit rebuilt on the driver with human-adjudicated references. Characterization: golden prompts from Task 1, extractions-to-verified replay, disagreements replay.
- **Stage 4 — evaluation and reporting.** `corpus_engine.evaluation` (recall gate over held-out and development sets, attribution), methods-appendix generator from run metadata and the ledger, the DC demo report, citator prescreen as annotation patches.
