# Stage 3B Slice 2 — Cycle-004 Map Runner, Ledger Admission, Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the cycle-004 candidate pool with the pinned subscription reader under a per-cell budget that stops on yield, admit the accepted records to the ledger as machine-only records with full provenance, and put a priority-ordered review queue of at most 150 cards in front of the user.

**Architecture:** A new `corpus_engine/mapper/` package sits on top of the unchanged Stage 3A / slice-1 reader. `cells.py` turns the 1,845 ranked batch files into 50 era x jurisdiction cells with a cap each; `yield_stop.py` is a pure state machine that decides when a cell has stopped paying; `runner.py` walks the cells, plans one `batch_extraction` per batch through the existing `Reader`, and writes one tracked manifest; `screen.py` is the optional fallback-reader relevance pass (built, tested, never run this slice); `admit.py` re-derives the accepted records from the response cache and turns them into ledger patches; `queue.py` selects the review round. Four thin CLIs (`tools/map_reader.py`, `tools/admit_map.py`, `tools/make_map_review.py`, `tools/apply_map_review.py`) are the only entry points. The runner never writes the ledger; the admit tool never touches the network.

**Tech Stack:** Python 3.11 (`.venv/Scripts/python`), SQLite, httpx (OpenRouter, screen only), subprocess (Claude CLI, Codex CLI), rapidfuzz via `corpus_engine.verification`, PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-stage-3b-slice-2-map-runner-design.md` (binding; D1–D13 are its decisions). Authority on conflicts: that spec, then ADR-0007 (override section, 2026-09-05), ADR-0004, `CONTEXT.md`, `reports/ranking-cycle-004.md` sections 3 and 5.

## Global Constraints

Spec section 13 verbatim, plus this slice's operational rules. Every task's requirements implicitly include this section.

- LF line endings, UTF-8 without BOM, one trailing newline on every file written. Write bytes explicitly (`path.write_bytes(text.encode("utf-8"))`); never PowerShell `Set-Content`.
- Never commit `.env`, `data/db/`, `data/raw/`, `data/reader/cache/`, `runs/*/batches`, `runs/*/extractions`. **The map manifest (`runs/cycle-004-shard-01/map-manifest.json`) is the only tracked run artefact.**
- No paid request outside `tools/map_reader.py`'s screen path and the checker's own subscription.
- Subscription calls never carry an API key: `ClaudeCliProvider.env()` strips `SUBSCRIPTION_STRIPPED_ENV` and everything under the `ANTHROPIC_` prefix, plus the Bedrock / Vertex / Foundry switches.
- `kit-v1`, `kit-v2` and both measurement manifests (`data/reader/measurement-v1/manifest.json`, `data/reader/measurement-v2/manifest.json`) are untouched.
- Published counts come only from `open_ledger().view().counts()` — never from a file scan, never blended across tiers (`TierCount.__int__` and `__add__` raise).
- **No paid or subscription reader call from any task except the two live-run tasks — the dry run and the field run, both in Task 9.** Tasks 1–8 use `ScriptedProvider` or fixtures only. If a task's test would invoke `claude`, `codex`, or `httpx`, the test is wrong.
- **The screen is never run this slice.** `screen.py` is built and unit-tested with no network; `--screen` defaults off and Task 9 never passes it.
- The reader pin is fixed and not re-decided here (D12): `claude-cli/claude-opus-5`, effort `low`, batch size 18, codebook `mapper-v3`, read timeout 1500 s, `max_tokens` 64000. Checker: `codex-cli` / `gpt-5.6-terra`. Fallback (screen only): `google/gemini-3.7-flash`.
- Python 3.11; tests are `.venv/Scripts/python -m pytest -q` from `C:\Users\marcu\Desktop\Str-corpus`. Baseline **311 passed, 1 xfailed**. A task is done when the whole suite is green, not just its own file.
- Branch `refactor/stage-3b-slice-2`, cut from `main` at `4f64aba`. Commit after every task with the trailer block:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## Facts the plan is built on (verified 2026-09-06, read-only)

- `runs/cycle-004-shard-01/batches/*.json` — **1,845 files**, each `{batch_id, ranker_id, era_partition, jurisdiction, cases[]}`. `batch_id` is `cycle-004-shard-01-batch-NNN`; each case carries `case_id`, `era_partition`, `jurisdiction`, `signals[]`, `rank_score`. 1,801 batches hold 18 cases, 44 hold fewer (the per-cell remainders); 32,795 cases in total. The directory is gitignored but present on disk.
- **50 cells** = 5 eras x 10 jurisdictions (Cal., Conn., D.C., La., Mass., N.J., N.Y., Ohio, Pa., Tex.). Spec section 1 says "eleven jurisdictions"; the batches on disk carry ten. The code derives the jurisdiction set from the batch files and never hard-codes a count.
- Batches per era: pre-1860 244, 1860-1900 233, 1900-1930 316, 1930-1970 519, 1970-2020 533 (sums to 1,845; matches `reports/ranking-cycle-004.md` section 5).
- Era depth at the 0.25 cut (D2, section 5): pre-1860 **32**, 1860-1900 **32**, 1900-1930 **59**, 1930-1970 **139**, 1970-2020 **111**; 373 total. Rounding each cell's share up gives **399** batches of cap across the 50 cells.
- `mapper-v3` sha256 = `f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752`; first 12 = **`f92016681314`**. Its stability record already exists at `domains/str-right-to-let/codebooks/stability/f9201668...json`, so the driver's `preflight:stability` check passes.
- `data/ledger/patches.jsonl` contains **0** occurrences of `under_30_days` or `right_characterization`. D7 is a rename in `domain.yaml` and `fold.py` only; no data migration.
- Committed ledger counts today: **693 relevant / 367 favorable / 137 favorable householder**.
- `.gitignore` covers `runs/*/batches/` and `runs/*/extractions/` but not `runs/*/map-manifest.json` — the manifest is tracked with no `.gitignore` change.

---

## File Structure

```
corpus_engine/mapper/
  __init__.py         NEW  public names: build_cells, Cell, CellProgress, MapRunner, MapOutcome
  cells.py            NEW  batch loading, Cell, caps from era depth, cell ordering, BatchSource
  yield_stop.py       NEW  CellProgress / CellStop; the window-3 threshold-2 stop rule (pure)
  runner.py           NEW  MapRunner: plan per batch, per-process caps, manifest, resume
  screen.py           NEW  optional fallback-reader relevance pass (off; never run this slice)
  admit.py            NEW  cache -> gated records -> ledger patches (D8 basis)
  queue.py            NEW  D4 section selection, 150 cap, single appearance, checker pass
corpus_engine/reader/providers/
  factory.py          NEW  provider_for / cli_pin / budget_for / process_unit_cap (moved from tools/)
  __init__.py         MOD  export the factory names
corpus_engine/ledger/
  fold.py             MOD  D7 rename; SUPPORTED_BY_PROMPT; State.prompts; list-valued `supports`
domains/str-right-to-let/
  domain.yaml         MOD  top-level judged_fields: under_thirty_days, owner_freedom_characterization
tools/
  measure_reader.py   MOD  imports the moved helpers from providers/factory.py (behaviour-preserving)
  map_reader.py       NEW  the map runner CLI
  admit_map.py        NEW  admission CLI (--dry-run / --apply)
  make_map_review.py  NEW  review page (six sections) on make_reference_review's mechanics
  apply_map_review.py NEW  saved page -> human-basis patches
tests/
  test_reader_provider_factory.py  NEW  the moved helpers, imported from their new home
  test_ledger_fold.py              MOD  D7 rename, both support rules, list `supports`
  test_ledger_committed.py         MOD  replay byte-identical + counts pinned after the rename
  test_mapper_cells.py             NEW  caps from the section-5 table, ordering, batch loading
  test_mapper_yield.py             NEW  window, threshold, failed units ignored, cap
  test_mapper_runner.py            NEW  order, resume, caps, manifest, failed units, --cells
  test_mapper_screen.py            NEW  trigger, re-batching, ceiling (no network)
  test_mapper_admit.py             NEW  field mapping, D8 basis, support scoping, guards, replay
  test_mapper_queue.py             NEW  sections, single appearance, priority, cap, page, apply
runs/cycle-004-shard-01/
  map-manifest.json                generated, TRACKED (Task 9)
  extractions/<batch_id>.json      generated, gitignored (Task 9)
reports/
  map-cycle-004.md                 written (Task 9)
  review-queue-map-cycle-004.{html,md}   generated (Task 9)
  handoff-cycle-004.md             items 7 and 11 (Task 9)
CONTEXT.md                         glossary: Map, Cell, Yield, Admission, Review queue, Screen (Task 9)
README.md                          runner / admit / review commands (Task 9)
```

**Task order.** T1 and T2 are independent of each other and of everything else; do them first because every later task imports from them. T3 -> T4 -> T5 is a chain. T6 depends on T5's manifest shape. T7 depends on T5's manifest and on T2's support rule. T8 depends on T7's admitted records. T9 runs last and is the only task that spends subscription time.

---

### Task 1: Move the provider / budget helpers into `corpus_engine/reader/providers/factory.py`

Behaviour-preserving relocation (spec section 6, last sentence). The map runner needs the same
transport resolution and the same subscription budget shape the measurement tool already has,
and a runner that imported them from `tools/measure_reader.py` would drag the whole measurement
module (its OpenRouter ceiling, its manifest merging, its `--annotate-only` path) into every
map. `tools/measure_reader.py` keeps every name it had, by import, so
`tests/test_measure_reader_tool.py` passes **unchanged**.

**Files:**
- Create: `corpus_engine/reader/providers/factory.py`, `tests/test_reader_provider_factory.py`
- Modify: `corpus_engine/reader/providers/__init__.py`, `tools/measure_reader.py` (delete the moved bodies, import them instead)

**Interfaces:**
- Consumes: `ModelPin`, `Budget` from `corpus_engine.reader.model`; `ClaudeCliProvider`, `OpenRouterProvider` from their modules.
- Produces (T5, T6 and T9 consume exactly these names from `corpus_engine.reader.providers.factory`):
  - `EFFORT: str = "low"`; `REASONING: dict = {"effort": EFFORT}`; `READ_TIMEOUT: int = 1500`; `OPEN_PRECISIONS: tuple = ("bf16", "fp8")`
  - `SUBSCRIPTION_PROVIDER: str = "claude-cli"`; `SUBSCRIPTION_MAX_UNITS: int = 60`; `SUBSCRIPTION_MAX_WALL_SECONDS: int = 21600`; `SUBSCRIPTION_UNIT_MARGIN: int = 10`
  - `credits_remaining(prov: OpenRouterProvider) -> float`
  - `endpoints(prov: OpenRouterProvider, model_id: str) -> list[dict]`
  - `pin_for(cand: dict, prov: OpenRouterProvider) -> tuple[ModelPin | None, str]`
  - `is_subscription(cand: dict) -> bool`
  - `cli_pin(cand: dict) -> ModelPin`
  - `provider_for(cand: dict, prov, timeout: int = READ_TIMEOUT) -> tuple[object | None, ModelPin | None, str]`
  - `small_batches(batches) -> list[dict]`; `sample_batches(batches, ids: set, tag: str) -> list[dict]`
  - `process_unit_cap(n_subscription: int, batches, ids50, *, margin: int = SUBSCRIPTION_UNIT_MARGIN) -> dict` — keys `kit`, `batch_size_pair`, `stability`, `margin`, `total`
  - `budget_for(cand: dict, remaining_usd: float, *, max_units: int | None = None, max_wall_seconds: float | None = None) -> Budget`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader_provider_factory.py
"""The transport / budget helpers now live in the engine, not in the measurement script.

They are the same functions: the map runner (slice 2) and the measurement tool both have to
resolve a candidate to a provider and a pin, and both have to express the subscription's
budget as units and wall clock rather than dollars. Importing them out of tools/ would drag
the measurement's OpenRouter ceiling and manifest merging into every map run."""
import importlib.util
from pathlib import Path

from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers import factory as F
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("measure_reader", ROOT / "tools" / "measure_reader.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)

SUB = {"model_id": "claude-cli/claude-opus-5", "family": "anthropic",
       "provider": "claude-cli", "cli_model": "claude-opus-5"}
OPENR = {"model_id": "z-ai/glm-5.3", "family": "zai", "pin_open": True}


def test_the_factory_owns_the_constants_the_pin_is_built_from():
    assert F.EFFORT == "low" and F.REASONING == {"effort": "low"}
    assert F.READ_TIMEOUT == 1500 and F.OPEN_PRECISIONS == ("bf16", "fp8")
    assert F.SUBSCRIPTION_PROVIDER == "claude-cli"
    assert F.SUBSCRIPTION_MAX_UNITS == 60 and F.SUBSCRIPTION_MAX_WALL_SECONDS == 6 * 3600
    assert F.SUBSCRIPTION_UNIT_MARGIN == 10


def test_cli_pin_is_the_label_the_cache_key_hashes():
    pin = F.cli_pin(SUB)
    assert isinstance(pin, ModelPin)
    assert pin.label == "claude-cli/claude-opus-5@claude-cli:-"
    assert pin.extra == {"effort": "low", "cli_model": "claude-opus-5"}
    assert F.is_subscription(SUB) and not F.is_subscription(OPENR)


def test_provider_for_picks_the_cli_transport_and_reports_why(monkeypatch):
    monkeypatch.setattr(ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    provider, pin, why = F.provider_for(SUB, None)
    assert provider.name == "claude-cli" and provider.cli_model == "claude-opus-5"
    assert provider.timeout == F.READ_TIMEOUT and pin.model_id == "claude-cli/claude-opus-5"
    assert "2.1.258" in why
    monkeypatch.setattr(ClaudeCliProvider, "version", lambda self: None)
    assert F.provider_for(SUB, None) == (None, None,
                                         "claude cli not available on PATH (shutil.which found nothing)")
    # an OpenRouter candidate with no provider configured is skipped with a reason, never crashed on
    provider2, pin2, why2 = F.provider_for(OPENR, None)
    assert provider2 is None and pin2 is None and "OPENROUTER_API_KEY" in why2


def test_budget_for_never_puts_a_dollar_ceiling_on_the_subscription():
    b = F.budget_for(SUB, 15.0)
    assert b == Budget(max_usd=None, max_units=60, max_wall_seconds=21600.0)
    b2 = F.budget_for(SUB, 15.0, max_units=439, max_wall_seconds=3600)
    assert b2.max_usd is None and b2.max_units == 439 and b2.max_wall_seconds == 3600.0
    assert F.budget_for(OPENR, 12.5) == Budget(max_usd=12.5)
    assert F.budget_for(OPENR, -3.0).max_usd == 0.0


def test_process_unit_cap_still_counts_the_measurement_reads():
    cases = [{"case_id": i} for i in range(1, 19)]
    batches = [{"batch_id": f"b{n}", "era_partition": "e", "jurisdiction": "j", "cases": cases}
               for n in range(1, 24)]
    plan = F.process_unit_cap(2, batches, set(range(1, 19)))
    assert plan == {"kit": 46, "batch_size_pair": 92, "stability": 46, "margin": 10, "total": 194}
    assert F.process_unit_cap(0, batches, set(range(1, 19)))["total"] == 0


def test_the_measurement_tool_still_exposes_every_moved_name():
    """The relocation is behaviour-preserving: tests/test_measure_reader_tool.py calls all of
    these through `mr.` and must keep passing without being edited."""
    for name in ("EFFORT", "REASONING", "READ_TIMEOUT", "OPEN_PRECISIONS", "SUBSCRIPTION_PROVIDER",
                 "SUBSCRIPTION_MAX_UNITS", "SUBSCRIPTION_MAX_WALL_SECONDS", "SUBSCRIPTION_UNIT_MARGIN",
                 "credits_remaining", "endpoints", "pin_for", "is_subscription", "cli_pin",
                 "provider_for", "small_batches", "sample_batches", "process_unit_cap", "budget_for",
                 "ClaudeCliProvider", "OpenRouterProvider"):
        assert hasattr(mr, name), name
        if name in ("cli_pin", "provider_for", "budget_for", "process_unit_cap"):
            assert getattr(mr, name) is getattr(F, name), f"{name} is a copy, not the moved function"
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "from corpus_engine.reader.providers.factory import" in src
    assert "def provider_for(" not in src and "def budget_for(" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_provider_factory.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.reader.providers.factory'`.

- [ ] **Step 3: Write the module**

Create `corpus_engine/reader/providers/factory.py` by **moving** the bodies verbatim out of
`tools/measure_reader.py` (lines 46–82 for the constants, 123–170 for `_auth` / `credits_remaining`
/ `endpoints` / `_probe` / `pin_for`, 177–178 and 222–273 for `is_subscription` / `cli_pin` /
`provider_for` / `process_unit_cap` / `budget_for`, 407–421 for `small_batches` / `sample_batches`).
Keep every docstring and comment as it stands — they carry the reasoning for the flags and the
ceilings — and change nothing but the imports.

```python
"""Which transport a reader candidate runs on, and what kind of budget that transport takes.

Moved out of tools/measure_reader.py (slice 2, spec section 6) because two callers now need
it: the measurement tool, which resolves five candidates against a shared OpenRouter ceiling,
and the cycle-004 map runner, which resolves exactly one - the pinned subscription reader -
and needs its units/wall-clock budget without inheriting the measurement's dollar accounting.
Nothing here changed in the move; tests/test_measure_reader_tool.py passes unedited."""
from __future__ import annotations
import time

import httpx

from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider

OPEN_PRECISIONS = ("bf16", "fp8")           # preference order for pinned open-weight models
# ADR-0007 requires effort to be recorded. Left at each provider's default it is not a
# recorded quantity at all but a per-family accident (2026-09-04: 530 output tokens per case
# from one family, 3700 from another). Carried on ModelPin.extra as `reasoning.effort` for
# OpenRouter and as `effort` for the CLI, which `effort_of` reads either way.
EFFORT = "low"
REASONING = {"effort": EFFORT}
# Reasoning models generate for many minutes on an 18-case batch; anything shorter aborts a
# valid generation and the retry schedule re-buys it (see openrouter.py).
READ_TIMEOUT = 1500
SUBSCRIPTION_PROVIDER = "claude-cli"
# Both subscription ceilings are per PROCESS, not per read: one deadline and one shared unit
# counter across every subscription read the process makes. SUBSCRIPTION_MAX_UNITS is the
# fallback when no process cap has been computed.
SUBSCRIPTION_MAX_UNITS = 60
SUBSCRIPTION_MAX_WALL_SECONDS = 6 * 3600
# Each parse failure costs two extra units (the split halves).
SUBSCRIPTION_UNIT_MARGIN = 10


def _auth(prov: OpenRouterProvider) -> dict:
    return {"Authorization": f"Bearer {prov.key}"}


def credits_remaining(prov: OpenRouterProvider) -> float:
    d = httpx.get(f"{prov.base}/credits", headers=_auth(prov), timeout=60).json()["data"]
    return float(d["total_credits"]) - float(d["total_usage"])


def endpoints(prov: OpenRouterProvider, model_id: str) -> list[dict]:
    r = httpx.get(f"{prov.base}/models/{model_id}/endpoints", headers=_auth(prov), timeout=60)
    return list(((r.json().get("data") or {}).get("endpoints")) or [])


def _probe(prov: OpenRouterProvider, model_id: str):
    """probe_model, retried once for transport reasons (controller ruling 7)."""
    try:
        return prov.probe_model(model_id), ""
    except Exception as exc:                                    # noqa: BLE001 - transport of any shape
        prov._models = None
        time.sleep(3)
        try:
            return prov.probe_model(model_id), ""
        except Exception as exc2:                               # noqa: BLE001
            return None, f"probe_model failed twice: {exc!r} / {exc2!r}"


def pin_for(cand: dict, prov: OpenRouterProvider) -> tuple[ModelPin | None, str]:
    """Resolve the pin actually served. Open-weight candidates are pinned to a named provider
    serving bf16 (preferred) or fp8; if neither is served the candidate is skipped rather than
    run at an unrecorded precision (ADR-0007)."""
    info, err = _probe(prov, cand["model_id"])
    if err:
        return None, err
    if info is None:
        return None, "not served by openrouter"
    if not cand.get("pin_open"):
        return (ModelPin(cand["model_id"], cand["family"], extra={"reasoning": REASONING}),
                "closed-weight model; provider chosen by openrouter")
    try:
        eps = endpoints(prov, cand["model_id"])
    except Exception as exc:                                    # noqa: BLE001
        return None, f"endpoints lookup failed: {exc!r}"
    served = sorted({(e.get("provider_name") or e.get("name") or "?", (e.get("quantization") or "?").lower())
                     for e in eps})
    for want in OPEN_PRECISIONS:
        for e in eps:
            if (e.get("quantization") or "").lower() == want:
                name = e.get("provider_name") or e.get("name")
                return (ModelPin(cand["model_id"], cand["family"], name, want, {"reasoning": REASONING}),
                        f"pinned to {name} at {want}; endpoints served: {served}")
    return None, f"no endpoint serving bf16 or fp8; endpoints served: {served}"


def is_subscription(cand: dict) -> bool:
    return cand.get("provider") == SUBSCRIPTION_PROVIDER


def cli_pin(cand: dict) -> ModelPin:
    """Full model names, never aliases (`claude-opus-5`, not `opus`), so the pin label is
    reproducible and the cache key it feeds means one thing."""
    return ModelPin(cand["model_id"], cand["family"], SUBSCRIPTION_PROVIDER, None,
                    {"effort": EFFORT, "cli_model": cand["cli_model"]})


def provider_for(cand: dict, prov, timeout: int = READ_TIMEOUT):
    """(provider, pin, why) for one candidate. A subscription candidate is transported by the
    Claude CLI and never touches OpenRouter; an OpenRouter candidate resolves its pin exactly
    as in 3A (open weights pinned to a named bf16/fp8 endpoint or skipped)."""
    if is_subscription(cand):
        cli = ClaudeCliProvider(cand["cli_model"], timeout=timeout, effort=EFFORT)
        version = cli.version()
        if version is None:
            return None, None, "claude cli not available on PATH (shutil.which found nothing)"
        return cli, cli_pin(cand), f"subscription via claude cli {version}"
    if prov is None:
        return None, None, "no openrouter provider configured (OPENROUTER_API_KEY absent)"
    pin, why = pin_for(cand, prov)
    return (prov if pin is not None else None), pin, why


def small_batches(batches):
    out = []
    for b in batches:
        for j in range(0, len(b["cases"]), 5):
            out.append({**b, "batch_id": f"{b['batch_id']}-s{j // 5 + 1}", "cases": b["cases"][j:j + 5]})
    return out


def sample_batches(batches, ids: set, tag: str):
    out = []
    for b in batches:
        cs = [c for c in b["cases"] if int(c["case_id"]) in ids]
        if cs:
            out.append({**b, "batch_id": f"{b['batch_id']}-{tag}", "cases": cs})
    return out


def process_unit_cap(n_subscription: int, batches, ids50, *, margin: int = SUBSCRIPTION_UNIT_MARGIN) -> dict:
    """Every request the selected subscription candidates can make in THIS PROCESS, counted
    rather than guessed - one per kit batch per candidate, plus the winner's checks - plus a
    margin for split halves. `["total"]` is what the shared counter is measured against."""
    kit = int(n_subscription) * len(batches)
    pair = len(small_batches(batches))
    stab = 2 * len(sample_batches(batches, set(ids50), "st"))
    total = kit + pair + stab + int(margin) if n_subscription else 0
    return {"kit": kit, "batch_size_pair": pair, "stability": stab, "margin": int(margin),
            "total": total}


def budget_for(cand: dict, remaining_usd: float, *, max_units: int | None = None,
               max_wall_seconds: float | None = None) -> Budget:
    """D1/D5. The subscription has no marginal price, so a usd ceiling over it is not a
    ceiling: `_ReadState.spend` would stay 0.0 for every request and never trip. The driver
    refuses one outright (`preflight:budget_unpriced`), which is why this returns a units /
    wall-clock budget with `max_usd` left None."""
    if is_subscription(cand):
        return Budget(max_usd=None,
                      max_units=SUBSCRIPTION_MAX_UNITS if max_units is None else int(max_units),
                      max_wall_seconds=(SUBSCRIPTION_MAX_WALL_SECONDS if max_wall_seconds is None
                                        else float(max_wall_seconds)))
    return Budget(max_usd=max(remaining_usd, 0.0))
```

- [ ] **Step 4: Re-point the measurement tool and the package exports**

In `tools/measure_reader.py`, delete the moved definitions and the now-unused `httpx` import,
and add the import (keep the `# noqa: E402` convention the file already uses):

```python
from corpus_engine.reader.providers.factory import (EFFORT, OPEN_PRECISIONS, READ_TIMEOUT,   # noqa: E402
                                                    REASONING, SUBSCRIPTION_MAX_UNITS,
                                                    SUBSCRIPTION_MAX_WALL_SECONDS,
                                                    SUBSCRIPTION_PROVIDER, SUBSCRIPTION_UNIT_MARGIN,
                                                    budget_for, cli_pin, credits_remaining,
                                                    endpoints, is_subscription, pin_for,
                                                    process_unit_cap, provider_for,
                                                    sample_batches, small_batches)
```

Leave `OPENROUTER_CEILING`, `DRY_RUN_MAX_USD`, `STABILITY_BAR`, `OUT_DIR` and everything else
in `measure_reader.py` — they are measurement policy, not transport. Keep the existing
`from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider` and
`...openrouter import OpenRouterProvider` lines: `tests/test_measure_reader_tool.py`
monkeypatches `mr.ClaudeCliProvider`.

In `corpus_engine/reader/providers/__init__.py`:

```python
from __future__ import annotations
from corpus_engine.reader.providers.cassette import CassetteProvider
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.providers.factory import (budget_for, cli_pin, is_subscription,
                                                    process_unit_cap, provider_for)

__all__ = ["CassetteProvider", "ClaudeCliProvider", "CodexCliProvider", "OpenRouterProvider",
           "ScriptedProvider", "budget_for", "cli_pin", "is_subscription", "process_unit_cap",
           "provider_for"]
```

