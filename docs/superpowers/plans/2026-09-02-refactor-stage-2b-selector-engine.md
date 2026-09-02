# Refactor Stage 2B — Selector Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `pipeline/shard.py` with `corpus_engine.selector`: selectors as data with a per-kind runner registry, coverage rows keyed by a retriever fingerprint (so a partition re-embedded under a new model or a changed seed set is uncovered automatically and a mixed-model partition is refused), two new selector kinds (citation graph, relevance feedback), a stable candidate sort, and the two common calls `shard` and `attribution`, with the cycle-003 batches, lexical signals, and recall report reproduced exactly.

**Architecture:** Per the approved hybrid in `docs/design/2026-09-01-module-interfaces/README.md` (selector engine section). `model.py` holds the frozen value types and the selector parser; `coverage.py` owns the fingerprinted coverage table and its one-time migration; `ports.py` holds the two real seams (query embedder, seed resolver) and the fingerprint rule; `runners.py` holds one function per selector kind behind an internal registry and a per-run `EngineContext` that replaces the module-global embedding cache; `engine.py` composes them into `plan`, `shard`, `attribution`, `probe`; `packing.py` (Stage 1) keeps batch emission. Ranking never touches the signals table. The legacy `shard.py` and `eval_recall.py` become wrappers.

**Tech Stack:** Python 3.11, SQLite (FTS5), numpy, PyYAML, sentence-transformers (query-time only). No new dependencies.

**Spec:** `docs/design/2026-09-01-module-interfaces/README.md` (selector engine hybrid) and `design-selector-3-common.md` beside it; `docs/adr/0005`, `0006`, `0009`, `0011`; `CONTEXT.md`. Requires Stage 2A Tasks 1-5 merged (`cites_to`, `chunks.embed_run`, `partition_runs`, `LocalEmbedder.encode_query`). Stage 2A Task 7 (the cycle-004 build) may run before or after this plan; the engine must behave correctly either way.

## Global Constraints

- Python 3.11; `.venv\Scripts\python` from the repo root `C:\Users\marcu\Desktop\Str-corpus`. Tests: `.venv\Scripts\python -m pytest tests -q`. Canonical bytes are LF.
- **Determinism (ADR-0009):** given the same selectors, coverage state, seed sets, index, and recipe, `shard` emits byte-identical batches. Selectors iterate in file order; partitions in domain era order then domain jurisdiction order; embedding candidates sort by `(-cosine, chunk_id)` with `np.lexsort`, never plain `argsort`.
- **Signals are never truncated by ranking.** `attribution` reads the `signals` table only.
- **Coverage key** = `(selector_id, selector_version, partition_key, fingerprint)` where `partition_key = f"{era}|{jurisdiction}"`. Fingerprint rules (exact strings): lexical kinds `fts_phrase`/`fts_near` → `"fts:v1"`; `regex` → `"regex:v1"`; `embedding` → `f"embed:{run}|engine:{ENGINE_VERSION}"` where `run` is the single `embed_run` over the partitions in scope; `relevance_feedback` → the embedding fingerprint plus `f"|seed:{hash}"`; `citation_graph` → `f"graph:v1|seed:{hash}"`. `ENGINE_VERSION = "v2"` (the stable-sort fix). Seed hash = first 16 hex of sha256 over `",".join(sorted ids)`.
- **Skips, never silent:** a partition with zero non-duplicate cases → `Skip("partition_empty")` and no coverage row (this replaces the Stage 1 `missing_jurisdictions` guard); an embedding-kind selector whose in-scope partitions carry more than one `embed_run` → `Skip("mixed_embedding_model")`; any in-scope partition with no chunks → `Skip("index_incomplete")`; a seeded selector whose seed set is smaller than `min_seeds` (5) → `Skip("seed_unavailable")`.
- A signal row and its coverage row are written in the same transaction; a skipped unit writes neither.
- The `signals` table schema is unchanged (batch packing and the golden signals fixture depend on it).
- Already-read exclusion = case ids in `runs/*/extractions*/*.json` **union** every case id in `data/ledger/manifest/*.jsonl`; recorded in the shard report by count and sha256.
- Selectors YAML: never edit a selector in place past a shard run, bump `version`; never delete, `status: retired`.
- `selectors/selectors.yaml` currently has 40 entries (36 active); ids repeat across version bumps, so the unique key is `(id, version)`.
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## File Structure

```
corpus_engine/selector/
  __init__.py          public API: shard, attribution, plan, probe, ENGINE_VERSION
  model.py             Partition, SelectorKey, Selector, KIND_SPECS, parse_selector, load_selectors, SeedSet, Signal, SignalRef, Skip, PlanUnit, ShardPlan, ShardReport, SelectorSpecError
  coverage.py          COVERAGE_V2 DDL, migrate_coverage(), partition_key(), covered(), mark_covered(), coverage_rows()
  ports.py             QueryEmbedder (LocalQueryEmbedder, RecordedEmbedder), SeedResolver (LedgerSeedResolver, FrozenSeedResolver), fingerprint()
  runners.py           EngineContext, run_fts, run_regex, run_embedding, run_citation_graph, run_relevance_feedback, RUNNERS
  engine.py            plan(), shard(), attribution(), probe(), already_read_ids(), report manifest
  packing.py           (Stage 1) + build_batches() returning data
domains/str-right-to-let/domain.yaml   (+) sharding: {batch_size: 18, min_seeds: 5}
selectors/selectors.yaml               (+) citation-graph-38, relevance-feedback-39 (v4)
selectors/CHANGELOG.md                 (+) v4 entry, engine v2 note
pipeline/shard.py, pipeline/eval_recall.py     thin wrappers
tests/test_selector_model.py, test_selector_coverage.py, test_selector_ports.py,
      test_selector_runners.py, test_selector_engine.py, test_recall_char.py
tests/golden/recall-cycle-003.json      captured in Task 1
tests/fixtures/query-vectors-v3.npz     captured in Task 1 (recorded query vectors for the 6 embedding selectors, 0.6B model)
```

---

### Task 1: Capture the recall golden and recorded query vectors

**Files:**
- Create: `tools/capture_selector_goldens.py`, `tests/golden/recall-cycle-003.json`, `tests/fixtures/query-vectors-v3.npz`
- Modify: `tests/golden/README.md`

**Interfaces:**
- Consumes: `pipeline/eval_recall.py:evaluate(None)` (old code), `pipeline/shard.py:load_selectors` (old), the live DB's `embed_meta`, sentence-transformers.
- Produces: `tests/golden/recall-cycle-003.json` = the exact `evaluate(None)` report with `hits`/`misses` reduced to `{case_id, selectors (sorted)}`; `tests/fixtures/query-vectors-v3.npz` with one array per active embedding selector, key `f"{id}@v{version}"`, the 512-d float32 normalized query vector under the current index model (`prompt_name="query"`), plus an array `__meta__` holding the JSON string of `embed_meta`.

- [ ] **Step 1: Write the capture tool**

```python
# tools/capture_selector_goldens.py
"""One-time: freeze the pre-refactor recall report and the embedding selectors' query vectors."""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline")); sys.path.insert(0, str(ROOT))
import eval_recall, shard  # noqa: E402  (old code, on purpose)
from corpus_engine import store  # noqa: E402

if __name__ == "__main__":
    rep = eval_recall.evaluate(None)
    slim = {"tiers": rep["tiers"],
            "hits": sorted([{"case_id": h["case_id"], "selectors": sorted(h["selectors"])} for h in rep["hits"]], key=lambda h: h["case_id"]),
            "misses": sorted(g["case_id"] for g in rep["misses"])}
    (ROOT / "tests/golden/recall-cycle-003.json").write_bytes(json.dumps(slim, indent=1, sort_keys=True).encode("utf-8"))
    conn = store.connect(wal=False)
    meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(meta["model"], revision=meta.get("revision") or None, device="cuda" if shard._cuda() else "cpu")
    dim = int(meta.get("dim", "512")); arrays = {"__meta__": np.array(json.dumps(meta))}
    for s in shard.load_selectors():
        if s["type"] == "embedding":
            q = model.encode([s["query_text"]], prompt_name="query", convert_to_numpy=True)[0][:dim].astype(np.float32)
            arrays[f"{s['id']}@v{s['version']}"] = q / (np.linalg.norm(q) + 1e-12)
    np.savez(ROOT / "tests/fixtures/query-vectors-v3.npz", **arrays)
    print("recall tiers:", slim["tiers"]); print("vectors:", sorted(k for k in arrays if k != "__meta__"))
```

- [ ] **Step 2: Run it once**

