# Stage 2C — Candidate Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Order the cycle-004 candidate pool before mapping through a `Ranker` port (null, fusion baseline, logistic-regression classifier, gated Qwen3 reranker) without changing which cases are candidates or touching the `signals` table.

**Architecture:** New package `corpus_engine/ranker/`: `features.py` (one feature function shared by training and scoring), `ports.py` (protocol + null + fusion), `labels.py` (labelled reads, frozen held-out slice), `classifier.py` (train/load/score), `evaluate.py` (AP, P@k, views), `reranker.py` (cross-encoder adapter). `build_batches` gains `ranker=None`; scores persist in a `rankings` table; `pipeline/rank.py` re-packs an existing run. Tools build the held-out set, train v1, pin and measure the reranker.

**Tech Stack:** Python 3.11, SQLite, numpy, scikit-learn (already in `.venv`), sentence-transformers/transformers (reranker only, GPU). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md`. One amendment made while planning (recorded in Task 2 and to be folded into the spec in Task 8): features are computed from the **union of a case's signals across all runs**, not the ranked run only, because the batch pool is itself all-runs (`build_batches` reads every signal; 2,799 of the 32,795 unread pool cases carry only cycle-001..003 signals) and every labelled read has signals from its own cycle. `run_id` names the `rankings` rows; it does not filter features.

## Global Constraints

- Python 3.11; `.venv\Scripts\python` from the repo root `C:\Users\marcu\Desktop\Str-corpus`. Tests: `.venv\Scripts\python -m pytest tests -q` (baseline 119 passed, 1 xfailed). Fixtures only in tests; the real reranker and the live DB are touched only by `tools/` scripts and `pipeline/rank.py`.
- **Order only (spec §1):** ranking never removes a candidate; `signals` and `coverage_v2` are never written by anything in this plan.
- **Golden (spec §7):** `build_batches(..., ranker=None)` is byte-for-byte the current path; `tests/test_packing_char.py` must keep passing at every task.
- **Determinism (ADR-0009, spec §7):** scores are `float32` rounded to 6 decimals before sorting; within a cell sort `(-score, case_id)`; batches order `(-mean_score, cell_key)`; the same model file + signals + pool ⇒ identical `rankings` rows and batch bytes.
- **Labels (spec §4):** positives = ledger `relevant == True` (weight 3 if human-reviewed else 1); negatives = extraction records with `relevant` false whose case is not ledger-relevant (weight 1); retracted ⇒ negative; duplicates excluded.
- **Held-out discipline (spec §4):** `data/eval/ranker-heldout-v1.jsonl` is built once with seed `20260904`, 25% per (era, jurisdiction, label) stratum (≥1 when the stratum has ≥2), its sha256 recorded in `domain.yaml` `ranking.heldout_sha256`; training refuses on hash mismatch or id overlap.
- **Ship rules (spec §5.4, §6):** classifier is default only if held-out AP beats fusion on both views (all labels; human-reviewed only); reranker is default only if its held-out AP beats the shipped default by ≥ 0.05 on both views. Bars are fixed before measurement.
- **Model pins:** the reranker revision is a commit sha, never `main`.
- `corpus_engine` stays domain-agnostic (query text, weights, paths from `domain.yaml`). Canonical bytes LF/UTF-8 without BOM (write files with `open(..., "w", encoding="utf-8", newline="\n")` or bytes).
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## File Structure

```
corpus_engine/ranker/
  __init__.py        public API: Ranker, NullRanker, FusionRanker, ClassifierRanker, QwenReranker, load_ranker
  features.py        FeatureLayout, feature_layout(), signal_summary(), case_features()
  ports.py           Ranker protocol, NullRanker, FusionRanker, round6(), load_ranker()
  labels.py          Label, labelled_reads(), read_extractions(), build_heldout(), load_heldout(), sha256_file()
  classifier.py      ClassifierRanker, train(), MODEL_FILE/MANIFEST_FILE
  evaluate.py        average_precision(), precision_at(), evaluate_scores(), compare()
  reranker.py        QwenReranker (CrossEncoder adapter), gpu_has_resident_model()
corpus_engine/store.py           (+) rankings DDL
corpus_engine/domain.py          (+) RankingSpec, Domain.ranking
domains/str-right-to-let/domain.yaml   (+) ranking: section
corpus_engine/selector/packing.py      build_batches(..., ranker=None); persist_rankings()
corpus_engine/selector/engine.py       shard(..., ranker=None); manifest "ranker"
pipeline/shard.py                      --ranker / --no-rank
pipeline/rank.py                       re-score + re-pack an existing run
tools/build_ranker_heldout.py, tools/train_ranker.py, tools/pin_reranker.py, tools/measure_reranker.py
data/eval/ranker-heldout-v1.jsonl      frozen (Task 4)
data/ranker/v1/{model.npz,manifest.json}   (Task 5; committed — small)
reports/ranking-cycle-004.md           (Task 8)
tests/helpers/ranker_fixture.py, tests/test_ranker_features.py, test_ranker_ports.py, test_ranker_labels.py,
tests/test_ranker_classifier.py, test_ranker_packing.py, test_ranker_reranker.py, test_rank_cli.py
```

---

### Task 1: Schema, domain config, package skeleton

**Files:**
- Modify: `corpus_engine/store.py` (SCHEMA), `corpus_engine/domain.py`, `domains/str-right-to-let/domain.yaml`
- Create: `corpus_engine/ranker/__init__.py` (empty for now), `tests/test_ranker_schema.py`

**Interfaces:**
- Produces: table `rankings(run_id TEXT, ranker_id TEXT, case_id INTEGER, score REAL, ts TEXT, PRIMARY KEY (run_id, ranker_id, case_id))`; `RankingSpec(default: str, classifier_version: str, fusion: Mapping[str, float], reranker: Mapping[str, Any], heldout: str, heldout_sha256: str | None, bar_ap_delta: float)`; `Domain.ranking: RankingSpec`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranker_schema.py
import shutil
from corpus_engine import store
from corpus_engine.domain import load_domain

def test_rankings_table_and_ranking_spec(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); actions = store.migrate(conn)
    assert "created rankings" in actions
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rankings)")]
    assert cols == ["run_id", "ranker_id", "case_id", "score", "ts"]
    assert store.migrate(conn) == []
    dom = load_domain()
    assert dom.ranking.default in {"null", "fusion", "classifier", "reranker"}
    assert dom.ranking.classifier_version == "v1" and dom.ranking.bar_ap_delta == 0.05
    assert dom.ranking.fusion == {"lexical_weight": 0.5, "cosine_weight": 0.5}
    assert dom.ranking.reranker["model"] == "Qwen/Qwen3-Reranker-4B" and dom.ranking.reranker["query"]
    assert dom.ranking.heldout == "data/eval/ranker-heldout-v1.jsonl"
```

- [ ] **Step 2: Run to verify failure** — `.venv\Scripts\python -m pytest tests/test_ranker_schema.py -q` — Expected: FAIL (`created rankings` missing / `Domain` has no `ranking`).

- [ ] **Step 3: Implement**

Append to `store.SCHEMA` (before the closing `"""`):
```sql
CREATE TABLE IF NOT EXISTS rankings (
    run_id TEXT, ranker_id TEXT, case_id INTEGER, score REAL, ts TEXT,
    PRIMARY KEY (run_id, ranker_id, case_id)
);
```
`migrate()` already runs `executescript(SCHEMA)` and reports `created <table>`; nothing else to add.

`corpus_engine/domain.py` — add after `ShardingSpec`:
```python
@dataclass(frozen=True)
class RankingSpec:
    default: str = "null"
    classifier_version: str = "v1"
    fusion: Mapping[str, float] = None            # type: ignore[assignment]
    reranker: Mapping[str, object] = None         # type: ignore[assignment]
    heldout: str = ""
    heldout_sha256: str | None = None
    bar_ap_delta: float = 0.05

    def __post_init__(self):
        object.__setattr__(self, "fusion", dict(self.fusion or {"lexical_weight": 0.5, "cosine_weight": 0.5}))
        object.__setattr__(self, "reranker", dict(self.reranker or {}))
```
Add `ranking: RankingSpec` to `Domain` (after `sharding`) and in `load_domain`: `ranking=RankingSpec(**cfg.get("ranking", {}))`.

Append to `domains/str-right-to-let/domain.yaml`:
```yaml
ranking:
  default: null                # switched by tools/train_ranker.py (ship rule) and tools/measure_reranker.py (bar)
  classifier_version: v1
  fusion: {lexical_weight: 0.5, cosine_weight: 0.5}
  reranker:
    model: Qwen/Qwen3-Reranker-4B
    revision: main             # replaced by tools/pin_reranker.py before any use; adapters refuse "main"
    query: >
      A judicial opinion about a householder, owner, or lessee letting rooms,
      lodgings, or a dwelling to lodgers, boarders, roomers, or short-term
      occupants, or about regulation of that practice.
  heldout: data/eval/ranker-heldout-v1.jsonl
  heldout_sha256: null         # written by tools/build_ranker_heldout.py
  bar_ap_delta: 0.05
```
(`default: null` in YAML is Python `None`; in `RankingSpec.__post_init__` add `object.__setattr__(self, "default", self.default or "null")` so the string `"null"` is the value.)

