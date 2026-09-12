# Stage 4 sub-project 1: the evaluation package — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `corpus_engine.evaluation` (five measures, one JSON contract, one report), the blind audit of 150 machine-only records that feeds two of them, and the tool that publishes the evaluation.

**Architecture:** Pure measure functions over the ledger view and explicit, hashed inputs (`corpus_engine/evaluation/`), composed into one `Evaluation` that a single writer (`tools/evaluate.py`) validates against a JSON schema and publishes as `.json` + `.md`. The audit rides on the existing review-round tooling (queue shape, card export, page, apply) in a blind, three-field mode, with the user reading all 150 before any model answer is revealed.

**Tech Stack:** Python 3.12, stdlib only (`dataclasses`, `json`, `hashlib`, `random`, `math`, `sqlite3`), `jsonschema` is NOT added: the contract check is a small hand-written validator over the schema file's required keys. pytest via `.venv/Scripts/python.exe -m pytest`. Existing modules: `corpus_engine.ledger` (`open_ledger`, `LedgerView`, `Patch`, `Basis`), `corpus_engine.store`, `corpus_engine.reader.sources.StoreCaseSource`, `corpus_engine.selector.engine.attribution`, `tools/apply_map_review.py`, `tools/make_map_review.py`, `tools/export_review_cards.py`, `tools/first_pass_codex.py`.

**Spec:** `docs/superpowers/specs/2026-09-12-stage-4-evaluation-design.md`

## Global Constraints