Run: `.venv\Scripts\python tools\capture_selector_goldens.py`
Expected: `recall tiers:` showing brief-letting 6/9, treatise 22/29, brief-all 17/63; `vectors:` listing six keys (the active embedding selectors: `embed-householder-letting-21@v2`, `embed-zoning-paying-occupants-22@v2`, `adverse-embed-regulation-29@v1`, and the three others in the file). If the live signals table already contains cycle-004 rows (Stage 2A Task 7 ran a shard? It must not have), stop and report.

Add to `tests/golden/README.md`: a "Selector goldens" section naming the two files, the commit, and that the vectors are for the 0.6B index (they are replaced when the 4B index lands, as a logged golden change).

- [ ] **Step 3: Commit**

```bash
git add tools/capture_selector_goldens.py tests/golden/recall-cycle-003.json tests/fixtures/query-vectors-v3.npz tests/golden/README.md
git commit -m "goldens: cycle-003 recall report and recorded query vectors for the embedding selectors"
```

---

### Task 2: Selector data model and parser

**Files:**
- Create: `corpus_engine/selector/model.py`, `tests/test_selector_model.py`
- Modify: `domains/str-right-to-let/domain.yaml` (add `sharding: {batch_size: 18, min_seeds: 5}`), `corpus_engine/domain.py` (`Domain.sharding: ShardingSpec(batch_size, min_seeds)`)

**Interfaces:**
- Produces (all frozen dataclasses unless noted):
  - `Partition(era: str, jurisdiction: str)` with `.key -> str` (`f"{era}|{jurisdiction}"`).
  - `SelectorKey = tuple[str, int]`.
  - `Selector(id, version, kind, concept, polarity, era_scope: tuple[str,...], jurisdiction_scope: tuple[str,...], params: Mapping[str, Any], author, rationale, status)` with `.key`, `.label -> f"{id}@v{version}"`, `.digest() -> str` (sha256 over canonical JSON of the dataclass minus rationale/author, first 16 hex).
  - `KIND_SPECS: dict[str, KindSpec]` with `KindSpec(required: tuple[str,...], optional: dict[str, Any])`: `fts_phrase`/`fts_near`: required `pattern`, optional `index="raw"`; `regex`: required `pattern`; `embedding`: required `query_text`, optional `top_k=50, min_cosine=0.5, model_rev=None`; `citation_graph`: required `seed_set`, optional `direction="both"`; `relevance_feedback`: required `seed_set`, optional `top_k=50, min_cosine=0.5`.
  - `parse_selector(raw: dict, *, eras, jurisdictions) -> Selector` (expands `"all"`/missing scopes; validates kind and required params; raises `SelectorSpecError`). The YAML field is `type`; the model calls it `kind`.
  - `load_selectors(domain) -> list[Selector]` (active only, file order; raises on duplicate `(id, version)`).
  - `SeedSet(name: str, case_ids: tuple[int,...], hash: str)` with `SeedSet.build(name, ids)` computing the hash rule from the constraints.
  - `Signal(case_id, selector_id, selector_version, matched_text, char_span: tuple[int,int], chunk_id: int|None, cosine: float|None, partition: Partition)`.
  - `SignalRef(selector_id, selector_version, run_id, cosine)`.
  - `Skip(key: SelectorKey, partitions: tuple[Partition,...], reason: str)`.
  - `PlanUnit(key, partition, fingerprint)`; `ShardPlan(run_id, units: tuple[PlanUnit,...], skips: tuple[Skip,...], selectors_digest: str)`.
  - `ShardReport(plan, signals_written: dict[tuple[SelectorKey, str], int], batches_written: int, batch_dir: Path|None, cases_batched: int, excluded_already_read: int, manifest: dict)`.
  - `SelectorSpecError(ValueError)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selector_model.py
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import (KIND_SPECS, Partition, SeedSet, Selector, SelectorSpecError,
                                          load_selectors, parse_selector)

def test_partition_key_and_seed_hash():
    assert Partition("pre-1860", "Tex.").key == "pre-1860|Tex."
    a = SeedSet.build("x", [3, 1, 2]); b = SeedSet.build("x", (1, 2, 3))
    assert a.case_ids == (1, 2, 3) and a.hash == b.hash and len(a.hash) == 16

def test_parse_expands_scopes_and_validates_params():
    dom = load_domain()
    s = parse_selector({"id": "a", "version": 1, "concept": "c", "type": "fts_phrase", "polarity": "favorable-candidate",
                        "pattern": '"x"', "era_scope": "all", "jurisdiction_scope": ["Tex."], "status": "active"},
                       eras=dom.eras, jurisdictions=dom.jurisdictions)
    assert s.kind == "fts_phrase" and s.era_scope == dom.eras and s.jurisdiction_scope == ("Tex.",)
    assert s.params["index"] == "raw" and s.label == "a@v1" and len(s.digest()) == 16
    with pytest.raises(SelectorSpecError):
        parse_selector({"id": "b", "version": 1, "concept": "c", "type": "embedding", "polarity": "p"}, eras=dom.eras, jurisdictions=dom.jurisdictions)
    with pytest.raises(SelectorSpecError):
        parse_selector({"id": "b", "version": 1, "concept": "c", "type": "nope", "polarity": "p", "pattern": "x"}, eras=dom.eras, jurisdictions=dom.jurisdictions)
    assert set(KIND_SPECS) == {"fts_phrase", "fts_near", "regex", "embedding", "citation_graph", "relevance_feedback"}

def test_load_real_selectors_file():
    dom = load_domain()
    sels = load_selectors(dom)
    assert len(sels) == 36 and len({s.key for s in sels}) == 36
    kinds = {s.kind for s in sels}
    assert {"fts_phrase", "fts_near", "embedding"} <= kinds
    assert dom.sharding.batch_size == 18 and dom.sharding.min_seeds == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv\Scripts\python -m pytest tests/test_selector_model.py -q` — Expected: FAIL with `ModuleNotFoundError: corpus_engine.selector.model`.

- [ ] **Step 3: Implement**

Add to `corpus_engine/domain.py`: `@dataclass(frozen=True) class ShardingSpec: batch_size: int = 18; min_seeds: int = 5` and `sharding: ShardingSpec` on `Domain`, loaded via `ShardingSpec(**cfg.get("sharding", {}))`; add `sharding: {batch_size: 18, min_seeds: 5}` to `domain.yaml`.