Create empty `corpus_engine/ranker/__init__.py`.

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_ranker_schema.py tests/test_domain.py tests/test_store_migrate.py -q` — Expected: pass.
```bash
git add corpus_engine/store.py corpus_engine/domain.py domains/str-right-to-let/domain.yaml corpus_engine/ranker/__init__.py tests/test_ranker_schema.py
git commit -m "ranker: rankings table, RankingSpec, domain ranking config"
```

---

### Task 2: Feature layout and case features

**Files:**
- Create: `corpus_engine/ranker/features.py`, `tests/helpers/ranker_fixture.py`, `tests/test_ranker_features.py`

**Interfaces:**
- Consumes: `load_selectors(domain)` (`corpus_engine.selector.model`), `signals`, `cases`, `chunks`, `embed_meta` (dim).
- Produces:
  - `FeatureLayout(selector_labels: tuple[str,...], vector_labels: tuple[str,...], eras: tuple[str,...], jurisdictions: tuple[str,...], dim: int)` with `.names -> list[str]` and `.size -> int`, `.to_json() / FeatureLayout.from_json(d)`.
  - `feature_layout(domain, selectors, dim) -> FeatureLayout`.
  - `signal_summary(conn, case_ids) -> dict[int, CaseSignals]` where `CaseSignals(selectors: frozenset[str], best_cosine: dict[str, float], best_chunk_id: int | None)` over the **union of runs**.
  - `case_features(conn, case_ids, layout, *, summary=None) -> np.ndarray` float32 `(n, layout.size)` in the order of `case_ids`.
  - `lexical_density(cs: CaseSignals, layout) -> float`, `best_cosine(cs) -> float`.

- [ ] **Step 1: Write the fixture helper and failing tests**

```python
# tests/helpers/ranker_fixture.py
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
```

```python
# tests/test_ranker_features.py
import numpy as np
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.features import (FeatureLayout, best_cosine, case_features, feature_layout,
                                           lexical_density, signal_summary)
from tests.helpers.ranker_fixture import make_ranker_db

def _layout(dom):
    return feature_layout(dom, load_selectors(dom), 512)

def test_layout_names_and_roundtrip():
    dom = load_domain(); lay = _layout(dom)
    assert lay.size == len(lay.names) and lay.dim == 512
    assert lay.names[:1] == [f"sel:{lay.selector_labels[0]}"] and "n_selectors" in lay.names
    assert "pagerank_pct" in lay.names and "pagerank_missing" in lay.names and "ocr_missing" in lay.names
    assert lay.names[-1] == "vec:511" and sum(n.startswith("era:") for n in lay.names) == len(dom.eras)
    assert FeatureLayout.from_json(lay.to_json()) == lay

def test_signal_summary_unions_runs_and_picks_best_chunk(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    cid = conn.execute("SELECT case_id FROM signals WHERE cosine IS NOT NULL GROUP BY case_id ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    s = signal_summary(conn, [cid])[cid]
    top = conn.execute("SELECT chunk_id, cosine FROM signals WHERE case_id=? AND cosine IS NOT NULL ORDER BY cosine DESC, chunk_id LIMIT 1", (cid,)).fetchone()
    assert s.best_chunk_id == top[0] and abs(best_cosine(s) - top[1]) < 1e-9
    assert len(s.selectors) == conn.execute("SELECT count(DISTINCT selector_id||'@v'||selector_version) FROM signals WHERE case_id=?", (cid,)).fetchone()[0]

def test_case_features_shape_missing_indicators_and_text_vector(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain(); lay = _layout(dom)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 40")]
    X = case_features(conn, ids, lay)
    assert X.shape == (40, lay.size) and X.dtype == np.float32 and np.isfinite(X).all()
    vec = X[:, lay.names.index("vec:0"):lay.names.index("vec:0") + 512]
    assert (np.abs(vec).sum(axis=1) > 0).all()                       # every case has a chunk vector
    conn.execute("UPDATE cases SET pagerank_pct=NULL WHERE case_id=?", (ids[0],)); conn.commit()
    X2 = case_features(conn, ids[:1], lay)
    assert X2[0, lay.names.index("pagerank_missing")] == 1.0 and X2[0, lay.names.index("pagerank_pct")] == 0.0
    # a lexical-only case gets its first chunk's vector, not zeros
    lex = conn.execute("SELECT case_id FROM signals GROUP BY case_id HAVING max(cosine) IS NULL LIMIT 1").fetchone()[0]
    X3 = case_features(conn, [lex], lay); assert np.abs(X3[0, -512:]).sum() > 0
    # same inputs twice -> identical bytes
    assert np.array_equal(case_features(conn, ids, lay), X)
```

- [ ] **Step 2: Run to verify failure** — `.venv\Scripts\python -m pytest tests/test_ranker_features.py -q` — Expected: `ModuleNotFoundError: corpus_engine.ranker.features`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/ranker/features.py
"""One feature function for training and scoring (spec §5.1). Features come from the union
of a case's signals across runs; the batch pool is all-runs too."""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np

VECTOR_KINDS = {"embedding", "relevance_feedback"}
LEXICAL_KINDS = {"fts_phrase", "fts_near", "regex"}


@dataclass(frozen=True)
class FeatureLayout:
    selector_labels: tuple[str, ...]
    vector_labels: tuple[str, ...]
    lexical_labels: tuple[str, ...]
    eras: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    dim: int

    @property
    def names(self) -> list[str]:
        return ([f"sel:{s}" for s in self.selector_labels] + ["n_selectors"]
                + [f"cos:{v}" for v in self.vector_labels]
                + ["pagerank_pct", "pagerank_missing", "log_len", "ocr_confidence", "ocr_missing"]
                + [f"era:{e}" for e in self.eras] + [f"jur:{j}" for j in self.jurisdictions]
                + [f"vec:{i}" for i in range(self.dim)])

    @property
    def size(self) -> int:
        return len(self.names)

    def to_json(self) -> dict:
        return {"selector_labels": list(self.selector_labels), "vector_labels": list(self.vector_labels),
                "lexical_labels": list(self.lexical_labels), "eras": list(self.eras),
                "jurisdictions": list(self.jurisdictions), "dim": self.dim}

    @staticmethod
    def from_json(d: dict) -> "FeatureLayout":
        return FeatureLayout(tuple(d["selector_labels"]), tuple(d["vector_labels"]), tuple(d["lexical_labels"]),
                             tuple(d["eras"]), tuple(d["jurisdictions"]), int(d["dim"]))


def feature_layout(domain, selectors, dim: int) -> FeatureLayout:
    labels = tuple(s.label for s in selectors)
    return FeatureLayout(labels, tuple(s.label for s in selectors if s.kind in VECTOR_KINDS),
                         tuple(s.label for s in selectors if s.kind in LEXICAL_KINDS),
                         tuple(domain.eras), tuple(domain.jurisdictions), dim)


@dataclass(frozen=True)
class CaseSignals:
    selectors: frozenset[str]
    best_cosine: dict           # label -> max cosine
    best_chunk_id: int | None   # chunk of the highest-cosine signal (ties: lowest chunk_id)


def _batched(ids, n=500):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def signal_summary(conn, case_ids) -> dict[int, CaseSignals]:
    sel: dict[int, set] = {}; cos: dict[int, dict] = {}; best: dict[int, tuple] = {}
    for chunk in _batched(case_ids):
        ph = ",".join("?" * len(chunk))
        for cid, sid, ver, chunk_id, c in conn.execute(
                f"SELECT case_id, selector_id, selector_version, chunk_id, cosine FROM signals WHERE case_id IN ({ph})", chunk):
            label = f"{sid}@v{ver}"
            sel.setdefault(cid, set()).add(label)
            if c is not None:
                d = cos.setdefault(cid, {})
                d[label] = max(d.get(label, -1.0), float(c))
                key = (-float(c), chunk_id if chunk_id is not None else 1 << 62)
                if cid not in best or key < best[cid][0]:
                    best[cid] = (key, chunk_id)
    return {cid: CaseSignals(frozenset(sel.get(cid, ())), cos.get(cid, {}), best.get(cid, (None, None))[1])
            for cid in case_ids}


def best_cosine(cs: CaseSignals) -> float:
    return max(cs.best_cosine.values()) if cs.best_cosine else 0.0


def lexical_density(cs: CaseSignals, layout: FeatureLayout) -> float:
    if not layout.lexical_labels:
        return 0.0
    return len(cs.selectors & set(layout.lexical_labels)) / len(layout.lexical_labels)


def _chunk_vector(conn, chunk_id: int | None, case_id: int, dim: int) -> np.ndarray:
    row = None
    if chunk_id is not None:
        row = conn.execute("SELECT embedding, embed_scale FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT embedding, embed_scale FROM chunks WHERE case_id=? ORDER BY seq LIMIT 1", (case_id,)).fetchone()
    out = np.zeros(dim, np.float32)
    if row is None or row[0] is None:
        return out
    v = np.frombuffer(row[0], dtype=np.int8).astype(np.float32) * float(row[1] or 1.0)
    out[:min(dim, len(v))] = v[:dim]
    return out


def case_features(conn, case_ids, layout: FeatureLayout, *, summary: dict | None = None) -> np.ndarray:
    ids = [int(c) for c in case_ids]
    summary = summary if summary is not None else signal_summary(conn, ids)
    idx = {n: i for i, n in enumerate(layout.names)}
    X = np.zeros((len(ids), layout.size), np.float32)
    meta: dict[int, tuple] = {}
    for chunk in _batched(ids):
        ph = ",".join("?" * len(chunk))
        for cid, pr, ocr, ln, era, jur in conn.execute(
                f"SELECT case_id, pagerank_pct, ocr_confidence, length(norm_text), era_partition, jurisdiction "
                f"FROM cases WHERE case_id IN ({ph})", chunk):
            meta[cid] = (pr, ocr, ln, era, jur)
    v0 = idx["vec:0"]
    for row, cid in enumerate(ids):
        cs = summary.get(cid) or CaseSignals(frozenset(), {}, None)
        for label in cs.selectors:
            if f"sel:{label}" in idx:
                X[row, idx[f"sel:{label}"]] = 1.0
        X[row, idx["n_selectors"]] = len(cs.selectors)
        for label, c in cs.best_cosine.items():
            if f"cos:{label}" in idx:
                X[row, idx[f"cos:{label}"]] = c
        pr, ocr, ln, era, jur = meta.get(cid, (None, None, None, None, None))
        X[row, idx["pagerank_pct"]] = 0.0 if pr is None else float(pr)
        X[row, idx["pagerank_missing"]] = 1.0 if pr is None else 0.0
        X[row, idx["log_len"]] = math.log1p(ln or 0)
        X[row, idx["ocr_confidence"]] = 0.0 if ocr is None else float(ocr)
        X[row, idx["ocr_missing"]] = 1.0 if ocr is None else 0.0
        if f"era:{era}" in idx:
            X[row, idx[f"era:{era}"]] = 1.0
        if f"jur:{jur}" in idx:
            X[row, idx[f"jur:{jur}"]] = 1.0
        X[row, v0:v0 + layout.dim] = _chunk_vector(conn, cs.best_chunk_id, cid, layout.dim)
    return X
```

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_ranker_features.py -q` — Expected: 3 passed.
```bash
git add corpus_engine/ranker/features.py tests/helpers/ranker_fixture.py tests/test_ranker_features.py
git commit -m "ranker: feature layout and case features shared by training and scoring"
```

---

### Task 3: Ranker port, NullRanker, FusionRanker, load_ranker

**Files:**
- Create: `corpus_engine/ranker/ports.py`, `tests/test_ranker_ports.py`
- Modify: `corpus_engine/ranker/__init__.py`

**Interfaces:**
- Produces: `class Ranker(Protocol): ranker_id: str; def digest(self) -> str; def score(self, conn, run_id, case_ids) -> dict[int, float]`; `round6(x) -> float` (float32 then round 6); `NullRanker` (`ranker_id="null"`, score = number of distinct selectors, a float, so the sort `(-score, case_id)` reproduces the legacy density order); `FusionRanker(layout, lexical_weight, cosine_weight)` (`ranker_id="fusion:v1"`); `load_ranker(domain, conn, ranker_id: str | None) -> Ranker` resolving `"null" | "fusion" | "classifier" | "reranker"` (classifier/reranker imported lazily from Tasks 5/7; until then `load_ranker` raises `NotImplementedError` for them — Task 5 and Task 7 replace those branches).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ranker_ports.py
import math
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.ports import FusionRanker, NullRanker, load_ranker, round6
from tests.helpers.ranker_fixture import make_ranker_db

def test_round6_is_float32_then_six_places():
    assert round6(0.12345678901) == 0.123457 and isinstance(round6(1), float)
    assert round6(0.1 + 1e-9) == round6(0.1)

def test_null_and_fusion_score_every_id_deterministically(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 30")] + [999999999]
    lay = feature_layout(dom, load_selectors(dom), 512)
    for r in (NullRanker(), FusionRanker(lay, 0.5, 0.5)):
        s = r.score(conn, "r", ids)
        assert set(s) == set(ids) and all(isinstance(v, float) and math.isfinite(v) for v in s.values())
        assert s == r.score(conn, "r", ids) and s[999999999] == 0.0
    n = NullRanker().score(conn, "r", ids)
    dens = {cid: len({x[0] for x in conn.execute("SELECT selector_id FROM signals WHERE case_id=?", (cid,))}) for cid in ids}
    assert all(n[c] == float(dens[c]) for c in ids)
    f = FusionRanker(lay, 1.0, 0.0).score(conn, "r", ids)
    assert 0.0 <= max(f.values()) <= 1.0 and NullRanker().digest() == "" and len(FusionRanker(lay, .5, .5).digest()) == 16

def test_load_ranker_resolves_null_and_fusion(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    assert load_ranker(dom, conn, "null").ranker_id == "null"
    assert load_ranker(dom, conn, "fusion").ranker_id == "fusion:v1"
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.ranker.ports`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/ranker/ports.py
from __future__ import annotations
import hashlib, json
from typing import Protocol, Sequence
import numpy as np
from corpus_engine.ranker.features import FeatureLayout, best_cosine, lexical_density, signal_summary


def round6(x) -> float:
    return round(float(np.float32(x)), 6)


class Ranker(Protocol):
    ranker_id: str
    def digest(self) -> str: ...
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]: ...


class NullRanker:
    """Legacy order: distinct-selector density (the batch packer breaks ties by case_id)."""
    ranker_id = "null"
    def digest(self) -> str:
        return ""
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        return {c: float(len({l.split("@v")[0] for l in summ[c].selectors})) for c in ids}


class FusionRanker:
    ranker_id = "fusion:v1"
    def __init__(self, layout: FeatureLayout, lexical_weight: float, cosine_weight: float):
        self.layout, self.wl, self.wc = layout, float(lexical_weight), float(cosine_weight)
    def digest(self) -> str:
        cfg = json.dumps({"wl": self.wl, "wc": self.wc, "lexical": self.layout.lexical_labels}, sort_keys=True)
        return hashlib.sha256(cfg.encode()).hexdigest()[:16]
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        return {c: round6(self.wl * lexical_density(summ[c], self.layout) + self.wc * max(0.0, best_cosine(summ[c])))
                for c in ids}


def _dim(conn) -> int:
    return int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))