- Published counts come only from `open_ledger().view().counts()`.
- Human-tier writes happen only through the apply tool with the user's own decisions; the audit apply refuses `--assisted-by`.
- No API spend; the audit's model passes run on the Claude subscription (opus subagents) and the Codex subscription (`tools/first_pass_codex.py`).
- Every file written by a tool goes through a byte-safe writer: LF line endings, UTF-8 without BOM, one trailing newline (`tools/export_review_cards.write_text` contract).
- Nothing in `corpus_engine/evaluation/` writes a file or reads the network.
- Every estimate is an `Estimate(value, n, lo, hi, status)`; never a bare float. `status` is one of `ok`, `undefined`, `unavailable`.
- Tests never read live `data/` or `runs/` except the two named real-data tests (Task 9's live smoke and Task 8's frozen fixture, which is copied under `tests/fixtures/`).
- Run tests as `.venv/Scripts/python.exe -m pytest <path> -q` from the repo root (bash `python` resolves to another venv). Tools run with `PYTHONPATH=.`.
- Commit trailers on every commit:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3`.
- Never commit `.env`, `data/db/`, `data/raw/`, `data/reader/cache/`, `runs/*/batches|extractions`.

## File structure

| path | responsibility |
|---|---|
| `corpus_engine/evaluation/__init__.py` | re-exports |
| `corpus_engine/evaluation/stats.py` | `wilson_interval`, `cohens_kappa`, `estimate` |
| `corpus_engine/evaluation/types.py` | `Estimate`, `Uncertainty`, `Provenance`, `Envelope`, the five result dataclasses, `Evaluation`, `to_json` |
| `corpus_engine/evaluation/gold.py` | measure 1 |
| `corpus_engine/evaluation/coverage.py` | measure 5 |
| `corpus_engine/evaluation/agreement.py` | measure 4 (+ label resolution shared with the three-way tool) |
| `corpus_engine/evaluation/precision.py` | measures 2-3 |
| `corpus_engine/evaluation/summary.py` | `evaluate()` composition, ledger content hash |
| `corpus_engine/evaluation/schema.json` | the contract; `validate(doc)` in `contract.py` |
| `corpus_engine/evaluation/contract.py` | hand-written validator over `schema.json` |
| `corpus_engine/evaluation/render.py` | markdown report from the JSON dict |
| `tools/evaluate.py` | the only writer; `--build-bands`; `--force` revisioning |
| `tools/draw_audit_sample.py` | the frozen draw, opinions, audit queue |
| `tools/threeway_sheet.py` | the scratch `threeway.py`/`agreed_set.py` moved in, plus `--per-field` |
| `tools/export_review_cards.py` | `--audit` blind mode |
| `tools/first_pass_codex.py` | `--audit --workdir` |
| `tools/make_map_review.py` | `--audit` page (lock-then-reveal) |
| `tools/apply_map_review.py` | `--audit` apply (three fields, confirm patches, drift check, outcomes) |
| `reports/review-audit-brief.md` | the audit brief |
| `runs/evaluation/rounds.json` | the rounds registry (hand-curated) |
| `runs/evaluation/shard-02-bands.json` | the bands table (built once, committed) |
| `tests/test_evaluation_*.py`, `tests/test_audit_tools.py` | tests |

---

### Task 1: stats and types

**Files:**
- Create: `corpus_engine/evaluation/__init__.py`, `corpus_engine/evaluation/stats.py`, `corpus_engine/evaluation/types.py`
- Test: `tests/test_evaluation_stats.py`

**Interfaces:**
- Produces: `stats.wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]`; `stats.cohens_kappa(pairs: Sequence[tuple[str, str]]) -> float | None` (None when undefined); `stats.estimate(k, n) -> Estimate`; `types.Estimate(value, n, lo, hi, status)`, `types.Uncertainty(type, level, method)`, `types.Provenance(inputs: tuple[tuple[str, str, str], ...], run_ids: tuple[str, ...], ledger_seqs: dict)`, `types.Envelope(method_version, population, exclusions, uncertainty, limitations, provenance)`; `types.UNAVAILABLE = Estimate(None, 0, None, None, "unavailable")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_stats.py
"""corpus_engine.evaluation.stats: Wilson intervals and Cohen's kappa against known values."""
import math
import pytest
from corpus_engine.evaluation import stats
from corpus_engine.evaluation.types import Estimate


def test_wilson_interval_matches_published_values():
    lo, hi = stats.wilson_interval(0, 10)                 # zero successes: lower bound is 0
    assert lo == 0.0 and abs(hi - 0.2775) < 0.001
    lo, hi = stats.wilson_interval(10, 10)
    assert abs(lo - 0.7225) < 0.001 and hi == 1.0
    lo, hi = stats.wilson_interval(75, 100)               # Wilson 95%: 0.657 .. 0.825
    assert abs(lo - 0.6573) < 0.001 and abs(hi - 0.8250) < 0.001


def test_wilson_interval_refuses_n_zero():
    with pytest.raises(ValueError, match="n must be positive"):
        stats.wilson_interval(0, 0)


def test_cohens_kappa_textbook_example():
    # 50 items: both say A on 20, both say B on 15, rater1 A / rater2 B on 5, B/A on 10.
    pairs = [("A", "A")] * 20 + [("B", "B")] * 15 + [("A", "B")] * 5 + [("B", "A")] * 10
    # po = 35/50 = 0.70; pe = (25/50)(30/50) + (25/50)(20/50) = 0.30 + 0.20 = 0.50; k = 0.40
    assert abs(stats.cohens_kappa(pairs) - 0.40) < 1e-9


def test_cohens_kappa_is_undefined_with_one_category_or_no_pairs():
    assert stats.cohens_kappa([("A", "A")] * 7) is None
    assert stats.cohens_kappa([]) is None


def test_estimate_carries_the_interval_and_status():
    e = stats.estimate(75, 100)
    assert isinstance(e, Estimate) and e.value == 0.75 and e.n == 100 and e.status == "ok"
    assert abs(e.lo - 0.6573) < 0.001
    z = stats.estimate(0, 0)
    assert z.status == "undefined" and z.value is None and z.n == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: corpus_engine.evaluation`

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/__init__.py
"""Stage 4 evaluation: five pure measures over the ledger view and hashed inputs, composed
into one Evaluation (see docs/superpowers/specs/2026-09-12-stage-4-evaluation-design.md)."""
from corpus_engine.evaluation.types import (Estimate, Uncertainty, Provenance, Envelope,  # noqa: F401
                                            UNAVAILABLE)
```

```python
# corpus_engine/evaluation/types.py
"""Result types every measure returns. Frozen dataclasses; `to_json`-able via `asdict`."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Estimate:
    value: float | None
    n: int
    lo: float | None
    hi: float | None
    status: str                       # "ok" | "undefined" | "unavailable"


UNAVAILABLE = Estimate(None, 0, None, None, "unavailable")


@dataclass(frozen=True)
class Uncertainty:
    type: str                         # "sampling" | "assumption" | "none"
    level: float | None               # 0.95 for a Wilson interval; None otherwise
    method: str                       # "wilson" | "scenarios" | "none"


@dataclass(frozen=True)
class Provenance:
    inputs: tuple[tuple[str, str, str], ...] = ()     # (path, sha256, role)
    run_ids: tuple[str, ...] = ()
    ledger_seqs: dict = field(default_factory=dict)   # e.g. {"reporting": 51234}


@dataclass(frozen=True)
class Envelope:
    method_version: str
    population: str
    exclusions: tuple[str, ...]
    uncertainty: Uncertainty
    limitations: tuple[str, ...]
    provenance: Provenance


def as_dict(obj: Any) -> Any:
    """`dataclasses.asdict` that also turns tuples into lists, for JSON."""
    def fix(v):
        if isinstance(v, tuple):
            return [fix(x) for x in v]
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {str(k): fix(x) for k, x in v.items()}
        return v
    return fix(asdict(obj))
```

```python
# corpus_engine/evaluation/stats.py
"""Wilson score interval and Cohen's kappa, stdlib only, tested against known values."""
from __future__ import annotations
import math
from collections import Counter
from typing import Sequence
from corpus_engine.evaluation.types import Estimate


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohens_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """None when kappa is undefined: no pairs, or expected agreement is 1 (one category)."""
    n = len(pairs)
    if n == 0:
        return None
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    pe = sum(a[c] * b[c] for c in set(a) | set(b)) / (n * n)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def estimate(k: int, n: int) -> Estimate:
    if n <= 0:
        return Estimate(None, 0, None, None, "undefined")
    lo, hi = wilson_interval(k, n)
    return Estimate(k / n, n, lo, hi, "ok")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_stats.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/evaluation tests/test_evaluation_stats.py
git commit -m "evaluation: stats (Wilson, kappa) and result types" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 2: measure 5, tail coverage, and the bands table builder

**Files:**
- Create: `corpus_engine/evaluation/coverage.py`
- Create: `tools/evaluate.py` (only the `--build-bands` subcommand in this task; Task 9 adds the rest)
- Test: `tests/test_evaluation_coverage.py`

**Interfaces:**
- Consumes: `Estimate`, `Envelope`, `Uncertainty`, `Provenance` from Task 1.
- Produces: `coverage.tail_coverage(bands_table: Mapping) -> Coverage` where the bands table is `{"run_id", "map_manifest_sha256", "batches": [{"batch_id", "cell", "score", "cases", "read": bool, "relevant": int|None, "sha256"}]}` and `Coverage(envelope, bands: tuple[Band,...], scenarios: tuple[Scenario,...])`, `Band(lo, hi, read_cases, relevant, unread_cases)`, `Scenario(name, assumption, estimated_relevant: int)`; `tools/evaluate.build_bands(manifest: Mapping, batches: Sequence[Mapping], *, manifest_sha: str, batch_shas: Mapping[str, str]) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_coverage.py
"""Measure 5: the unread tail as three scenarios from a bands table; the bands builder."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.evaluation.coverage import tail_coverage
import evaluate as ev


def _table():
    rows = []
    # read batches: band 0.30-0.35 yields 20% (2 of 10 per batch), band 0.25-0.30 yields 10%
    for i in range(30):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|N.Y.", "score": 0.32, "cases": 10,
                     "read": True, "relevant": 2, "sha256": "x"})
    for i in range(30, 60):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|N.Y.", "score": 0.27, "cases": 10,
                     "read": True, "relevant": 1, "sha256": "x"})
    # unread: 100 batches of 10 cases at score 0.15
    for i in range(60, 160):
        rows.append({"batch_id": f"b{i}", "cell": "1900-1930|Ohio", "score": 0.15, "cases": 10,
                     "read": False, "relevant": None, "sha256": "x"})
    return {"run_id": "cycle-004-shard-02", "map_manifest_sha256": "m", "batches": rows}


def test_scenarios_use_per_case_yield_of_the_lowest_read_band_with_enough_cases():
    c = tail_coverage(_table())
    by = {s.name: s for s in c.scenarios}
    # lowest read band with >= 200 cases is 0.25-0.30 at 10%: 1000 unread cases -> 100
    assert by["lowest-read-band"].estimated_relevant == 100
    assert by["half-lowest-read-band"].estimated_relevant == 50
    assert by["observed-11pct"].estimated_relevant == 110
    assert c.envelope.uncertainty.type == "assumption"
    assert any("adaptively" in s for s in c.envelope.limitations)
    bands = {(b.lo, b.hi): b for b in c.bands}
    assert bands[(0.25, 0.30)].read_cases == 300 and bands[(0.25, 0.30)].relevant == 30
    assert bands[(0.15, 0.20)].unread_cases == 1000


def test_a_table_with_no_read_batches_is_unavailable_not_a_crash():
    t = _table(); t["batches"] = [b for b in t["batches"] if not b["read"]]
    c = tail_coverage(t)
    assert c.scenarios == () and "no read batches" in c.envelope.exclusions[0]


def test_build_bands_reads_the_manifest_units_and_batch_scores():
    manifest = {"run_id": "r", "cells": {"1900-1930|N.Y.": {"units": [
        {"unit_id": "r-batch-001", "cases_read": 2, "relevant_accepted": 1, "status": "ok", "failed": False}]}}}
    batches = [{"batch_id": "r-batch-001", "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                "cases": [{"case_id": 1, "rank_score": 0.4}, {"case_id": 2, "rank_score": 0.2}]},
               {"batch_id": "r-batch-002", "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                "cases": [{"case_id": 3, "rank_score": 0.1}]}]
    t = ev.build_bands(manifest, batches, manifest_sha="m", batch_shas={"r-batch-001": "a", "r-batch-002": "b"})
    rows = {r["batch_id"]: r for r in t["batches"]}
    assert rows["r-batch-001"] == {"batch_id": "r-batch-001", "cell": "1900-1930|N.Y.", "score": 0.3,
                                   "cases": 2, "read": True, "relevant": 1, "sha256": "a"}
    assert rows["r-batch-002"]["read"] is False and rows["r-batch-002"]["relevant"] is None
    assert t["map_manifest_sha256"] == "m" and t["run_id"] == "r"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_coverage.py -q`
Expected: FAIL with `ModuleNotFoundError` (coverage) / `ImportError` (evaluate)

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/coverage.py
"""Measure 5: what the unread tail of shard 02 plausibly holds, as scenarios, never a bound."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance

METHOD_VERSION = "coverage-1"
BAND_WIDTH = 0.05
MIN_BAND_CASES = 200
OBSERVED_TAIL_YIELD = 0.11          # reports/map-cycle-004-shard-02.md §10: 11% below score 0.3


@dataclass(frozen=True)
class Band:
    lo: float
    hi: float
    read_cases: int
    relevant: int
    unread_cases: int


@dataclass(frozen=True)
class Scenario:
    name: str
    assumption: str
    estimated_relevant: int


@dataclass(frozen=True)
class Coverage:
    envelope: Envelope
    bands: tuple[Band, ...]
    scenarios: tuple[Scenario, ...]


def _band_of(score: float) -> tuple[float, float]:
    lo = round((score // BAND_WIDTH) * BAND_WIDTH, 2)
    return (lo, round(lo + BAND_WIDTH, 2))


def tail_coverage(table: Mapping) -> Coverage:
    acc: dict[tuple[float, float], list[int]] = {}
    for b in table["batches"]:
        key = _band_of(float(b["score"]))
        row = acc.setdefault(key, [0, 0, 0])
        if b["read"]:
            row[0] += int(b["cases"]); row[1] += int(b["relevant"] or 0)
        else:
            row[2] += int(b["cases"])
    bands = tuple(Band(lo, hi, r, k, u) for (lo, hi), (r, k, u) in sorted(acc.items()))
    unread = sum(b.unread_cases for b in bands)
    prov = Provenance(inputs=(("bands-table", str(table.get("map_manifest_sha256")), "map-manifest"),),
                      run_ids=(str(table.get("run_id")),))
    limitations = (
        "Batches were read in a rule-driven, adaptively stopped order, so read-band yields are "
        "not a random sample of the tail.",
        "Unsignaled cases and reader false negatives are unmeasured; the estimate covers "
        "shard-02 candidates only.",
    )
    eligible = [b for b in bands if b.read_cases >= MIN_BAND_CASES]
    if not eligible:
        return Coverage(Envelope(METHOD_VERSION, "unread shard-02 candidate cases by ranker band",
                                 ("no read batches with at least 200 cases in a band; no scenario computed",),
                                 Uncertainty("assumption", None, "scenarios"), limitations, prov),
                        bands, ())
    lowest = min(eligible, key=lambda b: b.lo)
    rate = lowest.relevant / lowest.read_cases
    scenarios = (
        Scenario("lowest-read-band", f"the tail yields at the rate of band {lowest.lo:.2f}-{lowest.hi:.2f} "
                 f"({lowest.relevant}/{lowest.read_cases} = {rate:.3f})", round(unread * rate)),
        Scenario("half-lowest-read-band", "half that rate", round(unread * rate / 2)),
        Scenario("observed-11pct", "the 11% observed below score 0.3 in the third budget", round(unread * OBSERVED_TAIL_YIELD)),
    )
    env = Envelope(METHOD_VERSION, f"{unread} unread shard-02 candidate cases, by ranker-score band",
                   (), Uncertainty("assumption", None, "scenarios"), limitations, prov)
    return Coverage(env, bands, scenarios)
```

```python
# tools/evaluate.py  (Task 2 version: the bands builder only; Task 9 extends main)
"""Publish the Stage 4 evaluation (tools/evaluate.py). This task: --build-bands.

--build-bands derives runs/evaluation/shard-02-bands.json from the gitignored batches and
the map manifest so measure 5 can be recomputed from tracked data."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from export_review_cards import write_text                     # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bands(manifest: Mapping, batches: Sequence[Mapping], *, manifest_sha: str,
                batch_shas: Mapping[str, str]) -> dict:
    read: dict[str, dict] = {}
    for cell in (manifest.get("cells") or {}).values():
        for u in cell.get("units") or ():
            if u.get("status") == "ok" and not u.get("failed"):
                read[u["unit_id"]] = u
    rows = []
    for b in batches:
        cases = b.get("cases") or []
        score = round(sum(float(c.get("rank_score") or 0) for c in cases) / len(cases), 6) if cases else 0.0
        u = read.get(b["batch_id"])
        rows.append({"batch_id": b["batch_id"], "cell": f"{b['era_partition']}|{b['jurisdiction']}",
                     "score": score, "cases": len(cases), "read": u is not None,
                     "relevant": int(u["relevant_accepted"]) if u else None,
                     "sha256": batch_shas.get(b["batch_id"])})
    rows.sort(key=lambda r: r["batch_id"])
    return {"run_id": manifest.get("run_id"), "map_manifest_sha256": manifest_sha, "batches": rows}


def cmd_build_bands(a) -> int:
    run = ROOT / "runs" / a.run_id
    mpath = run / "map-manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    paths = sorted((run / "batches").glob("batch-*.json"))
    batches = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    shas = {b["batch_id"]: sha256_file(p) for b, p in zip(batches, paths)}
    table = build_bands(manifest, batches, manifest_sha=sha256_file(mpath), batch_shas=shas)
    out = Path(a.out)
    write_text(out, json.dumps(table, indent=1))
    print(f"{len(table['batches'])} batches ({sum(1 for r in table['batches'] if r['read'])} read) -> {out.as_posix()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    bb = sub.add_parser("build-bands", help="derive the bands table from a run's batches")
    bb.add_argument("--run-id", default="cycle-004-shard-02")
    bb.add_argument("--out", default="runs/evaluation/shard-02-bands.json")
    bb.set_defaults(func=cmd_build_bands)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: the `--build-bands` flag in the spec is spelled as the subcommand `build-bands` here; Task 9 adds the `publish` subcommand beside it.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_coverage.py -q`
Expected: 3 passed

- [ ] **Step 5: Build the real bands table and commit it with the code**

Run: `PYTHONPATH=. .venv/Scripts/python.exe tools/evaluate.py build-bands`
Expected: a line like `1465 batches (652 read) -> runs/evaluation/shard-02-bands.json`

```bash
git add corpus_engine/evaluation/coverage.py tools/evaluate.py tests/test_evaluation_coverage.py runs/evaluation/shard-02-bands.json
git commit -m "evaluation: measure 5 (tail coverage scenarios) and the committed bands table" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 3: measure 1, gold recovery

**Files:**
- Create: `corpus_engine/evaluation/gold.py`
- Test: `tests/test_evaluation_gold.py`

**Interfaces:**
- Consumes: Task 1 types; `LedgerView` (`state.records`, `history`, `reviewed`); `corpus_engine.selector.engine.attribution(conn, case_ids) -> dict[int, tuple]`.
- Produces: `gold.gold_recovery(gold_rows, view, *, signaled: Mapping[int, bool], read_units: Mapping[int, str]) -> GoldRecovery`. The caller (Task 9) computes `signaled` from `attribution` and `read_units` (`{case_id: first run_id that read it}`) from the map manifests + batches, so the measure itself stays free of sqlite and the filesystem. `GoldRecovery(envelope, tiers: dict[str, TierFunnel], union: TierFunnel, misses: tuple[Miss,...], unresolved: tuple[dict,...], inventory: dict)`, `TierFunnel(entries, resolved, signaled, read, relevant, relevant_human, recovery: Estimate)`, `Miss(cite, case_id, tier, lost_at, detail)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_gold.py
"""Measure 1: gold recovery over the eligible frame with a per-stage funnel."""
from corpus_engine.evaluation.gold import gold_recovery
from corpus_engine.ledger.types import Basis, Patch


class _View:
    """The slice of LedgerView the measure reads: records, history, reviewed."""
    def __init__(self, records, history=None, reviewed=()):
        self.state = type("S", (), {})(); self.state.records = records
        self._h = history or {}; self._r = set(reviewed)
    def history(self, cid): return self._h.get(cid, [])
    def reviewed(self, cid): return cid in self._r


def _gold():
    return [
        {"cite": "1 A. 1", "cite_norm": "1 a 1", "tier": "brief", "domain": "letting", "case_id": 1},
        {"cite": "2 A. 2", "cite_norm": "2 a 2", "tier": "brief", "domain": "letting", "case_id": 2},
        {"cite": "3 A. 3", "cite_norm": "3 a 3", "tier": "brief", "domain": "letting", "case_id": 3},
        {"cite": "4 A. 4", "cite_norm": "4 a 4", "tier": "brief", "domain": "letting", "case_id": 4},
        {"cite": "5 A. 5", "cite_norm": "5 a 5", "tier": "brief", "domain": "letting", "case_id": None},
        {"cite": "6 A. 6", "cite_norm": "6 a 6", "tier": "brief", "domain": "doctrine", "case_id": 6},
        {"cite": "7 A. 7", "cite_norm": "7 a 7", "tier": "treatise", "domain": None, "case_id": 7},
        {"cite": "7 A. 7", "cite_norm": "7 a 7", "tier": "treatise", "domain": None, "case_id": 7},  # duplicate
    ]


def test_funnel_places_every_miss_at_the_stage_it_was_lost():
    records = {1: {"relevant": True}, 2: {"relevant": False}, 3: {"relevant": False}, 7: {"relevant": True}}
    hist = {3: [Patch(3, "set", "relevant", False, "round", Basis(reviewer="u", run_id="r-1b"))]}
    g = gold_recovery(_gold(), _View(records, hist, reviewed={1}),
                      signaled={1: True, 2: True, 3: True, 4: False, 7: True},
                      read_units={1: "run-a", 2: "run-a", 3: "run-b", 7: "run-a"})
    bl = g.tiers["brief-letting"]
    assert (bl.entries, bl.resolved, bl.signaled, bl.read, bl.relevant, bl.relevant_human) == (5, 4, 3, 3, 1, 1)
    assert bl.recovery.value == 0.25 and bl.recovery.n == 4
    tr = g.tiers["treatise"]
    assert (tr.entries, tr.resolved, tr.relevant) == (1, 1, 1)          # the duplicate row counted once
    assert g.union.resolved == 5 and g.union.relevant == 2
    lost = {m.case_id: m.lost_at for m in g.misses}
    assert lost == {2: "reader-negative", 3: "withdrawn", 4: "unsignaled"}
    assert [u["cite"] for u in g.unresolved] == ["5 A. 5"]
    assert g.inventory["brief-doctrine"]["entries"] == 1
    assert "recovery" in g.envelope.population and g.envelope.uncertainty.method == "wilson"
    w = next(m for m in g.misses if m.case_id == 3)
    assert "u" in w.detail and "r-1b" in w.detail


def test_read_but_unread_and_read_failed_are_distinct():
    gold = [{"cite": "1", "cite_norm": "1", "tier": "treatise", "case_id": 1},
            {"cite": "2", "cite_norm": "2", "tier": "treatise", "case_id": 2}]
    g = gold_recovery(gold, _View({}), signaled={1: True, 2: True}, read_units={2: "read-failed"})
    lost = {m.case_id: m.lost_at for m in g.misses}
    assert lost == {1: "unread", 2: "read-failed"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_gold.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/gold.py
"""Measure 1: recovery of the eligible gold cases, with the stage each miss was lost at."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from corpus_engine.evaluation.stats import estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate

METHOD_VERSION = "gold-recovery-1"
READ_FAILED = "read-failed"          # the read_units value for a case whose unit failed


@dataclass(frozen=True)
class TierFunnel:
    entries: int
    resolved: int
    signaled: int
    read: int
    relevant: int
    relevant_human: int
    recovery: Estimate


@dataclass(frozen=True)
class Miss:
    cite: str
    case_id: int | None
    tier: str
    lost_at: str          # unresolved | unsignaled | unread | read-failed | reader-negative | withdrawn
    detail: str


@dataclass(frozen=True)
class GoldRecovery:
    envelope: Envelope
    tiers: dict
    union: TierFunnel
    misses: tuple[Miss, ...]
    unresolved: tuple[dict, ...]
    inventory: dict


def _tier_of(row: Mapping) -> str | None:
    if row.get("tier") == "treatise":
        return "treatise"
    if row.get("tier") == "brief":
        return "brief-letting" if row.get("domain") == "letting" else "brief-doctrine"
    return None


def _dedupe(rows: Sequence[Mapping]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        key = r.get("case_id") or r.get("cite_norm")
        if key in seen:
            continue
        seen.add(key); out.append(dict(r))
    return out


def _lost_at(cid: int, view, signaled, read_units) -> tuple[str, str]:
    if not signaled.get(cid):
        return "unsignaled", "no selector or ranker signal"
    ru = read_units.get(cid)
    if ru is None:
        return "unread", "signaled but never in a completed map unit"
    if ru == READ_FAILED:
        return "read-failed", "its map unit failed"
    for p in view.history(cid):
        if p.op == "set" and p.field == "relevant" and p.new is False and p.basis.reviewer:
            return "withdrawn", f"withdrawn by {p.basis.reviewer} in run {p.basis.run_id}"
    return "reader-negative", f"read in {ru}; the reader said not relevant and no human overturned it"


def _funnel(rows, view, signaled, read_units, misses: list[Miss]) -> TierFunnel:
    resolved = [r for r in rows if r.get("case_id")]
    n_sig = n_read = n_rel = n_hum = 0
    for r in resolved:
        cid = int(r["case_id"])
        rec = view.state.records.get(cid) or {}
        if signaled.get(cid):
            n_sig += 1
        if cid in read_units and read_units[cid] != READ_FAILED:
            n_read += 1
        if rec.get("relevant") is True:
            n_rel += 1
            if view.reviewed(cid):
                n_hum += 1
        else:
            stage, detail = _lost_at(cid, view, signaled, read_units)
            misses.append(Miss(str(r.get("cite")), cid, _tier_of(r) or "", stage, detail))
    return TierFunnel(len(rows), len(resolved), n_sig, n_read, n_rel, n_hum, estimate(n_rel, len(resolved)))


def gold_recovery(gold_rows: Sequence[Mapping], view, *, signaled: Mapping[int, bool],
                  read_units: Mapping[int, str]) -> GoldRecovery:
    rows = _dedupe(gold_rows)
    by_tier = {"brief-letting": [], "treatise": [], "brief-doctrine": []}
    for r in rows:
        t = _tier_of(r)
        if t in by_tier:
            by_tier[t].append(r)
    misses: list[Miss] = []
    tiers = {t: _funnel(by_tier[t], view, signaled, read_units, misses) for t in ("brief-letting", "treatise")}
    seen = {m.case_id for m in misses}
    union = _funnel(by_tier["brief-letting"] + by_tier["treatise"], view, signaled, read_units, [])
    unresolved = tuple({"cite": r.get("cite"), "tier": _tier_of(r)}
                       for r in by_tier["brief-letting"] + by_tier["treatise"] if not r.get("case_id"))
    for u in unresolved:
        misses.append(Miss(str(u["cite"]), None, u["tier"] or "", "unresolved", "no case in the store for this cite"))
    doc = by_tier["brief-doctrine"]
    inventory = {"brief-doctrine": {"entries": len(doc), "resolved": sum(1 for r in doc if r.get("case_id"))}}
    env = Envelope(
        METHOD_VERSION,
        "benchmark recovery: the gold brief-letting and treatise cases that resolve to a corpus case "
        "(the briefs and treatises the project started from; no documented held-out split)",
        ("brief-doctrine entries are inventory only: authorities cited for doctrine, not letting cases",
         "unresolved cites are an ingest coverage gap, listed but outside the recovery denominator"),
        Uncertainty("sampling", 0.95, "wilson"),
        ("Recovery is cumulative across every map run; a per-run column names the run that first carried each hit.",
         "The gold set is a benchmark, not a random sample of the population of letting cases."),
        Provenance(inputs=(("data/gold/gold.jsonl", "", "gold"),)))
    del seen
    return GoldRecovery(env, tiers, union, tuple(misses), unresolved, inventory)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_gold.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/evaluation/gold.py tests/test_evaluation_gold.py
git commit -m "evaluation: measure 1, gold recovery funnel" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 4: measure 4, reviewer agreement, and the rounds registry

**Files:**
- Create: `corpus_engine/evaluation/agreement.py`, `runs/evaluation/rounds.json`
- Test: `tests/test_evaluation_agreement.py`

**Interfaces:**
- Consumes: Task 1 types and `cohens_kappa`.
- Produces: `agreement.effective_label(decision: Mapping, card: Mapping, checker_values: Mapping | None) -> str` (the substantive label a decision yields; shared with Task 7's three-way tool); `agreement.agreement(registry: Mapping, files: Mapping[str, object], *, ledger_run_ids: Sequence[str]) -> Agreement` where `files` maps each path named in the registry to its parsed JSON (the caller loads files; the measure never touches disk) and `ledger_run_ids` is every reviewer-basis run id in the ledger; `Agreement(envelope, rounds: tuple[RoundAgreement,...], excluded: tuple[dict,...], unregistered_run_ids: tuple[str,...])`, `RoundAgreement(round_id, kind, selection_rule, exposure, pairs: dict[str, dict[str, PairStat]])`, `PairStat(n, raw: Estimate, kappa: Estimate)`.
- Registry entry shape (spec §6): `{"round_id", "kind": "historical"|"audit", "queue", "checker", "claude", "astra", "user", "selection_rule", "user_mode": "card_by_card"|"bulk_adopted_astra"|"none", "apply_run_ids": [...]}`; top-level `{"rounds": [...], "dispositions": {run_id: reason}}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_agreement.py
"""Measure 4: agreement per round and pair on substantive labels; the registry reconciliation."""
from corpus_engine.evaluation.agreement import agreement, effective_label


def _queue():
    return {"run_id": "r1", "sections": {"A": [
        {"case_id": 1, "decide_field": "polarity", "values": {"polarity": "favorable"}},
        {"case_id": 2, "decide_field": "polarity", "values": {"polarity": "favorable"}},
        {"case_id": 3, "decide_field": "polarity", "values": {"polarity": "mixed"}},
        {"case_id": 4, "decide_field": "polarity", "values": {"polarity": "favorable"}}]}}


def _dec(cid, field, decision, value=None):
    d = {"case_id": cid, "field": field, "decision": decision, "note": ""}
    if value is not None:
        d["value"] = value
    return d


def test_effective_label_resolves_keep_set_adopt_withdraw_unsure():
    card = {"decide_field": "polarity", "values": {"polarity": "favorable"}}
    assert effective_label(_dec(1, "polarity", "keep"), card, None) == "favorable"
    assert effective_label(_dec(1, "polarity", "set", "adverse"), card, None) == "adverse"
    assert effective_label(_dec(1, "polarity", "adopt"), card, {"polarity": "adverse"}) == "adverse"
    assert effective_label(_dec(1, "relevant", "set", False), card, None) == "WITHDRAWN"
    assert effective_label(_dec(1, "polarity", "unsure"), card, None) == "UNSURE"


def test_agreement_per_pair_with_bulk_rounds_excluded_and_unregistered_runs_listed():
    registry = {"rounds": [
        {"round_id": "r1", "kind": "historical", "queue": "q1.json", "checker": "c1.json",
         "claude": "cl1.json", "astra": "as1.json", "user": "u1.json",
         "selection_rule": "A: favorable + under thirty days", "user_mode": "card_by_card",
         "apply_run_ids": ["r1", "r1b"]},
        {"round_id": "r2", "kind": "historical", "queue": "q1.json", "checker": "c1.json",
         "claude": "cl1.json", "astra": "as1.json", "user": "u1.json",
         "selection_rule": "same", "user_mode": "bulk_adopted_astra", "apply_run_ids": ["r2"]}],
        "dispositions": {"seed": "the bootstrap, not a review round"}}
    files = {"q1.json": _queue(), "c1.json": {"1": {"values": {"polarity": "adverse"}}},
             "cl1.json": [_dec(1, "polarity", "keep"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "as1.json": [_dec(1, "polarity", "adopt"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "u1.json": [_dec(1, "polarity", "set", "adverse")]}
    a = agreement(registry, files, ledger_run_ids=["r1", "r1b", "r2", "seed", "orphan"])
    r1 = a.rounds[0]
    assert r1.round_id == "r1" and r1.exposure == "exposure-affected"
    ca = r1.pairs["claude-astra"]["polarity"]
    assert ca.n == 4 and ca.raw.value == 0.75                    # 1 disagrees (favorable vs adverse); withdrawals agree
    assert r1.pairs["claude-user"]["polarity"].n == 1 and r1.pairs["claude-user"]["polarity"].raw.value == 0.0
    assert r1.pairs["astra-user"]["polarity"].raw.value == 1.0
    assert r1.pairs["astra-user"]["polarity"].kappa.status == "undefined"   # one category
    assert [e["round_id"] for e in a.excluded] == ["r2"] and a.excluded[0]["cards"] == 4
    assert a.unregistered_run_ids == ("orphan",)
    assert "bulk" in a.envelope.exclusions[0]


def test_an_audit_round_is_reported_blind_with_per_field_pairs():
    registry = {"rounds": [{"round_id": "audit", "kind": "audit", "queue": "aq.json", "checker": None,
                            "claude": "ac.json", "astra": "aa.json", "user": "au.json",
                            "selection_rule": "simple random sample of machine-only relevant records",
                            "user_mode": "card_by_card", "apply_run_ids": ["audit-cycle-004"]}],
                "dispositions": {}}
    q = {"run_id": "audit", "sections": {"H": [{"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"]}]}}
    files = {"aq.json": q,
             "ac.json": [_dec(9, "relevant", "set", True), _dec(9, "polarity", "set", "adverse"), _dec(9, "who_was_letting", "set", "householder")],
             "aa.json": [_dec(9, "relevant", "set", True), _dec(9, "polarity", "set", "adverse"), _dec(9, "who_was_letting", "set", "unclear")],
             "au.json": [{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "initial_value": True},
                         {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "initial_value": "favorable"},
                         {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "householder", "initial_value": "householder"}]}
    a = agreement(registry, files, ledger_run_ids=["audit-cycle-004"])
    r = a.rounds[0]
    assert r.exposure == "blind" and r.pairs["claude-astra"]["who_was_letting"].raw.value == 0.0
    # the user pair uses the INITIAL (pre-reveal) value: claude said adverse, user initially favorable
    assert r.pairs["claude-user"]["polarity"].raw.value == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_agreement.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/agreement.py
"""Measure 4: reviewer agreement per round, pair and field, on substantive labels."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from corpus_engine.evaluation.stats import cohens_kappa, estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate

METHOD_VERSION = "agreement-1"
WITHDRAWN, UNSURE = "WITHDRAWN", "UNSURE"
PAIRS = (("claude", "astra"), ("claude", "user"), ("astra", "user"))


@dataclass(frozen=True)
class PairStat:
    n: int
    raw: Estimate
    kappa: Estimate


@dataclass(frozen=True)
class RoundAgreement:
    round_id: str
    kind: str
    selection_rule: str
    exposure: str                 # "blind" | "exposure-affected"
    pairs: dict                   # {"claude-astra": {field: PairStat}}


@dataclass(frozen=True)
class Agreement:
    envelope: Envelope
    rounds: tuple[RoundAgreement, ...]
    excluded: tuple[dict, ...]
    unregistered_run_ids: tuple[str, ...]


def effective_label(d: Mapping, card: Mapping, checker_values: Mapping | None) -> str:
    field, decision = d.get("field"), d.get("decision")
    if field == "relevant" and decision in ("set", "adopt") and (d.get("value") in (False, "false", "False") or decision == "adopt"):
        return WITHDRAWN
    if decision == "unsure":
        return UNSURE
    if decision == "keep":
        return str((card.get("values") or {}).get(field))
    if decision == "adopt":
        return str((checker_values or {}).get(field))
    return str(d.get("value"))


def _cards(queue: Mapping) -> dict[int, Mapping]:
    out = {}
    for lst in (queue.get("sections") or {}).values():
        for c in lst:
            out[int(c["case_id"])] = c
    return out


def _labels(decisions: Sequence[Mapping], cards: Mapping[int, Mapping], checker: Mapping, *,
            initial: bool = False) -> dict[tuple[int, str], str]:
    """{(case_id, field): label}. A withdrawal labels every field of its card WITHDRAWN so a
    withdrawal against a field value is a disagreement and two withdrawals agree."""
    out: dict[tuple[int, str], str] = {}
    for d in decisions or ():
        cid = int(d["case_id"]); card = cards.get(cid)
        if card is None:
            continue
        fields = card.get("decide_fields") or [card.get("decide_field")]
        chk = (checker.get(str(cid)) or {}).get("values") if checker else None
        dd = dict(d)
        if initial and "initial_value" in d:
            dd["value"] = d["initial_value"]
        lab = effective_label(dd, card, chk)
        if lab == WITHDRAWN:
            for f in fields:
                out[(cid, f)] = WITHDRAWN
        elif d.get("field") in fields:
            out.setdefault((cid, d["field"]), lab)
    return out


def _pair(a: Mapping, b: Mapping, fields: Sequence[str]) -> dict[str, PairStat]:
    out = {}
    for f in fields:
        keys = [k for k in a if k[1] == f and k in b]
        pairs = [(a[k], b[k]) for k in keys]
        n = len(pairs)
        agree = sum(1 for x, y in pairs if x == y)
        kap = cohens_kappa(pairs)
        out[f] = PairStat(n, estimate(agree, n),
                          Estimate(kap, n, None, None, "ok") if kap is not None else Estimate(None, n, None, None, "undefined"))
    return out


def agreement(registry: Mapping, files: Mapping[str, object], *, ledger_run_ids: Sequence[str]) -> Agreement:
    rounds, excluded, named = [], [], set()
    for e in registry.get("rounds") or ():
        named.update(e.get("apply_run_ids") or ())
        queue = files[e["queue"]]; cards = _cards(queue)
        checker = files.get(e["checker"]) if e.get("checker") else {}
        fields = sorted({f for c in cards.values() for f in (c.get("decide_fields") or [c.get("decide_field")])})
        if e.get("user_mode") == "bulk_adopted_astra":
            excluded.append({"round_id": e["round_id"], "reason": "the user adopted Astra's view in bulk", "cards": len(cards)})
            continue
        readers = {"claude": _labels(files[e["claude"]], cards, checker),
                   "astra": _labels(files[e["astra"]], cards, checker)}
        if e.get("user") and e.get("user_mode") == "card_by_card":
            readers["user"] = _labels(files[e["user"]], cards, checker, initial=(e.get("kind") == "audit"))
        pairs = {f"{x}-{y}": _pair(readers[x], readers[y], fields) for x, y in PAIRS if x in readers and y in readers}
        rounds.append(RoundAgreement(e["round_id"], e.get("kind", "historical"), e.get("selection_rule", ""),
                                     "blind" if e.get("kind") == "audit" else "exposure-affected", pairs))
    named.update((registry.get("dispositions") or {}).keys())
    unregistered = tuple(sorted(set(ledger_run_ids) - named))
    env = Envelope(METHOD_VERSION,
                   "review-round cards decided by two model readers and, where the user decided card by card, the user",
                   ("rounds where the user adopted one reader in bulk are excluded from every user pair",),
                   Uncertainty("sampling", 0.95, "wilson"),
                   ("Historical rounds are workflow evidence: cards were selected by rules, readers saw the machine "
                    "values and the checker, and the user saw both readers' notes; only the audit round is blind.",),
                   Provenance(inputs=tuple((p, "", "registry-file") for p in sorted(files))))
    return Agreement(env, tuple(rounds), tuple(excluded), unregistered)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_agreement.py -q`
Expected: 3 passed

- [ ] **Step 5: Write the real registry**

Create `runs/evaluation/rounds.json` with one entry per round on file. The files exist under `runs/cycle-004-shard-02/` and `runs/cycles-001-003-reread/`; paths are repo-relative. Use exactly these entries (the `user` file for a `b` round is its decisions file; where the user decided on a saved page, name the `-saved.html` and the caller converts it with `apply_map_review.read_page`):

```json
{
 "rounds": [
  {"round_id": "reread-1", "kind": "historical", "queue": "runs/cycles-001-003-reread/review-round-1.json", "checker": "runs/cycles-001-003-reread/review-round-1-checker.json", "claude": "runs/cycles-001-003-reread/review-round-1-decisions-claude.json", "astra": "runs/cycles-001-003-reread/review-round-1-decisions-astra.json", "user": "runs/cycles-001-003-reread/review-round-1b-decisions.json", "selection_rule": "G: re-read conflicts with a human decision; then A-F rules; cap 250", "user_mode": "card_by_card", "apply_run_ids": ["reread-round-1", "reread-round-1b"]},
  {"round_id": "reread-2", "kind": "historical", "queue": "runs/cycles-001-003-reread/review-round-2.json", "checker": "runs/cycles-001-003-reread/review-round-2-checker.json", "claude": "runs/cycles-001-003-reread/review-round-2-decisions-claude.json", "astra": null, "user": null, "selection_rule": "E and F cards deferred from round 1", "user_mode": "none", "apply_run_ids": ["reread-round-2"]},
  {"round_id": "s02-1", "kind": "historical", "queue": "runs/cycle-004-shard-02/review-round-1.json", "checker": "runs/cycle-004-shard-02/review-round-1-checker.json", "claude": "runs/cycle-004-shard-02/review-round-1-decisions-claude.json", "astra": "runs/cycle-004-shard-02/review-round-1-decisions-astra.json", "user": "runs/cycle-004-shard-02/review-round-1b-saved.html", "selection_rule": "A favorable+under30, B householder nights, C checker disagreements, D mixed, E gate-erased, F fuzzy; cap 250", "user_mode": "card_by_card", "apply_run_ids": ["map-cycle-004-shard-02-round-1", "map-cycle-004-shard-02-round-1b"]},
  {"round_id": "s02-2", "kind": "historical", "queue": "runs/cycle-004-shard-02/review-round-2.json", "checker": "runs/cycle-004-shard-02/review-round-2-checker.json", "claude": "runs/cycle-004-shard-02/review-round-2-decisions-claude.json", "astra": "runs/cycle-004-shard-02/review-round-2-decisions-astra.json", "user": "runs/cycle-004-shard-02/review-round-2b-decisions.json", "selection_rule": "same section rules over the second budget's records", "user_mode": "bulk_adopted_astra", "apply_run_ids": ["map-cycle-004-shard-02-round-2", "map-cycle-004-shard-02-round-2b"]},
  {"round_id": "s02-3", "kind": "historical", "queue": "runs/cycle-004-shard-02/review-round-3.json", "checker": "runs/cycle-004-shard-02/review-round-3-checker.json", "claude": "runs/cycle-004-shard-02/review-round-3-decisions-claude.json", "astra": "runs/cycle-004-shard-02/review-round-3-decisions-astra.json", "user": "runs/cycle-004-shard-02/review-round-3b-saved.html", "selection_rule": "same section rules over the third budget's records", "user_mode": "card_by_card", "apply_run_ids": ["map-cycle-004-shard-02-round-3", "map-cycle-004-shard-02-round-3b"]},
  {"round_id": "s02-4", "kind": "historical", "queue": "runs/cycle-004-shard-02/review-round-4.json", "checker": "runs/cycle-004-shard-02/review-round-4-checker.json", "claude": "runs/cycle-004-shard-02/review-round-4-decisions-claude.json", "astra": "runs/cycle-004-shard-02/review-round-4-decisions-astra.json", "user": "runs/cycle-004-shard-02/review-round-4b-decisions.json", "selection_rule": "same section rules over the high-score leftovers", "user_mode": "bulk_adopted_astra", "apply_run_ids": ["map-cycle-004-shard-02-round-4", "map-cycle-004-shard-02-round-4b"]}
 ],
 "dispositions": {}
}
```

A round with `"astra": null` is skipped by the measure for the claude-astra pair (implement: if either reader file is null, omit that pair; add this to `agreement()` as `if e.get("claude") and e.get("astra")` guards) and reported with whatever pairs exist. The `dispositions` map is filled in Task 9 when the tool first lists unregistered run ids (expected: the reference-review, admission and bootstrap run ids, each with a one-line reason).

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/evaluation/agreement.py tests/test_evaluation_agreement.py runs/evaluation/rounds.json
git commit -m "evaluation: measure 4, reviewer agreement per round/pair/field; the rounds registry" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 5: measures 2-3, precision and field accuracy

**Files:**
- Create: `corpus_engine/evaluation/precision.py`
- Test: `tests/test_evaluation_precision.py`

**Interfaces:**
- Consumes: Task 1 types and `estimate`.
- Produces: `precision.precision_and_accuracy(sample_manifest: Mapping, outcomes: Mapping | None) -> Precision`. Sample manifest (spec §4.1): `{"drawn_at", "ledger_head_seq", "ledger_content_sha256", "frame_size", "frame_sha256", "seed", "method", "n", "tool_revision", "brief_sha256", "records": [{"case_id", "record": {...judged fields...}, "reader_run_id", "prompt_version", "rank_score", "band", "cell", "opinion_sha256"}]}`. Outcomes (spec §4.7): `{"run_id", "applied_seq_range": [lo, hi], "drift": {"checked": n, "changed": [...], "disposition": str}, "records": {case_id: {"draw_time": {...}, "claude": {...}|null, "astra": {...}|null, "checker": {...}|null, "user_initial": {...}, "user_final": {...}, "revised_reason": str|null, "status": "decided"|"unresolved"}}}` where each value dict is `{"relevant": bool, "polarity": str|None, "who_was_letting": str|None}`. `Precision(envelope, sampling_seq, frame_size, n, decided, unresolved, precision: Estimate, field_accuracy: dict[str, Estimate], joint_correctness: Estimate, confusion: dict[str, dict[str, dict[str, int]]], subgroups: dict, revisions: dict[str, int], drift: dict)`; when `outcomes is None` every Estimate is `UNAVAILABLE` and the envelope says so.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_precision.py
"""Measures 2-3: precision and field accuracy from the frozen sample and the audit outcomes."""
from corpus_engine.evaluation.precision import precision_and_accuracy


def _manifest(n=4):
    recs = [{"case_id": i, "record": {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
             "reader_run_id": "r", "prompt_version": "v", "rank_score": 0.5, "band": "0.50-0.55",
             "cell": "1900-1930|N.Y.", "opinion_sha256": "o"} for i in range(1, n + 1)]
    recs[1]["record"]["who_was_letting"] = "commercial_operator"
    return {"drawn_at": "t", "ledger_head_seq": 100, "ledger_content_sha256": "h", "frame_size": 2842,
            "frame_sha256": "f", "seed": 7, "method": "random.Random(seed).sample", "n": n,
            "tool_revision": "g", "brief_sha256": "b", "records": recs}


def _val(rel, pol=None, who=None):
    return {"relevant": rel, "polarity": pol, "who_was_letting": who}


def test_rates_confusions_subgroup_and_revisions():
    out = {"run_id": "audit-cycle-004", "applied_seq_range": [101, 140],
           "drift": {"checked": 4, "changed": [], "disposition": "none"},
           "records": {
               "1": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "householder"),
                     "revised_reason": None, "status": "decided"},
               "2": {"draw_time": _val(True, "favorable", "commercial_operator"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "adverse", "commercial_operator"), "user_final": _val(True, "adverse", "commercial_operator"),
                     "revised_reason": None, "status": "decided"},
               "3": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(False), "user_final": _val(False), "revised_reason": None, "status": "decided"},
               "4": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "unclear"),
                     "revised_reason": "the model note pointed to the lease", "status": "unresolved"}}}
    p = precision_and_accuracy(_manifest(), out)
    assert (p.n, p.decided, p.unresolved) == (4, 3, 1)
    assert p.precision.n == 3 and abs(p.precision.value - 2 / 3) < 1e-9
    assert p.field_accuracy["polarity"].n == 2 and p.field_accuracy["polarity"].value == 0.5
    assert p.field_accuracy["who_was_letting"].value == 1.0
    assert p.joint_correctness.n == 3 and abs(p.joint_correctness.value - 1 / 3) < 1e-9
    assert p.confusion["polarity"]["favorable"] == {"favorable": 1, "adverse": 1, "withdrawn": 1}
    assert p.subgroups["favorable_householder"]["n"] == 3         # draw-time favorable+householder: cases 1,3,4
    assert p.subgroups["favorable_householder"]["precision"].n == 2   # 4 is unresolved
    assert p.revisions == {"relevant": 0, "polarity": 0, "who_was_letting": 0}   # 4 revised but is unresolved -> not counted
    assert p.sampling_seq == 100 and p.frame_size == 2842 and p.drift["checked"] == 4
    assert any("unresolved" in s for s in p.envelope.limitations)


def test_without_outcomes_everything_is_unavailable():
    p = precision_and_accuracy(_manifest(), None)
    assert p.precision.status == "unavailable" and p.field_accuracy["polarity"].status == "unavailable"
    assert p.decided == 0 and "not yet" in p.envelope.exclusions[0]


def test_unknown_case_in_outcomes_is_refused():
    import pytest
    out = {"run_id": "a", "applied_seq_range": [1, 2], "drift": {}, "records": {"99": {"status": "decided",
           "draw_time": _val(True), "user_initial": _val(True), "user_final": _val(True), "claude": None, "astra": None,
           "checker": None, "revised_reason": None}}}
    with pytest.raises(ValueError, match="99 is not in the sample"):
        precision_and_accuracy(_manifest(), out)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_precision.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/precision.py
"""Measures 2-3: machine-tier precision and field accuracy over the frozen audit sample."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from corpus_engine.evaluation.stats import estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate, UNAVAILABLE

METHOD_VERSION = "precision-1"
FIELDS = ("polarity", "who_was_letting")
WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class Precision:
    envelope: Envelope
    sampling_seq: int
    frame_size: int
    n: int
    decided: int
    unresolved: int
    precision: Estimate
    field_accuracy: dict
    joint_correctness: dict | Estimate
    confusion: dict
    subgroups: dict
    revisions: dict
    drift: dict


def _rates(rows: list[dict]) -> dict:
    """rows: outcome entries with status decided. Returns the estimates and confusions."""
    relevant = [r for r in rows if r["user_final"].get("relevant") is True]
    prec = estimate(len(relevant), len(rows))
    acc, conf = {}, {}
    for f in FIELDS:
        hit = sum(1 for r in relevant if r["draw_time"].get(f) == r["user_final"].get(f))
        acc[f] = estimate(hit, len(relevant))
        m: dict[str, dict[str, int]] = {}
        for r in rows:
            row = str(r["draw_time"].get(f))
            col = WITHDRAWN if r["user_final"].get("relevant") is not True else str(r["user_final"].get(f))
            m.setdefault(row, {}); m[row][col] = m[row].get(col, 0) + 1
        conf[f] = m
    joint = sum(1 for r in relevant if all(r["draw_time"].get(f) == r["user_final"].get(f) for f in FIELDS))
    return {"precision": prec, "field_accuracy": acc, "joint": estimate(joint, len(rows)), "confusion": conf}


def precision_and_accuracy(manifest: Mapping, outcomes: Mapping | None) -> Precision:
    sample = {int(r["case_id"]): r for r in manifest["records"]}
    n = len(sample)
    prov = Provenance(inputs=(("sample-manifest", str(manifest.get("frame_sha256")), "frame"),),
                      ledger_seqs={"sampling": manifest["ledger_head_seq"]})
    if outcomes is None:
        env = Envelope(METHOD_VERSION, f"{n} machine-only relevant records drawn at seq {manifest['ledger_head_seq']}",
                       ("the audit has not yet been read; every estimate is unavailable",),
                       Uncertainty("sampling", 0.95, "wilson"), (), prov)
        return Precision(env, manifest["ledger_head_seq"], manifest["frame_size"], n, 0, 0, UNAVAILABLE,
                         {f: UNAVAILABLE for f in FIELDS}, UNAVAILABLE, {}, {}, {}, {})
    rows_all = []
    for cid_s, o in outcomes["records"].items():
        cid = int(cid_s)
        if cid not in sample:
            raise ValueError(f"case {cid} is not in the sample manifest")
        rows_all.append({"case_id": cid, **o})
    decided = [r for r in rows_all if r["status"] == "decided"]
    unresolved = [r for r in rows_all if r["status"] != "decided"]
    rates = _rates(decided)
    sub_ids = [cid for cid, r in sample.items()
               if r["record"].get("polarity") == "favorable" and r["record"].get("who_was_letting") == "householder"]
    sub_rows = [r for r in decided if r["case_id"] in sub_ids]
    sub = _rates(sub_rows) if sub_rows else {"precision": UNAVAILABLE, "field_accuracy": {}, "joint": UNAVAILABLE, "confusion": {}}
    revisions = {f: sum(1 for r in decided if r["user_initial"].get(f) != r["user_final"].get(f))
                 for f in ("relevant",) + FIELDS}
    limitations = [
        "Precision is the share of DRAW-TIME machine-only relevant records a blind human reading kept; "
        "after the audit those records are human-reviewed, so the live machine tier is a different population.",
        "Field accuracy is conditioned on the records the human found relevant; a withdrawn record counts "
        "against joint correctness, not against a field.",
    ]
    if unresolved:
        limitations.append(f"{len(unresolved)} sampled records were left unresolved (unreadable opinions) and "
                           f"are outside every rate's denominator: " + ", ".join(str(r["case_id"]) for r in unresolved))
    env = Envelope(METHOD_VERSION,
                   f"simple random sample of {n} of the {manifest['frame_size']} machine-only relevant records at seq "
                   f"{manifest['ledger_head_seq']} (seed {manifest['seed']})",
                   tuple(f"case {r['case_id']}: {r['status']}" for r in unresolved),
                   Uncertainty("sampling", 0.95, "wilson"), tuple(limitations), prov)
    return Precision(env, manifest["ledger_head_seq"], manifest["frame_size"], n, len(decided), len(unresolved),
                     rates["precision"], rates["field_accuracy"], rates["joint"], rates["confusion"],
                     {"favorable_householder": {"n": len(sub_ids), "precision": sub["precision"],
                                                "field_accuracy": sub["field_accuracy"]}},
                     revisions, dict(outcomes.get("drift") or {}))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_precision.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/evaluation/precision.py tests/test_evaluation_precision.py
git commit -m "evaluation: measures 2-3, precision and field accuracy over the frozen sample" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 6: summary, contract and markdown renderer

**Files:**
- Create: `corpus_engine/evaluation/summary.py`, `corpus_engine/evaluation/contract.py`, `corpus_engine/evaluation/schema.json`, `corpus_engine/evaluation/render.py`
- Test: `tests/test_evaluation_summary.py`

**Interfaces:**
- Consumes: Tasks 1-5 result types; `LedgerView.counts()` (`.total.human_reviewed/.machine_only`; `counts(polarity="favorable")`, `counts(polarity="favorable", who_was_letting="householder")`); `Ledger.log.head()`.
- Produces: `summary.Inputs(gold: GoldRecovery, precision: Precision, agreement: Agreement, coverage: Coverage)`; `summary.evaluate(view, inputs, *, cycle: str, reporting_seq: int, content_sha256: str, code: dict) -> Evaluation`; `summary.to_json(ev) -> dict`; `summary.ledger_content_sha256(ledger_dir: Path) -> str` (sha256 over the LF-normalised bytes of `patches.jsonl` then each `cycle-*.jsonl` in name order); `contract.validate(doc: dict) -> list[str]` (empty list = valid; each string names a missing/mistyped key path); `render.markdown(doc: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluation_summary.py
"""Composition into one Evaluation, the JSON contract, and the markdown report."""
import json
from pathlib import Path
from corpus_engine.evaluation import contract, render, summary
from corpus_engine.evaluation.types import UNAVAILABLE, Estimate, Envelope, Uncertainty, Provenance
from corpus_engine.evaluation.gold import GoldRecovery, TierFunnel
from corpus_engine.evaluation.precision import Precision
from corpus_engine.evaluation.agreement import Agreement
from corpus_engine.evaluation.coverage import Coverage, Band, Scenario


def _env(v="x-1"):
    return Envelope(v, "pop", ("ex",), Uncertainty("none", None, "none"), ("lim",), Provenance())


class _Counts:
    def __init__(self, h, m):
        self.total = type("T", (), {"human_reviewed": h, "machine_only": m})()


class _View:
    def counts(self, **f):
        if f.get("who_was_letting"): return _Counts(161, 236)
        if f.get("polarity"): return _Counts(754, 1200)
        return _Counts(1509, 2842)


def _inputs():
    tf = TierFunnel(5, 4, 3, 3, 1, 1, Estimate(0.25, 4, 0.05, 0.7, "ok"))
    gold = GoldRecovery(_env("gold-recovery-1"), {"brief-letting": tf, "treatise": tf}, tf, (), (), {"brief-doctrine": {"entries": 1, "resolved": 1}})
    prec = Precision(_env("precision-1"), 100, 2842, 150, 0, 0, UNAVAILABLE, {"polarity": UNAVAILABLE, "who_was_letting": UNAVAILABLE}, UNAVAILABLE, {}, {}, {}, {})
    agr = Agreement(_env("agreement-1"), (), (), ())
    cov = Coverage(_env("coverage-1"), (Band(0.25, 0.30, 300, 30, 0),), (Scenario("lowest-read-band", "a", 100),))
    return summary.Inputs(gold, prec, agr, cov)


def test_evaluate_composes_counts_and_validates_against_the_schema():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=51234, content_sha256="ab" * 32,
                          code={"git_revision": "deadbeef", "command": "tools/evaluate.py publish", "python": "3.12", "packages": {}})
    doc = summary.to_json(ev)
    assert doc["schema_version"] == "1" and doc["cycle"] == "004"
    assert doc["evaluation_id"] == "004-51234-abababab"
    assert doc["ledger"]["counts"]["relevant"] == {"human_reviewed": 1509, "machine_only": 2842}
    assert doc["ledger"]["counts"]["favorable_householder"]["human_reviewed"] == 161
    assert doc["precision"]["precision"]["status"] == "unavailable"
    assert doc["coverage"]["scenarios"][0]["estimated_relevant"] == 100
    assert contract.validate(doc) == []
    json.dumps(doc)                                     # serialisable


def test_validate_names_missing_and_mistyped_keys():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=1, content_sha256="0" * 64, code={})
    doc = summary.to_json(ev)
    del doc["gold_recovery"]["tiers"]
    doc["coverage"]["scenarios"] = "not a list"
    problems = contract.validate(doc)
    assert "gold_recovery.tiers" in problems and "coverage.scenarios" in problems


def test_markdown_has_the_headline_table_and_one_section_per_measure():
    ev = summary.evaluate(_View(), _inputs(), cycle="004", reporting_seq=1, content_sha256="0" * 64, code={})
    md = render.markdown(summary.to_json(ev))
    assert md.startswith("# Evaluation of the corpus")
    assert "| measure | headline | denominator | uncertainty |" in md
    for h in ("## 1. Gold recovery", "## 2. Machine-tier precision", "## 3. Field accuracy", "## 4. Reviewer agreement", "## 5. Unread-tail coverage", "## Rounds registry"):
        assert h in md
    assert "unavailable" in md and "4,351" in md      # counts formatted with thousands separators


def test_ledger_content_hash_is_over_lf_bytes_in_a_fixed_order(tmp_path):
    (tmp_path / "patches.jsonl").write_bytes(b'{"a":1}\r\n')
    (tmp_path / "cycle-001.jsonl").write_bytes(b'{"b":2}\n')
    h1 = summary.ledger_content_sha256(tmp_path)
    (tmp_path / "patches.jsonl").write_bytes(b'{"a":1}\n')
    assert summary.ledger_content_sha256(tmp_path) == h1        # CRLF and LF hash the same
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_summary.py -q`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# corpus_engine/evaluation/summary.py
"""Compose the five measures and the published counts into one Evaluation; JSON out."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from corpus_engine.evaluation.types import as_dict
from corpus_engine.evaluation.gold import GoldRecovery
from corpus_engine.evaluation.precision import Precision
from corpus_engine.evaluation.agreement import Agreement
from corpus_engine.evaluation.coverage import Coverage

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Inputs:
    gold: GoldRecovery
    precision: Precision
    agreement: Agreement
    coverage: Coverage


@dataclass(frozen=True)
class Evaluation:
    evaluation_id: str
    generated_at: str
    cycle: str
    code: dict
    ledger: dict
    gold_recovery: GoldRecovery
    precision: Precision
    agreement: Agreement
    coverage: Coverage


def _tier(c) -> dict:
    return {"human_reviewed": c.total.human_reviewed, "machine_only": c.total.machine_only}


def ledger_content_sha256(ledger_dir: Path) -> str:
    h = hashlib.sha256()
    names = ["patches.jsonl"] + sorted(p.name for p in ledger_dir.glob("cycle-*.jsonl"))
    for n in names:
        p = ledger_dir / n
        if p.exists():
            h.update(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return h.hexdigest()


def evaluate(view, inputs: Inputs, *, cycle: str, reporting_seq: int, content_sha256: str,
             code: dict, generated_at: str = "") -> Evaluation:
    from datetime import datetime, timezone
    ledger = {"reporting_seq": reporting_seq, "content_sha256": content_sha256,
              "counts": {"relevant": _tier(view.counts()),
                         "favorable": _tier(view.counts(polarity="favorable")),
                         "favorable_householder": _tier(view.counts(polarity="favorable", who_was_letting="householder"))}}
    return Evaluation(f"{cycle}-{reporting_seq}-{content_sha256[:8]}",
                      generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      cycle, dict(code), ledger, inputs.gold, inputs.precision, inputs.agreement, inputs.coverage)


def to_json(ev: Evaluation) -> dict:
    return {"schema_version": SCHEMA_VERSION, "evaluation_id": ev.evaluation_id, "generated_at": ev.generated_at,
            "cycle": ev.cycle, "code": ev.code, "ledger": ev.ledger,
            "gold_recovery": as_dict(ev.gold_recovery), "precision": as_dict(ev.precision),
            "agreement": as_dict(ev.agreement), "coverage": as_dict(ev.coverage)}
```

`schema.json` lists, per top-level key, the required keys and their JSON types; `contract.validate` walks it:

```json
{
 "schema_version": "1",
 "required": {
  "": {"schema_version": "string", "evaluation_id": "string", "generated_at": "string", "cycle": "string",
       "code": "object", "ledger": "object", "gold_recovery": "object", "precision": "object",
       "agreement": "object", "coverage": "object"},
  "ledger": {"reporting_seq": "integer", "content_sha256": "string", "counts": "object"},
  "ledger.counts": {"relevant": "object", "favorable": "object", "favorable_householder": "object"},
  "gold_recovery": {"envelope": "object", "tiers": "object", "union": "object", "misses": "array", "unresolved": "array", "inventory": "object"},
  "precision": {"envelope": "object", "sampling_seq": "integer", "frame_size": "integer", "n": "integer", "decided": "integer",
                "unresolved": "integer", "precision": "object", "field_accuracy": "object", "joint_correctness": "object",
                "confusion": "object", "subgroups": "object", "revisions": "object", "drift": "object"},
  "agreement": {"envelope": "object", "rounds": "array", "excluded": "array", "unregistered_run_ids": "array"},
  "coverage": {"envelope": "object", "bands": "array", "scenarios": "array"},
  "gold_recovery.envelope": {"method_version": "string", "population": "string", "exclusions": "array", "uncertainty": "object", "limitations": "array", "provenance": "object"},
  "precision.envelope": {"method_version": "string", "population": "string", "exclusions": "array", "uncertainty": "object", "limitations": "array", "provenance": "object"},
  "agreement.envelope": {"method_version": "string", "population": "string", "exclusions": "array", "uncertainty": "object", "limitations": "array", "provenance": "object"},
  "coverage.envelope": {"method_version": "string", "population": "string", "exclusions": "array", "uncertainty": "object", "limitations": "array", "provenance": "object"},
  "precision.precision": {"value": "number|null", "n": "integer", "lo": "number|null", "hi": "number|null", "status": "string"}
 }
}
```

```python
# corpus_engine/evaluation/contract.py
"""A small validator over schema.json: required keys and JSON types per path."""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA = json.loads((Path(__file__).with_name("schema.json")).read_text(encoding="utf-8"))
_TYPES = {"string": str, "integer": int, "number": (int, float), "object": dict, "array": list, "null": type(None)}


def _ok(value, spec: str) -> bool:
    return any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
               for t in spec.split("|"))


def validate(doc: dict) -> list[str]:
    problems = []
    for path, keys in SCHEMA["required"].items():
        node = doc
        for part in [p for p in path.split(".") if p]:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            if path:
                problems.append(path)
            continue
        for k, spec in keys.items():
            full = f"{path}.{k}" if path else k
            if k not in node or not _ok(node[k], spec):
                problems.append(full)
    return sorted(set(problems))
```

```python
# corpus_engine/evaluation/render.py
"""The markdown report from the evaluation's JSON dict. Numbers in tables, limitations verbatim."""
from __future__ import annotations


def _est(e: dict) -> str:
    if e.get("status") != "ok":
        return e.get("status", "unavailable")
    return f"{e['value']:.3f} ({e['lo']:.3f}-{e['hi']:.3f}, n={e['n']:,})"


def _tier(t: dict) -> str:
    return f"{t['human_reviewed'] + t['machine_only']:,} ({t['human_reviewed']:,} human / {t['machine_only']:,} machine)"


def _envelope(env: dict) -> list[str]:
    out = [f"Population: {env['population']}", ""]
    if env["exclusions"]:
        out += ["Exclusions:"] + [f"- {x}" for x in env["exclusions"]] + [""]
    out += ["Limitations:"] + [f"- {x}" for x in env["limitations"]] + [""]
    if env["provenance"].get("inputs"):
        out += ["Provenance:"] + [f"- {p[0]} ({p[2]}) sha256 {p[1] or '-'}" for p in env["provenance"]["inputs"]] + [""]
    return out


def markdown(doc: dict) -> str:
    g, p, a, c, led = doc["gold_recovery"], doc["precision"], doc["agreement"], doc["coverage"], doc["ledger"]
    L = [f"# Evaluation of the corpus, cycle {doc['cycle']} ({doc['evaluation_id']})", "",
         f"Generated {doc['generated_at']} at ledger seq {led['reporting_seq']:,} "
         f"(content {led['content_sha256'][:12]}), code {doc['code'].get('git_revision', '?')}.", "",
         "Published counts (`open_ledger().view().counts()`):", "",
         "| population | count |", "|---|---|",
         f"| relevant | {_tier(led['counts']['relevant'])} |",
         f"| favorable | {_tier(led['counts']['favorable'])} |",
         f"| favorable householder | {_tier(led['counts']['favorable_householder'])} |", "",
         "## Headline", "",
         "| measure | headline | denominator | uncertainty |", "|---|---|---|---|",
         f"| gold recovery (union) | {_est(g['union']['recovery'])} | {g['union']['resolved']} resolved gold cases | {g['envelope']['uncertainty']['type']} |",
         f"| machine-tier precision | {_est(p['precision'])} | {p['decided']} decided of {p['n']} sampled | {p['envelope']['uncertainty']['type']} |",
         f"| polarity accuracy | {_est(p['field_accuracy'].get('polarity', {'status': 'unavailable'}))} | records found relevant | sampling |",
         f"| who_was_letting accuracy | {_est(p['field_accuracy'].get('who_was_letting', {'status': 'unavailable'}))} | records found relevant | sampling |",
         f"| blind agreement (audit) | {_audit_headline(a)} | audit cards | sampling |",
         f"| unread-tail coverage | {_scenarios_headline(c)} | unread shard-02 cases | {c['envelope']['uncertainty']['type']} |", "",
         "## 1. Gold recovery", ""]
    L += ["| tier | entries | resolved | signaled | read | relevant | human-reviewed | recovery |", "|---|---|---|---|---|---|---|---|"]
    for name, t in list(g["tiers"].items()) + [("union", g["union"])]:
        L.append(f"| {name} | {t['entries']} | {t['resolved']} | {t['signaled']} | {t['read']} | {t['relevant']} | {t['relevant_human']} | {_est(t['recovery'])} |")
    L += ["", f"Inventory: brief-doctrine {g['inventory']['brief_doctrine']['entries']} entries, {g['inventory']['brief_doctrine']['resolved']} resolved (not in the denominator).", ""]
    if g["misses"]:
        L += ["| cite | case | tier | lost at | detail |", "|---|---|---|---|---|"]
        L += [f"| {m['cite']} | {m['case_id'] or '-'} | {m['tier']} | {m['lost_at']} | {m['detail']} |" for m in g["misses"]]
        L.append("")
    L += _envelope(g["envelope"])
    L += ["## 2. Machine-tier precision", "",
          f"Sample: {p['n']} of {p['frame_size']:,} machine-only relevant records at seq {p['sampling_seq']:,}; "
          f"{p['decided']} decided, {p['unresolved']} unresolved.", "",
          f"Precision: {_est(p['precision'])}", ""]
    L += _envelope(p["envelope"])
    L += ["## 3. Field accuracy", "", "| field | accuracy |", "|---|---|"]
    L += [f"| {f} | {_est(e)} |" for f, e in p["field_accuracy"].items()]
    L += ["", f"Joint correctness (relevant, polarity, who_was_letting all match): {_est(p['joint_correctness'])}", ""]
    for f, m in p.get("confusion", {}).items():
        cols = sorted({c for row in m.values() for c in row})
        L += [f"Confusion, {f} (draw-time by row, adjudicated by column):", "",
              "| draw-time \\ adjudicated | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        L += [f"| {row} | " + " | ".join(str(m[row].get(c, 0)) for c in cols) + " |" for row in sorted(m)]
        L.append("")
    if p.get("subgroups"):
        s = p["subgroups"]["favorable_householder"]
        L += [f"Favorable-householder subgroup: n={s['n']}, precision {_est(s['precision'])}.", ""]
    if p.get("revisions"):
        L += ["Revisions after reveal: " + ", ".join(f"{f} {n}" for f, n in p["revisions"].items()), ""]
    L += ["## 4. Reviewer agreement", ""]
    for r in a["rounds"]:
        L += [f"### {r['round_id']} ({r['kind']}, {r['exposure']})", "", f"Selection rule: {r['selection_rule']}", "",
              "| pair | field | n | raw agreement | kappa |", "|---|---|---|---|---|"]
        for pair, fields in r["pairs"].items():
            for f, st in fields.items():
                k = st["kappa"]
                L.append(f"| {pair} | {f} | {st['n']} | {_est(st['raw'])} | {k['value']:.3f} |" if k["status"] == "ok"
                         else f"| {pair} | {f} | {st['n']} | {_est(st['raw'])} | {k['status']} |")
        L.append("")
    if a["excluded"]:
        L += ["Excluded rounds:"] + [f"- {e['round_id']}: {e['reason']} ({e['cards']} cards)" for e in a["excluded"]] + [""]
    if a["unregistered_run_ids"]:
        L += ["Reviewer run ids in the ledger not named by the registry: " + ", ".join(a["unregistered_run_ids"]), ""]
    L += _envelope(a["envelope"])
    L += ["## 5. Unread-tail coverage", "", "| band | read cases | relevant | yield | unread cases |", "|---|---|---|---|---|"]
    for b in c["bands"]:
        y = f"{b['relevant'] / b['read_cases']:.3f}" if b["read_cases"] else "-"
        L.append(f"| {b['lo']:.2f}-{b['hi']:.2f} | {b['read_cases']:,} | {b['relevant']} | {y} | {b['unread_cases']:,} |")
    L += ["", "| scenario | assumption | estimated relevant |", "|---|---|---|"]
    L += [f"| {s['name']} | {s['assumption']} | {s['estimated_relevant']:,} |" for s in c["scenarios"]]
    L.append("")
    L += _envelope(c["envelope"])
    L += ["## Rounds registry", "", "See `runs/evaluation/rounds.json` (hash in the agreement provenance).", ""]
    return "\n".join(L)


def _audit_headline(a: dict) -> str:
    for r in a["rounds"]:
        if r["kind"] == "audit" and "claude-astra" in r["pairs"] and "relevant" in r["pairs"]["claude-astra"]:
            return _est(r["pairs"]["claude-astra"]["relevant"]["raw"])
    return "unavailable"


def _scenarios_headline(c: dict) -> str:
    if not c["scenarios"]:
        return "unavailable"
    vals = [s["estimated_relevant"] for s in c["scenarios"]]
    return f"{min(vals):,}-{max(vals):,} (three scenarios)"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluation_summary.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/evaluation tests/test_evaluation_summary.py
git commit -m "evaluation: summary composition, JSON contract with validator, markdown renderer" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 7: the three-way sheet tool (scratch scripts moved in, plus `--per-field`)

**Files:**
- Create: `tools/threeway_sheet.py`
- Test: `tests/test_threeway_sheet.py`
- Reference: the session scratch scripts `threeway.py` and `agreed_set.py` (scratchpad); their behaviour is restated here in full, so the implementer does not need them.

**Interfaces:**
- Consumes: `corpus_engine.evaluation.agreement.effective_label`.
- Produces: `threeway_sheet.build(queue: Mapping, checker: Mapping, claude: list, astra: list, *, label: str, per_field: bool = False) -> tuple[str, list[dict]]` returning `(markdown, agreed_decisions)`; in one-field mode `agreed_decisions` is the agreed set in the apply schema (Claude's entry, with `adopt` resolved to `set` + the checker value); in `--per-field` mode it is always `[]` (spec §4.8: nothing in the audit is applied without the user). CLI: `tools/threeway_sheet.py --queue Q --checker C --claude A --astra B --out-md M [--out-agreed J] [--per-field] --label L`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_threeway_sheet.py
"""tools/threeway_sheet.py: agree/disagree per card (one-field) or per field (audit)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import threeway_sheet as tw


def _d(cid, field, decision, value=None, note="n"):
    d = {"case_id": cid, "field": field, "decision": decision, "note": note}
    if value is not None: d["value"] = value
    return d


def test_one_field_mode_agreed_set_resolves_adopt_and_lists_disagreements_first():
    queue = {"run_id": "r", "sections": {"A": [
        {"case_id": 1, "decide_field": "polarity", "cite": "1 A. 1", "values": {"polarity": "favorable"}},
        {"case_id": 2, "decide_field": "polarity", "cite": "2 A. 2", "values": {"polarity": "favorable"}},
        {"case_id": 3, "decide_field": "polarity", "cite": "3 A. 3", "values": {"polarity": "mixed"}}]}}
    checker = {"1": {"values": {"polarity": "adverse"}}}
    claude = [_d(1, "polarity", "set", "adverse"), _d(2, "polarity", "keep"), _d(3, "relevant", "set", False)]
    astra = [_d(1, "polarity", "adopt"), _d(2, "polarity", "set", "adverse"), _d(3, "relevant", "set", False)]
    md, agreed = tw.build(queue, checker, claude, astra, label="round x")
    assert "agree on 2; disagree on 1" in md
    assert md.index("## Disagreements") < md.index("## Agreements")
    assert "| 2 | 2 A. 2 |" in md.split("## Agreements")[0]          # the disagreement row
    assert [(d["case_id"], d["decision"], d.get("value")) for d in agreed] == [(1, "set", "adverse"), (3, "set", False)]


def test_per_field_mode_compares_each_field_and_applies_nothing():
    queue = {"run_id": "audit", "sections": {"H": [
        {"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9"}]}}
    claude = [_d(9, "relevant", "set", True), _d(9, "polarity", "set", "adverse"), _d(9, "who_was_letting", "set", "householder")]
    astra = [_d(9, "relevant", "set", True), _d(9, "polarity", "set", "adverse"), _d(9, "who_was_letting", "set", "unclear")]
    md, agreed = tw.build(queue, {}, claude, astra, label="audit", per_field=True)
    assert agreed == []
    assert "| 9 | 9 A. 9 | who_was_letting | householder | unclear |" in md
    assert "fields agree 2; disagree 1" in md
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_threeway_sheet.py -q`
Expected: FAIL with `ModuleNotFoundError: threeway_sheet`

- [ ] **Step 3: Implement**

```python
# tools/threeway_sheet.py
"""Three-way sheet: Claude first pass vs GPT Astra vs the checker, per card (one-field rounds)
or per field (--per-field, the audit). One-field mode also writes the agreed set in the apply
schema; per-field mode never does (the audit applies only the user's decisions)."""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.evaluation.agreement import effective_label, WITHDRAWN   # noqa: E402
from export_review_cards import write_text                                   # noqa: E402


def _cards(queue: Mapping) -> dict[int, dict]:
    out = {}
    for sec, lst in (queue.get("sections") or {}).items():
        for c in lst:
            out[int(c["case_id"])] = dict(c, section=sec)
    return out


def _by_case(decisions: Sequence[Mapping]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for d in decisions or ():
        out.setdefault(int(d["case_id"]), []).append(dict(d))
    return out


def _label_for(entries: list[dict], card: dict, field: str, checker_values) -> tuple[str, str]:
    """(label, note) for `field` on this card from one reader's entries."""
    for d in entries:
        if effective_label(d, card, checker_values) == WITHDRAWN:
            return WITHDRAWN, d.get("note", "")
    for d in entries:
        if d.get("field") == field:
            return effective_label(d, card, checker_values), d.get("note", "")
    return "MISSING", ""


def build(queue: Mapping, checker: Mapping, claude: Sequence[Mapping], astra: Sequence[Mapping], *,
          label: str, per_field: bool = False) -> tuple[str, list[dict]]:
    cards = _cards(queue)
    cl, asr = _by_case(claude), _by_case(astra)
    rows_dis, rows_agr, agreed, sec_tally = [], [], [], {}
    for cid in sorted(cards):
        card = cards[cid]
        chk = ((checker.get(str(cid)) or {}).get("values") or {})
        fields = card.get("decide_fields") or [card["decide_field"]]
        for f in fields:
            a, an = _label_for(cl.get(cid, []), card, f, chk)
            b, bn = _label_for(asr.get(cid, []), card, f, chk)
            row = (f"| {cid} | {card.get('cite') or ''} | {card.get('section')} | {f} | "
                   f"{card.get('values', {}).get(f, '')} | {chk.get(f, '')} | {a} | {b} | "
                   f"{an[:160].replace('|', '/')} | {bn[:160].replace('|', '/')} |")
            t = sec_tally.setdefault(card.get("section"), Counter())
            if a == b and a != "MISSING":
                rows_agr.append(row); t["agree"] += 1
                if not per_field:
                    d = next((x for x in cl[cid] if x.get("field") == f or effective_label(x, card, chk) == WITHDRAWN), None)
                    if d:
                        d = dict(d)
                        if d.get("decision") == "adopt":
                            d["decision"], d["value"] = "set", chk.get(f)
                        agreed.append(d)
            else:
                rows_dis.append(row); t["disagree"] += 1
            if not per_field:
                break
    n_agree, n_dis = len(rows_agr), len(rows_dis)
    unit = "fields" if per_field else "cards"
    head = [f"# Three-way sheet: {label}", "",
            (f"{len(cards)} cards. {unit} agree {n_agree}; disagree {n_dis}." if per_field
             else f"{len(cards)} cards. Claude and Astra agree on {n_agree}; disagree on {n_dis}."),
            "", "| section | agree | disagree |", "|---|---|---|"]
    head += [f"| {s} | {t['agree']} | {t['disagree']} |" for s, t in sorted(sec_tally.items())]
    hdr = ["| case | cite | sec | field | current | checker | Claude | Astra | Claude note | Astra note |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    md = "\n".join(head + ["", "## Disagreements", ""] + hdr + rows_dis + ["", "## Agreements", ""] + hdr + rows_agr) + "\n"
    agreed.sort(key=lambda d: (int(d["case_id"]), d["field"]))
    return md, ([] if per_field else agreed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", required=True); ap.add_argument("--checker", default=None)
    ap.add_argument("--claude", required=True); ap.add_argument("--astra", required=True)
    ap.add_argument("--out-md", required=True); ap.add_argument("--out-agreed", default=None)
    ap.add_argument("--per-field", action="store_true"); ap.add_argument("--label", required=True)
    a = ap.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    checker = load(a.checker) if a.checker and Path(a.checker).exists() else {}
    md, agreed = build(load(a.queue), checker, load(a.claude), load(a.astra), label=a.label, per_field=a.per_field)
    write_text(Path(a.out_md), md)
    if a.out_agreed and not a.per_field:
        write_text(Path(a.out_agreed), json.dumps(agreed, indent=1, ensure_ascii=False))
    print(md.splitlines()[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_threeway_sheet.py -q`
Expected: 2 passed

- [ ] **Step 5: Regenerate one historical sheet to check parity, then commit**

Run: `PYTHONPATH=. .venv/Scripts/python.exe tools/threeway_sheet.py --queue runs/cycle-004-shard-02/review-round-4.json --checker runs/cycle-004-shard-02/review-round-4-checker.json --claude runs/cycle-004-shard-02/review-round-4-decisions-claude.json --astra runs/cycle-004-shard-02/review-round-4-decisions-astra.json --out-md /tmp/s4.md --label "parity check"`
Expected: the printed line says `23 cards. Claude and Astra agree on 17; disagree on 6.` (the committed sheet's numbers). Do not commit `/tmp/s4.md`.

```bash
git add tools/threeway_sheet.py tests/test_threeway_sheet.py
git commit -m "tools/threeway_sheet.py: the three-way sheet as a tool (one-field and per-field modes)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 8: the sampler, the blind export, the audit brief, and the first-pass audit mode

**Files:**
- Create: `tools/draw_audit_sample.py`, `reports/review-audit-brief.md`
- Modify: `tools/export_review_cards.py` (`markdown_for`, `main`: `--audit`), `tools/first_pass_codex.py` (`--audit`, `--workdir`; `parse_decisions_audit`), `corpus_engine/reader/providers/codex_cli.py:31` (`cwd` parameter)
- Test: `tests/test_audit_tools.py`

**Interfaces:**
- Consumes: `LedgerView` (`state.order`, `state.records`, `reviewed`), `corpus_engine.reader.sources.StoreCaseSource.fetch(ids) -> [CaseText(case_id, norm_text)]`, `corpus_engine.store.connect()`, `Ledger.log.head()`, `summary.ledger_content_sha256`.
- Produces: `draw_audit_sample.draw(view, *, seed: int, n: int, texts: Mapping[int, str], scores: Mapping[int, float], cells: Mapping[int, str], head_seq: int, content_sha256: str, tool_revision: str, brief_sha256: str, drawn_at: str) -> tuple[dict, dict]` returning `(sample_manifest, audit_queue)`; `export_review_cards.markdown_for(cards, run_id, *, part=None, audit=False)`; `first_pass_codex.parse_decisions_audit(text, card) -> list[dict]`; `CodexCliProvider(cli_model, *, cwd=None, ...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit_tools.py
"""The audit draw, the blind card export, and the first-pass tool's audit mode."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import draw_audit_sample as das
import export_review_cards as erc
import first_pass_codex as fp
from corpus_engine.reader.model import Response


class _View:
    def __init__(self, records, reviewed=()):
        self.state = type("S", (), {})(); self.state.records = records; self.state.order = sorted(records)
        self._r = set(reviewed)
    def reviewed(self, cid): return cid in self._r


def _rec(cid, **o):
    r = {"case_id": cid, "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
         "characterization": "lodging", "under_thirty_days": None, "owner_freedom_characterization": None,
         "restriction_nature": None, "duration_of_occupancy": "weeks", "quotes": [], "holding_summary": "h",
         "cite": f"{cid} A. 1", "name": "A v. B", "court": "Ct.", "jurisdiction": "N.Y.", "year": 1900,
         "review": {"basis": {"run_id": "run-a", "prompt_version": "mapper-v3"}}}
    r.update(o); return r


def _draw(seed=7, n=3):
    records = {i: _rec(i) for i in range(1, 11)}
    records[5]["relevant"] = False
    view = _View(records, reviewed={6})
    texts = {i: f"opinion {i}" for i in records}
    return das.draw(view, seed=seed, n=n, texts=texts, scores={i: 0.5 for i in records},
                    cells={i: "1900-1930|N.Y." for i in records}, head_seq=100, content_sha256="c" * 64,
                    tool_revision="g", brief_sha256="b", drawn_at="2026-09-12T00:00:00Z")


def test_draw_is_deterministic_and_excludes_irrelevant_and_reviewed_records():
    m1, q1 = _draw(); m2, _ = _draw()
    assert m1["records"] == m2["records"] and m1["frame_size"] == 8          # 10 minus 5 (irrelevant) minus 6 (reviewed)
    ids = [r["case_id"] for r in m1["records"]]
    assert len(ids) == 3 and 5 not in ids and 6 not in ids
    assert m1["seed"] == 7 and m1["method"] == "random.Random(seed).sample" and len(m1["frame_sha256"]) == 64
    r0 = m1["records"][0]
    assert r0["record"]["polarity"] == "favorable" and r0["reader_run_id"] == "run-a" and r0["prompt_version"] == "mapper-v3"
    assert r0["band"] == "0.50-0.55" and len(r0["opinion_sha256"]) == 64
    card = q1["sections"]["H"][0]
    assert q1["run_id"] == "audit-cycle-004" and card["decide_fields"] == ["relevant", "polarity", "who_was_letting"]
    assert "values" not in card and "quotes" not in card and "holding_summary" not in card and card["cite"]


def test_draw_refuses_n_larger_than_the_frame():
    with pytest.raises(ValueError, match="frame has 8"):
        _draw(n=9)


def test_blind_markdown_carries_only_identity_and_opinion():
    card = {"case_id": 1, "section": "H", "section_title": "Audit sample", "cite": "1 A. 1", "name": "A v. B",
            "court": "Ct.", "jurisdiction": "N.Y.", "year": 1900, "decide_fields": ["relevant", "polarity", "who_was_letting"],
            "courtlistener_url": "https://www.courtlistener.com/?q=x", "opinion_text": "she let the room",
            "reader": {"polarity": "favorable"}, "checker": {"polarity": "adverse"}, "quotes": [{"text": "q"}],
            "holding_summary": "SECRET", "decide_field": "polarity"}
    md = erc.markdown_for([card], "audit-cycle-004", audit=True)
    assert "1 A. 1" in md and "she let the room" in md and "Decide: **relevant, polarity, who_was_letting**" in md
    for leak in ("favorable", "adverse", "SECRET", "Reader:", "Checker:", "Quotes"):
        assert leak not in md


def _card():
    return {"case_id": 9, "section": "H", "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9",
            "name": "n", "court": "c", "jurisdiction": "j", "year": 1, "courtlistener_url": "u", "opinion_text": "t", "section_title": "H"}


def test_audit_parse_requires_three_entries_or_one_withdrawal_or_one_unresolved():
    ok = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": "a"},
                     {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "note": "b"},
                     {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "unclear", "note": "c"}])
    got = fp.parse_decisions_audit(ok, _card())
    assert [(d["field"], d["value"]) for d in got] == [("relevant", True), ("polarity", "adverse"), ("who_was_letting", "unclear")]
    wd = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": False, "note": "not letting"}])
    assert fp.parse_decisions_audit(wd, _card()) == [{"case_id": 9, "field": "relevant", "decision": "set", "value": False, "note": "not letting"}]
    un = json.dumps([{"case_id": 9, "field": "relevant", "decision": "unresolved", "note": "garbled"}])
    assert fp.parse_decisions_audit(un, _card())[0]["decision"] == "unresolved"
    with pytest.raises(ValueError, match="three entries"):
        fp.parse_decisions_audit(json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": ""}]), _card())
    with pytest.raises(ValueError, match="duplicate"):
        fp.parse_decisions_audit(json.dumps(json.loads(ok)[:2] + [json.loads(ok)[1]]), _card())
    with pytest.raises(ValueError, match="keep"):
        fp.parse_decisions_audit(json.dumps([dict(json.loads(ok)[0], decision="keep")] + json.loads(ok)[1:]), _card())
    with pytest.raises(ValueError, match="vocabulary"):
        fp.parse_decisions_audit(json.dumps(json.loads(ok)[:2] + [dict(json.loads(ok)[2], value="lodger")]), _card())


class _Scripted:
    def __init__(self, reply): self.reply, self.prompts = reply, []
    def complete(self, req):
        self.prompts.append(req.user)
        return Response(self.reply, 1, 1, None, {"provider": "codex-cli"}, "stop", "0")
    def version(self): return "0"


def test_audit_run_writes_three_entries_per_card_and_resumes_by_brief_hash(tmp_path):
    reply = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": "a"},
                        {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "note": "b"},
                        {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "unclear", "note": "c"}])
    out = tmp_path / "d.json"
    man = fp.run_first_pass([_card()], brief="B1", handoff="", provider=_Scripted(reply), out_path=out, log=lambda *_: None, audit=True)
    assert man["decided"] == 1 and len(json.loads(out.read_text(encoding="utf-8"))) == 3
    assert len(man["brief_sha256"]) == 64
    p2 = _Scripted(reply)
    fp.run_first_pass([_card()], brief="B1", handoff="", provider=p2, out_path=out, log=lambda *_: None, audit=True)
    assert p2.prompts == []                                   # same brief: not re-asked
    p3 = _Scripted(reply)
    fp.run_first_pass([_card()], brief="B2", handoff="", provider=p3, out_path=out, log=lambda *_: None, audit=True)
    assert len(p3.prompts) == 1                               # changed brief: re-asked


def test_codex_provider_passes_cwd_to_the_runner():
    from corpus_engine.reader.providers.codex_cli import CodexCliProvider
    from corpus_engine.reader.model import Request
    seen = {}
    def runner(argv, **kw):
        seen.update(kw)
        class P: returncode = 0; stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}\n'; stderr = ""
        return P()
    prov = CodexCliProvider("m", runner=runner, cwd="/iso")
    prov.complete(Request(pin={}, user="hi"))
    assert seen.get("cwd") == "/iso"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_tools.py -q`
Expected: FAIL with `ModuleNotFoundError: draw_audit_sample`

- [ ] **Step 3: Implement the sampler**

```python
# tools/draw_audit_sample.py
"""Draw the frozen audit sample (spec §4.1): 150 machine-only relevant records, simple random,
seeded, with the judged record at draw time, the opinion texts, and a blind audit queue.

  PYTHONPATH=. .venv/Scripts/python tools/draw_audit_sample.py --seed 20260912 --n 150 --out runs/audit-cycle-004

Never rewrites an existing --out directory: a redraw is a new directory."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.domain import load_domain                 # noqa: E402
from corpus_engine.ledger import open_ledger                 # noqa: E402
from corpus_engine.evaluation.summary import ledger_content_sha256   # noqa: E402
from export_review_cards import write_text, courtlistener_url        # noqa: E402

RUN_ID = "audit-cycle-004"
DECIDE_FIELDS = ["relevant", "polarity", "who_was_letting"]
JUDGED = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy", "characterization",
          "under_thirty_days", "owner_freedom_characterization", "restriction_nature")
BAND = 0.05


def _band(score: float) -> str:
    lo = (score // BAND) * BAND
    return f"{lo:.2f}-{lo + BAND:.2f}"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def draw(view, *, seed: int, n: int, texts: Mapping[int, str], scores: Mapping[int, float],
         cells: Mapping[int, str], head_seq: int, content_sha256: str, tool_revision: str,
         brief_sha256: str, drawn_at: str) -> tuple[dict, dict]:
    frame = sorted(cid for cid in view.state.order
                   if view.state.records[cid].get("relevant") is True and not view.reviewed(cid))
    if n > len(frame):
        raise ValueError(f"the frame has {len(frame)} records; cannot draw {n}")
    ids = random.Random(seed).sample(frame, n)
    records, cards = [], []
    for cid in ids:
        r = view.state.records[cid]
        basis = ((r.get("review") or {}).get("basis") or {})
        records.append({"case_id": cid,
                        "record": {**{f: r.get(f) for f in JUDGED}, "quotes": list(r.get("quotes") or ()),
                                   "holding_summary": r.get("holding_summary")},
                        "reader_run_id": basis.get("run_id"), "prompt_version": basis.get("prompt_version"),
                        "rank_score": scores.get(cid), "band": _band(float(scores.get(cid) or 0.0)),
                        "cell": cells.get(cid), "opinion_sha256": _sha(texts[cid])})
        cards.append({"case_id": cid, "section": "H", "reason": "audit_sample", "other_reasons": [],
                      "decide_fields": list(DECIDE_FIELDS), "cite": r.get("cite"), "name": r.get("name"),
                      "court": r.get("court"), "jur": r.get("jurisdiction"), "year": r.get("year")})
    manifest = {"drawn_at": drawn_at, "ledger_head_seq": head_seq, "ledger_content_sha256": content_sha256,
                "frame_size": len(frame), "frame_sha256": _sha("\n".join(map(str, frame))), "seed": seed,
                "method": "random.Random(seed).sample", "n": n, "tool_revision": tool_revision,
                "brief_sha256": brief_sha256, "records": records}
    queue = {"run_id": RUN_ID, "cap": n, "titles": {"H": "Audit sample: relevance, polarity, who was letting"},
             "sections": {"H": cards}, "deferred": []}
    return manifest, queue


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True); ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--out", default=f"runs/{RUN_ID}")
    ap.add_argument("--brief", default="reports/review-audit-brief.md")
    ap.add_argument("--pool-run", default="cycle-004-shard-02", help="run whose batches carry rank scores")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        sys.exit(f"{out} exists; a redraw is a new directory")
    from corpus_engine import store
    from corpus_engine.reader.sources import StoreCaseSource
    dom = load_domain(); led = open_ledger(domain=dom); view = led.view()
    frame_ids = [cid for cid in view.state.order if view.state.records[cid].get("relevant") is True and not view.reviewed(cid)]
    conn = store.connect()
    texts = {t.case_id: t.norm_text for t in StoreCaseSource(conn).fetch(frame_ids)}
    scores, cells = {}, {}
    for p in sorted((ROOT / "runs" / a.pool_run / "batches").glob("batch-*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        for c in b.get("cases") or ():
            scores[int(c["case_id"])] = c.get("rank_score"); cells[int(c["case_id"])] = f"{b['era_partition']}|{b['jurisdiction']}"
    for cid in frame_ids:                                  # records from earlier cycles: cell from the store row
        if cid not in cells:
            row = conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE case_id=?", (cid,)).fetchone()
            cells[cid] = f"{row[0]}|{row[1]}" if row else None
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    from datetime import datetime, timezone
    manifest, queue = draw(view, seed=a.seed, n=a.n, texts=texts, scores=scores, cells=cells,
                           head_seq=led.log.head(), content_sha256=ledger_content_sha256(led.dir),
                           tool_revision=rev, brief_sha256=hashlib.sha256(Path(a.brief).read_bytes()).hexdigest(),
                           drawn_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    write_text(out / "sample-manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
    write_text(out / "audit-queue.json", json.dumps(queue, indent=1, ensure_ascii=False))
    for r in manifest["records"]:
        write_text(out / "opinions" / f"{r['case_id']}.txt", texts[r["case_id"]])
    print(f"frame {manifest['frame_size']} (sha {manifest['frame_sha256'][:12]}), drew {a.n} with seed {a.seed} "
          f"at seq {manifest['ledger_head_seq']} -> {out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement the blind export**

In `tools/export_review_cards.py`, change `markdown_for`'s signature to `markdown_for(cards, run_id, *, part=None, audit=False)` and add, right after the section heading logic at the top of the per-card loop:

```python
        if audit:
            lines.append(f"### {c.get('cite') or c['case_id']} - {c.get('name') or ''} [{c['case_id']}]")
            lines.append(f"- Court: {c.get('court') or '?'} - {c.get('jurisdiction') or '?'} - {c.get('year') or '?'}")
            lines.append(f"- Decide: **{', '.join(c.get('decide_fields') or [])}**")
            lines.append(f"- CourtListener: {c['courtlistener_url']}")
            lines.append(""); lines.append("#### Opinion text"); lines.append("")
            lines.append(c.get("opinion_text") or ""); lines.append("")
            continue
```

In `cards_from_queue`, carry `decide_fields` when the queue card has it (`"decide_fields": list(c.get("decide_fields") or ())` beside `decide_field`, and `"decide_field": c.get("decide_field") or (c.get("decide_fields") or ["polarity"])[0]`). The section table `SECTIONS` in `corpus_engine/mapper/queue.py` has no `H`; `cards_from_queue` iterates `SECTIONS`, so add to it a fallback: after the `SECTIONS` loop, iterate any section key in `queue_doc["sections"]` not in `SECTIONS` (title from `titles`). In `main`, add `--audit` (`action="store_true"`), which forces `--full-text` and passes `audit=True` to `markdown_parts` (add the keyword through `markdown_parts(cards, run_id, n=1, *, audit=False)`), and in audit mode strips every key but `case_id, section, section_title, name, cite, court, jurisdiction, year, decide_fields, courtlistener_url, opinion_text` from the JSON twin before writing.

- [ ] **Step 5: Implement the first-pass audit mode and the provider `cwd`**

In `corpus_engine/reader/providers/codex_cli.py`, add `cwd: str | Path | None = None` to `__init__` (store as `self.cwd`) and pass `cwd=self.cwd` in the `runner(...)` call inside `complete` (and in `version`).

In `tools/first_pass_codex.py`:

```python
AUDIT_FIELDS = ("relevant", "polarity", "who_was_letting")
AUDIT_CARD = """## This call

You are given ONE card with the full opinion text and nothing else about the case. From the
opinion alone, decide `relevant` (true|false) and, if true, `polarity` and `who_was_letting`.
Reply with exactly one JSON list: three entries {"case_id", "field", "decision": "set", "value",
"note"} (relevant, polarity, who_was_letting) when relevant is true; exactly one entry with
"field": "relevant", "value": false when it is not a letting case; or exactly one entry
{"case_id", "field": "relevant", "decision": "unresolved", "note"} if the text is unreadable.
No keep, adopt or unsure. Nothing but the JSON list is needed in the reply.
"""


def parse_decisions_audit(text: str, card: dict) -> list[dict]:
    objs = _json_objects(text)                       # accepts a bare list too: _json_objects unwraps single-object lists,
    # so read the list directly here:
    lst = None
    for cand in (_FENCE.findall(text) or []) + [text]:
        i = cand.find("[")
        while i >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(cand, i); lst = obj; break
            except ValueError:
                i = cand.find("[", i + 1)
        if lst is not None:
            break
    if not isinstance(lst, list) or not lst:
        raise ValueError("no JSON list of decisions in the reply")
    entries = []
    for d in lst:
        if str(d.get("case_id")) != str(card["case_id"]):
            raise ValueError(f"case_id {d.get('case_id')!r} is not the card's ({card['case_id']})")
        if d.get("decision") == "unresolved":
            return [{"case_id": card["case_id"], "field": "relevant", "decision": "unresolved",
                     "note": str(d.get("note") or "").strip()}]
        if d.get("decision") != "set":
            raise ValueError(f"decision {d.get('decision')!r}: audit entries are set only, never keep/adopt/unsure")
        if d.get("field") not in AUDIT_FIELDS:
            raise ValueError(f"field {d.get('field')!r} is not one of {AUDIT_FIELDS}")
        entries.append({"case_id": card["case_id"], "field": d["field"], "decision": "set",
                        "value": _checked_value(d["field"], d.get("value")), "note": str(d.get("note") or "").strip()})
    fields = [e["field"] for e in entries]
    if len(set(fields)) != len(fields):
        raise ValueError("duplicate field in the reply")
    rel = next((e for e in entries if e["field"] == "relevant"), None)
    if rel is None:
        raise ValueError("no relevant entry")
    if rel["value"] is False:
        if len(entries) != 1:
            raise ValueError("a withdrawal is exactly one entry")
        return entries
    if sorted(fields) != sorted(AUDIT_FIELDS):
        raise ValueError("a relevant card needs exactly three entries: relevant, polarity, who_was_letting")
    return sorted(entries, key=lambda e: AUDIT_FIELDS.index(e["field"]))
```

`run_first_pass` gains `audit: bool = False`: in audit mode the prompt is `brief + AUDIT_CARD + the card rendered with markdown_for([card], "", audit=True)` (no handoff), the reply goes through `parse_decisions_audit` and every returned entry is appended to `decided`, resume is keyed on `(case_id, brief_sha256)` — the out file's sidecar manifest records `brief_sha256 = sha256(brief)`, and when it differs from the current brief's hash the existing decisions are moved to `<out>-superseded-<oldhash8>.json` and every card is asked again; the manifest returned includes `"brief_sha256"`. `build_parser` gains `--audit` and `--workdir` (passed as `CodexCliProvider(a.model, timeout=a.timeout, cwd=a.workdir)`); `main` in audit mode does not require `--handoff`.

- [ ] **Step 6: Write the audit brief**

`reports/review-audit-brief.md`: copy the standing brief's "What the corpus is about" paragraph, the polarity and relevance definitions, and the `polarity` / `who_was_letting` / `relevant` vocabulary lines from `reports/review-first-pass-brief.md` verbatim; replace everything from "The four decisions" onward with:

```markdown
## The decision

You see ONE card at a time: the case's citation, court and year, a CourtListener link, and the
full opinion text. Nothing else - no earlier reading, no checker. From the opinion alone:

1. `relevant`: true if the opinion bears on compensated occupancy of another's dwelling or rooms,
   its legal character, or its regulation; false otherwise (commercial leases of shops or farms,
   mortgage foreclosures, hotel torts with no letting question, "boarder" as incidental colour).
2. If relevant: `polarity` (favorable | adverse | mixed, judged from the OWNER's freedom to let;
   mixed only when both sides are holdings, otherwise follow the holding) and `who_was_letting`
   (householder | commercial_operator | non_resident_owner | unclear).

Each entry carries a one-line `note` quoting the fact in the opinion that decides it.

## Output

A JSON list. Relevant: exactly three entries, `{"case_id": <id>, "field": "relevant", "decision":
"set", "value": true, "note": "..."}`, then the same shape for `polarity` and `who_was_letting`.
Not a letting case: exactly one entry with `"field": "relevant", "value": false`. Unreadable
text: exactly one entry `{"case_id": <id>, "field": "relevant", "decision": "unresolved", "note":
"..."}`. Never `keep`, `adopt` or `unsure`; commit to a value.
```

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_tools.py tests/test_first_pass_codex.py tests/test_map_review_tools.py -q`
Expected: all pass (the existing export and first-pass tests are unchanged in behaviour).

- [ ] **Step 8: Commit**

```bash
git add tools/draw_audit_sample.py tools/export_review_cards.py tools/first_pass_codex.py corpus_engine/reader/providers/codex_cli.py reports/review-audit-brief.md tests/test_audit_tools.py
git commit -m "audit: the frozen sample draw, blind card export, audit brief, first-pass audit mode with an isolated workdir" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 9: the audit page (lock-then-reveal)

**Files:**
- Modify: `tools/make_map_review.py` (`main`: `--audit`; new `build_audit_page(queue, out_stem, *, opinions: Mapping[int, str], claude: list, astra: list, checker: dict) -> tuple`; new `AUDIT_TMPL`)
- Test: `tests/test_audit_page.py`

**Interfaces:**
- Consumes: the audit queue (Task 8), the opinions directory, the two readers' decisions files (Task 8's shape: three entries or one withdrawal or one unresolved per card), the optional checker file; `_mr.STATE_MARKER`, `_mr.TB64_MARKER`, `write_text`, `esc`.
- Produces: a self-saving page whose `review-state` block holds entries `{case_id, field, decision: "set", value, initial_value, locked_at, revised_reason, note}`; `make_map_review.read_audit_state(html) -> list[dict]` (used by Task 10) which returns the entries and refuses a page whose entry lacks `locked_at`.

Page behaviour (all in `AUDIT_TMPL`, same markers and save path as `CONTENT_TMPL`):

- `DOC = {{DATA}}` carries `{"run_id", "cards": [{case_id, cite, name, court, jur, year, opinion}], "readers": {case_id: {"claude": [...entries], "astra": [...], "checker": {...values}|null}}}`. The draw-time values are NOT in `DOC`.
- Each card: identity line, CourtListener link, the opinion in a scrollable `<pre class="op">`, three radio groups (`rel-<id>`: true/false; `pol-<id>`: favorable/adverse/mixed; `who-<id>`: householder/commercial_operator/non_resident_owner/unclear), a note input, a **Lock** button, and a **Cannot read this opinion** button (records `{field: "relevant", decision: "unresolved"}` and locks).
- Lock is enabled only when `relevant` is answered and, if true, both other groups are answered. Locking writes three (or one) state entries with `initial_value = value`, `locked_at = new Date().toISOString()`, disables the radios, and reveals the `.reveal` panel: a table with rows claude / astra / checker and columns relevant / polarity / who_was_letting plus each reader's notes.
- After reveal, a **Revise** button re-enables the radios and shows a required `revised_reason` text input; confirming writes the new `value`s, keeps `initial_value` and `locked_at`, and stores `revised_reason`. A revision that leaves every value unchanged is refused with a message.
- The status bar shows `locked / total` and unsaved changes; **Save decisions** republishes as today (`rebuildDoc`, `claude.use('artifact')`), **Copy JSON** copies the state.
- State loader: entries keyed `case_id::field`; a loaded page renders locked cards as locked with the reveal panel open.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit_page.py
"""The audit page: blind until locked, reveal after, revisions keep the initial answer."""
import json
import re
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_map_review as mmr


def _queue():
    return {"run_id": "audit-cycle-004", "cap": 2, "titles": {"H": "Audit sample"}, "deferred": [],
            "sections": {"H": [{"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9",
                                "name": "A v. B", "court": "Ct.", "jur": "N.Y.", "year": 1900},
                               {"case_id": 10, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "10 A. 10",
                                "name": "C v. D", "court": "Ct.", "jur": "N.Y.", "year": 1901}]}}


def _readers():
    e = lambda cid, f, v, n: {"case_id": cid, "field": f, "decision": "set", "value": v, "note": n}
    claude = [e(9, "relevant", True, "cn1"), e(9, "polarity", "adverse", "cn2"), e(9, "who_was_letting", "householder", "cn3"),
              e(10, "relevant", False, "cn4")]
    astra = [e(9, "relevant", True, "an1"), e(9, "polarity", "favorable", "an2"), e(9, "who_was_letting", "householder", "an3"),
             e(10, "relevant", False, "an4")]
    return claude, astra


def test_page_carries_opinions_and_reader_answers_but_no_draw_time_values(tmp_path):
    claude, astra = _readers()
    html_path, _ = mmr.build_audit_page(_queue(), tmp_path / "audit", opinions={9: "she let the room", 10: "a store lease"},
                                        claude=claude, astra=astra, checker={"9": {"values": {"polarity": "adverse"}}})
    html = html_path.read_text(encoding="utf-8")
    doc = json.loads(re.search(r"const DOC = (.*?);\n", html).group(1))
    assert [c["case_id"] for c in doc["cards"]] == [9, 10] and doc["cards"][0]["opinion"] == "she let the room"
    assert doc["readers"]["9"]["claude"][1]["value"] == "adverse" and doc["readers"]["9"]["checker"]["polarity"] == "adverse"
    assert "draw_time" not in html and "record" not in doc
    for s in ("name=\"rel-", "name=\"pol-", "name=\"who-", "Lock", "Cannot read this opinion", "Revise", "class=\"reveal\""):
        assert s in html
    assert 'id="review-state">[]</script>' in html


def test_read_audit_state_returns_locked_entries_and_refuses_unlocked_ones(tmp_path):
    claude, astra = _readers()
    html_path, _ = mmr.build_audit_page(_queue(), tmp_path / "audit", opinions={9: "x", 10: "y"}, claude=claude, astra=astra, checker={})
    html = html_path.read_text(encoding="utf-8")
    state = [{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "initial_value": True, "locked_at": "t", "revised_reason": None, "note": ""},
             {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "initial_value": "favorable", "locked_at": "t", "revised_reason": "the note", "note": ""},
             {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "householder", "initial_value": "householder", "locked_at": "t", "revised_reason": None, "note": ""}]
    saved = html.replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps(state) + '</script>')
    got = mmr.read_audit_state(saved)
    assert [(d["field"], d["value"], d["initial_value"]) for d in got] == [("relevant", True, True), ("polarity", "adverse", "favorable"), ("who_was_letting", "householder", "householder")]
    bad = html.replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps([dict(state[0], locked_at=None)]) + '</script>')
    with pytest.raises(ValueError, match="not locked"):
        mmr.read_audit_state(bad)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_page.py -q`
Expected: FAIL with `AttributeError: build_audit_page`

- [ ] **Step 3: Implement**

Add to `tools/make_map_review.py`:

```python
AUDIT_FIELDS = ("relevant", "polarity", "who_was_letting")
AUDIT_VOCAB = {"relevant": ["true", "false"], "polarity": ["favorable", "adverse", "mixed"],
               "who_was_letting": ["householder", "commercial_operator", "non_resident_owner", "unclear"]}


def build_audit_page(queue: dict, out_stem: Path, *, opinions: Mapping[int, str], claude: Sequence[dict],
                     astra: Sequence[dict], checker: dict | None = None) -> tuple:
    cards = [{"case_id": c["case_id"], "cite": c.get("cite"), "name": c.get("name"), "court": c.get("court"),
              "jur": c.get("jur"), "year": c.get("year"), "opinion": opinions[int(c["case_id"])]}
             for c in queue["sections"]["H"]]
    readers: dict[str, dict] = {}
    for name, lst in (("claude", claude), ("astra", astra)):
        for d in lst or ():
            readers.setdefault(str(d["case_id"]), {"claude": [], "astra": [], "checker": None})[name].append(d)
    for k, v in (checker or {}).items():
        readers.setdefault(str(k), {"claude": [], "astra": [], "checker": None})["checker"] = (v or {}).get("values")
    data = {"run_id": queue["run_id"], "cards": cards, "readers": readers}
    content = (AUDIT_TMPL.replace("{{DATA}}", json.dumps(data).replace("</", "<\\/"))
               .replace("{{VOCAB}}", json.dumps(AUDIT_VOCAB)).replace("{{RUN}}", esc(queue["run_id"]))
               .replace("{{N_CARDS}}", str(len(cards))))
    full = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body>" + content + "</body></html>")
    tb64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    out = content.replace(TB64_MARKER, tb64).replace(f'"{STATE_MARKER}"', "[]")
    html_path = Path(str(out_stem) + ".html")
    write_text(html_path, out)
    return html_path, len(tb64)


def read_audit_state(html: str) -> list[dict]:
    m = _mr.STATE_RE.search(html)
    if not m:
        raise ValueError("no review-state block")
    raw = json.loads(m.group(1))
    if not isinstance(raw, list):
        raise ValueError("review-state is not a list")
    out = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict) or d.get("field") not in AUDIT_FIELDS:
            raise ValueError(f"entry {i}: not an audit entry")
        if d.get("decision") not in ("set", "unresolved"):
            raise ValueError(f"entry {i}: decision {d.get('decision')!r}")
        if not d.get("locked_at"):
            raise ValueError(f"entry {i} (case {d.get('case_id')}): not locked")
        out.append({"case_id": int(d["case_id"]), "field": d["field"], "decision": d["decision"],
                    "value": d.get("value"), "initial_value": d.get("initial_value"), "locked_at": d["locked_at"],
                    "revised_reason": d.get("revised_reason"), "note": d.get("note") or ""})
    return out
```

`AUDIT_TMPL` (a raw string beside `CONTENT_TMPL`): reuse `CONTENT_TMPL`'s `<style>`, top bar (`status-top`, `save-top`, `copy-top`), and the `save`/`copyJson`/`rebuildDoc` functions verbatim; the card renderer is:

```javascript
const DOC = {{DATA}};
const VOCAB = {{VOCAB}};
const TB64 = "__TEMPLATE_B64__";
const FIELDS = ['relevant','polarity','who_was_letting'];
let state = {};
try { const raw = JSON.parse(document.getElementById('review-state').textContent);
      if (Array.isArray(raw)) for (const d of raw) if (d && d.case_id != null && d.field) state[d.case_id + '::' + d.field] = d; } catch(e) {}
let dirty = 0;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const clq = c => 'https://www.courtlistener.com/?q=%22' + encodeURIComponent(String(c||'')) + '%22';
const radios = (name, opts) => opts.map(o => `<label><input type="radio" name="${name}" value="${o}"> ${o}</label>`).join(' ');
const locked = it => !!(state[it.case_id + '::relevant'] || {}).locked_at;
const valueOf = (div, name) => { const r = div.querySelector(`input[name="${name}"]:checked`); return r ? r.value : null; };
const conv = (f, v) => f === 'relevant' ? v === 'true' : v;

function readerTable(it){
  const r = DOC.readers[String(it.case_id)] || {claude: [], astra: [], checker: null};
  const cell = (list, f) => { const e = (list || []).find(x => x.field === f); if (!e) return (list||[]).some(x => x.field === 'relevant' && x.value === false) ? '&mdash;' : ''; return esc(e.decision === 'unresolved' ? 'unresolved' : String(e.value)); };
  const notes = list => (list || []).map(e => `<div class="who">${esc(e.field)}: ${esc(e.note || '')}</div>`).join('');
  return `<div class="reveal"><table><tr><th></th><th>relevant</th><th>polarity</th><th>who_was_letting</th></tr>
    <tr><td>Claude</td><td>${cell(r.claude,'relevant')}</td><td>${cell(r.claude,'polarity')}</td><td>${cell(r.claude,'who_was_letting')}</td></tr>
    <tr><td>Astra</td><td>${cell(r.astra,'relevant')}</td><td>${cell(r.astra,'polarity')}</td><td>${cell(r.astra,'who_was_letting')}</td></tr>
    ${r.checker ? `<tr><td>Checker</td><td>${esc(String(r.checker.relevant))}</td><td>${esc(String(r.checker.polarity))}</td><td></td></tr>` : ''}
    </table><div>Claude notes</div>${notes(r.claude)}<div>Astra notes</div>${notes(r.astra)}</div>`;
}

function card(it){
  const div = document.createElement('div'); div.className = 'item'; div.id = 'c-' + it.case_id;
  const id = it.case_id;
  div.innerHTML = `
    <div><span class="nm">${esc(it.name || '')}</span></div>
    <div class="cite"><a href="${clq(it.cite)}" target="_blank" rel="noopener">${esc(it.cite || '')}</a></div>
    <div class="meta">${esc(it.court || '')} &middot; ${esc(it.jur || '')} &middot; ${esc(it.year || '')} &middot; case ${esc(id)}</div>
    <pre class="op">${esc(it.opinion)}</pre>
    <div class="controls">
      <div>relevant: ${radios('rel-' + id, VOCAB.relevant)}</div>
      <div class="dep">polarity: ${radios('pol-' + id, VOCAB.polarity)}</div>
      <div class="dep">who_was_letting: ${radios('who-' + id, VOCAB.who_was_letting)}</div>
      <input type="text" class="note" placeholder="note (optional)">
      <button class="lock" disabled>Lock</button>
      <button class="unres">Cannot read this opinion</button>
      <button class="revise" hidden>Revise</button>
      <input type="text" class="why" placeholder="reason for the revision (required)" hidden>
      <button class="confirm" hidden>Confirm revision</button>
    </div>
    <div class="revealslot"></div>`;
  const lockBtn = div.querySelector('.lock'), unres = div.querySelector('.unres'), rev = div.querySelector('.revise');
  const why = div.querySelector('.why'), confirm = div.querySelector('.confirm'), note = div.querySelector('.note');
  const inputs = div.querySelectorAll('input[type=radio]');
  const complete = () => { const r = valueOf(div, 'rel-' + id); return r === 'false' || (r === 'true' && valueOf(div, 'pol-' + id) && valueOf(div, 'who-' + id)); };
  const refresh = () => { lockBtn.disabled = !complete(); div.querySelectorAll('.dep').forEach(d => d.style.opacity = valueOf(div, 'rel-' + id) === 'false' ? 0.4 : 1); };
  inputs.forEach(r => r.onchange = refresh);
  const write = (initial) => {
    const rel = valueOf(div, 'rel-' + id) === 'true';
    const vals = {relevant: rel, polarity: rel ? valueOf(div, 'pol-' + id) : null, who_was_letting: rel ? valueOf(div, 'who-' + id) : null};
    for (const f of FIELDS) {
      if (!rel && f !== 'relevant') { delete state[id + '::' + f]; continue; }
      const prev = state[id + '::' + f] || {};
      state[id + '::' + f] = {case_id: id, field: f, decision: 'set', value: vals[f],
        initial_value: initial ? vals[f] : (prev.initial_value ?? vals[f]),
        locked_at: initial ? new Date().toISOString() : prev.locked_at, revised_reason: initial ? null : why.value, note: note.value || ''};
    }
  };
  const showLocked = () => { inputs.forEach(r => r.disabled = true); lockBtn.hidden = true; unres.hidden = true; rev.hidden = false;
    div.querySelector('.revealslot').innerHTML = readerTable(it); div.classList.add('decided'); };
  lockBtn.onclick = () => { write(true); showLocked(); dirty++; updateBar(); };
  unres.onclick = () => { state[id + '::relevant'] = {case_id: id, field: 'relevant', decision: 'unresolved', value: null, initial_value: null,
      locked_at: new Date().toISOString(), revised_reason: null, note: note.value || ''}; for (const f of ['polarity','who_was_letting']) delete state[id + '::' + f]; showLocked(); dirty++; updateBar(); };
  rev.onclick = () => { inputs.forEach(r => r.disabled = false); why.hidden = false; confirm.hidden = false; rev.hidden = true; };
  confirm.onclick = () => {
    if (!why.value.trim()) { why.focus(); return; }
    const before = FIELDS.map(f => JSON.stringify((state[id + '::' + f] || {}).value));
    write(false);
    const after = FIELDS.map(f => JSON.stringify((state[id + '::' + f] || {}).value));
    if (before.join() === after.join()) { for (const s of ['status','status-top']) document.getElementById(s).textContent = 'Revision unchanged - nothing recorded.'; return; }
    inputs.forEach(r => r.disabled = true); why.hidden = true; confirm.hidden = true; rev.hidden = false; dirty++; updateBar();
  };
  // a loaded page: restore and lock
  const st = state[id + '::relevant'];
  if (st && st.locked_at) {
    if (st.decision === 'set') { div.querySelector(`input[name="rel-${id}"][value="${st.value}"]`).checked = true;
      for (const [f, n] of [['polarity','pol'],['who_was_letting','who']]) { const e = state[id + '::' + f]; if (e) { const r = div.querySelector(`input[name="${n}-${id}"][value="${e.value}"]`); if (r) r.checked = true; } } }
    note.value = st.note || ''; showLocked();
  }
  refresh();
  return div;
}
function decisions(){ const out = []; for (const it of DOC.cards) for (const f of FIELDS) { const d = state[it.case_id + '::' + f]; if (d) out.push(d); } return out; }
function updateBar(){ const done = DOC.cards.filter(locked).length;
  const txt = `${done}/${DOC.cards.length} locked` + (dirty ? ` · ${dirty} unsaved change${dirty > 1 ? 's' : ''}` : ' · saved');
  for (const id of ['status','status-top']) document.getElementById(id).textContent = txt; }
const root = document.getElementById('cards-H'); for (const it of DOC.cards) root.appendChild(card(it));
```

Add `--audit` to `main` (mutually exclusive with `--check`/`--build` is not needed: make it a third `mode` flag): reads `--queue`, `--opinions <dir>` (default `<queue dir>/opinions`), `--claude`, `--astra`, optional `--checker`, `--out-stem`; loads each opinion as `opinions[case_id] = (dir / f"{case_id}.txt").read_text(encoding="utf-8")`; calls `build_audit_page`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_page.py tests/test_map_review_tools.py -q`
Expected: all pass

- [ ] **Step 5: Verify the page headless**

Build a page from a two-card fixture (`.venv/Scripts/python.exe -c` with the test's `_queue()`/`_readers()`, opinions dir under the scratchpad), serve it with `python -m http.server 8765 --directory <dir>` and open it with the Playwright MCP (`browser_navigate` to `http://localhost:8765/audit.html?v=1`): click `relevant=true`, `polarity=adverse`, `who_was_letting=householder` on card 9, click Lock, assert via `browser_evaluate` that `document.querySelectorAll('.reveal').length === 1` and `JSON.parse(JSON.stringify(decisions())).length === 3` and the first entry has `locked_at`; click Revise, set polarity favorable, type a reason, Confirm, assert `decisions()[1].initial_value === 'adverse' && decisions()[1].value === 'favorable'`; check `browser_console_messages` is free of errors. Then `browser_close` and stop the server. Record the result in the task report.

- [ ] **Step 6: Commit**

```bash
git add tools/make_map_review.py tests/test_audit_page.py
git commit -m "audit page: blind three-field cards, lock-then-reveal, revisions keep the initial answer" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 10: the audit apply (three fields, confirm patches, drift check, outcomes)

**Files:**
- Modify: `tools/apply_map_review.py` (`--audit`, `audit_patches`, `drift_check`, `write_outcomes`)
- Test: `tests/test_audit_apply.py`

**Interfaces:**
- Consumes: `make_map_review.read_audit_state`, the sample manifest and audit queue (Task 8), the readers' decisions files, `Patch`, `Basis`, `open_ledger`, `arr._label`.
- Produces: `apply_map_review.drift_check(manifest: Mapping, records: Mapping[int, dict]) -> list[int]` (case ids whose current `relevant`, `polarity`, `who_was_letting` differ from the manifest's draw-time values); `apply_map_review.audit_patches(entries: Sequence[dict], records, reviewer: str, *, run_id: str) -> list[Patch]`; `apply_map_review.outcomes_doc(manifest, entries, *, claude, astra, checker, run_id, applied_seq_range, drift) -> dict` (spec §4.7 shape). CLI: `--audit --saved <page> --queue <audit-queue> --sample <manifest> --claude <f> --astra <f> [--checker <f>] --run-id audit-cycle-004 [--allow-drift 1,2] [--dry-run]`; `--assisted-by` with `--audit` exits 2.

Patch rules for one decided record (entries for `relevant`, and if true `polarity` and `who_was_letting`):
- `relevant: true`: `Patch(cid, "set", "relevant", True, why, basis)` even though it is already true (the explicit confirmation carries field-level human provenance), then `set polarity <value>` and `set who_was_letting <value>` (equal or not); a `review.notes` line per field: `"{tag}: {field} {old!r} -> {new!r} (audit, blind reading)"` or `"... confirmed {old!r} (audit, blind reading)"` when equal; if `revised_reason` is set, one more notes line `"{tag}: {field} revised after reveal from {initial!r}: {reason}"`; then `set review.status human-adjudicated`.
- `relevant: false`: the existing withdrawal cascade (`set relevant False`, `set polarity None`, `set who_was_letting None`, notes, status) plus the moot-flag clearing at the end of `patches_for` (reuse by calling `patches_for([{case_id, field: "relevant", decision: "set", value: False, note}], ...)` for that case).
- `unresolved`: no patches; listed.
- Every field decision clears `needs-review:<field>` through `arr._clear_flag`, as the ordinary path does.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit_apply.py
"""The audit apply: explicit set patches on all three fields, drift refusal, outcomes file."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import apply_map_review as ap
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger as real_open_ledger
from corpus_engine.ledger.types import Basis, Patch


def _rec(cid, **o):
    r = {"case_id": cid, "cite": f"{cid} A. 1", "name": "n", "court": "c", "jurisdiction": "N.Y.", "year": 1900,
         "era_partition": "1900-1930", "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
         "characterization": None, "under_thirty_days": None, "owner_freedom_characterization": None,
         "restriction_nature": None, "duration_of_occupancy": None, "quotes": [], "holding_summary": "h",
         "extraction_status": "ok", "review": {"status": "machine", "flags": ["needs-review:polarity"], "notes": []}}
    r.update(o); return r


def _manifest(records):
    return {"ledger_head_seq": 1, "frame_size": 3, "seed": 1, "n": len(records),
            "records": [{"case_id": r["case_id"], "record": {k: r[k] for k in ("relevant", "polarity", "who_was_letting")}}
                        for r in records]}


def _entry(cid, f, v, initial=None, reason=None, decision="set"):
    return {"case_id": cid, "field": f, "decision": decision, "value": v, "initial_value": v if initial is None else initial,
            "locked_at": "t", "revised_reason": reason, "note": ""}


def test_audit_patches_confirm_equal_values_with_reviewer_provenance_and_withdraw(tmp_path):
    dom = load_domain(); led = real_open_ledger(tmp_path / "ledger", domain=dom)
    recs = [_rec(1), _rec(2, polarity="mixed"), _rec(3)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    view = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "favorable"), _entry(1, "who_was_letting", "householder"),
               _entry(2, "relevant", True), _entry(2, "polarity", "adverse", initial="mixed", reason="the holding"), _entry(2, "who_was_letting", "unclear"),
               _entry(3, "relevant", False)]
    patches = ap.audit_patches(entries, view.state.records, "mmaldo2", run_id="audit-cycle-004")
    sets = [(p.case_id, p.field, p.new) for p in patches if p.op == "set" and p.field in ("relevant", "polarity", "who_was_letting")]
    assert (1, "relevant", True) in sets and (1, "polarity", "favorable") in sets and (1, "who_was_letting", "householder") in sets
    assert (2, "polarity", "adverse") in sets and (3, "relevant", False) in sets and (3, "polarity", None) in sets
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == "audit-cycle-004" for p in patches)
    real_open_ledger(tmp_path / "ledger", domain=dom).apply(patches, note="audit")
    after = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    assert after.provenance(1) == {"relevant": "human", "polarity": "human", "who_was_letting": "human"}
    assert after.reviewed(1) and after.reviewed(3) and after.record(3)["relevant"] is False
    assert after.record(1)["review"]["flags"] == []                            # needs-review:polarity cleared
    notes = "\n".join(after.record(2)["review"]["notes"])
    assert "revised after reveal from 'mixed'" in notes and "the holding" in notes and "blind reading" in notes


def test_drift_check_names_changed_records():
    recs = {1: _rec(1), 2: _rec(2, polarity="adverse")}
    man = _manifest([_rec(1), _rec(2)])                                     # draw-time polarity favorable on both
    assert ap.drift_check(man, recs) == [2]


def test_main_refuses_assisted_by_and_drift_and_writes_outcomes(tmp_path, monkeypatch):
    import sys as _sys
    dom = load_domain(); ledger_dir = tmp_path / "ledger"; led = real_open_ledger(ledger_dir, domain=dom)
    recs = [_rec(1), _rec(2)]
    led.apply([Patch(r["case_id"], "admit", "", r, "seed", Basis(model="m", prompt_version="v", run_id="seed"), cycle="cycle-004") for r in recs], note="seed")
    out = tmp_path / "audit"; out.mkdir()
    (out / "sample-manifest.json").write_text(json.dumps(_manifest(recs)), encoding="utf-8")
    queue = {"run_id": "audit-cycle-004", "sections": {"H": [{"case_id": 1, "decide_fields": ["relevant", "polarity", "who_was_letting"]},
                                                              {"case_id": 2, "decide_fields": ["relevant", "polarity", "who_was_letting"]}]}}
    (out / "audit-queue.json").write_text(json.dumps(queue), encoding="utf-8")
    entries = [_entry(1, "relevant", True), _entry(1, "polarity", "favorable"), _entry(1, "who_was_letting", "householder"),
               _entry(2, "relevant", None, decision="unresolved")]
    import make_map_review as mmr
    html_path, _ = mmr.build_audit_page(dict(queue, cap=2, titles={"H": "t"}, deferred=[],
                                             sections={"H": [dict(c, cite="x") for c in queue["sections"]["H"]]}),
                                        out / "page", opinions={1: "a", 2: "b"}, claude=[], astra=[], checker={})
    html = html_path.read_text(encoding="utf-8").replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps(entries) + '</script>')
    saved = out / "saved.html"; saved.write_text(html, encoding="utf-8")
    for n in ("claude", "astra"):
        (out / f"{n}.json").write_text(json.dumps([{"case_id": 1, "field": "relevant", "decision": "set", "value": True, "note": n}]), encoding="utf-8")
    monkeypatch.setattr(ap, "open_ledger", lambda *a, **kw: real_open_ledger(ledger_dir, domain=kw.get("domain") or dom))
    base = ["apply_map_review.py", "--audit", "--saved", str(saved), "--queue", str(out / "audit-queue.json"),
            "--sample", str(out / "sample-manifest.json"), "--claude", str(out / "claude.json"), "--astra", str(out / "astra.json"),
            "--run-id", "audit-cycle-004", "--outcomes", str(out / "outcomes.json")]
    monkeypatch.setattr(_sys, "argv", base + ["--assisted-by", "x"])
    with pytest.raises(SystemExit) as e:
        ap.main()
    assert e.value.code == 2
    # drift: change record 1 after the draw
    real_open_ledger(ledger_dir, domain=dom).apply([Patch(1, "set", "polarity", "adverse", "later", Basis(model="m", run_id="later"))], note="later")
    monkeypatch.setattr(_sys, "argv", base)
    with pytest.raises(SystemExit) as e:
        ap.main()
    assert "drift" in str(e.value.code)
    monkeypatch.setattr(_sys, "argv", base + ["--allow-drift", "1"])
    assert ap.main() == 0
    oc = json.loads((out / "outcomes.json").read_text(encoding="utf-8"))
    assert oc["run_id"] == "audit-cycle-004" and oc["drift"]["changed"] == [1] and oc["drift"]["disposition"] == "allowed: 1"
    r1 = oc["records"]["1"]
    assert r1["status"] == "decided" and r1["user_final"] == {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"}
    assert r1["draw_time"]["polarity"] == "favorable" and r1["claude"]["relevant"] is True and r1["checker"] is None
    assert oc["records"]["2"]["status"] == "unresolved"
    assert oc["applied_seq_range"][0] <= oc["applied_seq_range"][1]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_apply.py -q`
Expected: FAIL with `AttributeError: audit_patches`

- [ ] **Step 3: Implement**

Add to `tools/apply_map_review.py`:

```python
AUDIT_FIELDS = ("relevant", "polarity", "who_was_letting")


def drift_check(manifest: Mapping, records: Mapping[int, dict]) -> list[int]:
    changed = []
    for r in manifest["records"]:
        cid = int(r["case_id"]); cur = records.get(cid) or {}
        if any(cur.get(f) != r["record"].get(f) for f in AUDIT_FIELDS):
            changed.append(cid)
    return changed


def audit_patches(entries: Sequence[dict], records: Mapping[int, dict], reviewer: str, *, run_id: str) -> list[Patch]:
    basis = Basis(reviewer=reviewer, run_id=run_id)
    tag = arr._label(run_id)
    by_case: dict[int, dict[str, dict]] = {}
    for e in entries:
        by_case.setdefault(int(e["case_id"]), {})[e["field"]] = e
    out: list[Patch] = []
    live: dict[int, list] = {}
    for cid in sorted(by_case):
        fields = by_case[cid]; rel = fields.get("relevant")
        if rel is None or rel.get("decision") == "unresolved":
            continue
        if rel.get("value") is False:
            out += patches_for([{"case_id": cid, "field": "relevant", "decision": "set", "value": False,
                                 "note": f"audit, blind reading: {rel.get('note') or ''}"}], records, reviewer, run_id=run_id)
            continue
        if sorted(fields) != sorted(AUDIT_FIELDS):
            raise ValueError(f"case {cid}: a relevant audit card needs relevant, polarity and who_was_letting; got {sorted(fields)}")
        for f in AUDIT_FIELDS:
            e = fields[f]; value = _checked(cid, f, _value(f, e.get("value")))
            old = (records.get(cid) or {}).get(f)
            why = f"{tag}: {f}"
            out.append(Patch(cid, "append", "review.notes",
                             (f"{tag}: {f} confirmed {old!r} (audit, blind reading)" if old == value
                              else f"{tag}: {f} {old!r} -> {value!r} (audit, blind reading)"), why, basis))
            if e.get("revised_reason"):
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {f} revised after reveal from {e.get('initial_value')!r}: {e['revised_reason']}", why, basis))
            out.append(Patch(cid, "set", f, value, why, basis))
            out += arr._clear_flag(live, records, cid, f, why, basis, tag)
            if e.get("note"):
                out.append(Patch(cid, "append", "review.notes", f"user note: {e['note']}", why, basis))
        out.append(Patch(cid, "set", "review.status", "human-adjudicated", f"{tag}: audit", basis))
    return out


def _vals(entries: Sequence[dict] | None, initial: bool = False):
    if entries is None:
        return None
    d = {f: None for f in AUDIT_FIELDS}
    for e in entries:
        if e.get("field") in d:
            d[e["field"]] = e.get("initial_value") if initial and "initial_value" in e else e.get("value")
    return d


def outcomes_doc(manifest: Mapping, entries: Sequence[dict], *, claude: Sequence[dict], astra: Sequence[dict],
                 checker: Mapping | None, run_id: str, applied_seq_range: tuple[int, int], drift: dict) -> dict:
    by = lambda lst: {int(e["case_id"]): [x for x in lst if int(x["case_id"]) == int(e["case_id"])] for e in lst}
    cl, asr, us = by(claude or []), by(astra or []), by(entries)
    recs = {}
    for r in manifest["records"]:
        cid = int(r["case_id"]); mine = us.get(cid, [])
        rel = next((e for e in mine if e["field"] == "relevant"), None)
        status = "decided" if rel and rel.get("decision") == "set" else "unresolved"
        chk = ((checker or {}).get(str(cid)) or {}).get("values") if checker else None
        recs[str(cid)] = {"draw_time": {f: r["record"].get(f) for f in AUDIT_FIELDS},
                          "claude": _vals(cl.get(cid)), "astra": _vals(asr.get(cid)),
                          "checker": ({f: chk.get(f) for f in AUDIT_FIELDS} if chk else None),
                          "user_initial": _vals(mine, initial=True) if status == "decided" else None,
                          "user_final": _vals(mine) if status == "decided" else None,
                          "revised_reason": next((e.get("revised_reason") for e in mine if e.get("revised_reason")), None),
                          "status": status}
    return {"run_id": run_id, "applied_seq_range": list(applied_seq_range), "drift": drift, "records": recs}
```

In `main`: add `--audit` (store_true), `--sample`, `--claude`, `--astra`, `--outcomes` (default `<sample dir>/outcomes.json`), `--allow-drift` (comma-separated ids). When `--audit`: if `a.assisted_by`: `sys.exit(2)` with the message "audit decisions are the user's own; --assisted-by is refused"; read entries with `make_map_review.read_audit_state` (import via `importlib` like `arr`) from `--saved` or a JSON list from `--decisions`; load the manifest; `changed = drift_check(manifest, head.state.records)`; `allowed = {int(x) for x in a.allow_drift.split(",") if x}` ; if `set(changed) - allowed`: `sys.exit(f"drift: records changed since the draw: {sorted(set(changed) - allowed)}; pass --allow-drift to override per record")`; `patches = audit_patches(...)`; the same run-id guard, dry-run print and `led.apply` as the ordinary path; after a real apply, `res.applied` gives the seqs (use `min`/`max` of `p.seq for p in res.applied` or `(head_before + 1, led.log.head())`); write the outcomes with `write_text` (import from `export_review_cards`) to `--outcomes` (`-dry` suffix on dry runs), `drift = {"checked": len(manifest["records"]), "changed": changed, "disposition": f"allowed: {','.join(map(str, sorted(allowed & set(changed))))}" if changed else "none"}`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audit_apply.py tests/test_map_review_tools.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tools/apply_map_review.py tests/test_audit_apply.py
git commit -m "audit apply: explicit reviewer set patches on all three fields, drift check, outcomes file; --assisted-by refused" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 11: `tools/evaluate.py publish`, the frozen fixture, the live smoke

**Files:**
- Modify: `tools/evaluate.py` (add the `publish` subcommand), `runs/evaluation/rounds.json` (dispositions)
- Create: `tests/fixtures/evaluation/` (round s02-3's queue, checker, claude, astra, and the 3b saved page converted to a decisions list), `tests/test_evaluate_tool.py`
- Test: `tests/test_evaluate_tool.py`

**Interfaces:**
- Consumes: everything above; `apply_map_review.read_page(html, fields)` for registry `user` entries ending in `.html`; `corpus_engine.selector.engine.attribution`; `corpus_engine.store.connect`.
- Produces: `evaluate.load_registry_files(registry, root) -> dict[path, parsed]` (a `.html` user file is converted with `read_page` to the decisions list); `evaluate.read_units(root) -> dict[int, str]` (case -> first run id that read it, `READ_FAILED` for failed units; from every `runs/*/map-manifest.json` plus each run's batches when present, else the ledger's admit patches' `basis.run_id` as the fallback); `evaluate.publish(args) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluate_tool.py
"""tools/evaluate.py publish: writes json+md together after validation, --force revisions,
the frozen historical fixture pins agreement numbers, the live smoke validates only."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import evaluate as ev
from corpus_engine.evaluation.agreement import agreement

FIX = ROOT / "tests" / "fixtures" / "evaluation"


def test_frozen_fixture_pins_round_s02_3_agreement():
    reg = {"rounds": [{"round_id": "s02-3", "kind": "historical", "queue": "q.json", "checker": "c.json", "claude": "cl.json",
                       "astra": "as.json", "user": "u.json", "selection_rule": "A-F", "user_mode": "card_by_card",
                       "apply_run_ids": ["map-cycle-004-shard-02-round-3", "map-cycle-004-shard-02-round-3b"]}], "dispositions": {}}
    files = {n: json.loads((FIX / f).read_text(encoding="utf-8")) for n, f in
             (("q.json", "s02-3-queue.json"), ("c.json", "s02-3-checker.json"), ("cl.json", "s02-3-claude.json"),
              ("as.json", "s02-3-astra.json"), ("u.json", "s02-3-user.json"))}
    a = agreement(reg, files, ledger_run_ids=["map-cycle-004-shard-02-round-3", "map-cycle-004-shard-02-round-3b"])
    ca = a.rounds[0].pairs["claude-astra"]
    # Pinned by hand from reports/review-round-s02-3-threeway.md: 192 cards, 141 agree, 51 disagree.
    total = sum(s.n for s in ca.values()); agree = sum(round(s.raw.value * s.n) for s in ca.values())
    assert (total, agree) == (192, 141)
    assert a.envelope.method_version == "agreement-1"


def test_publish_writes_json_and_md_together_and_force_keeps_a_revision(tmp_path, monkeypatch):
    calls = []
    fake = {"schema_version": "1", "evaluation_id": "004-1-abcdefab", "generated_at": "t", "cycle": "004", "code": {},
            "ledger": {"reporting_seq": 1, "content_sha256": "0" * 64, "counts": {"relevant": {"human_reviewed": 1, "machine_only": 1},
                       "favorable": {"human_reviewed": 1, "machine_only": 1}, "favorable_householder": {"human_reviewed": 1, "machine_only": 1}}},
            "gold_recovery": {"envelope": _env(), "tiers": {}, "union": {"entries": 0, "resolved": 0, "signaled": 0, "read": 0, "relevant": 0, "relevant_human": 0, "recovery": _u()}, "misses": [], "unresolved": [], "inventory": {"brief_doctrine": {"entries": 0, "resolved": 0}}},
            "precision": {"envelope": _env(), "sampling_seq": 1, "frame_size": 1, "n": 0, "decided": 0, "unresolved": 0, "precision": _u(), "field_accuracy": {}, "joint_correctness": _u(), "confusion": {}, "subgroups": {}, "revisions": {}, "drift": {}},
            "agreement": {"envelope": _env(), "rounds": [], "excluded": [], "unregistered_run_ids": []},
            "coverage": {"envelope": _env(), "bands": [], "scenarios": []}}
    monkeypatch.setattr(ev, "compute", lambda a: fake)
    out = tmp_path / "evaluation-cycle-004"
    assert ev.main(["publish", "--out", str(out)]) == 0
    assert (tmp_path / "evaluation-cycle-004.json").exists() and (tmp_path / "evaluation-cycle-004.md").exists()
    assert ev.main(["publish", "--out", str(out)]) == 1                                  # refuses to overwrite
    assert ev.main(["publish", "--out", str(out), "--force"]) == 0
    assert (tmp_path / "evaluation-cycle-004-rev1.json").exists() and (tmp_path / "evaluation-cycle-004-rev1.md").exists()
    bad = dict(fake); del bad["coverage"]
    monkeypatch.setattr(ev, "compute", lambda a: bad)
    assert ev.main(["publish", "--out", str(tmp_path / "other")]) == 1
    assert not (tmp_path / "other.json").exists() and not (tmp_path / "other.md").exists()


def _env():
    return {"method_version": "x", "population": "p", "exclusions": [], "uncertainty": {"type": "none", "level": None, "method": "none"}, "limitations": [], "provenance": {"inputs": [], "run_ids": [], "ledger_seqs": {}}}


def _u():
    return {"value": None, "n": 0, "lo": None, "hi": None, "status": "unavailable"}


@pytest.mark.skipif(not (ROOT / "data" / "ledger" / "patches.jsonl").exists(), reason="no committed ledger here")
def test_live_smoke_validates_and_renders(tmp_path):
    from corpus_engine.evaluation import contract, render
    doc = ev.compute(ev.build_parser().parse_args(["publish", "--out", str(tmp_path / "e"), "--no-store"]))
    assert contract.validate(doc) == []
    md = render.markdown(doc)
    assert "## Headline" in md and doc["ledger"]["counts"]["relevant"]["human_reviewed"] > 0
    assert doc["precision"]["precision"]["status"] in ("ok", "unavailable")
```

- [ ] **Step 2: Build the fixture and run to verify failure**

Copy `runs/cycle-004-shard-02/review-round-3.json` -> `tests/fixtures/evaluation/s02-3-queue.json`, `review-round-3-checker.json` -> `s02-3-checker.json`, `review-round-3-decisions-claude.json` -> `s02-3-claude.json`, `review-round-3-decisions-astra.json` -> `s02-3-astra.json`, and convert `review-round-3b-saved.html` with `PYTHONPATH=. .venv/Scripts/python.exe -c "import json,sys; sys.path.insert(0,'tools'); import apply_map_review as ap; from corpus_engine.domain import load_domain; html=open('runs/cycle-004-shard-02/review-round-3b-saved.html',encoding='utf-8').read(); d=ap.read_page(html, tuple(load_domain().judged_fields)+ap.EXTRA_FIELDS); open('tests/fixtures/evaluation/s02-3-user.json','w',encoding='utf-8',newline='\n').write(json.dumps(d,indent=1)+'\n')"`. Strip `opinion_text` if any file carries it (the queue does not).

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluate_tool.py -q`
Expected: the fixture test may pass already (Task 4's measure); `test_publish_*` FAILS with `AttributeError: compute`; the live smoke FAILS the same way.

If the fixture test's `(total, agree)` differs from `(192, 141)`, do NOT change the pin: the three-way sheet counted cards with `(adopt)` resolved and withdrawals per card; reconcile `effective_label` / the per-card counting in `agreement._labels` until the fixture reproduces the committed sheet, and record what differed in the task report.

- [ ] **Step 3: Implement `publish`**

Add to `tools/evaluate.py`:

```python
import platform, subprocess
from datetime import datetime, timezone
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.evaluation import contract, render, summary
from corpus_engine.evaluation.gold import gold_recovery, READ_FAILED
from corpus_engine.evaluation.precision import precision_and_accuracy
from corpus_engine.evaluation.agreement import agreement
from corpus_engine.evaluation.coverage import tail_coverage
import apply_map_review as ap


def load_registry_files(registry: dict, root: Path) -> dict:
    files = {}
    fields = tuple(load_domain().judged_fields) + ap.EXTRA_FIELDS
    for e in registry.get("rounds") or ():
        for key in ("queue", "checker", "claude", "astra", "user"):
            p = e.get(key)
            if not p or p in files:
                continue
            path = root / p
            if not path.exists():
                raise SystemExit(f"registry names {p} for round {e['round_id']} but it does not exist")
            if p.endswith(".html"):
                files[p] = ap.read_page(path.read_text(encoding="utf-8"), fields)
            else:
                files[p] = json.loads(path.read_text(encoding="utf-8"))
    return files


def read_units(root: Path, view) -> dict[int, str]:
    out: dict[int, str] = {}
    for mpath in sorted((root / "runs").glob("*/map-manifest.json")):
        m = json.loads(mpath.read_text(encoding="utf-8")); run = m.get("run_id") or mpath.parent.name
        bdir = mpath.parent / "batches"
        cases_of = {}
        if bdir.exists():
            for b in bdir.glob("batch-*.json"):
                d = json.loads(b.read_text(encoding="utf-8")); cases_of[d["batch_id"]] = [int(c["case_id"]) for c in d.get("cases") or ()]
        for cell in (m.get("cells") or {}).values():
            for u in cell.get("units") or ():
                for cid in cases_of.get(u["unit_id"], ()):
                    ok = u.get("status") == "ok" and not u.get("failed")
                    if cid not in out or out[cid] == READ_FAILED and ok:
                        out[cid] = run if ok else READ_FAILED
    for p in view.patches:                                  # fallback: a record the ledger carries was read by its admit run
        if p.op == "admit" and p.case_id not in out:
            out[p.case_id] = p.basis.run_id or "unknown-run"
    return out


def compute(a) -> dict:
    dom = load_domain(); led = open_ledger(domain=dom); view = led.view()
    reporting_seq = led.log.head(); content = summary.ledger_content_sha256(led.dir)
    gold_rows = [json.loads(l) for l in (ROOT / "data" / "gold" / "gold.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [int(g["case_id"]) for g in gold_rows if g.get("case_id")]
    if a.no_store:
        signaled = {cid: True for cid in ids}
    else:
        from corpus_engine import store
        from corpus_engine.selector.engine import attribution
        signaled = {cid: bool(refs) for cid, refs in attribution(store.connect(), ids).items()}
    gold = gold_recovery(gold_rows, view, signaled=signaled, read_units=read_units(ROOT, view))
    audit = Path(a.audit)
    manifest = json.loads((audit / "sample-manifest.json").read_text(encoding="utf-8")) if (audit / "sample-manifest.json").exists() else None
    outcomes = json.loads((audit / "outcomes.json").read_text(encoding="utf-8")) if (audit / "outcomes.json").exists() else None
    prec = precision_and_accuracy(manifest, outcomes) if manifest else precision_and_accuracy(
        {"ledger_head_seq": 0, "frame_size": 0, "seed": None, "records": []}, None)
    registry = json.loads(Path(a.rounds).read_text(encoding="utf-8"))
    files = load_registry_files(registry, ROOT)
    ledger_run_ids = sorted({p.basis.run_id for p in view.patches if p.basis.reviewer and p.basis.run_id})
    agr = agreement(registry, files, ledger_run_ids=ledger_run_ids)
    if agr.unregistered_run_ids:
        raise SystemExit(f"unregistered reviewer run ids: {', '.join(agr.unregistered_run_ids)}; add a disposition to {a.rounds}")
    cov = tail_coverage(json.loads(Path(a.bands).read_text(encoding="utf-8")))
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    code = {"git_revision": rev, "command": " ".join(sys.argv), "python": platform.python_version(), "packages": {}}
    ev = summary.evaluate(view, summary.Inputs(gold, prec, agr, cov), cycle=a.cycle, reporting_seq=reporting_seq,
                          content_sha256=content, code=code)
    return summary.to_json(ev)


def cmd_publish(a) -> int:
    doc = compute(a)
    problems = contract.validate(doc)
    if problems:
        print("contract violations: " + ", ".join(problems), file=sys.stderr); return 1
    jp, mp = Path(a.out + ".json"), Path(a.out + ".md")
    if jp.exists():
        if not a.force:
            print(f"{jp} exists; pass --force to supersede (the old pair is kept as -revN)", file=sys.stderr); return 1
        n = 1
        while Path(f"{a.out}-rev{n}.json").exists():
            n += 1
        jp.rename(f"{a.out}-rev{n}.json")
        if mp.exists():
            mp.rename(f"{a.out}-rev{n}.md")
    md = render.markdown(doc)
    write_text(jp, json.dumps(doc, indent=1, ensure_ascii=False)); write_text(mp, md)
    print(f"{doc['evaluation_id']} -> {jp.as_posix()}, {mp.as_posix()}")
    return 0
```

and in `build_parser` the `publish` subparser: `--cycle` (default `004`), `--audit` (default `runs/audit-cycle-004`), `--rounds` (default `runs/evaluation/rounds.json`), `--bands` (default `runs/evaluation/shard-02-bands.json`), `--out` (default `reports/evaluation-cycle-004`), `--force`, `--no-store` (skip the sqlite attribution; every resolved gold case counts as signaled; for tests and machines without the store).

- [ ] **Step 4: First live publish; fill the dispositions**

Run: `PYTHONPATH=. .venv/Scripts/python.exe tools/evaluate.py publish`
Expected on the first run: exit with `unregistered reviewer run ids: ...` naming the reference-review, bootstrap, admission and any other reviewer-basis run ids the registry does not cover. Add each to `runs/evaluation/rounds.json` `dispositions` with a one-line reason (e.g. `"reference-v2": "the Stage 1 reference review (no model first pass; predates the two-reader flow)"`). Re-run until it publishes `reports/evaluation-cycle-004.{json,md}` with measures 2-3 `unavailable`.

- [ ] **Step 5: Run the tests and the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluate_tool.py -q` then `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add tools/evaluate.py tests/test_evaluate_tool.py tests/fixtures/evaluation runs/evaluation/rounds.json reports/evaluation-cycle-004.json reports/evaluation-cycle-004.md
git commit -m "tools/evaluate.py publish: validated json+md pair, --force revisions, registry reconciliation; first evaluation (audit pending)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 12: the audit run (runbook, human in the loop)

This task is executed by the controller with the user, not by an implementer subagent. Each step is one action; stop where the step says the user acts.

**Files:**
- Create: `runs/audit-cycle-004/` (sample manifest, opinions, queue, readers' files, saved page, outcomes), `reports/review-audit-cards.{md,json}`, `reports/review-audit-page.html`, `reports/review-audit-threeway.md`
- Modify: `runs/evaluation/rounds.json` (the audit entry), `reports/evaluation-cycle-004.{json,md}` (republished), `reports/handoff-cycle-004.md`, `README.md` (evaluation block)

- [ ] **Step 1: Draw the sample** (the user gives the seed; suggest the date, `20260912`)

```
PYTHONPATH=. .venv/Scripts/python.exe tools/draw_audit_sample.py --seed <seed> --n 150 --out runs/audit-cycle-004
git add runs/audit-cycle-004/sample-manifest.json runs/audit-cycle-004/audit-queue.json runs/audit-cycle-004/opinions
git commit -m "audit: the frozen sample (seed <seed>, 150 of <frame> machine-only relevant records at seq <seq>)" ...
```

- [ ] **Step 2: Export the blind cards**

```
PYTHONPATH=. .venv/Scripts/python.exe tools/export_review_cards.py --queue runs/audit-cycle-004/audit-queue.json --audit --out-stem reports/review-audit-cards --chunks 6
```
Expected: `reports/review-audit-cards.json` and `-part1..6.md`, ~25 cards each, no reader or checker lines.

- [ ] **Step 3: The Astra pass, isolated**

Create `<scratchpad>/audit-iso/` holding only `review-audit-brief.md` and `review-audit-cards.json`; run
```
PYTHONPATH=. .venv/Scripts/python.exe tools/first_pass_codex.py --audit --workdir <scratchpad>/audit-iso --cards <scratchpad>/audit-iso/review-audit-cards.json --brief <scratchpad>/audit-iso/review-audit-brief.md --out runs/audit-cycle-004/decisions-astra.json
```
in the background (~150 minutes at a minute a card); resume with the same command if it stops. Expected manifest: `decided 150`, `failed []`.

- [ ] **Step 4: The Claude pass, isolated**

Dispatch six opus subagents in parallel, each with ONLY two paths: `reports/review-audit-brief.md` and one `reports/review-audit-cards-partK.md`, and the instruction to write `runs/audit-cycle-004/decisions-claude-partK.json` in the audit output shape; no other files, no repo exploration (say so in the dispatch). Merge the six parts into `runs/audit-cycle-004/decisions-claude.json` (concatenate the lists, sort by case id then field order relevant/polarity/who_was_letting) and validate every card with `first_pass_codex.parse_decisions_audit` on the merged entries (write a five-line script in the scratchpad).

- [ ] **Step 5: Optional checker**

`PYTHONPATH=. .venv/Scripts/python.exe tools/make_map_review.py --check --queue runs/audit-cycle-004/audit-queue.json --checker runs/audit-cycle-004/checker.json` (Codex 100%; skip if the Codex limit is near; the page and outcomes accept a missing checker).

- [ ] **Step 6: Three-way sheet (per field) and commit the passes**

```
PYTHONPATH=. .venv/Scripts/python.exe tools/threeway_sheet.py --queue runs/audit-cycle-004/audit-queue.json --claude runs/audit-cycle-004/decisions-claude.json --astra runs/audit-cycle-004/decisions-astra.json --out-md reports/review-audit-threeway.md --per-field --label "audit cycle 004"
git add runs/audit-cycle-004/decisions-*.json runs/audit-cycle-004/checker.json reports/review-audit-threeway.md reports/review-audit-cards*.md reports/review-audit-cards.json
git commit -m "audit: blind model passes (Claude, Astra), per-field three-way sheet" ...
```

- [ ] **Step 7: Build and publish the page**

```
PYTHONPATH=. .venv/Scripts/python.exe tools/make_map_review.py --audit --queue runs/audit-cycle-004/audit-queue.json --claude runs/audit-cycle-004/decisions-claude.json --astra runs/audit-cycle-004/decisions-astra.json --checker runs/audit-cycle-004/checker.json --out-stem reports/review-audit-page
```
Publish `reports/review-audit-page.html` as an Artifact with `capabilities {"artifact": {}}` (favicon `🔍`, title "Audit sample, cycle 004"), verify headless that 150 cards render and none is locked, and hand the link to the user with the instruction: read each opinion, answer the three questions, Lock, then look at the reveal and revise only with a reason; Save often; "Cannot read this opinion" for garbled text. **The user reads all 150. Stop here until the user says the page is saved.**

- [ ] **Step 8: Apply**

Read the saved page (`Artifact action: read`, save the HTML to `runs/audit-cycle-004/page-saved.html`), then:
```
PYTHONPATH=. .venv/Scripts/python.exe tools/apply_map_review.py --audit --saved runs/audit-cycle-004/page-saved.html --queue runs/audit-cycle-004/audit-queue.json --sample runs/audit-cycle-004/sample-manifest.json --claude runs/audit-cycle-004/decisions-claude.json --astra runs/audit-cycle-004/decisions-astra.json --checker runs/audit-cycle-004/checker.json --run-id audit-cycle-004 --dry-run
```
Show the user the dry-run summary (decided / unresolved / withdrawals / drift), get "apply", run without `--dry-run`. Expected: `outcomes.json` written; published counts printed.

- [ ] **Step 9: Register the audit round and republish the evaluation**

Add to `runs/evaluation/rounds.json`: `{"round_id": "audit-cycle-004", "kind": "audit", "queue": "runs/audit-cycle-004/audit-queue.json", "checker": "runs/audit-cycle-004/checker.json" (or null), "claude": "runs/audit-cycle-004/decisions-claude.json", "astra": "runs/audit-cycle-004/decisions-astra.json", "user": "runs/audit-cycle-004/page-saved.html", "selection_rule": "simple random sample of 150 machine-only relevant records at seq <seq>, seed <seed>", "user_mode": "card_by_card", "apply_run_ids": ["audit-cycle-004"]}`. Note: `load_registry_files` converts `.html` with `read_page`, which reads one-field state; for the audit page use `make_map_review.read_audit_state` instead: add `if e.get("kind") == "audit" and p.endswith(".html"): files[p] = mmr.read_audit_state(...)` to `load_registry_files` (one line; test in Task 11's file: an audit entry's html is read through `read_audit_state`).

```
PYTHONPATH=. .venv/Scripts/python.exe tools/evaluate.py publish --force
```
Expected: `reports/evaluation-cycle-004.{json,md}` with all five measures `ok`, the previous pair kept as `-rev1`.

- [ ] **Step 10: Repin, document, commit**

Update the count pins in `tests/test_ledger_committed.py` and `tests/test_ledger_tally.py` (the audit moves ~150 records to the human tier and withdraws some); add an "Evaluation" block to `README.md` (the five commands: build-bands, draw, first-pass --audit, page --audit, apply --audit, publish); add the evaluation's headline table and the audit's outcome to `reports/handoff-cycle-004.md`; run the full suite; commit; then the finishing menu.

## Self-review notes

- Spec §3.2 `gold_recovery` inputs say "the view, the store's case table, every map manifest": Task 3 takes `signaled` and `read_units` as precomputed maps and Task 11's `compute` builds them from the store and manifests, so the measure stays pure. Covered.
- Spec §4.6 `--assisted-by` refused: Task 10 test asserts exit 2.
- Spec §4.4 resume by card and brief hash: Task 8 test `test_audit_run_writes_three_entries_per_card_and_resumes_by_brief_hash`.
- Spec §5 typed payloads: Task 6's schema lists the envelope and estimate shapes; the per-measure dataclasses are the payloads.
- Spec §7 "a validation failure writes nothing": Task 11 test `other.json` absent.
- Spec §8 frozen fixture: Task 11 pins (192, 141) from the committed round-3 sheet.
- Type consistency: `Estimate` fields `(value, n, lo, hi, status)` used identically in Tasks 1, 4, 5, 6; `Envelope` positional order `(method_version, population, exclusions, uncertainty, limitations, provenance)` used identically in Tasks 2-6; `decide_fields` spelled the same in Tasks 4, 7, 8, 9, 10; `read_audit_state` defined in Task 9 and used in Tasks 10 and 12.