```python
# corpus_engine/selector/model.py
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Mapping
import yaml

ENGINE_VERSION = "v2"   # stable candidate sort (ADR-0011)


class SelectorSpecError(ValueError): ...


@dataclass(frozen=True, slots=True)
class Partition:
    era: str
    jurisdiction: str
    @property
    def key(self) -> str:
        return f"{self.era}|{self.jurisdiction}"


SelectorKey = tuple[str, int]


@dataclass(frozen=True)
class KindSpec:
    required: tuple[str, ...]
    optional: dict[str, Any] = field(default_factory=dict)


KIND_SPECS: dict[str, KindSpec] = {
    "fts_phrase": KindSpec(("pattern",), {"index": "raw"}),
    "fts_near": KindSpec(("pattern",), {"index": "raw"}),
    "regex": KindSpec(("pattern",)),
    "embedding": KindSpec(("query_text",), {"top_k": 50, "min_cosine": 0.5, "model_rev": None}),
    "citation_graph": KindSpec(("seed_set",), {"direction": "both"}),
    "relevance_feedback": KindSpec(("seed_set",), {"top_k": 50, "min_cosine": 0.5}),
}


@dataclass(frozen=True)
class Selector:
    id: str
    version: int
    kind: str
    concept: str
    polarity: str
    era_scope: tuple[str, ...]
    jurisdiction_scope: tuple[str, ...]
    params: Mapping[str, Any]
    author: str = ""
    rationale: str = ""
    status: str = "active"

    @property
    def key(self) -> SelectorKey:
        return (self.id, self.version)

    @property
    def label(self) -> str:
        return f"{self.id}@v{self.version}"

    def digest(self) -> str:
        d = asdict(self); d.pop("rationale"); d.pop("author")
        d["params"] = dict(sorted(dict(self.params).items()))
        return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


def _scope(value, universe: tuple[str, ...]) -> tuple[str, ...]:
    if value in (None, "all"):
        return tuple(universe)
    return tuple(value)


def parse_selector(raw: dict, *, eras, jurisdictions) -> Selector:
    for f in ("id", "version", "concept", "type", "polarity"):
        if f not in raw:
            raise SelectorSpecError(f"selector missing {f}: {raw.get('id')}")
    kind = raw["type"]
    if kind not in KIND_SPECS:
        raise SelectorSpecError(f"{raw['id']}: unknown selector type {kind}")
    spec = KIND_SPECS[kind]
    params: dict[str, Any] = {}
    for p in spec.required:
        if p not in raw:
            raise SelectorSpecError(f"{raw['id']}: {kind} requires {p}")
        params[p] = raw[p]
    for p, default in spec.optional.items():
        params[p] = raw.get(p, default)
    return Selector(id=raw["id"], version=int(raw["version"]), kind=kind, concept=raw["concept"],
                    polarity=raw["polarity"], era_scope=_scope(raw.get("era_scope"), tuple(eras)),
                    jurisdiction_scope=_scope(raw.get("jurisdiction_scope"), tuple(jurisdictions)),
                    params=params, author=raw.get("author", ""), rationale=raw.get("rationale", ""),
                    status=raw.get("status", "active"))


def load_selectors(domain) -> list[Selector]:
    raw = yaml.safe_load(Path(domain.selectors_path).read_text(encoding="utf-8"))
    out, seen = [], set()
    for r in raw:
        if r.get("status") != "active":
            continue
        s = parse_selector(r, eras=domain.eras, jurisdictions=domain.jurisdictions)
        if s.key in seen:
            raise SelectorSpecError(f"duplicate selector {s.label}")
        seen.add(s.key); out.append(s)
    return out


@dataclass(frozen=True)
class SeedSet:
    name: str
    case_ids: tuple[int, ...]
    hash: str

    @staticmethod
    def build(name: str, ids) -> "SeedSet":
        cids = tuple(sorted({int(i) for i in ids}))
        h = hashlib.sha256(",".join(map(str, cids)).encode()).hexdigest()[:16]
        return SeedSet(name, cids, h)


@dataclass(frozen=True)
class Signal:
    case_id: int; selector_id: str; selector_version: int
    matched_text: str; char_span: tuple[int, int]
    chunk_id: int | None; cosine: float | None
    partition: Partition


@dataclass(frozen=True)
class SignalRef:
    selector_id: str; selector_version: int; run_id: str; cosine: float | None


@dataclass(frozen=True)
class Skip:
    key: SelectorKey; partitions: tuple[Partition, ...]; reason: str


@dataclass(frozen=True)
class PlanUnit:
    key: SelectorKey; partition: Partition; fingerprint: str


@dataclass(frozen=True)
class ShardPlan:
    run_id: str; units: tuple[PlanUnit, ...]; skips: tuple[Skip, ...]; selectors_digest: str


@dataclass
class ShardReport:
    plan: ShardPlan
    signals_written: dict
    batches_written: int
    batch_dir: Path | None
    cases_batched: int
    excluded_already_read: int
    manifest: dict
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_selector_model.py tests/test_domain.py -q` — Expected: pass.

```bash
git add corpus_engine/selector/model.py corpus_engine/domain.py domains/str-right-to-let/domain.yaml tests/test_selector_model.py
git commit -m "selector: data model, kind specs, parser, seed sets, plan/report types"
```

---

### Task 3: Fingerprinted coverage table with a one-time migration

**Files:**
- Create: `corpus_engine/selector/coverage.py`, `tests/test_selector_coverage.py`
- Modify: `corpus_engine/store.py` (add `coverage_v2` DDL to `SCHEMA`)

**Interfaces:**
- Consumes: `store.SCHEMA`, `corpus_engine.indexer.embed.partition_runs` (Stage 2A), `Partition`, `Selector`, `KIND_SPECS`.
- Produces: `coverage_v2(selector_id TEXT, selector_version INTEGER, partition_key TEXT, fingerprint TEXT, run_id TEXT, ts TEXT, n_signals INTEGER, PRIMARY KEY (selector_id, selector_version, partition_key, fingerprint))`; `migrate_coverage(conn, selectors_by_key: dict[SelectorKey, Selector]) -> int` (copies every legacy `coverage` row into `coverage_v2` with the fingerprint derived by kind: lexical `fts:v1`, regex `regex:v1`, embedding `embed:<the partition's single legacy run>|engine:v1` (note `v1`, so the engine-v2 fingerprint never matches and embedding units re-run — intended); rows already present are left; returns rows copied; renames nothing, the legacy table stays for the goldens); `covered(conn, key, partition_key, fingerprint) -> bool`; `mark_covered(conn, key, partition_key, fingerprint, run_id, ts, n_signals)`; `coverage_rows(conn) -> list[tuple]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selector_coverage.py
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
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.selector.coverage`.

- [ ] **Step 3: Implement**

Add to `store.SCHEMA`:
```
CREATE TABLE IF NOT EXISTS coverage_v2 (
    selector_id TEXT, selector_version INTEGER, partition_key TEXT, fingerprint TEXT,
    run_id TEXT, ts TEXT, n_signals INTEGER,
    PRIMARY KEY (selector_id, selector_version, partition_key, fingerprint)
);
```

```python
# corpus_engine/selector/coverage.py
from __future__ import annotations
import sqlite3
from corpus_engine.selector.model import Partition, Selector, SelectorKey

LEXICAL_FP = {"fts_phrase": "fts:v1", "fts_near": "fts:v1", "regex": "regex:v1"}


def partition_key(era: str, jurisdiction: str) -> str:
    return Partition(era, jurisdiction).key


def _legacy_embed_run(conn, era: str, jur: str) -> str:
    runs = [r[0] for r in conn.execute("""SELECT DISTINCT ch.embed_run FROM chunks ch JOIN cases c ON c.case_id = ch.case_id
                                          WHERE c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL""", (era, jur))]
    return runs[0] if len(runs) == 1 else "unknown"


def migrate_coverage(conn: sqlite3.Connection, selectors_by_key: dict[SelectorKey, Selector]) -> int:
    if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='coverage'").fetchone():
        return 0
    n = 0
    for sid, ver, era, jur, run_id, ts, n_sig in conn.execute(
            "SELECT selector_id, selector_version, era_partition, jurisdiction, run_id, ts, n_signals FROM coverage"):
        sel = selectors_by_key.get((sid, ver))
        kind = sel.kind if sel else "fts_phrase"
        fp = LEXICAL_FP.get(kind) or f"embed:{_legacy_embed_run(conn, era, jur)}|engine:v1"
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
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_selector_coverage.py tests/test_store_migrate.py -q` — Expected: pass.

```bash
git add corpus_engine/selector/coverage.py corpus_engine/store.py tests/test_selector_coverage.py
git commit -m "selector: fingerprinted coverage_v2 with legacy migration"
```

---

### Task 4: Ports and the fingerprint rule

**Files:**
- Create: `corpus_engine/selector/ports.py`, `tests/test_selector_ports.py`

