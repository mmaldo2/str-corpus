# Stage 3B Slice 1 — Subscription Reader, Codebook v3, Reference v2, Remeasurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the reader on the user's Claude subscription through the Claude Code CLI, repair the three measurement defects the polarity diagnosis found (quote-gate erasure over formatting, relevance leaking into polarity, undefined `mixed`), harden the kit reference with the user's adjudications, and remeasure the five finalists under a pre-registered bar so `reader.model` is pinned on evidence before the cycle-004 map is read.

**Architecture:** The Stage 3A reader keeps its shape — one `Reader` driver over a `Provider` port, the quote gate inside the driver, a content-keyed response cache. This slice adds a fourth adapter (`providers/claude_cli.py`, subscription, unpriced), a request schema module (`schema.py`) whose JSON Schema every `Request` now carries, a v3 codebook, a scoring pass that separates "did not decide" from "decided differently" and gates polarity on relevance, two ledger tools that fold the user's adjudications and a 4-of-5 model consensus into the reference, a rebuilt kit (same 195 cases, patched labels), and a measurement runner that mixes subscription and OpenRouter candidates under two different kinds of budget.

**Tech Stack:** Python 3.12, `.venv/Scripts/python`. SQLite, httpx (OpenRouter), subprocess (Claude CLI v2.1.258, Codex CLI), rapidfuzz via `corpus_engine.verification`, PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-05-stage-3b-slice-1-subscription-reader-design.md` (binding; authority on conflicts is that spec, then ADR-0007 amendment 2026-09-05, ADR-0004, CONTEXT.md).

## Global Constraints

Copied from spec section 11, plus this slice's operational rules. Every task's requirements implicitly include this section.

- LF line endings, UTF-8 without BOM, one trailing newline on every file written (write bytes explicitly; never PowerShell `Set-Content`).
- Never commit `.env`, `data/db/`, `data/raw/`, `data/reader/cache/`, `runs/*/batches|extractions`.
- **No paid request outside `tools/measure_reader.py`.**
- The OpenRouter ceiling is enforced before every paid request.
- Subscription calls never carry an API key: `ANTHROPIC_API_KEY` is removed from the subprocess environment of every `claude -p` call.
- `data/reader/kit-v1/**` files are never edited (they are the provenance of measurement v1).
- **Never run `tools/measure_reader.py` in a paid mode from a task other than Task 9.** Tasks 1–8 may run it only with `--annotate-only` (offline, no request, no spend) or not at all. Task 9 is the only task that spends.
- **The OpenRouter ceiling for this slice is $15 total** (D5: kit reads for three OpenRouter candidates plus the winner's stability and batch-size pair if the winner is an OpenRouter model). The subscription has no dollar budget; its ceilings are units and wall-clock.
- Python 3.12; tests are `.venv/Scripts/python -m pytest -q` from `C:\Users\marcu\Desktop\Str-corpus`, baseline **208 passed, 1 xfailed**. A task is done when the whole suite is green, not just its own file.
- Branch `refactor/stage-3b`. Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## File Structure

```
corpus_engine/reader/
  schema.py                       NEW  record_schema(codebook) -> dict; schema_sha(schema) -> str; value vocabularies
  model.py                        MOD  Response.raw; Plan.json_schema; Plan.resume_tool; effort_of(pin)
  cache.py                        MOD  key() widened (schema sha, max_tokens, effort); key_v1() kept for the 3A cache
  parse.py                        MOD  accepts {"records": [...]} as well as a bare array
  driver.py                       MOD  Request carries plan.json_schema; widened cache key; required store_norm_version;
                                       broad catch in the split loop; resume_command from plan.resume_tool
  measure.py                      MOD  scoring v2 (decided_rate / agreement_decided / relevance gating / exclusions),
                                       select_reader v2 (D4), excluded_fields(), accepted_full
  providers/claude_cli.py         NEW  ClaudeCliProvider (subscription transport)
  providers/__init__.py           MOD  export ClaudeCliProvider
domains/str-right-to-let/
  codebooks/mapper-v3.md          NEW  schema_version 3; mixed defined; supports rule explicit
  domain.yaml                     MOD  reader.codebook, kit_path, kit_sha256, stability_sample, candidates, families, model
tools/
  apply_reference_review.py       NEW  saved review page -> ledger patches (reviewer basis)
  consensus_reference.py          NEW  4-of-5 who-was-letting consensus -> machine-basis patches + second review page
  build_reader_kit.py             MOD  --case-ids-from / --out; excluded_fields per case; kit v2
  measure_reader.py               MOD  provider per candidate; subscription budget; $15 OpenRouter ceiling;
                                       measurement-v2; dry-run mode
tests/
  test_reader_schema.py           NEW  schema shape, both parse shapes, cache-key composition, planner wiring
  test_reader_claude_cli.py       NEW  flags, env, envelope, errors, throttle schedule
  test_reader_codebook_v3.py      NEW  mapper-v3 content + render golden
  test_reader_measure.py          MOD  scoring v2 + selection v2
  test_apply_reference_review.py  NEW  saved-page state -> patches
  test_consensus_reference.py     NEW  consensus math + contested-doc shape
  test_build_reader_kit.py        NEW  reference rows, exclusions, batch determinism
  test_reader_driver.py           MOD  required store_norm_version, split-loop defect, resume_tool
  test_measure_reader_tool.py     MOD  provider/budget selection, ceiling guard
data/reader/kit-v2/{kit.json,batches/,sample-50.json}       generated (Task 7)
data/reader/review/reference-v2/contested-who.json          generated (Task 6)
data/reader/measurement-v2/manifest.json                    generated (Task 9)
reports/review-queue-reference-v2.{html,md}                 generated (Task 6)
reports/reader-measurement-v2.md                            written (Task 9)
docs/adr/0004-extraction-schema-v2.md                       amended (Task 3)
docs/adr/0007-*.md                                          result note (Task 9)
CONTEXT.md                                                  polarity entry (Task 3)
reports/handoff-cycle-004.md                                item 7 (Task 9)
```

**Task order.** T1–T4 are engine work and have no external input. **T5, T6 and T7 can start as soon as the user's saved review page exists** — T5's real input arrives from the user (the saved `reports/review-queue-reference-v1.html` republished with decisions embedded); the task's *tests* run against a fixture built in-test, and only its final live step waits for the file. T8 is a residual cleanup that can run at any time after T1. T9 runs last and is the only task that spends.

---

### Task 1: Request schema, both parse shapes, widened cache key

**Files:**
- Create: `corpus_engine/reader/schema.py`, `tests/test_reader_schema.py`
- Modify: `corpus_engine/reader/model.py`, `corpus_engine/reader/cache.py`, `corpus_engine/reader/parse.py`, `corpus_engine/reader/driver.py`, `tools/measure_reader.py` (two offline helpers switch to `key_v1`)

**Interfaces:**
- Consumes: `Codebook(id, path, text, sha, judged_fields, validated_norm_version)` from `corpus_engine.reader.codebook`; `ModelPin`, `Request`, `Response`, `Plan`, `Unit` from `corpus_engine.reader.model`.
- Produces (later tasks consume exactly these names):
  - `corpus_engine.reader.schema.record_schema(codebook: Codebook) -> dict` — the JSON Schema for `{"records": [Record, ...]}`.
  - `corpus_engine.reader.schema.schema_sha(schema: dict | None) -> str` — `sha256(json.dumps(schema, sort_keys=True))`, `""` for `None`.
  - `corpus_engine.reader.schema.POLARITY_VALUES / WHO_VALUES / DURATION_VALUES / CHARACTERIZATION_VALUES / UNDER_THIRTY_VALUES / OWNER_FREEDOM_VALUES / RESTRICTION_VALUES / REQUIRED_RECORD_FIELDS` (lists).
  - `corpus_engine.reader.model.effort_of(pin: ModelPin) -> str` — reads `extra["reasoning"]["effort"]` (OpenRouter pins) or `extra["effort"]` (CLI pins), `""` if neither.
  - `Response(text, input_tokens, output_tokens, cost_usd, provider_reported, finish_reason, tool_version=None, raw: Mapping = {})` — new last field `raw`, default empty dict.
  - `Plan(kind, units, codebook_id, pin, budget, worker, checker_pin=None, sample_pct=10, json_schema: dict | None = None, resume_tool: str = "")` — `resume_tool` is added here (unused until Task 8) so `Plan` is touched once.
  - `plan_batch_extraction(batches, codebook_id, pin, budget, *, worker, checker_pin=None, sample_pct=10, json_schema=None, resume_tool="")`; `plan_reread(records, codebook_id, pin, budget, *, worker, json_schema=None)`; `plan_judgment(case_ids, question, codebook_id, pin, budget, *, worker, json_schema=None)`.
  - `ResponseCache.key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str, *, schema_sha: str = "", max_tokens: int = 0, effort: str = "") -> str` — `sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}|{schema_sha}|{max_tokens}|{effort}")`.
  - `ResponseCache.key_v1(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str` — the frozen Stage 3A composition, for reading the purchased measurement-v1 cache only.
  - `parse_records(text, case_ids, *, required=REQUIRED) -> list[dict] | None` — unchanged signature, now also accepts `{"records": [...]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader_schema.py
"""The schema every Request now carries, the two response shapes parse accepts, and the
cache key that decides what a new read may reuse. The key is widened here, while every
read is being re-bought anyway: the 3A key hashed only the pin label, so two runs that
differed in effort, max_tokens or schema collided (measurement-v1 manifest, LIMITATION)."""
import hashlib, json, shutil

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader, plan_batch_extraction
from corpus_engine.reader.model import Budget, ModelPin, Response, Unit, effort_of
from corpus_engine.reader.parse import parse_records
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.schema import record_schema, schema_sha
from corpus_engine.reader.sources import StoreCaseSource

CLI_PIN = ModelPin("claude-cli/claude-sonnet-5", "anthropic", "claude-cli", None,
                   {"effort": "low", "cli_model": "claude-sonnet-5"})


def test_record_schema_pins_the_vocabularies_and_the_supports_rule():
    cb = load_codebook(load_domain(), "mapper-v2")
    s = record_schema(cb)
    assert s["required"] == ["records"] and s["properties"]["records"]["type"] == "array"
    rec = s["properties"]["records"]["items"]
    assert rec["required"] == ["case_id", "relevant", "polarity", "quotes"]
    assert rec["properties"]["polarity"]["enum"] == ["favorable", "adverse", "mixed", None]
    assert "irrelevant" not in rec["properties"]["polarity"]["enum"]          # D2: not a polarity value
    assert rec["properties"]["who_was_letting"]["enum"] == [
        "householder", "commercial_operator", "non_resident_owner", "unclear", None]
    q = rec["properties"]["quotes"]["items"]
    assert q["required"] == ["text", "supports"]
    assert q["properties"]["supports"]["type"] == "array"
    assert set(q["properties"]["supports"]["items"]["enum"]) == set(cb.judged_fields) | {"relevant"}
    # a relevant record must carry at least one quote; an irrelevant one need not
    assert rec["if"] == {"properties": {"relevant": {"const": True}}, "required": ["relevant"]}
    assert rec["then"] == {"properties": {"quotes": {"minItems": 1}}}
    assert schema_sha(s) == hashlib.sha256(json.dumps(s, sort_keys=True).encode("utf-8")).hexdigest()
    assert schema_sha(None) == ""


def test_parse_accepts_the_wrapped_object_and_the_bare_array():
    recs = [{"case_id": 1, "relevant": True, "polarity": "favorable", "quotes": []}]
    assert parse_records(json.dumps({"records": recs}), [1]) == recs
    assert parse_records(json.dumps(recs), [1]) == recs
    assert parse_records("```json\n" + json.dumps({"records": recs}) + "\n```", [1]) == recs
    assert parse_records("here you go: " + json.dumps({"records": recs}), [1]) == recs
    assert parse_records(json.dumps({"records": recs}), [1, 2]) is None       # coverage still required
    assert parse_records(json.dumps({"other": recs}), [1]) is None


def test_cache_key_composition_is_pinned():
    unit = Unit("u1", (2, 1), {})
    sha = schema_sha({"type": "object"})
    got = ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=64000, effort="low")
    want = hashlib.sha256(
        f"CB|claude-cli/claude-sonnet-5@claude-cli:-|u1|1,2|PROMPT|{sha}|64000|low".encode("utf-8")).hexdigest()
    assert got == want
    for other in (ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=64000, effort="high"),
                  ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha="", max_tokens=64000, effort="low"),
                  ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=16000, effort="low")):
        assert other != got
    # the 3A composition is kept verbatim so the purchased v1 cache stays addressable,
    # and a v2 key never collides with it
    v1 = ResponseCache.key_v1("CB", CLI_PIN, unit, "PROMPT")
    assert v1 == hashlib.sha256(
        "CB|claude-cli/claude-sonnet-5@claude-cli:-|u1|1,2|PROMPT".encode("utf-8")).hexdigest()
    assert v1 != got


def test_effort_of_reads_both_pin_shapes():
    assert effort_of(ModelPin("m", "f", extra={"reasoning": {"effort": "low"}})) == "low"
    assert effort_of(CLI_PIN) == "low"
    assert effort_of(ModelPin("m", "f")) == ""


def test_response_carries_a_raw_envelope_slot_and_defaults_it_empty():
    r = Response("t", 1, 2, None, {}, "stop")
    assert r.raw == {}
    assert Response("t", 1, 2, None, {}, "stop", None, {"list_cost_usd": 0.42}).raw["list_cost_usd"] == 0.42


def test_the_plan_carries_the_schema_and_every_request_sends_it(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    cb = load_codebook(dom, "mapper-v1")
    batch = json.loads(sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01")
                              .glob("batch-*.json"))[0].read_text(encoding="utf-8"))
    schema = record_schema(cb)
    plan = plan_batch_extraction([batch], "mapper-v1", ModelPin("m", "f"), Budget(max_usd=1.0),
                                 worker="claude", json_schema=schema)
    assert plan.json_schema is schema and plan.resume_tool == ""
    seen = []

    def answer(req):
        seen.append(req.json_schema)
        return json.dumps({"records": [{"case_id": c, "relevant": False, "polarity": None, "quotes": []}
                                       for c in plan.units[0].case_ids]})

    out = Reader(ScriptedProvider(answer), StoreCaseSource(conn), log=lambda *_: None, domain=dom,
                 store_norm_version="v1").read(plan)
    assert seen == [schema] and out.stop.kind == "done"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'corpus_engine.reader.schema'`.

- [ ] **Step 3: Write `corpus_engine/reader/schema.py`**

```python
"""The JSON Schema every reader Request carries (spec section 4).

OpenRouter sends it as `response_format.json_schema`, the Claude CLI as `--json-schema`.
A schema-valid response can still fail the quote gate (a quote that is not verbatim);
what it can no longer do is fill a judged field and name that field in no quote's
`supports`, which is the silent erasure the 2026-09-05 polarity diagnosis found.

`required` is the four fields `parse.REQUIRED` demands, not the two the spec names as the
minimum: `parse_records` rejects a response whose records omit `polarity` or `quotes`, and
a schema that permitted the omission would buy a split retry for a record the model was
entitled to send. Both are nullable/empty for an irrelevant record, so nothing is forced.
"""
from __future__ import annotations
import hashlib, json
from corpus_engine.reader.codebook import Codebook

POLARITY_VALUES = ["favorable", "adverse", "mixed", None]
WHO_VALUES = ["householder", "commercial_operator", "non_resident_owner", "unclear", None]
DURATION_VALUES = ["nights", "weeks", "months", "unclear", None]
CHARACTERIZATION_VALUES = ["lease", "license", "lodging", "innkeeping", "other", None]
UNDER_THIRTY_VALUES = ["yes", "no", "unclear", None]
OWNER_FREEDOM_VALUES = ["incident_of_ownership", "regulable_privilege", "commercial_use",
                        "not_addressed", None]
RESTRICTION_VALUES = ["licensing", "zoning", "nuisance", "tenant_protection", "tax", "other", None]
REQUIRED_RECORD_FIELDS = ["case_id", "relevant", "polarity", "quotes"]


def record_schema(codebook: Codebook) -> dict:
    """The schema for `{"records": [Record, ...]}` under `codebook`'s judged fields."""
    supports = list(codebook.judged_fields) + ["relevant"]
    record = {
        "type": "object",
        "additionalProperties": True,          # a model may carry extra fields; we ignore them
        "required": list(REQUIRED_RECORD_FIELDS),
        "properties": {
            "case_id": {"type": ["integer", "string"]},
            "schema_version": {"type": ["integer", "null"]},
            "cite": {"type": ["string", "null"]},
            "court": {"type": ["string", "null"]},
            "jurisdiction": {"type": ["string", "null"]},
            "year": {"type": ["integer", "null"]},
            "relevant": {"type": "boolean"},
            "relevance_score": {"type": ["number", "null"]},
            "polarity": {"enum": list(POLARITY_VALUES)},
            "who_was_letting": {"enum": list(WHO_VALUES)},
            "duration_of_occupancy": {"enum": list(DURATION_VALUES)},
            "characterization": {"enum": list(CHARACTERIZATION_VALUES)},
            "under_thirty_days": {"enum": list(UNDER_THIRTY_VALUES)},
            "owner_freedom_characterization": {"enum": list(OWNER_FREEDOM_VALUES)},
            "restriction_nature": {"enum": list(RESTRICTION_VALUES)},
            "holding_summary": {"type": ["string", "null"]},
            "doctrinal_concepts": {"type": "array", "items": {"type": "string"}},
            "new_terms_observed": {"type": "array", "items": {"type": "string"}},
            "worker": {"type": ["string", "null"]},
            "batch_id": {"type": ["string", "null"]},
            "notes": {"type": ["string", "null"]},
            "quotes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["text", "supports"],
                    "properties": {
                        "text": {"type": "string"},
                        "supports": {"type": "array", "minItems": 1,
                                     "items": {"enum": list(supports)}},
                    },
                },
            },
        },
        "if": {"properties": {"relevant": {"const": True}}, "required": ["relevant"]},
        "then": {"properties": {"quotes": {"minItems": 1}}},
    }
    return {"type": "object", "additionalProperties": False, "required": ["records"],
            "properties": {"records": {"type": "array", "items": record}}}


def schema_sha(schema: dict | None) -> str:
    if not schema:
        return ""
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Widen the cache key and keep the 3A one**

In `corpus_engine/reader/cache.py`, replace the `key` staticmethod with these two:

```python
    @staticmethod
    def key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str, *, schema_sha: str = "",
            max_tokens: int = 0, effort: str = "") -> str:
        """What a cached response is allowed to answer for (spec section 4).

        3A hashed only `codebook_sha|pin.label|unit.id|case ids|prompt`, so two runs that
        differed only in reasoning effort, max_tokens or the attached schema collided - the
        limitation recorded in the measurement-v1 manifest. Slice 1 re-buys every read, so
        the key is widened now; measurement-v1's cache stays on disk for provenance and is
        addressed only by `key_v1`."""
        ids = ",".join(map(str, sorted(unit.case_ids)))
        parts = f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}|{schema_sha}|{max_tokens}|{effort}"
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()

    @staticmethod
    def key_v1(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str:
        """The frozen Stage 3A composition. Offline tools (manifest annotation, the
        who-was-letting consensus) address the purchased measurement-v1 cache with it.
        Never used for a new read."""
        ids = ",".join(map(str, sorted(unit.case_ids)))
        return hashlib.sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}".encode("utf-8")).hexdigest()
```

In `tools/measure_reader.py`, the two offline helpers must keep addressing the v1 cache — change `ResponseCache.key(` to `ResponseCache.key_v1(` in **both** places:
- `keys_for()`: `k = ResponseCache.key_v1(cb.sha, pin, u, prompt)`
- `accepted_from_cache()`'s inner `cached()`: `p = cache.dir / f"{ResponseCache.key_v1(cb.sha, pin, u, render_unit(cb, u, texts, 'reader'))}.json"`

- [ ] **Step 5: Add `raw` to `Response`, `json_schema`/`resume_tool` to `Plan`, and `effort_of`**

In `corpus_engine/reader/model.py`:

```python
@dataclass(frozen=True)
class Response:
    text: str; input_tokens: int; output_tokens: int; cost_usd: float | None
    provider_reported: Mapping; finish_reason: str; tool_version: str | None = None
    # Whatever else the transport reported that no other field has a home for. The
    # subscription CLI puts `total_cost_usd` here as `list_cost_usd`: it is what the same
    # call would have cost on the API, not a charge, so it must never reach `cost_usd`
    # (that would price a subscription candidate and let it win a cost comparison).
    raw: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    kind: str; units: tuple[Unit, ...]; codebook_id: str; pin: ModelPin; budget: Budget; worker: str
    checker_pin: ModelPin | None = None; sample_pct: int = 10
    json_schema: dict | None = None
    # The tool that built this plan, so `resume_command` can name a program that exists
    # (Task 8). Empty means "no runner"; the manifest note says so.
    resume_tool: str = ""


def effort_of(pin: ModelPin) -> str:
    """The reasoning effort a pin asks for, whichever spelling it uses: OpenRouter pins
    carry `extra["reasoning"]["effort"]`, CLI pins carry `extra["effort"]`."""
    extra = pin.extra or {}
    reasoning = extra.get("reasoning") or {}
    return str(reasoning.get("effort") or extra.get("effort") or "")
```

- [ ] **Step 6: Accept both response shapes in `parse.py`**

```python
def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        starts = [i for i in (t.find("["), t.find("{")) if i >= 0]
        t = t[min(starts):] if starts else t
    return t.strip()


def _wrapped(t: str) -> list | None:
    """`{"records": [...]}` - the shape the v3 schema asks for. Scanned for the same way a
    bare array is, because a model may still prefix it with a sentence."""
    dec = json.JSONDecoder()
    for i in range(len(t)):
        if t[i] != "{":
            continue
        try:
            obj, _end = dec.raw_decode(t, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("records"), list):
            return obj["records"]
    return None


def parse_records(text: str, case_ids: Sequence[int], *, required=REQUIRED) -> list[dict] | None:
    t = strip_fences(text)
    dec = json.JSONDecoder()
    candidates: list[list] = []
    wrapped = _wrapped(t)
    if wrapped is not None:
        candidates.append(wrapped)
    for i in range(len(t)):
        if t[i] == "[":
            try:
                recs, _end = dec.raw_decode(t, i)
            except json.JSONDecodeError:
                continue
            if isinstance(recs, list):
                candidates.append(recs)
    for recs in candidates:
        if not all(isinstance(r, dict) for r in recs):
            continue
        if not {int(c) for c in case_ids} <= {_as_case_id(r.get("case_id")) for r in recs}:
            continue
        if not all(set(required) <= set(r) for r in recs):
            continue
        return recs
    return None
```

- [ ] **Step 7: Attach the schema in the planners and send it from the driver**

In `corpus_engine/reader/driver.py`:

```python
def plan_batch_extraction(batches, codebook_id: str, pin: ModelPin, budget: Budget, *, worker: str,
                          checker_pin: ModelPin | None = None, sample_pct: int = 10,
                          json_schema: dict | None = None, resume_tool: str = "") -> Plan:
    units = tuple(Unit(b["batch_id"], tuple(int(c["case_id"]) for c in b["cases"]),
                       {"batch_id": b["batch_id"], "era_partition": b["era_partition"], "jurisdiction": b["jurisdiction"],
                        "signals": {int(c["case_id"]): c.get("signals", []) for c in b["cases"]}}) for b in batches)
    return Plan("batch_extraction", units, codebook_id, pin, budget, worker, checker_pin, sample_pct,
                json_schema, resume_tool)


def plan_reread(records, codebook_id, pin, budget, *, worker, json_schema: dict | None = None) -> Plan:
    units = tuple(Unit(f"reread-{r['case_id']}", (int(r["case_id"]),),
                       {"batch_id": f"reread-{r['case_id']}", "era_partition": r.get("era_partition", "?"),
                        "jurisdiction": r.get("jurisdiction", "?"), "signals": {}}) for r in records)
    return Plan("reread", units, codebook_id, pin, budget, worker, json_schema=json_schema)


def plan_judgment(case_ids, question: str, codebook_id, pin, budget, *, worker,
                  json_schema: dict | None = None) -> Plan:
    units = tuple(Unit(f"judge-{c}", (int(c),), {"batch_id": f"judge-{c}", "era_partition": "?", "jurisdiction": "?",
                                                 "signals": {}, "question": question}) for c in case_ids)
    return Plan("judgment", units, codebook_id, pin, budget, worker, json_schema=json_schema)
```

and in `Reader._ask` (imports at the top of the module: `from corpus_engine.reader.model import ... effort_of` and `from corpus_engine.reader.schema import schema_sha`):

```python
    def _ask(self, plan: Plan, cb: Codebook, unit: Unit, pin: ModelPin, worker: str, provider, state: _ReadState):
        texts = self.cases.fetch(unit.case_ids)
        prompt = render_unit(cb, unit, texts, worker)
        req = Request(pin, prompt, json_schema=plan.json_schema)
        key = (ResponseCache.key(cb.sha, pin, unit, prompt, schema_sha=schema_sha(plan.json_schema),
                                 max_tokens=req.max_tokens, effort=effort_of(pin)) if self.cache else None)
        resp = self.cache.get(key) if key else None; hit = resp is not None
        if resp is None:
            state.check_budget()                       # before any paid request; a cache hit never trips it
            resp = provider.complete(req)
            if key:
                self.cache.put(key, resp)
            state.record_paid(resp)
        return texts, resp, hit
```

- [ ] **Step 8: Run the new test, then the whole suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader_schema.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: 208+ passed, 1 xfailed, 0 failed. (`ResponseCache.get` reads old cache files through `Response(**json.loads(...))`; the new `raw` field has a default, so entries written before this task still load.)

- [ ] **Step 9: Commit**

```bash
git add corpus_engine/reader/schema.py corpus_engine/reader/model.py corpus_engine/reader/cache.py corpus_engine/reader/parse.py corpus_engine/reader/driver.py tools/measure_reader.py tests/test_reader_schema.py
git commit -m "reader: request schema, wrapped-response parsing, cache key widened to schema/max_tokens/effort"
```

---

### Task 2: `ClaudeCliProvider` — the subscription transport

**Files:**
- Create: `corpus_engine/reader/providers/claude_cli.py`, `tests/test_reader_claude_cli.py`
- Modify: `corpus_engine/reader/providers/__init__.py`, `corpus_engine/reader/driver.py` (pre-flight: unpriced providers)

**Interfaces:**
- Consumes: `Request`, `Response`, `ReaderError` (Task 1's `Response.raw`); `preflight(...)` from `corpus_engine.reader.driver`.
- Produces:
  - `corpus_engine.reader.providers.claude_cli.ClaudeCliProvider(cli_model: str, *, runner=subprocess.run, timeout: int = 1500, exe: str = "claude", effort: str = "low", system_default: str = DEFAULT_SYSTEM, sleep=time.sleep, delays: tuple[int, ...] = THROTTLE_DELAYS)` with class attribute `name = "claude-cli"`, methods `version() -> str | None`, `is_available() -> bool`, `argv(req: Request) -> list[str]`, `env() -> dict`, `complete(req: Request) -> Response`.
  - Module constants `DEFAULT_SYSTEM`, `STDIN_LIMIT_BYTES = 10 * 1024 * 1024`, `PROMPT_LIMIT_BYTES = 9 * 1024 * 1024`, `THROTTLE_DELAYS = (60, 300, 900, 1800, 3600)`.
  - `corpus_engine.reader.driver.UNPRICED_PROVIDERS = ("codex-cli", "claude-cli")`.
  - Exported from `corpus_engine.reader.providers` as `ClaudeCliProvider`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader_claude_cli.py
"""The subscription transport. Every flag in the invocation is load-bearing: the probe on
2026-09-05 measured ~750 input tokens of overhead with them against ~137,000 for a bare
`claude -p`, so each one is asserted here and a silent removal fails the suite. The
environment must not carry ANTHROPIC_API_KEY: with a key present the call bills the API,
which is exactly the route ADR-0007's amendment moved away from."""
import json
import subprocess

import pytest

from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import plan_batch_extraction, preflight
from corpus_engine.reader.model import Budget, ModelPin, ReaderError, Request
from corpus_engine.reader.providers import claude_cli as cc
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider

PIN = ModelPin("claude-cli/claude-sonnet-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-sonnet-5"})
SCHEMA = {"type": "object", "properties": {"records": {"type": "array"}}}
VERSION = "2.1.258 (Claude Code)"


class P:
    """A fake CompletedProcess."""
    def __init__(self, stdout, code=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, code, stderr


def envelope(**kw) -> str:
    body = {"result": "[]", "is_error": False, "session_id": "sess-1", "num_turns": 1,
            "stop_reason": "end_turn", "total_cost_usd": 0.42,
            "usage": {"input_tokens": 700, "cache_creation_input_tokens": 40,
                      "cache_read_input_tokens": 14, "output_tokens": 120}}
    body.update(kw)
    return json.dumps(body)


def runner_for(responses, calls):
    def runner(cmd, **kw):
        if cmd[1] == "--version":
            return P(VERSION + "\n")
        calls.append((cmd, kw))
        out = responses.pop(0)
        return out if isinstance(out, P) else P(out)
    return runner


def test_every_flag_is_sent_and_the_api_key_is_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-be-passed")
    monkeypatch.setenv("STR_CORPUS_SENTINEL", "kept")
    calls = []
    p = ClaudeCliProvider("claude-sonnet-5", runner=runner_for([envelope()], calls), exe="claude")
    r = p.complete(Request(PIN, "the prompt", json_schema=SCHEMA))
    cmd, kw = calls[0]
    assert cmd[1:] == ["-p", "--model", "claude-sonnet-5", "--output-format", "json",
                       "--effort", "low", "--tools", "",
                       "--system-prompt", cc.DEFAULT_SYSTEM,
                       "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--setting-sources", "", "--exclude-dynamic-system-prompt-sections",
                       "--json-schema", json.dumps(SCHEMA, sort_keys=True)]
    assert kw["input"] == "the prompt" and kw["timeout"] == 1500 and kw["encoding"] == "utf-8"
    assert kw["capture_output"] is True and kw["text"] is True
    assert "ANTHROPIC_API_KEY" not in kw["env"] and kw["env"]["STR_CORPUS_SENTINEL"] == "kept"
    # usage is the sum of the three input counters; the subscription has no marginal price
    assert r.input_tokens == 754 and r.output_tokens == 120 and r.cost_usd is None
    assert r.raw["list_cost_usd"] == 0.42
    assert r.provider_reported == {"provider": "claude-cli", "cli_model": "claude-sonnet-5",
                                   "effort": "low", "claude_version": VERSION, "session_id": "sess-1"}
    assert r.tool_version == VERSION and r.finish_reason == "end_turn" and r.text == "[]"


def test_structured_output_is_the_response_text_when_present():
    so = {"records": [{"case_id": 1, "relevant": False, "polarity": None, "quotes": []}]}
    p = ClaudeCliProvider("claude-opus-5", runner=runner_for([envelope(structured_output=so, result="prose")], []))
    r = p.complete(Request(PIN, "u", json_schema=SCHEMA))
    assert r.text == json.dumps(so, sort_keys=True) and json.loads(r.text) == so


def test_request_system_overrides_the_default_and_no_schema_means_no_flag():
    calls = []
    p = ClaudeCliProvider("claude-sonnet-5", runner=runner_for([envelope()], calls))
    p.complete(Request(PIN, "u", system="CODEBOOK SYSTEM LINE"))
    cmd = calls[0][0]
    assert cmd[cmd.index("--system-prompt") + 1] == "CODEBOOK SYSTEM LINE"
    assert "--json-schema" not in cmd


def test_the_windows_cmd_shim_is_resolved_with_which(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda name: r"C:\npm\claude.cmd" if name == "claude" else None)
    calls = []
    ClaudeCliProvider("m", runner=runner_for([envelope()], calls), exe="claude").complete(Request(PIN, "u"))
    assert calls[0][0][0] == r"C:\npm\claude.cmd"
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    assert ClaudeCliProvider("m", exe="claude")._exe() == "claude"


def test_error_envelopes_and_unparseable_output_raise():
    p = ClaudeCliProvider("m", runner=runner_for([P(envelope(is_error=True, result="bad request",
                                                             api_error_status=400))], []))
    with pytest.raises(ReaderError, match="api_error_status=400"):
        p.complete(Request(PIN, "u"))
    p2 = ClaudeCliProvider("m", runner=runner_for([P("not json", 1, "exploded")], []))
    with pytest.raises(ReaderError, match="unparseable envelope"):
        p2.complete(Request(PIN, "u"))
    p3 = ClaudeCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("claude")))
    assert not p3.is_available()
    with pytest.raises(ReaderError, match="claude cli unavailable"):
        p3.complete(Request(PIN, "u"))
    def slow(cmd, **kw):
        if cmd[1] == "--version":
            return P(VERSION)
        raise subprocess.TimeoutExpired(cmd, 1500)
    with pytest.raises(ReaderError, match="timed out"):
        ClaudeCliProvider("m", runner=slow).complete(Request(PIN, "u"))


def test_throttling_waits_the_pinned_schedule_and_then_gives_up():
    slept, calls = [], []
    responses = [P(envelope(is_error=True, api_error_status=429, result="usage limit reached")) for _ in range(6)]
    p = ClaudeCliProvider("m", runner=runner_for(responses, calls), sleep=slept.append)
    with pytest.raises(ReaderError, match="subscription window exhausted"):
        p.complete(Request(PIN, "u"))
    assert slept == [60, 300, 900, 1800, 3600] and len(calls) == 6


def test_a_throttled_call_that_later_succeeds_returns_its_response():
    slept, calls = [], []
    responses = [P(envelope(is_error=True, api_error_status=529, result="overloaded, please retry")), P(envelope())]
    p = ClaudeCliProvider("m", runner=runner_for(responses, calls), sleep=slept.append)
    assert p.complete(Request(PIN, "u")).text == "[]"
    assert slept == [60] and len(calls) == 2
    # throttling is also recognised from the message when no status is set
    slept2, calls2 = [], []
    p2 = ClaudeCliProvider("m", runner=runner_for([P(envelope(is_error=True, result="5-hour usage limit reached")),
                                                   P(envelope())], calls2), sleep=slept2.append)
    assert p2.complete(Request(PIN, "u")).text == "[]" and slept2 == [60]


def test_a_prompt_over_the_stdin_cap_raises_before_any_call():
    calls = []
    p = ClaudeCliProvider("m", runner=runner_for([], calls))
    with pytest.raises(ReaderError, match="stdin cap"):
        p.complete(Request(PIN, "x" * (cc.PROMPT_LIMIT_BYTES + 1)))
    assert calls == []


def test_preflight_refuses_a_dollar_budget_on_the_unpriced_subscription_provider():
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    plan = plan_batch_extraction([], "mapper-v1", PIN, Budget(max_usd=5.0), worker="reader")
    stop = preflight(plan, cb, None, ClaudeCliProvider("claude-sonnet-5"), None,
                     store_norm_version="v1", families={})
    assert stop.kind == "preflight:budget_unpriced" and "claude-cli" in stop.detail
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_claude_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'corpus_engine.reader.providers.claude_cli'`.

- [ ] **Step 3: Write the provider**

```python
# corpus_engine/reader/providers/claude_cli.py
"""Reader transport: the Claude Code CLI on the user's subscription (ADR-0007 amendment
2026-09-05, decision D1).

Never `shell=True` (the legacy pipeline/run_map.py call_claude used it on Windows and so
handed the prompt to cmd.exe's quoting rules); the executable is resolved with
`shutil.which` instead, which finds the `.cmd` shim npm installs on Windows.

Every flag is load-bearing. Measured 2026-09-05: this invocation costs ~750 input tokens
of overhead per call, against ~137,000 for a bare `claude -p` (tools, MCP config, dynamic
system-prompt sections and the user's settings all arrive as context otherwise). Each flag
is asserted in tests/test_reader_claude_cli.py, so removing one fails the suite."""
from __future__ import annotations
import json, os, re, shutil, subprocess, time
from corpus_engine.reader.model import ReaderError, Request, Response

DEFAULT_SYSTEM = ("You are an extraction worker in a legal-history pipeline. Follow the codebook "
                  "in the message exactly and return only the JSON it asks for.")
# The CLI reads the prompt from stdin and caps it at 10 MB. Refuse at 9 MB rather than let
# a unit be truncated mid-case: a truncated opinion still parses and still gates, so the
# damage would be silent.
STDIN_LIMIT_BYTES = 10 * 1024 * 1024
PROMPT_LIMIT_BYTES = 9 * 1024 * 1024
# The subscription's own refusal is a wait, not a failure: the window reopens. A unit that
# still cannot be bought after the last wait is failed and the driver moves on; the next
# run resumes it from the cache for free.
THROTTLE_DELAYS = (60, 300, 900, 1800, 3600)
THROTTLE_STATUS = ("429", "529")
THROTTLE_TEXT = re.compile(r"usage limit|rate.?limit|too many requests|overloaded|"
                           r"capacity|try again later", re.IGNORECASE)


def _throttled(status: str, blob: str) -> bool:
    return status in THROTTLE_STATUS or bool(THROTTLE_TEXT.search(blob or ""))


class ClaudeCliProvider:
    name = "claude-cli"

    def __init__(self, cli_model: str, *, runner=subprocess.run, timeout: int = 1500,
                 exe: str = "claude", effort: str = "low", system_default: str = DEFAULT_SYSTEM,
                 sleep=time.sleep, delays: tuple[int, ...] = THROTTLE_DELAYS):
        self.cli_model, self.runner, self.timeout, self.exe = cli_model, runner, timeout, exe
        self.effort, self.system_default = effort, system_default
        self.sleep, self.delays = sleep, tuple(delays)
        self._version: str | None = None

    def _exe(self) -> str:
        return shutil.which(self.exe) or self.exe

    def version(self) -> str | None:
        if self._version is None:
            try:
                p = self.runner([self._exe(), "--version"], capture_output=True, text=True, timeout=60)
                self._version = (p.stdout or "").strip() or None
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                self._version = None
        return self._version

    def is_available(self) -> bool:
        return self.version() is not None

    def argv(self, req: Request) -> list[str]:
        cmd = [self._exe(), "-p", "--model", self.cli_model, "--output-format", "json",
               "--effort", self.effort, "--tools", "",
               "--system-prompt", req.system or self.system_default,
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--setting-sources", "", "--exclude-dynamic-system-prompt-sections"]
        if req.json_schema:
            cmd += ["--json-schema", json.dumps(req.json_schema, sort_keys=True)]
        return cmd

    @staticmethod
    def env() -> dict:
        """The subscription pays for this call. With ANTHROPIC_API_KEY visible the CLI bills
        the API instead - the route ADR-0007's amendment deliberately left."""
        return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    def complete(self, req: Request) -> Response:
        size = len(req.user.encode("utf-8"))
        if size > PROMPT_LIMIT_BYTES:
            raise ReaderError(f"prompt is {size} bytes; the CLI stdin cap is {STDIN_LIMIT_BYTES} "
                              f"and this unit must be split before it is asked")
        last = ""
        for attempt in range(len(self.delays) + 1):
            resp, last, throttled = self._attempt(req)
            if resp is not None:
                return resp
            if not throttled:
                raise ReaderError(last)
            if attempt < len(self.delays):
                self.sleep(self.delays[attempt])
        raise ReaderError(f"subscription window exhausted after {len(self.delays)} waits; last {last}")

    def _attempt(self, req: Request) -> tuple[Response | None, str, bool]:
        try:
            p = self.runner(self.argv(req), input=req.user, capture_output=True, text=True,
                            timeout=self.timeout, encoding="utf-8", env=self.env())
        except (FileNotFoundError, OSError) as exc:
            return None, f"claude cli unavailable: {exc!r}", False
        except subprocess.TimeoutExpired:
            return None, f"claude cli timed out after {self.timeout}s", False
        out, err = p.stdout or "", p.stderr or ""
        try:
            env = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            env = None
        if not isinstance(env, dict):
            return (None, f"claude exited {p.returncode} with unparseable envelope: {(out or err)[:300]}",
                    _throttled("", f"{out} {err}"))
        status = str(env.get("api_error_status") or "")
        blob = f"{env.get('result') or ''} {err}"
        if p.returncode != 0 or env.get("is_error") or status:
            return (None, f"claude exited {p.returncode} (api_error_status={status or 'none'}): "
                          f"{str(env.get('result'))[:300]}", _throttled(status, blob))
        structured = env.get("structured_output")
        text = json.dumps(structured, sort_keys=True) if structured is not None else (env.get("result") or "")
        if not text:
            return None, "claude cli produced no result and no structured_output", False
        u = env.get("usage") or {}
        inp = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                               "cache_read_input_tokens"))
        reported = {"provider": self.name, "cli_model": self.cli_model, "effort": self.effort,
                    "claude_version": self.version(), "session_id": env.get("session_id")}
        # cost_usd stays None: `total_cost_usd` is what the same call would have cost on the
        # API, not a charge against anything. It is recorded so the report can say what the
        # subscription saved, and `score_candidate` marks the candidate unpriced.
        raw = {"list_cost_usd": env.get("total_cost_usd"), "num_turns": env.get("num_turns"),
               "session_id": env.get("session_id")}
        return (Response(text, inp, int(u.get("output_tokens") or 0), None, reported,
                         env.get("stop_reason") or "stop", self.version(), raw), "", False)
```

- [ ] **Step 4: Export it and teach pre-flight about unpriced providers**

`corpus_engine/reader/providers/__init__.py`:

```python
from __future__ import annotations
from corpus_engine.reader.providers.cassette import CassetteProvider
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider

__all__ = ["CassetteProvider", "ClaudeCliProvider", "CodexCliProvider", "OpenRouterProvider",
           "ScriptedProvider"]
```

In `corpus_engine/reader/driver.py`, above `preflight`:

```python
# Transports that report no per-call price. A usd budget over one of them is not a budget:
# `_ReadState.spend` would stay at 0.0 for every request and the ceiling would never trip.
UNPRICED_PROVIDERS = ("codex-cli", "claude-cli")
```

and replace the pre-flight check:

```python
    if plan.budget.max_usd is not None and getattr(provider, "name", None) in UNPRICED_PROVIDERS:
        return StopReason("preflight:budget_unpriced",
                          f"{getattr(provider, 'name', '?')} reports no per-call cost; a usd budget "
                          f"cannot be enforced - use max_units / max_wall_seconds")
```

- [ ] **Step 5: Run the test, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader_claude_cli.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/reader/providers/claude_cli.py corpus_engine/reader/providers/__init__.py corpus_engine/reader/driver.py tests/test_reader_claude_cli.py
git commit -m "reader: ClaudeCliProvider - subscription transport with pinned flags, stripped API key, throttle schedule"
```

---
### Task 3: Codebook mapper-v3, CONTEXT.md, ADR-0004 amendment, render golden

**Files:**
- Create: `domains/str-right-to-let/codebooks/mapper-v3.md`, `tests/test_reader_codebook_v3.py`
- Modify: `CONTEXT.md` (Polarity entry), `docs/adr/0004-extraction-schema-v2.md` (amendment paragraph)

**Interfaces:**
- Consumes: `load_codebook(domain, "mapper-v3") -> Codebook`, `render_unit(codebook, unit, texts, worker) -> str`.
- Produces: codebook id `mapper-v3` with `schema_version: 3`, header `<!-- validated_norm_version: v1 -->`, polarity vocabulary `favorable | adverse | mixed | null`, and an array-valued `supports`. Task 7 points `domain.yaml` `reader.codebook` at it; Task 9 measures under it.

**Note on scope:** mapper-v3 is mapper-v2 with the spec's listed changes and one further change the spec's own section 4 forces: v2's requirement 5 told the model to emit "a single JSON array of records", while the v3 schema demands `{"records": [...]}`. Asking for one and validating the other would fail every response, so requirement 5 now asks for the object and says an array is still accepted. Nothing else in v2 is touched.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader_codebook_v3.py
"""mapper-v3 is mapper-v2 with three repairs: `mixed` is defined, `irrelevant` is not a
polarity value, and the support rule says out loud what the gate does to a judged value no
quote names. The render check is the byte-stable part: the prompt the reader sees is the
codebook body followed by exactly the batch text the frozen mapper-v1 goldens contain, so
the codebook is the only thing that changed."""
import json
import shutil

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import Unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.sources import StoreCaseSource


def _body(text: str) -> str:
    """The codebook as render_unit uses it: the metadata comment line is stripped."""
    return text.split("\n", 1)[1] if text.startswith("<!--") else text


def test_mapper_v3_carries_the_v3_vocabulary_and_the_support_rule():
    dom = load_domain()
    v2 = load_codebook(dom, "mapper-v2")
    cb = load_codebook(dom, "mapper-v3")
    assert cb.validated_norm_version == "v1" and cb.sha != v2.sha and len(cb.sha) == 64
    assert '"schema_version": 3' in cb.text
    # D2: mixed is defined, irrelevant is gone as a polarity value
    assert ("Mixed means the same opinion both recognizes the owner's freedom to let on one "
            "point and restricts it on another") in cb.text
    assert "An owner who wins on a ground unrelated to letting is not favorable" in cb.text
    assert "`favorable` | `adverse` | `mixed` | `null`" in cb.text
    assert '"irrelevant"' not in cb.text
    # the support rule, with the worked example and the consequence spelled out
    assert '"supports": ["polarity", "characterization"]' in cb.text
    assert "a judged value not named in any quote's supports list will be erased by the verifier" in cb.text
    # who_was_letting vocabulary unchanged from v2
    for value in ("householder", "commercial_operator", "non_resident_owner", "unclear"):
        assert value in cb.text
    # irrelevant records: no polarity, no who, quotes optional
    assert ("`relevant: false`, `polarity: null`, `who_was_letting: null`, no quotes required") in cb.text


def test_render_under_v3_is_the_v3_body_plus_the_frozen_batch_text(tmp_path, fixture_db, repo_root, golden_dir):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    dom = load_domain()
    v1 = load_codebook(dom, "mapper-v1")
    v3 = load_codebook(dom, "mapper-v3")
    src = StoreCaseSource(conn)
    n = 0
    for bf in sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json")):
        batch = json.loads(bf.read_text(encoding="utf-8"))
        unit = Unit(batch["batch_id"], tuple(c["case_id"] for c in batch["cases"]),
                    {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"],
                     "jurisdiction": batch["jurisdiction"],
                     "signals": {c["case_id"]: c["signals"] for c in batch["cases"]}})
        golden = (golden_dir / "prompts/cycle-003-shard-01" / (bf.stem + ".txt")
                  ).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        assert golden.startswith(v1.text)
        want = _body(v3.text) + golden[len(v1.text):]
        assert render_unit(v3, unit, src.fetch(unit.case_ids), "claude") == want, bf.name
        n += 1
    assert n == 5          # only 5 of the ten golden batches are in corpus-tiny.db


def test_context_and_adr_carry_the_mixed_definition(repo_root):
    ctx = (repo_root / "CONTEXT.md").read_text(encoding="utf-8")
    assert "A case the reader finds irrelevant carries no polarity." in ctx
    assert "both are holdings rather than remarks in passing" in ctx
    adr = (repo_root / "docs/adr/0004-extraction-schema-v2.md").read_text(encoding="utf-8")
    assert "## Amendment 2026-09-05" in adr and "mapper-v3" in adr
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_codebook_v3.py -q`
Expected: FAIL — `FileNotFoundError: ...codebooks/mapper-v3.md`.

- [ ] **Step 3: Write `domains/str-right-to-let/codebooks/mapper-v3.md`**

Write these bytes exactly (LF, UTF-8 no BOM, trailing newline):

```markdown
<!-- validated_norm_version: v1 -->
# Mapper prompt — extraction worker (spec §8)

You are an extraction worker in a legal-history pipeline recovering
historical case law on the right to let one's property short-term. You
receive one batch file (JSON) of candidate cases with retrieval provenance
(which selector fired, on what matched text), plus the full opinion text of
each case, fetched with the provided tool/command. You emit one JSON record
per case. You do doctrinal READING, not doctrinal ARGUING — record what the
court said, not what a litigant would wish it said.

## Context

The pipeline hunts two files of authority in pre-1990 American case law:
- FAVORABLE: householders lawfully letting rooms/dwellings for short periods
  for pay; courts treating letting as an ordinary incident of ownership;
  lodger/boarder arrangements enforced or protected.
- ADVERSE: licensing/regulation of lodging or boarding houses sustained
  under the police power; boarding houses treated as commercial intrusions
  or nuisances in residential contexts.
Both matter. Mark polarity honestly; a case can be mixed.

POLARITY IS JUDGED FROM THE PROPERTY OWNER'S RIGHT TO LET — never from the
occupant's interests. A ruling that expands an occupant's or tenant's
rights AGAINST the owner (rent control, eviction protection, "permanent
tenant" status, statutory tenancy, habitability duties) is ADVERSE unless it
also affirms the owner's freedom to let. "Pro-tenant" is not "favorable."
Favorable means the owner's liberty to let, on the owner's terms, was
recognized, protected, or assumed as lawful.

Mixed means the same opinion both recognizes the owner's freedom to let on
one point and restricts it on another, and both are holdings rather than
remarks in passing. If only one side is a holding, follow the holding and
note the tension in the summary. An owner who wins on a ground unrelated to
letting is not favorable; judge only what the court decided about letting.

## Output schema — one record per case, ALL cases in the batch

```json
{
  "case_id": 123456,
  "schema_version": 3,
  "cite": "...", "court": "...", "year": 1897, "jurisdiction": "N.Y.",
  "relevant": true,
  "relevance_score": 0.85,
  "polarity": "favorable",
  "who_was_letting": "householder",
  "duration_of_occupancy": "weeks",
  "characterization": "license",
  "under_thirty_days": "yes",
  "owner_freedom_characterization": "incident_of_ownership",
  "restriction_nature": null,
  "holding_summary": "<= 3 sentences, plain statement of the holding",
  "doctrinal_concepts": ["lodger_status", "license_vs_lease"],
  "new_terms_observed": ["mesne lodger"],
  "quotes": [
    {"text": "verbatim passage copied from the opinion text",
     "supports": ["polarity", "characterization"]}
  ],
  "worker": "claude", "batch_id": "...", "notes": ""
}
```

Field values:
- `relevant`: does the case bear on compensated occupancy of another's
  dwelling/rooms, its legal character, or its regulation? Procedural cases
  that merely mention a boarding house in passing are `false`.
- `polarity`: `favorable` | `adverse` | `mixed` | `null` (see Context).
  A case you mark `relevant: false` carries no polarity: it is `null`.
- `who_was_letting`: `householder` (owner/family letting part of their own
  dwelling) | `commercial_operator` (business: hotel, boarding house run as
  enterprise, multiple properties) | `non_resident_owner` (owner of a single
  dwelling who does not live there) | `unclear`.
- `duration_of_occupancy`: `nights` | `weeks` | `months` | `unclear` —
  the occupancy actually at issue, from the facts.
- `characterization`: how the COURT classified the arrangement:
  `lease` | `license` | `lodging` | `innkeeping` | `other`.
- `doctrinal_concepts`: from ontology.yaml concept ids where applicable.
- `new_terms_observed`: recurring period terms for the practice that are NOT
  in the current lexicon (check the selector provenance you received). This
  feeds the Planner. Empty list if none.
- `under_thirty_days`: `yes` | `no` | `unclear` — whether the occupancy at
  issue was under thirty days.
- `owner_freedom_characterization`: how the court framed the owner's liberty
  to let: `incident_of_ownership` | `regulable_privilege` | `commercial_use`
  | `not_addressed`.
- `restriction_nature` (adverse records only): `licensing` | `zoning` |
  `nuisance` | `tenant_protection` | `tax` | `other` | `null`.

## Hard requirements

1. `quotes[].supports` is an ARRAY of field names. One quote may support
   several fields — a single passage routinely settles both the polarity and
   the characterization — so name every field it supports:
   `"supports": ["polarity", "characterization"]`. Every non-null judged
   field (`characterization`, `polarity`, `holding_summary`,
   `owner_freedom_characterization`, `restriction_nature`,
   `under_thirty_days`) MUST appear in some quote's `supports` array;
   a judged value not named in any quote's supports list will be erased by
   the verifier. No supporting quote -> leave the field null and say why in
   `notes`.
2. `quotes[].text` is copied VERBATIM from the opinion text provided to you
   — no paraphrase, no ellipsis insertions, no cleanup of OCR errors. The
   verifier does exact matching against source text; an "improved" quote is
   a discarded quote.
3. `who_was_letting` and `duration_of_occupancy` are first-class: the
   level-of-generality argument runs on them. Dig for them in the facts;
   use `unclear` only after actually looking.
4. Return a record for EVERY case in the batch, including the ones you find
   irrelevant — accounting for every candidate is part of the coverage
   guarantee. For an irrelevant case: `relevant: false`, `polarity: null`,
   `who_was_letting: null`, no quotes required, and a one-line `notes`
   saying why.
5. Output: a single JSON object `{"records": [ ... ]}`, nothing else — no
   markdown fences, no commentary outside the JSON. A bare JSON array of the
   same records is also accepted.
```

- [ ] **Step 4: Amend `CONTEXT.md`**

Replace the **Polarity** entry (currently four lines plus the `_Avoid_` line) with:

```markdown
**Polarity**:
Whether a case is favorable, adverse, or mixed for the owner's right to let.
Judged from the owner's side only. An outcome that protects an occupant
against the owner is adverse. Mixed means the same opinion both recognizes
the owner's freedom to let on one point and restricts it on another, and
both are holdings rather than remarks in passing; an owner who wins on a
ground unrelated to letting is not favorable. A case the reader finds
irrelevant carries no polarity.
_Avoid_: pro-tenant, pro-landlord, outcome, irrelevant-as-a-polarity
```

- [ ] **Step 5: Amend `docs/adr/0004-extraction-schema-v2.md`**

Append at the end of the file:

```markdown

## Amendment 2026-09-05: schema v3 defines `mixed` and drops `irrelevant` from polarity

Schema v2 left `mixed` undefined and carried `irrelevant` as a fourth polarity
value, so a relevance miss was scored twice — once as relevance, once as
polarity — and two readers could disagree on `mixed` without either being
wrong. Codebook `mapper-v3` (schema_version 3) defines `mixed` as an opinion
whose holdings both recognize and restrict the owner's freedom to let, makes
`null` the polarity of a record marked `relevant: false`, and states the
support rule the quote gate actually enforces: `supports` is an array, one
quote may support several fields, and a judged value no quote names is erased.
Consumers must tolerate `polarity: null` on relevant-false records, and must
not read `irrelevant` as a polarity on any v3 record. See
`docs/superpowers/specs/2026-09-05-stage-3b-slice-1-subscription-reader-design.md`
section 5.
```

- [ ] **Step 6: Run the test, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader_codebook_v3.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green (`test_reader_render.py` still asserts mapper-v1 and mapper-v2 unchanged; neither file is touched).

- [ ] **Step 7: Commit**

```bash
git add domains/str-right-to-let/codebooks/mapper-v3.md CONTEXT.md docs/adr/0004-extraction-schema-v2.md tests/test_reader_codebook_v3.py
git commit -m "codebook mapper-v3: mixed defined, irrelevant dropped from polarity, supports rule explicit"
```

---

### Task 4: Scoring v2 — decided rate, relevance-gated polarity, selection rule D4

**Files:**
- Modify: `corpus_engine/reader/measure.py`, `tests/test_reader_measure.py`, `tests/test_measure_reader_tool.py` (its merge fixture's score shape), `tools/measure_reader.py` (the `line()` reader of the score keys)

**Interfaces:**
- Consumes: `ReadingOutcome`, `UnitResult`, `Response.raw` (Task 1).
- Produces (Task 9 consumes exactly these):
  - `corpus_engine.reader.measure.BAR_FIELDS = ("relevant", "polarity", "who_was_letting")`; `POLARITY_VALUES = ("favorable", "adverse", "mixed")`.
  - `field_scores(predictions: list[dict], reference: list[dict], *, fields=BAR_FIELDS, excluded: Mapping[int, set[str]] | None = None) -> dict` — `{field: {"decided_rate", "agreement_decided", "n_reference_decided", "n_both_decided", "n_prediction_irrelevant"}, "macro": float}`.
  - `excluded_fields(reference: list[dict]) -> dict[int, set[str]]` — reads each reference row's `excluded_fields` list (D6).
  - `score_candidate(outcome, reference, *, spend_usd_override: float | None = None, excluded=None) -> dict` — keys `fidelity, fields, macro, agreement_machine_irrelevant, schema_compliance, accepted, accepted_full, missing_records, priced, list_cost_usd, cost_per_accepted, spend_usd, wall_seconds, provider_reported, failed_units, stop`.
  - `select_reader(scores: dict[str, dict], *, subscription: frozenset[str] | set[str] = frozenset(), fidelity_floor=0.97, decided_floor=0.90, agreement_bar=0.85, tie_window=0.02, fields=BAR_FIELDS) -> dict` — keys `winner, rule, survivors, eliminated (dict label -> reason), shortfall, best_macro`.
  - `stability_agreement(out_a, out_b, fields=BAR_FIELDS) -> dict[str, float]` (unchanged), `load_kit(path)` (unchanged), `kit_sample_50(reference)` (unchanged).

- [ ] **Step 1: Write the failing test**

Replace the whole of `tests/test_reader_measure.py` with:

```python
"""Scoring v2 (spec section 6). Two numbers per field, not one: `decided_rate` says how
often the reader answered at all after the gate, `agreement_decided` how often it agreed
when both sides answered. 3A blended them, so a model that left polarity null scored the
same as one that got polarity wrong. Polarity and who_was_letting are judged only where
both sides call the case relevant, so a relevance miss is scored once, as relevance."""
import math

import pytest

from corpus_engine.reader.measure import (BAR_FIELDS, excluded_fields, field_scores,
                                          score_candidate, select_reader)
from corpus_engine.reader.model import (Budget, ModelPin, Plan, ReadingOutcome, RecordResult,
                                        Response, StopReason, Unit, UnitResult)

REF = [
    {"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
    {"case_id": 2, "source": "human", "relevant": True, "polarity": "adverse", "who_was_letting": "commercial_operator"},
    {"case_id": 3, "source": "human", "relevant": True, "polarity": "mixed", "who_was_letting": "unclear"},
    {"case_id": 4, "source": "human", "relevant": False, "polarity": None, "who_was_letting": None},
    {"case_id": 5, "source": "machine", "relevant": False, "polarity": None, "who_was_letting": None},
]
PRED = [
    {"case_id": 1, "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
     "quotes": [1, 2], "extraction_status": "ok"},
    {"case_id": 2, "relevant": True, "polarity": None, "who_was_letting": "non_resident_owner",
     "quotes": [1], "extraction_status": "partial"},
    {"case_id": 3, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
    {"case_id": 4, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
    {"case_id": 5, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
]


def _out(recs, dropped, spend, *, cache_hit=False, cost_usd=None, list_cost=None):
    rr = tuple(RecordResult(r["case_id"], r, r.get("extraction_status", "ok"), d, ())
               for r, d in zip(recs, dropped))
    resp = Response("", 1, 1, cost_usd if cost_usd is not None else spend, {"provider": "P"}, "stop",
                    None, {"list_cost_usd": list_cost} if list_cost is not None else {})
    u = UnitResult("u", "ok", rr, resp, cache_hit)
    plan = Plan("k", (Unit("u", tuple(r["case_id"] for r in recs)),), "cb", ModelPin("m", "f"), Budget(), "w")
    return ReadingOutcome(plan, [u], [], spend, 1, 1, 2.0, StopReason("done"), {}, "")


def test_field_scores_separates_undecided_from_disagreeing():
    s = field_scores(PRED, REF)
    # relevant: every reference row is decided; case 3 is the one miss
    assert s["relevant"]["n_reference_decided"] == 5 and s["relevant"]["n_both_decided"] == 5
    assert s["relevant"]["decided_rate"] == 1.0 and s["relevant"]["agreement_decided"] == 4 / 5
    # polarity: reference-decided on 1, 2, 3; case 3 drops out because the prediction says
    # irrelevant (that miss is already counted once, as relevance); case 2 answered null
    assert s["polarity"]["n_reference_decided"] == 2 and s["polarity"]["n_both_decided"] == 1
    assert s["polarity"]["decided_rate"] == 0.5 and s["polarity"]["agreement_decided"] == 1.0
    assert s["polarity"]["n_prediction_irrelevant"] == 1
    # who_was_letting: both answered on 1 and 2, and disagreed on 2
    assert s["who_was_letting"]["decided_rate"] == 1.0 and s["who_was_letting"]["agreement_decided"] == 0.5
    assert abs(s["macro"] - (4 / 5 + 1.0 + 0.5) / 3) < 1e-9


def test_a_reference_field_marked_unsure_is_excluded_for_that_field_only():
    s = field_scores(PRED, REF, excluded={2: {"who_was_letting"}})
    assert s["who_was_letting"]["n_reference_decided"] == 1 and s["who_was_letting"]["agreement_decided"] == 1.0
    assert s["polarity"]["n_reference_decided"] == 2          # the case stays in for the other fields
    assert excluded_fields([{"case_id": 2, "excluded_fields": ["who_was_letting"]},
                            {"case_id": 3, "excluded_fields": []}]) == {2: {"who_was_letting"}}


def test_a_reference_polarity_of_irrelevant_is_not_a_decided_value():
    ref = [dict(REF[0], polarity="irrelevant")]
    s = field_scores([PRED[0]], ref)
    assert s["polarity"]["n_reference_decided"] == 0 and s["polarity"]["agreement_decided"] == 0.0


def test_score_candidate_reports_both_accepted_counts_and_prices_only_a_paid_run():
    s = score_candidate(_out(PRED, [0, 1, 0, 0, 0], 0.30), REF)
    assert s["fidelity"] == 3 / 4                       # one dropped quote among relevant records
    assert s["accepted"] == 5 and s["accepted_full"] == 4      # case 2 is partial
    assert s["priced"] is True and abs(s["cost_per_accepted"] - 0.06) < 1e-9
    assert s["agreement_machine_irrelevant"] == 1.0 and s["schema_compliance"] == 1.0
    assert abs(s["macro"] - (4 / 5 + 1.0 + 0.5) / 3) < 1e-9 and set(s["fields"]) == set(BAR_FIELDS)


def test_a_subscription_candidate_is_unpriced_and_records_the_list_cost():
    s = score_candidate(_out(PRED, [0, 0, 0, 0, 0], 0.0, cost_usd=None, list_cost=0.42), REF)
    assert s["priced"] is False and s["cost_per_accepted"] == math.inf
    assert s["list_cost_usd"] == 0.42 and s["spend_usd"] == 0.0


def test_score_candidate_spend_override_prices_a_cache_only_rerun():
    s = score_candidate(_out(PRED, [0, 0, 0, 0, 0], 0.0, cache_hit=True), REF, spend_usd_override=0.5)
    assert s["priced"] is True and abs(s["cost_per_accepted"] - 0.1) < 1e-9
    assert score_candidate(_out(PRED, [0] * 5, 0.0, cache_hit=True), REF)["priced"] is False


def _s(macro, *, fidelity=0.99, decided=0.95):
    fields = {f: {"decided_rate": decided, "agreement_decided": macro,
                  "n_reference_decided": 100, "n_both_decided": 95, "n_prediction_irrelevant": 0}
              for f in BAR_FIELDS}
    return {"fidelity": fidelity, "fields": fields, "macro": macro}


def test_select_reader_applies_both_floors():
    r = select_reader({"a": _s(0.99, fidelity=0.90), "b": _s(0.88)})
    assert r["winner"] == "b" and "a" in r["eliminated"] and "fidelity" in r["eliminated"]["a"]
    r2 = select_reader({"a": _s(0.99, decided=0.80)})
    assert r2["winner"] is None and "decided rate" in r2["eliminated"]["a"] and r2["shortfall"] is True


def test_a_subscription_candidate_wins_within_two_points_of_the_best():
    subs = {"claude-cli/claude-sonnet-5"}
    r = select_reader({"openai/gpt-5.6-terra": _s(0.88), "claude-cli/claude-sonnet-5": _s(0.87)},
                      subscription=subs)
    assert r["winner"] == "claude-cli/claude-sonnet-5" and r["shortfall"] is False
    assert "within 0.02" in r["rule"] and abs(r["best_macro"] - 0.88) < 1e-9
    r2 = select_reader({"openai/gpt-5.6-terra": _s(0.90), "claude-cli/claude-sonnet-5": _s(0.87)},
                       subscription=subs)
    assert r2["winner"] == "openai/gpt-5.6-terra" and "highest macro" in r2["rule"]


def test_the_tie_break_also_applies_when_nobody_reaches_the_bar():
    """D4's tie-break is stated over survivors, and the reason for it - the subscription
    read costs nothing - does not change when the bar is missed. The shortfall is disclosed
    either way, and the rule string says which branch fired."""
    r = select_reader({"openai/gpt-5.6-terra": _s(0.80), "claude-cli/claude-opus-5": _s(0.79)},
                      subscription={"claude-cli/claude-opus-5"})
    assert r["winner"] == "claude-cli/claude-opus-5" and r["shortfall"] is True
    assert "no survivor reached 0.85" in r["rule"]


def test_selection_is_deterministic_on_an_exact_tie():
    r = select_reader({"b/two": _s(0.90), "a/one": _s(0.90)})
    assert r["winner"] == "a/one" and r["survivors"] == ["a/one", "b/two"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_measure.py -q`
Expected: FAIL — `ImportError: cannot import name 'field_scores'`.

- [ ] **Step 3: Rewrite the scoring half of `corpus_engine/reader/measure.py`**

Keep `load_kit`, `KIT_SEED`, `kit_sample_50` and `stability_agreement` as they are. Replace `BAR_FIELDS`, `score_candidate` and `select_reader` with:

```python
BAR_FIELDS = ("relevant", "polarity", "who_was_letting")
POLARITY_VALUES = ("favorable", "adverse", "mixed")
KIT_SEED = 20260904


def _decided(field: str, value) -> bool:
    """Whether a side answered this field at all. `irrelevant` is not a polarity value
    (D2): a kit-v1 reference row still carrying it is undecided, not wrong."""
    if value is None:
        return False
    if field == "polarity":
        return value in POLARITY_VALUES
    return True


def excluded_fields(reference: list[dict]) -> dict[int, set[str]]:
    """D6: fields the reviewer marked `unsure`, per case. The case stays in the kit for
    fidelity and for every other field."""
    return {int(r["case_id"]): set(r["excluded_fields"]) for r in reference if r.get("excluded_fields")}


def field_scores(predictions: list[dict], reference: list[dict], *, fields=BAR_FIELDS,
                 excluded=None) -> dict:
    """Per field: how often the reader decided, and how often it agreed when both decided.

    The denominator for `decided_rate` is the reference-decided cases the reader returned a
    record for; `agreement_decided` runs over the subset where the reader also decided.
    `polarity` and `who_was_letting` are computed only where the reference marks the case
    relevant AND the prediction does, so a relevance miss is scored once, as relevance -
    `n_prediction_irrelevant` records how many cases that removed, because a reader that
    calls everything irrelevant would otherwise shrink its way to a high decided rate."""
    ref = {int(r["case_id"]): r for r in reference}
    pred = {int(r["case_id"]): r for r in predictions if r.get("case_id") is not None}
    ex = {int(k): set(v) for k, v in (excluded or {}).items()}
    out: dict = {}
    for f in fields:
        pool = [c for c in sorted(ref)
                if c in pred and f not in ex.get(c, ()) and _decided(f, ref[c].get(f))]
        gated = pool
        dropped = 0
        if f != "relevant":
            gated = [c for c in pool if ref[c].get("relevant") is True and pred[c].get("relevant") is True]
            dropped = len(pool) - len(gated)
        decided = [c for c in gated if _decided(f, pred[c].get(f))]
        agreed = sum(1 for c in decided if pred[c].get(f) == ref[c].get(f))
        out[f] = {"decided_rate": (len(decided) / len(gated)) if gated else 0.0,
                  "agreement_decided": (agreed / len(decided)) if decided else 0.0,
                  "n_reference_decided": len(gated), "n_both_decided": len(decided),
                  "n_prediction_irrelevant": dropped}
    out["macro"] = sum(out[f]["agreement_decided"] for f in fields) / len(fields)
    return out


def score_candidate(outcome: ReadingOutcome, reference: list[dict], *,
                    spend_usd_override: float | None = None, excluded=None) -> dict:
    ref = {int(r["case_id"]): r for r in reference}
    recs = outcome.records
    # Stub records for failed/partial units carry extraction_status "missing" and
    # relevant: None; they must not count as accepted and must be excluded from agreement.
    missing_records = sum(1 for r in recs if r.get("extraction_status") == "missing")
    non_missing = [r for r in recs if r.get("extraction_status") != "missing"]
    by_id = {int(r["case_id"]): r for r in non_missing if r.get("case_id") is not None}
    kept = sum(len(r.record.get("quotes") or []) for u in outcome.units for r in u.records if r.record.get("relevant"))
    dropped = sum(r.dropped_quotes for u in outcome.units for r in u.records if r.record.get("relevant"))
    fidelity = kept / (kept + dropped) if (kept + dropped) else 0.0
    human = [r for r in reference if r["source"] == "human"]
    fields = field_scores([by_id[c] for c in by_id if c in ref and ref[c]["source"] == "human"],
                          human, excluded=excluded)
    macro = fields.pop("macro")
    machine = [r for r in reference if r["source"] == "machine"]
    mi = (sum(1 for r in machine if by_id.get(r["case_id"], {}).get("relevant") is False) / len(machine)) if machine else None
    n_cases = sum(len(u.records) for u in outcome.units) or sum(len(u.case_ids) for u in outcome.plan.units)
    accepted = sum(1 for r in non_missing if r.get("extraction_status") in ("ok", "partial")
                   and r.get("relevant") is not None)
    # `accepted` is the pre-registered denominator; `accepted_full` counts only the records
    # whose judged fields all survived the gate, so the gap is how many were partial (I7).
    accepted_full = sum(1 for r in non_missing if r.get("extraction_status") == "ok"
                        and r.get("relevant") is not None)
    responses = [u.response for u in outcome.units if u.response is not None]
    list_costs = [r.raw.get("list_cost_usd") for r in responses if (r.raw or {}).get("list_cost_usd") is not None]
    list_cost_usd = round(sum(list_costs), 6) if list_costs else None
    subscription = bool(responses) and all(r.cost_usd is None for r in responses)
    any_cache_hit = any(u.cache_hit for u in outcome.units)
    if subscription:
        # The subscription has no marginal price. A zero is not cheap, it is absent, and an
        # absent price must never win a cost comparison.
        priced, spend_for_cost = False, 0.0
    elif spend_usd_override is not None:
        priced, spend_for_cost = True, spend_usd_override
    elif any_cache_hit:
        priced, spend_for_cost = False, outcome.spend_usd
    else:
        priced, spend_for_cost = True, outcome.spend_usd
    cost_per_accepted = (spend_for_cost / accepted) if (priced and accepted) else math.inf
    return {"fidelity": fidelity, "fields": fields, "macro": macro,
            "agreement_machine_irrelevant": mi,
            "schema_compliance": (len(non_missing) / n_cases) if n_cases else 0.0,
            "accepted": accepted, "accepted_full": accepted_full,
            "missing_records": missing_records, "priced": priced, "list_cost_usd": list_cost_usd,
            "cost_per_accepted": cost_per_accepted, "spend_usd": spend_for_cost,
            "wall_seconds": round(outcome.wall_seconds, 1),
            "provider_reported": outcome.manifest.get("provider_reported"),
            "failed_units": outcome.failed_units, "stop": outcome.stop.kind}


def select_reader(scores: dict[str, dict], *, subscription=frozenset(), fidelity_floor: float = 0.97,
                  decided_floor: float = 0.90, agreement_bar: float = 0.85, tie_window: float = 0.02,
                  fields=BAR_FIELDS) -> dict:
    """Decision D4, pre-registered in the spec before any read.

    Floors first (fidelity, then decided rate per judged field), then the agreement bar,
    then the tie-break: a subscription candidate within `tie_window` of the best surviving
    macro wins, because the subscription read costs nothing and the difference is inside the
    noise the 3A stability check measured. Cost per accepted record is reported but is not
    part of the rule: D4 has no cost term."""
    eliminated: dict[str, str] = {}
    for k in sorted(scores):
        s = scores[k]
        if s["fidelity"] < fidelity_floor:
            eliminated[k] = f"fidelity {s['fidelity']:.4f} < {fidelity_floor}"
            continue
        low = [f for f in fields if s["fields"][f]["decided_rate"] < decided_floor]
        if low:
            eliminated[k] = ("decided rate below " + f"{decided_floor}" + " on "
                             + ", ".join(f"{f} {s['fields'][f]['decided_rate']:.4f}" for f in low))
    survivors = {k: s for k, s in scores.items() if k not in eliminated}
    if not survivors:
        return {"winner": None, "rule": f"no candidate cleared the fidelity floor {fidelity_floor} "
                                        f"and the decided-rate floor {decided_floor}",
                "survivors": [], "eliminated": eliminated, "shortfall": True, "best_macro": None}
    best = max(s["macro"] for s in survivors.values())
    pool = {k: s for k, s in survivors.items() if s["macro"] >= agreement_bar}
    shortfall = not pool
    if shortfall:
        pool = dict(survivors)
    near = {k: s for k, s in pool.items() if k in set(subscription) and s["macro"] >= best - tie_window}
    if near:
        winner = max(sorted(near), key=lambda k: near[k]["macro"])
        rule = (f"subscription candidate within {tie_window} of the best surviving macro "
                f"({best:.4f})")
    else:
        winner = max(sorted(pool), key=lambda k: pool[k]["macro"])
        rule = "highest macro agreement among survivors"
    if shortfall:
        rule += f"; no survivor reached {agreement_bar} (shortfall disclosed)"
    return {"winner": winner, "rule": rule, "survivors": sorted(survivors), "eliminated": eliminated,
            "shortfall": shortfall, "best_macro": best}
```

- [ ] **Step 4: Keep the measurement tool's log line readable**

`tools/measure_reader.py` prints `s['agreement_human']['macro']`, which no longer exists. Replace `line()` with:

```python
def line(s: dict) -> str:
    cpa = s["cost_per_accepted"]
    cpa_txt = "inf" if not math.isfinite(cpa) else f"${cpa:.4f}"
    decided = " ".join(f"{f}={s['fields'][f]['decided_rate']:.2f}/{s['fields'][f]['agreement_decided']:.2f}"
                       for f in ("relevant", "polarity", "who_was_letting"))
    return (f"   fidelity={s['fidelity']:.4f} macro={s['macro']:.4f} [{decided}] "
            f"cpa={cpa_txt} spend=${s['spend_usd']:.2f} "
            f"accepted={s['accepted']} ({s['accepted_full']} full) schema={s['schema_compliance']:.3f} "
            f"wall={s['wall_seconds']:.0f}s stop={s['stop']}"
            + ("" if s.get("priced", True) else "  [UNPRICED]"))
```

Add this comment above `main()` in the same file (the tool is rewritten for v2 in Task 9; until then it must not be pointed at the v1 manifest):

```python
# NOTE (Stage 3B slice 1): scores are the v2 shape from measure.score_candidate. The
# measurement-v1 manifest holds v1-shaped scores, which select_reader can no longer read;
# this tool is rewritten for measurement-v2 in Task 9 and must not be run in a paid mode
# before then.
```

- [ ] **Step 5: Move `test_measure_reader_tool.py`'s merge fixture to v2-shaped scores**

`test_merge_manifest_never_drops_a_candidate_a_rerun_did_not_run` ends by calling
`mr.select_reader(merged["scores"])`, and its fixture scores carry the 3A `agreement_human`
shape that `select_reader` no longer reads. Add this helper above the test:

```python
def _score(macro, cpa, accepted, *, fidelity=0.99, decided=0.95):
    """A v2-shaped score (measure.score_candidate): two numbers per field, macro alongside."""
    return {"fidelity": fidelity, "macro": macro, "cost_per_accepted": cpa, "priced": True,
            "accepted": accepted, "accepted_full": accepted,
            "fields": {f: {"decided_rate": decided, "agreement_decided": macro,
                           "n_reference_decided": 155, "n_both_decided": 150,
                           "n_prediction_irrelevant": 0}
                       for f in ("relevant", "polarity", "who_was_letting")}}
```

and replace the four score dicts in the fixture:

```python
        "scores": {"a/one": _score(0.70, 0.05, 195), "b/two": _score(0.60, 0.01, 190)},
```
```python
        "scores": {"b/two": _score(0.62, 0.02, 193)},
```

The assertions below them (`winner == "a/one"`, `survivors == ["a/one", "b/two"]`) still hold:
both clear the fidelity and decided-rate floors, neither reaches 0.85, and the shortfall
branch picks the higher macro.

- [ ] **Step 6: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader_measure.py tests/test_measure_reader_tool.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/reader/measure.py tools/measure_reader.py tests/test_reader_measure.py tests/test_measure_reader_tool.py
git commit -m "reader scoring v2: decided rate vs agreement, relevance-gated polarity, D4 selection with subscription tie-break"
```

---

### Task 5: `tools/apply_reference_review.py` — the saved page becomes ledger patches

**Files:**
- Create: `tools/apply_reference_review.py`, `tests/test_apply_reference_review.py`

**Interfaces:**
- Consumes: `Patch`, `Basis` from `corpus_engine.ledger.types`; `open_ledger()` from `corpus_engine.ledger`; the STATE marker `make_reference_review.py` writes (`<script type="application/json" id="review-state">`).
- Produces (Task 7 relies on the flags this writes):
  - `read_state(html: str) -> list[dict]` — validated decisions `{"case_id": int, "field": str, "decision": str, "value": object, "note": str}`.
  - `patches_for(decisions, records: Mapping[int, dict], reviewer: str, *, field_order=FIELDS, run_id="reference-v2") -> list[Patch]`.
  - Module constants `FIELDS = ("polarity", "who_was_letting")`, `DECISIONS = ("keep", "adopt", "set", "unsure")`, `VALUES`, `IRRELEVANT = "irrelevant"`, `FLAG_PREFIX = "needs-review:"`, `RUN_ID = "reference-v2"`.
  - CLI: `--saved <html> [--field-order polarity,who_was_letting] [--dry-run]`.

**This task's live input arrives from the user.** Steps 1–5 build and test the tool against a page generated in-test; Step 6 waits for the user's saved page and is the only step that touches the ledger.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apply_reference_review.py
"""The saved review page IS the record (same mechanism as pipeline/make_review.py), so this
tool has one job: turn the decision state embedded in that page into ledger patches with the
user as basis, and refuse anything it cannot read. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTESTED = ROOT / "tests" / "fixtures" / "reference-contested-tiny.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arr = _load("apply_reference_review")
mrr = _load("make_reference_review")


def saved_page(tmp_path, decisions) -> str:
    """A page in exactly the state the artifact capability republishes it in: the empty
    state array replaced by the decisions, everything else byte-identical."""
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    html = html_path.read_text(encoding="utf-8")
    payload = json.dumps(decisions).replace("<", "\\u003c")
    return html.replace('id="review-state">[]<', f'id="review-state">{payload}<')


def _d(case_id, field, decision, value=None, note=""):
    return {"case_id": case_id, "field": field, "decision": decision, "value": value, "note": note}


def test_read_state_returns_the_decisions_a_saved_page_carries(tmp_path):
    decisions = [_d(65116, "polarity", "adopt", "favorable"), _d(65116, "who_was_letting", "keep", "unclear")]
    got = arr.read_state(saved_page(tmp_path, decisions))
    assert [(d["case_id"], d["field"], d["decision"], d["value"]) for d in got] == [
        (65116, "polarity", "adopt", "favorable"), (65116, "who_was_letting", "keep", "unclear")]


def test_read_state_refuses_an_unsaved_page_and_a_bad_decision(tmp_path):
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    with pytest.raises(ValueError, match="no decisions"):
        arr.read_state(html_path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no review-state"):
        arr.read_state("<html>nothing here</html>")
    with pytest.raises(ValueError, match="decision"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "maybe", "favorable")]))
    with pytest.raises(ValueError, match="value"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "set", "pro-tenant")]))
    with pytest.raises(ValueError, match="field"):
        arr.read_state(saved_page(tmp_path, [_d(1, "duration_of_occupancy", "keep", "weeks")]))


def test_patches_for_covers_the_four_decisions():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True},
               2: {"polarity": "mixed", "who_was_letting": "unclear", "relevant": True},
               3: {"polarity": "adverse", "who_was_letting": "householder", "relevant": True},
               4: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "polarity", "keep", "favorable"),
                 _d(2, "polarity", "adopt", "adverse", note="clearly a tenant-protection holding"),
                 _d(3, "who_was_letting", "set", "non_resident_owner"),
                 _d(4, "polarity", "unsure")]
    ps = arr.patches_for(decisions, records, "mmaldo2")
    by_case = {}
    for p in ps:
        by_case.setdefault(p.case_id, []).append((p.op, p.field, p.new))
    assert 1 not in by_case                                        # keep -> no patch at all
    assert ("set", "polarity", "adverse") in by_case[2]
    assert ("append", "review.notes", "user note: clearly a tenant-protection holding") in by_case[2]
    assert ("set", "review.status", "human-adjudicated") in by_case[2]
    assert ("set", "who_was_letting", "non_resident_owner") in by_case[3]
    assert ("append", "review.flags", "needs-review:polarity") in by_case[4]
    assert not any(op == "set" and f == "polarity" for op, f, _v in by_case[4])
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == "reference-v2" for p in ps)
    assert all(p.basis.kind() == "human" for p in ps)


def test_adopting_irrelevant_on_polarity_clears_the_whole_record():
    records = {9: {"polarity": "mixed", "who_was_letting": "commercial_operator", "relevant": True}}
    ps = arr.patches_for([_d(9, "polarity", "adopt", "irrelevant")], records, "mmaldo2")
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert ("relevant", False) in sets and ("polarity", None) in sets and ("who_was_letting", None) in sets
    assert ("review.status", "human-adjudicated") in sets


def test_patch_order_follows_the_field_order_flag():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "who_was_letting", "set", "householder"), _d(1, "polarity", "set", "adverse")]
    fields = [p.field for p in arr.patches_for(decisions, records, "u") if p.op == "set"]
    assert fields.index("polarity") < fields.index("who_was_letting")
    fields2 = [p.field for p in arr.patches_for(decisions, records, "u",
                                                field_order=("who_was_letting", "polarity")) if p.op == "set"]
    assert fields2.index("who_was_letting") < fields2.index("polarity")


def test_null_spellings_become_none():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    ps = arr.patches_for([_d(1, "polarity", "set", "null")], records, "u")
    assert ("polarity", None) in [(p.field, p.new) for p in ps if p.op == "set"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_apply_reference_review.py -q`
Expected: FAIL — `FileNotFoundError: ...tools/apply_reference_review.py`.

- [ ] **Step 3: Write the tool**

```python
# tools/apply_reference_review.py
"""Apply the user's saved reference-adjudication page to the ledger (spec section 7).

`tools/make_reference_review.py` renders the contested kit reference labels as a page that
saves its own decision state back into itself; the saved page IS the record. This reads that
state and emits ledger patches with the user as basis, exactly as pipeline/polarity_review.py's
apply path does:

  keep   -> no patch
  adopt  -> set the field to the model majority value
  set    -> set the field to the value the reviewer chose
  unsure -> a `needs-review:<field>` flag; the field is excluded from agreement for that case
            (D6) and the case stays in the kit for fidelity and for its other fields

Adopting `irrelevant` on polarity is not a polarity at all (D2): it sets `relevant` false and
nulls polarity and who_was_letting.

Usage:
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved reports\\review-queue-reference-v1.html
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved <page> --dry-run
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                       # noqa: E402
from corpus_engine.ledger import open_ledger                       # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                # noqa: E402

STATE_RE = re.compile(r'<script[^>]*id="review-state"[^>]*>(.*?)</script>', re.S)
FIELDS = ("polarity", "who_was_letting")
DECISIONS = ("keep", "adopt", "set", "unsure")
IRRELEVANT = "irrelevant"
FLAG_PREFIX = "needs-review:"
RUN_ID = "reference-v2"
NULLS = (None, "null", "")
VALUES = {"polarity": {"favorable", "adverse", "mixed", IRRELEVANT, None},
          "who_was_letting": {"householder", "commercial_operator", "non_resident_owner",
                              "unclear", None}}


def _value(field: str, raw):
    return None if raw in NULLS else raw


def read_state(html: str) -> list[dict]:
    """The decisions a saved page carries, validated. A page that was never saved carries
    `[]`, and applying nothing silently would look exactly like applying everything."""
    m = STATE_RE.search(html)
    if not m:
        raise ValueError("no review-state block in this page; is it the page make_reference_review.py wrote?")
    raw = json.loads(m.group(1))
    if not isinstance(raw, list) or not raw:
        raise ValueError("the page carries no decisions; save the page after deciding, then re-run")
    out = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ValueError(f"decision {i} is not an object: {d!r}")
        field = d.get("field")
        if field not in FIELDS:
            raise ValueError(f"decision {i}: field {field!r} is not one of {FIELDS}")
        decision = d.get("decision")
        if decision not in DECISIONS:
            raise ValueError(f"decision {i}: decision {decision!r} is not one of {DECISIONS}")
        value = _value(field, d.get("value"))
        if decision in ("adopt", "set") and value not in VALUES[field]:
            raise ValueError(f"decision {i}: value {value!r} is not a {field} value")
        out.append({"case_id": int(d["case_id"]), "field": field, "decision": decision,
                    "value": value, "note": (d.get("note") or "").strip()})
    return out


def patches_for(decisions: Sequence[dict], records: Mapping[int, dict], reviewer: str, *,
                field_order: Sequence[str] = FIELDS, run_id: str = RUN_ID) -> list[Patch]:
    """Ledger patches for one saved page. Deterministic: field order first (so a case
    contested on both fields is written in a fixed order), then case id."""
    basis = Basis(reviewer=reviewer, run_id=run_id)
    order = {f: i for i, f in enumerate(field_order)}
    out: list[Patch] = []
    for d in sorted(decisions, key=lambda d: (order.get(d["field"], 99), int(d["case_id"]))):
        cid, field, decision = int(d["case_id"]), d["field"], d["decision"]
        if decision == "keep":
            continue
        old = (records.get(cid) or {}).get(field)
        why = f"reference v2 adjudication: {field}"
        if decision == "unsure":
            out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why, basis))
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: {field} left unsure by the reviewer; excluded from "
                             f"agreement for this field (D6)", why, basis))
        elif field == "polarity" and d["value"] == IRRELEVANT:
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: polarity {old!r} -> irrelevant; the case is not "
                             f"relevant, so it carries no polarity", why, basis))
            out.append(Patch(cid, "set", "relevant", False, why, basis))
            out.append(Patch(cid, "set", "polarity", None, why, basis))
            out.append(Patch(cid, "set", "who_was_letting", None, why, basis))
        else:
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: {field} {old!r} -> {d['value']!r} ({decision})", why, basis))
            out.append(Patch(cid, "set", field, d["value"], why, basis))
        if d["note"]:
            out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why, basis))
        out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--saved", required=True, help="the review page, saved with decisions in it")
    ap.add_argument("--field-order", default=",".join(FIELDS))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    decisions = read_state(Path(a.saved).read_text(encoding="utf-8"))
    dom = load_domain()
    led = open_ledger(domain=dom)
    records = led.view().state.records
    patches = patches_for(decisions, records, dom.reviewer_default,
                          field_order=tuple(f.strip() for f in a.field_order.split(",") if f.strip()))
    counts = {d: sum(1 for x in decisions if x["decision"] == d) for d in DECISIONS}
    print(f"{len(decisions)} decisions {counts} -> {len(patches)} patches", flush=True)
    res = led.apply(patches, note="reference v2 adjudication", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_apply_reference_review.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 5: Commit the tool**

```bash
git add tools/apply_reference_review.py tests/test_apply_reference_review.py
git commit -m "tools: apply_reference_review - saved review page to ledger patches with reviewer basis"
```

- [ ] **Step 6: Apply the user's saved page (waits for the user's file)**

The input is the user's own saved copy of `reports/review-queue-reference-v1.html` (71 contested cases, 82 field decisions). Do not invent it and do not proceed without it; if it is not on disk, stop and say so.

```bash
.venv/Scripts/python tools/apply_reference_review.py --saved reports/review-queue-reference-v1.html --dry-run
.venv/Scripts/python tools/apply_reference_review.py --saved reports/review-queue-reference-v1.html
.venv/Scripts/python -m pytest -q
```
Expected: the dry run prints the decision counts and `replay_ok=True`; the real run prints the same applied count. Record the four decision counts (keep / adopt / set / unsure) — they go in the Task 9 report. Then:

```bash
git add data/ledger reports/review-queue-reference-v1.html
git commit -m "reference v2: apply the user's adjudications of the 71 contested kit labels"
```

---

### Task 6: `tools/consensus_reference.py` — the 4-of-5 who-was-letting reference

**Files:**
- Create: `tools/consensus_reference.py`, `tests/test_consensus_reference.py`
- Modify: `tools/measure_reader.py` (extract `records_from_cache` from `accepted_from_cache`)

**Interfaces:**
- Consumes: `ResponseCache.key_v1` (Task 1), `pin_from_label`, `accepted_from_cache` (existing), `plan_batch_extraction`, `gate_unit`, `parse_records`, `split_unit`, `render_unit`, `load_kit`; `make_reference_review.build_pages(contested: Path, out_stem: Path)`.
- Produces:
  - `tools/measure_reader.records_from_cache(cb, pin, units, source, cache, judged) -> list[dict]` — the gated records a candidate's cached responses yield, offline (no request, no spend). `accepted_from_cache` now counts over it and keeps its behaviour.
  - `tools/consensus_reference.CANDIDATES` (the five measured finalists, in the fixed order `make_reference_review.CANDIDATES` uses), `CONSENSUS_K = 4`, `CONSENSUS_MODEL = "model-consensus:mapper-v2:4of5"`, `RUN_ID = "reference-v2-consensus"`.
  - `consensus(values: Mapping[str, object], k: int = CONSENSUS_K) -> tuple[object | None, int, int]` — `(value or None, top count, non-null count)`.
  - `patches_for(agreed: Mapping[int, tuple], records: Mapping[int, dict]) -> list[Patch]` — machine-basis patches.
  - `contested_doc(splits, texts: Mapping[int, CaseText], reference: Mapping[int, dict], per_candidate: Mapping[int, Mapping[str, object]]) -> dict` — a contested-style document `make_reference_review.build_items` accepts.
  - CLI: `[--kit data/reader/kit-v1/kit.json] [--out data/reader/review/reference-v2/contested-who.json] [--dry-run]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_consensus_reference.py
"""D3: the who-was-letting reference for the 154 kit cases nobody ever reviewed on that
field is the value at least 4 of the 5 finalists returned under mapper-v2; the rest go to
the user on a second page. The counting rule and the shape of that second page are what
this file pins - the cached reads it counts over are provenance, not a test fixture."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cr = _load("consensus_reference")
mrr = _load("make_reference_review")

C = list(cr.CANDIDATES)


def test_four_of_five_agree_is_consensus_and_three_is_not():
    four = dict(zip(C, ["householder", "householder", "householder", "householder", "commercial_operator"]))
    assert cr.consensus(four) == ("householder", 4, 5)
    three = dict(zip(C, ["householder", "householder", "householder", "unclear", "commercial_operator"]))
    assert cr.consensus(three) == (None, 3, 5)
    unanimous = dict(zip(C, ["unclear"] * 5))
    assert cr.consensus(unanimous) == ("unclear", 5, 5)


def test_nulls_do_not_count_toward_the_four():
    values = dict(zip(C, ["householder", "householder", "householder", "householder", None]))
    assert cr.consensus(values) == ("householder", 4, 4)
    thin = dict(zip(C, ["householder", "householder", None, None, None]))
    assert cr.consensus(thin) == (None, 2, 2)
    assert cr.consensus(dict(zip(C, [None] * 5))) == (None, 0, 0)


def test_consensus_patches_carry_a_machine_basis_that_can_judge():
    ps = cr.patches_for({77: ("householder", 4, 5)}, {77: {"who_was_letting": None}})
    assert [(p.op, p.field, p.new) for p in ps if p.op == "set"] == [("who_was_letting", "householder")]
    p = ps[0]
    assert p.basis.kind() == "reader" and p.basis.can_judge()
    assert p.basis.model == "model-consensus:mapper-v2:4of5" and p.basis.prompt_version == "mapper-v2"
    assert p.basis.run_id == "reference-v2-consensus"
    assert all(p.basis.reviewer is None for p in ps)              # never a human basis


def test_the_split_document_builds_a_second_review_page(tmp_path):
    class T:
        def __init__(self, cid):
            self.case_id, self.name, self.cite = cid, f"Case {cid}", f"{cid} N.Y. 1"
            self.court, self.jurisdiction, self.year = "N.Y. Ct. App.", "N.Y.", 1899
    splits = {5: (None, 3, 5), 6: (None, 2, 4)}
    per_candidate = {5: dict(zip(C, ["householder", "householder", "householder", "unclear", "commercial_operator"])),
                     6: dict(zip(C, ["unclear", "unclear", "commercial_operator", "commercial_operator", None]))}
    doc = cr.contested_doc(splits, {5: T(5), 6: T(6)},
                           {5: {"who_was_letting": None, "relevant": True, "polarity": "favorable"},
                            6: {"who_was_letting": None, "relevant": True, "polarity": "adverse"}},
                           per_candidate)
    assert [c["case_id"] for c in doc["contested"]] == [5, 6]
    assert all(c["contested_fields"] == ["who_was_letting"] for c in doc["contested"])
    assert doc["counts"]["splits"] == 2
    data = mrr.build_items(doc)                                   # the page builder accepts it
    assert data["A"] == [] and [i["case_id"] for i in data["B"]] == [5, 6]
    assert [c["label"] for c in data["B"][0]["cands"]] == [lab for _full, lab in mrr.CANDIDATES]
    assert data["B"][0]["maj"] == "householder" and data["B"][0]["maj_n"] == 3
    out = tmp_path / "contested-who.json"
    out.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    html, md, _n = mrr.build_pages(out, tmp_path / "review-queue-reference-v2")
    assert "5" in html.read_text(encoding="utf-8") and md.exists()


def test_records_from_cache_is_the_basis_of_the_accepted_counts():
    """The consensus reads the same cached records the accepted counts are derived from, so
    the two can never disagree about what a candidate said."""
    mr = _load("measure_reader")
    assert callable(mr.records_from_cache)
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "records_from_cache(" in src.split("def accepted_from_cache", 1)[1]
    assert "ResponseCache.key_v1" in src                          # the v1 cache, addressed the v1 way
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_consensus_reference.py -q`
Expected: FAIL — `FileNotFoundError: ...tools/consensus_reference.py`.

- [ ] **Step 3: Extract `records_from_cache` in `tools/measure_reader.py`**

Replace `accepted_from_cache` with these two functions (the body is the old one, split at the point where it stopped needing to be private):

```python
def records_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged) -> list[dict]:
    """One candidate's gated records, re-derived from its own cached responses. Offline:
    reads the response cache and the frozen kit, issues no request, spends nothing. Mirrors
    the driver exactly - parse, split-half fallback on a parse failure, then the quote gate.

    The measurement-v1 cache is addressed with `ResponseCache.key_v1`: slice 1 widened the
    live key with the schema, max_tokens and effort, and those responses were bought under
    the old composition."""
    def cached(u):
        texts = source.fetch(u.case_ids)
        p = cache.dir / f"{ResponseCache.key_v1(cb.sha, pin, u, render_unit(cb, u, texts, 'reader'))}.json"
        return texts, (json.loads(p.read_text(encoding="utf-8"))["text"] if p.exists() else None)

    records = []
    for unit in units:
        texts, text = cached(unit)
        if text is None:                                   # unit never bought, or bought under another pin
            continue
        recs, stubbed = parse_records(text, unit.case_ids), set()
        if recs is None:
            recs = []
            for half in split_unit(unit):
                if not half.case_ids:
                    continue
                _t, htext = cached(half)
                part = parse_records(htext, half.case_ids) if htext is not None else None
                if part is None:
                    stubbed.update(half.case_ids)
                else:
                    recs.extend(part)
        ok_ids = [c for c in unit.case_ids if c not in stubbed]
        if ok_ids:
            records += [r.record for r in gate_unit(recs, texts, ok_ids, judged, unit.id)]
    return records


def accepted_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged) -> dict:
    """`accepted` (the pre-registered denominator: parsed, gated, `relevant` decided -
    extraction_status "ok" OR "partial") and `accepted_full` (only "ok"). The gap between
    them is why cost per accepted record is a lower bound on the cost of a fully judged
    record (I7)."""
    live = [r for r in records_from_cache(cb, pin, units, source, cache, judged)
            if r.get("extraction_status") != "missing"]
    return {"accepted": sum(1 for r in live if r.get("extraction_status") in ("ok", "partial")
                            and r.get("relevant") is not None),
            "accepted_full": sum(1 for r in live if r.get("extraction_status") == "ok"
                                 and r.get("relevant") is not None)}
```

- [ ] **Step 4: Write `tools/consensus_reference.py`**

```python
"""The who-was-letting reference for the kit cases nobody ever reviewed on that field
(spec section 7, decision D3).

155 of the 195 kit cases came from human-reviewed ledger records, but the review that
produced them was about relevance and polarity: 154 of them carry a who_was_letting value no
human ever checked. Scoring a reader against an unchecked label measures agreement with
whatever the first reader said. So: where at least 4 of the 5 measured finalists returned
the same non-null post-gate value under mapper-v2, that value becomes the reference on a
machine basis; the rest go to the user on a second review page.

Offline. Reads the frozen kit, the measurement-v1 manifest and the purchased response
cache; issues no request and spends nothing.

Usage:
  .venv\\Scripts\\python tools\\consensus_reference.py --dry-run
  .venv\\Scripts\\python tools\\consensus_reference.py
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                          # noqa: E402
from corpus_engine.ledger import open_ledger                          # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                   # noqa: E402
from corpus_engine.reader.cache import ResponseCache                  # noqa: E402
from corpus_engine.reader.codebook import load_codebook               # noqa: E402
from corpus_engine.reader.driver import plan_batch_extraction         # noqa: E402
from corpus_engine.reader.measure import load_kit                     # noqa: E402
from corpus_engine.reader.model import Budget                         # noqa: E402


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIELD = "who_was_letting"
CANDIDATES = ("anthropic/claude-opus-5", "openai/gpt-5.6-terra", "z-ai/glm-5.3",
              "google/gemini-3.7-flash", "anthropic/claude-sonnet-5")
CONSENSUS_K = 4
CONSENSUS_MODEL = "model-consensus:mapper-v2:4of5"
PROMPT_VERSION = "mapper-v2"
RUN_ID = "reference-v2-consensus"
DEFAULT_KIT = "data/reader/kit-v1/kit.json"
DEFAULT_CONTESTED = "data/reader/review/reference-v2/contested-who.json"
DEFAULT_STEM = "reports/review-queue-reference-v2"
UNREVIEWED = "data/reader/review/reference-v1/contested.json"      # carries who_was_letting_unreviewed


def consensus(values: Mapping[str, object], k: int = CONSENSUS_K) -> tuple[object | None, int, int]:
    """The value at least `k` candidates returned, ignoring the ones that returned nothing.
    A null is not a vote: a candidate that left the field blank, or lost it to the gate, is
    silent, not a dissenter. Sorted so an exact tie is resolved the same way every run."""
    counts = Counter(v for v in values.values() if v is not None)
    if not counts:
        return None, 0, 0
    value, n = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
    return (value if n >= k else None), n, sum(counts.values())


def patches_for(agreed: Mapping[int, tuple], records: Mapping[int, dict]) -> list[Patch]:
    """Machine-basis patches. `Basis.can_judge()` needs model + prompt_version + run_id, so
    all three are set; `reviewer` is never set - this is a model consensus, not a review."""
    basis = Basis(model=CONSENSUS_MODEL, prompt_version=PROMPT_VERSION, run_id=RUN_ID)
    out: list[Patch] = []
    for cid in sorted(agreed):
        value, n, non_null = agreed[cid]
        old = (records.get(cid) or {}).get(FIELD)
        why = f"reference v2 consensus: {FIELD} {n} of {non_null} finalists agreed"
        out.append(Patch(int(cid), "set", FIELD, value, why, basis))
        out.append(Patch(int(cid), "append", "review.notes",
                         f"reference v2 consensus: {FIELD} {old!r} -> {value!r} "
                         f"({n} of {non_null} finalists under mapper-v2; never human-reviewed)",
                         why, basis))
    return out


def contested_doc(splits: Mapping[int, tuple], texts: Mapping[int, object],
                  reference: Mapping[int, dict], per_candidate: Mapping[int, Mapping[str, object]]) -> dict:
    """A contested-style document for make_reference_review.build_pages: one entry per case
    the finalists could not agree 4-of-5 on, contested on who_was_letting only."""
    contested = []
    for cid in sorted(splits):
        _value, n, non_null = splits[cid]
        values = dict(per_candidate.get(cid) or {})
        top = sorted(Counter(v for v in values.values() if v is not None).items(),
                     key=lambda kv: (-kv[1], str(kv[0])))
        t = texts.get(cid)
        contested.append({
            "case_id": int(cid),
            "name": getattr(t, "name", ""), "cite": getattr(t, "cite", ""),
            "court": getattr(t, "court", ""), "jurisdiction": getattr(t, "jurisdiction", ""),
            "year": getattr(t, "year", None),
            "contested_fields": [FIELD],
            "reference": {"relevant": (reference.get(cid) or {}).get("relevant"),
                          "polarity": (reference.get(cid) or {}).get("polarity"),
                          FIELD: (reference.get(cid) or {}).get(FIELD)},
            "majority": {FIELD: {"majority_value": top[0][0] if top else None,
                                 "majority_n": top[0][1] if top else 0,
                                 "non_null_n": non_null,
                                 "reference_value": (reference.get(cid) or {}).get(FIELD)}},
            "candidates": {c: {"record_present": c in values,
                               FIELD: {"model_value": values.get(c), "gated_value": values.get(c),
                                       "gate_nulled": False}}
                           for c in CANDIDATES},
            "evidence_for_majority": {FIELD: []},
            "evidence_for_reference": {FIELD: []},
        })
    return {"generated_from": {"kit": DEFAULT_KIT, "cache": "data/reader/cache",
                               "manifest": "data/reader/measurement-v1/manifest.json",
                               "candidates": list(CANDIDATES)},
            "method": (f"Decision D3: the who_was_letting reference for kit cases never reviewed on "
                       f"that field is the value at least {CONSENSUS_K} of the {len(CANDIDATES)} "
                       f"finalists returned (post-gate, under mapper-v2). These are the cases where "
                       f"they did not; no quote evidence is offered because the field is not "
                       f"quote-gated."),
            "counts": {"splits": len(contested)},
            "contested": contested}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kit", default=DEFAULT_KIT)
    ap.add_argument("--out", default=DEFAULT_CONTESTED)
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    mr = _tool("measure_reader")
    mrr = _tool("make_reference_review")
    dom = load_domain()
    cb = load_codebook(dom, PROMPT_VERSION)
    reference_rows, batches, source = load_kit(ROOT / a.kit)
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    manifest = json.loads((ROOT / "data" / "reader" / "measurement-v1" / "manifest.json")
                          .read_text(encoding="utf-8"))
    ids = {int(r["case_id"]) for r in json.loads((ROOT / UNREVIEWED).read_text(encoding="utf-8"))
           ["who_was_letting_unreviewed"]}
    print(f"{len(ids)} kit cases were never human-reviewed on {FIELD}", flush=True)

    per_candidate: dict[int, dict[str, object]] = {cid: {} for cid in ids}
    for model_id in CANDIDATES:
        label = (manifest.get("pins") or {}).get(model_id)
        if not label:
            sys.exit(f"measurement-v1 manifest has no pin for {model_id}")
        pin = mr.pin_from_label(label, dom.reader.families)
        units = plan_batch_extraction(batches, cb.id, pin, Budget(), worker="reader").units
        recs = mr.records_from_cache(cb, pin, units, source, cache, cb.judged_fields)
        found = 0
        for r in recs:
            cid = int(r.get("case_id"))
            if cid in ids and r.get("extraction_status") != "missing":
                per_candidate[cid][model_id] = r.get(FIELD)
                found += 1
        print(f"  {model_id:<32} {found:>4} cached records over those cases", flush=True)

    agreed, splits = {}, {}
    for cid in sorted(ids):
        value, n, non_null = consensus(per_candidate[cid])
        (agreed if value is not None else splits)[cid] = (value, n, non_null)
    print(f"consensus ({CONSENSUS_K} of {len(CANDIDATES)}): {len(agreed)} agreed, {len(splits)} split",
          flush=True)

    led = open_ledger(domain=dom)
    patches = patches_for(agreed, led.view().state.records)
    res = led.apply(patches, note="reference v2 who-was-letting consensus", dry_run=a.dry_run)
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)

    split_ids = sorted(splits)
    texts = {t.case_id: t for t in source.fetch(split_ids)} if split_ids else {}
    doc = contested_doc(splits, texts, {int(r["case_id"]): r for r in reference_rows}, per_candidate)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    html, md, _n = mrr.build_pages(out, ROOT / a.out_stem)
    print(f"wrote {out.as_posix()}, {html.as_posix()} and {md.as_posix()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_consensus_reference.py tests/test_measure_reader_tool.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 6: Run the tool (offline, no spend), then hand the page to the user**

```bash
.venv/Scripts/python tools/consensus_reference.py --dry-run
.venv/Scripts/python tools/consensus_reference.py
```
Expected: both counts printed (agreed / split), `replay_ok=True`, and the second review page written. Publish `reports/review-queue-reference-v2.html` as an Artifact with `capabilities={"artifact": {}}` so the user can decide the splits, exactly as the v1 page was published. Then:

```bash
git add tools/consensus_reference.py tools/measure_reader.py tests/test_consensus_reference.py data/ledger data/reader/review/reference-v2 reports/review-queue-reference-v2.html reports/review-queue-reference-v2.md
git commit -m "reference v2: 4-of-5 who-was-letting consensus on the never-reviewed kit cases; splits to a second review page"
```

When the user returns that second page saved, apply it with the Task 5 tool before Task 7's kit build:

```bash
.venv/Scripts/python tools/apply_reference_review.py --saved reports/review-queue-reference-v2.html --field-order who_was_letting,polarity
```

---
### Task 7: Kit v2 — same 195 cases, patched labels, recorded exclusions

**Files:**
- Modify: `tools/build_reader_kit.py` (rewritten with a `--case-ids-from` mode and importable functions), `domains/str-right-to-let/domain.yaml`, `tests/test_reader_model.py` (the `reader:` assertions)
- Create: `tests/test_build_reader_kit.py`, `data/reader/kit-v2/{kit.json,batches/,sample-50.json}` (generated)

**Interfaces:**
- Consumes: `open_ledger().view()` (`state.records`, `state.order`, `state.in_file`), `StoreCaseSource`, `kit_sample_50`, the `needs-review:<field>` flags Task 5 writes.
- Produces (Task 9 consumes these):
  - `tools/build_reader_kit.case_ids_from(kit_path: Path) -> list[dict]` — `[{"case_id", "source", "era", "jurisdiction"}, ...]` in the existing kit's order.
  - `tools/build_reader_kit.reference_rows(rows, records: Mapping[int, dict], flags: Mapping[int, list[str]]) -> list[dict]` — reference rows carrying `case_id, source, era, jurisdiction, relevant, polarity, who_was_letting, excluded_fields`.
  - `tools/build_reader_kit.make_batches(reference, signals: Mapping[int, list], version: str, size: int = 18) -> list[dict]`.
  - `domain.yaml`: `reader.codebook: mapper-v3`, `reader.kit_path: data/reader/kit-v2/kit.json`, `reader.kit_sha256`, `reader.stability_sample: data/reader/kit-v2/sample-50.json`, the five candidates (two of them `provider: claude-cli` with a `cli_model`), and family entries for both `claude-cli/*` ids.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_reader_kit.py
"""Kit v2 is kit v1's 195 cases with the labels the ledger now carries. What has to hold:
the same case ids in the same batching, `irrelevant` normalised out of polarity (D2), and
the fields the reviewer marked unsure recorded per case so scoring can drop them for that
field only (D6). Imported by path because tools/ is scripts, not a package."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_reader_kit", ROOT / "tools" / "build_reader_kit.py")
brk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brk)

ROWS = [{"case_id": 1, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
        {"case_id": 2, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
        {"case_id": 3, "source": "human", "era": "1860-1900", "jurisdiction": "Mass."},
        {"case_id": 4, "source": "machine", "era": "1860-1900", "jurisdiction": "Mass."}]
RECORDS = {1: {"relevant": True, "polarity": "irrelevant", "who_was_letting": "unclear"},
           2: {"relevant": True, "polarity": "mixed", "who_was_letting": "householder"},
           3: {"relevant": False, "polarity": "adverse", "who_was_letting": "commercial_operator"},
           4: {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"}}
FLAGS = {2: ["needs-review:who_was_letting", "polarity-open-question"], 3: ["needs-review:polarity"]}


def test_reference_rows_normalise_polarity_and_record_the_exclusions():
    out = {r["case_id"]: r for r in brk.reference_rows(ROWS, RECORDS, FLAGS)}
    # `irrelevant` is not a polarity value; the case stays relevant and its polarity is undecided
    assert out[1]["relevant"] is True and out[1]["polarity"] is None and out[1]["who_was_letting"] == "unclear"
    assert out[2]["polarity"] == "mixed" and out[2]["excluded_fields"] == ["who_was_letting"]
    # a case the ledger now calls irrelevant carries no polarity and no who_was_letting
    assert out[3]["relevant"] is False and out[3]["polarity"] is None and out[3]["who_was_letting"] is None
    assert out[3]["excluded_fields"] == ["polarity"]
    # a machine row keeps its machine-irrelevant label whatever the ledger says: it is the
    # control sample, scored separately and never toward the bar
    assert out[4]["source"] == "machine" and out[4]["relevant"] is False and out[4]["polarity"] is None
    assert out[1]["excluded_fields"] == []


def test_make_batches_is_deterministic_and_keeps_every_case():
    reference = brk.reference_rows(ROWS, RECORDS, FLAGS)
    a = brk.make_batches(reference, {1: [{"selector_id": "s"}]}, "kit-v2")
    b = brk.make_batches(reference, {1: [{"selector_id": "s"}]}, "kit-v2")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert [x["batch_id"] for x in a] == ["kit-v2-batch-001", "kit-v2-batch-002"]     # two strata
    ids = sorted(c["case_id"] for x in a for c in x["cases"])
    assert ids == [1, 2, 3, 4]
    assert a[0]["era_partition"] == "1860-1900" and a[0]["jurisdiction"] == "Mass."
    assert a[0]["cases"][0]["signals"] == []
    big = brk.make_batches([dict(ROWS[0], case_id=i, relevant=True, polarity=None,
                                 who_was_letting=None, excluded_fields=[]) for i in range(40)],
                           {}, "kit-v2")
    assert [len(x["cases"]) for x in big] == [18, 18, 4]


def test_case_ids_from_reads_an_existing_kit(tmp_path):
    kit = {"reference": [{"case_id": 7, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
                         {"case_id": 8, "source": "machine", "era": "pre-1860", "jurisdiction": "N.Y."}]}
    p = tmp_path / "kit.json"
    p.write_bytes(json.dumps(kit).encode("utf-8"))
    assert brk.case_ids_from(p) == [{"case_id": 7, "source": "human", "era": "pre-1860", "jurisdiction": "N.Y."},
                                    {"case_id": 8, "source": "machine", "era": "pre-1860", "jurisdiction": "N.Y."}]


def test_kit_v1_is_still_the_kit_v1_the_measurement_bought(repo_root):
    """kit-v1 is never edited: measurement-v1's numbers are only meaningful against it."""
    import hashlib
    raw = (repo_root / "data/reader/kit-v1/kit.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == \
        "b393f2863feef6c9f1810c2bdeb2af983f695aa9d64604ab3db8be364160891f"
```

And update `tests/test_reader_model.py::test_domain_reader_spec` to the v2 configuration:

```python
def test_domain_reader_spec():
    r = load_domain().reader
    assert r.codebook == "mapper-v3" and r.codebooks_dir.endswith("codebooks") and r.checker_sample_pct == 10
    assert set(("characterization", "polarity", "holding_summary")) <= set(r.judged_fields)
    assert r.families["anthropic/claude-sonnet-5"] == "anthropic"
    assert r.families["claude-cli/claude-sonnet-5"] == "anthropic" and r.families["claude-cli/claude-opus-5"] == "anthropic"
    assert [c["model_id"] for c in r.candidates] == [
        "claude-cli/claude-sonnet-5", "claude-cli/claude-opus-5", "openai/gpt-5.6-terra",
        "z-ai/glm-5.3", "google/gemini-3.7-flash"]
    subs = [c for c in r.candidates if c.get("provider") == "claude-cli"]
    assert [c["cli_model"] for c in subs] == ["claude-sonnet-5", "claude-opus-5"]
    assert r.kit_path == "data/reader/kit-v2/kit.json" and r.stability_sample == "data/reader/kit-v2/sample-50.json"
    assert r.kit_sha256 and len(r.kit_sha256) == 64
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_build_reader_kit.py tests/test_reader_model.py -q`
Expected: FAIL — `AttributeError: module 'build_reader_kit' has no attribute 'reference_rows'`, and the domain assertions fail on `mapper-v2`.

- [ ] **Step 3: Rewrite `tools/build_reader_kit.py`**

```python
"""Freeze a reader kit: reference labels, batches, and the case texts inlined.

v1 (2026-09-04) chose its cases: 155 human-reviewed ledger records plus 40 machine-labelled
irrelevant reads. v2 rebuilds THE SAME 195 cases from the patched ledger, so the two kits are
comparable case by case and the only thing that moved is the labels. kit-v1 is never edited.

Usage:
  .venv\\Scripts\\python tools\\build_reader_kit.py --case-ids-from data/reader/kit-v1/kit.json --out data/reader/kit-v2
"""
from __future__ import annotations
import argparse, hashlib, json, random, sys, time
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import open_ledger                                     # noqa: E402
from corpus_engine.ranker.labels import labelled_reads, read_extractions         # noqa: E402
from corpus_engine.reader.measure import KIT_SEED, POLARITY_VALUES, kit_sample_50  # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

BATCH_SIZE = 18
FLAG_PREFIX = "needs-review:"


def case_ids_from(kit_path: Path) -> list[dict]:
    """The cases an existing kit froze, with the source and stratum each was frozen under."""
    kit = json.loads(Path(kit_path).read_text(encoding="utf-8"))
    return [{"case_id": int(r["case_id"]), "source": r["source"], "era": r["era"],
             "jurisdiction": r["jurisdiction"]} for r in kit["reference"]]


def reference_rows(rows: Sequence[dict], records: Mapping[int, dict],
                   flags: Mapping[int, list]) -> list[dict]:
    """The reference labels for one kit build.

    A human row takes the ledger's current values. `irrelevant` is not a polarity (D2): it
    becomes null, which scoring reads as "the reference did not decide this field", not as a
    value a reader can disagree with. An irrelevant case carries no polarity and no
    who_was_letting at all. A machine row keeps its machine-irrelevant label whatever the
    ledger now says - it is the control sample, scored separately and never toward the bar.
    `excluded_fields` is D6: the fields the reviewer marked unsure, dropped from agreement
    for that field only while the case stays in the kit for fidelity and its other fields."""
    out = []
    for row in rows:
        cid = int(row["case_id"])
        rec = records.get(cid) or {}
        if row["source"] == "human":
            relevant = bool(rec.get("relevant"))
            polarity = rec.get("polarity") if rec.get("polarity") in POLARITY_VALUES else None
            who = rec.get("who_was_letting")
        else:
            relevant, polarity, who = False, None, None
        if not relevant:
            polarity, who = None, None
        excluded = sorted({f[len(FLAG_PREFIX):] for f in (flags.get(cid) or [])
                           if isinstance(f, str) and f.startswith(FLAG_PREFIX)})
        out.append({"case_id": cid, "source": row["source"], "era": row["era"],
                    "jurisdiction": row["jurisdiction"], "relevant": relevant, "polarity": polarity,
                    "who_was_letting": who, "excluded_fields": excluded})
    return out


def make_batches(reference: Sequence[dict], signals: Mapping[int, list], version: str,
                 size: int = BATCH_SIZE) -> list[dict]:
    """Stratum by stratum (era x jurisdiction, sorted), cases in ascending id order, `size`
    to a batch. Deterministic: the same reference and the same signals give the same bytes."""
    groups: dict[tuple, list[int]] = {}
    for r in sorted(reference, key=lambda r: int(r["case_id"])):
        groups.setdefault((r["era"], r["jurisdiction"]), []).append(int(r["case_id"]))
    batches, n = [], 0
    for (era, jur), cids in sorted(groups.items()):
        for j in range(0, len(cids), size):
            n += 1
            batches.append({"batch_id": f"{version}-batch-{n:03d}", "era_partition": era,
                            "jurisdiction": jur,
                            "cases": [{"case_id": c, "signals": list(signals.get(c, []))[:6]}
                                      for c in cids[j:j + size]]})
    return batches


def _signals(conn, ids: Sequence[int]) -> dict:
    sig: dict[int, list] = {}
    for i in range(0, len(ids), 500):
        ch = ids[i:i + 500]
        for cid, sid, ver, mt in conn.execute(
                f"SELECT case_id, selector_id, selector_version, matched_text FROM signals "
                f"WHERE case_id IN ({','.join('?' * len(ch))})", ch):
            sig.setdefault(cid, []).append({"selector_id": sid, "selector_version": ver,
                                            "matched_text": mt or ""})
    return sig


def _fresh_rows(view, conn) -> list[dict]:
    """The v1 selection rule, for a kit built from scratch rather than from an existing one."""
    rows = []
    for cid in view.state.order:
        if view.state.in_file.get(cid) and view.reviewed(cid):
            rows.append({"case_id": int(cid), "source": "human"})
    labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    neg = [l for l in labels if l.label == 0]
    rng = random.Random(KIT_SEED)
    strata: dict[tuple, list] = {}
    for l in neg:
        strata.setdefault((l.era, l.jurisdiction), []).append(l)
    picked = []
    quota = max(1, 45 // len(strata))
    for k in sorted(strata):
        picked += rng.sample(strata[k], min(quota, len(strata[k])))
    rows += [{"case_id": l.case_id, "source": "machine"} for l in picked[:45]]
    ids = [r["case_id"] for r in rows]
    meta = {r[0]: r for r in conn.execute(
        f"SELECT case_id, era_partition, jurisdiction FROM cases WHERE case_id IN "
        f"({','.join('?' * len(ids))})", ids)}
    for r in rows:
        r["era"], r["jurisdiction"] = meta[r["case_id"]][1], meta[r["case_id"]][2]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case-ids-from", default=None,
                    help="an existing kit.json; the new kit freezes exactly its cases")
    ap.add_argument("--out", required=True, help="the kit directory, e.g. data/reader/kit-v2")
    a = ap.parse_args()

    out_dir = ROOT / a.out
    out = out_dir / "kit.json"
    if out.exists():
        sys.exit(f"{out} exists; a new kit is a new version")
    version = out_dir.name
    dom = load_domain()
    conn = store.connect()
    view = open_ledger(domain=dom).view()
    rows = case_ids_from(ROOT / a.case_ids_from) if a.case_ids_from else _fresh_rows(view, conn)
    flags = {int(cid): list((view.state.records.get(cid) or {}).get("review.flags") or [])
             for cid in {r["case_id"] for r in rows}}
    reference = reference_rows(rows, view.state.records, flags)
    ids = [r["case_id"] for r in reference]
    batches = make_batches(reference, _signals(conn, ids), version)
    texts = {str(t.case_id): {"cite": t.cite, "name": t.name, "court": t.court,
                              "jurisdiction": t.jurisdiction, "year": t.year, "raw_text": t.raw_text,
                              "norm_text": t.norm_text, "page_map": t.page_map}
             for t in StoreCaseSource(conn).fetch(ids)}
    kit = {"version": version, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": KIT_SEED,
           "built_from": a.case_ids_from, "reference": reference, "batches": batches, "texts": texts}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batches").mkdir(exist_ok=True)
    out.write_bytes(json.dumps(kit, sort_keys=True).encode("utf-8"))
    for b in batches:
        (out_dir / "batches" / f"{b['batch_id']}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    (out_dir / "sample-50.json").write_bytes(json.dumps(kit_sample_50(reference)).encode("utf-8"))
    excluded = sum(1 for r in reference if r["excluded_fields"])
    human = sum(1 for r in reference if r["source"] == "human")
    print(f"kit {version}: {human} human + {len(reference) - human} machine = {len(reference)} cases, "
          f"{len(batches)} batches, {excluded} cases with an excluded field")
    print("sha256:", hashlib.sha256(out.read_bytes()).hexdigest(), "-> set reader.kit_sha256 in domain.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Build kit v2 (offline; requires Tasks 5 and 6 applied)**

```bash
.venv/Scripts/python tools/build_reader_kit.py --case-ids-from data/reader/kit-v1/kit.json --out data/reader/kit-v2
```
Expected: `kit kit-v2: 155 human + 40 machine = 195 cases, 23 batches, <n> cases with an excluded field`, and a sha256 that differs from kit-v1's. Confirm 195 cases and 23 batches; if either differs, stop — the ledger lost or gained a case and that has to be understood before anything is bought.

- [ ] **Step 5: Point `domain.yaml` at v3/v2 and the five candidates**

In `domains/str-right-to-let/domain.yaml`, under `reader:`:

```yaml
  codebook: mapper-v3
```
```yaml
  families:
    anthropic/claude-sonnet-5: anthropic
    anthropic/claude-opus-5: anthropic
    anthropic/claude-haiku-4.5: anthropic
    claude-cli/claude-sonnet-5: anthropic
    claude-cli/claude-opus-5: anthropic
    google/gemini-3.7-flash: google
    openai/gpt-5.6-terra: openai
    deepseek/deepseek-v4-pro: deepseek
    z-ai/glm-5.3: zai
    minimax/minimax-m3: minimax
    deepseek/deepseek-v4-flash: deepseek
    qwen/qwen3.8-27b: qwen
    codex-cli: openai
  kit_path: data/reader/kit-v2/kit.json
  kit_sha256: "<the sha256 the build printed>"
  stability_sample: data/reader/kit-v2/sample-50.json
  # Slice-1 finalists (spec section 8). The two claude-cli entries run on the user's
  # subscription through the Claude Code CLI (ADR-0007 amendment 2026-09-05); full model
  # names, never aliases, so the pin label is reproducible.
  candidates:
    - {model_id: claude-cli/claude-sonnet-5, family: anthropic, provider: claude-cli, cli_model: claude-sonnet-5}
    - {model_id: claude-cli/claude-opus-5, family: anthropic, provider: claude-cli, cli_model: claude-opus-5}
    - {model_id: openai/gpt-5.6-terra, family: openai}
    - {model_id: z-ai/glm-5.3, family: zai, pin_open: true}
    - {model_id: google/gemini-3.7-flash, family: google}
```

Leave `reader.model` alone: ADR-0007's amendment says the opus-5 pin stands until the remeasurement, and Task 9 replaces it.

- [ ] **Step 6: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_build_reader_kit.py tests/test_reader_model.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 7: Commit**

```bash
git add tools/build_reader_kit.py domains/str-right-to-let/domain.yaml data/reader/kit-v2 tests/test_build_reader_kit.py tests/test_reader_model.py
git commit -m "kit v2: same 195 cases, patched reference labels, per-case field exclusions; domain points at mapper-v3 and the five finalists"
```

---

### Task 8: Driver residuals — required norm version, broad catch in the split loop, honest resume line

**Files:**
- Modify: `corpus_engine/reader/driver.py`, `tests/test_reader_driver.py`, `tools/measure_reader.py` (pass `resume_tool`)

**Interfaces:**
- Consumes: `Plan.resume_tool` (Task 1).
- Produces:
  - `Reader(provider, cases, *, checker=None, cache=None, log=print, clock=time.time, domain=None, store_norm_version)` — `store_norm_version` is now **required** (keyword-only, no default). Passing `None` is still allowed, but only deliberately.
  - `resume_command(plan) -> str` — `f".venv\\Scripts\\python {plan.resume_tool} --only {plan.pin.model_id}"` for a `batch_extraction` plan that names a tool, `""` otherwise; `resume_note(plan) -> str` explains which.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reader_driver.py`:

```python
def test_store_norm_version_is_required_so_the_guard_cannot_be_left_inert(tmp_path, fixture_db):
    """I10. It defaulted to None, and None short-circuits pre-flight check (1) - the check
    that stops a read of texts the codebook was never validated against. A caller now has to
    say what the store holds, even if what it says is None."""
    import pytest
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    with pytest.raises(TypeError, match="store_norm_version"):
        Reader(ScriptedProvider(["[]"]), StoreCaseSource(conn))
    r = Reader(ScriptedProvider(["[]"]), StoreCaseSource(conn), store_norm_version="v1")
    assert r.norm == "v1"


def test_a_defect_in_one_split_half_keeps_the_half_already_paid_for(tmp_path, fixture_db, repo_root):
    """N6. The unit loop catches Exception (an engine defect costs one unit, not the run),
    but the split loop caught only ReaderError and _BudgetStop - so a TypeError raised while
    the second half was being fetched threw away the first half, which had been bought."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude")
    unit = plan.units[0]
    first, _second = split_unit(unit)
    answer = _answer(conn)
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return "this will not parse"
        if calls["n"] == 2:
            return answer(req)
        raise TypeError("engine defect on the second half")

    out = Reader(ScriptedProvider(flaky), StoreCaseSource(conn), log=lambda *_: None, domain=dom,
                 store_norm_version="v1").read(plan)
    u = out.units[0]
    assert u.status == "partial_parse" and u.retried is True and "TypeError" in u.error
    kept = [r for r in u.records if r.record.get("extraction_status") != "missing"]
    assert sorted(r.case_id for r in kept) == sorted(first.case_ids)
    assert out.stop.kind == "done"                       # the run continues


def test_resume_command_names_the_tool_that_built_the_plan():
    """I9 again, one step further: the line has to name a program that exists AND that
    actually built this plan. A plan nothing has a runner for gets no command at all."""
    plan = plan_batch_extraction([], "mapper-v1", PIN, Budget(), worker="reader",
                                 resume_tool="tools\\measure_reader.py")
    assert resume_command(plan) == f".venv\\Scripts\\python tools\\measure_reader.py --only {PIN.model_id}"
    bare = plan_batch_extraction([], "mapper-v1", PIN, Budget(), worker="reader")
    assert resume_command(bare) == ""
    assert "no runner" in resume_note(bare)
    assert plan_judgment([1], "q?", "mapper-v1", PIN, Budget(), worker="reader").resume_tool == ""
```

Update the existing assertion in `test_read_gates_caches_budgets_and_reports`:

```python
    assert out.resume_command == ""          # this plan names no tool; the manifest note says why
```

and add `store_norm_version="v1"` to **every** `Reader(...)` construction in `tests/test_reader_driver.py` (mapper-v1 carries no `validated_norm_version`, so the check stays inert for those plans and nothing else changes). Import `resume_note` alongside `resume_command`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_reader_driver.py -q`
Expected: FAIL — `Reader(...)` still accepts a missing `store_norm_version`; `resume_command` still hard-codes the tool.

- [ ] **Step 3: Implement the three changes in `corpus_engine/reader/driver.py`**

```python
def resume_command(plan: Plan) -> str:
    """A literal CLI line that re-runs this plan (spec section 5); the response cache makes
    the units already bought free.

    It has to name a program that exists AND that built this plan. 3A hard-coded
    tools/measure_reader.py for every batch_extraction plan, which was true while the
    measurement was the only caller and stops being true the moment the map runner exists
    (slice 2). The plan now carries its own tool; a plan that names none gets no command,
    and `manifest["resume"]` says why."""
    if plan.kind == "batch_extraction" and plan.resume_tool:
        return f".venv\\Scripts\\python {plan.resume_tool} --only {plan.pin.model_id}"
    return ""


def resume_note(plan: Plan) -> str:
    if plan.kind == "batch_extraction" and plan.resume_tool:
        return f"re-run through {plan.resume_tool}; units already in the response cache are free"
    return (f"no runner recorded for this {plan.kind!r} plan (the planner passed no resume_tool); "
            f"resume_command is empty by design")
```

```python
class Reader:
    def __init__(self, provider, cases, *, checker=None, cache: ResponseCache | None = None, log=print,
                 clock=time.time, domain=None, store_norm_version):
```

and in the split loop, widen the handler (the body is unchanged except for the message):

```python
                        except Exception as exc:            # noqa: BLE001 - see the unit handler
                            # A half that never ran (budget tripped, N1), died on a provider
                            # error (I2), or hit an engine defect (N6) must not take the other
                            # half's paid, parsed records with it: what was bought is kept, only
                            # the rest is stubbed.
                            budget = isinstance(exc, _BudgetStop)
                            detail = "" if budget else f"{type(exc).__name__}: {exc}"
                            note = ("budget stop before split half" if budget else
                                    f"failed on split half ({type(exc).__name__})")
                            for cid in (c for h in halves[i:] for c in h.case_ids):
                                stub_notes[cid] = note
                            units.append(UnitResult(unit.id, "partial_parse",
                                                    self._assemble(unit, texts, recs, judged, stub_notes), resp, hit,
                                                    detail[:300], retried=True))
                            if budget:
                                raise
                            self.log(f"{unit.id}: split half FAILED {detail}")
                            continue
```

- [ ] **Step 4: Have the measurement tool name itself**

In `tools/measure_reader.py`, `run_candidate` builds its plan with `resume_tool=RESUME_TOOL` (the module already defines `RESUME_TOOL = "tools\\measure_reader.py"` in `driver.py`; import it or repeat the literal in the tool):

```python
from corpus_engine.reader.driver import RESUME_TOOL, Reader, plan_batch_extraction   # noqa: E402
...
    plan = plan_batch_extraction(kit_batches, cb.id, pin, budget, worker="reader",
                                 json_schema=record_schema(cb), resume_tool=RESUME_TOOL)
```

- [ ] **Step 5: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_reader_driver.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/reader/driver.py tools/measure_reader.py tests/test_reader_driver.py
git commit -m "reader driver: store_norm_version required, split loop keeps the paid half on any defect, resume line names the plan's own tool"
```

---

### Task 9: The remeasurement — two dry runs, five candidates, winner's checks, report

**This is the only task that spends.** It spends OpenRouter credits up to **$15 total** (D5) and subscription units. Nothing here may be run from another task.

**Files:**
- Modify: `tools/measure_reader.py`, `tests/test_measure_reader_tool.py`, `domains/str-right-to-let/domain.yaml` (`reader.model`), `docs/adr/0007-llm-access-is-provider-neutral-and-model-choice-is-measured.md`, `reports/handoff-cycle-004.md`
- Create: `reports/reader-measurement-v2.md`, `data/reader/measurement-v2/manifest.json` (generated), `data/reader/measurement-v2/dry-run-*.json` (generated), `domains/str-right-to-let/codebooks/stability/<mapper-v3 sha>.json` (generated)

**Interfaces:**
- Consumes: `ClaudeCliProvider` (T2), `record_schema`/`schema_sha` (T1), `effort_of` (T1), `field_scores`/`score_candidate`/`select_reader`/`excluded_fields` (T4), kit v2 and the five candidates (T7), `Plan.resume_tool` (T8).
- Produces: `is_subscription(cand)`, `cli_pin(cand)`, `provider_for(cand, or_prov, timeout=READ_TIMEOUT)`, `budget_for(cand, remaining_usd)`, `keys_for(units, cb, pin, source, cache, schema)`, constants `OPENROUTER_CEILING = 15.0`, `EFFORT = "low"`, `SUBSCRIPTION_MAX_UNITS`, `SUBSCRIPTION_MAX_WALL_SECONDS`, `OUT_DIR = "measurement-v2"`, `DRY_RUN_MAX_USD = 2.0`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_measure_reader_tool.py`:

```python
def test_a_subscription_candidate_gets_a_cli_pin_and_a_unit_budget():
    """D1/D5: the subscription has no dollar price, so its ceilings are units and
    wall-clock. A usd budget over it is not a budget - `spend` would stay 0.0 for every
    request - and pre-flight refuses one (test_reader_claude_cli.py)."""
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    assert mr.is_subscription(cand) and not mr.is_subscription({"model_id": "z-ai/glm-5.3", "family": "zai"})
    pin = mr.cli_pin(cand)
    assert pin.label == "claude-cli/claude-sonnet-5@claude-cli:-" and pin.family == "anthropic"
    assert pin.extra == {"effort": "low", "cli_model": "claude-sonnet-5"}
    b = mr.budget_for(cand, 15.0)
    assert b.max_usd is None and b.max_units == mr.SUBSCRIPTION_MAX_UNITS
    assert b.max_wall_seconds == mr.SUBSCRIPTION_MAX_WALL_SECONDS
    b2 = mr.budget_for({"model_id": "z-ai/glm-5.3", "family": "zai"}, 12.5)
    assert b2.max_usd == 12.5 and b2.max_units is None and b2.max_wall_seconds is None
    assert mr.budget_for({"model_id": "x/y", "family": "f"}, -3.0).max_usd == 0.0


def test_the_openrouter_ceiling_for_this_slice_is_fifteen_dollars():
    assert mr.OPENROUTER_CEILING == 15.0
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "exceeds this slice's approved OpenRouter ceiling" in src
    assert "measurement-v2" in src and "record_schema(cb)" in src


def test_provider_for_returns_the_cli_transport_for_a_subscription_candidate(monkeypatch):
    cand = {"model_id": "claude-cli/claude-opus-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-opus-5"}
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    provider, pin, why = mr.provider_for(cand, None)
    assert provider.name == "claude-cli" and provider.cli_model == "claude-opus-5"
    assert pin.model_id == "claude-cli/claude-opus-5" and "2.1.258" in why
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: None)
    provider2, pin2, why2 = mr.provider_for(cand, None)
    assert provider2 is None and pin2 is None and "not available" in why2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_measure_reader_tool.py -q`
Expected: FAIL — `AttributeError: module 'measure_reader' has no attribute 'is_subscription'`.

- [ ] **Step 3: Bring `tools/measure_reader.py` to v2**

Add the imports:

```python
from corpus_engine.reader.driver import RESUME_TOOL, Reader, plan_batch_extraction            # noqa: E402
from corpus_engine.reader.measure import (excluded_fields, load_kit, score_candidate,          # noqa: E402
                                          select_reader, stability_agreement)
from corpus_engine.reader.model import Budget, ModelPin, Request, effort_of                    # noqa: E402
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider                        # noqa: E402
from corpus_engine.reader.schema import record_schema, schema_sha                              # noqa: E402
```

Replace the budget/effort constants block with:

```python
EFFORT = "low"
REASONING = {"effort": EFFORT}
READ_TIMEOUT = 1500
# D5: the whole slice's OpenRouter spend. Three candidates over the kit plus, if the winner
# is an OpenRouter model, its stability pair and batch-size pair. The subscription has no
# dollar budget; its ceilings are units and wall-clock.
OPENROUTER_CEILING = 15.0
SUBSCRIPTION_PROVIDER = "claude-cli"
# 23 kit batches, plus headroom for the split halves a parse failure falls back to.
SUBSCRIPTION_MAX_UNITS = 60
SUBSCRIPTION_MAX_WALL_SECONDS = 6 * 3600
DRY_RUN_MAX_USD = 2.0
OUT_DIR = "measurement-v2"
STABILITY_BAR = 0.90
```

Add the provider/budget selection:

```python
def is_subscription(cand: dict) -> bool:
    return cand.get("provider") == SUBSCRIPTION_PROVIDER


def cli_pin(cand: dict) -> ModelPin:
    """Full model names, never aliases (`claude-sonnet-5`, not `sonnet`), so the pin label
    is reproducible and the cache key it feeds means one thing."""
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
    pin, why = pin_for(cand, prov)
    return (prov if pin is not None else None), pin, why


def budget_for(cand: dict, remaining_usd: float) -> Budget:
    if is_subscription(cand):
        return Budget(max_units=SUBSCRIPTION_MAX_UNITS, max_wall_seconds=SUBSCRIPTION_MAX_WALL_SECONDS)
    return Budget(max_usd=max(remaining_usd, 0.0))


def run_candidate(pin: ModelPin, provider, budget: Budget, kit_batches, source, dom, cb, cache,
                  log, budget_state):
    plan = plan_batch_extraction(kit_batches, cb.id, pin, budget, worker="reader",
                                 json_schema=record_schema(cb), resume_tool=RESUME_TOOL)
    out = Reader(provider, source, cache=cache, log=log, domain=dom,
                 store_norm_version=STORE_NORM_VERSION).read(plan)
    budget_state["remaining"] -= out.spend_usd
    budget_state["spent"] += out.spend_usd
    return out


def keys_for(units, cb, pin: ModelPin, source, cache: ResponseCache, schema) -> dict:
    """The v2 cache key for each unit and for the split halves it falls back to. Only keys
    present in the cache are recorded, so the map is evidence rather than prediction."""
    found = {}
    for unit in units:
        for u in (unit, *split_unit(unit)):
            if not u.case_ids:
                continue
            prompt = render_unit(cb, u, source.fetch(u.case_ids), "reader")
            k = ResponseCache.key(cb.sha, pin, u, prompt, schema_sha=schema_sha(schema),
                                  max_tokens=Request.max_tokens, effort=effort_of(pin))
            if (cache.dir / f"{k}.json").exists():
                found[u.id] = k
    return found
```

Rename the existing v1 helper `keys_for` (used by `annotate`) to `keys_for_v1` and leave its body alone — it addresses the purchased v1 cache with `ResponseCache.key_v1`.

In `main()`:

```python
    ap.add_argument("--max-usd", type=float, default=OPENROUTER_CEILING)
    ap.add_argument("--dry-run", default=None,
                    help="run ONE kit batch for this candidate, write the inspection file, and stop")
```
```python
    if a.max_usd > OPENROUTER_CEILING:
        sys.exit(f"--max-usd {a.max_usd} exceeds this slice's approved OpenRouter ceiling "
                 f"${OPENROUTER_CEILING:.2f} (spec decision D5)")
    out_dir = ROOT / "data" / "reader" / OUT_DIR
```

The candidate loop body becomes:

```python
    subscription = {c["model_id"] for c in dom.reader.candidates if is_subscription(c)}
    excl = excluded_fields(reference)
    schema = record_schema(cb)
    print(f"schema sha {schema_sha(schema)[:12]}; {len(excl)} cases carry an excluded field", flush=True)
    for cand in dom.reader.candidates:
        mid = cand["model_id"]
        if a.only and mid != a.only:
            continue
        if not is_subscription(cand) and budget["remaining"] <= 0:
            not_run[mid] = "budget exhausted before this candidate ran"
            print(f"NOT RUN {mid}: budget exhausted", flush=True)
            continue
        provider, pin, why = provider_for(cand, prov)
        print(f"PIN {mid} -> {pin.label if pin else 'SKIP'}  ({why})", flush=True)
        if pin is None:
            skipped[mid] = why
            continue
        print(f"== {pin.label}  (openrouter remaining ${budget['remaining']:.2f})", flush=True)
        try:
            out = run_candidate(pin, provider, budget_for(cand, budget["remaining"]), batches,
                                source, dom, cb, cache, print, budget)
        except Exception as exc:                                # noqa: BLE001 - one candidate never aborts the run
            failed[mid] = f"run raised {type(exc).__name__}: {str(exc)[:300]}"
            print(f"   FAILED {failed[mid]}", flush=True)
            if not is_subscription(cand):
                reconcile(prov, before, ceiling, budget, print)
            continue
        real_delta = None if is_subscription(cand) else reconcile(prov, before, ceiling, budget, print)
        if out.stop.kind.startswith("preflight:"):
            failed[mid] = f"pre-flight refusal {out.stop.kind}: {out.stop.detail}"
            print(f"   FAILED {failed[mid]}", flush=True)
            continue
        s = score(out, reference, mid, prior_spend, spend_by, tracked_by, real_delta, excluded=excl)
        ...
        timeouts[mid] = READ_TIMEOUT
        efforts[mid] = EFFORT
        cache_keys[mid] = {"pin": pin.label, "units": keys_for(out.plan.units, cb, pin, source, cache, schema)}
```

`score()` gains the `excluded` keyword and passes it through to `score_candidate`; a subscription run is unpriced by construction (`score_candidate` sees `cost_usd is None` on every response), so `spend_by[mid]` stays 0.0 and `list_cost_by[mid] = s["list_cost_usd"]`.

Selection and manifest:

```python
    sel = select_reader(merged_scores, subscription=subscription)
    manifest = {"kit_sha256": dom.reader.kit_sha256, "kit_path": dom.reader.kit_path,
                "codebook": cb.id, "codebook_sha": cb.sha, "schema_sha": schema_sha(schema),
                "openrouter_ceiling_usd": OPENROUTER_CEILING, "budget_usd": a.max_usd,
                "prior_spend_usd": round(prior_usd, 4), "prior_spend_source": why_prior,
                "effective_budget_usd": round(ceiling, 4),
                "subscription_candidates": sorted(subscription),
                "subscription_budget": {"max_units": SUBSCRIPTION_MAX_UNITS,
                                        "max_wall_seconds": SUBSCRIPTION_MAX_WALL_SECONDS},
                "reasoning": REASONING, "effort_by_candidate": efforts,
                "read_timeout_by_candidate": timeouts, "max_tokens": Request.max_tokens,
                "batch_size": 18, "cache_keys": cache_keys,
                "excluded_fields_by_case": {str(k): sorted(v) for k, v in excl.items()},
                "list_cost_by_candidate": list_cost_by,
                "pins": pins, "skipped": skipped, "failed": failed, "not_run": not_run,
                "scores": scores, "selection": sel, "spend_by_candidate": spend_by,
                "tracked_spend_by_candidate": tracked_by,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
```

Dry-run mode, placed right after the codebook is loaded and the provisional stability record is written:

```python
    if a.dry_run:
        cand = next((c for c in dom.reader.candidates if c["model_id"] == a.dry_run), None)
        if cand is None:
            sys.exit(f"{a.dry_run} is not a candidate in domain.yaml")
        provider, pin, why = provider_for(cand, prov)
        if pin is None:
            sys.exit(f"cannot run {a.dry_run}: {why}")
        one = batches[:1]
        print(f"DRY RUN {pin.label} over {one[0]['batch_id']} ({len(one[0]['cases'])} cases): {why}", flush=True)
        out = run_candidate(pin, provider, budget_for(cand, min(ceiling, DRY_RUN_MAX_USD)), one,
                            source, dom, cb, cache, print, budget)
        s = score_candidate(out, reference, excluded=excluded_fields(reference))
        payload = {"candidate": a.dry_run, "pin": pin.label, "why": why, "batch": one[0]["batch_id"],
                   "schema_sha": schema_sha(record_schema(cb)), "stop": out.stop.kind,
                   "units": [{"unit_id": u.unit_id, "status": u.status, "cache_hit": u.cache_hit,
                              "retried": u.retried, "error": u.error,
                              "finish_reason": (u.response.finish_reason if u.response else None),
                              "input_tokens": (u.response.input_tokens if u.response else None),
                              "output_tokens": (u.response.output_tokens if u.response else None),
                              "list_cost_usd": ((u.response.raw or {}).get("list_cost_usd") if u.response else None)}
                             for u in out.units],
                   "status_counts": {st: sum(1 for r in out.records if r.get("extraction_status") == st)
                                     for st in ("ok", "partial", "extraction-invalid", "missing")},
                   "nulled_fields": sorted({f for u in out.units for r in u.records for f in r.nulled_fields}),
                   "dropped_quotes": sum(r.dropped_quotes for u in out.units for r in u.records),
                   "score": s, "spend_usd": out.spend_usd, "first_record": (out.records or [None])[0]}
        write_json(out_dir / f"dry-run-{a.dry_run.replace('/', '_')}.json", payload, indent=1, sort_keys=True)
        print(dumps({k: payload[k] for k in ("stop", "status_counts", "nulled_fields",
                                             "dropped_quotes", "spend_usd")}, indent=1), flush=True)
        return 0
```

Guard the OpenRouter credits pre-checks so a subscription-only invocation needs no key: read `OPENROUTER_API_KEY` and call `/credits` only when the candidates about to run include a non-subscription one.

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest tests/test_measure_reader_tool.py -q` — Expected: PASS.
Run: `.venv/Scripts/python -m pytest -q` — Expected: green. **Commit before spending anything.**

```bash
git add tools/measure_reader.py tests/test_measure_reader_tool.py
git commit -m "measure_reader v2: provider per candidate, subscription unit budget, $15 OpenRouter ceiling, dry-run mode"
```

- [ ] **Step 5: GATE — dry run 1, the cheapest OpenRouter candidate (one batch, ≤ $2)**

Pre-checks: `OPENROUTER_API_KEY` in `.env`; `GET /credits` ≥ $15; kit sha256 matches `domain.yaml`.

```bash
.venv/Scripts/python tools/measure_reader.py --dry-run google/gemini-3.7-flash --max-usd 15
```

Inspect `data/reader/measurement-v2/dry-run-google_gemini-3.7-flash.json` before anything else runs, and confirm **all** of:
1. the response parsed on the first ask (`units[0].retried` is `false`, `status` is `ok`);
2. `status_counts` has no `missing` and few `partial`;
3. `nulled_fields` is empty or explainable — a judged field nulled here means the model filled it and named it in no quote's `supports`, which is exactly what mapper-v3 was rewritten to prevent;
4. `first_record` shows an array-valued `supports` and a `polarity` inside the v3 vocabulary (never `"irrelevant"`);
5. `schema_sha` is present and the response respected it (no schema-rejection error in `units[].error`);
6. `spend_usd` is a small fraction of $15.

If a candidate's response is rejected because it named a `supports` value outside the schema's enum (the enum is judged fields + `relevant`, per spec section 4), record it in the report and stop for a decision rather than absorbing it silently.

- [ ] **Step 6: GATE — dry run 2, Sonnet through the CLI (one batch, no dollars)**

```bash
.venv/Scripts/python tools/measure_reader.py --dry-run claude-cli/claude-sonnet-5 --max-usd 15
```

Inspect `dry-run-claude-cli_claude-sonnet-5.json` for the same six points, plus:
7. `units[].list_cost_usd` is populated and `spend_usd` is `0.0` (the subscription is unpriced, and nothing about it may be counted as a charge);
8. the run used the subscription: no `ANTHROPIC_API_KEY` was passed (assert by checking `claude` did not error on an invalid key, and that the manifest's provider is `claude-cli`);
9. wall time per batch is recorded — it sets the expectation for `SUBSCRIPTION_MAX_WALL_SECONDS` over 23 batches.

Commit both dry-run files: `git add data/reader/measurement-v2 && git commit -m "measurement v2: two one-batch dry runs inspected before the field run"`.

- [ ] **Step 7: The field run — five candidates over kit v2**

```bash
.venv/Scripts/python tools/measure_reader.py --max-usd 15
```
Foreground, expect 1–4 hours (the two subscription candidates run 23 batches each through a CLI subprocess and may sit out a usage-limit wait of up to an hour per throttle). If it stops on budget or on the subscription's unit/wall ceiling, the manifest records what ran; re-running resumes from the cache for free. Record for the report: each candidate's pin as served, fidelity, per-field `decided_rate` and `agreement_decided`, macro, accepted / accepted_full, cost per accepted record (OpenRouter) or `list_cost_usd` with `priced: false` (subscription), wall time, stop reason, and the selection with the rule that fired.

- [ ] **Step 8: The winner's checks**

The tool runs these automatically once a winner is chosen: the batch-size pair (5-case batches over the same kit) and the stability check (two reads of `data/reader/kit-v2/sample-50.json`, stable at ≥ 0.90 per field on decided answers). Both use the winner's own provider and budget kind. Confirm the mapper-v3 stability record was written to `domains/str-right-to-let/codebooks/stability/<mapper-v3 sha>.json` with `provisional` gone, and that the OpenRouter total is at or under $15.

- [ ] **Step 9: Pin the winner and write the report**

Set `domain.yaml` `reader.model` to the winner the tool prints (`model_id`, `family`, `provider_name`, `precision`, `extra`) — for a subscription winner that is `{model_id: claude-cli/<name>, family: anthropic, provider_name: claude-cli, precision: null, extra: {effort: low, cli_model: <name>}}`.

Write `reports/reader-measurement-v2.md` with:
- the pre-registration: bar D4 (fidelity 0.97, decided rate 0.90 per field, macro 0.85, subscription tie-break within 0.02, shortfall rule), fixed here before any read, with the codebook sha, kit sha, schema sha, batch size 18, effort low, max_tokens 64000, read timeout 1500 s;
- what changed since v1 and why: `mixed` defined, `irrelevant` no longer a polarity, `supports` an array with the erasure rule stated, polarity scored only where both sides say relevant, decided rate reported separately from agreement;
- the reference: how many of the 71 contested labels the user kept / adopted / set / marked unsure (from Task 5), how many of the 154 never-reviewed who-was-letting labels the 4-of-5 consensus settled and how many went to the second page (from Task 6), and the count of cases carrying an excluded field (D6);
- the candidate table: pin as served, fidelity, per-field decided rate and agreement, macro, accepted / accepted_full, schema compliance, cost per accepted (or UNPRICED with the list cost), wall, stop;
- skipped and failed candidates with reasons;
- the selection: the rule that fired, whether a shortfall was disclosed, and — if a subscription candidate won on the 0.02 tie-break — the exact macro gap;
- the batch-size pair and the stability result against the 0.90 bar;
- spend: OpenRouter charged against the $15 ceiling (credits-reconciled), and the subscription's units and wall-clock with the list-price equivalent recorded as **not** a charge;
- the two dry runs and what they showed;
- the licence note already recorded in ADR-0007's amendment, referenced, not re-argued.

Append to `docs/adr/0007-*.md` a short result note under the 2026-09-05 amendment: the five candidates, the winner and rule, whether the bar was met, the mapper-v3 stability result, and that `reader.model` now points at it.

Update `reports/handoff-cycle-004.md` item 7: mark the slice-1 remeasurement done, name the winner, state whether the 0.85 bar was met this time, and point at `reports/reader-measurement-v2.md`. Add a handoff item for slice 2 (the cycle-004 map runner and its per-cell budget) noting that the reader is now pinned and the kit is v2.

- [ ] **Step 10: Full suite, commit**

Run: `.venv/Scripts/python -m pytest -q` — Expected: green.

```bash
git add tools/measure_reader.py data/reader/measurement-v2 domains/str-right-to-let reports/reader-measurement-v2.md docs/adr/0007-llm-access-is-provider-neutral-and-model-choice-is-measured.md reports/handoff-cycle-004.md tests/test_measure_reader_tool.py
git commit -m "reader measurement v2: five finalists on mapper-v3 and kit v2 under the D4 bar; reader.model re-pinned"
```

---

## Self-review notes (done while writing)

**1. Spec coverage**

| Spec section | Where it is implemented |
| --- | --- |
| 1 Goal | the plan as a whole; T9 closes it |
| 2 D1 subscription reader, Codex checker | T2 (provider), T7 (candidates), T9 (run) |
| 2 D2 `mixed` defined, `irrelevant` not a polarity | T3 (codebook, CONTEXT, ADR-0004), T1 (schema enum), T4 (`_decided`), T7 (kit normalisation) |
| 2 D3 4-of-5 who-was-letting consensus, splits to a page | T6 |
| 2 D4 remeasurement bar and tie-break | T4 (`select_reader`), T9 (applied, pre-registered in the report) |
| 2 D5 $15 OpenRouter cap, subscription on units/wall | Global Constraints, T9 (`OPENROUTER_CEILING`, `budget_for`) |
| 2 D6 `unsure` excluded for that field only | T5 (flag), T7 (`excluded_fields` in the kit), T4 (`excluded=` in scoring) |
| 3 Claude CLI provider (argv, env, envelope, throttle, pin) | T2 |
| 4 Request schema, both parse shapes, widened cache key | T1 |
| 5 Codebook mapper-v3, CONTEXT.md, ADR-0004 | T3 |
| 6 Scoring v2, `select_reader`, manifest v2 fields, measurement-v2 dir | T4 (scoring), T9 (manifest, directory) |
| 7 `apply_reference_review.py`, `consensus_reference.py`, kit v2 + domain.yaml | T5, T6, T7 |
| 8 Remeasurement: candidates, settings, dry runs, field run, winner's checks, outputs | T9 |
| 9 Driver residuals (I10, N6, N4/resume) | T8 |
| 10 Testing (provider, schema, cache key, scoring, apply, consensus, kit determinism, render golden, live dry runs) | T2, T1, T1, T4, T5, T6, T7, T3, T9 steps 5–6 |
| 11 Constraints | Global Constraints, enforced per task |

No spec section is without a task.

**2. Placeholder scan**

No "TBD", "TODO", "handle edge cases", "similar to Task N", or test steps without test code. Every code step carries the actual code to transcribe. Three values are deliberately filled in at run time and are not placeholders: `reader.kit_sha256` (printed by the Task 7 build), `reader.model` (printed by the Task 9 run), and the stability record's filename (the mapper-v3 sha). Task 5 step 6 and Task 6 step 6 wait on a file the *user* produces; both say so explicitly and tell the implementer to stop rather than invent it.

**3. Type consistency**

- `record_schema(codebook)` / `schema_sha(schema)` — defined T1, used T1 (driver), T9 (plan, manifest, dry run).
- `effort_of(pin)` — defined T1 (model.py), used T1 (driver cache key), T9 (`keys_for`).
- `Response.raw` — added T1, written T2 (`list_cost_usd`), read T4 (`score_candidate`), reported T9.
- `Plan.json_schema` / `Plan.resume_tool` — added T1, `resume_tool` consumed T8 (`resume_command`) and set T9.
- `ResponseCache.key(..., schema_sha=, max_tokens=, effort=)` vs `key_v1(...)` — the same two names in T1, T6 (`records_from_cache` uses `key_v1`) and T9 (`keys_for` uses `key`); no third spelling.
- `score_candidate(outcome, reference, *, spend_usd_override=None, excluded=None)` and `select_reader(scores, *, subscription=...)` — defined T4, called T9 with exactly those keywords; the score keys `fields`/`macro`/`accepted_full`/`list_cost_usd` are read by T4's `line()`, T9's manifest and the report, and nowhere else.
- `excluded_fields(reference)` (T4) reads the `excluded_fields` list that `reference_rows` (T7) writes, which holds the `needs-review:<field>` flags that `patches_for` (T5) appends — one prefix constant, `needs-review:`, spelled the same in all three (`FLAG_PREFIX`).
- `patches_for` exists in two tools with different signatures (`apply_reference_review.patches_for(decisions, records, reviewer, ...)` and `consensus_reference.patches_for(agreed, records)`); they are module-scoped in scripts that are never imported together except by their own tests, and each task's Interfaces block gives the full signature.
- `ClaudeCliProvider(cli_model, *, runner, timeout, exe, effort, system_default, sleep, delays)` — defined T2, constructed T9 (`provider_for`) with `timeout=` and `effort=` only.

**4. Deviations recorded**

- mapper-v3 changes v2's requirement 5 (output shape) as well as the changes spec section 5 lists, because section 4's schema demands `{"records": [...]}` and a codebook asking for a bare array would contradict it. Recorded in T3's scope note and in the report.
- The record schema's `required` is the four fields `parse.REQUIRED` enforces, not the two the spec names as the minimum; both extra fields are nullable/empty for an irrelevant record. Recorded in `schema.py`'s docstring.
- D4's subscription tie-break is applied in the shortfall branch as well as above the bar (T4, with a test that names the reasoning). The shortfall is disclosed either way and the `rule` string says which branch fired.