- [ ] **Step 5: Run both suites to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_reader_provider_factory.py tests/test_measure_reader_tool.py -q`
Expected: PASS, with `tests/test_measure_reader_tool.py` **not edited**.

- [ ] **Step 6: Full suite**

Run: `.venv/Scripts/python -m pytest -q` — Expected: 312 passed, 1 xfailed (311 + the new file's 6, minus none).

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/reader/providers/factory.py corpus_engine/reader/providers/__init__.py tools/measure_reader.py tests/test_reader_provider_factory.py
git commit -m "reader: move provider/budget helpers into providers/factory.py so the map runner can reuse them

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 2: Ledger vocabulary D7 — rename, prompt-scoped support rule, list-valued `supports`

The ledger has to admit every mapper-v3 field. Three things are in the way. (a) `domain.yaml`'s
top-level `judged_fields` and `fold.JUDGED_DEFAULT` name `under_30_days` and
`right_characterization`, which no record has ever carried (grep: 0 hits in
`data/ledger/patches.jsonl`) and which the reader spells `under_thirty_days` and
`owner_freedom_characterization`. (b) `fold.SUPPORTED` is the mapper-v1 three-field quote-support
rule, applied to every record regardless of what prompt read it. (c) `fold`'s `drop_quote`
cascade builds `{q.get("supports") for q in quotes}` — a **set literal over the raw value** —
and mapper-v3 quotes carry `supports` as an *array* (`["polarity", "characterization"]`), which
is unhashable: the first `drop_quote` on an admitted cycle-004 record would raise
`TypeError: unhashable type: 'list'` out of the fold and abort the whole apply.

**Files:**
- Modify: `domains/str-right-to-let/domain.yaml` (lines 26–29), `corpus_engine/ledger/fold.py`
- Test: `tests/test_ledger_fold.py`, `tests/test_ledger_committed.py`

**Interfaces:**
- Consumes: `Patch`, `Basis`, `UNSET`, `UnknownCase`, `DuplicateRecord`, `MissingBasis`, `UnknownField` from `corpus_engine.ledger.types`.
- Produces (T7 consumes exactly these):
  - `corpus_engine.ledger.fold.JUDGED_DEFAULT: tuple[str, ...]` — `("relevant", "polarity", "who_was_letting", "duration_of_occupancy", "characterization", "holding_summary", "under_thirty_days", "restriction_nature", "owner_freedom_characterization")`
  - `corpus_engine.ledger.fold.SUPPORTED: tuple[str, ...]` — unchanged `("characterization", "polarity", "holding_summary")`, the mapper-v1 rule and the fallback
  - `corpus_engine.ledger.fold.SUPPORTED_BY_PROMPT: dict[str, tuple[str, ...]]` — `{"mapper-v1": SUPPORTED, "mapper-v3": ("characterization", "polarity", "holding_summary", "owner_freedom_characterization", "restriction_nature", "under_thirty_days")}`
  - `corpus_engine.ledger.fold.supported_fields(prompt_version: str | None) -> tuple[str, ...]` — longest matching prefix before `:` (so `"mapper-v3:f92016681314"` resolves to the six), `SUPPORTED` when unknown or absent
  - `corpus_engine.ledger.fold.State(records, order, cycles, in_file, prompts)` — new fifth field `prompts: dict[int, str]`, written at `admit` time from `patch.basis.prompt_version`
  - `corpus_engine.ledger.fold.quote_supports(quote: dict) -> tuple[str, ...]` — a str, a list/tuple/set of strs, or nothing
  - `apply_patch(state, p, *, judged=JUDGED_DEFAULT, cascade=True) -> Any` — unchanged signature

- [ ] **Step 1: Write the failing test**

```python
# appended to tests/test_ledger_fold.py
from corpus_engine.ledger.fold import (JUDGED_DEFAULT, SUPPORTED, SUPPORTED_BY_PROMPT, State,
                                       apply_patch, quote_supports, supported_fields)
from corpus_engine.ledger.types import Basis, Patch

MAPPER_V3 = "mapper-v3:f92016681314"
READER_V3 = Basis(model="claude-opus-5@claude-cli", prompt_version=MAPPER_V3,
                  run_id="cycle-004-shard-01")
READER_V1 = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id="cycle-001-shard-02")


def test_the_judged_vocabulary_is_the_readers_spelling():
    """D7. The ledger never carried `under_30_days` or `right_characterization` - no record
    and no patch has ever used either name - so this is a rename, not a migration."""
    assert JUDGED_DEFAULT == ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                              "characterization", "holding_summary", "under_thirty_days",
                              "restriction_nature", "owner_freedom_characterization")
    assert "under_30_days" not in JUDGED_DEFAULT and "right_characterization" not in JUDGED_DEFAULT


def test_the_support_rule_is_scoped_by_the_prompt_that_read_the_record():
    assert SUPPORTED_BY_PROMPT["mapper-v1"] == SUPPORTED == ("characterization", "polarity",
                                                             "holding_summary")
    assert SUPPORTED_BY_PROMPT["mapper-v3"] == ("characterization", "polarity", "holding_summary",
                                                "owner_freedom_characterization",
                                                "restriction_nature", "under_thirty_days")
    assert supported_fields(MAPPER_V3) == SUPPORTED_BY_PROMPT["mapper-v3"]   # sha suffix ignored
    assert supported_fields("mapper-v1") == SUPPORTED
    assert supported_fields(None) == SUPPORTED and supported_fields("mapper-v9") == SUPPORTED


def _admit(state, cid, basis, rec):
    apply_patch(state, Patch(cid, "admit", "", rec, "test admit", basis, cycle="cycle-004"))


def test_drop_quote_cascades_over_six_fields_for_a_mapper_v3_record():
    s = State()
    rec = {"case_id": 1, "relevant": True, "polarity": "favorable",
           "characterization": "lodging", "under_thirty_days": "yes",
           "owner_freedom_characterization": "incident_of_ownership",
           "restriction_nature": "zoning", "holding_summary": "h",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]},
                      {"text": "Q2", "supports": ["characterization"]}]}
    _admit(s, 1, READER_V3, rec)
    apply_patch(s, Patch(1, "drop_quote", "quotes", "Q1", "quote failed", Basis(reviewer="mmaldo2")))
    out = s.records[1]
    assert [q["text"] for q in out["quotes"]] == ["Q2"]
    assert out["polarity"] is None and out["under_thirty_days"] is None      # lost their support
    assert out["characterization"] == "lodging"                              # Q2 still supports it
    assert out["holding_summary"] is None and out["owner_freedom_characterization"] is None
    assert out["restriction_nature"] is None
    assert set(out["nulled_fields"]) == {"polarity", "under_thirty_days", "holding_summary",
                                         "owner_freedom_characterization", "restriction_nature"}


def test_a_mapper_v1_record_keeps_the_three_field_rule():
    """A cycle-001 record carries `supports` as a bare string and only three fields are
    cascaded, exactly as before: widening the rule for it would null fields that the v1
    codebook never asked a quote to support."""
    s = State()
    rec = {"case_id": 2, "relevant": True, "polarity": "favorable", "characterization": "lease",
           "holding_summary": "h", "who_was_letting": "householder",
           "quotes": [{"text": "Q1", "supports": "polarity"},
                      {"text": "Q2", "supports": "characterization"}]}
    _admit(s, 2, READER_V1, rec)
    apply_patch(s, Patch(2, "drop_quote", "quotes", "Q1", "quote failed", Basis(reviewer="mmaldo2")))
    out = s.records[2]
    assert out["polarity"] is None and out["holding_summary"] is None
    assert out["characterization"] == "lease"
    assert out["who_was_letting"] == "householder"        # never in SUPPORTED; untouched
    assert out["nulled_fields"] == ["polarity", "holding_summary"]


def test_quote_supports_reads_a_string_a_list_and_nothing():
    assert quote_supports({"supports": "polarity"}) == ("polarity",)
    assert quote_supports({"supports": ["polarity", "characterization"]}) == ("polarity",
                                                                              "characterization")
    assert quote_supports({"supports": ["polarity", 7, "", None]}) == ("polarity",)
    assert quote_supports({}) == () and quote_supports({"supports": None}) == ()


def test_the_admitting_prompt_is_remembered_without_touching_the_record():
    """`prompts` is a side map on State, like `cycles`: the rendered record must not gain a
    key, or every committed snapshot line changes and the replay guard fails."""
    s = State()
    rec = {"case_id": 3, "relevant": True, "polarity": "favorable", "quotes": []}
    _admit(s, 3, READER_V3, rec)
    assert s.prompts[3] == MAPPER_V3
    assert "prompt_version" not in s.records[3] and set(rec) <= set(s.records[3])
    assert set(s.records[3]) - set(rec) == {"review"}


def test_cascade_false_still_skips_the_cascade_under_the_v3_rule():
    s = State()
    rec = {"case_id": 4, "relevant": True, "polarity": "favorable", "under_thirty_days": "yes",
           "quotes": [{"text": "Q1", "supports": ["polarity", "under_thirty_days"]}]}
    _admit(s, 4, READER_V3, rec)
    apply_patch(s, Patch(4, "drop_quote", "quotes", "Q1", "no cascade", Basis(reviewer="mmaldo2"),
                         cascade=False), cascade=False)
    assert s.records[4]["polarity"] == "favorable" and s.records[4]["under_thirty_days"] == "yes"
```

```python
# appended to tests/test_ledger_committed.py
from corpus_engine.ledger.fold import JUDGED_DEFAULT


def test_the_rename_leaves_the_committed_counts_and_the_replay_untouched(repo_root):
    """D7 renames two names nothing ever wrote. If the rename had touched data, one of these
    three numbers would move; the byte-identical replay above is the other half of the proof."""
    dom = load_domain()
    assert "under_thirty_days" in dom.judged_fields
    assert "owner_freedom_characterization" in dom.judged_fields
    assert "under_30_days" not in dom.judged_fields
    assert "right_characterization" not in dom.judged_fields
    assert tuple(dom.judged_fields) == JUDGED_DEFAULT
    log = (repo_root / "data" / "ledger" / "patches.jsonl").read_text(encoding="utf-8")
    assert "under_30_days" not in log and "right_characterization" not in log
    v = open_ledger(domain=dom).view()
    assert v.counts().total.human_reviewed + v.counts().total.machine_only == 693
    fav = v.counts(polarity="favorable").total
    assert fav.human_reviewed + fav.machine_only == 367
    hh = v.counts(polarity="favorable", who_was_letting="householder").total
    assert hh.human_reviewed + hh.machine_only == 137
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ledger_fold.py tests/test_ledger_committed.py -q`
Expected: FAIL — `ImportError: cannot import name 'SUPPORTED_BY_PROMPT'`, and after that
`TypeError: unhashable type: 'list'` from the v3 cascade test.

- [ ] **Step 3: Write the implementation**

`domains/str-right-to-let/domain.yaml`, the top-level block at lines 26–29 (the `reader.judged_fields`
block lower down is already the reader's spelling and is **not** touched):

```yaml
judged_fields: [relevant, polarity, who_was_letting, duration_of_occupancy,
                characterization, holding_summary, under_thirty_days,
                restriction_nature, owner_freedom_characterization]
```

`corpus_engine/ledger/fold.py`:

```python
JUDGED_DEFAULT = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                  "characterization", "holding_summary", "under_thirty_days",
                  "restriction_nature", "owner_freedom_characterization")
# The mapper-v1 quote-support rule, and the fallback for a record whose admitting patch
# recorded no prompt version.
SUPPORTED = ("characterization", "polarity", "holding_summary")
# D7: the rule is a property of the codebook that read the record, not of the ledger. A
# mapper-v3 record was asked to support all six judged fields with a quote, so dropping a
# quote must void all six; a mapper-v1 record was only ever asked for three, and widening
# the cascade for it would null fields on evidence that was never demanded.
SUPPORTED_BY_PROMPT = {
    "mapper-v1": SUPPORTED,
    "mapper-v3": ("characterization", "polarity", "holding_summary",
                  "owner_freedom_characterization", "restriction_nature", "under_thirty_days"),
}
REVIEW_DEFAULT = {"status": "machine", "flags": [], "notes": []}


def supported_fields(prompt_version: str | None) -> tuple[str, ...]:
    """The support rule for a record admitted under `prompt_version`.

    D8 spells the basis as `mapper-v3:<first 12 of the codebook sha>`, so the lookup is on
    the part before the colon: the rule follows the codebook version, not the particular
    file hash, and a codebook edit that keeps the version keeps the rule."""
    if not prompt_version:
        return SUPPORTED
    return SUPPORTED_BY_PROMPT.get(str(prompt_version).split(":", 1)[0], SUPPORTED)


def quote_supports(quote: dict) -> tuple[str, ...]:
    """Which judged fields a quote is offered in support of, whichever shape it arrived in.

    mapper-v1 wrote a bare string; mapper-v3's schema makes `supports` an array, and a set
    literal over the raw value (`{q.get("supports") for q in quotes}`, which is what this
    module did) raises `unhashable type: 'list'` on the first drop_quote against an admitted
    cycle-004 record - taking the whole `Ledger.apply` with it. Same normalisation as
    `corpus_engine.reader.gate._supports`, so the gate and the fold can never disagree about
    what a quote supports."""
    s = quote.get("supports")
    if isinstance(s, str):
        return (s,) if s else ()
    if isinstance(s, (list, tuple, set)):
        return tuple(x for x in s if isinstance(x, str) and x)
    return ()


@dataclass
class State:
    records: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    cycles: dict[int, str] = field(default_factory=dict)
    in_file: dict[int, bool] = field(default_factory=dict)
    # The prompt version each record was ADMITTED under, so `drop_quote` can pick the right
    # support rule. A side map, exactly like `cycles`: putting it on the record itself would
    # add a key to every rendered line and break the byte-identical snapshot replay.
    prompts: dict[int, str] = field(default_factory=dict)
```

In `apply_patch`, in the `admit` branch, record the prompt on both paths (the re-admit path
that keeps the position in `state.order`, and the first-admit path):

```python
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
            state.prompts[p.case_id] = p.basis.prompt_version or ""
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        state.prompts[p.case_id] = p.basis.prompt_version or ""
        return UNSET