**Interfaces:**
- Consumes: `corpus_engine.indexer.embedders.LocalEmbedder` (Stage 2A; `encode_query`), `corpus_engine.indexer.embed.partition_runs`, `corpus_engine.ledger.open_ledger`, `Domain.gold_path`, `Domain.sharding.min_seeds`, `Selector`, `Partition`, `SeedSet`, `Skip`, `ENGINE_VERSION`.
- Produces:
  - `class QueryEmbedder(Protocol): dim: int; def encode_query(self, text: str) -> np.ndarray` (float32, normalized, length `dim`).
  - `LocalQueryEmbedder(conn)`: reads `embed_meta` (`model`, `revision`, `dim`) and wraps `LocalEmbedder(...).encode_query`, normalizing.
  - `RecordedEmbedder(npz_path)`: `encode_query(text)` looks up by the selector label the engine passes via `encode_query(text, label=...)` — so the protocol is `encode_query(text: str, *, label: str | None = None)`; raises `KeyError` naming the label when absent.
  - `class SeedResolver(Protocol): def resolve(self, ref: str) -> SeedSet`.
  - `LedgerSeedResolver(domain)`: `"ledger-favorable-reviewed"` → `open_ledger(domain=domain).view().seed_set().case_ids`; `"treatise-anchors"` → gold entries with `tier == "treatise"` and a `case_id`; `"both"` → union; unknown ref → `SelectorSpecError`.
  - `FrozenSeedResolver(mapping: dict[str, list[int]])`.
  - `fingerprint(conn, selector, partitions: list[Partition], *, seeds: SeedResolver, min_seeds: int) -> str | Skip` implementing the Global Constraints rules; `Skip.key = selector.key`, `Skip.partitions = tuple(partitions)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selector_ports.py
import numpy as np, pytest, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, Selector, Skip
from corpus_engine.selector.ports import FrozenSeedResolver, RecordedEmbedder, fingerprint

def _sel(kind, **params):
    return Selector("s", 1, kind, "c", "p", ("pre-1860",), ("Tex.",), params)

def test_recorded_embedder_by_label(repo_root):
    e = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    v = e.encode_query("ignored", label="embed-householder-letting-21@v2")
    assert v.shape == (512,) and abs(np.linalg.norm(v) - 1) < 1e-4
    with pytest.raises(KeyError):
        e.encode_query("x", label="nope@v9")

def test_fingerprint_rules(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    part = [Partition(*conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone())]
    seeds = FrozenSeedResolver({"few": [1, 2], "many": list(range(10))})
    assert fingerprint(conn, _sel("fts_phrase", pattern="x"), part, seeds=seeds, min_seeds=5) == "fts:v1"
    assert fingerprint(conn, _sel("regex", pattern="x"), part, seeds=seeds, min_seeds=5) == "regex:v1"
    assert fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5) == "embed:qwen3-0.6b-512-int8|engine:v2"
    fb = fingerprint(conn, _sel("relevance_feedback", seed_set="many"), part, seeds=seeds, min_seeds=5)
    assert fb.startswith("embed:qwen3-0.6b-512-int8|engine:v2|seed:") and len(fb.split("seed:")[1]) == 16
    g = fingerprint(conn, _sel("citation_graph", seed_set="many"), part, seeds=seeds, min_seeds=5)
    assert g.startswith("graph:v1|seed:")
    s = fingerprint(conn, _sel("citation_graph", seed_set="few"), part, seeds=seeds, min_seeds=5)
    assert isinstance(s, Skip) and s.reason == "seed_unavailable"
    # mixed model: retag one case's chunks
    cid = conn.execute("SELECT case_id FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL LIMIT 1", (part[0].era, part[0].jurisdiction)).fetchone()[0]
    conn.execute("UPDATE chunks SET embed_run='other' WHERE case_id=?", (cid,)); conn.commit()
    m = fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5)
    assert isinstance(m, Skip) and m.reason == "mixed_embedding_model"
    conn.execute("DELETE FROM chunks"); conn.commit()
    assert fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5).reason == "index_incomplete"
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.selector.ports`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/selector/ports.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Protocol
import numpy as np
from corpus_engine.indexer.embed import partition_runs
from corpus_engine.selector.model import ENGINE_VERSION, Partition, SeedSet, Selector, SelectorSpecError, Skip


class QueryEmbedder(Protocol):
    dim: int
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray: ...


class LocalQueryEmbedder:
    def __init__(self, conn):
        from corpus_engine.indexer.embedders import LocalEmbedder
        meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
        self.dim = int(meta.get("dim", "512"))
        self._local = LocalEmbedder(meta["model"], meta.get("revision") or "main", self.dim)
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray:
        q = self._local.encode_query(text).astype(np.float32)
        return q / (np.linalg.norm(q) + 1e-12)


class RecordedEmbedder:
    def __init__(self, npz_path: Path):
        self._z = np.load(npz_path)
        self.dim = int(json.loads(str(self._z["__meta__"])).get("dim", "512"))
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray:
        if label is None or label not in self._z.files:
            raise KeyError(f"no recorded vector for {label}")
        return self._z[label].astype(np.float32)


class SeedResolver(Protocol):
    def resolve(self, ref: str) -> SeedSet: ...


class FrozenSeedResolver:
    def __init__(self, mapping: dict[str, list[int]]):
        self.m = mapping
    def resolve(self, ref: str) -> SeedSet:
        if ref not in self.m:
            raise SelectorSpecError(f"unknown seed set {ref}")
        return SeedSet.build(ref, self.m[ref])