def load_ranker(domain, conn, ranker_id: str | None):
    from corpus_engine.selector.model import load_selectors
    from corpus_engine.ranker.features import feature_layout
    rid = (ranker_id or domain.ranking.default or "null").split(":")[0]
    if rid == "null":
        return NullRanker()
    layout = feature_layout(domain, load_selectors(domain), _dim(conn))
    if rid == "fusion":
        f = domain.ranking.fusion
        return FusionRanker(layout, f["lexical_weight"], f["cosine_weight"])
    if rid == "classifier":
        from corpus_engine.ranker.classifier import ClassifierRanker   # Task 5
        return ClassifierRanker.from_domain(domain)
    if rid == "reranker":
        from corpus_engine.ranker.reranker import QwenReranker         # Task 7
        return QwenReranker.from_domain(domain)
    raise ValueError(f"unknown ranker {ranker_id!r}")
```

`corpus_engine/ranker/__init__.py`: `from corpus_engine.ranker.ports import Ranker, NullRanker, FusionRanker, load_ranker, round6` and `__all__`.

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_ranker_ports.py -q` — Expected: 3 passed.
```bash
git add corpus_engine/ranker/ports.py corpus_engine/ranker/__init__.py tests/test_ranker_ports.py
git commit -m "ranker: Ranker port, null and fusion adapters, load_ranker"
```

---

### Task 4: Labels and the frozen held-out slice (tool run once)

**Files:**
- Create: `corpus_engine/ranker/labels.py`, `tools/build_ranker_heldout.py`, `tests/test_ranker_labels.py`, `data/eval/ranker-heldout-v1.jsonl` (generated)
- Modify: `domains/str-right-to-let/domain.yaml` (`heldout_sha256`), `docs/adr/0003-gold-set-frozen-versioned-and-split.md` (amendment)