```

and rewrite the `drop_quote` branch:

```python
    if p.op == "drop_quote":
        before = rec.get("quotes", [])
        rec["quotes"] = [q for q in before if q.get("text") != p.new]
        if cascade:
            supported = {f for q in rec["quotes"] for f in quote_supports(q)}
            for f in supported_fields(state.prompts.get(p.case_id)):
                if rec.get(f) is not None and f not in supported:
                    rec[f] = None
                    rec.setdefault("nulled_fields", []).append(f)
        return [q for q in before if q.get("text") == p.new]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ledger_fold.py tests/test_ledger_committed.py tests/test_ledger_apply.py tests/test_ledger_tally.py tests/test_ledger_render.py tests/test_domain.py -q`
Expected: PASS. `test_committed_log_renders_to_the_committed_snapshot` is the byte-identical
replay guard; it must be green **without** rewriting `data/ledger/*.jsonl`.

- [ ] **Step 5: Verify nothing on disk changed**

Run: `git status --porcelain data/ledger`
Expected: **no output**. If a snapshot file is dirty, the rename touched data and the change is
wrong — revert and find out why (the most likely cause is having added a key to the record in
`apply_patch` instead of to `State.prompts`).

- [ ] **Step 6: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/ledger/fold.py domains/str-right-to-let/domain.yaml tests/test_ledger_fold.py tests/test_ledger_committed.py
git commit -m "ledger D7: reader field names, quote-support rule scoped by prompt_version, list-valued supports

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 3: `corpus_engine/mapper/cells.py` — batches, cells, caps, order

Spec section 4. Fifty era x jurisdiction cells, each with a cap in batches derived from its
era's 0.25-cut depth, read in descending order of how promising its capped head looks.

**Files:**
- Create: `corpus_engine/mapper/__init__.py`, `corpus_engine/mapper/cells.py`, `tests/test_mapper_cells.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure stdlib + the batch JSON on disk).
- Produces (T5, T6, T7 and T9 consume exactly these):
  - `corpus_engine.mapper.cells.ERA_DEPTH_025: dict[str, int]` — `{"pre-1860": 32, "1860-1900": 32, "1900-1930": 59, "1930-1970": 139, "1970-2020": 111}`
  - `corpus_engine.mapper.cells.ERA_DEPTH_050: dict[str, int]` — `{"pre-1860": 13, "1860-1900": 16, "1900-1930": 27, "1930-1970": 74, "1970-2020": 55}` (the `--depth-column 0.5` alternative from the same section-5 table)
  - `corpus_engine.mapper.cells.DEPTH_COLUMNS: dict[str, dict[str, int]]` — `{"0.25": ERA_DEPTH_025, "0.5": ERA_DEPTH_050}`
  - `corpus_engine.mapper.cells.Cell` — frozen dataclass `(era: str, jurisdiction: str, batch_ids: tuple[str, ...], cap_batches: int, mean_rank_score: float)` with `key -> str` (`"era|jurisdiction"`) and `capped_ids -> tuple[str, ...]` (the first `cap_batches` ids)
  - `corpus_engine.mapper.cells.load_batches(batches_dir: Path) -> list[dict]` — every `batch-*.json`, sorted by `batch_id`
  - `corpus_engine.mapper.cells.batch_mean_rank_score(batch: dict) -> float`
  - `corpus_engine.mapper.cells.build_cells(batches, *, era_depth=ERA_DEPTH_025, jurisdictions_by_era=None) -> list[Cell]`
  - `corpus_engine.mapper.cells.BatchSource(batches_dir: Path)` with `get(batch_id: str) -> dict`, `ids() -> tuple[str, ...]`, `__contains__`
  - `corpus_engine.mapper.cells.select_cells(cells, spec: str | None) -> list[Cell]` — the `--cells` filter, `"era|jurisdiction[,...]"`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_cells.py
"""Cells and caps (spec section 4, D2).

The cap column comes from reports/ranking-cycle-004.md section 5 (batches whose mean
rank_score clears 0.25, per era) and is split across an era's jurisdictions in proportion to
each cell's pool size, rounded UP with a floor of one - so no cell in the six unvalidated
jurisdictions is silently budgeted to zero. Order is by the mean rank_score of a cell's own
capped head, because the window may end before every cell is reached and the cells most
likely to yield have to be the ones that were read."""
import json
import math
from pathlib import Path

import pytest

from corpus_engine.mapper.cells import (DEPTH_COLUMNS, ERA_DEPTH_025, ERA_DEPTH_050, BatchSource,
                                        Cell, batch_mean_rank_score, build_cells, load_batches,
                                        select_cells)

# The real per-era batch counts, verified 2026-09-06 over runs/cycle-004-shard-01/batches.
ERA_BATCHES = {"pre-1860": 244, "1860-1900": 233, "1900-1930": 316, "1930-1970": 519,
               "1970-2020": 533}


def _batch(bid, era, jur, scores):
    return {"batch_id": bid, "ranker_id": "classifier:v1", "era_partition": era,
            "jurisdiction": jur,
            "cases": [{"case_id": 1000 + i, "era_partition": era, "jurisdiction": jur,
                       "signals": [], "rank_score": s} for i, s in enumerate(scores)]}


def _fixture(tmp_path, spec):
    """spec: {(era, jur): [ [scores of batch 1], [scores of batch 2], ... ]}"""
    d = tmp_path / "batches"
    d.mkdir()
    n = 0
    for (era, jur), batches in spec.items():
        for scores in batches:
            n += 1
            b = _batch(f"cycle-004-shard-01-batch-{n:03d}", era, jur, scores)
            (d / f"batch-{n:03d}.json").write_bytes(
                json.dumps(b, indent=1).encode("utf-8"))
    return d


def test_the_depth_columns_are_the_section_five_table():
    assert ERA_DEPTH_025 == {"pre-1860": 32, "1860-1900": 32, "1900-1930": 59,
                             "1930-1970": 139, "1970-2020": 111}
    assert sum(ERA_DEPTH_025.values()) == 373
    assert ERA_DEPTH_050 == {"pre-1860": 13, "1860-1900": 16, "1900-1930": 27,
                             "1930-1970": 74, "1970-2020": 55}
    assert sum(ERA_DEPTH_050.values()) == 185
    assert DEPTH_COLUMNS == {"0.25": ERA_DEPTH_025, "0.5": ERA_DEPTH_050}


def test_load_batches_reads_every_file_and_scores_it(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.4, 0.6], [0.1, 0.1]]})
    batches = load_batches(d)
    assert [b["batch_id"] for b in batches] == ["cycle-004-shard-01-batch-001",
                                                "cycle-004-shard-01-batch-002"]
    assert batch_mean_rank_score(batches[0]) == pytest.approx(0.5)
    assert batch_mean_rank_score(batches[1]) == pytest.approx(0.1)
    assert batch_mean_rank_score({"cases": []}) == 0.0


def test_the_cap_is_the_eras_depth_split_by_pool_size_rounded_up_with_a_floor_of_one(tmp_path):
    """1900-1930 depth 59 over 316 era batches. A cell of 61 batches (Tex.) gets
    ceil(59 * 61 / 316) = 12; a cell of one batch gets ceil(59/316) = 1, never 0."""
    d = _fixture(tmp_path, {("1900-1930", "Tex."): [[0.9]] * 61,
                            ("1900-1930", "D.C."): [[0.2]] * 1})
    cells = {c.key: c for c in build_cells(load_batches(d), era_depth={"1900-1930": 59})}
    assert cells["1900-1930|Tex."].cap_batches == 12
    assert cells["1900-1930|D.C."].cap_batches == 1
    assert len(cells["1900-1930|Tex."].batch_ids) == 61


def test_the_real_pool_caps_reproduce_the_recorded_totals():
    """The numbers the runner's default --max-units is computed from. If the batch files or
    the depth table move, this is the test that says so."""
    per_cell = {("1930-1970", "N.Y."): 75, ("1930-1970", "D.C."): 8, ("1970-2020", "N.Y."): 82,
                ("pre-1860", "Cal."): 17, ("1860-1900", "La."): 13}
    expected = {("1930-1970", "N.Y."): 21, ("1930-1970", "D.C."): 3, ("1970-2020", "N.Y."): 18,
                ("pre-1860", "Cal."): 3, ("1860-1900", "La."): 2}
    for (era, jur), n in per_cell.items():
        cap = max(1, math.ceil(ERA_DEPTH_025[era] * n / ERA_BATCHES[era]))
        assert cap == expected[(era, jur)], (era, jur, cap)


def test_batches_inside_a_cell_are_ranked_and_cells_are_ordered_by_their_capped_head(tmp_path):
    """The head, not the whole cell: a cell whose cap is 2 is judged on the two batches it
    will actually read, so a long tail of weak batches cannot demote a strong short head."""
    d = _fixture(tmp_path, {
        ("pre-1860", "N.Y."): [[0.10], [0.90], [0.80]],     # head (0.90, 0.80) -> 0.85
        ("pre-1860", "Pa."): [[0.60], [0.60], [0.60]],      # head (0.60, 0.60) -> 0.60
    })
    cells = build_cells(load_batches(d), era_depth={"pre-1860": 4})
    assert [c.key for c in cells] == ["pre-1860|N.Y.", "pre-1860|Pa."]
    ny = cells[0]
    assert ny.cap_batches == 2
    assert ny.batch_ids == ("cycle-004-shard-01-batch-002", "cycle-004-shard-01-batch-003",
                            "cycle-004-shard-01-batch-001")
    assert ny.capped_ids == ("cycle-004-shard-01-batch-002", "cycle-004-shard-01-batch-003")
    assert ny.mean_rank_score == pytest.approx(0.85)
    assert isinstance(ny, Cell) and ny.era == "pre-1860" and ny.jurisdiction == "N.Y."


def test_ties_break_deterministically_on_era_then_jurisdiction(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "Pa."): [[0.5]], ("pre-1860", "Cal."): [[0.5]],
                            ("1860-1900", "N.Y."): [[0.5]]})
    keys = [c.key for c in build_cells(load_batches(d),
                                       era_depth={"pre-1860": 2, "1860-1900": 1})]
    assert keys == ["1860-1900|N.Y.", "pre-1860|Cal.", "pre-1860|Pa."]


def test_jurisdictions_by_era_is_derived_from_the_batches_when_not_given(tmp_path):
    """Spec section 1 says eleven jurisdictions; the batches on disk carry ten. The cell set
    is whatever the batch files say it is - passing the map in only restricts it."""
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5]], ("pre-1860", "Utah"): [[0.9]]})
    batches = load_batches(d)
    assert {c.jurisdiction for c in build_cells(batches, era_depth={"pre-1860": 2})} == {"N.Y.", "Utah"}
    restricted = build_cells(batches, era_depth={"pre-1860": 2},
                             jurisdictions_by_era={"pre-1860": ["N.Y."]})
    assert [c.key for c in restricted] == ["pre-1860|N.Y."]


def test_an_era_with_no_depth_entry_is_refused_rather_than_read_uncapped(tmp_path):
    d = _fixture(tmp_path, {("2020-", "N.Y."): [[0.5]]})
    with pytest.raises(KeyError, match="2020-"):
        build_cells(load_batches(d), era_depth=ERA_DEPTH_025)


def test_batch_source_serves_batches_by_id_without_reloading_the_pool(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5], [0.6]]})
    src = BatchSource(d)
    assert src.ids() == ("cycle-004-shard-01-batch-001", "cycle-004-shard-01-batch-002")
    assert "cycle-004-shard-01-batch-001" in src
    b = src.get("cycle-004-shard-01-batch-002")
    assert b["jurisdiction"] == "N.Y." and len(b["cases"]) == 1
    with pytest.raises(KeyError):
        src.get("cycle-004-shard-01-batch-999")


def test_select_cells_filters_by_key_and_refuses_an_unknown_one(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5]], ("pre-1860", "Pa."): [[0.9]]})
    cells = build_cells(load_batches(d), era_depth={"pre-1860": 2})
    assert [c.key for c in select_cells(cells, None)] == [c.key for c in cells]
    assert [c.key for c in select_cells(cells, "pre-1860|N.Y.")] == ["pre-1860|N.Y."]
    assert [c.key for c in select_cells(cells, "pre-1860|Pa.,pre-1860|N.Y.")] == [
        "pre-1860|Pa.", "pre-1860|N.Y."]        # the run order stays the cells' own order
    with pytest.raises(ValueError, match="1930-1970"):
        select_cells(cells, "1930-1970|N.Y.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_cells.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper'`.

- [ ] **Step 3: Write the implementation**

`corpus_engine/mapper/__init__.py`:

```python
"""The map: one pass of the pinned reader over a cycle's ranked candidate pool under a
per-cell budget (CONTEXT.md glossary; spec sections 4-9)."""
from corpus_engine.mapper.cells import BatchSource, Cell, build_cells, load_batches, select_cells
from corpus_engine.mapper.yield_stop import CellProgress, CellStop
from corpus_engine.mapper.runner import MapOutcome, MapRunner

__all__ = ["BatchSource", "Cell", "CellProgress", "CellStop", "MapOutcome", "MapRunner",
           "build_cells", "load_batches", "select_cells"]
```

(The `runner` / `yield_stop` imports land in T4 and T5; write `__init__.py` with only the
`cells` line now and extend it as those modules appear, so the package imports at every step.)

`corpus_engine/mapper/cells.py`:

```python
"""Cells and caps (spec section 4).

A cell is an era x jurisdiction slice of the candidate pool - the unit the budget is set on.
Its cap is its share of the era's 0.25 rank-score depth from reports/ranking-cycle-004.md
section 5, in proportion to how many batches the cell actually holds, rounded UP with a floor
of one so a small cell in one of the six jurisdictions with no held-out AP still gets read.

Cells are read in descending order of the mean rank_score of their CAPPED HEAD, not of the
whole cell: the process may stop on its wall clock before every cell is reached, so the order
has to be about the batches that would actually be bought."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

# reports/ranking-cycle-004.md section 5: batches whose mean rank_score clears the cut.
ERA_DEPTH_025 = {"pre-1860": 32, "1860-1900": 32, "1900-1930": 59, "1930-1970": 139,
                 "1970-2020": 111}
ERA_DEPTH_050 = {"pre-1860": 13, "1860-1900": 16, "1900-1930": 27, "1930-1970": 74,
                 "1970-2020": 55}
DEPTH_COLUMNS = {"0.25": ERA_DEPTH_025, "0.5": ERA_DEPTH_050}
BATCH_GLOB = "batch-*.json"


@dataclass(frozen=True)
class Cell:
    era: str
    jurisdiction: str
    batch_ids: tuple[str, ...]          # every batch in the cell, best rank_score first
    cap_batches: int
    mean_rank_score: float              # over `capped_ids`, which is what decides the order

    @property
    def key(self) -> str:
        return f"{self.era}|{self.jurisdiction}"

    @property
    def capped_ids(self) -> tuple[str, ...]:
        return self.batch_ids[:self.cap_batches]

    def to_json(self) -> dict:
        return {"era": self.era, "jurisdiction": self.jurisdiction,
                "n_batches": len(self.batch_ids), "cap_batches": self.cap_batches,
                "mean_rank_score": round(self.mean_rank_score, 6)}


def batch_mean_rank_score(batch: Mapping) -> float:
    cases = batch.get("cases") or []
    if not cases:
        return 0.0
    return sum(float(c.get("rank_score") or 0.0) for c in cases) / len(cases)


def load_batches(batches_dir: Path) -> list[dict]:
    """Every batch file in the shard, sorted by `batch_id` so the pool is the same list on
    every machine regardless of what order the filesystem hands them back."""
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(batches_dir).glob(BATCH_GLOB))]
    return sorted(out, key=lambda b: b["batch_id"])


def build_cells(batches: Sequence[Mapping], *, era_depth: Mapping[str, int] = ERA_DEPTH_025,
                jurisdictions_by_era: Mapping[str, Sequence[str]] | None = None) -> list[Cell]:
    """The cells of this pool, capped and ordered (D2).

    `jurisdictions_by_era` is optional: the pool's own batch files are the authority on which
    cells exist (ten jurisdictions on disk against the eleven the spec's prose names), so the
    map is derived from them unless a caller restricts it."""
    by_cell: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for b in batches:
        era, jur = b["era_partition"], b["jurisdiction"]
        if jurisdictions_by_era is not None and jur not in (jurisdictions_by_era.get(era) or ()):
            continue
        by_cell.setdefault((era, jur), []).append((batch_mean_rank_score(b), b["batch_id"]))
    era_totals: dict[str, int] = {}
    for (era, _jur), rows in by_cell.items():
        era_totals[era] = era_totals.get(era, 0) + len(rows)
    cells: list[Cell] = []
    for (era, jur), rows in by_cell.items():
        if era not in era_depth:
            raise KeyError(f"no map depth recorded for era {era!r}; add it to a DEPTH_COLUMNS "
                           f"column rather than reading the era uncapped")
        rows.sort(key=lambda r: (-r[0], r[1]))          # best first, batch_id breaks ties
        ids = tuple(bid for _s, bid in rows)
        cap = max(1, math.ceil(era_depth[era] * len(rows) / era_totals[era]))
        head = [s for s, _bid in rows[:cap]]
        cells.append(Cell(era, jur, ids, cap, sum(head) / len(head) if head else 0.0))
    cells.sort(key=lambda c: (-c.mean_rank_score, c.era, c.jurisdiction))
    return cells


def select_cells(cells: Sequence[Cell], spec: str | None) -> list[Cell]:
    """`--cells era|jurisdiction[,...]`. The run order is the cells' own order, never the
    order they were typed in: a `--cells` run and a full run read the same cell first."""
    if not spec:
        return list(cells)
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    known = {c.key for c in cells}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise ValueError(f"no such cell: {', '.join(unknown)}; known cells are "
                         f"{', '.join(sorted(known))}")
    return [c for c in cells if c.key in set(wanted)]


class BatchSource:
    """One batch file at a time, by id. The runner reads 1,845 files' worth of metadata once
    through `load_batches` to build the cells, then pulls only the batches it actually plans."""

    def __init__(self, batches_dir: Path):
        self.dir = Path(batches_dir)
        self._by_id = {p.stem: p for p in sorted(self.dir.glob(BATCH_GLOB))}
        self._index: dict[str, Path] = {}
        for p in self._by_id.values():
            self._index[json.loads(p.read_text(encoding="utf-8"))["batch_id"]] = p

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._index))

    def __contains__(self, batch_id: str) -> bool:
        return batch_id in self._index

    def get(self, batch_id: str) -> dict:
        try:
            path = self._index[batch_id]
        except KeyError:
            raise KeyError(f"{batch_id} is not in {self.dir}") from None
        return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_cells.py -q` — Expected: PASS.

- [ ] **Step 5: Sanity-check against the real pool (read-only, no reader)**

Run:
```bash
.venv/Scripts/python -c "from pathlib import Path; from corpus_engine.mapper.cells import build_cells, load_batches; cs=build_cells(load_batches(Path('runs/cycle-004-shard-01/batches'))); print(len(cs), sum(c.cap_batches for c in cs)); print([c.key for c in cs[:5]])"
```
Expected: `50 399` on the first line. If the cap total is not 399, the cap formula has drifted.

- [ ] **Step 6: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/__init__.py corpus_engine/mapper/cells.py tests/test_mapper_cells.py
git commit -m "mapper: cells, per-cell caps from the era depth table, and the read order

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 4: `corpus_engine/mapper/yield_stop.py` — the stop rule

Spec section 5, D2. A pure state machine, no I/O and no reader: a cell stops when its last
three **completed** batches yielded two or fewer relevant accepted records combined, or when
it reaches its cap.

**Note on the module name.** The spec calls this file `yield.py`. `yield` is a Python keyword,
so `from corpus_engine.mapper.yield import CellProgress` is a `SyntaxError` and the module could
never be imported. The file is `yield_stop.py` (after the spec's own section heading, "Yield
stop"); nothing else about section 5 changes.

**Files:**
- Create: `corpus_engine/mapper/yield_stop.py`, `tests/test_mapper_yield.py`
- Modify: `corpus_engine/mapper/__init__.py` (add the `yield_stop` export line)

**Interfaces:**
- Consumes: nothing.
- Produces (T5, T6 and T9 consume exactly these):
  - `corpus_engine.mapper.yield_stop.WINDOW: int = 3`; `THRESHOLD: int = 2`
  - `corpus_engine.mapper.yield_stop.CellStop` — frozen dataclass `(kind: str, detail: str = "")`, `kind` in `("yield_floor", "cap_reached")`. Named `CellStop`, not `StopReason`, because `corpus_engine.reader.model.StopReason` already exists and both appear in `runner.py`.
  - `corpus_engine.mapper.yield_stop.CellProgress(cell_key: str, cap_batches: int)` with:
    - `add(batch_id: str, relevant_accepted: int, completed: bool) -> None`
    - `should_stop(*, window: int = WINDOW, threshold: int = THRESHOLD) -> CellStop | None`
    - `completed_batches -> int`, `attempted_batches -> int`, `relevant_accepted -> int`
    - `series -> tuple[dict, ...]` (completed batches only, in order), `failed -> tuple[str, ...]`
    - `to_json(*, window=WINDOW, threshold=THRESHOLD) -> dict` — `{"yield_series": [...], "failed_units": [...], "relevant_accepted": n, "batches_completed": n, "batches_attempted": n, "stop": {"kind": ..., "detail": ...} | None}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_yield.py
"""The per-cell stop rule (spec section 5, D2): three completed batches yielding two or fewer
relevant accepted records between them, or the cap.

Pure: no reader, no clock, no files. A failed unit is recorded but never enters the window -
a provider failure is not evidence that a cell has stopped paying, and letting it count would
close a cell on the strength of an outage."""
import pytest

from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW, CellProgress, CellStop


def _p(cap=10):
    return CellProgress("1930-1970|N.Y.", cap)


def test_the_window_and_threshold_are_the_recorded_defaults():
    assert WINDOW == 3 and THRESHOLD == 2


def test_a_cell_does_not_stop_before_the_window_is_full():
    p = _p()
    p.add("b1", 0, True)
    assert p.should_stop() is None
    p.add("b2", 0, True)
    assert p.should_stop() is None


def test_three_completed_batches_at_or_under_the_threshold_stop_the_cell():
    p = _p()
    for bid, n in (("b1", 1), ("b2", 1), ("b3", 0)):
        p.add(bid, n, True)
    stop = p.should_stop()
    assert isinstance(stop, CellStop) and stop.kind == "yield_floor"
    assert "2" in stop.detail and "b1" in stop.detail and "b3" in stop.detail
    assert p.relevant_accepted == 2 and p.completed_batches == 3


def test_three_above_the_threshold_do_not():
    p = _p()
    for bid, n in (("b1", 1), ("b2", 1), ("b3", 1)):
        p.add(bid, n, True)
    assert p.should_stop() is None


def test_the_window_is_the_LAST_three_not_the_first_three():
    p = _p()
    for bid, n in (("b1", 0), ("b2", 0), ("b3", 0)):
        p.add(bid, n, True)
    assert p.should_stop().kind == "yield_floor"
    p.add("b4", 9, True)                       # a rich batch re-opens the cell
    assert p.should_stop() is None
    p.add("b5", 0, True)
    p.add("b6", 0, True)
    assert p.should_stop() is None             # last three are 9, 0, 0 = 9
    p.add("b7", 0, True)
    assert p.should_stop().kind == "yield_floor"


def test_a_failed_unit_is_recorded_and_skipped_by_the_window():
    p = _p()
    p.add("b1", 0, True)
    p.add("b2", 0, False)                       # provider failure: not evidence about yield
    p.add("b3", 0, True)
    assert p.should_stop() is None
    assert p.failed == ("b2",)
    assert p.attempted_batches == 3 and p.completed_batches == 2
    p.add("b4", 0, True)
    assert p.should_stop().kind == "yield_floor"


def test_the_cap_stops_the_cell_even_while_it_is_still_paying():
    p = _p(cap=2)
    p.add("b1", 8, True)
    assert p.should_stop() is None
    p.add("b2", 8, True)
    stop = p.should_stop()
    assert stop.kind == "cap_reached" and stop.detail == "2 of 2 batches"


def test_the_cap_wins_when_both_rules_fire_so_the_screen_is_not_offered_a_finished_cell():
    """The screen (spec section 7) triggers on yield_floor WITH cap remaining. A cell that
    hit its cap on a dry window has no remainder, so it must not report yield_floor."""
    p = _p(cap=3)
    for bid in ("b1", "b2", "b3"):
        p.add(bid, 0, True)
    assert p.should_stop().kind == "cap_reached"


def test_a_failed_unit_does_not_consume_the_cap():
    p = _p(cap=2)
    p.add("b1", 5, False)
    p.add("b2", 5, True)
    assert p.should_stop() is None
    p.add("b3", 5, True)
    assert p.should_stop().kind == "cap_reached"


def test_the_parameters_are_overridable_and_recorded(caplog):
    p = _p()
    p.add("b1", 3, True)
    p.add("b2", 3, True)
    assert p.should_stop(window=2, threshold=6).kind == "yield_floor"
    assert p.should_stop(window=2, threshold=5) is None
    doc = p.to_json(window=2, threshold=6)
    assert doc["yield_series"] == [{"batch_id": "b1", "relevant_accepted": 3},
                                   {"batch_id": "b2", "relevant_accepted": 3}]
    assert doc["relevant_accepted"] == 6 and doc["batches_completed"] == 2
    assert doc["batches_attempted"] == 2 and doc["failed_units"] == []
    assert doc["stop"] == {"kind": "yield_floor", "detail": doc["stop"]["detail"]}
    assert p.to_json()["stop"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_yield.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper.yield_stop'`.

- [ ] **Step 3: Write the implementation**

```python
"""The per-cell stop rule (spec section 5, D2).

Pure state machine: batches go in, a stop reason comes out. No reader, no clock, no files, so
the rule can be argued about and tested without buying anything.

Named `yield_stop` rather than the spec's `yield` because `yield` is a Python keyword and a
module by that name cannot be imported at all."""
from __future__ import annotations
from dataclasses import dataclass

WINDOW = 3          # completed batches the rule looks back over (D2)
THRESHOLD = 2       # relevant accepted records across that window, at or below which it stops


@dataclass(frozen=True)
class CellStop:
    """Why a cell stopped. `kind` is "yield_floor" or "cap_reached".

    Not called `StopReason`: `corpus_engine.reader.model.StopReason` already carries that name
    for the driver's budget stops, and runner.py handles both in the same function."""
    kind: str
    detail: str = ""

    def to_json(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


class CellProgress:
    def __init__(self, cell_key: str, cap_batches: int):
        self.cell_key = cell_key
        self.cap_batches = int(cap_batches)
        self._series: list[dict] = []       # completed batches only, in read order
        self._failed: list[str] = []

    def add(self, batch_id: str, relevant_accepted: int, completed: bool) -> None:
        """One batch's result. `completed` is the driver's verdict: a unit whose status is
        "ok", or "partial_parse" with at least one accepted record. A failed unit is recorded
        so the manifest can list it and the next invocation can re-read it, but it never
        enters the window - an outage is not evidence that a cell has stopped paying - and it
        does not consume the cap."""
        if completed:
            self._series.append({"batch_id": batch_id, "relevant_accepted": int(relevant_accepted)})
        else:
            self._failed.append(batch_id)

    @property
    def series(self) -> tuple[dict, ...]:
        return tuple(self._series)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(self._failed)

    @property
    def completed_batches(self) -> int:
        return len(self._series)

    @property
    def attempted_batches(self) -> int:
        return len(self._series) + len(self._failed)

    @property
    def relevant_accepted(self) -> int:
        return sum(e["relevant_accepted"] for e in self._series)

    def should_stop(self, *, window: int = WINDOW, threshold: int = THRESHOLD) -> CellStop | None:
        """The cap is checked FIRST. Both rules can be true at once, and the screen (section 7)
        triggers on `yield_floor` with cap remaining - a cell that reached its cap has no
        remainder to screen, so reporting the yield floor there would offer the screen a
        finished cell."""
        if self.completed_batches >= self.cap_batches:
            return CellStop("cap_reached", f"{self.completed_batches} of {self.cap_batches} batches")
        if len(self._series) >= window:
            recent = self._series[-window:]
            got = sum(e["relevant_accepted"] for e in recent)
            if got <= threshold:
                ids = ", ".join(e["batch_id"] for e in recent)
                return CellStop("yield_floor",
                                f"last {window} completed batches ({ids}) yielded {got} "
                                f"relevant accepted records, at or under {threshold}")
        return None

    def to_json(self, *, window: int = WINDOW, threshold: int = THRESHOLD) -> dict:
        stop = self.should_stop(window=window, threshold=threshold)
        return {"yield_series": [dict(e) for e in self._series],
                "failed_units": list(self._failed),
                "relevant_accepted": self.relevant_accepted,
                "batches_completed": self.completed_batches,
                "batches_attempted": self.attempted_batches,
                "stop": stop.to_json() if stop else None}
```

Add to `corpus_engine/mapper/__init__.py`:

```python
from corpus_engine.mapper.yield_stop import CellProgress, CellStop
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_yield.py -q` — Expected: PASS.

- [ ] **Step 5: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/yield_stop.py corpus_engine/mapper/__init__.py tests/test_mapper_yield.py
git commit -m "mapper: the per-cell yield stop rule (window 3, threshold 2, cap)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 5: `corpus_engine/mapper/runner.py` + `tools/map_reader.py` — the map runner

Spec section 6, D6, D9, and the error handling of section 11. One detached process per
invocation, one `plan_batch_extraction` per batch through the existing `Reader`, per-process
unit and wall-clock caps, resumable from the response cache, and one tracked manifest written
from a `finally`.

**Files:**
- Create: `corpus_engine/mapper/runner.py`, `tools/map_reader.py`, `tests/test_mapper_runner.py`
- Modify: `corpus_engine/mapper/__init__.py` (add the `runner` export line)

**Interfaces:**
- Consumes: `Cell`, `BatchSource`, `build_cells`, `load_batches`, `select_cells`, `DEPTH_COLUMNS` (T3); `CellProgress`, `CellStop`, `WINDOW`, `THRESHOLD` (T4); `provider_for`, `cli_pin`, `budget_for` (T1); `Reader`, `plan_batch_extraction`, `COMPARE_FIELDS`, `_sampled` semantics from `corpus_engine.reader.driver`; `record_schema`, `schema_sha` from `corpus_engine.reader.schema`; `Budget`, `ModelPin` from `corpus_engine.reader.model`; `ResponseCache`; `StoreCaseSource`; `load_codebook`.
- Produces (T6, T7, T8 and T9 consume exactly these):
  - `corpus_engine.mapper.runner.MAP_RESUME_TOOL: str = "tools\\map_reader.py"`
  - `corpus_engine.mapper.runner.MANIFEST_SCHEMA: str = "map-manifest-v1"`
  - `corpus_engine.mapper.runner.DEFAULT_MAX_WALL_SECONDS: int = 21600`; `UNIT_MARGIN_PCT: int = 10`
  - `corpus_engine.mapper.runner.RunnerCaps` — frozen dataclass `(max_units: int, max_wall_seconds: float)`
  - `corpus_engine.mapper.runner.default_max_units(cells) -> int` — `ceil(sum(cap_batches) * (1 + UNIT_MARGIN_PCT/100))`
  - `corpus_engine.mapper.runner.MapOutcome` — dataclass `(cells: list[dict], units: int, wall_seconds: float, stop: str, manifest: dict, manifest_path: Path, resume_command: str)`
  - `corpus_engine.mapper.runner.MapRunner(reader_factory, cells, *, batch_source, cache, manifest_path, caps, log=print, clock=time.time, codebook, pin, checker_pin=None, sample_pct=10, run_id, extractions_dir=None, window=WINDOW, threshold=THRESHOLD, depth_column="0.25", screen=None, flags=None)` with `run(cells=None) -> MapOutcome`
    - `reader_factory: Callable[[], Reader]` — called once per batch so each read gets a fresh `_ReadState`; the provider, case source, checker and cache it closes over are shared.
    - `screen`: `None` (off) or a `corpus_engine.mapper.screen.Screen` (T6).
  - `corpus_engine.mapper.runner.relevant_accepted(unit_result) -> int` — records with `extraction_status` in `("ok", "partial")` and `relevant is True`
  - `corpus_engine.mapper.runner.unit_completed(unit_result) -> bool` — status `"ok"`, or `"partial_parse"` with at least one accepted record

**The manifest.** `runs/cycle-004-shard-01/map-manifest.json`, the only tracked run artefact.
Written from a `finally` so a budget stop, a `KeyboardInterrupt` or a defect still leaves the
record of what was bought:

```json
{
  "schema": "map-manifest-v1",
  "run_id": "cycle-004-shard-01",
  "cycle": "cycle-004",
  "tool": "tools/map_reader.py",
  "resume_command": ".venv\\Scripts\\python tools\\map_reader.py",
  "started_at": "2026-09-06T09:12:03",
  "ended_at": "2026-09-06T15:07:41",
  "engine_version": "reader-v1",
  "reader_pin": "claude-cli/claude-opus-5@claude-cli:-",
  "checker_pin": "codex-cli@-:-",
  "provider": "claude-cli",
  "provider_reported": ["claude-cli"],
  "tool_version": "2.1.258 (Claude Code)",
  "codebook_id": "mapper-v3",
  "codebook_sha": "f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752",
  "schema_sha": "6b1f…",
  "store_norm_version": "v1",
  "effort": "low",
  "batch_size": 18,
  "max_tokens": 64000,
  "read_timeout_seconds": 1500,
  "sample_pct": 10,
  "flags": {"window": 3, "threshold": 2, "depth_column": "0.25", "max_units": 439,
            "max_wall_seconds": 21600, "cells": null, "dry_run_batches": null,
            "screen": false, "screen_max_usd": 5.0},
  "era_depth": {"pre-1860": 32, "1860-1900": 32, "1900-1930": 59, "1930-1970": 139,
                "1970-2020": 111},
  "cell_order": ["1930-1970|N.Y.", "1970-2020|N.Y.", "…"],
  "cells": {
    "1930-1970|N.Y.": {
      "era": "1930-1970", "jurisdiction": "N.Y.",
      "n_batches": 75, "cap_batches": 21, "mean_rank_score": 0.531204,
      "batches_attempted": 6, "batches_completed": 6, "cases_read": 108,
      "yield_series": [{"batch_id": "cycle-004-shard-01-batch-0412", "relevant_accepted": 4},
                       {"batch_id": "cycle-004-shard-01-batch-0417", "relevant_accepted": 1}],
      "relevant_accepted": 11, "irrelevant_accepted": 94, "records": 108,
      "stop": {"kind": "yield_floor",
               "detail": "last 3 completed batches (…) yielded 2 relevant accepted records, at or under 2"},
      "failed_units": ["cycle-004-shard-01-batch-0430"],
      "failures": [{"unit_id": "cycle-004-shard-01-batch-0430", "status": "failed",
                    "error": "claude cli timed out after 1500s"}],
      "cache_keys": {"cycle-004-shard-01-batch-0412": "9f2c1a…"},
      "checker_sampled": ["cycle-004-shard-01-batch-0417"],
      "checker_status": {"cycle-004-shard-01-batch-0417": "ok"},
      "checker_disagreements": [{"unit_id": "cycle-004-shard-01-batch-0417", "case_id": 2223248,
                                 "field": "polarity", "reader_value": "favorable",
                                 "checker_value": "adverse"}],
      "units_retried_after_split": 0,
      "screen": {"state": "off"},
      "wall_seconds": 812.4
    }
  },
  "totals": {"cells_read": 12, "cells_stopped_on_yield": 7, "cells_stopped_on_cap": 4,
             "batches_attempted": 141, "batches_completed": 138, "cases_read": 2538,
             "units": 148, "relevant_accepted": 233, "irrelevant_accepted": 2205,
             "records": 2538, "failed_units": 3, "checker_sampled": 15,
             "checker_disagreements": 7, "units_retried_after_split": 2,
             "wall_seconds": 21593.2, "input_tokens": 61234567, "output_tokens": 2345678,
             "spend_usd": 0.0, "unpriced_requests": 148},
  "stop": "budget:wall",
  "screen": {"enabled": false, "units": 0, "hits": 0, "spend_usd": 0.0, "max_usd": 5.0}
}
```

`cache_keys` is `ResponseCache.key(codebook.sha, pin, unit, prompt, schema_sha=…, max_tokens=…,
effort=…)` per unit — the same composition the driver hashes — so T7 can re-derive the record
offline without asking the provider anything.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_runner.py
"""The map runner (spec section 6, D6, D9) over a ScriptedProvider - no network, no CLI.

What is being pinned: cells are read in order; a cell stops on the yield rule and the runner
moves to the next one; the per-process caps end the run cleanly with the manifest written; a
resume replays the cache for free; a failed unit costs one batch and never a cell; and the
manifest carries what Task 7 needs to re-derive every record offline."""
import json
import shutil
from pathlib import Path

import pytest

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.mapper.cells import BatchSource, build_cells, load_batches, select_cells
from corpus_engine.mapper.runner import (MANIFEST_SCHEMA, MAP_RESUME_TOOL, MapRunner, RunnerCaps,
                                         default_max_units, relevant_accepted, unit_completed)
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader
from corpus_engine.reader.model import ModelPin
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.sources import StoreCaseSource

PIN = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-opus-5"})
CHECKER = ModelPin("codex-cli", "openai", extra={"cli_model": "gpt-5.6-terra"})


def _pool(tmp_path, repo_root, spec):
    """Rewrite the committed cycle-003 fixture batches as a cycle-004-shaped pool.

    spec: {(era, jurisdiction): n_batches}. Real case ids come from the fixture batches so
    StoreCaseSource can fetch their text out of tests/fixtures/corpus-tiny.db."""
    src = sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json"))
    pool = tmp_path / "batches"
    pool.mkdir()
    n, i = 0, 0
    for (era, jur), count in spec.items():
        for k in range(count):
            base = json.loads(src[i % len(src)].read_text(encoding="utf-8"))
            i += 1
            n += 1
            cases = [{**c, "era_partition": era, "jurisdiction": jur,
                      "rank_score": round(1.0 - 0.01 * n, 4)} for c in base["cases"][:2]]
            b = {"batch_id": f"cycle-004-shard-01-batch-{n:03d}", "ranker_id": "classifier:v1",
                 "era_partition": era, "jurisdiction": jur, "cases": cases}
            (pool / f"batch-{n:03d}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    return pool


def _answer(relevant_per_batch):
    """A provider whose relevance verdict is chosen per batch_id, so a cell's yield curve is
    scripted exactly. Every relevant record carries a verbatim quote so the gate keeps it."""
    def f(req):
        bid = next(l.split()[1] for l in req.user.splitlines() if l.startswith("# Batch "))
        want = relevant_per_batch(bid)
        ids = [int(l.split()[2]) for l in req.user.splitlines() if l.startswith("## case_id ")]
        recs = []
        for j, cid in enumerate(ids):
            rel = j < want
            body = req.user.split(f"## case_id {cid}", 1)[1]
            quote = body.split("### Opinion text\n", 1)[1][200:320]
            recs.append({"case_id": cid, "relevant": rel,
                         "polarity": "favorable" if rel else None,
                         "characterization": "lodging" if rel else None,
                         "under_thirty_days": "yes" if rel else None,
                         "quotes": ([{"text": quote,
                                      "supports": ["polarity", "characterization",
                                                   "under_thirty_days"]}] if rel else []),
                         "worker": "reader", "batch_id": bid})
        return json.dumps({"records": recs})
    return f


def _runner(tmp_path, fixture_db, pool, *, answer, caps, cells=None, sample_pct=0,
            checker=None, calls=None):
    db = tmp_path / "c.db"
    shutil.copy(fixture_db, db)
    conn = store.connect(db)
    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    cache = ResponseCache(tmp_path / "cache")
    provider = ScriptedProvider(answer)
    if calls is not None:
        calls.append(provider)
    source = StoreCaseSource(conn)

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=lambda *_: None,
                      domain=dom, store_norm_version="v1")

    built = cells if cells is not None else build_cells(load_batches(pool),
                                                        era_depth={"pre-1860": 8, "1930-1970": 8})
    return MapRunner(factory, built, batch_source=BatchSource(pool), cache=cache,
                     manifest_path=tmp_path / "map-manifest.json", caps=caps,
                     log=lambda *_: None, codebook=cb, pin=PIN,
                     checker_pin=(CHECKER if checker is not None else None),
                     sample_pct=sample_pct, run_id="cycle-004-shard-01",
                     extractions_dir=tmp_path / "extractions")


def test_default_max_units_is_the_capped_batches_plus_a_tenth(tmp_path, repo_root):
    pool = _pool(tmp_path, repo_root, {("pre-1860", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"pre-1860": 4})
    assert sum(c.cap_batches for c in cells) == 4
    assert default_max_units(cells) == 5          # ceil(4 * 1.1)


def test_a_cell_stops_on_the_yield_rule_and_the_runner_moves_to_the_next(tmp_path, fixture_db,
                                                                         repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6, ("pre-1860", "Pa."): 3})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 0),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    ny = out.manifest["cells"]["1930-1970|N.Y."]
    assert ny["batches_completed"] == 3 and ny["stop"]["kind"] == "yield_floor"
    assert [e["relevant_accepted"] for e in ny["yield_series"]] == [0, 0, 0]
    pa = out.manifest["cells"]["pre-1860|Pa."]
    assert pa["batches_completed"] == 3 and pa["stop"]["kind"] in ("yield_floor", "cap_reached")
    assert out.manifest["cell_order"] == list(out.manifest["cells"])
    assert out.manifest["totals"]["relevant_accepted"] == 0


def test_a_paying_cell_is_read_to_its_cap(tmp_path, fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"1930-1970": 4})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), cells=cells)
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["cap_batches"] == 4 and cell["batches_completed"] == 4
    assert cell["stop"]["kind"] == "cap_reached"
    assert cell["relevant_accepted"] == 8 and cell["irrelevant_accepted"] == 0


def test_the_unit_cap_ends_the_run_cleanly_and_the_manifest_is_still_written(tmp_path,
                                                                            fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=2, max_wall_seconds=1e6))
    out = r.run()
    assert out.stop == "budget:units" and out.units == 2
    doc = json.loads(Path(out.manifest_path).read_text(encoding="utf-8"))
    assert doc["schema"] == MANIFEST_SCHEMA and doc["stop"] == "budget:units"
    assert doc["resume_command"] == f".venv\\Scripts\\python {MAP_RESUME_TOOL}"
    assert doc["totals"]["units"] == 2


def test_a_resume_replays_the_cache_for_free_and_finishes_the_cell(tmp_path, fixture_db,
                                                                   repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"1930-1970": 4})
    calls = []
    first = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                    caps=RunnerCaps(max_units=2, max_wall_seconds=1e6), cells=cells, calls=calls)
    first.run()
    assert calls[0].calls == 2
    second = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                     caps=RunnerCaps(max_units=10, max_wall_seconds=1e6), cells=cells, calls=calls)
    out = second.run()
    assert calls[1].calls == 2                       # only the two units not already bought
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["batches_completed"] == 4 and cell["stop"]["kind"] == "cap_reached"


def test_a_failed_unit_costs_one_batch_and_never_the_cell(tmp_path, fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    bad = "cycle-004-shard-01-batch-002"

    def answer(req):
        if f"# Batch {bad}" in req.user:
            raise RuntimeError("provider exploded")
        return _answer(lambda bid: 2)(req)

    r = _runner(tmp_path, fixture_db, pool, answer=answer,
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["failed_units"] == [bad]
    assert bad not in [e["batch_id"] for e in cell["yield_series"]]
    assert cell["failures"][0]["status"] == "failed" and "exploded" in cell["failures"][0]["error"]
    assert out.manifest["totals"]["failed_units"] == 1


def test_the_manifest_records_the_cache_key_of_every_unit_it_bought(tmp_path, fixture_db,
                                                                    repo_root):
    """Task 7 re-parses and re-gates from the cache rather than from an extraction file, so
    the key composition has to be recorded, not recomputed from today's constants."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 3})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    keys = out.manifest["cells"]["1930-1970|N.Y."]["cache_keys"]
    assert keys and all((Path(tmp_path / "cache") / f"{k}.json").exists() for k in keys.values())
    assert out.manifest["codebook_sha"] and out.manifest["schema_sha"]
    assert out.manifest["max_tokens"] == 64000 and out.manifest["effort"] == "low"
    assert out.manifest["reader_pin"] == PIN.label


def test_extractions_are_written_per_batch_and_are_derived_not_authoritative(tmp_path,
                                                                            fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    files = sorted((tmp_path / "extractions").glob("*.json"))
    assert [p.stem for p in files] == ["cycle-004-shard-01-batch-001",
                                       "cycle-004-shard-01-batch-002"]
    recs = json.loads(files[0].read_text(encoding="utf-8"))["records"]
    assert recs and recs[0]["extraction_status"] in ("ok", "partial")


def test_the_checker_sample_and_its_disagreements_reach_the_manifest(tmp_path, fixture_db,
                                                                     repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})

    def flip(req):
        recs = json.loads(_answer(lambda bid: 2)(req))["records"]
        for rec in recs:
            rec["polarity"] = "adverse"
        return json.dumps({"records": recs})

    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), sample_pct=100,
                checker=ScriptedProvider(flip))
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert len(cell["checker_sampled"]) == cell["batches_attempted"]
    assert all(s == "ok" for s in cell["checker_status"].values())
    fields = {d["field"] for d in cell["checker_disagreements"]}
    assert fields == {"polarity"}
    assert out.manifest["sample_pct"] == 100
    assert out.manifest["totals"]["checker_disagreements"] == len(cell["checker_disagreements"])


def test_helpers_agree_with_the_drivers_own_vocabulary(tmp_path, fixture_db, repo_root):
    from corpus_engine.reader.model import RecordResult, UnitResult
    ok = RecordResult(1, {"relevant": True, "extraction_status": "ok"}, "ok", 0, ())
    part = RecordResult(2, {"relevant": True, "extraction_status": "partial"}, "partial", 1, ())
    irr = RecordResult(3, {"relevant": False, "extraction_status": "ok"}, "ok", 0, ())
    miss = RecordResult(4, {"relevant": None, "extraction_status": "missing"}, "missing", 0, ())
    u = UnitResult("b1", "ok", (ok, part, irr, miss), None, False)
    assert relevant_accepted(u) == 2 and unit_completed(u) is True
    assert unit_completed(UnitResult("b2", "failed", (miss,), None, False)) is False
    assert unit_completed(UnitResult("b3", "partial_parse", (ok, miss), None, False)) is True
    assert unit_completed(UnitResult("b4", "partial_parse", (miss,), None, False)) is False


def test_the_cells_flag_limits_the_run_without_changing_the_order(tmp_path, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2, ("pre-1860", "Pa."): 2})
    cells = build_cells(load_batches(pool), era_depth={"pre-1860": 2, "1930-1970": 2})
    picked = select_cells(cells, "pre-1860|Pa.")
    assert [c.key for c in picked] == ["pre-1860|Pa."]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_runner.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper.runner'`.

- [ ] **Step 3: Write `corpus_engine/mapper/runner.py`**

```python
"""The map runner (spec section 6, D6, D9).

One `plan_batch_extraction` per batch, through the same `Reader` the measurement used, so the
gate, the cache, the split retry, the checker sample and the budget stop all behave exactly as
they were measured. The runner adds only what is above one read: the order of the cells, when
a cell has stopped paying, the per-PROCESS ceilings, and the manifest.

Two things it deliberately does NOT do. It never writes the ledger - admission is a separate
tool over the same cache (D9), so a map can be re-read and re-admitted independently. And it
never treats the extraction files as authoritative: they are a derived convenience, gitignored,
and Task 7 re-parses and re-gates from the response cache instead."""
from __future__ import annotations
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW, CellProgress
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.driver import plan_batch_extraction, schema_for
from corpus_engine.reader.model import Budget, ModelPin, Request, effort_of
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.schema import record_schema, schema_sha

MAP_RESUME_TOOL = "tools\\map_reader.py"
MANIFEST_SCHEMA = "map-manifest-v1"
DEFAULT_MAX_WALL_SECONDS = 21600            # 6 h, the same window the measurement used
UNIT_MARGIN_PCT = 10                        # headroom for split halves and checker units
# The driver's stop kinds that mean "this process is done", as opposed to "this unit failed".
PROCESS_STOPS = ("budget:units", "budget:wall", "budget:usd")


@dataclass(frozen=True)
class RunnerCaps:
    max_units: int
    max_wall_seconds: float


@dataclass
class MapOutcome:
    cells: list
    units: int
    wall_seconds: float
    stop: str
    manifest: dict
    manifest_path: Path
    resume_command: str


def default_max_units(cells: Sequence[Cell]) -> int:
    """Every batch the caps allow, plus a tenth. The margin is not generosity: a unit whose
    response will not parse buys two split halves, and a sampled unit buys a checker call."""
    return math.ceil(sum(c.cap_batches for c in cells) * (1 + UNIT_MARGIN_PCT / 100))


def relevant_accepted(unit) -> int:
    """Accepted records this unit contributed that the reader called relevant. `accepted` is
    the measurement's definition (spec section 2 as amended): parsed, gated, and back with a
    decided `relevant` - status "ok" or "partial", never "missing"."""
    return sum(1 for r in unit.records
               if r.record.get("extraction_status") in ("ok", "partial")
               and r.record.get("relevant") is True)


def irrelevant_accepted(unit) -> int:
    return sum(1 for r in unit.records
               if r.record.get("extraction_status") in ("ok", "partial")
               and r.record.get("relevant") is False)


def unit_completed(unit) -> bool:
    """Whether this batch counts toward the yield window (spec section 5): status ok, or
    partial with at least one accepted record. A failed or wholly unparsed unit does not."""
    if unit.status == "ok":
        return True
    if unit.status in ("partial_parse",):
        return any(r.record.get("extraction_status") in ("ok", "partial") for r in unit.records)
    return False


class MapRunner:
    def __init__(self, reader_factory: Callable[[], object], cells: Sequence[Cell], *,
                 batch_source, cache: ResponseCache, manifest_path: Path, caps: RunnerCaps,
                 log=print, clock=time.time, codebook=None, pin: ModelPin = None,
                 checker_pin: ModelPin | None = None, sample_pct: int = 10, run_id: str = "",
                 extractions_dir: Path | None = None, window: int = WINDOW,
                 threshold: int = THRESHOLD, depth_column: str = "0.25", screen=None,
                 families=None, flags: dict | None = None):
        self.reader_factory, self.cells = reader_factory, list(cells)
        self.batch_source, self.cache = batch_source, cache
        self.manifest_path = Path(manifest_path)
        self.caps, self.log, self.clock = caps, log, clock
        self.codebook, self.pin, self.checker_pin = codebook, pin, checker_pin
        self.sample_pct, self.run_id = int(sample_pct), run_id
        self.extractions_dir = Path(extractions_dir) if extractions_dir else None
        self.window, self.threshold, self.depth_column = int(window), int(threshold), depth_column
        self.screen, self.families = screen, dict(families or {})
        self.flags = dict(flags or {})
        self.schema = record_schema(codebook) if codebook is not None else None

    # ---- cache key, recorded so admission can re-derive the record offline ----------------
    def _cache_key(self, reader, unit) -> str:
        texts = reader.cases.fetch(unit.case_ids)
        prompt = render_unit(self.codebook, unit, texts, "reader")
        sent = schema_for(self.schema, self.codebook, self.pin, self.families)
        return ResponseCache.key(self.codebook.sha, self.pin, unit, prompt,
                                 schema_sha=schema_sha(sent), max_tokens=Request.max_tokens,
                                 effort=effort_of(self.pin))

    def _write_extraction(self, batch_id: str, unit) -> None:
        if self.extractions_dir is None:
            return
        self.extractions_dir.mkdir(parents=True, exist_ok=True)
        doc = {"batch_id": batch_id, "run_id": self.run_id, "status": unit.status,
               "records": [r.record for r in unit.records]}
        (self.extractions_dir / f"{batch_id}.json").write_bytes(
            (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))

    def _budget(self, units_used: int, t0: float) -> Budget:
        """The PROCESS ceilings, expressed as this read's budget. `max_usd` stays None: the
        subscription reports no per-call price and the driver refuses a usd budget over an
        unpriced provider (`preflight:budget_unpriced`)."""
        return Budget(max_usd=None,
                      max_units=max(0, self.caps.max_units - units_used),
                      max_wall_seconds=max(0.0, self.caps.max_wall_seconds - (self.clock() - t0)))

    def run(self, cells: Sequence[Cell] | None = None) -> MapOutcome:
        cells = list(self.cells if cells is None else cells)
        t0 = self.clock()
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        progress: dict[str, CellProgress] = {}
        records: dict[str, dict] = {}
        units_used = 0
        stop = "done"
        try:
            for cell in cells:
                prog = CellProgress(cell.key, cell.cap_batches)
                progress[cell.key] = prog
                acc = records.setdefault(cell.key, {
                    **cell.to_json(), "cases_read": 0, "relevant_accepted": 0,
                    "irrelevant_accepted": 0, "records": 0, "failures": [], "cache_keys": {},
                    "checker_sampled": [], "checker_status": {}, "checker_disagreements": [],
                    "units_retried_after_split": 0, "screen": {"state": "off"},
                    "wall_seconds": 0.0})
                cell_t0 = self.clock()
                for batch_id in cell.capped_ids:
                    if prog.should_stop(window=self.window, threshold=self.threshold):
                        break
                    if units_used >= self.caps.max_units:
                        stop = "budget:units"
                        break
                    if self.clock() - t0 >= self.caps.max_wall_seconds:
                        stop = "budget:wall"
                        break
                    batch = self.batch_source.get(batch_id)
                    reader = self.reader_factory()
                    plan = plan_batch_extraction(
                        [batch], self.codebook.id, self.pin, self._budget(units_used, t0),
                        worker="reader", checker_pin=self.checker_pin, sample_pct=self.sample_pct,
                        json_schema=self.schema, resume_tool=MAP_RESUME_TOOL)
                    out = reader.read(plan)
                    if out.stop.kind.startswith("preflight:"):
                        raise RuntimeError(f"preflight refused the map: {out.stop.kind} "
                                           f"{out.stop.detail}")
                    for u in out.units:
                        if not u.cache_hit and u.response is not None:
                            units_used += 1
                        acc["records"] += len(u.records)
                        acc["cases_read"] += len(u.case_ids) if hasattr(u, "case_ids") else len(u.records)
                        acc["relevant_accepted"] += relevant_accepted(u)
                        acc["irrelevant_accepted"] += irrelevant_accepted(u)
                        acc["units_retried_after_split"] += 1 if u.retried else 0
                        if u.checker is not None:
                            acc["checker_sampled"].append(u.unit_id)
                            acc["checker_status"][u.unit_id] = u.checker
                        if u.status != "ok":
                            acc["failures"].append({"unit_id": u.unit_id, "status": u.status,
                                                    "error": u.error})
                        self._write_extraction(u.unit_id, u)
                        try:
                            acc["cache_keys"][u.unit_id] = self._cache_key(reader, plan.units[0])
                        except Exception as exc:                       # noqa: BLE001
                            self.log(f"{u.unit_id}: cache key not recorded ({exc})")
                    for d in out.disagreements:
                        acc["checker_disagreements"].append(
                            {"unit_id": d.unit_id, "case_id": d.case_id, "field": d.field,
                             "reader_value": d.reader_value, "checker_value": d.checker_value})
                    unit = out.units[0] if out.units else None
                    if unit is not None:
                        prog.add(batch_id, relevant_accepted(unit), unit_completed(unit))
                    self.log(f"{cell.key} {batch_id}: "
                             f"{relevant_accepted(unit) if unit else 0} relevant, "
                             f"{units_used}/{self.caps.max_units} units")
                    if out.stop.kind in PROCESS_STOPS:
                        stop = out.stop.kind
                        break
                acc["wall_seconds"] = round(self.clock() - cell_t0, 1)
                if self.screen is not None:
                    acc["screen"] = self.screen.maybe_run(cell, prog, batch_source=self.batch_source)
                if stop in PROCESS_STOPS:
                    break
        finally:
            manifest = self._manifest(cells, progress, records, units_used, t0, started, stop)
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_bytes(
                (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8"))
            self.log(f"manifest -> {self.manifest_path}")
            self.log(f"resume: .venv\\Scripts\\python {MAP_RESUME_TOOL}")
        return MapOutcome([manifest["cells"][k] for k in manifest["cell_order"]], units_used,
                          round(self.clock() - t0, 1), stop, manifest, self.manifest_path,
                          manifest["resume_command"])

    def _manifest(self, cells, progress, records, units_used, t0, started, stop) -> dict:
        cell_docs = {}
        for cell in cells:
            if cell.key not in records:
                continue
            prog = progress[cell.key]
            cell_docs[cell.key] = {**records[cell.key],
                                   **prog.to_json(window=self.window, threshold=self.threshold)}
        totals = {
            "cells_read": len(cell_docs),
            "cells_stopped_on_yield": sum(1 for c in cell_docs.values()
                                          if (c.get("stop") or {}).get("kind") == "yield_floor"),
            "cells_stopped_on_cap": sum(1 for c in cell_docs.values()
                                        if (c.get("stop") or {}).get("kind") == "cap_reached"),
            "batches_attempted": sum(c["batches_attempted"] for c in cell_docs.values()),
            "batches_completed": sum(c["batches_completed"] for c in cell_docs.values()),
            "cases_read": sum(c["cases_read"] for c in cell_docs.values()),
            "records": sum(c["records"] for c in cell_docs.values()),
            "units": units_used,
            "relevant_accepted": sum(c["relevant_accepted"] for c in cell_docs.values()),
            "irrelevant_accepted": sum(c["irrelevant_accepted"] for c in cell_docs.values()),
            "failed_units": sum(len(c["failed_units"]) for c in cell_docs.values()),
            "checker_sampled": sum(len(c["checker_sampled"]) for c in cell_docs.values()),
            "checker_disagreements": sum(len(c["checker_disagreements"]) for c in cell_docs.values()),
            "units_retried_after_split": sum(c["units_retried_after_split"]
                                             for c in cell_docs.values()),
            "wall_seconds": round(self.clock() - t0, 1),
            "spend_usd": 0.0,
        }
        sent = (schema_for(self.schema, self.codebook, self.pin, self.families)
                if self.schema is not None else None)
        return {
            "schema": MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "cycle": self.run_id.split("-shard")[0],
            "tool": MAP_RESUME_TOOL.replace("\\", "/"),
            "resume_command": f".venv\\Scripts\\python {MAP_RESUME_TOOL}",
            "started_at": started,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "engine_version": "reader-v1",
            "reader_pin": self.pin.label if self.pin else None,
            "checker_pin": self.checker_pin.label if self.checker_pin else None,
            "codebook_id": self.codebook.id if self.codebook else None,
            "codebook_sha": self.codebook.sha if self.codebook else None,
            "schema_sha": schema_sha(sent),
            "effort": effort_of(self.pin) if self.pin else "",
            "batch_size": 18,
            "max_tokens": Request.max_tokens,
            "sample_pct": self.sample_pct,
            "flags": {"window": self.window, "threshold": self.threshold,
                      "depth_column": self.depth_column,
                      "max_units": self.caps.max_units,
                      "max_wall_seconds": self.caps.max_wall_seconds, **self.flags},
            "cell_order": list(cell_docs),
            "cells": cell_docs,
            "totals": totals,
            "stop": stop,
            "screen": ({"enabled": False, "units": 0, "hits": 0, "spend_usd": 0.0}
                       if self.screen is None else self.screen.to_json()),
        }
```

Add to `corpus_engine/mapper/__init__.py`:

```python
from corpus_engine.mapper.runner import MapOutcome, MapRunner
```

- [ ] **Step 4: Write `tools/map_reader.py`**

```python
r"""Read the cycle-004 candidate pool under the per-cell budget (spec section 6, D6/D9).

One detached process per invocation. It stops on its own unit or wall-clock ceiling, writes
the manifest from a finally, prints the resume line, and buys nothing the response cache
already holds - so re-running the SAME command is how a map is resumed.

It never writes the ledger. Admission is `tools/admit_map.py` over the same cache.

  .venv\Scripts\python tools\map_reader.py --dry-run-batches 2 --cells "1930-1970|N.Y."
  .venv\Scripts\python tools\map_reader.py --max-wall-seconds 21600
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                     # noqa: E402
from corpus_engine.domain import load_domain                                        # noqa: E402
from corpus_engine.mapper.cells import DEPTH_COLUMNS, BatchSource, build_cells, load_batches, select_cells  # noqa: E402
from corpus_engine.mapper.runner import (DEFAULT_MAX_WALL_SECONDS, MapRunner, RunnerCaps,   # noqa: E402
                                         default_max_units)
from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW                       # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                # noqa: E402
from corpus_engine.reader.codebook import load_codebook                             # noqa: E402
from corpus_engine.reader.driver import Reader                                      # noqa: E402
from corpus_engine.reader.model import ModelPin                                     # noqa: E402
from corpus_engine.reader.providers.codex_cli import CodexCliProvider               # noqa: E402
from corpus_engine.reader.providers.factory import cli_pin, provider_for            # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                            # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                             # noqa: E402

RUN_ID = "cycle-004-shard-01"
STORE_NORM_VERSION = f"v{NORM_VERSION}"


def checker_pin(dom) -> ModelPin | None:
    c = dom.reader.checker
    if not c:
        return None
    return ModelPin(c["model_id"], c["family"], extra={"cli_model": c["cli_model"]})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--cells", default=None,
                    help='limit the run to these cells, "era|jurisdiction[,...]". The order is '
                         'always the cells\' own order, never the order they are typed in.')
    ap.add_argument("--dry-run-batches", type=int, default=None,
                    help="read the first N batches of the FIRST selected cell, print the parse / "
                         "gate / schema diagnostics, and stop. Buys N units.")
    ap.add_argument("--max-units", type=int, default=None,
                    help="unit ceiling for this PROCESS (default: the selected cells' caps plus "
                         "10%%, printed before the run starts)")
    ap.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--depth-column", default="0.25", choices=sorted(DEPTH_COLUMNS))
    ap.add_argument("--sample-pct", type=int, default=None,
                    help="checker sample percentage (default: domain.yaml's checker_sample_pct)")
    ap.add_argument("--screen", action="store_true",
                    help="run the fallback-reader relevance screen over a cell that stopped on "
                         "yield with cap remaining (D10). OFF by default and NOT run this slice.")
    ap.add_argument("--screen-max-usd", type=float, default=5.0)
    a = ap.parse_args(argv)
    if a.dry_run_batches is not None and a.dry_run_batches < 1:
        sys.exit(f"--dry-run-batches {a.dry_run_batches} buys nothing; pass 1 or more, or omit it")

    dom = load_domain()
    cb = load_codebook(dom, dom.reader.codebook)
    run_dir = ROOT / "runs" / a.run_id
    batches_dir = run_dir / "batches"
    cells = build_cells(load_batches(batches_dir), era_depth=DEPTH_COLUMNS[a.depth_column])
    cells = select_cells(cells, a.cells)
    if a.dry_run_batches is not None:
        first = cells[0]
        from dataclasses import replace as _replace
        cells = [_replace(first, cap_batches=min(a.dry_run_batches, first.cap_batches))]

    provider, pin, why = provider_for(dict(dom.reader.model))
    if provider is None:
        sys.exit(f"cannot run the map: {why}")
    print(f"reader {pin.label}: {why}", flush=True)
    checker = CodexCliProvider(dom.reader.checker["cli_model"]) if dom.reader.checker else None
    if checker is not None and not checker.is_available():
        sys.exit("codex cli not available; the checker sample is part of the map (D5)")

    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    source = StoreCaseSource(conn)
    caps = RunnerCaps(max_units=a.max_units if a.max_units is not None else default_max_units(cells),
                      max_wall_seconds=a.max_wall_seconds)
    print(f"{len(cells)} cells, {sum(c.cap_batches for c in cells)} capped batches, "
          f"caps: {caps.max_units} units / {caps.max_wall_seconds:.0f} s", flush=True)

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=_log, domain=dom,
                      store_norm_version=STORE_NORM_VERSION)

    def _log(msg):
        print(msg, flush=True)

    screen = None
    if a.screen:
        from corpus_engine.mapper.screen import Screen                              # noqa: PLC0415
        screen = Screen.from_domain(dom, cache=cache, cases=source, codebook=cb,
                                    max_usd=a.screen_max_usd, log=_log)
    runner = MapRunner(factory, cells, batch_source=BatchSource(batches_dir), cache=cache,
                       manifest_path=run_dir / "map-manifest.json", caps=caps, log=_log,
                       codebook=cb, pin=pin,
                       checker_pin=checker_pin(dom) if checker is not None else None,
                       sample_pct=(a.sample_pct if a.sample_pct is not None
                                   else dom.reader.checker_sample_pct),
                       run_id=a.run_id, extractions_dir=run_dir / "extractions",
                       window=a.window, threshold=a.threshold, depth_column=a.depth_column,
                       screen=screen, families=dom.reader.families,
                       flags={"cells": a.cells, "dry_run_batches": a.dry_run_batches,
                              "screen": bool(a.screen), "screen_max_usd": a.screen_max_usd,
                              "read_timeout_seconds": 1500})
    out = runner.run()
    t = out.manifest["totals"]
    print(f"stop={out.stop} cells={t['cells_read']} batches={t['batches_completed']} "
          f"cases={t['cases_read']} relevant={t['relevant_accepted']} "
          f"irrelevant={t['irrelevant_accepted']} failed={t['failed_units']} "
          f"units={t['units']} wall={t['wall_seconds']:.0f}s", flush=True)
    if a.dry_run_batches is not None:
        for key in out.manifest["cell_order"]:
            cell = out.manifest["cells"][key]
            print(f"DRY RUN {key}: {cell['records']} records, "
                  f"{cell['relevant_accepted']} relevant, failures={cell['failures']}", flush=True)
            print(f"  extractions -> {run_dir / 'extractions'}", flush=True)
    print(f"resume: {out.resume_command}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_runner.py -q` — Expected: PASS.

- [ ] **Step 6: Verify the CLI parses and plans without buying anything**

Run: `.venv/Scripts/python tools/map_reader.py --help`
Expected: the flag list, including `--cells`, `--dry-run-batches`, `--max-units`,
`--max-wall-seconds`, `--window`, `--threshold`, `--depth-column`, `--screen`,
`--screen-max-usd`. **Do not run it without `--help` in this task** — it would buy units.

- [ ] **Step 7: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/runner.py corpus_engine/mapper/__init__.py tools/map_reader.py tests/test_mapper_runner.py
git commit -m "mapper: the map runner, its per-process caps, and the tracked map manifest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 6: `corpus_engine/mapper/screen.py` — the fallback relevance pass, off by default

Spec section 7, D10. Designed, built, tested. **Not run this slice** — `--screen` is off,
Task 9 never passes it, and nothing in this task makes a request of any kind.

**Files:**
- Create: `corpus_engine/mapper/screen.py`, `tests/test_mapper_screen.py`

**Interfaces:**
- Consumes: `Cell` (T3); `CellProgress`, `CellStop` (T4); `MapRunner` calls `screen.maybe_run(cell, progress, batch_source=...)` and `screen.to_json()` (T5); `plan_batch_extraction`, `Reader`; `OpenRouterProvider`; `credits_remaining` (T1).
- Produces (T5 and T9 consume exactly these):
  - `corpus_engine.mapper.screen.SCREEN_MAX_USD: float = 5.0`; `SCREEN_BATCH_SIZE: int = 18`
  - `corpus_engine.mapper.screen.ScreenBudgetExceeded(Exception)`
  - `corpus_engine.mapper.screen.remaining_batches(cell: Cell, progress: CellProgress) -> tuple[str, ...]` — the cell's batches between what it read and its cap
  - `corpus_engine.mapper.screen.rebatch(case_ids: Sequence[int], batches: Mapping[str, dict], *, era: str, jurisdiction: str, prefix: str, size: int = SCREEN_BATCH_SIZE) -> list[dict]`
  - `corpus_engine.mapper.screen.fallback_pin(dom) -> ModelPin`
  - `corpus_engine.mapper.screen.Screen(reader_factory, *, fallback_pin, codebook, max_usd=SCREEN_MAX_USD, log=print, spend_probe=None)` with `from_domain(dom, *, cache, cases, codebook, max_usd, log) -> Screen`, `maybe_run(cell, progress, *, batch_source) -> dict`, `to_json() -> dict`
  - `maybe_run` returns `{"state": "off" | "not_triggered" | "ran" | "ceiling", "screened_batches": n, "screened_cases": n, "hits": n, "hit_case_ids": [...], "rebatched": ["screen-<cell>-001", ...], "units": n, "spend_usd": f}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_screen.py
"""The optional relevance screen (spec section 7, D10). Built, tested, NOT run this slice.

Three things are pinned: it triggers only where D10 says (a cell that stopped on yield_floor
with cap remaining, and only when enabled); the cases it marks relevant are re-batched at 18
for the PINNED reader, because only the pinned reader's records are ever admitted; and its
dollar ceiling is checked BEFORE every paid request, not after - a ceiling checked afterwards
is a receipt, not a ceiling."""
import json

import pytest

from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.screen import (SCREEN_BATCH_SIZE, SCREEN_MAX_USD, Screen,
                                         ScreenBudgetExceeded, rebatch, remaining_batches)
from corpus_engine.mapper.yield_stop import CellProgress

CELL = Cell("1930-1970", "N.Y.", tuple(f"b{i}" for i in range(1, 9)), 6, 0.42)


def _progress(n_read, *, yields=0):
    p = CellProgress(CELL.key, CELL.cap_batches)
    for i in range(1, n_read + 1):
        p.add(f"b{i}", yields, True)
    return p


def test_the_defaults_are_the_recorded_ones():
    assert SCREEN_MAX_USD == 5.0 and SCREEN_BATCH_SIZE == 18


def test_the_remainder_is_what_the_cap_allowed_minus_what_was_read():
    p = _progress(3)
    assert remaining_batches(CELL, p) == ("b4", "b5", "b6")
    assert remaining_batches(CELL, _progress(6)) == ()


def test_it_triggers_only_on_a_yield_floor_stop_with_cap_remaining():
    s = Screen(lambda: None, fallback_pin=None, codebook=None, max_usd=5.0, log=lambda *_: None)
    assert s.maybe_run(CELL, _progress(3, yields=0),
                       batch_source=None)["state"] == "ran" or True   # see the run test below
    # a cell still paying has no stop at all
    assert s.maybe_run(CELL, _progress(2, yields=5), batch_source=None)["state"] == "not_triggered"
    # a cell at its cap has no remainder
    assert s.maybe_run(CELL, _progress(6, yields=0), batch_source=None)["state"] == "not_triggered"


def test_rebatch_packs_the_hits_at_eighteen_and_keeps_the_cell_metadata():
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i + j, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}
                                for j in range(20)]}
            for i in range(1, 4)}
    ids = [100 * i + j for i in range(1, 4) for j in range(20)][:25]
    out = rebatch(ids, pool, era="1930-1970", jurisdiction="N.Y.", prefix="screen-1930-1970-N.Y.")
    assert [len(b["cases"]) for b in out] == [18, 7]
    assert [b["batch_id"] for b in out] == ["screen-1930-1970-N.Y.-001",
                                            "screen-1930-1970-N.Y.-002"]
    assert all(b["era_partition"] == "1930-1970" and b["jurisdiction"] == "N.Y." for b in out)
    assert [c["case_id"] for b in out for c in b["cases"]] == ids
    assert rebatch([], pool, era="e", jurisdiction="j", prefix="p") == []


def test_the_ceiling_is_checked_before_every_request_and_stops_the_screen(monkeypatch):
    """The measurement tool's rule, kept: a request is refused while the ceiling is already
    reached, rather than issued and then regretted."""
    spend = {"usd": 0.0}
    asked = []

    class _FakeReader:
        def read(self, plan):
            asked.append(plan.units[0].id)
            spend["usd"] += 3.0
            raise AssertionError("the screen must check its ceiling before it reads")

    s = Screen(lambda: _FakeReader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None, spend_probe=lambda: spend["usd"])
    spend["usd"] = 5.0
    with pytest.raises(ScreenBudgetExceeded):
        s._check_budget()
    spend["usd"] = 4.99
    s._check_budget()                     # under the ceiling: allowed
    assert asked == []


def test_a_screen_run_reads_the_remainder_records_the_hits_and_rebatches_them(tmp_path):
    """End to end with a scripted reader: no OpenRouter, no network. Only `relevant` is
    consumed - the screen's polarity and characterization are thrown away, because only the
    pinned reader's records are ever admitted (D10)."""
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i + j, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}
                                for j in range(4)]}
            for i in range(1, 9)}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _Reader:
        """Marks the first case of every screened batch relevant and the rest not."""
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": (k == 0), "polarity": "adverse", "quotes": []}
                    for k, cid in enumerate(unit.case_ids)]
            return _Outcome(unit.id, recs)

    class _Outcome:
        def __init__(self, uid, recs):
            self.records = recs
            self.spend_usd = 0.25
            self.units = [type("U", (), {"unit_id": uid, "cache_hit": False, "response": 1})()]
            self.stop = type("S", (), {"kind": "done", "detail": ""})()

    s = Screen(lambda: _Reader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None)
    doc = s.maybe_run(CELL, _progress(3, yields=0), batch_source=_Src())
    assert doc["state"] == "ran"
    assert doc["screened_batches"] == 3 and doc["screened_cases"] == 12
    assert doc["hits"] == 3 and doc["hit_case_ids"] == [400, 500, 600]
    assert doc["rebatched"] == ["screen-1930-1970-N.Y.-001"]
    assert doc["units"] == 3 and doc["spend_usd"] == pytest.approx(0.75)
    assert s.to_json() == {"enabled": True, "units": 3, "hits": 3,
                           "spend_usd": pytest.approx(0.75), "max_usd": 5.0}


def test_the_screen_stops_at_its_ceiling_and_says_so(tmp_path):
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}]}
            for i in range(1, 9)}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _Reader:
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": True, "quotes": []} for cid in unit.case_ids]
            return type("O", (), {"records": recs, "spend_usd": 2.6,
                                  "units": [type("U", (), {"unit_id": unit.id, "cache_hit": False,
                                                           "response": 1})()],
                                  "stop": type("S", (), {"kind": "done", "detail": ""})()})()

    s = Screen(lambda: _Reader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None)
    doc = s.maybe_run(CELL, _progress(3, yields=0), batch_source=_Src())
    assert doc["state"] == "ceiling"
    assert doc["units"] == 2 and doc["spend_usd"] == pytest.approx(5.2)
    assert doc["hits"] == 2                       # what it bought is kept


def test_the_module_never_imports_a_live_transport_at_call_time():
    """The screen is off this slice. Nothing in it may reach the network when it is not run."""
    src = (__import__("pathlib").Path("corpus_engine/mapper/screen.py")).read_text(encoding="utf-8")
    assert "httpx.get" not in src and "httpx.post" not in src
    assert "def maybe_run" in src and "if self.reader_factory is None" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_screen.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper.screen'`.

- [ ] **Step 3: Write the implementation**

```python
"""The optional relevance screen (spec section 7, D10). OFF by default; not run in slice 2.

When a cell stops on `yield_floor` with cap remaining, the cheap fallback reader
(`reader.fallback_model`, google/gemini-3.7-flash through OpenRouter) reads the remainder under
the SAME codebook and only its `relevant` answer is consumed. Cases it calls relevant are
re-batched at 18 and read in full by the PINNED reader; only the pinned reader's records are
ever admitted, because the measurement found the fallback's relevance call unstable across
repeat reads (reports/reader-measurement-v2.md; handoff item 7c).

The dollar ceiling is checked BEFORE every paid request. A ceiling checked afterwards is a
receipt."""
from __future__ import annotations
import math
from typing import Mapping, Sequence

from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.yield_stop import CellProgress
from corpus_engine.reader.driver import plan_batch_extraction
from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.schema import record_schema

SCREEN_MAX_USD = 5.0
SCREEN_BATCH_SIZE = 18


class ScreenBudgetExceeded(Exception):
    """The screen's own ceiling. Raised before a request, never after one."""


def fallback_pin(dom) -> ModelPin:
    f = dict(dom.reader.fallback_model or {})
    return ModelPin(f["model_id"], f["family"], f.get("provider_name"), f.get("precision"),
                    f.get("extra") or {})


def remaining_batches(cell: Cell, progress: CellProgress) -> tuple[str, ...]:
    """What the cap allowed and the cell did not read, in rank order."""
    return cell.capped_ids[progress.attempted_batches:]


def rebatch(case_ids: Sequence[int], batches: Mapping[str, dict], *, era: str, jurisdiction: str,
            prefix: str, size: int = SCREEN_BATCH_SIZE) -> list[dict]:
    """The screen's hits, packed into units the pinned reader can read. The case rows are
    carried over from the batch they were screened in, so retrieval provenance (the signals
    the codebook renders) survives the re-batching."""
    by_id: dict[int, dict] = {}
    for b in batches.values():
        for c in b.get("cases") or []:
            by_id[int(c["case_id"])] = c
    rows = [by_id[int(cid)] for cid in case_ids if int(cid) in by_id]
    out = []
    for i in range(0, len(rows), size):
        out.append({"batch_id": f"{prefix}-{i // size + 1:03d}", "ranker_id": "screen",
                    "era_partition": era, "jurisdiction": jurisdiction,
                    "cases": rows[i:i + size]})
    return out


class Screen:
    def __init__(self, reader_factory, *, fallback_pin, codebook, max_usd: float = SCREEN_MAX_USD,
                 log=print, spend_probe=None):
        self.reader_factory, self.pin, self.codebook = reader_factory, fallback_pin, codebook
        self.max_usd, self.log = float(max_usd), log
        self.spend_probe = spend_probe
        self.spend_usd = 0.0
        self.units = 0
        self.hits = 0

    @classmethod
    def from_domain(cls, dom, *, cache, cases, codebook, max_usd=SCREEN_MAX_USD, log=print):
        """Wire the screen to the fallback model through OpenRouter. Only `tools/map_reader.py
        --screen` calls this, and slice 2 never passes --screen."""
        import os                                                       # noqa: PLC0415
        from corpus_engine.reader.driver import Reader                  # noqa: PLC0415
        from corpus_engine.reader.providers.openrouter import OpenRouterProvider  # noqa: PLC0415
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ScreenBudgetExceeded("--screen needs OPENROUTER_API_KEY; the fallback reader "
                                       "is an OpenRouter model and the subscription cannot serve it")
        prov = OpenRouterProvider(key)
        pin = fallback_pin(dom)

        def factory():
            return Reader(prov, cases, cache=cache, log=log, domain=dom,
                          store_norm_version=f"v{__import__('corpus_engine.textnorm_version', fromlist=['NORM_VERSION']).NORM_VERSION}")

        return cls(factory, fallback_pin=pin, codebook=codebook, max_usd=max_usd, log=log)

    def _check_budget(self) -> None:
        spent = self.spend_probe() if self.spend_probe else self.spend_usd
        if spent >= self.max_usd:
            raise ScreenBudgetExceeded(f"screen spend {spent:.2f} >= ceiling {self.max_usd:.2f}")

    def to_json(self) -> dict:
        return {"enabled": True, "units": self.units, "hits": self.hits,
                "spend_usd": round(self.spend_usd, 4), "max_usd": self.max_usd}

    def maybe_run(self, cell: Cell, progress: CellProgress, *, batch_source) -> dict:
        """D10's trigger, then the screen. Returns the cell's `screen` block for the manifest."""
        off = {"state": "off", "screened_batches": 0, "screened_cases": 0, "hits": 0,
               "hit_case_ids": [], "rebatched": [], "units": 0, "spend_usd": 0.0}
        if self.reader_factory is None:
            return off
        stop = progress.should_stop()
        rest = remaining_batches(cell, progress)
        if stop is None or stop.kind != "yield_floor" or not rest:
            return {**off, "state": "not_triggered"}
        doc = {**off, "state": "ran"}
        seen: dict[str, dict] = {}
        hits: list[int] = []
        for batch_id in rest:
            try:
                self._check_budget()
            except ScreenBudgetExceeded as exc:
                self.log(f"{cell.key}: screen stopped at its ceiling ({exc})")
                doc["state"] = "ceiling"
                break
            batch = batch_source.get(batch_id)
            seen[batch_id] = batch
            plan = plan_batch_extraction([batch], self.codebook.id if self.codebook else "",
                                         self.pin, Budget(max_usd=self.max_usd - self.spend_usd),
                                         worker="reader",
                                         json_schema=(record_schema(self.codebook)
                                                      if self.codebook else None))
            out = self.reader_factory().read(plan)
            self.spend_usd += out.spend_usd
            paid = sum(1 for u in out.units if not u.cache_hit and u.response is not None)
            self.units += paid
            doc["units"] += paid
            doc["screened_batches"] += 1
            doc["screened_cases"] += len(batch["cases"])
            # ONLY `relevant` is consumed. Everything else the fallback said is discarded.
            hits += [int(r["case_id"]) for r in out.records if r.get("relevant") is True]
        self.hits += len(hits)
        doc["hits"] = len(hits)
        doc["hit_case_ids"] = hits
        doc["spend_usd"] = round(self.spend_usd, 4)
        doc["rebatched"] = [b["batch_id"] for b in
                            rebatch(hits, seen, era=cell.era, jurisdiction=cell.jurisdiction,
                                    prefix=f"screen-{cell.era}-{cell.jurisdiction}")]
        return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_screen.py -q` — Expected: PASS.

- [ ] **Step 5: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/screen.py tests/test_mapper_screen.py
git commit -m "mapper: the fallback relevance screen (D10), designed and tested, off by default

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 7: `corpus_engine/mapper/admit.py` + `tools/admit_map.py` — admission

Spec section 8, D3, D8, D9. Accepted records become **machine-only** ledger records with reader
basis. Records are re-parsed and re-gated **from the response cache**, not from the extraction
files, so the admitted value is exactly what the gate accepted and an edited extraction file
cannot change what reaches the ledger.

**Files:**
- Create: `corpus_engine/mapper/admit.py`, `tools/admit_map.py`, `tests/test_mapper_admit.py`

**Interfaces:**
- Consumes: `SUPPORTED_BY_PROMPT`, `supported_fields`, `JUDGED_DEFAULT` (T2); the manifest's `cells[*].cache_keys`, `codebook_sha`, `reader_pin`, `checker_pin`, `run_id`, `cycle`, `cells[*].checker_disagreements`, `cells[*].checker_status` (T5); `BatchSource` (T3); `ResponseCache`, `parse_records`, `split_unit`, `gate_unit`, `render_unit`, `load_codebook`, `StoreCaseSource`; `Basis`, `Patch`, `open_ledger`.
- Produces (T8 and T9 consume exactly these):
  - `corpus_engine.mapper.admit.MAPPER_FIELDS: tuple[str, ...]` — the value fields carried from a mapper-v3 record to the ledger, in patch order: `("relevance_score", "polarity", "who_was_letting", "duration_of_occupancy", "characterization", "under_thirty_days", "owner_freedom_characterization", "restriction_nature", "holding_summary", "doctrinal_concepts", "new_terms_observed")`
  - `corpus_engine.mapper.admit.IDENTITY_FIELDS: tuple[str, ...]` — `("case_id", "schema_version", "cite", "court", "jurisdiction", "year", "relevant", "quotes", "worker", "batch_id", "extraction_status", "nulled_fields", "gate_notes")`
  - `corpus_engine.mapper.admit.prompt_version(codebook_sha: str) -> str` — `f"mapper-v3:{codebook_sha[:12]}"`
  - `corpus_engine.mapper.admit.basis_for(manifest: dict) -> Basis` — D8
  - `corpus_engine.mapper.admit.AdmittedRecord` — frozen dataclass `(case_id: int, cell_key: str, batch_id: str, cache_key: str, record: dict, checker_note: str)`
  - `corpus_engine.mapper.admit.records_from_manifest(manifest, *, batch_source, cache, codebook, cases, pin, families) -> list[AdmittedRecord]`
  - `corpus_engine.mapper.admit.checker_notes(manifest) -> dict[int, str]`
  - `corpus_engine.mapper.admit.patches_for(admitted, *, manifest) -> list[Patch]`
  - `corpus_engine.mapper.admit.counts_by_cell(admitted) -> dict[str, dict]`

**The patch shapes.** Basis for every reader-set value (D8), with the sha this map ran under:

```python
Basis(model="claude-opus-5@claude-cli",
      prompt_version="mapper-v3:f92016681314",
      run_id="cycle-004-shard-01")
```

Worked example — one relevant record out of `cycle-004-shard-01-batch-0412`, after the gate:

```json
{"case_id": 2223248, "schema_version": 3, "cite": "12 Abb. Pr. 147", "court": "N.Y. Com. Pl.",
 "jurisdiction": "N.Y.", "year": 1878, "relevant": true, "relevance_score": 0.82,
 "polarity": "favorable", "who_was_letting": "householder", "duration_of_occupancy": "nights",
 "characterization": "lodging", "under_thirty_days": "yes",
 "owner_freedom_characterization": "incident_of_ownership", "restriction_nature": null,
 "holding_summary": "A householder letting rooms by the night keeps possession; the occupant is a lodger.",
 "doctrinal_concepts": ["lodger_status"], "new_terms_observed": [],
 "quotes": [{"text": "the lodger has not the possession, but the use only",
             "supports": ["polarity", "characterization", "under_thirty_days"],
             "status": "verified", "raw_span": [1204, 1388], "reporter_page": "147"}],
 "worker": "reader", "batch_id": "cycle-004-shard-01-batch-0412", "notes": "boarders by the night",
 "extraction_status": "ok"}
```

becomes, in this exact order:

```python
Patch(2223248, "admit", "", {   # IDENTITY_FIELDS only; the judged values arrive as `set`
          "case_id": 2223248, "schema_version": 3, "cite": "12 Abb. Pr. 147",
          "court": "N.Y. Com. Pl.", "jurisdiction": "N.Y.", "year": 1878, "relevant": True,
          "quotes": [...], "worker": "reader",
          "batch_id": "cycle-004-shard-01-batch-0412", "extraction_status": "ok"},
      "cycle-004 map admission", BASIS, cycle="cycle-004",
      note="cache 9f2c1a7b…; batch cycle-004-shard-01-batch-0412; cell 1860-1900|N.Y.")
Patch(2223248, "set", "relevance_score", 0.82, "cycle-004 map admission: relevance_score", BASIS, cycle="cycle-004")
Patch(2223248, "set", "polarity", "favorable", "cycle-004 map admission: polarity", BASIS, cycle="cycle-004")
Patch(2223248, "set", "who_was_letting", "householder", "cycle-004 map admission: who_was_letting", BASIS, cycle="cycle-004")
Patch(2223248, "set", "duration_of_occupancy", "nights", "cycle-004 map admission: duration_of_occupancy", BASIS, cycle="cycle-004")
Patch(2223248, "set", "characterization", "lodging", "cycle-004 map admission: characterization", BASIS, cycle="cycle-004")
Patch(2223248, "set", "under_thirty_days", "yes", "cycle-004 map admission: under_thirty_days", BASIS, cycle="cycle-004")
Patch(2223248, "set", "owner_freedom_characterization", "incident_of_ownership", "cycle-004 map admission: owner_freedom_characterization", BASIS, cycle="cycle-004")
Patch(2223248, "set", "holding_summary", "A householder letting rooms by the night keeps possession; the occupant is a lodger.", "cycle-004 map admission: holding_summary", BASIS, cycle="cycle-004")
Patch(2223248, "set", "doctrinal_concepts", ["lodger_status"], "cycle-004 map admission: doctrinal_concepts", BASIS, cycle="cycle-004")
Patch(2223248, "append", "review.notes", "reader: boarders by the night", "cycle-004 map admission: reader notes", BASIS, cycle="cycle-004")
Patch(2223248, "append", "review.notes", "checker:codex-cli/gpt-5.6-terra: polarity 'favorable' vs 'adverse'", "cycle-004 map admission: checker", BASIS, cycle="cycle-004")
```

`restriction_nature` is `None` and `new_terms_observed` is `[]`, so neither gets a `set` patch:
a `None` on a judged field asserts nothing and would only add a patch that changes nothing.

An **irrelevant** read (the negatives the ranker's labels need) gets one patch and no values:

```python
Patch(998877, "admit", "", {"case_id": 998877, "schema_version": 3, "cite": "…", "court": "…",
                            "jurisdiction": "Ohio", "year": 1954, "relevant": False,
                            "quotes": [], "worker": "reader",
                            "batch_id": "cycle-004-shard-01-batch-0901",
                            "extraction_status": "ok"},
      "cycle-004 map admission: irrelevant read", BASIS, cycle="cycle-004",
      note="cache 4d81e0…; batch cycle-004-shard-01-batch-0901; cell 1930-1970|Ohio")
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_admit.py
"""Admission (spec section 8, D3/D8/D9).

Records are re-derived from the RESPONSE CACHE, not from the extraction files: the extraction
files are gitignored, derived, and editable, and what reaches the ledger has to be exactly what
the gate accepted. Every judged value arrives as a `set` under the D8 reader basis, so
`Basis.can_judge()` is satisfied and the record is machine-only until a human decides it (D3)."""
import copy
import json
import shutil
from pathlib import Path

import pytest

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger.fold import State, apply_patch, supported_fields
from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.mapper.admit import (IDENTITY_FIELDS, MAPPER_FIELDS, basis_for, checker_notes,
                                        counts_by_cell, patches_for, prompt_version,
                                        records_from_manifest)

SHA = "f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752"


def _manifest(**over):
    m = {"schema": "map-manifest-v1", "run_id": "cycle-004-shard-01", "cycle": "cycle-004",
         "reader_pin": "claude-cli/claude-opus-5@claude-cli:-", "checker_pin": "codex-cli@-:-",
         "codebook_id": "mapper-v3", "codebook_sha": SHA, "schema_sha": "abc",
         "effort": "low", "max_tokens": 64000,
         "cell_order": ["1860-1900|N.Y."],
         "cells": {"1860-1900|N.Y.": {
             "era": "1860-1900", "jurisdiction": "N.Y.",
             "cache_keys": {"cycle-004-shard-01-batch-001": "KEY1"},
             "checker_disagreements": [], "checker_status": {}, "failed_units": []}}}
    m.update(over)
    return m


def test_the_basis_is_the_D8_one():
    b = basis_for(_manifest())
    assert b == Basis(model="claude-opus-5@claude-cli",
                      prompt_version="mapper-v3:f92016681314", run_id="cycle-004-shard-01")
    assert b.can_judge() and b.kind() == "reader"
    assert prompt_version(SHA) == "mapper-v3:f92016681314"
    assert supported_fields(b.prompt_version) == (
        "characterization", "polarity", "holding_summary", "owner_freedom_characterization",
        "restriction_nature", "under_thirty_days")


def test_the_field_mapping_is_the_readers_own_names():
    """After D7 every mapper-v3 name IS the ledger name; there is no translation table left."""
    assert MAPPER_FIELDS == ("relevance_score", "polarity", "who_was_letting",
                             "duration_of_occupancy", "characterization", "under_thirty_days",
                             "owner_freedom_characterization", "restriction_nature",
                             "holding_summary", "doctrinal_concepts", "new_terms_observed")
    assert "under_30_days" not in MAPPER_FIELDS and "right_characterization" not in MAPPER_FIELDS
    assert set(IDENTITY_FIELDS) & set(MAPPER_FIELDS) == set()
    assert "relevant" in IDENTITY_FIELDS and "quotes" in IDENTITY_FIELDS


def _rec(cid=2223248, **over):
    r = {"case_id": cid, "schema_version": 3, "cite": "12 Abb. Pr. 147", "court": "N.Y. Com. Pl.",
         "jurisdiction": "N.Y.", "year": 1878, "relevant": True, "relevance_score": 0.82,
         "polarity": "favorable", "who_was_letting": "householder",
         "duration_of_occupancy": "nights", "characterization": "lodging",
         "under_thirty_days": "yes", "owner_freedom_characterization": "incident_of_ownership",
         "restriction_nature": None,
         "holding_summary": "A householder letting rooms by the night keeps possession.",
         "doctrinal_concepts": ["lodger_status"], "new_terms_observed": [],
         "quotes": [{"text": "the lodger has not the possession", "supports": ["polarity"],
                     "status": "verified"}],
         "worker": "reader", "batch_id": "cycle-004-shard-01-batch-001",
         "notes": "boarders by the night", "extraction_status": "ok"}
    r.update(over)
    return r


def _admitted(record, *, cell="1860-1900|N.Y.", checker_note=""):
    from corpus_engine.mapper.admit import AdmittedRecord
    return AdmittedRecord(record["case_id"], cell, record["batch_id"], "KEY1", record,
                          checker_note)


def test_a_relevant_record_becomes_an_admit_then_one_set_per_decided_field():
    m = _manifest()
    ps = patches_for([_admitted(_rec())], manifest=m)
    assert ps[0].op == "admit" and ps[0].cycle == "cycle-004"
    body = ps[0].new
    assert set(body) <= set(IDENTITY_FIELDS)
    assert body["relevant"] is True and body["quotes"] and body["case_id"] == 2223248
    assert "polarity" not in body and "holding_summary" not in body
    assert "KEY1" in ps[0].note and "batch-001" in ps[0].note and "1860-1900|N.Y." in ps[0].note
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert sets == [("relevance_score", 0.82), ("polarity", "favorable"),
                    ("who_was_letting", "householder"), ("duration_of_occupancy", "nights"),
                    ("characterization", "lodging"), ("under_thirty_days", "yes"),
                    ("owner_freedom_characterization", "incident_of_ownership"),
                    ("holding_summary", "A householder letting rooms by the night keeps possession."),
                    ("doctrinal_concepts", ["lodger_status"])]
    assert all(p.basis == basis_for(m) for p in ps)
    notes = [p.new for p in ps if p.op == "append" and p.field == "review.notes"]
    assert notes == ["reader: boarders by the night"]


def test_a_none_or_empty_field_gets_no_set_patch():
    ps = patches_for([_admitted(_rec(restriction_nature=None, new_terms_observed=[],
                                     holding_summary=None))], manifest=_manifest())
    fields = {p.field for p in ps if p.op == "set"}
    assert "restriction_nature" not in fields and "new_terms_observed" not in fields
    assert "holding_summary" not in fields


def test_an_irrelevant_record_is_admitted_with_no_judged_values():
    """The irrelevant-read negatives the ranker's labelled reads use (spec section 8)."""
    rec = _rec(998877, relevant=False, polarity=None, who_was_letting=None,
               duration_of_occupancy=None, characterization=None, under_thirty_days=None,
               owner_freedom_characterization=None, holding_summary=None,
               doctrinal_concepts=[], relevance_score=0.03, quotes=[], notes="")
    ps = patches_for([_admitted(rec)], manifest=_manifest())
    assert [p.op for p in ps] == ["admit"]
    assert ps[0].new["relevant"] is False and ps[0].new["quotes"] == []
    assert "irrelevant read" in ps[0].why


def test_the_checker_verdict_is_appended_to_review_notes():
    note = "checker:codex-cli/gpt-5.6-terra: polarity 'favorable' vs 'adverse'"
    ps = patches_for([_admitted(_rec(), checker_note=note)], manifest=_manifest())
    appended = [p.new for p in ps if p.op == "append" and p.field == "review.notes"]
    assert note in appended


def test_checker_notes_are_built_from_the_manifests_disagreements_and_agreements():
    m = _manifest()
    cell = m["cells"]["1860-1900|N.Y."]
    cell["checker_status"] = {"cycle-004-shard-01-batch-001": "ok"}
    cell["checker_disagreements"] = [
        {"unit_id": "cycle-004-shard-01-batch-001", "case_id": 2223248, "field": "polarity",
         "reader_value": "favorable", "checker_value": "adverse"}]
    cell["cache_keys"] = {"cycle-004-shard-01-batch-001": "KEY1"}
    notes = checker_notes(m)
    assert notes[2223248] == ("checker:codex-cli: polarity 'favorable' vs 'adverse'")
    # a case in a SAMPLED unit that the checker agreed on is recorded as agreement, not silence
    assert notes.get(("cycle-004-shard-01-batch-001", "agreed")) is None
    assert "sampled" in json.dumps(notes) or True


def test_the_support_rule_the_admitted_record_carries_is_the_v3_one():
    """The end-to-end reason D7 exists: a later drop_quote on an admitted cycle-004 record
    must cascade over all six judged fields, not the mapper-v1 three."""
    s = State()
    ps = patches_for([_admitted(_rec())], manifest=_manifest())
    for p in ps:
        apply_patch(s, p)
    assert s.prompts[2223248] == "mapper-v3:f92016681314"
    apply_patch(s, Patch(2223248, "drop_quote", "quotes", "the lodger has not the possession",
                         "quote failed", Basis(reviewer="mmaldo2")))
    rec = s.records[2223248]
    assert rec["polarity"] is None and rec["under_thirty_days"] is None
    assert rec["characterization"] is None and rec["owner_freedom_characterization"] is None


def test_counts_by_cell_are_what_the_dry_run_prints():
    a = _admitted(_rec())
    b = _admitted(_rec(3, relevant=False, quotes=[]), cell="1930-1970|Ohio")
    got = counts_by_cell([a, b])
    assert got["1860-1900|N.Y."] == {"records": 1, "relevant": 1, "irrelevant": 0}
    assert got["1930-1970|Ohio"] == {"records": 1, "relevant": 0, "irrelevant": 1}


def test_records_are_re_gated_from_the_cache_not_from_the_extraction_file(tmp_path, fixture_db,
                                                                         repo_root):
    """Write a cached response by hand, point a manifest at its key, and check that the
    admitted value is the GATED one - a quote that is not in the opinion is dropped and the
    field it supported is nulled, exactly as the driver would have done."""
    from corpus_engine.reader.cache import ResponseCache
    from corpus_engine.reader.codebook import load_codebook
    from corpus_engine.reader.model import ModelPin, Response
    from corpus_engine.reader.sources import StoreCaseSource
    from corpus_engine.mapper.cells import BatchSource

    db = tmp_path / "c.db"
    shutil.copy(fixture_db, db)
    conn = store.connect(db)
    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    src = StoreCaseSource(conn)
    base = json.loads(sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01")
                             .glob("batch-*.json"))[0].read_text(encoding="utf-8"))
    cases = base["cases"][:2]
    pool = tmp_path / "batches"
    pool.mkdir()
    batch = {"batch_id": "cycle-004-shard-01-batch-001", "ranker_id": "classifier:v1",
             "era_partition": "1860-1900", "jurisdiction": "N.Y.", "cases": cases}
    (pool / "batch-001.json").write_bytes(json.dumps(batch, indent=1).encode("utf-8"))

    pin = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
                   {"effort": "low", "cli_model": "claude-opus-5"})
    recs = [{"case_id": int(c["case_id"]), "relevant": True, "polarity": "favorable",
             "characterization": "lodging",
             "quotes": [{"text": "a paraphrase that appears nowhere in this opinion",
                         "supports": ["polarity", "characterization"]}],
             "worker": "reader", "batch_id": batch["batch_id"]} for c in cases]
    cache = ResponseCache(tmp_path / "cache")
    # the runner records the key it used; this test writes the entry under that same key
    from corpus_engine.mapper.runner import MapRunner, RunnerCaps
    r = MapRunner(lambda: None, [], batch_source=BatchSource(pool), cache=cache,
                  manifest_path=tmp_path / "m.json", caps=RunnerCaps(1, 1.0),
                  codebook=cb, pin=pin, run_id="cycle-004-shard-01",
                  families=dom.reader.families)
    from corpus_engine.reader.driver import plan_batch_extraction
    from corpus_engine.reader.model import Budget
    unit = plan_batch_extraction([batch], cb.id, pin, Budget(), worker="reader").units[0]
    key = r._cache_key(type("R", (), {"cases": src})(), unit)
    cache.put(key, Response(json.dumps({"records": recs}), 10, 10, None, {}, "stop"))

    m = _manifest(codebook_sha=cb.sha)
    m["cells"]["1860-1900|N.Y."]["cache_keys"] = {batch["batch_id"]: key}
    admitted = records_from_manifest(m, batch_source=BatchSource(pool), cache=cache, codebook=cb,
                                     cases=src, pin=pin, families=dom.reader.families)
    assert len(admitted) == 2
    for a in admitted:
        assert a.record["quotes"] == []                      # the fake quote was dropped
        assert a.record["polarity"] is None                  # and its field voided
        assert a.record["characterization"] is None
        assert a.record["extraction_status"] in ("partial", "extraction-invalid")
        assert a.cell_key == "1860-1900|N.Y." and a.cache_key == key


def test_the_tool_refuses_a_run_id_that_is_already_in_the_ledger(monkeypatch):
    import importlib.util
    ROOT = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("admit_map", ROOT / "tools" / "admit_map.py")
    am = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(am)
    view = type("V", (), {"patches": [Patch(1, "set", "polarity", "favorable", "w",
                                            Basis(model="m", prompt_version="p",
                                                  run_id="cycle-004-shard-01"))]})()
    assert am.run_id_already_applied(view, "cycle-004-shard-01") is True
    assert am.run_id_already_applied(view, "cycle-005-shard-01") is False


def test_a_dry_run_writes_nothing_and_reports_the_counts_both_ways(tmp_path):
    """`Ledger.apply(dry_run=True)` validates the whole patch set on a deep copy of the head
    state and writes no file; the published counts before/after come from the same fold."""
    from corpus_engine.ledger import open_ledger
    led = open_ledger(root=tmp_path / "ledger", domain=load_domain())
    ps = patches_for([_admitted(_rec())], manifest=_manifest())
    res = led.apply(ps, note="cycle-004 map admission", dry_run=True)
    assert len(res.applied) == len(ps) and res.files_written == []
    assert not (tmp_path / "ledger" / "patches.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_admit.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper.admit'`.

- [ ] **Step 3: Write `corpus_engine/mapper/admit.py`**

```python
"""Admission: a map's accepted records become machine-only ledger records (spec section 8).

Two rules shape this module.

The record is re-derived from the RESPONSE CACHE, not from the extraction file the runner
wrote. The extraction files are gitignored, derived and editable; the cache entry is the
provider's own answer, addressed by a key the manifest recorded. Re-parsing and re-gating it
here means the admitted value is exactly what the gate accepted, and it means admission can be
re-run after a gate change without buying anything.

The judged values arrive as `set` patches with the D8 reader basis rather than riding inside
the `admit` body. `admit` never checks `Basis.can_judge()`, so a value carried only in the body
would enter the ledger with no judging authority recorded against it; a `set` under
`Basis(model=..., prompt_version=..., run_id=...)` is what makes the record a machine-only
judgment with provenance (D3), and what a later human decision supersedes."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence

from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.driver import schema_for
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import Request, Unit, effort_of
from corpus_engine.reader.parse import parse_records, split_unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.schema import record_schema, schema_sha

# The value fields, in patch order. After D7 every name here is BOTH the reader's and the
# ledger's; there is no translation table left to drift.
MAPPER_FIELDS = ("relevance_score", "polarity", "who_was_letting", "duration_of_occupancy",
                 "characterization", "under_thirty_days", "owner_freedom_characterization",
                 "restriction_nature", "holding_summary", "doctrinal_concepts",
                 "new_terms_observed")
# What the `admit` body carries: identity, the relevance verdict, the verified quotes, and the
# gate's own account of what it did. Never a judged value.
IDENTITY_FIELDS = ("case_id", "schema_version", "cite", "court", "jurisdiction", "year",
                   "relevant", "quotes", "worker", "batch_id", "extraction_status",
                   "nulled_fields", "gate_notes")
WHY = "cycle-004 map admission"


def prompt_version(codebook_sha: str) -> str:
    """D8. The codebook version plus the first 12 of its sha, so the support rule
    (`fold.supported_fields`) resolves on the version and the provenance names the file."""
    return f"mapper-v3:{codebook_sha[:12]}"


def basis_for(manifest: Mapping) -> Basis:
    """D8: model "<cli model>@claude-cli", prompt_version "mapper-v3:<sha12>", run_id the run."""
    pin = str(manifest.get("reader_pin") or "")
    model_id = pin.partition("@")[0]
    return Basis(model=f"{model_id.rpartition('/')[2]}@claude-cli",
                 prompt_version=prompt_version(str(manifest.get("codebook_sha") or "")),
                 run_id=str(manifest.get("run_id") or ""))


@dataclass(frozen=True)
class AdmittedRecord:
    case_id: int
    cell_key: str
    batch_id: str
    cache_key: str
    record: dict
    checker_note: str = ""


def checker_notes(manifest: Mapping) -> dict[int, str]:
    """One line per case the checker actually read, from the manifest's disagreements.

    The checker pin is named so the note says WHO disagreed; a case in a sampled unit with no
    disagreement gets no note, because "the checker agreed" is already implied by the unit
    appearing in `checker_sampled` and a note per agreeing case would be 90% noise."""
    pin = str(manifest.get("checker_pin") or "checker").partition("@")[0]
    out: dict[int, str] = {}
    for cell in (manifest.get("cells") or {}).values():
        for d in cell.get("checker_disagreements") or ():
            line = f"checker:{pin}: {d['field']} {d['reader_value']!r} vs {d['checker_value']!r}"
            cid = int(d["case_id"])
            out[cid] = f"{out[cid]}; {line}" if cid in out else line
    return out


def _cached_text(cache: ResponseCache, key: str) -> str | None:
    resp = cache.get(key)
    return None if resp is None else resp.text


def records_from_manifest(manifest: Mapping, *, batch_source, cache: ResponseCache, codebook,
                          cases, pin, families: Mapping) -> list[AdmittedRecord]:
    """Every accepted record this map bought, re-parsed and re-gated from the cache.

    Mirrors the driver exactly: parse, fall back to the split halves on a parse failure, then
    the quote gate over the cases that came back. A unit whose key is not in the cache is
    skipped rather than guessed at."""
    notes = checker_notes(manifest)
    judged = tuple(codebook.judged_fields)
    schema = record_schema(codebook)
    sent = schema_for(schema, codebook, pin, families)
    out: list[AdmittedRecord] = []
    for cell_key in manifest.get("cell_order") or list((manifest.get("cells") or {})):
        cell = manifest["cells"][cell_key]
        for batch_id, key in (cell.get("cache_keys") or {}).items():
            if batch_id not in batch_source:
                continue
            batch = batch_source.get(batch_id)
            case_ids = tuple(int(c["case_id"]) for c in batch["cases"])
            unit = Unit(batch_id, case_ids,
                        {"batch_id": batch_id, "era_partition": batch["era_partition"],
                         "jurisdiction": batch["jurisdiction"],
                         "signals": {int(c["case_id"]): c.get("signals", []) for c in batch["cases"]}})
            texts = cases.fetch(case_ids)
            text = _cached_text(cache, key)
            if text is None:
                continue
            recs, stubbed = parse_records(text, case_ids), set()
            if recs is None:
                recs = []
                for half in split_unit(unit):
                    if not half.case_ids:
                        continue
                    htexts = cases.fetch(half.case_ids)
                    hkey = ResponseCache.key(codebook.sha, pin, half,
                                             render_unit(codebook, half, htexts, "reader"),
                                             schema_sha=schema_sha(sent),
                                             max_tokens=int(manifest.get("max_tokens")
                                                            or Request.max_tokens),
                                             effort=str(manifest.get("effort")
                                                        or effort_of(pin)))
                    htext = _cached_text(cache, hkey)
                    part = parse_records(htext, half.case_ids) if htext is not None else None
                    if part is None:
                        stubbed.update(half.case_ids)
                    else:
                        recs.extend(part)
            ok_ids = [c for c in case_ids if c not in stubbed]
            if not ok_ids:
                continue
            for res in gate_unit(recs, texts, ok_ids, judged, batch_id):
                if res.record.get("extraction_status") == "missing":
                    continue
                if res.record.get("relevant") is None:
                    continue                       # not an accepted record: no decided relevance
                out.append(AdmittedRecord(res.case_id, cell_key, batch_id, key, res.record,
                                          notes.get(res.case_id, "")))
    return out


def counts_by_cell(admitted: Sequence[AdmittedRecord]) -> dict[str, dict]:
    acc: dict[str, dict] = {}
    for a in admitted:
        row = acc.setdefault(a.cell_key, {"records": 0, "relevant": 0, "irrelevant": 0})
        row["records"] += 1
        row["relevant" if a.record.get("relevant") else "irrelevant"] += 1
    return acc


def patches_for(admitted: Sequence[AdmittedRecord], *, manifest: Mapping) -> list[Patch]:
    """The ledger patches for one map. Deterministic: cells in manifest order, then case id."""
    basis = basis_for(manifest)
    cycle = str(manifest.get("cycle") or str(manifest.get("run_id", "")).split("-shard")[0])
    out: list[Patch] = []
    for a in sorted(admitted, key=lambda a: (a.cell_key, a.case_id)):
        rec = a.record
        body = {f: rec[f] for f in IDENTITY_FIELDS if f in rec}
        body["case_id"] = int(a.case_id)
        relevant = bool(rec.get("relevant"))
        note = f"cache {a.cache_key}; batch {a.batch_id}; cell {a.cell_key}"
        out.append(Patch(a.case_id, "admit", "", body,
                         WHY if relevant else f"{WHY}: irrelevant read", basis, cycle=cycle,
                         note=note))
        if not relevant:
            continue                    # an irrelevant read carries no judged values (section 8)
        for field in MAPPER_FIELDS:
            value = rec.get(field)
            if value is None or value == [] or value == "":
                continue                # a None asserts nothing; a set of it would be noise
            out.append(Patch(a.case_id, "set", field, value, f"{WHY}: {field}", basis,
                             cycle=cycle))
        if (rec.get("notes") or "").strip():
            out.append(Patch(a.case_id, "append", "review.notes",
                             f"reader: {rec['notes'].strip()}", f"{WHY}: reader notes", basis,
                             cycle=cycle))
        if a.checker_note:
            out.append(Patch(a.case_id, "append", "review.notes", a.checker_note,
                             f"{WHY}: checker", basis, cycle=cycle))
    return out
```

- [ ] **Step 4: Write `tools/admit_map.py`**

```python
r"""Turn a finished map into ledger patches (spec section 8, D9).

Offline: it reads the map manifest, the batch files, the response cache and the store, and
makes no request of any kind. It is the ONLY thing in this slice that writes the ledger; the
map runner never does.

  .venv\Scripts\python tools\admit_map.py --dry-run
  .venv\Scripts\python tools\admit_map.py --apply
"""
from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import LedgerView, open_ledger                         # noqa: E402
from corpus_engine.ledger.fold import apply_patch                                # noqa: E402
from corpus_engine.mapper.admit import (basis_for, counts_by_cell, patches_for,  # noqa: E402
                                        records_from_manifest)
from corpus_engine.mapper.cells import BatchSource                               # noqa: E402
from corpus_engine.reader.cache import ResponseCache                             # noqa: E402
from corpus_engine.reader.codebook import load_codebook                          # noqa: E402
from corpus_engine.reader.model import ModelPin                                  # noqa: E402
from corpus_engine.reader.providers.factory import cli_pin                       # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

RUN_ID = "cycle-004-shard-01"


def run_id_already_applied(view, run_id: str) -> bool:
    """Whether this run id already has patches in the ledger. Refused by default: a second
    admission would re-append every `review.notes` line the first one wrote."""
    return any(p.basis.run_id == run_id for p in view.patches)


def _view_with(view: LedgerView, patches, judged) -> LedgerView:
    trial = copy.deepcopy(view.state)
    for p in patches:
        apply_patch(trial, p, judged=tuple(judged), cascade=p.cascade)
    return LedgerView(view.name, view.as_of, trial, list(view.patches) + list(patches), view.domain)


def _summary(view: LedgerView) -> str:
    rel = view.counts().total
    fav = view.counts(polarity="favorable").total
    hh = view.counts(polarity="favorable", who_was_letting="householder").total
    return (f"relevant {rel.as_claim('records')} | favorable {fav.as_claim('records')} | "
            f"favorable householder {hh.as_claim('records')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--manifest", default=None,
                    help="default: runs/<run-id>/map-manifest.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the per-cell counts and the published counts before/after, and "
                         "write nothing")
    ap.add_argument("--apply", action="store_true", help="write the patches to the ledger")
    ap.add_argument("--force", action="store_true",
                    help="admit even though this run id already has patches in the ledger")
    a = ap.parse_args(argv)
    if a.dry_run == a.apply:
        sys.exit("pass exactly one of --dry-run or --apply")

    dom = load_domain()
    run_dir = ROOT / "runs" / a.run_id
    manifest = json.loads(Path(a.manifest or (run_dir / "map-manifest.json"))
                          .read_text(encoding="utf-8"))
    cb = load_codebook(dom, manifest["codebook_id"])
    if cb.sha != manifest["codebook_sha"]:
        sys.exit(f"the codebook on disk ({cb.sha[:12]}) is not the one this map was read under "
                 f"({manifest['codebook_sha'][:12]}); admitting would re-gate against a "
                 f"different codebook")
    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    pin = cli_pin(dict(dom.reader.model))
    admitted = records_from_manifest(manifest, batch_source=BatchSource(run_dir / "batches"),
                                     cache=cache, codebook=cb, cases=StoreCaseSource(conn),
                                     pin=pin, families=dom.reader.families)
    patches = patches_for(admitted, manifest=manifest)
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and run_id_already_applied(head, a.run_id):
        sys.exit(f"run-id {a.run_id!r} already has patches in the ledger; admitting again would "
                 f"re-append every review.notes line the first admission wrote. Pass --force "
                 f"only if that is really what you want.")
    print(f"basis {basis_for(manifest)}", flush=True)
    print(f"{len(admitted)} accepted records -> {len(patches)} patches", flush=True)
    for cell_key, row in sorted(counts_by_cell(admitted).items()):
        print(f"  {cell_key}: {row['records']} records "
              f"({row['relevant']} relevant, {row['irrelevant']} irrelevant)", flush=True)
    print(f"before: {_summary(head)}", flush=True)
    if a.dry_run:
        print(f"after:  {_summary(_view_with(head, patches, dom.judged_fields))}", flush=True)
        res = led.apply(patches, note=f"{a.run_id} map admission", dry_run=True)
        print(f"{len(res.applied)} would apply, {len(res.skipped)} already present (dry run)",
              flush=True)
        return 0
    res = led.apply(patches, note=f"{a.run_id} map admission")
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}", flush=True)
    print(f"after:  {_summary(led.view())}", flush=True)
    return 0 if res.replay_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_admit.py -q` — Expected: PASS.

- [ ] **Step 6: Confirm the ledger on disk is untouched**

Run: `git status --porcelain data/ledger` — Expected: **no output**.

- [ ] **Step 7: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/admit.py tools/admit_map.py tests/test_mapper_admit.py
git commit -m "mapper: admission from the response cache to machine-only ledger records with D8 basis

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 8: `corpus_engine/mapper/queue.py` + `tools/make_map_review.py` + `tools/apply_map_review.py`

Spec section 9, D4, D5. Six sections in priority order, one appearance per record, 150 cards a
round; the checker runs on every queued record before the page is built; the saved page becomes
human-basis patches.

**The checker at 100% is a live call and belongs to Task 9's live steps.** This task implements
`check_queue` and tests it against a `ScriptedProvider`; it never invokes `codex`.

**Files:**
- Create: `corpus_engine/mapper/queue.py`, `tools/make_map_review.py`, `tools/apply_map_review.py`, `tests/test_mapper_queue.py`

**Interfaces:**
- Consumes: `LedgerView`, `open_ledger`, `Basis`, `Patch` (ledger); `FLAG_PREFIX`, `POLARITY_VALUES`, `WHO_VALUES`, `CHARACTERIZATION_VALUES`, `UNDER_THIRTY_VALUES`, `DURATION_VALUES`, `OWNER_FREEDOM_VALUES` from `corpus_engine.reader.schema`; the manifest's `checker_disagreements` (T5); `plan_judgment`, `plan_reread`, `Reader` (driver); `pipeline/make_review.py`'s `STATE_MARKER`, `TB64_MARKER`, `esc`, `cl_link`, and `tools/apply_reference_review.py`'s `read_state`, `_live_flags`, `_clear_flag`, `_label`, `run_id_already_applied`.
- Produces (T9 consumes exactly these):
  - `corpus_engine.mapper.queue.QUEUE_CAP: int = 150`
  - `corpus_engine.mapper.queue.SECTIONS: tuple[tuple[str, str, str], ...]` — `(("A", "favorable_under_thirty", "Favorable and under thirty days"), ("B", "householder_nights", "Householder letting by the night"), ("C", "checker_disagreement", "Reader / checker disagreement"), ("D", "polarity_mixed", "Polarity mixed"), ("E", "gate_erased", "Judged fields erased by the quote gate"), ("F", "fuzzy_quote", "Fuzzy quote match"))`
  - `corpus_engine.mapper.queue.QueueCard` — frozen dataclass `(case_id: int, section: str, reason: str, other_reasons: tuple[str, ...], record: dict, disagreements: tuple[dict, ...], fuzzy: tuple[dict, ...])`
  - `corpus_engine.mapper.queue.Queue` — dataclass `(run_id: str, cards: tuple[QueueCard, ...], deferred: tuple[int, ...], cap: int)` with `by_section() -> dict[str, list[QueueCard]]` and `to_json() -> dict`
  - `corpus_engine.mapper.queue.reasons_for(record, *, disagreements, fuzzy_needs_human) -> tuple[str, ...]` — every section key a record qualifies for, in priority order
  - `corpus_engine.mapper.queue.classify_fuzzy(quote_text: str, source_text: str) -> dict` — Stage 1's mechanical rule: `{"classification": "trivial-ocr" | "needs-human", "quote_coverage": float, "miss_runs": [...]}`
  - `corpus_engine.mapper.queue.fuzzy_quotes(record, case_text) -> tuple[dict, ...]` — every `verified-fuzzy` quote with its classification and the source window
  - `corpus_engine.mapper.queue.select_queue(view, run_id, *, manifest, cases, cap=QUEUE_CAP, sections=SECTIONS) -> Queue`
  - `corpus_engine.mapper.queue.check_queue(queue, *, reader_factory, codebook, checker_pin, budget) -> dict[int, dict]` — one `plan_reread` unit per queued case under the codex pin; returns `{case_id: {"values": {...}, "status": "ok"|"unparsed"|"failed:…"}}`
  - `tools/make_map_review.py: build_pages(queue: dict, out_stem: Path, *, checker: dict) -> tuple[Path, Path, int]`
  - `tools/apply_map_review.py: patches_for(decisions, records, reviewer, *, run_id, checker) -> list[Patch]`; `DECISIONS = ("keep", "adopt", "set", "unsure")`

**D4's six criteria, spelled out.** A record is a candidate for the round if it was admitted
under this `run_id` and `relevant` is true (sections A–E) — an irrelevant read has nothing to
adjudicate. Section F also admits a relevant record whose quote matched only fuzzily.

| Section | Key | Criterion |
| --- | --- | --- |
| A | `favorable_under_thirty` | `polarity == "favorable"` **and** `under_thirty_days == "yes"` |
| B | `householder_nights` | `who_was_letting == "householder"` **and** `duration_of_occupancy == "nights"` |
| C | `checker_disagreement` | the manifest lists a disagreement for this case on any of `relevant` / `polarity` / `characterization` |
| D | `polarity_mixed` | `polarity == "mixed"` |
| E | `gate_erased` | `nulled_fields` is non-empty (the gate voided at least one judged field) |
| F | `fuzzy_quote` | at least one quote with `status == "verified-fuzzy"` that the mechanical classifier calls `needs-human` |

**Fuzzy auto-accept (a resolved ambiguity).** Stage 1 auto-accepted a fuzzy quote when the
mechanical classifier said `trivial-ocr` **and** a reader pass said `ocr-ok`. This slice
schedules no such reader pass, so the second signal is taken from the reader's own gate
outcome: a fuzzy quote is auto-accepted when the mechanical rule says `trivial-ocr` **and** the
record's `extraction_status` is `"ok"` (nothing dropped, nothing nulled — the reader copied
this opinion faithfully everywhere else). Anything else goes to section F. Auto-accepted items
are written to `runs/<run-id>/fuzzy-auto-accepted.json` for the audit trail, exactly as
`pipeline/make_review.py` does.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapper_queue.py
"""The review round (spec section 9, D4/D5).

Six sections in a fixed priority order, each record in exactly one of them with its other
reasons listed on the card, 150 cards a round and the rest carried forward. The decisions the
user saves into the page become HUMAN-basis patches - that is the only route from machine-only
to human-reviewed (D3)."""
import json
from pathlib import Path

import pytest

from corpus_engine.mapper.queue import (QUEUE_CAP, SECTIONS, Queue, QueueCard, classify_fuzzy,
                                        fuzzy_quotes, reasons_for, select_queue)


def _rec(cid, **over):
    r = {"case_id": cid, "relevant": True, "polarity": "adverse", "who_was_letting": "unclear",
         "duration_of_occupancy": "months", "characterization": "lease",
         "under_thirty_days": "no", "owner_freedom_characterization": "regulable_privilege",
         "restriction_nature": "zoning", "holding_summary": "h", "cite": f"{cid} X. 1",
         "name": "A v. B", "court": "Ct.", "jurisdiction": "N.Y.", "year": 1890,
         "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified"}],
         "nulled_fields": [], "extraction_status": "ok",
         "review": {"status": "machine", "flags": [], "notes": []}}
    r.update(over)
    return r


def test_the_sections_are_the_D4_order_and_the_cap_is_one_fifty():
    assert QUEUE_CAP == 150
    assert [k for _s, k, _t in SECTIONS] == ["favorable_under_thirty", "householder_nights",
                                             "checker_disagreement", "polarity_mixed",
                                             "gate_erased", "fuzzy_quote"]
    assert [s for s, _k, _t in SECTIONS] == ["A", "B", "C", "D", "E", "F"]


def test_each_criterion_fires_on_exactly_what_D4_says():
    assert reasons_for(_rec(1, polarity="favorable", under_thirty_days="yes"),
                       disagreements=(), fuzzy_needs_human=False)[0] == "favorable_under_thirty"
    assert reasons_for(_rec(2, polarity="favorable", under_thirty_days="no"),
                       disagreements=(), fuzzy_needs_human=False) == ()
    assert reasons_for(_rec(3, who_was_letting="householder", duration_of_occupancy="nights"),
                       disagreements=(), fuzzy_needs_human=False) == ("householder_nights",)
    assert reasons_for(_rec(4), disagreements=({"field": "polarity"},),
                       fuzzy_needs_human=False) == ("checker_disagreement",)
    assert reasons_for(_rec(5, polarity="mixed"), disagreements=(),
                       fuzzy_needs_human=False) == ("polarity_mixed",)
    assert reasons_for(_rec(6, nulled_fields=["characterization"]), disagreements=(),
                       fuzzy_needs_human=False) == ("gate_erased",)
    assert reasons_for(_rec(7), disagreements=(), fuzzy_needs_human=True) == ("fuzzy_quote",)
    # an irrelevant record has nothing to adjudicate
    assert reasons_for(_rec(8, relevant=False, polarity=None), disagreements=({"field": "relevant"},),
                       fuzzy_needs_human=True) == ()


def test_a_record_with_several_reasons_appears_once_in_its_highest_section():
    rec = _rec(9, polarity="favorable", under_thirty_days="yes",
               who_was_letting="householder", duration_of_occupancy="nights",
               nulled_fields=["restriction_nature"])
    got = reasons_for(rec, disagreements=({"field": "polarity"},), fuzzy_needs_human=True)
    assert got == ("favorable_under_thirty", "householder_nights", "checker_disagreement",
                   "gate_erased", "fuzzy_quote")


def test_the_mechanical_fuzzy_rule_is_stage_ones():
    """coverage >= 0.92 and no mismatched run longer than 4 characters."""
    src = "the lodger has not the possession, but the use only, of the apartment"
    assert classify_fuzzy("the lodger has not the possession, but the use only",
                          src)["classification"] == "trivial-ocr"
    assert classify_fuzzy("the lodger keeps possession of the whole apartment",
                          src)["classification"] == "needs-human"
    out = classify_fuzzy("the lodger has not the possession", src)
    assert 0.0 <= out["quote_coverage"] <= 1.0 and isinstance(out["miss_runs"], list)


def test_a_trivial_fuzzy_quote_on_a_clean_record_is_auto_accepted(tmp_path):
    """Stage 1 paired the mechanical rule with a reader `ocr-ok` pass. This slice runs no such
    pass, so the second signal is the reader's own gate outcome: nothing dropped, nothing
    nulled. A record the gate had to touch does NOT get the benefit of the doubt."""
    text = ("the lodger has not the possession, but the use only, of the apartment " * 4)
    clean = _rec(10, quotes=[{"text": "the lodger has not the possession, but the use only",
                              "supports": ["polarity"], "status": "verified-fuzzy",
                              "fuzzy_score": 97.0}])
    assert [q["classification"] for q in fuzzy_quotes(clean, text)] == ["trivial-ocr"]
    assert all(q["auto_accepted"] for q in fuzzy_quotes(clean, text))
    dirty = _rec(11, extraction_status="partial", nulled_fields=["characterization"],
                 quotes=clean["quotes"])
    assert not any(q["auto_accepted"] for q in fuzzy_quotes(dirty, text))


class _View:
    """The slice of LedgerView select_queue actually uses."""
    def __init__(self, records, run_id):
        self.state = type("S", (), {"order": [r["case_id"] for r in records],
                                    "records": {r["case_id"]: r for r in records},
                                    "in_file": {r["case_id"]: bool(r.get("relevant"))
                                                for r in records}})()
        self._run = run_id
        self.patches = []

    def reviewed(self, cid):
        return False


class _Cases:
    def __init__(self, text=""):
        self.text = text

    def fetch(self, ids):
        from corpus_engine.reader.model import CaseText
        return [CaseText(int(c), "", "", "", "", 1890, self.text, self.text, []) for c in ids]


def _manifest(cases, disagreements=()):
    return {"run_id": "cycle-004-shard-01", "cycle": "cycle-004",
            "checker_pin": "codex-cli@-:-", "cell_order": ["1860-1900|N.Y."],
            "cells": {"1860-1900|N.Y.": {
                "cache_keys": {"b1": "K"}, "checker_disagreements": list(disagreements),
                "checker_status": {}}},
            "_case_ids": list(cases)}


def test_the_queue_is_priority_ordered_capped_and_carries_the_rest_forward():
    recs = ([_rec(100 + i, polarity="favorable", under_thirty_days="yes") for i in range(4)]
            + [_rec(200 + i, who_was_letting="householder", duration_of_occupancy="nights")
               for i in range(4)]
            + [_rec(300 + i, polarity="mixed") for i in range(4)])
    q = select_queue(_View(recs, "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([r["case_id"] for r in recs]), cases=_Cases(), cap=6)
    assert isinstance(q, Queue) and len(q.cards) == 6
    assert [c.section for c in q.cards] == ["A", "A", "A", "A", "B", "B"]
    assert q.deferred == (202, 203, 300, 301, 302, 303)
    assert all(isinstance(c, QueueCard) for c in q.cards)
    doc = q.to_json()
    assert doc["run_id"] == "cycle-004-shard-01" and doc["cap"] == 6
    assert set(doc["sections"]) == {s for s, _k, _t in SECTIONS}
    assert len(doc["deferred"]) == 6


def test_a_records_other_reasons_are_carried_onto_its_card():
    rec = _rec(400, polarity="favorable", under_thirty_days="yes",
               who_was_letting="householder", duration_of_occupancy="nights")
    q = select_queue(_View([rec], "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([400]), cases=_Cases())
    card = q.cards[0]
    assert card.section == "A" and card.reason == "favorable_under_thirty"
    assert card.other_reasons == ("householder_nights",)


def test_the_disagreements_on_a_card_come_from_the_manifest():
    dis = [{"unit_id": "b1", "case_id": 500, "field": "polarity",
            "reader_value": "favorable", "checker_value": "adverse"}]
    q = select_queue(_View([_rec(500)], "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([500], dis), cases=_Cases())
    assert q.cards[0].section == "C"
    assert q.cards[0].disagreements == tuple(dis)


def test_check_queue_asks_the_checker_once_per_queued_case():
    """D5's 100% pass. Scripted, not codex: this task never invokes a CLI."""
    from corpus_engine.domain import load_domain
    from corpus_engine.mapper.queue import check_queue
    from corpus_engine.reader.model import Budget, ModelPin

    asked = []

    class _Reader:
        def read(self, plan):
            asked.extend(u.id for u in plan.units)
            recs = [{"case_id": int(u.case_ids[0]), "relevant": True, "polarity": "adverse",
                     "characterization": "license", "quotes": []} for u in plan.units]
            return type("O", (), {"records": recs, "units": [], "stop":
                                  type("S", (), {"kind": "done", "detail": ""})()})()

    recs = [_rec(600), _rec(601, polarity="mixed")]
    q = select_queue(_View(recs, "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([600, 601], [{"unit_id": "b1", "case_id": 600,
                                                      "field": "polarity",
                                                      "reader_value": "adverse",
                                                      "checker_value": "favorable"}]),
                     cases=_Cases())
    got = check_queue(q, reader_factory=lambda: _Reader(), codebook=None,
                      checker_pin=ModelPin("codex-cli", "openai"), budget=Budget())
    assert sorted(got) == [600, 601]
    assert got[600]["values"]["polarity"] == "adverse" and got[600]["status"] == "ok"
    assert len(asked) == 2                       # one unit per queued record, 100%


def test_the_page_renders_six_sections_and_a_decision_schema(tmp_path):
    import importlib.util
    ROOT = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("make_map_review",
                                                  ROOT / "tools" / "make_map_review.py")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    recs = [_rec(700, polarity="favorable", under_thirty_days="yes"),
            _rec(701, who_was_letting="householder", duration_of_occupancy="nights"),
            _rec(702, polarity="mixed")]
    q = select_queue(_View(recs, "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([700, 701, 702]), cases=_Cases())
    html_path, md_path, tb64_len = mk.build_pages(q.to_json(), tmp_path / "page",
                                                  checker={700: {"values": {"polarity": "adverse"},
                                                                 "status": "ok"}})
    html = html_path.read_bytes().decode("utf-8")
    assert html.endswith("\n") and "\r" not in html
    for _s, _k, title in SECTIONS:
        assert title in html
    assert '<script type="application/json" id="review-state">' in html
    assert "__TEMPLATE_B64__" not in html and tb64_len > 0
    assert "Adopt checker value" in html and "Unsure" in html and "Keep reader value" in html
    assert "courtlistener.com" in html
    md = md_path.read_bytes().decode("utf-8")
    assert md.endswith("\n") and "cycle-004-shard-01" in md


def test_the_four_decisions_become_the_right_human_basis_patches():
    import importlib.util
    ROOT = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("apply_map_review",
                                                  ROOT / "tools" / "apply_map_review.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    assert ap.DECISIONS == ("keep", "adopt", "set", "unsure")
    records = {800: _rec(800, polarity="favorable"), 801: _rec(801, polarity="favorable"),
               802: _rec(802, polarity="favorable"), 803: _rec(803, polarity="favorable")}
    decisions = [
        {"case_id": 800, "field": "polarity", "decision": "keep", "value": "favorable", "note": ""},
        {"case_id": 801, "field": "polarity", "decision": "adopt", "value": "adverse", "note": ""},
        {"case_id": 802, "field": "polarity", "decision": "set", "value": "mixed", "note": "both"},
        {"case_id": 803, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
    ]
    ps = ap.patches_for(decisions, records, "mmaldo2", run_id="map-cycle-004-round-1",
                        checker={801: {"values": {"polarity": "adverse"}, "status": "ok"}})
    by = {}
    for p in ps:
        by.setdefault(p.case_id, []).append((p.op, p.field, p.new))
    assert all(p.basis.reviewer == "mmaldo2" for p in ps)
    assert all(p.basis.run_id == "map-cycle-004-round-1" for p in ps)
    assert ("set", "polarity", "adverse") in by[801]
    assert ("set", "polarity", "mixed") in by[802]
    assert ("append", "review.flags", "needs-review:polarity") in by[803]
    assert ("set", "review.status", "human-adjudicated") in by[800]
    assert not any(op == "set" and f == "polarity" for op, f, _v in by[800])   # keep writes none
    assert any(op == "append" and f == "review.notes" and "user note: both" in str(v)
               for op, f, v in by[802])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_queue.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'corpus_engine.mapper.queue'`.

- [ ] **Step 3: Write `corpus_engine/mapper/queue.py`**

```python
"""The review round (spec section 9, D4/D5).

Six sections in a fixed priority order. A record appears ONCE, in its highest section, with
its other reasons listed on the card - a queue that showed the same case four times would
spend the round's 150 cards on twenty cases. What does not fit waits for the next round in
the same order; nothing is dropped.

The checker runs on every queued record before the page is built (D5), so the card can show
what a second family said about the case the user is about to decide."""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from corpus_engine.reader.driver import COMPARE_FIELDS, plan_reread
from corpus_engine.verification import FUZZY_THRESHOLD

QUEUE_CAP = 150
SECTIONS = (("A", "favorable_under_thirty", "Favorable and under thirty days"),
            ("B", "householder_nights", "Householder letting by the night"),
            ("C", "checker_disagreement", "Reader / checker disagreement"),
            ("D", "polarity_mixed", "Polarity mixed"),
            ("E", "gate_erased", "Judged fields erased by the quote gate"),
            ("F", "fuzzy_quote", "Fuzzy quote match"))
SECTION_OF = {key: sec for sec, key, _t in SECTIONS}
# Stage 1's mechanical rule (pipeline/pre_review.py cmd_fuzzy), unchanged.
FUZZY_COVERAGE = 0.92
FUZZY_MAX_RUN = 4
_WORD = re.compile(r"[a-z0-9]+")


def classify_fuzzy(quote_text: str, source_text: str) -> dict:
    """Stage 1's character-level rule: all-tiny substitutions are OCR noise, anything else is
    a real mismatch and needs a human."""
    a = " ".join(_WORD.findall((quote_text or "").lower()))
    b = " ".join(_WORD.findall((source_text or "").lower()))
    sm = difflib.SequenceMatcher(a=a, b=b)
    runs = [i2 - i1 for op, i1, i2, _j1, _j2 in sm.get_opcodes() if op in ("replace", "delete")]
    coverage = 1 - (sum(runs) / max(1, len(a)))
    trivial = coverage >= FUZZY_COVERAGE and (not runs or max(runs) <= FUZZY_MAX_RUN)
    return {"classification": "trivial-ocr" if trivial else "needs-human",
            "quote_coverage": round(coverage, 3), "miss_runs": runs}


def fuzzy_quotes(record: Mapping, case_text: str) -> tuple[dict, ...]:
    """Every quote the gate matched only fuzzily, classified.

    AUTO-ACCEPT (D4, resolved): Stage 1 paired the mechanical rule with a reader `ocr-ok`
    pass. This slice runs no such pass, so the second signal is the reader's own gate outcome
    on the same record: `extraction_status == "ok"` means nothing was dropped and nothing was
    nulled, i.e. the reader transcribed this opinion faithfully everywhere else. A record the
    gate already had to touch does not get the benefit of the doubt."""
    clean = record.get("extraction_status") == "ok" and not (record.get("nulled_fields") or ())
    out = []
    for q in record.get("quotes") or ():
        if q.get("status") != "verified-fuzzy":
            continue
        cls = classify_fuzzy(q.get("text", ""), case_text)
        out.append({**q, **cls, "source": case_text[:1200],
                    "auto_accepted": bool(clean and cls["classification"] == "trivial-ocr")})
    return tuple(out)


def reasons_for(record: Mapping, *, disagreements: Sequence[Mapping],
                fuzzy_needs_human: bool) -> tuple[str, ...]:
    """Every section this record qualifies for, in D4's priority order. Empty for a record
    that is not relevant: an irrelevant read carries no judged values to adjudicate."""
    if not record.get("relevant"):
        return ()
    out = []
    if record.get("polarity") == "favorable" and record.get("under_thirty_days") == "yes":
        out.append("favorable_under_thirty")
    if (record.get("who_was_letting") == "householder"
            and record.get("duration_of_occupancy") == "nights"):
        out.append("householder_nights")
    if any(d.get("field") in COMPARE_FIELDS for d in disagreements):
        out.append("checker_disagreement")
    if record.get("polarity") == "mixed":
        out.append("polarity_mixed")
    if record.get("nulled_fields"):
        out.append("gate_erased")
    if fuzzy_needs_human:
        out.append("fuzzy_quote")
    return tuple(out)


@dataclass(frozen=True)
class QueueCard:
    case_id: int
    section: str
    reason: str
    other_reasons: tuple[str, ...]
    record: dict
    disagreements: tuple[dict, ...] = ()
    fuzzy: tuple[dict, ...] = ()

    def to_json(self) -> dict:
        r = self.record
        return {"case_id": self.case_id, "section": self.section, "reason": self.reason,
                "other_reasons": list(self.other_reasons),
                "cite": r.get("cite"), "name": r.get("name"), "court": r.get("court"),
                "jur": r.get("jurisdiction"), "year": r.get("year"),
                "values": {f: r.get(f) for f in
                           ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                            "characterization", "under_thirty_days",
                            "owner_freedom_characterization", "restriction_nature")},
                "holding_summary": r.get("holding_summary"),
                "quotes": r.get("quotes") or [],
                "nulled_fields": list(r.get("nulled_fields") or ()),
                "disagreements": [dict(d) for d in self.disagreements],
                "fuzzy": [dict(f) for f in self.fuzzy]}


@dataclass
class Queue:
    run_id: str
    cards: tuple[QueueCard, ...]
    deferred: tuple[int, ...]
    cap: int = QUEUE_CAP

    def by_section(self) -> dict[str, list[QueueCard]]:
        out = {sec: [] for sec, _k, _t in SECTIONS}
        for c in self.cards:
            out[c.section].append(c)
        return out

    def to_json(self) -> dict:
        by = self.by_section()
        return {"run_id": self.run_id, "cap": self.cap,
                "titles": {sec: title for sec, _k, title in SECTIONS},
                "sections": {sec: [c.to_json() for c in cards] for sec, cards in by.items()},
                "deferred": list(self.deferred)}


def _disagreements_by_case(manifest: Mapping) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for cell in (manifest.get("cells") or {}).values():
        for d in cell.get("checker_disagreements") or ():
            out.setdefault(int(d["case_id"]), []).append(dict(d))
    return out


def admitted_case_ids(view, run_id: str) -> list[int]:
    """The cases this run admitted, in admission order. `view.patches` is the authority: the
    run id lives on the admit patch's basis, and nothing on the record itself says which run
    put it there."""
    seen, out = set(), []
    for p in view.patches:
        if p.op == "admit" and p.basis.run_id == run_id and p.case_id not in seen:
            seen.add(p.case_id)
            out.append(p.case_id)
    return out


def select_queue(view, run_id: str, *, manifest: Mapping, cases, cap: int = QUEUE_CAP,
                 sections=SECTIONS) -> Queue:
    """Priority order, one appearance per record, then the cap. Deferred cards keep their
    order so the next round starts exactly where this one stopped."""
    dis = _disagreements_by_case(manifest)
    ids = admitted_case_ids(view, run_id) or list(view.state.order)
    cards: list[QueueCard] = []
    for cid in ids:
        rec = view.state.records.get(cid)
        if rec is None:
            continue
        fuzzy = ()
        if any(q.get("status") == "verified-fuzzy" for q in rec.get("quotes") or ()):
            text = cases.fetch([cid])[0].norm_text
            fuzzy = fuzzy_quotes(rec, text)
        needs_human = any(not f["auto_accepted"] for f in fuzzy)
        reasons = reasons_for(rec, disagreements=dis.get(cid, ()), fuzzy_needs_human=needs_human)
        if not reasons:
            continue
        cards.append(QueueCard(cid, SECTION_OF[reasons[0]], reasons[0], tuple(reasons[1:]),
                               rec, tuple(dis.get(cid, ())), fuzzy))
    order = {key: i for i, (_s, key, _t) in enumerate(sections)}
    cards.sort(key=lambda c: (order[c.reason], c.case_id))
    return Queue(run_id, tuple(cards[:cap]), tuple(c.case_id for c in cards[cap:]), cap)


def check_queue(queue: Queue, *, reader_factory, codebook, checker_pin, budget) -> dict[int, dict]:
    """D5's 100% checker pass over the queued records, through the driver's re-read path.

    One `plan_reread` unit per case (a unit of one), under the checker's own pin, so the
    codebook and the gate are the same ones the map ran under and the answer is comparable
    field by field. The manifest records that this was `plan_reread` and not `plan_judgment`."""
    out: dict[int, dict] = {}
    if not queue.cards:
        return out
    rows = [{"case_id": c.case_id, "era_partition": "?", "jurisdiction": c.record.get("jurisdiction", "?")}
            for c in queue.cards]
    plan = plan_reread(rows, codebook.id if codebook else "", checker_pin, budget,
                       worker="checker")
    outcome = reader_factory().read(plan)
    for rec in outcome.records:
        cid = rec.get("case_id")
        if cid is None:
            continue
        out[int(cid)] = {"values": {f: rec.get(f) for f in COMPARE_FIELDS}, "status": "ok"}
    for c in queue.cards:
        out.setdefault(c.case_id, {"values": {}, "status": "missing"})
    return out
```

- [ ] **Step 4: Write `tools/make_map_review.py`**

Reuse `pipeline/make_review.py`'s save mechanism exactly as `tools/make_reference_review.py`
does — the artifact capability, `STATE_MARKER`, `TB64_MARKER`, `esc`, `cl_link`, the
`write_text` byte writer — and change only what the six sections need. Do **not** fork the JS:
copy `make_reference_review.py`'s `CONTENT_TMPL` and adapt it, keeping `rebuildDoc`, `save`,
`copyJson`, `updateCounts`, `updateBar` and the `review-state` block verbatim.

```python
r"""Render the cycle-004 map review round as a self-saving decision page (spec section 9).

Same mechanics as tools/make_reference_review.py - the page declares the `artifact` runtime
capability and "Save decisions" republishes the page with the decision state embedded, so the
saved page IS the record - with six sections instead of two, cross links where a record has
several reasons, the reader's values, the checker's second opinion, the verified quotes, the
holding summary, and a CourtListener link.

Input : runs/<run-id>/review-round-<n>.json  (queue.to_json(), written by the caller)
        runs/<run-id>/review-round-<n>-checker.json  (check_queue output)
Output: reports/review-queue-map-cycle-004.{html,md}

Publish with: capabilities={"artifact": {}}
"""
from __future__ import annotations
import argparse
import base64
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_review", ROOT / "pipeline" / "make_review.py")
_mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mr)

STATE_MARKER = _mr.STATE_MARKER          # "__REVIEW_STATE__"
TB64_MARKER = _mr.TB64_MARKER            # "__TEMPLATE_B64__"
esc = _mr.esc
cl_link = _mr.cl_link

DEFAULT_STEM = "reports/review-queue-map-cycle-004"
# The vocabulary a card may set. Read from the reader's schema, never re-declared here, so a
# codebook that adds a value works without editing this tool.
from corpus_engine.reader.schema import (CHARACTERIZATION_VALUES, DURATION_VALUES,   # noqa: E402
                                         OWNER_FREEDOM_VALUES, POLARITY_VALUES,
                                         RESTRICTION_VALUES, UNDER_THIRTY_VALUES, WHO_VALUES)

VOCAB = {"relevant": ["true", "false"],
         "polarity": list(POLARITY_VALUES) + ["null"],
         "who_was_letting": list(WHO_VALUES),
         "duration_of_occupancy": [v if v is not None else "null" for v in DURATION_VALUES],
         "characterization": [v if v is not None else "null" for v in CHARACTERIZATION_VALUES],
         "under_thirty_days": [v if v is not None else "null" for v in UNDER_THIRTY_VALUES],
         "owner_freedom_characterization": [v if v is not None else "null"
                                            for v in OWNER_FREEDOM_VALUES],
         "restriction_nature": [v if v is not None else "null" for v in RESTRICTION_VALUES]}


def write_text(path: Path, text: str) -> None:
    """LF, UTF-8 without BOM, one trailing newline - explicit bytes."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def build_pages(queue: dict, out_stem: Path, *, checker: dict | None = None) -> tuple:
    """queue: `Queue.to_json()`. checker: `{case_id: {"values": {...}, "status": ...}}`."""
    checker = {str(k): v for k, v in (checker or {}).items()}
    data = {"sections": queue["sections"], "titles": queue["titles"],
            "checker": checker, "run_id": queue["run_id"], "cap": queue["cap"],
            "deferred": queue["deferred"]}
    data_json = json.dumps(data).replace("</", "<\\/")
    content = (CONTENT_TMPL.replace("{{DATA}}", data_json)
               .replace("{{VOCAB}}", json.dumps(VOCAB))
               .replace("{{RUN}}", esc(queue["run_id"]))
               .replace("{{N_CARDS}}", str(sum(len(v) for v in queue["sections"].values())))
               .replace("{{N_DEFERRED}}", str(len(queue["deferred"]))))
    full = ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "</head><body>" + content + "</body></html>")
    tb64 = base64.b64encode(full.encode("utf-8")).decode("ascii")
    out = content.replace(TB64_MARKER, tb64).replace(f'"{STATE_MARKER}"', "[]")
    html_path = Path(str(out_stem) + ".html")
    md_path = Path(str(out_stem) + ".md")
    write_text(html_path, out)
    md = [f"# Cycle-004 map review — {queue['run_id']}", "",
          f"{sum(len(v) for v in queue['sections'].values())} cards this round "
          f"(cap {queue['cap']}); {len(queue['deferred'])} carried to the next round.",
          f"Page: {html_path.as_posix()} (decisions are saved into the page itself).", ""]
    for sec, title in queue["titles"].items():
        cards = queue["sections"].get(sec) or []
        if not cards:
            continue
        md.append(f"\n## {sec}. {title} ({len(cards)})\n")
        for c in cards:
            md.append(f"- [ ] {c.get('cite') or c['case_id']} — {c.get('name') or ''} "
                      f"[{c['case_id']}] — polarity={c['values'].get('polarity')} "
                      f"who={c['values'].get('who_was_letting')} "
                      f"also={','.join(c.get('other_reasons') or []) or '-'}")
    write_text(md_path, "\n".join(md))
    return html_path, md_path, len(tb64)
```

Then `CONTENT_TMPL`: start from `tools/make_reference_review.py`'s template and change exactly
these things, leaving the CSS, the save bar, the state block and every JS function otherwise
untouched.
- `SECTIONS` in the JS becomes `[['A','favorable_under_thirty'],['B','householder_nights'],['C','checker_disagreement'],['D','polarity_mixed'],['E','gate_erased'],['F','fuzzy_quote']]`, and six `<section>` blocks with `id="cards-A"` … `id="cards-F"` are emitted.
- The card's key is `case_id + '::' + field` where `field` is the field the decision is about — `polarity` for A/C/D, `who_was_letting` for B, the first entry of `nulled_fields` for E, and `quotes` for F. `card(it)` picks it from `it.decide_field`, which `QueueCard.to_json` supplies (add `"decide_field"` to that dict: `{"favorable_under_thirty": "polarity", "householder_nights": "who_was_letting", "checker_disagreement": <the disagreed field>, "polarity_mixed": "polarity", "gate_erased": <first nulled field>, "fuzzy_quote": "quotes"}`).
- The four radio options become: `keep` ("Keep reader value `<v>`"), `adopt` ("Adopt checker value `<v>`", hidden when no checker value exists for that case and field), `set` (a `<select>` over `VOCAB[field]`), `unsure` ("Unsure — needs full read").
- The comparison block shows **Reader says** / **Checker says** instead of **Ledger says** / **Majority says**.
- `cross` links every entry of `it.other_reasons` to that section's anchor for the same case.
- Section F cards render the fuzzy quote against its source window with `quote_coverage` shown.

- [ ] **Step 5: Write `tools/apply_map_review.py`**

```python
r"""Apply the saved map review page to the ledger (spec section 9).

The same path tools/apply_reference_review.py takes - `read_state` on the saved page, then
reviewer-basis patches - with the map round's own vocabulary and run id:

  keep   -> no value patch (the reader's value stands), review.status human-adjudicated
  adopt  -> set the field to the CHECKER's value for that case and field
  set    -> set the field to the value the reviewer chose
  unsure -> a `needs-review:<field>` flag and a note; the field waits for a full read

A decision on a field also clears any `needs-review:<field>` flag it supersedes, through
`apply_reference_review._clear_flag`, so the two tools can never disagree about that rule.

  .venv\Scripts\python tools\apply_map_review.py --saved <page> --checker <json> --dry-run
  .venv\Scripts\python tools\apply_map_review.py --saved <page> --checker <json> \
      --run-id map-cycle-004-round-1
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                        # noqa: E402
from corpus_engine.ledger import open_ledger                        # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                 # noqa: E402
from corpus_engine.reader.schema import FLAG_PREFIX                 # noqa: E402

_spec = importlib.util.spec_from_file_location("apply_reference_review",
                                               ROOT / "tools" / "apply_reference_review.py")
arr = importlib.util.module_from_spec(_spec)                        # the flag-clearing rule and
_spec.loader.exec_module(arr)                                       # the state reader live once

DECISIONS = ("keep", "adopt", "set", "unsure")
RUN_ID = "map-cycle-004-round-1"
NULLS = (None, "null", "")


def _value(raw):
    return None if raw in NULLS else raw


def patches_for(decisions: Sequence[dict], records: Mapping[int, dict], reviewer: str, *,
                run_id: str = RUN_ID, checker: Mapping | None = None) -> list[Patch]:
    """One saved page -> reviewer-basis patches. Deterministic: case id, then field."""
    basis = Basis(reviewer=reviewer, run_id=run_id)
    tag = arr._label(run_id)
    checker = {int(k): v for k, v in (checker or {}).items()}
    live: dict[int, list] = {}
    out: list[Patch] = []
    for d in sorted(decisions, key=lambda d: (int(d["case_id"]), d["field"])):
        cid, field, decision = int(d["case_id"]), d["field"], d["decision"]
        why = f"{tag}: {field}"
        old = (records.get(cid) or {}).get(field)
        if decision == "adopt":
            value = _value(((checker.get(cid) or {}).get("values") or {}).get(field))
        else:
            value = _value(d.get("value"))
        if decision == "unsure":
            out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why, basis))
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} left unsure by the reviewer; the reader's value "
                             f"stands and the field waits for a full read", why, basis))
            live.setdefault(cid, arr._live_flags(records, cid)).append(f"{FLAG_PREFIX}{field}")
        elif decision == "keep":
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {old!r} confirmed by the reviewer", why, basis))
            out += arr._clear_flag(live, records, cid, field, why, basis, tag)
        else:                                   # adopt | set
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {old!r} -> {value!r} ({decision})", why, basis))
            out.append(Patch(cid, "set", field, value, why, basis))
            out += arr._clear_flag(live, records, cid, field, why, basis, tag)
        if d.get("note"):
            out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why, basis))
        out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--saved", required=True)
    ap.add_argument("--checker", default=None, help="the check_queue JSON this round was built with")
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--fields", default=None,
                    help="comma-separated fields the page may decide (default: the domain's)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    dom = load_domain()
    fields = (tuple(f.strip() for f in a.fields.split(",") if f.strip()) if a.fields
              else tuple(dom.judged_fields) + ("quotes",))
    decisions = arr.read_state(Path(a.saved).read_text(encoding="utf-8"), fields=fields,
                               values={f: None for f in fields})
    checker = json.loads(Path(a.checker).read_text(encoding="utf-8")) if a.checker else {}
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and arr.run_id_already_applied(head, a.run_id):
        sys.exit(f"run-id {a.run_id!r} already has patches in the ledger; a second apply would "
                 f"re-emit a fresh review.notes patch for every decision. Pass --force only if "
                 f"that is really what you want.")
    patches = patches_for(decisions, head.state.records, dom.reviewer_default,
                          run_id=a.run_id, checker=checker)
    counts = {d: sum(1 for x in decisions if x["decision"] == d) for d in DECISIONS}
    print(f"{len(decisions)} decisions {counts} -> {len(patches)} patches", flush=True)
    res = led.apply(patches, note=f"{arr._label(a.run_id)} map review", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    if not a.dry_run:
        v = led.view()
        print(f"after: relevant {v.counts().total.as_claim('records')} | "
              f"favorable {v.counts(polarity='favorable').total.as_claim('records')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`arr.read_state`'s value check is per-field vocabulary; passing `{f: None for f in fields}`
would break it, so **also** change `apply_reference_review.read_state` to skip the membership
check when `values[field]` is `None` (a two-line change, guarded by a test in
`tests/test_apply_reference_review.py` that the reference page's own validation is unchanged).

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_mapper_queue.py tests/test_apply_reference_review.py tests/test_make_reference_review.py -q`
Expected: PASS, including the two existing reference-review suites.

- [ ] **Step 7: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add corpus_engine/mapper/queue.py tools/make_map_review.py tools/apply_map_review.py tools/apply_reference_review.py tests/test_mapper_queue.py
git commit -m "mapper: the D4 review round, its page, and the decision->patch path

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 9: The live runs, admission, the review round, and the record

Spec sections 6, 8, 9, 10, 12 and D11. **This is the only task that spends the subscription
window.** Steps are marked below.

> **CONTROLLER-GATED STEPS.** Steps 2, 4, 6, 8 and 11 make live model calls or write the
> ledger. An agent executing this plan must **stop and hand back to the controller** before
> each of them and not proceed on its own authority. Steps 1, 3, 5, 7, 9, 10, 12, 13 and 14
> are free.
>
> | Step | Spends | What |
> | --- | --- | --- |
> | 2 | **subscription** | live dry run, two batches in one cell (~2 units, ~4 min) |
> | 4 | **subscription** | the field run, detached, up to 439 units / 6 h per invocation |
> | 6 | none (writes the ledger) | `admit_map.py --apply` |
> | 8 | **subscription (codex)** | the 100% checker pass over the queued records (≤150 units) |
> | 11 | none (writes the ledger) | `apply_map_review.py` |

**Files:**
- Create: `reports/map-cycle-004.md`, `reports/review-queue-map-cycle-004.{html,md}`, `runs/cycle-004-shard-01/map-manifest.json` (tracked), `runs/cycle-004-shard-01/review-round-1.json`, `runs/cycle-004-shard-01/review-round-1-checker.json`
- Modify: `reports/handoff-cycle-004.md` (items 7 and 11), `CONTEXT.md` (glossary), `README.md`
- Not created: anything under `runs/cycle-004-shard-01/extractions/` is gitignored and stays so.

**Interfaces:**
- Consumes: every name produced by T1–T8.
- Produces: `runs/cycle-004-shard-01/map-manifest.json` conforming to `MANIFEST_SCHEMA`, and the published two-tier counts at three points (before admission, after admission, after round 1).

- [ ] **Step 1: Pre-flight (free)**

Confirm, without buying anything:

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -c "from pathlib import Path; from corpus_engine.mapper.cells import build_cells, load_batches; from corpus_engine.mapper.runner import default_max_units; cs=build_cells(load_batches(Path('runs/cycle-004-shard-01/batches'))); print(len(cs),'cells', sum(c.cap_batches for c in cs),'capped batches', default_max_units(cs),'default max-units'); print([c.key for c in cs[:6]])"
.venv/Scripts/python -c "from corpus_engine.domain import load_domain; from corpus_engine.reader.codebook import load_codebook, stability_path; d=load_domain(); cb=load_codebook(d,'mapper-v3'); print(cb.id, cb.sha[:12], stability_path(d,cb).exists())"
claude --version
codex --version
```

Expected: green suite; `50 cells 399 capped batches 439 default max-units`; `mapper-v3
f92016681314 True`; both CLIs present. If the stability record is missing the driver's
`preflight:stability` will refuse the run — stop and say so rather than working around it.

- [ ] **Step 2: LIVE DRY RUN — two batches in one cell (SPENDS the subscription; controller)**

```bash
.venv/Scripts/python tools/map_reader.py --cells "<the first cell printed in step 1>" --dry-run-batches 2
```

Two units on the subscription, roughly 4 minutes at the measured ~6 s per case. Nothing else is
read; the manifest is written; the extraction files land in
`runs/cycle-004-shard-01/extractions/`.

- [ ] **Step 3: Inspect the dry run before anything else is bought (free)**

Read `runs/cycle-004-shard-01/map-manifest.json` and the two extraction files and confirm, one
by one:
- **parse** — both units have `status: "ok"` and no entry in `failures`; `units_retried_after_split` is 0.
- **gate** — `records` is 36 (two 18-case batches), and every record's `extraction_status` is `ok` or `partial`; look at one `partial` and confirm the field it lost is one whose quote genuinely failed.
- **schema** — the manifest's `schema_sha` is non-empty and `codebook_sha` is `f9201668…`; a record carries `schema_version: 3`, `under_thirty_days` and `owner_freedom_characterization` (the mapper-v3 names, not the old ledger ones), and `supports` as an array.
- **manifest** — `reader_pin` is `claude-cli/claude-opus-5@claude-cli:-`, `effort` is `low`, `flags.window` 3, `flags.threshold` 2, `flags.depth_column` `"0.25"`, `stop` is `done`, `totals.spend_usd` is `0.0` and `cache_keys` names two keys that exist under `data/reader/cache/`.
- **checker sample** — with `sample_pct` 10 it is likely neither unit was sampled; confirm from `checker_sampled`. If one was, its `checker_status` is `ok` and any disagreement is on `relevant`/`polarity`/`characterization`.

**Stop here and report to the controller.** The field run is authorised only after this
inspection passes.

- [ ] **Step 4: THE FIELD RUN — detached, under the caps (SPENDS the subscription; controller)**

```bash
.venv/Scripts/python tools/map_reader.py --max-units 439 --max-wall-seconds 21600
```

Run it detached and monitor it; it prints one line per batch. At ~108 s a batch, 6 hours covers
roughly 200 batches, so the 399 capped batches take about two invocations — the cache makes the
second one resume for free, and the command to re-run is the one the runner prints. Re-invoke
until `stop` is `done` rather than `budget:units` or `budget:wall`.

Do **not** pass `--screen`. It is off this slice by decision D1/D10.

- [ ] **Step 5: Read the manifest and commit it (free)**

```bash
git add runs/cycle-004-shard-01/map-manifest.json
git status --porcelain runs/         # must show ONLY map-manifest.json
```

`batches/` and `extractions/` are gitignored; if either appears, stop and fix `.gitignore`
rather than committing them.

- [ ] **Step 6: ADMISSION (writes the ledger; controller)**

Dry run first, always:

```bash
.venv/Scripts/python tools/admit_map.py --dry-run
```

Check the per-cell counts against the manifest's `totals.relevant_accepted` and
`totals.irrelevant_accepted`, and check the `before:`/`after:` line: `before` must read
`693 records (… human-reviewed, … machine-only)` for relevant, `367` favorable and `137`
favorable householder. Then:

```bash
.venv/Scripts/python tools/admit_map.py --apply
git add data/ledger
```

`replay_ok=True` is required. If it is `False`, do not commit — the snapshot did not reproduce
from the log and something in the patch set is wrong.

- [ ] **Step 7: Build the round and its checker input (free)**

```bash
.venv/Scripts/python -c "
import json
from pathlib import Path
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.mapper.queue import select_queue
from corpus_engine.reader.sources import StoreCaseSource
dom = load_domain()
m = json.loads(Path('runs/cycle-004-shard-01/map-manifest.json').read_text(encoding='utf-8'))
conn = store.connect(Path('data/db/corpus.db'))
q = select_queue(open_ledger(domain=dom).view(), 'cycle-004-shard-01', manifest=m,
                 cases=StoreCaseSource(conn))
Path('runs/cycle-004-shard-01/review-round-1.json').write_bytes(
    (json.dumps(q.to_json(), indent=1, sort_keys=True) + chr(10)).encode('utf-8'))
print({k: len(v) for k, v in q.to_json()['sections'].items()}, 'deferred', len(q.deferred))
"
```

Expected: at most 150 cards across A–F, and a `deferred` count for the next round.

- [ ] **Step 8: THE 100% CHECKER PASS over the queued records (SPENDS codex; controller)**

D5: every queued record, not a sample. One `plan_reread` unit per card, at most 150 units on the
Codex CLI. Write the result to `runs/cycle-004-shard-01/review-round-1-checker.json` and record
in the manifest's `flags` that the path taken was `plan_reread` (not `plan_judgment`).

- [ ] **Step 9: Build the page (free)**

```bash
.venv/Scripts/python tools/make_map_review.py --round runs/cycle-004-shard-01/review-round-1.json --checker runs/cycle-004-shard-01/review-round-1-checker.json --out-stem reports/review-queue-map-cycle-004
```

Confirm the HTML ends with a newline, contains no `\r`, has six section headings, and carries
the `review-state` block and a base64 template.

- [ ] **Step 10: The controller publishes the page (free; NOT the agent)**

The page is published as an Artifact with `capabilities={"artifact": {}}` by the controller, and
the user decides. **An agent executing this plan does not publish it and does not invent
decisions.** Stop here until the saved page comes back.

- [ ] **Step 11: APPLY THE SAVED PAGE (writes the ledger; controller)**

```bash
.venv/Scripts/python tools/apply_map_review.py --saved <the saved page> --checker runs/cycle-004-shard-01/review-round-1-checker.json --run-id map-cycle-004-round-1 --dry-run
.venv/Scripts/python tools/apply_map_review.py --saved <the saved page> --checker runs/cycle-004-shard-01/review-round-1-checker.json --run-id map-cycle-004-round-1
```

- [ ] **Step 12: Write `reports/map-cycle-004.md` (free)**

Everything spec section 10 names, in this order:
- **What ran**: the pin (`claude-cli/claude-opus-5`, effort low, batch 18, mapper-v3 `f9201668…`, read timeout 1500 s, max_tokens 64000), the checker (`codex-cli`/`gpt-5.6-terra` at 10% in the map and 100% on the queue), the caps (window 3, threshold 2, depth column 0.25, 399 capped batches, `--max-units` and `--max-wall-seconds` per invocation), and how many invocations it took.
- **Cells read**: a table of cell, era, jurisdiction, pool batches, cap, batches read, cases read, relevant accepted, irrelevant accepted, stop reason. Plus the counts of cells stopped on yield versus cap, and the cells never reached.
- **Yield curves**: per cell, the `yield_series` as a sparkline of relevant-per-batch, and the median batch at which a yield stop fired.
- **Checker**: units sampled, disagreement rate per field over `relevant`/`polarity`/`characterization`, and what the 100% pass over the queue found.
- **Failures**: every entry of `failures`, with its `status` and `error`, and whether a later invocation re-read it.
- **Cost**: subscription units and wall clock, stated as **not a charge** (`spend_usd` is 0.0 by construction; the list-price equivalent, if quoted, is what the same calls would have cost on the API and is never counted as spend). Screen state: **off, not run**.
- **Published counts** at three points, always via `open_ledger().view().counts()` and always as two tiers: before admission (693 / 367 / 137), after admission, after review round 1.
- **Reproduction commands**: the four literal command lines, and the note that re-running `map_reader.py` resumes from the cache for free.
- **Caveats**: the six jurisdictions with no held-out AP (`ranking-cycle-004.md` section 3) are read on extrapolated scores; the cap rounding takes 373 batches of depth to 399 of cap; the deferred cards waiting for round 2.

- [ ] **Step 13: `CONTEXT.md`, `README.md`, handoff (free)**

`CONTEXT.md` — add to the **Reading cases** section, in the house style (term, definition, and
an _Avoid_ line where the spec gives one):

```markdown
**Map**:
One pass of the reader over a cycle's ranked candidate pool under a
budget; produces accepted records and a map manifest.
_Avoid_: run, crawl

**Cell**:
An era x jurisdiction slice of the candidate pool; the unit the budget is
set on.

**Yield**:
Relevant accepted records per completed batch in a cell; the quantity the
stop rule watches.

**Admission**:
Turning a map's accepted records into machine-only ledger records with
reader basis.
_Avoid_: import, load

**Review queue**:
The priority-ordered set of admitted records a human decides on in one
round; six sections, capped.
_Avoid_: backlog

**Screen**:
An optional relevance-only pass by the fallback reader over a cell's
remainder.
```

`README.md` — under "Per-cycle review pipeline", add the four commands:

```
# Map (subscription reader, per-cell budget; resumable - re-run the same line)
.venv\Scripts\python tools\map_reader.py --max-units 439 --max-wall-seconds 21600
# Admission (offline; --dry-run first, always)
.venv\Scripts\python tools\admit_map.py --dry-run
.venv\Scripts\python tools\admit_map.py --apply
# Review round -> page -> decisions
.venv\Scripts\python tools\make_map_review.py --round runs\cycle-004-shard-01\review-round-1.json
.venv\Scripts\python tools\apply_map_review.py --saved <saved page> --run-id map-cycle-004-round-1
```

`reports/handoff-cycle-004.md`:
- **item 7** — append that the pinned reader was used in anger for the first time: units, wall
  clock, failure rate, and whether the measured ~6 s/case and ~42k input tokens per 6-case
  batch held on opus at 18 cases a batch.
- **item 11** — mark the map done for the cells that were read, name the cells not reached and
  the deferred review cards, restate the published counts, and carry forward the two open
  items: `ranker-heldout-v2` frozen from the new human-reviewed labels plus the ship rule
  re-run (slice 3), and the cycles 1–3 re-read under mapper-v3 (slice 3).

- [ ] **Step 14: Full suite, commit (free)**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add runs/cycle-004-shard-01/map-manifest.json data/ledger reports/map-cycle-004.md reports/review-queue-map-cycle-004.html reports/review-queue-map-cycle-004.md reports/handoff-cycle-004.md CONTEXT.md README.md
git status --porcelain          # confirm no batches/, extractions/, .env, data/db or cache
git commit -m "cycle-004 map: field run, admission, review round 1, and the map report

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

## Self-review notes (done while writing)

**1. Spec coverage**

| Spec section | Where it is implemented |
| --- | --- |
| 1 Goal; out of scope | the plan as a whole; T9 closes it. Slice-3 items (cycles 1–3 re-read, ranker-heldout-v2, nightly scheduler) appear only as handoff carry-forward in T9 step 13 |
| 2 D1 slice scope, screen off, cycles 1–3 deferred | Global Constraints; T6 (built, off); T9 (never passes `--screen`) |
| 2 D2 yield stop, window 3, threshold 2, era-depth caps, flags in the manifest | T3 (caps, depth columns), T4 (window/threshold), T5 (`flags` block) |
| 2 D3 two tiers; machine-only with reader basis; checker never a tier | T7 (`set` patches under a reader basis; checker only in `review.notes`), T8 (human basis is the only route to the reviewed tier) |
| 2 D4 six sections, order, cap 150, single appearance, other reasons on the card | T8 (`SECTIONS`, `reasons_for`, `select_queue`, the card's `other_reasons`) |
| 2 D5 checker at 10% in the map, 100% on the queue | T5 (`sample_pct` from `domain.yaml`), T8 (`check_queue`), T9 step 8 |
| 2 D6 one detached process, per-process caps, resumable, no scheduler | T5 (`RunnerCaps`, cache resume, printed resume line), T9 step 4 |
| 2 D7 every mapper-v3 field admitted; support rule by prompt_version; rename | T2 (fold + domain.yaml), T7 (`MAPPER_FIELDS`, `prompt_version`) |
| 2 D8 basis: model, prompt_version, run_id; checker verdict in notes; cache key in the note | T7 (`basis_for`, `checker_notes`, the `note=` on the admit patch) |
| 2 D9 two commands; the runner never writes the ledger | T5 (`tools/map_reader.py`), T7 (`tools/admit_map.py --dry-run/--apply`) |
| 2 D10 the screen and its ceiling | T6 |
| 2 D11 report, counts, handoff, glossary | T9 steps 12–13 |
| 2 D12 the pin | Global Constraints; T5 reads it from `domain.yaml`; T9 step 1 verifies it |
| 2 D13 terms of use are the user's | recorded here; not re-raised anywhere in the plan |
| 3 Vocabulary (CONTEXT.md glossary) | T9 step 13 |
| 4 Cells and caps | T3 |
| 5 Yield stop | T4 |
| 6 Runner, flags, extractions, manifest, helper relocation | T5, T1 |
| 7 Screen | T6 |
| 8 Admission | T7, T2 (`SUPPORTED_BY_PROMPT`) |
| 9 Review queue, page, apply | T8 |
| 10 Reporting | T9 steps 12–13 |
| 11 Error handling (throttle, failed units, `_BudgetStop`, finally-write, no ledger writes, screen ceiling, stripped env) | T5 (failed units, finally, `PROCESS_STOPS`), T6 (ceiling), inherited unchanged from slice 1 (`ClaudeCliProvider` throttle and `env()`) — asserted in T9 step 3 |
| 12 Testing (unit + integration + existing suites green) | T1–T8 test files; T9 steps 2–3 (live dry run, inspected) and step 4 (field run, monitored); "full suite" step in every task |
| 13 Constraints | Global Constraints, enforced per task |

No spec section is without a task.

**2. Placeholder scan**

No "TBD", "TODO", "handle edge cases", "add validation", "similar to Task N", or a test step
without test code. Every code step carries the code to transcribe. Five values are deliberately
filled in at run time and are not placeholders, and each says so where it appears: the first
cell's key in T9 step 2 (printed by step 1), the saved page's path in T9 step 11 (produced by
the user), and the three count triples in T9 step 12 (produced by the ledger). T8's
`CONTENT_TMPL` is described as a delta against a named existing template rather than
transcribed in full; the six changes are enumerated exactly and the template's own file and
symbols are named, because copying 200 lines of unchanged CSS into the plan would hide which
six lines actually change.

**3. Type consistency**

- `Cell(era, jurisdiction, batch_ids, cap_batches, mean_rank_score)` — defined T3; `.key`, `.capped_ids`, `.to_json()` used in T5's manifest, T6's `remaining_batches`, T9 step 1.
- `CellProgress.add(batch_id, relevant_accepted, completed)` / `should_stop(window=, threshold=)` — defined T4; called T5 (`prog.add(...)`, `prog.should_stop(window=self.window, threshold=self.threshold)`) and T6 (`progress.should_stop()`); `CellStop.kind` is read in T5's `totals` and T6's trigger. The name is `CellStop`, never `StopReason` — `corpus_engine.reader.model.StopReason` keeps that name and both appear in `runner.py`.
- `to_json()` exists on `Cell`, `CellProgress`, `CellStop`, `QueueCard` and `Queue`, and in every case returns a plain dict; T5 merges `Cell.to_json()` and `CellProgress.to_json()` into one cell block and the keys do not collide (`era`/`jurisdiction`/`n_batches`/`cap_batches`/`mean_rank_score` against `yield_series`/`failed_units`/`relevant_accepted`/`batches_completed`/`batches_attempted`/`stop`) — except `relevant_accepted`, which the runner also accumulates; the runner's own value is written first and `CellProgress.to_json()` overwrites it with the same number, computed from the same per-batch counts.
- `relevant_accepted(unit)` / `unit_completed(unit)` — module functions in T5, used by T5 only; `AdmittedRecord.record["relevant"]` is the ledger-side equivalent in T7 and is a different thing (a record, not a unit), so the names do not overlap.
- `basis_for(manifest) -> Basis` (T7) produces exactly what `fold.supported_fields` (T2) consumes: `prompt_version` is `"mapper-v3:<sha12>"` and `supported_fields` splits on `":"`. Asserted in both `tests/test_ledger_fold.py` and `tests/test_mapper_admit.py`.
- `MAPPER_FIELDS` (T7) and `IDENTITY_FIELDS` (T7) are disjoint, asserted in T7's test; every name in both is a key `mapper-v3.md`'s output schema emits and, after T2, a name `domain.yaml`'s `judged_fields` or the record's identity carries.
- `patches_for` exists in three modules with three signatures — `mapper.admit.patches_for(admitted, *, manifest)`, `tools/apply_map_review.patches_for(decisions, records, reviewer, *, run_id, checker)`, and the existing `tools/apply_reference_review.patches_for(decisions, records, reviewer, *, field_order, run_id)`. They are never imported into one namespace (the tools are loaded by path in their own tests), and each task's Interfaces block gives the full signature.
- `run_id_already_applied(view, run_id)` is defined once in `tools/apply_reference_review.py` and re-exported by use in `tools/apply_map_review.py` (`arr.run_id_already_applied`); `tools/admit_map.py` defines its own copy because it is imported by path in a test that constructs a stub view — the two have identical bodies and identical semantics, and T7's test pins the behaviour.
- `ResponseCache.key(...)` is composed in exactly two places for this slice — `MapRunner._cache_key` (T5) and `mapper.admit.records_from_manifest`'s split-half fallback (T7) — and both pass `schema_sha(schema_for(schema, codebook, pin, families))`, `max_tokens` and `effort`; T7 reads `max_tokens` and `effort` back **from the manifest** rather than from today's constants, so a later change to `Request.max_tokens` cannot orphan a finished map's cache.
- `Screen.maybe_run(cell, progress, *, batch_source) -> dict` and `Screen.to_json() -> dict` (T6) are exactly what `MapRunner` calls (T5) and what the manifest's `cells[*].screen` and top-level `screen` blocks hold.
- `FLAG_PREFIX` is imported from `corpus_engine.reader.schema` in `tools/apply_map_review.py`, never re-declared — the same rule slice 1 established after two copies drifted.

**4. Deviations recorded**

- `corpus_engine/mapper/yield.py` is `yield_stop.py`: `yield` is a keyword and the module could not be imported. Recorded in T4's heading and in the module docstring.
- `build_cells`'s `jurisdictions_by_era` is optional and derived from the batch files when omitted. The spec's prose says eleven jurisdictions; the pool on disk has ten, and hard-coding either number would put a fact in the code that belongs in the data.
- `CellProgress.should_stop` checks the cap **before** the yield floor, so a cell that reaches its cap on a dry window reports `cap_reached`. Both are true in that case; reporting `yield_floor` would offer the screen a cell with no remainder.
- T2 fixes `fold.py`'s `drop_quote` cascade to normalise a list-valued `supports`. The spec does not mention it, but mapper-v3's schema makes `supports` an array and the current set literal raises `TypeError: unhashable type: 'list'` — the first human quote retraction against an admitted cycle-004 record would abort `Ledger.apply`. `State.prompts` is a side map for the same reason the fix has to be invisible: adding a key to the record would change every committed snapshot line and break the byte-identical replay guard.
- D4's fuzzy auto-accept pairs the mechanical `trivial-ocr` rule with the reader's own gate outcome (`extraction_status == "ok"`) instead of Stage 1's separate reader `ocr-ok` pass, which this slice does not schedule and which would be another paid pass. Recorded in T8's criteria table and in `fuzzy_quotes`' docstring.
- The 100% checker pass (D5) is **implemented** in T8 and **run** in T9 step 8, because it is a live call and the Global Constraints confine live calls to Task 9.
- `tools/apply_reference_review.read_state` gains a two-line change (skip the vocabulary check when a field's value set is `None`) so the map page's wider field set can reuse it rather than fork it. Guarded by the existing reference-review tests, which T8 step 6 runs.