class LedgerSeedResolver:
    def __init__(self, domain):
        self.domain = domain
    def _ledger(self) -> list[int]:
        from corpus_engine.ledger import open_ledger
        return list(open_ledger(domain=self.domain).view().seed_set().case_ids)
    def _treatise(self) -> list[int]:
        out = []
        for line in Path(self.domain.gold_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                if g.get("tier") == "treatise" and g.get("case_id"):
                    out.append(int(g["case_id"]))
        return out
    def resolve(self, ref: str) -> SeedSet:
        if ref == "ledger-favorable-reviewed":
            return SeedSet.build(ref, self._ledger())
        if ref == "treatise-anchors":
            return SeedSet.build(ref, self._treatise())
        if ref == "both":
            return SeedSet.build(ref, self._ledger() + self._treatise())
        raise SelectorSpecError(f"unknown seed set {ref}")


EMBED_KINDS = {"embedding", "relevance_feedback"}
SEEDED_KINDS = {"citation_graph", "relevance_feedback"}


def fingerprint(conn, selector: Selector, partitions: list[Partition], *, seeds: SeedResolver, min_seeds: int) -> str | Skip:
    parts = tuple(partitions)
    seed_part = ""
    if selector.kind in SEEDED_KINDS:
        ss = seeds.resolve(selector.params["seed_set"])
        if len(ss.case_ids) < min_seeds:
            return Skip(selector.key, parts, "seed_unavailable")
        seed_part = f"|seed:{ss.hash}"
    if selector.kind in ("fts_phrase", "fts_near"):
        return "fts:v1"
    if selector.kind == "regex":
        return "regex:v1"
    if selector.kind == "citation_graph":
        return f"graph:v1{seed_part}"
    runs = partition_runs(conn)
    seen: set[str] = set()
    for p in parts:
        r = runs.get((p.era, p.jurisdiction), set())
        if not r:
            return Skip(selector.key, parts, "index_incomplete")
        seen |= r
    if len(seen) != 1:
        return Skip(selector.key, parts, "mixed_embedding_model")
    return f"embed:{next(iter(seen))}|engine:{ENGINE_VERSION}{seed_part}"
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_selector_ports.py -q` — Expected: 2 passed.

```bash
git add corpus_engine/selector/ports.py tests/test_selector_ports.py
git commit -m "selector: query-embedder and seed-resolver ports; fingerprint rule with skips"
```

---

### Task 5: Runners and the per-run context

**Files:**
- Create: `corpus_engine/selector/runners.py`, `tests/test_selector_runners.py`

**Interfaces:**
- Consumes: `Selector`, `Partition`, `Signal`, `SeedSet`; ports from Task 4; `chunks`/`cites_to`/`cases`/FTS tables.
- Produces:
  - `class EngineContext: conn, domain, embedder: QueryEmbedder | None, seeds: SeedResolver, resources: dict` with `matrix_for(partitions) -> ChunkMatrix` (cached per sorted partition-key tuple; `ChunkMatrix(M8: int8 (n,dim), scales, chunk_ids, case_ids, spans, part_codes: int16, part_index: dict[str,int])` loaded ONLY for those partitions by a streaming cursor) and `query_vec(selector) -> np.ndarray` (cached per label; from `embedder.encode_query(params["query_text"], label=selector.label)` for `embedding`, or the normalized centroid of the seed cases' dequantized chunk vectors for `relevance_feedback`).
  - `run_fts(ctx, sel, part) -> list[Signal]`, `run_regex(...)` — verbatim moves of `pipeline/shard.py` `run_fts`/`run_regex` producing `Signal`s (same SQL, same `ctx()` 200-char padding, same first-literal-phrase rule and the `norm_text[:400]` fallback).
  - `run_embedding(ctx, sel, part)`: sims over `ctx.matrix_for(all in-scope partitions of sel)` computed once per selector (cached in `ctx.resources`), mask by `part`, order by `np.lexsort((chunk_ids[cand], -sims[cand]))`, take the first `top_k*3`, then the existing dedup-per-case/`min_cosine`/`top_k` loop; `matched_text` = `substr(norm_text, cs+1, min(ce-cs, 400))` as today.
  - `run_relevance_feedback(ctx, sel, part)`: identical to `run_embedding` with the centroid query; excludes seed case ids from results.
  - `run_citation_graph(ctx, sel, part)`: seeds = `ctx.seeds.resolve(params["seed_set"])`; direction `both|citing|cited`; `citing`: `SELECT ct.citing_case_id, ct.cited_case_id, ct.cite FROM cites_to ct JOIN cases c ON c.case_id = ct.citing_case_id WHERE ct.cited_case_id IN (seeds) AND c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL`; `cited`: symmetric on `cited_case_id`; one `Signal` per case (first hit), `matched_text = f"cites {cite}"` or `f"cited by {cite}"`, `char_span (0,0)`, `chunk_id None`, `cosine None`; seeds themselves excluded.
  - `RUNNERS: dict[str, Callable]` keyed by kind.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selector_runners.py
import json, shutil, sqlite3
import numpy as np
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, Selector, load_selectors
from corpus_engine.selector.ports import FrozenSeedResolver, RecordedEmbedder
from corpus_engine.selector.runners import EngineContext, RUNNERS, run_citation_graph, run_embedding, run_fts

def _ctx(tmp_path, fixture_db, repo_root, seeds=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    return EngineContext(conn, load_domain(), RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz"),
                         seeds or FrozenSeedResolver({}))

def test_lexical_runners_reproduce_cycle_003_signals_on_fixture_cases(tmp_path, fixture_db, repo_root):
    ctx = _ctx(tmp_path, fixture_db, repo_root)
    sig = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    fixture_ids = {r[0] for r in ctx.conn.execute("SELECT case_id FROM cases")}
    sels = [s for s in load_selectors(ctx.domain) if s.kind in ("fts_phrase", "fts_near", "regex")]
    checked = 0
    for s in sels:
        want = {(r[0], r[1], r[2], r[3]) for r in sig.execute(
            "SELECT case_id, matched_text, char_span_start, char_span_end FROM signals WHERE selector_id=? AND selector_version=?", (s.id, s.version))
            if r[0] in fixture_ids}
        got = set()
        for era in s.era_scope:
            for jur in s.jurisdiction_scope:
                for g in RUNNERS[s.kind](ctx, s, Partition(era, jur)):
                    got.add((g.case_id, g.matched_text, g.char_span[0], g.char_span[1]))
        assert got == want, s.label
        checked += len(want)
    assert checked > 50

def test_embedding_runner_is_deterministic_and_stable_sorted(tmp_path, fixture_db, repo_root):
    ctx = _ctx(tmp_path, fixture_db, repo_root)
    s = next(x for x in load_selectors(ctx.domain) if x.label == "embed-householder-letting-21@v2")
    part = Partition(*ctx.conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1,2 ORDER BY count(*) DESC LIMIT 1").fetchone())
    a = run_embedding(ctx, s, part); b = run_embedding(_ctx(tmp_path / "b", fixture_db, repo_root), s, part)
    assert [(x.case_id, x.chunk_id, round(x.cosine, 6)) for x in a] == [(x.case_id, x.chunk_id, round(x.cosine, 6)) for x in b]
    assert all(a[i].cosine >= a[i + 1].cosine for i in range(len(a) - 1)) and len({x.case_id for x in a}) == len(a)
    assert all(x.cosine >= s.params["min_cosine"] for x in a) and len(a) <= s.params["top_k"]

def test_citation_graph_runner_walks_both_directions(tmp_path, fixture_db, repo_root):
    seeds = FrozenSeedResolver({"s": [1, 2, 3, 4, 5]})
    ctx = _ctx(tmp_path, fixture_db, repo_root, seeds)
    part = Partition(*ctx.conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone())
    a, b = [r[0] for r in ctx.conn.execute("SELECT case_id FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL LIMIT 2", (part.era, part.jurisdiction))]
    ctx.conn.execute("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", (a, 1, "1 Seed 1", "reporters:state", "X", 1850, 1, 0))   # a cites seed 1
    ctx.conn.execute("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", (2, b, "2 B 2", "reporters:state", "X", 1850, 1, 0))       # seed 2 cites b
    ctx.conn.commit()
    sel = Selector("g", 1, "citation_graph", "c", "p", (part.era,), (part.jurisdiction,), {"seed_set": "s", "direction": "both"})
    got = {(g.case_id, g.matched_text) for g in run_citation_graph(ctx, sel, part)}
    assert got == {(a, "cites 1 Seed 1"), (b, "cited by 2 B 2")}
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.selector.runners`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/selector/runners.py
from __future__ import annotations
import re
from dataclasses import dataclass, field
import numpy as np
from corpus_engine.selector.model import Partition, SeedSet, Selector, Signal


def ctx_text(text: str, start: int, end: int, pad: int = 200) -> str:
    return text[max(0, start - pad): end + pad]


@dataclass
class ChunkMatrix:
    M8: np.ndarray; scales: np.ndarray; chunk_ids: np.ndarray; case_ids: np.ndarray
    spans: np.ndarray; part_codes: np.ndarray; part_index: dict[str, int]


@dataclass
class EngineContext:
    conn: object
    domain: object
    embedder: object | None
    seeds: object
    resources: dict = field(default_factory=dict)

    def matrix_for(self, partitions: list[Partition]) -> ChunkMatrix:
        keys = tuple(sorted(p.key for p in partitions))
        if ("matrix", keys) in self.resources:
            return self.resources[("matrix", keys)]
        conn = self.conn
        dim = int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))
        where = " OR ".join("(c.era_partition=? AND c.jurisdiction=?)" for _ in partitions)
        params = [x for p in partitions for x in (p.era, p.jurisdiction)]
        n = conn.execute(f"SELECT count(*) FROM chunks ch JOIN cases c ON c.case_id=ch.case_id WHERE c.is_duplicate_of IS NULL AND ({where})", params).fetchone()[0]
        M8 = np.empty((n, dim), dtype=np.int8); scales = np.empty(n, np.float32); chunk_ids = np.empty(n, np.int64)
        case_ids = np.empty(n, np.int64); spans = np.empty((n, 2), np.int32); codes = np.empty(n, np.int16)
        index = {k: i for i, k in enumerate(keys)}
        i = 0
        for row in conn.execute(f"""SELECT ch.chunk_id, ch.case_id, ch.char_start, ch.char_end, ch.embedding, ch.embed_scale,
                                    c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id=ch.case_id
                                    WHERE c.is_duplicate_of IS NULL AND ({where}) ORDER BY ch.chunk_id""", params):
            vec = np.frombuffer(row[4], dtype=np.int8)
            M8[i, :len(vec)] = vec[:dim]; scales[i] = row[5]; chunk_ids[i] = row[0]; case_ids[i] = row[1]
            spans[i] = (row[2], row[3]); codes[i] = index[f"{row[6]}|{row[7]}"]; i += 1
        m = ChunkMatrix(M8[:i], scales[:i], chunk_ids[:i], case_ids[:i], spans[:i], codes[:i], index)
        self.resources[("matrix", keys)] = m
        return m

    def query_vec(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        key = ("query", sel.label)
        if key in self.resources:
            return self.resources[key]
        if sel.kind == "embedding":
            q = self.embedder.encode_query(sel.params["query_text"], label=sel.label)
        else:
            seeds = self.seeds.resolve(sel.params["seed_set"])
            mask = np.isin(matrix.case_ids, np.asarray(seeds.case_ids))
            if not mask.any():
                q = np.zeros(matrix.M8.shape[1], np.float32)
            else:
                vecs = matrix.M8[mask].astype(np.float32) * matrix.scales[mask][:, None]
                q = vecs.mean(axis=0)
        q = (q / (np.linalg.norm(q) + 1e-12)).astype(np.float32)
        self.resources[key] = q
        return q

    def sims(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        key = ("sims", sel.label)
        if key in self.resources:
            return self.resources[key]
        q = self.query_vec(sel, matrix)
        n = len(matrix.M8); out = np.empty(n, np.float32); block = 200_000
        for a in range(0, n, block):
            b = min(a + block, n)
            out[a:b] = (matrix.M8[a:b].astype(np.float32) @ q) * matrix.scales[a:b]
        self.resources[key] = out
        return out


def _scope_partitions(sel: Selector) -> list[Partition]:
    return [Partition(e, j) for e in sel.era_scope for j in sel.jurisdiction_scope]


def run_fts(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    table = "fts_raw" if s.params.get("index", "raw") == "raw" else "fts_porter"
    rows = ctx.conn.execute(
        f"""SELECT c.case_id, c.norm_text FROM {table} JOIN cases c ON c.case_id = {table}.rowid
            WHERE {table} MATCH ? AND c.era_partition = ? AND c.jurisdiction = ? AND c.is_duplicate_of IS NULL""",
        (s.params["pattern"], part.era, part.jurisdiction)).fetchall()
    phrases = [p.lower() for p in re.findall(r'"([^"]+)"', s.params["pattern"])]
    out = []
    for case_id, norm_text in rows:
        span, matched = (0, 0), ""
        for ph in phrases:
            i = norm_text.find(ph)
            if i >= 0:
                span = (i, i + len(ph)); matched = ctx_text(norm_text, *span); break
        if not matched:
            matched = norm_text[:400]
        out.append(Signal(case_id, s.id, s.version, matched, span, None, None, part))
    return out


def run_regex(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    pat = re.compile(s.params["pattern"], re.IGNORECASE)
    out = []
    for case_id, norm_text in ctx.conn.execute(
            "SELECT case_id, norm_text FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL",
            (part.era, part.jurisdiction)):
        m = pat.search(norm_text)
        if m:
            out.append(Signal(case_id, s.id, s.version, ctx_text(norm_text, m.start(), m.end()), (m.start(), m.end()), None, None, part))
    return out


def _vector_runner(ctx: EngineContext, s: Selector, part: Partition, exclude: set[int]) -> list[Signal]:
    matrix = ctx.matrix_for(_scope_partitions(s))
    sims = ctx.sims(s, matrix)
    code = matrix.part_index.get(part.key)
    if code is None:
        return []
    cand = np.flatnonzero(matrix.part_codes == code)
    if not len(cand):
        return []
    order = cand[np.lexsort((matrix.chunk_ids[cand], -sims[cand]))][: int(s.params.get("top_k", 50)) * 3]
    out, seen = [], set()
    min_cos, top_k = float(s.params.get("min_cosine", 0.5)), int(s.params.get("top_k", 50))
    for i in order:
        if sims[i] < min_cos or len(out) >= top_k:
            break
        case_id = int(matrix.case_ids[i])
        if case_id in seen or case_id in exclude:
            continue
        seen.add(case_id)
        cs, ce = int(matrix.spans[i][0]), int(matrix.spans[i][1])
        text = ctx.conn.execute("SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?", (cs + 1, min(ce - cs, 400), case_id)).fetchone()[0]
        out.append(Signal(case_id, s.id, s.version, text, (cs, ce), int(matrix.chunk_ids[i]), float(sims[i]), part))
    return out


def run_embedding(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    return _vector_runner(ctx, s, part, set())


def run_relevance_feedback(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    seeds = ctx.seeds.resolve(s.params["seed_set"])
    return _vector_runner(ctx, s, part, set(seeds.case_ids))


def run_citation_graph(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    seeds = ctx.seeds.resolve(s.params["seed_set"]); ids = list(seeds.case_ids)
    if not ids:
        return []
    ph = ",".join("?" * len(ids)); direction = s.params.get("direction", "both")
    out, seen = [], set(ids)
    if direction in ("both", "citing"):
        for cid, cite in ctx.conn.execute(
                f"""SELECT ct.citing_case_id, ct.cite FROM cites_to ct JOIN cases c ON c.case_id = ct.citing_case_id
                    WHERE ct.cited_case_id IN ({ph}) AND c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL
                    ORDER BY ct.citing_case_id, ct.cite""", ids + [part.era, part.jurisdiction]):
            if cid not in seen:
                seen.add(cid); out.append(Signal(cid, s.id, s.version, f"cites {cite}", (0, 0), None, None, part))
    if direction in ("both", "cited"):
        for cid, cite in ctx.conn.execute(
                f"""SELECT ct.cited_case_id, ct.cite FROM cites_to ct JOIN cases c ON c.case_id = ct.cited_case_id
                    WHERE ct.citing_case_id IN ({ph}) AND c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL
                    ORDER BY ct.cited_case_id, ct.cite""", ids + [part.era, part.jurisdiction]):
            if cid not in seen:
                seen.add(cid); out.append(Signal(cid, s.id, s.version, f"cited by {cite}", (0, 0), None, None, part))
    return out


RUNNERS = {"fts_phrase": run_fts, "fts_near": run_fts, "regex": run_regex, "embedding": run_embedding,
           "citation_graph": run_citation_graph, "relevance_feedback": run_relevance_feedback}
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_selector_runners.py -q` — Expected: 3 passed. If the lexical replay fails for one selector, diff one `(case_id, matched_text)` pair against the fixture: the only legitimate difference is a case whose `norm_text` in `corpus-tiny.db` differs from the live DB at cycle-003 time, which would mean the fixture was built after a re-ingest; report rather than adjust.

```bash
git add corpus_engine/selector/runners.py tests/test_selector_runners.py
git commit -m "selector: runners for six kinds with a per-run context; stable candidate sort; lexical replay proven"
```

---

### Task 6: The engine: plan, shard, attribution, probe; scripts become wrappers

**Files:**
- Create: `corpus_engine/selector/engine.py`, `tests/test_selector_engine.py`, `tests/test_recall_char.py`
- Modify: `corpus_engine/selector/__init__.py`, `corpus_engine/selector/packing.py` (add `build_batches`), `pipeline/shard.py` (wrapper; remove `missing_jurisdictions` and its test), `pipeline/eval_recall.py` (use `attribution`), `tests/test_shard_guard.py` (delete)

**Interfaces:**
- Consumes: everything above; `packing.pack_batches`; `open_ledger` manifests.
- Produces:
  - `packing.build_batches(conn, run_id, *, gold_ids, exclude_ids, batch_size) -> list[dict]` (the in-memory list `pack_batches` writes; `pack_batches` becomes a thin caller that deletes old files and writes these, so Stage 1's byte-for-byte test still passes).
  - `engine.already_read_ids(runs_dir, ledger_dir) -> set[int]` per the Global Constraints.
  - `engine.plan(conn, domain, *, seeds, embedder=None, selectors=None) -> ShardPlan`: for each active selector (file order) and each scope partition (era order, jurisdiction order): if the partition has zero non-duplicate cases → `Skip("partition_empty")` (one Skip per selector listing those partitions); else `fp = fingerprint(...)`; a `Skip` result is recorded once per selector; otherwise a `PlanUnit` for each partition not yet `covered(...)`. `selectors_digest` = sha256 over the concatenated selector digests.
  - `engine.shard(conn, domain, run_id, *, seeds, embedder=None, dry_run=False, stamp=None, runs_dir=None, ledger_dir=None, out_dir=None, log=print) -> ShardReport`: `plan`, then for each unit in plan order run `RUNNERS[kind]`, `INSERT` its signals (`era_partition`, `jurisdiction`, `run_id`, `ts` from `stamp.ts`) and `mark_covered` in one commit; then `build_batches` with `gold_ids` from `domain.gold_path` and `exclude_ids = already_read_ids(...)`; writes files only when not `dry_run` (to `out_dir or runs_dir/run_id/batches`); `ShardReport.manifest` = `{"engine_version", "selectors_digest", "selectors": [{label, digest, kind}], "embed_runs": partition_runs summary, "seed_hashes": {ref: hash}, "batch_size", "exclude_count", "exclude_sha256", "units_run", "skips": [...], "ts"}` and is also written as `runs/<run_id>/shard-manifest.json` when not dry-run.
  - `engine.attribution(conn, case_ids) -> dict[int, tuple[SignalRef, ...]]` sorted by `(selector_id, selector_version, run_id)`; missing ids map to `()`.
  - `engine.probe(conn, domain, selector, partition, *, seeds, embedder=None, limit=50) -> list[Signal]` (no writes).
  - `pipeline/shard.py`: `main()` parses the old flags and calls `shard(...)` with `LedgerSeedResolver(domain)` and `LocalQueryEmbedder(conn)` (constructed lazily only if an embedding-kind selector is in the plan); prints the plan summary; `--dry-run` prints units and skips without writing.
  - `pipeline/eval_recall.py`: `evaluate` computes `attribution(conn, [gold case ids])` once and derives the same report shape as before.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selector_engine.py
import json, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.engine import attribution, plan, shard
from corpus_engine.selector.model import Selector
from corpus_engine.selector.ports import FrozenSeedResolver, RecordedEmbedder
from corpus_engine.selector.runners import EngineContext

class Stamp:
    run_id = "t-01"; ts = "2026-01-01T00:00:00"

def _conn(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn); return conn

def test_plan_skips_empty_partitions_and_covers_after_shard(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    pl = plan(conn, dom, seeds=seeds, embedder=emb)
    assert any(s.reason == "partition_empty" for s in pl.skips)          # Mass. etc. have no cases in the fixture
    assert pl.units and all(u.partition.jurisdiction in {"Tex.", "Pa.", "La.", "N.Y."} for u in pl.units)
    rep = shard(conn, dom, "t-01", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
                ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "b", log=lambda *_: None)
    assert sum(rep.signals_written.values()) > 0 and rep.batches_written > 0
    assert (tmp_path / "b" / "batch-001.json").exists() and rep.manifest["engine_version"] == "v2"
    pl2 = plan(conn, dom, seeds=seeds, embedder=emb)
    assert pl2.units == ()                                                 # everything covered now
    rep2 = shard(conn, dom, "t-02", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
                 ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "b2", dry_run=True, log=lambda *_: None)
    assert sum(rep2.signals_written.values()) == 0 and not (tmp_path / "b2").exists()

def test_attribution_reads_signals_only(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path, fixture_db)
    conn.execute("INSERT INTO signals (case_id, selector_id, selector_version, matched_text, char_span_start, char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts) VALUES (7,'a',1,'m',0,1,NULL,NULL,'e','j','r1','t')")
    conn.commit()
    a = attribution(conn, [7, 8])
    assert a[7][0].selector_id == "a" and a[8] == ()
```

```python
# tests/test_recall_char.py
import json, sqlite3
from corpus_engine.selector.engine import attribution

def test_attribution_reproduces_cycle_003_recall_report(repo_root, golden_dir):
    want = json.loads((golden_dir / "recall-cycle-003.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    gold = [json.loads(l) for l in (repo_root / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [g["case_id"] for g in gold if g.get("case_id")]
    attr = attribution(conn, ids)
    for tier, sel in (("brief-letting", lambda g: g.get("tier") == "brief" and g.get("domain") == "letting"),
                      ("brief-all", lambda g: g.get("tier") == "brief"), ("treatise", lambda g: g.get("tier") == "treatise")):
        entries = [g for g in gold if sel(g)]; in_corpus = [g for g in entries if g.get("case_id")]
        hits = [g for g in in_corpus if attr[g["case_id"]]]
        assert (len(entries), len(in_corpus), len(hits)) == (want["tiers"][tier]["total"], want["tiers"][tier]["resolved_in_corpus"], want["tiers"][tier]["signaled"]), tier
    letting = [g for g in gold if g.get("tier") == "brief" and g.get("domain") == "letting" and g.get("case_id")]
    got_hits = sorted([{"case_id": g["case_id"], "selectors": sorted({f"{r.selector_id}@v{r.selector_version}" for r in attr[g["case_id"]]})} for g in letting if attr[g["case_id"]]], key=lambda h: h["case_id"])
    assert got_hits == want["hits"] and sorted(g["case_id"] for g in letting if not attr[g["case_id"]]) == want["misses"]
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.selector.engine`.

- [ ] **Step 3: Implement**

In `packing.py`, split `pack_batches` so the body up to the sort builds `pending` and returns the batch dicts (with `batch_id` set) from a new `build_batches(conn, run_id, *, gold_ids, exclude_ids, batch_size=18) -> list[dict]`; `pack_batches` then does the directory cleanup and writes each dict with `json.dumps(batch, indent=1)` — the output bytes must be unchanged (the Stage 1 test guards this).

```python
# corpus_engine/selector/engine.py
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from corpus_engine.indexer.embed import partition_runs
from corpus_engine.selector.coverage import covered, mark_covered
from corpus_engine.selector.model import (ENGINE_VERSION, Partition, PlanUnit, Selector, ShardPlan, ShardReport,
                                          SignalRef, Skip, load_selectors)
from corpus_engine.selector.packing import build_batches, pack_batches
from corpus_engine.selector.ports import fingerprint
from corpus_engine.selector.runners import RUNNERS, EngineContext
from corpus_engine.store import paths


def already_read_ids(runs_dir: Path, ledger_dir: Path) -> set[int]:
    ids: set[int] = set()
    for f in runs_dir.glob("*/extractions*/*.json"):
        try:
            for r in json.loads(f.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("case_id"):
                    ids.add(int(r["case_id"]))
        except (json.JSONDecodeError, OSError):
            continue
    for f in (ledger_dir / "manifest").glob("*.jsonl") if (ledger_dir / "manifest").exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(int(json.loads(line)["case_id"]))
    return ids


def _partition_counts(conn) -> dict[str, int]:
    return {f"{e}|{j}": n for e, j, n in conn.execute(
        "SELECT era_partition, jurisdiction, count(*) FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1,2")}


def plan(conn, domain, *, seeds, embedder=None, selectors: list[Selector] | None = None) -> ShardPlan:
    sels = selectors if selectors is not None else load_selectors(domain)
    counts = _partition_counts(conn)
    units, skips = [], []
    for s in sels:
        parts = [Partition(e, j) for e in s.era_scope for j in s.jurisdiction_scope]
        empty = [p for p in parts if counts.get(p.key, 0) == 0]
        live = [p for p in parts if counts.get(p.key, 0) > 0]
        if empty:
            skips.append(Skip(s.key, tuple(empty), "partition_empty"))
        if not live:
            continue
        fp = fingerprint(conn, s, live, seeds=seeds, min_seeds=domain.sharding.min_seeds)
        if isinstance(fp, Skip):
            skips.append(fp); continue
        for p in live:
            if not covered(conn, s.key, p.key, fp):
                units.append(PlanUnit(s.key, p, fp))
    digest = hashlib.sha256("".join(s.digest() for s in sels).encode()).hexdigest()[:16]
    return ShardPlan("", tuple(units), tuple(skips), digest)


def _gold_ids(domain) -> set[int]:
    out = set(); gp = Path(domain.gold_path)
    if gp.exists():
        for line in gp.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("case_id"):
                out.add(int(json.loads(line)["case_id"]))
    return out


def shard(conn, domain, run_id: str, *, seeds, embedder=None, dry_run=False, stamp=None, runs_dir: Path | None = None,
          ledger_dir: Path | None = None, out_dir: Path | None = None, log=print) -> ShardReport:
    ts = getattr(stamp, "ts", None) or time.strftime("%Y-%m-%dT%H:%M:%S")
    sels = load_selectors(domain); by_key = {s.key: s for s in sels}
    pl = plan(conn, domain, seeds=seeds, embedder=embedder, selectors=sels)
    pl = ShardPlan(run_id, pl.units, pl.skips, pl.selectors_digest)
    ctx = EngineContext(conn, domain, embedder, seeds)
    written: dict = {}
    for sk in pl.skips:
        log(f"SKIP {sk.key[0]}@v{sk.key[1]}: {sk.reason} ({len(sk.partitions)} partitions)")
    if not dry_run:
        for u in pl.units:
            s = by_key[u.key]
            sigs = RUNNERS[s.kind](ctx, s, u.partition)
            conn.executemany("""INSERT INTO signals (case_id, selector_id, selector_version, matched_text, char_span_start,
                                char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                             [(g.case_id, g.selector_id, g.selector_version, g.matched_text, g.char_span[0], g.char_span[1],
                               g.chunk_id, g.cosine, u.partition.era, u.partition.jurisdiction, run_id, ts) for g in sigs])
            mark_covered(conn, u.key, u.partition.key, u.fingerprint, run_id, ts, len(sigs))
            conn.commit()
            written[(u.key, u.partition.key)] = len(sigs)
            log(f"{s.label} x {u.partition.key}: {len(sigs)} signals")
    runs_dir = runs_dir or paths().runs
    exclude = already_read_ids(runs_dir, ledger_dir or paths().ledger)
    gold = _gold_ids(domain)
    seed_hashes = {}
    for s in sels:
        if "seed_set" in s.params:
            try:
                seed_hashes[s.params["seed_set"]] = seeds.resolve(s.params["seed_set"]).hash
            except Exception as e:                     # noqa: BLE001 — reported, not fatal
                seed_hashes[s.params["seed_set"]] = f"unresolved: {type(e).__name__}"
    manifest = {"engine_version": ENGINE_VERSION, "run_id": run_id, "ts": ts, "selectors_digest": pl.selectors_digest,
                "selectors": [{"label": s.label, "digest": s.digest(), "kind": s.kind} for s in sels],
                "embed_runs": {k[0] + "|" + k[1]: sorted(v) for k, v in partition_runs(conn).items()},
                "seed_hashes": seed_hashes, "batch_size": domain.sharding.batch_size,
                "exclude_count": len(exclude), "exclude_sha256": hashlib.sha256(",".join(map(str, sorted(exclude))).encode()).hexdigest(),
                "units_run": len(pl.units) if not dry_run else 0,
                "skips": [{"selector": f"{k[0]}@v{k[1]}", "reason": r, "partitions": [p.key for p in ps]} for k, ps, r in
                          ((s.key, s.partitions, s.reason) for s in pl.skips)]}
    if dry_run:
        batches = build_batches(conn, run_id, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size)
        return ShardReport(pl, written, 0, None, sum(len(b["cases"]) for b in batches), len(exclude), manifest)
    out = out_dir or (runs_dir / run_id / "batches")
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size)
    (out.parent / "shard-manifest.json").write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    cases = sum(len(json.loads(f.read_text(encoding="utf-8"))["cases"]) for f in out.glob("batch-*.json"))
    return ShardReport(pl, written, n, out, cases, len(exclude), manifest)


def attribution(conn, case_ids) -> dict[int, tuple[SignalRef, ...]]:
    ids = [int(c) for c in case_ids]; out = {c: () for c in ids}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        for cid, sid, ver, run, cos in conn.execute(
                f"""SELECT DISTINCT case_id, selector_id, selector_version, run_id, cosine FROM signals
                    WHERE case_id IN ({','.join('?' * len(chunk))}) ORDER BY case_id, selector_id, selector_version, run_id""", chunk):
            out[cid] = out[cid] + (SignalRef(sid, ver, run, cos),)
    return out


def probe(conn, domain, selector: Selector, partition: Partition, *, seeds, embedder=None, limit: int = 50):
    ctx = EngineContext(conn, domain, embedder, seeds)
    return RUNNERS[selector.kind](ctx, selector, partition)[:limit]
```

`corpus_engine/selector/__init__.py`: `from corpus_engine.selector.engine import attribution, plan, probe, shard` and `from corpus_engine.selector.model import ENGINE_VERSION`; `__all__` accordingly.

`pipeline/shard.py` becomes a wrapper: keep the argument parser (`--run-id`, `--dry-run`, `--batches-only`, `--exclude-mapped` now a no-op kept for compatibility with a printed note), open the store, `store.ensure_schema` + `store.migrate` + `migrate_coverage(conn, {s.key: s for s in load_selectors(domain)})`, build `seeds = LedgerSeedResolver(domain)` and `embedder = LocalQueryEmbedder(conn)` only when the plan contains an embedding-kind unit (call `plan` with `embedder=None` first, which is fine because fingerprinting does not touch the embedder), then `shard(...)`; print the report summary. Delete `missing_jurisdictions`, `load_selectors`, `selector_scopes`, `ctx`, the runners, `RUNNERS`, `_EMBED_CACHE`, `already_mapped_ids`, and `emit_batches` from the script; delete `tests/test_shard_guard.py` (the engine's `partition_empty` skip supersedes it; add a test in `test_selector_engine.py` already covering it).

`pipeline/eval_recall.py`: replace the per-case query in `evaluate` with one `attribution(conn, [g["case_id"] for g in gold if g.get("case_id")])` call and `sels = attr[g["case_id"]]`; the report shape is unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python -m pytest tests/test_selector_engine.py tests/test_recall_char.py tests/test_packing_char.py -q` — Expected: all pass (the packing byte test proves `build_batches` did not change the bytes).
Run: `.venv\Scripts\python -m pytest tests -q` — Expected: green.
Run: `.venv\Scripts\python pipeline\shard.py --run-id probe --dry-run` (live DB; requires `LocalQueryEmbedder` only if embedding units are uncovered — after the coverage migration every embedding unit is uncovered because the fingerprint engine version moved from v1 to v2, so the local model loads; expect a plan listing 36 selectors' units and the `partition_empty` skips for the six un-ingested jurisdictions if Stage 2A Task 7 has not run yet). Expected: no writes; the printed plan.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/selector tests/test_selector_engine.py tests/test_recall_char.py pipeline/shard.py pipeline/eval_recall.py
git rm -q tests/test_shard_guard.py
git commit -m "selector engine: plan/shard/attribution/probe with fingerprinted coverage; shard.py and eval_recall.py are wrappers"
```

---

### Task 7: Selectors v4 (two graph-and-feedback selectors), changelog, planner note, handoff

**Files:**
- Modify: `selectors/selectors.yaml` (append two selectors), `selectors/CHANGELOG.md` (v4 entry), `prompts/planner.md` (one paragraph on the new kinds and the fingerprint rule), `reports/handoff-cycle-004.md` (order-of-work items 2 and 6), `README.md` (shard section)
- Create: `tests/test_selectors_v4.py`

**Interfaces:**
- Consumes: `load_selectors`, `plan`, `LedgerSeedResolver`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_selectors_v4.py
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.selector.ports import LedgerSeedResolver

def test_v4_selectors_present_and_seeds_resolve():
    dom = load_domain(); sels = {s.label: s for s in load_selectors(dom)}
    assert sels["citation-graph-38@v1"].kind == "citation_graph" and sels["citation-graph-38@v1"].params == {"seed_set": "both", "direction": "both"}
    fb = sels["relevance-feedback-39@v1"]
    assert fb.kind == "relevance_feedback" and fb.params["seed_set"] == "ledger-favorable-reviewed" and fb.params["top_k"] == 250
    ss = LedgerSeedResolver(dom).resolve("both")
    assert len(ss.case_ids) >= 50 and len(ss.hash) == 16
```

- [ ] **Step 2: Run to verify failure** — Expected: KeyError on `citation-graph-38@v1`.

- [ ] **Step 3: Append the selectors and the changelog**

Append to `selectors/selectors.yaml`:

```yaml
# ---------- v4 (cycle 004): graph and feedback selectors (ADR-0005, research §5) ----------

- id: citation-graph-38
  version: 1
  concept: incident_of_ownership
  type: citation_graph
  seed_set: both
  direction: both
  era_scope: all
  jurisdiction_scope: all
  polarity: favorable-candidate
  rationale: >
    One hop in both directions from the human-reviewed favorable ledger records and
    the treatise anchors. Reaches cases whose vocabulary no lexical selector matches,
    including pre-1860 authority through its later citations. Seed hash is part of the
    coverage fingerprint, so a grown seed set re-runs automatically.
  author: planner-cycle-004
  status: active

- id: relevance-feedback-39
  version: 1
  concept: letting_transaction
  type: relevance_feedback
  seed_set: ledger-favorable-reviewed
  top_k: 250
  min_cosine: 0.40
  era_scope: all
  jurisdiction_scope: all
  polarity: favorable-candidate
  rationale: >
    Centroid of the human-reviewed favorable cases' chunk vectors as the query
    (Kats et al. 2023: judged-relevant vector summing beats keyword expansion for
    recall). Seeds are excluded from the results. Threshold set for the 4B index;
    re-tune at the recall gate.
  author: planner-cycle-004
  status: active
```

Append to `selectors/CHANGELOG.md`:

```markdown
## v4 — 2026-09-02 (cycle 004), engine v2

- Engine: `corpus_engine.selector` replaces `pipeline/shard.py`. Coverage is keyed by
  a retriever fingerprint (lexical `fts:v1`/`regex:v1`; embedding
  `embed:<run>|engine:v2`; graph `graph:v1|seed:<hash>`; feedback adds `|seed:<hash>`).
  Consequence: every embedding selector re-runs once after this bump (engine v1
  rows never match v2), and again after the Qwen3-4B re-embed changes `<run>`.
- Engine v2 fixes an unstable candidate sort (`np.argsort` default) with
  `lexsort((chunk_id, -cosine))`; results on ties may differ from cycles 1-3.
- Added `citation-graph-38` (seed: ledger human-reviewed favorable + treatise anchors,
  one hop both ways) and `relevance-feedback-39` (centroid of the reviewed favorable
  set, top_k 250, min_cosine 0.40).
- Un-ingested partitions are skipped (`partition_empty`) and never marked covered.
- Gate: recall must be non-decreasing against the held-out set at the next cycle run
  (development set: brief-letting 6/9, treatise 22/29 at v3).
```

Add to `prompts/planner.md` (after the rules list): "Two selector kinds need no vocabulary: `citation_graph` (seed_set: both | ledger-favorable-reviewed | treatise-anchors; direction both | citing | cited) and `relevance_feedback` (seed_set, top_k, min_cosine). Their coverage fingerprint includes the seed-set hash, so they re-run whenever the reviewed favorable set grows; do not bump their version for that. Embedding selectors carry no `model_rev`; the index run is part of the fingerprint."

Update `reports/handoff-cycle-004.md`: item 2 gains "Stage 2B done (selector engine)"; item 6 becomes "citation graph: backfilled (2A Task 4); `citation-graph-38` and `relevance-feedback-39` active at v4; first run at the cycle-004 shard". Update `README.md`'s shard line to mention `corpus_engine.selector` and the `--dry-run` plan.

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests -q` — Expected: green (the `load_real_selectors_file` test in Task 2 asserts 36 active; update it to 38).

```bash
git add selectors/selectors.yaml selectors/CHANGELOG.md prompts/planner.md reports/handoff-cycle-004.md README.md tests/test_selectors_v4.py tests/test_selector_model.py
git commit -m "selectors v4: citation-graph-38 and relevance-feedback-39; engine v2 changelog; planner note"
```

---

## Follow-on

- **Stage 2C — candidate ranking** (separate plan): a logistic-regression classifier over existing labels ranking the candidate pool before packing; convex fusion of normalized lexical and cosine scores; an FTS5 trigram side-index for OCR variants of a small high-value vocabulary; an optional Qwen3-Reranker-4B stage between shard and map tuned on the held-out gold set only. All land as `Ranker` adapters used by `build_batches`; signals stay untouched.
- **Cycle-004 shard**: after Stage 2A Task 7 and this plan, `pipeline/shard.py --run-id cycle-004-shard-01 --dry-run`, then the recall gate (`pipeline/eval_recall.py`) against the held-out set, then the real shard.