**Interfaces:**
- Consumes: `open_ledger(domain=domain).view()` — `view.state.order`, `view.state.in_file`, `view.state.records[cid]["relevant"]`, `view.reviewed(cid)`; extraction files `runs/*/extractions*/*.json` (lists of dicts with `case_id`, `relevant`).
- Produces: `Label(case_id: int, label: int, weight: float, reviewed: bool, era: str, jurisdiction: str)`; `labelled_reads(view, extraction_records: Iterable[dict], conn) -> list[Label]` (era/jurisdiction/duplicate status from `cases`; duplicates and cases absent from `cases` dropped); `read_extractions(runs_dir) -> list[dict]`; `build_heldout(labels, *, fraction=0.25, seed=20260904) -> list[Label]`; `write_heldout(path, labels)`, `load_heldout(path) -> list[Label]`, `sha256_file(path) -> str`; `check_heldout(domain, path) -> str` (returns the hash; raises `ValueError` on mismatch with `domain.ranking.heldout_sha256`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ranker_labels.py
import json, pytest
from corpus_engine.ranker.labels import (Label, build_heldout, check_heldout, labelled_reads, load_heldout,
                                         sha256_file, write_heldout)
from tests.helpers.ranker_fixture import make_ranker_db

class _View:
    def __init__(self, rel, reviewed):
        class S: pass
        self.state = S(); self.state.order = list(rel); self.state.in_file = {c: True for c in rel}
        self.state.records = {c: {"relevant": v} for c, v in rel.items()}; self._rev = set(reviewed)
    def reviewed(self, c): return c in self._rev

def test_labelled_reads_rules(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 6")]
    a, b, c, d, e, f = ids
    conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=?", (a, f)); conn.commit()
    view = _View({a: True, b: True, c: False}, reviewed={a})          # c: retracted to not-relevant
    ext = [{"case_id": a, "relevant": True}, {"case_id": b, "relevant": False},   # ledger wins over extraction
           {"case_id": c, "relevant": True}, {"case_id": d, "relevant": False},
           {"case_id": e, "relevant": None}, {"case_id": f, "relevant": False}, {"case_id": 424242, "relevant": False}]
    labs = {l.case_id: l for l in labelled_reads(view, ext, conn)}
    assert labs[a].label == 1 and labs[a].weight == 3 and labs[a].reviewed
    assert labs[b].label == 1 and labs[b].weight == 1
    assert labs[c].label == 0 and labs[d].label == 0 and labs[d].weight == 1
    assert e not in labs and f not in labs and 424242 not in labs
    assert labs[a].era and labs[a].jurisdiction

def test_heldout_stratified_frozen_and_checked(tmp_path):
    labs = [Label(i, i % 2, 1.0, False, "pre-1860" if i < 40 else "1860-1900", "Tex." if i % 3 else "N.Y.") for i in range(100)]
    h1 = build_heldout(labs); h2 = build_heldout(labs)
    assert [l.case_id for l in h1] == [l.case_id for l in h2] and 20 <= len(h1) <= 30
    strata = {(l.era, l.jurisdiction, l.label) for l in labs}
    assert all(any((h.era, h.jurisdiction, h.label) == s for h in h1) for s in strata)
    p = tmp_path / "h.jsonl"; write_heldout(p, h1)
    assert load_heldout(p) == h1 and len(sha256_file(p)) == 64
    class D: pass
    dom = D(); dom.ranking = D(); dom.ranking.heldout_sha256 = sha256_file(p)
    assert check_heldout(dom, p) == dom.ranking.heldout_sha256
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        check_heldout(dom, p)
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.ranker.labels`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/ranker/labels.py
from __future__ import annotations
import glob, hashlib, json, math, random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

HELDOUT_SEED = 20260904
POS_WEIGHT_REVIEWED, POS_WEIGHT_MACHINE, NEG_WEIGHT = 3.0, 1.0, 1.0


@dataclass(frozen=True)
class Label:
    case_id: int; label: int; weight: float; reviewed: bool; era: str; jurisdiction: str


def read_extractions(runs_dir: Path) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(runs_dir / "*" / "extractions*" / "*.json"))):
        try:
            recs = json.loads(Path(f).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out += [r for r in recs if isinstance(r, dict) and r.get("case_id") is not None] if isinstance(recs, list) else []
    return out


def labelled_reads(view, extraction_records: Iterable[dict], conn) -> list[Label]:
    relevant = {int(c) for c in view.state.order if view.state.in_file.get(c) and view.state.records[c].get("relevant")}
    retracted = {int(c) for c in view.state.order if view.state.in_file.get(c) and view.state.records[c].get("relevant") is False}
    neg = set()
    for r in extraction_records:
        cid = int(r["case_id"])
        if r.get("relevant") is False and cid not in relevant:
            neg.add(cid)
    neg |= retracted - relevant
    wanted = sorted(relevant | neg)
    meta: dict[int, tuple] = {}
    for i in range(0, len(wanted), 500):
        chunk = wanted[i:i + 500]; ph = ",".join("?" * len(chunk))
        for cid, era, jur, dup in conn.execute(f"SELECT case_id, era_partition, jurisdiction, is_duplicate_of FROM cases WHERE case_id IN ({ph})", chunk):
            if dup is None:
                meta[cid] = (era, jur)
    out = []
    for cid in wanted:
        if cid not in meta:
            continue
        era, jur = meta[cid]
        if cid in relevant:
            rv = bool(view.reviewed(cid))
            out.append(Label(cid, 1, POS_WEIGHT_REVIEWED if rv else POS_WEIGHT_MACHINE, rv, era, jur))
        else:
            out.append(Label(cid, 0, NEG_WEIGHT, False, era, jur))
    return out


def build_heldout(labels: list[Label], *, fraction: float = 0.25, seed: int = HELDOUT_SEED) -> list[Label]:
    rng = random.Random(seed); strata: dict[tuple, list[Label]] = {}
    for l in sorted(labels, key=lambda l: l.case_id):
        strata.setdefault((l.era, l.jurisdiction, l.label), []).append(l)
    out = []
    for key in sorted(strata):
        members = strata[key]
        k = math.ceil(len(members) * fraction) if len(members) >= 2 else 0
        out += rng.sample(members, k)
    return sorted(out, key=lambda l: l.case_id)


def write_heldout(path: Path, labels: list[Label]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes("".join(json.dumps(asdict(l), sort_keys=True) + "\n" for l in labels).encode("utf-8"))


def load_heldout(path: Path) -> list[Label]:
    return [Label(**json.loads(line)) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_heldout(domain, path: Path) -> str:
    h = sha256_file(path); want = domain.ranking.heldout_sha256
    if want and h != want:
        raise ValueError(f"held-out file {path} sha256 {h[:12]}… does not match domain.yaml {str(want)[:12]}…; never edit it, make a v2")
    return h
```

```python
# tools/build_ranker_heldout.py
"""One-time: freeze the ranker held-out slice (spec §4). Refuses to overwrite an existing file."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                   # noqa: E402
from corpus_engine.domain import load_domain                      # noqa: E402
from corpus_engine.ledger import open_ledger                      # noqa: E402
from corpus_engine.ranker.labels import build_heldout, labelled_reads, read_extractions, sha256_file, write_heldout  # noqa: E402

if __name__ == "__main__":
    dom = load_domain(); out = ROOT / dom.ranking.heldout
    if out.exists():
        sys.exit(f"{out} exists; a new slice is a new version, not an overwrite")
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(), read_extractions(store.paths().runs), conn)
    held = build_heldout(labels); write_heldout(out, held)
    pos = sum(l.label for l in labels); hpos = sum(l.label for l in held)
    print(f"labelled reads: {len(labels)} ({pos} pos / {len(labels) - pos} neg); held-out: {len(held)} ({hpos} pos / {len(held) - hpos} neg)")
    strata = {}
    for l in held:
        strata[(l.era, l.jurisdiction, l.label)] = strata.get((l.era, l.jurisdiction, l.label), 0) + 1
    for k in sorted(strata):
        print(f"  {k[0]:>10} {k[1]:>6} label={k[2]}: {strata[k]}")
    print("sha256:", sha256_file(out)); print("now set ranking.heldout_sha256 in domain.yaml to that value")
```

- [ ] **Step 4: Run tests, then the tool once, then record the hash**

Run: `.venv\Scripts\python -m pytest tests/test_ranker_labels.py -q` — Expected: 2 passed.
Run: `.venv\Scripts\python tools\build_ranker_heldout.py` (live DB read-only; ledger and extractions on disk). Expected: roughly 6,100 labelled reads (≈710 pos), a held-out slice of ≈1,500 with every stratum of size ≥2 represented, and a sha256. Put that hash into `domains/str-right-to-let/domain.yaml` `ranking.heldout_sha256` (replace `null`, quoted string). Append to `docs/adr/0003-gold-set-frozen-versioned-and-split.md`:

```markdown
## Amendment 2026-09-04 — ranker held-out slice

The held-out set this ADR calls for now exists for *ranking* (not recall):
`data/eval/ranker-heldout-v1.jsonl`, a 25% stratified (era × jurisdiction × label)
slice of the labelled reads (ledger-relevant positives, irrelevant-read negatives),
seed 20260904, sha256 `<hash>`, frozen and never trained on. Recall keeps the v1 gold
set; the labelled reads carry negatives, which recall gold does not.
```

- [ ] **Step 5: Commit**
```bash
git add corpus_engine/ranker/labels.py tools/build_ranker_heldout.py tests/test_ranker_labels.py data/eval/ranker-heldout-v1.jsonl domains/str-right-to-let/domain.yaml docs/adr/0003-gold-set-frozen-versioned-and-split.md
git commit -m "ranker: labelled reads, frozen held-out slice v1 (sha256 pinned in domain.yaml), ADR-0003 amendment"
```

---

### Task 5: Evaluation, classifier training, ship rule (tool run once)

**Files:**
- Create: `corpus_engine/ranker/evaluate.py`, `corpus_engine/ranker/classifier.py`, `tools/train_ranker.py`, `tests/test_ranker_classifier.py`, `data/ranker/v1/model.npz`, `data/ranker/v1/manifest.json` (generated)
- Modify: `corpus_engine/ranker/__init__.py`, `domains/str-right-to-let/domain.yaml` (`ranking.default` per ship rule)

**Interfaces:**
- Produces:
  - `evaluate.average_precision(y: np.ndarray, s: np.ndarray, w: np.ndarray | None = None) -> float`; `precision_at(y, s, k) -> float`; `evaluate_scores(labels: list[Label], scores: dict[int, float]) -> dict` with keys `ap_all, ap_reviewed, p50_all, p200_all, n_all, n_reviewed, per_cell: {cell: {ap, n, p50}}`; `compare(a: dict, b: dict) -> dict` (deltas).
  - `ClassifierRanker(model_dir: Path)` with `ranker_id = "classifier:<version>"`, `.layout`, `.from_domain(domain)`, `.digest()` = sha256(model.npz)[:16], `.score(conn, run_id, case_ids)`; refuses (`ValueError` naming the first differing selector/field) if `feature_layout(domain, load_selectors(domain), dim)` ≠ the manifest layout.
  - `train(conn, domain, labels: list[Label], heldout: list[Label], *, version: str, out_dir: Path, commit: str, layout=None) -> dict` (the manifest): standardize with training statistics, `LogisticRegression(penalty="l2", class_weight="balanced", max_iter=2000)`, `C` by 5-fold CV over `(0.01, 0.03, 0.1, 0.3, 1, 3)` on AP inside the training set, sample weights from labels; writes `model.npz` (`coef`, `intercept`, `mean`, `scale`) and `manifest.json`; refuses on held-out overlap.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ranker_classifier.py
import json, numpy as np, pytest
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.classifier import ClassifierRanker, train
from corpus_engine.ranker.evaluate import average_precision, evaluate_scores, precision_at
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.labels import Label
from tests.helpers.ranker_fixture import make_ranker_db

def test_metrics():
    y = np.array([1, 0, 1, 0]); s = np.array([0.9, 0.8, 0.7, 0.1])
    assert abs(average_precision(y, s) - (1.0 + 2 / 3) / 2) < 1e-9 and precision_at(y, s, 2) == 0.5
    assert average_precision(np.zeros(3), np.arange(3)) == 0.0

def _synthetic_labels(conn):
    # positives: cases with >= 2 distinct selectors; negatives: the rest (a learnable rule)
    rows = conn.execute("SELECT c.case_id, c.era_partition, c.jurisdiction, count(DISTINCT s.selector_id) FROM cases c JOIN signals s ON s.case_id=c.case_id WHERE c.is_duplicate_of IS NULL GROUP BY 1").fetchall()
    return [Label(cid, int(n >= 2), 3.0 if n >= 3 else 1.0, n >= 3, era, jur) for cid, era, jur, n in rows]

def test_train_beats_chance_scores_and_refuses_layout_drift(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    labels = _synthetic_labels(conn); held = labels[::4]; train_set = [l for l in labels if l not in set(held)]
    out = tmp_path / "v9"
    man = train(conn, dom, train_set, held, version="v9", out_dir=out, commit="deadbeef")
    assert (out / "model.npz").exists() and man["ranker_id"] == "classifier:v9" and man["cv_C"] in (0.01, 0.03, 0.1, 0.3, 1, 3)
    base = sum(l.label for l in held) / len(held)
    assert man["metrics"]["classifier"]["ap_all"] > base + 0.1
    r = ClassifierRanker(out); s = r.score(conn, "run", [l.case_id for l in held])
    ev = evaluate_scores(held, s); assert abs(ev["ap_all"] - man["metrics"]["classifier"]["ap_all"]) < 1e-6
    assert s == r.score(conn, "run", [l.case_id for l in held]) and len(r.digest()) == 16
    with pytest.raises(ValueError, match="overlap"):
        train(conn, dom, train_set + held[:1], held, version="v9b", out_dir=tmp_path / "v9b", commit="x")
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8")); m["layout"]["selector_labels"][0] = "ghost-1@v1"
    (out / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="ghost-1@v1"):
        ClassifierRanker(out).check_layout(feature_layout(dom, load_selectors(dom), 512))
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.ranker.classifier`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/ranker/evaluate.py
from __future__ import annotations
import numpy as np


def average_precision(y, s, w=None) -> float:
    y = np.asarray(y, float); s = np.asarray(s, float); w = np.ones_like(y) if w is None else np.asarray(w, float)
    if y.sum() == 0:
        return 0.0
    order = np.lexsort((np.arange(len(s)), -s))          # score desc, stable
    y, w = y[order], w[order]
    tp = np.cumsum(y * w); n = np.cumsum(w)
    return float((tp / n * y * w).sum() / (y * w).sum())


def precision_at(y, s, k: int) -> float:
    y = np.asarray(y, float); s = np.asarray(s, float)
    order = np.lexsort((np.arange(len(s)), -s))[:k]
    return float(y[order].mean()) if len(order) else 0.0


def evaluate_scores(labels, scores: dict) -> dict:
    y = np.array([l.label for l in labels]); s = np.array([scores[l.case_id] for l in labels]); w = np.array([l.weight for l in labels])
    rv = np.array([l.reviewed or l.label == 0 for l in labels])       # "human-reviewed view" = reviewed positives + all negatives
    out = {"n_all": int(len(labels)), "ap_all": average_precision(y, s), "p50_all": precision_at(y, s, 50), "p200_all": precision_at(y, s, 200),
           "n_reviewed": int(rv.sum()), "ap_reviewed": average_precision(y[rv], s[rv]) if rv.any() else 0.0, "per_cell": {}}
    cells = sorted({(l.era, l.jurisdiction) for l in labels})
    for era, jur in cells:
        m = np.array([(l.era, l.jurisdiction) == (era, jur) for l in labels])
        out["per_cell"][f"{era}|{jur}"] = {"n": int(m.sum()), "ap": average_precision(y[m], s[m]), "p50": precision_at(y[m], s[m], 50)}
    return out


def compare(a: dict, b: dict) -> dict:
    return {k: round(b[k] - a[k], 6) for k in ("ap_all", "ap_reviewed", "p50_all", "p200_all")}
```

```python
# corpus_engine/ranker/classifier.py
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from typing import Sequence
import numpy as np
from corpus_engine.ranker.evaluate import average_precision, evaluate_scores
from corpus_engine.ranker.features import FeatureLayout, case_features, feature_layout
from corpus_engine.ranker.ports import FusionRanker, round6

MODEL_FILE, MANIFEST_FILE = "model.npz", "manifest.json"
C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0)


class ClassifierRanker:
    def __init__(self, model_dir: Path):
        self.dir = Path(model_dir)
        self.manifest = json.loads((self.dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        z = np.load(self.dir / MODEL_FILE)
        self.coef, self.intercept, self.mean, self.scale = z["coef"], float(z["intercept"]), z["mean"], z["scale"]
        self.layout = FeatureLayout.from_json(self.manifest["layout"])
        self.ranker_id = self.manifest["ranker_id"]

    @classmethod
    def from_domain(cls, domain):
        from corpus_engine.store import paths
        return cls(paths().root / "data" / "ranker" / domain.ranking.classifier_version)

    def digest(self) -> str:
        return hashlib.sha256((self.dir / MODEL_FILE).read_bytes()).hexdigest()[:16]

    def check_layout(self, current: FeatureLayout) -> None:
        if current != self.layout:
            a, b = self.layout.names, current.names
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    raise ValueError(f"model layout differs from the current selectors/domain at {i}: model {x!r} vs current {y!r}; retrain")
            raise ValueError(f"model layout size {len(a)} vs current {len(b)}; retrain")

    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        X = (case_features(conn, ids, self.layout) - self.mean) / self.scale
        logits = X @ self.coef + self.intercept
        return {c: round6(1.0 / (1.0 + np.exp(-l))) for c, l in zip(ids, logits)}


def train(conn, domain, labels, heldout, *, version: str, out_dir: Path, commit: str, layout: FeatureLayout | None = None) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from corpus_engine.selector.model import load_selectors
    held_ids = {l.case_id for l in heldout}
    overlap = [l.case_id for l in labels if l.case_id in held_ids]
    if overlap:
        raise ValueError(f"training set overlaps the held-out slice ({len(overlap)} ids, e.g. {overlap[:3]})")
    dim = int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))
    layout = layout or feature_layout(domain, load_selectors(domain), dim)
    ids = [l.case_id for l in labels]; y = np.array([l.label for l in labels]); w = np.array([l.weight for l in labels])
    X = case_features(conn, ids, layout)
    mean = X.mean(axis=0); scale = X.std(axis=0); scale[scale == 0] = 1.0
    Xs = (X - mean) / scale
    best_C, best_ap = None, -1.0
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    for C in C_GRID:
        aps = []
        for tr, va in skf.split(Xs, y):
            m = LogisticRegression(penalty="l2", C=C, class_weight="balanced", max_iter=2000).fit(Xs[tr], y[tr], sample_weight=w[tr])
            aps.append(average_precision(y[va], m.decision_function(Xs[va])))
        if np.mean(aps) > best_ap:
            best_C, best_ap = C, float(np.mean(aps))
    model = LogisticRegression(penalty="l2", C=best_C, class_weight="balanced", max_iter=2000).fit(Xs, y, sample_weight=w)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(out_dir / MODEL_FILE, coef=model.coef_[0].astype(np.float32), intercept=np.float32(model.intercept_[0]),
             mean=mean.astype(np.float32), scale=scale.astype(np.float32))
    manifest = {"ranker_id": f"classifier:{version}", "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": commit,
                "layout": layout.to_json(), "cv_C": best_C, "cv_ap": best_ap,
                "train": {"n_pos": int(y.sum()), "n_neg": int((1 - y).sum()),
                          "sha256_ids": hashlib.sha256(",".join(map(str, sorted(ids))).encode()).hexdigest()},
                "heldout": {"n": len(heldout)}, "metrics": {}}
    (out_dir / MANIFEST_FILE).write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    ranker = ClassifierRanker(out_dir); hid = [l.case_id for l in heldout]
    f = domain.ranking.fusion
    manifest["metrics"] = {"classifier": evaluate_scores(heldout, ranker.score(conn, "train", hid)),
                           "fusion": evaluate_scores(heldout, FusionRanker(layout, f["lexical_weight"], f["cosine_weight"]).score(conn, "train", hid))}
    (out_dir / MANIFEST_FILE).write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    return manifest
```

`corpus_engine/ranker/__init__.py`: also export `ClassifierRanker`.

```python
# tools/train_ranker.py
"""Train classifier:<version> on the labelled reads minus the held-out slice; apply the ship rule (spec §5.4)."""
import argparse, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                   # noqa: E402
from corpus_engine.domain import load_domain                                      # noqa: E402
from corpus_engine.ledger import open_ledger                                      # noqa: E402
from corpus_engine.ranker.classifier import train                                 # noqa: E402
from corpus_engine.ranker.labels import check_heldout, labelled_reads, load_heldout, read_extractions  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--version", default=None); a = ap.parse_args()
    dom = load_domain(); version = a.version or dom.ranking.classifier_version
    hpath = ROOT / dom.ranking.heldout; check_heldout(dom, hpath); held = load_heldout(hpath)
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(), read_extractions(store.paths().runs), conn)
    held_ids = {l.case_id for l in held}; train_set = [l for l in labels if l.case_id not in held_ids]
    held_present = [l for l in held if l.case_id in {x.case_id for x in labels}]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    man = train(conn, dom, train_set, held_present, version=version, out_dir=ROOT / "data" / "ranker" / version, commit=commit)
    c, f = man["metrics"]["classifier"], man["metrics"]["fusion"]
    print(f"train {man['train']} cv_C={man['cv_C']} cv_ap={man['cv_ap']:.4f}")
    print(f"held-out n={c['n_all']} (reviewed view n={c['n_reviewed']})")
    print(f"  classifier: ap_all={c['ap_all']:.4f} ap_reviewed={c['ap_reviewed']:.4f} p50={c['p50_all']:.3f} p200={c['p200_all']:.3f}")
    print(f"  fusion:     ap_all={f['ap_all']:.4f} ap_reviewed={f['ap_reviewed']:.4f} p50={f['p50_all']:.3f} p200={f['p200_all']:.3f}")
    ships = c["ap_all"] > f["ap_all"] and c["ap_reviewed"] > f["ap_reviewed"]
    print("SHIP RULE:", "classifier becomes the default" if ships else "fusion stays the default (classifier did not beat it on both views)")
    print(f"set ranking.default to {'classifier' if ships else 'fusion'} in domain.yaml")
```

- [ ] **Step 4: Run tests, then train v1 once, then apply the ship rule**

Run: `.venv\Scripts\python -m pytest tests/test_ranker_classifier.py -q` — Expected: 2 passed.
Run: `.venv\Scripts\python tools\train_ranker.py` (live DB read-only; ~6,100 × 1,100 features; a minute or two). Record the printed metrics. Set `ranking.default` in `domain.yaml` to `classifier` if the ship rule says so, else `fusion`. Commit `data/ranker/v1/` (model.npz is ~10 KB).

- [ ] **Step 5: Commit**
```bash
git add corpus_engine/ranker/evaluate.py corpus_engine/ranker/classifier.py corpus_engine/ranker/__init__.py tools/train_ranker.py tests/test_ranker_classifier.py data/ranker/v1 domains/str-right-to-let/domain.yaml
git commit -m "ranker: evaluation, logistic-regression classifier v1 trained and measured against fusion; ship rule applied"
```

---

### Task 6: Packing hook, rankings persistence, manifest, `pipeline/rank.py`, shard flags

**Files:**
- Modify: `corpus_engine/selector/packing.py`, `corpus_engine/selector/engine.py`, `pipeline/shard.py`
- Create: `pipeline/rank.py`, `tests/test_ranker_packing.py`, `tests/test_rank_cli.py`

**Interfaces:**
- Produces: `build_batches(conn, run_id, *, gold_ids, exclude_ids, batch_size=18, ranker=None, ts=None) -> list[dict]` — with a ranker: scores all pool cases once via `ranker.score`, writes `rankings` rows (`INSERT OR REPLACE`, one commit) via `persist_rankings(conn, run_id, ranker_id, scores, ts)`, sorts within cell by `(-score, case_id)`, orders batches by `(-mean_score, cell_key)` after the gold bump (`(-_gold, -mean_score, cell_key)`), adds `"ranker_id"` to each batch and `"rank_score"` to each case. `pack_batches(..., ranker=None, ts=None)` passes through. `engine.shard(..., ranker=None)` passes the ranker to packing and puts `"ranker": {"ranker_id", "digest"}` in the manifest. `pipeline/shard.py`: `--ranker <id>` (default: domain), `--no-rank`. `pipeline/rank.py --run-id <run> [--ranker <id>] [--out-dir <dir>]`: loads the ranker, rebuilds the exclusion set and gold ids exactly as `shard()` does, calls `pack_batches` into `runs/<run>/batches`, rewrites `runs/<run>/shard-manifest.json`'s `ranker` field (keeps everything else), prints counts. It never touches `signals`/`coverage_v2`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ranker_packing.py
import json
from corpus_engine.selector.packing import build_batches, pack_batches
from corpus_engine.ranker.ports import NullRanker
from tests.helpers.ranker_fixture import make_ranker_db

class _Const:
    ranker_id = "const:test"
    def __init__(self, table): self.t = table
    def digest(self): return "abc"
    def score(self, conn, run_id, ids): return {i: self.t.get(i, 0.0) for i in ids}

def test_null_ranker_reproduces_legacy_order_and_writes_rankings(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    legacy = build_batches(conn, "r", gold_ids=set(), exclude_ids=set())
    ranked = build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=NullRanker(), ts="t")
    assert [[c["case_id"] for c in b["cases"]] for b in ranked] == [[c["case_id"] for c in b["cases"]] for b in legacy]
    assert all(b["ranker_id"] == "null" for b in ranked) and all("rank_score" in c for b in ranked for c in b["cases"])
    n = conn.execute("SELECT count(*) FROM rankings WHERE run_id='r' AND ranker_id='null'").fetchone()[0]
    assert n == sum(len(b["cases"]) for b in legacy)
    assert "ranker_id" not in legacy[0] and "rank_score" not in legacy[0]["cases"][0]

def test_scores_order_cells_and_batches_with_six_place_rounding(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    pool = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id")]
    table = {cid: 0.5 for cid in pool}; table[pool[0]] = 0.5 + 1e-9; table[pool[-1]] = 0.9      # tie after rounding
    out = build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=_Const(table), ts="t")
    cell = next(b for b in out if any(c["case_id"] == pool[-1] for c in b["cases"]))
    assert cell["cases"][0]["case_id"] == pool[-1] and cell["cases"][0]["rank_score"] == 0.9
    same = [c for b in out for c in b["cases"] if c["rank_score"] == 0.5]
    assert any(c["case_id"] == pool[0] for c in same)                         # rounding collapsed the 1e-9 lead
    means = [sum(c["rank_score"] for c in b["cases"]) / len(b["cases"]) for b in out]
    assert means == sorted(means, reverse=True)
    assert out == build_batches(conn, "r", gold_ids=set(), exclude_ids=set(), ranker=_Const(table), ts="t")

def test_pack_writes_ranker_id_and_leaves_signals_untouched(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    before = conn.execute("SELECT count(*), sum(signal_id) FROM signals").fetchone()
    n = pack_batches(conn, "r", tmp_path / "b", gold_ids=set(), exclude_ids=set(), ranker=NullRanker(), ts="t")
    b1 = json.loads((tmp_path / "b" / "batch-001.json").read_text(encoding="utf-8"))
    assert n > 0 and b1["ranker_id"] == "null" and before == conn.execute("SELECT count(*), sum(signal_id) FROM signals").fetchone()
```

```python
# tests/test_rank_cli.py
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import rank as rank_cli
from tests.helpers.ranker_fixture import make_ranker_db

def test_rank_repacks_existing_run_without_touching_signals(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    run_dir = tmp_path / "runs" / "r"; (run_dir / "batches").mkdir(parents=True)
    (run_dir / "shard-manifest.json").write_text(json.dumps({"run_id": "r", "engine_version": "v2"}), encoding="utf-8")
    before = conn.execute("SELECT count(*) FROM signals").fetchone()[0]
    rep = rank_cli.rerank(conn, "r", ranker_id="null", runs_dir=tmp_path / "runs", ledger_dir=tmp_path / "ledger", log=lambda *_: None)
    assert rep["batches"] > 0 and (run_dir / "batches" / "batch-001.json").exists()
    m = json.loads((run_dir / "shard-manifest.json").read_text(encoding="utf-8"))
    assert m["ranker"]["ranker_id"] == "null" and m["engine_version"] == "v2"
    assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == before
```

- [ ] **Step 2: Run to verify failure** — Expected: `TypeError: build_batches() got an unexpected keyword argument 'ranker'` and `ModuleNotFoundError: rank`.

- [ ] **Step 3: Implement**

`corpus_engine/selector/packing.py` — replace the body of `build_batches` from `pending = []` on, and add `persist_rankings`:

```python
def persist_rankings(conn, run_id: str, ranker_id: str, scores: dict[int, float], ts: str) -> None:
    conn.executemany("INSERT OR REPLACE INTO rankings (run_id, ranker_id, case_id, score, ts) VALUES (?,?,?,?,?)",
                     [(run_id, ranker_id, cid, float(s), ts) for cid, s in sorted(scores.items())])
    conn.commit()


def build_batches(conn: sqlite3.Connection, run_id: str, *,
                  gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18,
                  ranker=None, ts: str | None = None) -> list[dict]:
    ...  # unchanged up to and including the exclusion filtering of `groups`
    scores: dict[int, float] | None = None
    if ranker is not None:
        from corpus_engine.ranker.ports import round6
        pool = [e["case_id"] for cases in groups.values() for e in cases]
        scores = {cid: round6(s) for cid, s in ranker.score(conn, run_id, pool).items()}
        persist_rankings(conn, run_id, ranker.ranker_id, scores, ts or time.strftime("%Y-%m-%dT%H:%M:%S"))
    pending = []
    for (era, jur), cases in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if scores is None:
            cases.sort(key=lambda e: (-len({s["selector_id"] for s in e["signals"]}), e["case_id"]))
        else:
            cases.sort(key=lambda e: (-scores[e["case_id"]], e["case_id"]))
            for e in cases:
                e["rank_score"] = scores[e["case_id"]]
        for i in range(0, len(cases), batch_size):
            chunk = cases[i:i + batch_size]
            b = {"era_partition": era, "jurisdiction": jur, "cases": chunk,
                 "_gold": sum(1 for e in chunk if e["case_id"] in gold_ids),
                 "_density": max(len({s["selector_id"] for s in e["signals"]}) for e in chunk)}
            if scores is not None:
                b["ranker_id"] = ranker.ranker_id
                b["_mean"] = sum(scores[e["case_id"]] for e in chunk) / len(chunk)
            pending.append(b)
    if scores is None:
        pending.sort(key=lambda b: (-b["_gold"], -b["_density"]))
    else:
        pending.sort(key=lambda b: (-b["_gold"], -b["_mean"], f"{b['era_partition']}|{b['jurisdiction']}"))
    for n, batch in enumerate(pending, 1):
        batch.pop("_gold"), batch.pop("_density"), batch.pop("_mean", None)
        batch["batch_id"] = f"{run_id}-batch-{n:03d}"
    return pending
```
(`import time` at the top.) The `ranker is None` path must remain byte-identical: the `rank_score` key is added only inside the `else`, `ranker_id` only when scored, and the legacy sort keys are untouched. `pack_batches(..., ranker=None, ts=None)` forwards both.

`corpus_engine/selector/engine.py`: `shard(..., ranker=None)`; pass `ranker=ranker, ts=ts` to both `build_batches` (dry run) and `pack_batches`; add to the manifest `"ranker": {"ranker_id": ranker.ranker_id, "digest": ranker.digest()} if ranker else None`.

`pipeline/shard.py`: `ap.add_argument("--ranker", default=None)`, `ap.add_argument("--no-rank", action="store_true")`; after the plan and before `shard(...)`: `ranker = None if args.no_rank else load_ranker(domain, conn, args.ranker)` (import from `corpus_engine.ranker`); pass `ranker=ranker`; print `f"ranker: {ranker.ranker_id if ranker else 'none (legacy order)'}"`.

```python
# pipeline/rank.py
"""Re-score and re-pack an existing run's batches with a ranker. Never touches signals or coverage."""
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                            # noqa: E402
from corpus_engine.domain import load_domain                               # noqa: E402
from corpus_engine.ranker import load_ranker                               # noqa: E402
from corpus_engine.selector.engine import _gold_ids, already_read_ids      # noqa: E402
from corpus_engine.selector.packing import pack_batches                    # noqa: E402


def rerank(conn, run_id: str, *, ranker_id: str | None, runs_dir: Path, ledger_dir: Path, domain=None, out_dir: Path | None = None, log=print) -> dict:
    domain = domain or load_domain()
    ranker = load_ranker(domain, conn, ranker_id)
    exclude = already_read_ids(runs_dir, ledger_dir); gold = _gold_ids(domain)
    out = out_dir or (runs_dir / run_id / "batches"); ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude, batch_size=domain.sharding.batch_size, ranker=ranker, ts=ts)
    mp = out.parent / "shard-manifest.json"
    manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"run_id": run_id}
    manifest["ranker"] = {"ranker_id": ranker.ranker_id, "digest": ranker.digest(), "reranked_at": ts}
    mp.write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    cases = sum(len(json.loads(f.read_text(encoding="utf-8"))["cases"]) for f in out.glob("batch-*.json"))
    log(f"{ranker.ranker_id}: {n} batches, {cases} cases -> {out} ({len(exclude)} already-read excluded)")
    return {"ranker_id": ranker.ranker_id, "batches": n, "cases": cases, "excluded": len(exclude)}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--run-id", required=True); ap.add_argument("--ranker", default=None); ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(); conn = store.connect(); store.ensure_schema(conn); store.migrate(conn)
    p = store.paths()
    rerank(conn, a.run_id, ranker_id=a.ranker, runs_dir=p.runs, ledger_dir=p.ledger, out_dir=Path(a.out_dir) if a.out_dir else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
(`_gold_ids` and `already_read_ids` exist in `corpus_engine/selector/engine.py`; if `_gold_ids` is private, expose it as `gold_ids` and keep the alias.)

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv\Scripts\python -m pytest tests/test_ranker_packing.py tests/test_rank_cli.py tests/test_packing_char.py tests/test_selector_engine.py -q` — Expected: pass (the packing golden proves the legacy path is byte-identical).
```bash
git add corpus_engine/selector/packing.py corpus_engine/selector/engine.py pipeline/shard.py pipeline/rank.py tests/test_ranker_packing.py tests/test_rank_cli.py
git commit -m "ranking hook in build_batches with rankings persistence; shard --ranker/--no-rank; pipeline/rank.py re-pack"
```

---

### Task 7: Reranker adapter, pin, held-out measurement (tool run once)

**Files:**
- Create: `corpus_engine/ranker/reranker.py`, `tools/pin_reranker.py`, `tools/measure_reranker.py`, `tests/test_ranker_reranker.py`, `data/ranker/reranker-<rev7>/manifest.json` (generated)
- Modify: `corpus_engine/ranker/__init__.py`, `domains/str-right-to-let/domain.yaml` (`reranker.revision`, maybe `ranking.default`)

**Interfaces:**
- Produces: `QwenReranker(model: str, revision: str, query: str, *, batch: int = 8, encoder=None)` with `ranker_id = f"qwen3-reranker-4b:{revision[:7]}"`, `.from_domain(domain)`, `.digest()` = sha256(model+revision+query)[:16], `.score(conn, run_id, case_ids)`: builds `(query, chunk_text)` pairs where `chunk_text = substr(norm_text, char_start+1, char_end-char_start)` of the case's best chunk (from `signal_summary`; first chunk if none), calls `encoder.predict(pairs, batch_size=batch)` → logits, returns `round6` per case. `encoder` injectable (tests pass a fake); the real one is `sentence_transformers.CrossEncoder(model, revision=revision, device="cuda", trust_remote_code=True)` loaded lazily on first `score`. Refuses to construct with `revision == "main"` (`ValueError`) and refuses to load the real encoder if `gpu_has_resident_model()` (`torch.cuda.memory_allocated() > 6 GiB`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ranker_reranker.py
import pytest
from corpus_engine.ranker.reranker import QwenReranker
from tests.helpers.ranker_fixture import make_ranker_db

class _Fake:
    def __init__(self): self.calls = []
    def predict(self, pairs, batch_size=8):
        self.calls.append((len(pairs), batch_size)); return [len(t) / 1000.0 for _, t in pairs]

def test_reranker_pairs_best_chunk_text_and_scores_by_case(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 12")]
    fake = _Fake(); r = QwenReranker("Qwen/Qwen3-Reranker-4B", "0123456789abcdef", "letting query", batch=4, encoder=fake)
    s = r.score(conn, "run", ids)
    assert set(s) == set(ids) and fake.calls == [(12, 4)] and r.ranker_id == "qwen3-reranker-4b:0123456" and len(r.digest()) == 16
    assert all(v > 0 for v in s.values()) and s == r.score(conn, "run", ids)
    with pytest.raises(ValueError, match="main"):
        QwenReranker("Qwen/Qwen3-Reranker-4B", "main", "q", encoder=fake)
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.ranker.reranker`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/ranker/reranker.py
from __future__ import annotations
import hashlib
from typing import Sequence
from corpus_engine.ranker.features import signal_summary
from corpus_engine.ranker.ports import round6


def gpu_has_resident_model(threshold_bytes: int = 6 << 30) -> bool:
    try:
        import torch
        return torch.cuda.is_available() and torch.cuda.memory_allocated() > threshold_bytes
    except Exception:            # noqa: BLE001 — no torch/cuda means nothing resident
        return False


class QwenReranker:
    def __init__(self, model: str, revision: str, query: str, *, batch: int = 8, encoder=None):
        if not revision or revision == "main":
            raise ValueError("reranker revision must be a pinned commit sha, not 'main' (run tools/pin_reranker.py)")
        self.model, self.revision, self.query, self.batch = model, revision, query, int(batch)
        self._encoder = encoder
        self.ranker_id = f"qwen3-reranker-4b:{revision[:7]}"

    @classmethod
    def from_domain(cls, domain):
        r = domain.ranking.reranker
        return cls(r["model"], str(r.get("revision", "")), r["query"], batch=int(r.get("batch", 8)))

    def digest(self) -> str:
        return hashlib.sha256(f"{self.model}@{self.revision}|{self.query}".encode()).hexdigest()[:16]

    def _enc(self):
        if self._encoder is None:
            if gpu_has_resident_model():
                raise RuntimeError("another model is resident on the GPU; run the reranker in its own process")
            from sentence_transformers import CrossEncoder
            self._encoder = CrossEncoder(self.model, revision=self.revision, device="cuda", trust_remote_code=True, max_length=1024)
        return self._encoder

    def _chunk_text(self, conn, case_id: int, chunk_id: int | None) -> str:
        row = conn.execute("SELECT char_start, char_end FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone() if chunk_id is not None else None
        if row is None:
            row = conn.execute("SELECT char_start, char_end FROM chunks WHERE case_id=? ORDER BY seq LIMIT 1", (case_id,)).fetchone()
        if row is None:
            return conn.execute("SELECT substr(norm_text, 1, 2000) FROM cases WHERE case_id=?", (case_id,)).fetchone()[0] or ""
        return conn.execute("SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?", (row[0] + 1, row[1] - row[0], case_id)).fetchone()[0] or ""

    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        pairs = [(self.query, self._chunk_text(conn, cid, summ[cid].best_chunk_id)) for cid in ids]
        logits = self._enc().predict(pairs, batch_size=self.batch)
        return {cid: round6(float(l)) for cid, l in zip(ids, logits)}
```

```python
# tools/pin_reranker.py
"""Resolve the reranker's revision to a commit sha and write it into domain.yaml (never 'main')."""
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from huggingface_hub import HfApi                                       # noqa: E402
from corpus_engine.domain import load_domain                            # noqa: E402
if __name__ == "__main__":
    dom = load_domain(); r = dom.ranking.reranker
    sha = HfApi().model_info(r["model"], revision=r.get("revision") if r.get("revision") not in (None, "main") else None).sha
    p = ROOT / "domains" / dom.name / "domain.yaml"; s = p.read_text(encoding="utf-8")
    s2 = re.sub(r"(reranker:\n(?:.*\n)*?\s+revision:\s*)\S+", lambda m: m.group(1) + sha, s, count=1)
    assert s2 != s or sha in s, "revision line not found"
    p.write_text(s2, encoding="utf-8", newline="\n"); print("pinned", r["model"], "->", sha)
```

```python
# tools/measure_reranker.py
"""Held-out measurement of the reranker against the shipped default (spec §6). Applies the bar."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                        # noqa: E402
from corpus_engine.domain import load_domain                                           # noqa: E402
from corpus_engine.ranker import load_ranker                                           # noqa: E402
from corpus_engine.ranker.evaluate import compare, evaluate_scores                     # noqa: E402
from corpus_engine.ranker.labels import check_heldout, load_heldout                    # noqa: E402
from corpus_engine.ranker.reranker import QwenReranker                                 # noqa: E402
if __name__ == "__main__":
    dom = load_domain(); hpath = ROOT / dom.ranking.heldout; check_heldout(dom, hpath); held = load_heldout(hpath)
    conn = store.connect(); ids = [l.case_id for l in held]
    base = load_ranker(dom, conn, dom.ranking.default); rr = QwenReranker.from_domain(dom)
    t0 = time.time(); sr = rr.score(conn, "heldout", ids); secs = time.time() - t0
    mb = evaluate_scores(held, base.score(conn, "heldout", ids)); mr = evaluate_scores(held, sr); d = compare(mb, mr)
    bar = dom.ranking.bar_ap_delta
    clears = d["ap_all"] >= bar and d["ap_reviewed"] >= bar
    out = ROOT / "data" / "ranker" / f"reranker-{rr.revision[:7]}"; out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_bytes(json.dumps({"ranker_id": rr.ranker_id, "digest": rr.digest(), "model": rr.model, "revision": rr.revision,
        "query": rr.query, "heldout_n": len(held), "seconds": round(secs, 1), "baseline": base.ranker_id,
        "metrics": {"baseline": mb, "reranker": mr, "delta": d}, "bar_ap_delta": bar, "clears_bar": clears}, indent=1, sort_keys=True).encode("utf-8"))
    print(f"baseline {base.ranker_id}: ap_all={mb['ap_all']:.4f} ap_reviewed={mb['ap_reviewed']:.4f}")
    print(f"reranker {rr.ranker_id}: ap_all={mr['ap_all']:.4f} ap_reviewed={mr['ap_reviewed']:.4f} ({len(held)} pairs in {secs:.0f}s)")
    print("delta", d, "| BAR", bar, "->", "CLEARS: set ranking.default to reranker" if clears else "does not clear: default unchanged")
```

`corpus_engine/ranker/__init__.py`: export `QwenReranker`.

- [ ] **Step 4: Run tests, pin, measure (once), apply the bar**

Run: `.venv\Scripts\python -m pytest tests/test_ranker_reranker.py -q` — Expected: 1 passed.
Run: `.venv\Scripts\python tools\pin_reranker.py` → `domain.yaml` now carries a sha. Run: `.venv\Scripts\python tools\measure_reranker.py` (downloads ~8 GB once; ~1,500 pairs; the GPU must be otherwise idle — nothing else in this plan holds a model). If `CrossEncoder` cannot load Qwen3-Reranker-4B (it is a causal-LM reranker; its model card documents a yes/no-logit recipe), implement `_enc()` with `transformers` per the model card behind the same `predict(pairs, batch_size)` shape and note it in the report — the adapter's interface does not change. Set `ranking.default: reranker` only if the printed verdict says CLEARS.

- [ ] **Step 5: Commit**
```bash
git add corpus_engine/ranker/reranker.py corpus_engine/ranker/__init__.py tools/pin_reranker.py tools/measure_reranker.py tests/test_ranker_reranker.py data/ranker/reranker-* domains/str-right-to-let/domain.yaml
git commit -m "ranker: Qwen3 reranker adapter (pinned), held-out measurement against the shipped default; bar applied"
```

---

### Task 8: Re-pack cycle 004, ranking report, spec/handoff updates

**Files:**
- Create: `reports/ranking-cycle-004.md`
- Modify: `reports/handoff-cycle-004.md` (item 11), `docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md` (§4 amendment: features from the union of runs), `README.md` (one line: `pipeline/rank.py`)

- [ ] **Step 1: Re-pack cycle 004 with the shipped default**

Run: `.venv\Scripts\python pipeline\rank.py --run-id cycle-004-shard-01` — Expected: 1,845 batches (same count as the shard; the pool is unchanged), `runs/cycle-004-shard-01/shard-manifest.json` gains `ranker`, every batch carries `ranker_id`. Then verify read-only:
```
.venv\Scripts\python -c "import sqlite3;c=sqlite3.connect('file:data/db/corpus.db?mode=ro',uri=True);print(c.execute(\"SELECT count(*) FROM signals WHERE run_id='cycle-004-shard-01'\").fetchone(), c.execute('SELECT count(*) FROM coverage_v2').fetchone(), c.execute('SELECT ranker_id, count(*) FROM rankings GROUP BY 1').fetchall())"
```
Expected: `(40115,)`, `(1514,)`, and one `rankings` row per pool case for the ranker used.

- [ ] **Step 2: Write `reports/ranking-cycle-004.md`** with: the metrics table (fusion / classifier / reranker × ap_all / ap_reviewed / p50 / p200, from the two manifests), the ship-rule and bar decisions, per-cell held-out AP for the shipped ranker (top 10 cells by n), the pool's score distribution (deciles) and the number of batches whose mean score exceeds 0.5 / 0.25 per era, so the map budget can be chosen per cell; the model digest and commit; the spec amendment (union of runs) and the reason.

- [ ] **Step 3: Update docs** — handoff item 11: "ranked with `<ranker_id>` (digest …); see `reports/ranking-cycle-004.md`; map budget to be chosen per cell". Spec §4: add the amendment paragraph. README: add `pipeline\rank.py --run-id <run> [--ranker <id>]` under the shard line.

- [ ] **Step 4: Full suite, commit**

Run: `.venv\Scripts\python -m pytest tests -q` — Expected: green.
```bash
git add reports/ranking-cycle-004.md reports/handoff-cycle-004.md docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md README.md
git commit -m "Cycle-004 ranking: re-packed with the shipped ranker; ranking report; handoff, spec, README updated"
```

---

## Self-review notes (done while writing)

- Spec coverage: §3 port/adapters → T3/T5/T7; §4 labels/held-out → T4; §5 features/model/baseline/ship rule → T2/T3/T5; §6 reranker/bar → T7; §7 packing/persistence/determinism/rank.py → T6; §8 errors → T2 (missing indicators), T5 (layout refusal), T4 (hash/overlap), T7 (resident GPU, "main"); §9 tests → each task; §10 rollout → T4/T5/T7/T8. §4 "same run" wording is amended (union of runs) and recorded in T8.
- Type consistency: `Label` fields used identically in T4/T5/T7; `signal_summary`/`CaseSignals` used by T3/T5/T7; `round6` defined in T3 and used by T5/T6/T7; `build_batches(..., ranker, ts)` signature identical in T6's code, tests, and `rank.py`.
- Placeholders: `<rev7>`/`<hash>` appear only as file-name/commit-text patterns resolved by the tools at run time.
