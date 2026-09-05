# Stage 3A — Reader Driver and Reader-Model Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the headless-CLI mapper with `corpus_engine.reader` (Provider and CaseSource ports, quote gate inside the driver, budget/stop/resume, content-keyed cache, checker sampling), then choose the reader model by the pre-registered measurement over a human-adjudicated kit under a $50 ceiling.

**Architecture:** `corpus_engine/reader/`: frozen types (`model.py`), two ports (`ports.py`), adapters (`providers/openrouter.py`, `providers/codex_cli.py`, `providers/cassette.py`, `providers/scripted.py`, `sources.py`), codebook loading (`codebook.py`), prompt rendering byte-identical to the legacy mapper (`render.py`), parsing with split retry (`parse.py`), the quote gate over `corpus_engine.verification` (`gate.py`), the response cache (`cache.py`), the read loop (`driver.py`), and the scorer/selection rule (`measure.py`). Tools build and export the kit and run the measurement. One driver serves the measurement and, in 3B, production.

**Tech Stack:** Python 3.11, SQLite, httpx (OpenRouter), subprocess (Codex CLI), rapidfuzz (via `corpus_engine.verification`), PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-stage-3a-reader-driver-design.md`. One correction found while planning (folded into the spec in Task 7): the legacy mapper rendered `raw_text`, not `norm_text`, and the Stage 1 golden prompts contain raw text; `render.py` therefore renders **`raw_text`** (the reader sees the raw opinion; the gate normalizes when verifying).

## Global Constraints

- Python 3.11; `.venv\Scripts\python` from `C:\Users\marcu\Desktop\Str-corpus`. Tests: `.venv\Scripts\python -m pytest tests -q` (baseline 151 passed, 1 xfailed). Fixtures only in tests; the live DB and any paid provider are touched only by `tools/` scripts.
- **Golden:** rendering the ten fixture batches `tests/fixtures/batches/cycle-003-shard-01/batch-*.json` under codebook `mapper-v1` with worker `claude` reproduces `tests/golden/prompts/cycle-003-shard-01/batch-*.txt` byte-for-byte.
- **Quote gate inside the driver (ADR-0011):** every quote verified via `corpus_engine.verification.verify_quote` (exact, then fuzzy ≥ 92); failed quotes dropped; a judged field (`characterization`, `polarity`, `holding_summary`; v2 adds `owner_freedom_characterization`, `restriction_nature`, `under_thirty_days`) left with no surviving `supports` quote is nulled and recorded. Every case in a unit gets a record.
- **Budget:** `Budget(max_usd, max_units, max_wall_seconds)`; checked before each paid request; stop reasons `budget:usd|units|wall`, `preflight:<check>`, `done`; the outcome carries a literal `resume_command`.
- **Cache key:** `sha256(codebook_sha | model_pin | unit.id | ",".join(sorted case ids) | rendered prompt)`, hex; raw responses stored before parsing.
- **Checker:** Codex CLI via subprocess (user decision), model pinned by flag, tool version recorded; sample = units with `int(sha256(unit.id)[:8],16) % 100 < sample_pct` (10); reader and checker families must differ (pre-flight).
- **Measurement bar (pre-registered):** fidelity < 0.97 eliminates; among survivors the cheapest cost per accepted record with macro agreement ≥ 0.85 on `relevant`, `polarity`, `who_was_letting`; if none ≥ 0.85, the highest-agreement survivor, shortfall disclosed. Machine-labelled irrelevant sample scored separately, never toward the bar. Open models pinned to a named bf16/fp8 provider, fallbacks disabled, else skipped. `Budget(max_usd=50)` shared across the run. No quantization pair. Batch-size pair (18 vs 5) and the stability check (2 reads of the 50-case sample; stable if ≥ 0.90 per judged field) on the winner only.
- **Model pins:** revisions/ids recorded verbatim; the provider actually served (and precision when reported) recorded per response.
- `corpus_engine` stays domain-agnostic: codebook text, judged fields, sample rate, family labels, candidate list, kit path come from `domain.yaml` (`reader:`) and the codebook. LF + UTF-8 without BOM on every file (`open(..., "w", encoding="utf-8", newline="\n")` or bytes; never PowerShell `Set-Content`).
- Commit after every task with the trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## File Structure

```
corpus_engine/reader/
  __init__.py            Reader, plan_batch_extraction, plan_reread, plan_judgment, agreement, Budget, StopReason
  model.py               ModelPin, Request, Response, CaseText, Budget, StopReason, Unit, Plan, RecordResult, UnitResult, Disagreement, ReadingOutcome, ReaderError
  ports.py               Provider, CaseSource protocols
  sources.py             StoreCaseSource, InlinedCaseSource
  codebook.py            Codebook(load, sha, judged_fields, validated_norm_version), stability_record()
  render.py              render_unit(codebook, unit, texts, worker) -> str  (byte-identical to legacy)
  parse.py               parse_records(text, case_ids) -> list[dict] | None; strip_fences(); split_unit()
  gate.py                gate_record(rec, case_row, judged_fields) -> dict; gate_unit()
  cache.py               ResponseCache(dir): key(), get(), put()
  driver.py              Reader, plan constructors, preflight(), agreement()
  measure.py             score_candidate(), select_reader(), stability_agreement()
  providers/__init__.py
  providers/scripted.py  ScriptedProvider(responses)
  providers/cassette.py  CassetteProvider(dir, fallback=None)
  providers/openrouter.py OpenRouterProvider(api_key, *, transport=None, timeout=300)
  providers/codex_cli.py CodexCliProvider(model, *, runner=subprocess.run, timeout=900)
domains/str-right-to-let/codebooks/mapper-v1.md   (byte copy of prompts/mapper.md)
domains/str-right-to-let/codebooks/mapper-v2.md   (ADR-0004 fields)
domains/str-right-to-let/domain.yaml               (+) reader: section
corpus_engine/domain.py                            (+) ReaderSpec
tools/build_reader_kit.py, tools/export_reader_kit.py, tools/measure_reader.py
data/reader/kit-v1/{kit.json, batches/}            frozen (Task 6)
data/reader/measurement-v1/manifest.json           (Task 7)
reports/reader-measurement.md                      (Task 7)
tests/test_reader_model.py, test_reader_render.py, test_reader_parse_gate.py, test_reader_providers.py,
tests/test_reader_driver.py, test_reader_measure.py
```

---

### Task 1: Types, ports, case sources, domain `reader:` section

**Files:**
- Create: `corpus_engine/reader/__init__.py`, `corpus_engine/reader/model.py`, `corpus_engine/reader/ports.py`, `corpus_engine/reader/sources.py`, `tests/test_reader_model.py`
- Modify: `corpus_engine/domain.py`, `domains/str-right-to-let/domain.yaml`

**Interfaces:**
- Produces (frozen dataclasses unless noted):
  - `ModelPin(model_id: str, family: str, provider_name: str | None = None, precision: str | None = None, extra: Mapping = {})` with `.label -> f"{model_id}@{provider_name or '-'}:{precision or '-'}"`.
  - `Request(pin: ModelPin, user: str, system: str | None = None, json_schema: dict | None = None, max_tokens: int = 16000, temperature: float = 0.0)`.
  - `Response(text: str, input_tokens: int, output_tokens: int, cost_usd: float | None, provider_reported: Mapping, finish_reason: str, tool_version: str | None = None)`.
  - `CaseText(case_id, cite, name, court, jurisdiction, year, raw_text, norm_text, page_map: list, provenance: tuple[dict, ...])`.
  - `Budget(max_usd: float | None = None, max_units: int | None = None, max_wall_seconds: float | None = None)`; `StopReason(kind: str, detail: str = "")` with kinds `done | budget:usd | budget:units | budget:wall | preflight:<check>`.
  - `Unit(id: str, case_ids: tuple[int, ...], meta: Mapping)` (meta carries `era_partition`, `jurisdiction`, `batch_id`, and per-case `signals`).
  - `Plan(kind: str, units: tuple[Unit, ...], codebook_id: str, pin: ModelPin, budget: Budget, worker: str, checker_pin: ModelPin | None = None, sample_pct: int = 10)`.
  - `RecordResult(case_id, record: dict, gate_status: str, dropped_quotes: int, nulled_fields: tuple[str, ...])`; `UnitResult(unit_id, status: str, records: tuple[RecordResult, ...], response: Response | None, cache_hit: bool, error: str = "")`; `Disagreement(unit_id, case_id, field, reader_value, checker_value)`.
  - `ReadingOutcome` (plain dataclass): `plan, units: list[UnitResult], disagreements: list[Disagreement], spend_usd, input_tokens, output_tokens, wall_seconds, stop: StopReason, manifest: dict, resume_command: str` with `.records -> list[dict]` (verified records across units) and `.failed_units -> list[str]`.
  - `ReaderError(Exception)`.
  - `class Provider(Protocol): name: str; def complete(self, req: Request) -> Response`; `class CaseSource(Protocol): def fetch(self, case_ids) -> list[CaseText]` (order = input order; missing ids raise `ReaderError` naming them).
  - `StoreCaseSource(conn)` reading `cases` (`case_id, cite, name_abbreviation, court, jurisdiction, decision_year, raw_text, norm_text, page_map`); `InlinedCaseSource(cases: Mapping[int, CaseText])`.
  - `ReaderSpec(codebooks_dir: str, codebook: str, judged_fields: tuple[str, ...], checker_sample_pct: int, families: Mapping[str, str], kit_path: str, kit_sha256: str | None, candidates: tuple[Mapping, ...], model: Mapping | None, stability_sample: str)`; `Domain.reader: ReaderSpec`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reader_model.py
import json, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.model import Budget, CaseText, ModelPin, Plan, StopReason, Unit
from corpus_engine.reader.sources import InlinedCaseSource, StoreCaseSource

def test_pin_label_and_types():
    p = ModelPin("deepseek/deepseek-v4-flash", "deepseek", "DeepInfra", "fp8")
    assert p.label == "deepseek/deepseek-v4-flash@DeepInfra:fp8" and ModelPin("x", "y").label == "x@-:-"
    assert StopReason("budget:usd", "50.00").kind.startswith("budget")
    u = Unit("b-001", (3, 1, 2), {"batch_id": "b-001"}); assert u.case_ids == (3, 1, 2)
    pl = Plan("batch_extraction", (u,), "mapper-v1", p, Budget(max_usd=1.0), worker="claude")
    assert pl.checker_pin is None and pl.sample_pct == 10

def test_store_source_reads_fixture_and_inlined_source_round_trips(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases ORDER BY case_id LIMIT 3")]
    texts = StoreCaseSource(conn).fetch(ids)
    assert [t.case_id for t in texts] == ids and texts[0].raw_text and texts[0].norm_text and isinstance(texts[0].page_map, list)
    inl = InlinedCaseSource({t.case_id: t for t in texts})
    assert inl.fetch(ids[::-1])[0].case_id == ids[-1]
    import pytest
    from corpus_engine.reader.model import ReaderError
    with pytest.raises(ReaderError, match="999999999"):
        StoreCaseSource(conn).fetch([ids[0], 999999999])

def test_domain_reader_spec():
    r = load_domain().reader
    assert r.codebook == "mapper-v2" and r.codebooks_dir.endswith("codebooks") and r.checker_sample_pct == 10
    assert set(("characterization", "polarity", "holding_summary")) <= set(r.judged_fields)
    assert r.families["anthropic/claude-sonnet-5"] == "anthropic" and len(r.candidates) == 10
    assert r.kit_path == "data/reader/kit-v1/kit.json" and r.stability_sample.endswith("sample-50.json")
```

- [ ] **Step 2: Run to verify failure** — `.venv\Scripts\python -m pytest tests/test_reader_model.py -q` — Expected: `ModuleNotFoundError: corpus_engine.reader`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/reader/model.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping


class ReaderError(Exception): ...


@dataclass(frozen=True)
class ModelPin:
    model_id: str
    family: str
    provider_name: str | None = None
    precision: str | None = None
    extra: Mapping = field(default_factory=dict)
    @property
    def label(self) -> str:
        return f"{self.model_id}@{self.provider_name or '-'}:{self.precision or '-'}"


@dataclass(frozen=True)
class Request:
    pin: ModelPin; user: str; system: str | None = None; json_schema: dict | None = None
    max_tokens: int = 16000; temperature: float = 0.0


@dataclass(frozen=True)
class Response:
    text: str; input_tokens: int; output_tokens: int; cost_usd: float | None
    provider_reported: Mapping; finish_reason: str; tool_version: str | None = None


@dataclass(frozen=True)
class CaseText:
    case_id: int; cite: str; name: str; court: str; jurisdiction: str; year: int | None
    raw_text: str; norm_text: str; page_map: list; provenance: tuple = ()


@dataclass(frozen=True)
class Budget:
    max_usd: float | None = None; max_units: int | None = None; max_wall_seconds: float | None = None


@dataclass(frozen=True)
class StopReason:
    kind: str; detail: str = ""


@dataclass(frozen=True)
class Unit:
    id: str; case_ids: tuple[int, ...]; meta: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    kind: str; units: tuple[Unit, ...]; codebook_id: str; pin: ModelPin; budget: Budget; worker: str
    checker_pin: ModelPin | None = None; sample_pct: int = 10


@dataclass(frozen=True)
class RecordResult:
    case_id: int; record: dict; gate_status: str; dropped_quotes: int; nulled_fields: tuple[str, ...]


@dataclass(frozen=True)
class UnitResult:
    unit_id: str; status: str; records: tuple[RecordResult, ...]; response: Response | None; cache_hit: bool; error: str = ""


@dataclass(frozen=True)
class Disagreement:
    unit_id: str; case_id: int; field: str; reader_value: object; checker_value: object


@dataclass
class ReadingOutcome:
    plan: Plan; units: list; disagreements: list; spend_usd: float; input_tokens: int; output_tokens: int
    wall_seconds: float; stop: StopReason; manifest: dict; resume_command: str
    @property
    def records(self) -> list[dict]:
        return [r.record for u in self.units for r in u.records]
    @property
    def failed_units(self) -> list[str]:
        return [u.unit_id for u in self.units if u.status != "ok"]
```

```python
# corpus_engine/reader/ports.py
from __future__ import annotations
from typing import Protocol, Sequence
from corpus_engine.reader.model import CaseText, Request, Response


class Provider(Protocol):
    name: str
    def complete(self, req: Request) -> Response: ...


class CaseSource(Protocol):
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]: ...
```

```python
# corpus_engine/reader/sources.py
from __future__ import annotations
import json
from typing import Mapping, Sequence
from corpus_engine.reader.model import CaseText, ReaderError


class StoreCaseSource:
    def __init__(self, conn):
        self.conn = conn
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]:
        ids = [int(c) for c in case_ids]; rows = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]; ph = ",".join("?" * len(chunk))
            for r in self.conn.execute(f"""SELECT case_id, cite, name_abbreviation, court, jurisdiction, decision_year,
                                             raw_text, norm_text, page_map FROM cases WHERE case_id IN ({ph})""", chunk):
                rows[r[0]] = CaseText(r[0], r[1] or "", r[2] or "", r[3] or "", r[4] or "", r[5], r[6] or "", r[7] or "",
                                      json.loads(r[8]) if r[8] else [])
        missing = [c for c in ids if c not in rows]
        if missing:
            raise ReaderError(f"cases not in store: {missing[:5]}")
        return [rows[c] for c in ids]


class InlinedCaseSource:
    def __init__(self, cases: Mapping[int, CaseText]):
        self.cases = dict(cases)
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]:
        missing = [c for c in case_ids if int(c) not in self.cases]
        if missing:
            raise ReaderError(f"cases not inlined: {missing[:5]}")
        return [self.cases[int(c)] for c in case_ids]
```

`corpus_engine/domain.py` — add:
```python
@dataclass(frozen=True)
class ReaderSpec:
    codebooks_dir: str = "codebooks"
    codebook: str = "mapper-v2"
    judged_fields: tuple[str, ...] = ("characterization", "polarity", "holding_summary")
    checker_sample_pct: int = 10
    families: Mapping[str, str] = None            # type: ignore[assignment]
    kit_path: str = ""
    kit_sha256: str | None = None
    candidates: tuple = ()
    model: Mapping | None = None
    stability_sample: str = ""
    def __post_init__(self):
        object.__setattr__(self, "families", dict(self.families or {}))
        object.__setattr__(self, "judged_fields", tuple(self.judged_fields))
        object.__setattr__(self, "candidates", tuple(dict(c) for c in (self.candidates or ())))
        object.__setattr__(self, "model", dict(self.model) if self.model else None)
```
`Domain.reader: ReaderSpec`; in `load_domain`: `reader=ReaderSpec(**cfg.get("reader", {}))`. `ReaderSpec.codebooks_dir` is relative to the domain root (`d / cfg["reader"]["codebooks_dir"]` resolved by consumers via `domain.root`).

Append to `domains/str-right-to-let/domain.yaml`:
```yaml
reader:
  codebooks_dir: codebooks
  codebook: mapper-v2
  judged_fields: [characterization, polarity, holding_summary, owner_freedom_characterization, restriction_nature, under_thirty_days]
  checker_sample_pct: 10
  families:
    anthropic/claude-sonnet-5: anthropic
    anthropic/claude-opus-5: anthropic
    anthropic/claude-haiku-4.5: anthropic
    google/gemini-3.7-flash: google
    openai/gpt-5.6-terra: openai
    deepseek/deepseek-v4-pro: deepseek
    z-ai/glm-5.3: zai
    minimax/minimax-m3: minimax
    deepseek/deepseek-v4-flash: deepseek
    qwen/qwen3.8-27b: qwen
    codex-cli: openai
  kit_path: data/reader/kit-v1/kit.json
  kit_sha256: null                      # written by tools/build_reader_kit.py
  stability_sample: data/reader/kit-v1/sample-50.json
  candidates:
    - {model_id: anthropic/claude-sonnet-5, family: anthropic}
    - {model_id: anthropic/claude-opus-5, family: anthropic}
    - {model_id: anthropic/claude-haiku-4.5, family: anthropic}
    - {model_id: google/gemini-3.7-flash, family: google}
    - {model_id: openai/gpt-5.6-terra, family: openai}
    - {model_id: deepseek/deepseek-v4-pro, family: deepseek, pin_open: true}
    - {model_id: z-ai/glm-5.3, family: zai, pin_open: true}
    - {model_id: minimax/minimax-m3, family: minimax, pin_open: true}
    - {model_id: deepseek/deepseek-v4-flash, family: deepseek, pin_open: true}
    - {model_id: qwen/qwen3.8-27b, family: qwen, pin_open: true}
  model: null                           # set by tools/measure_reader.py to the winner's pin
  checker: {model_id: codex-cli, family: openai, cli_model: gpt-5.6-terra}
```
(`ReaderSpec` also gets `checker: Mapping | None = None` handled like `model`.)

`corpus_engine/reader/__init__.py`: export `Budget, StopReason, ModelPin, ReaderError` for now (the driver's names are added in Task 5).

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_reader_model.py tests/test_domain.py -q` — Expected: pass.
```bash
git add corpus_engine/reader corpus_engine/domain.py domains/str-right-to-let/domain.yaml tests/test_reader_model.py
git commit -m "reader: types, ports, case sources, domain reader section"
```

---

### Task 2: Codebooks and byte-identical rendering

**Files:**
- Create: `corpus_engine/reader/codebook.py`, `corpus_engine/reader/render.py`, `domains/str-right-to-let/codebooks/mapper-v1.md`, `domains/str-right-to-let/codebooks/mapper-v2.md`, `tests/test_reader_render.py`

**Interfaces:**
- Consumes: `CaseText`, `Unit`, `Domain.reader`, `Domain.root`.
- Produces: `Codebook(id: str, path: Path, text: str, sha: str, judged_fields: tuple[str, ...], validated_norm_version: str | None)`; `load_codebook(domain, codebook_id) -> Codebook` (reads `<domain.root>/<codebooks_dir>/<id>.md`; `sha` = sha256 of the file bytes; `validated_norm_version` from an optional first-line HTML comment `<!-- validated_norm_version: vN -->`, else None; `judged_fields` = `domain.reader.judged_fields`); `stability_path(domain, codebook) -> Path` (`<codebooks_dir>/stability/<sha>.json`); `render_unit(codebook, unit, texts: list[CaseText], worker: str) -> str` producing exactly the legacy layout.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reader_render.py
import json, shutil
from pathlib import Path
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import Unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.sources import StoreCaseSource

def _unit(batch: dict) -> Unit:
    return Unit(batch["batch_id"], tuple(c["case_id"] for c in batch["cases"]),
                {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"], "jurisdiction": batch["jurisdiction"],
                 "signals": {c["case_id"]: c["signals"] for c in batch["cases"]}})

def test_mapper_v1_codebook_is_the_frozen_prompt(repo_root):
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    assert cb.text.encode("utf-8") == (repo_root / "prompts/mapper.md").read_bytes().replace(b"\r\n", b"\n")
    assert len(cb.sha) == 64 and cb.judged_fields == dom.reader.judged_fields
    v2 = load_codebook(dom, "mapper-v2")
    assert "schema_version" in v2.text and "under_thirty_days" in v2.text and "non_resident_owner" in v2.text and v2.sha != cb.sha

def test_render_reproduces_the_ten_golden_prompts(tmp_path, fixture_db, repo_root, golden_dir):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1"); src = StoreCaseSource(conn)
    n = 0
    for bf in sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json")):
        batch = json.loads(bf.read_text(encoding="utf-8")); u = _unit(batch)
        want = (golden_dir / "prompts/cycle-003-shard-01" / (bf.stem + ".txt")).read_bytes().replace(b"\r\n", b"\n")
        got = render_unit(cb, u, src.fetch(u.case_ids), "claude").encode("utf-8")
        assert got == want, bf.name
        n += 1
    assert n == 10
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.reader.codebook`.

- [ ] **Step 3: Implement**

Create `domains/str-right-to-let/codebooks/mapper-v1.md` as a **byte copy** of `prompts/mapper.md` (LF): `.venv\Scripts\python -c "from pathlib import Path; b=Path('prompts/mapper.md').read_bytes().replace(b'\r\n',b'\n'); Path('domains/str-right-to-let/codebooks').mkdir(parents=True, exist_ok=True); Path('domains/str-right-to-let/codebooks/mapper-v1.md').write_bytes(b)"`.

Create `mapper-v2.md`: start from v1 and make exactly these changes (keep everything else verbatim): (a) first line `<!-- validated_norm_version: v1 -->` followed by the v1 title; (b) in the output schema add `"schema_version": 2,` after `"case_id"`, add `"under_thirty_days": "yes"`, `"owner_freedom_characterization": "incident_of_ownership"`, `"restriction_nature": null` after `"characterization"`; (c) in "Field values" add: `who_was_letting` gains `non_resident_owner` (owner of a single dwelling who does not live there); `under_thirty_days`: `yes | no | unclear` — whether the occupancy at issue was under thirty days; `owner_freedom_characterization`: how the court framed the owner's liberty to let: `incident_of_ownership | regulable_privilege | commercial_use | not_addressed`; `restriction_nature` (adverse records only): `licensing | zoning | nuisance | tenant_protection | tax | other | null`; (d) in "Hard requirements" rule 1, extend the supported-field list to `characterization`, `polarity`, `holding_summary`, `owner_freedom_characterization`, `restriction_nature`, `under_thirty_days`. Write with `open(..., "w", encoding="utf-8", newline="\n")`.

```python
# corpus_engine/reader/codebook.py
from __future__ import annotations
import hashlib, re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Codebook:
    id: str; path: Path; text: str; sha: str; judged_fields: tuple[str, ...]; validated_norm_version: str | None


def load_codebook(domain, codebook_id: str) -> Codebook:
    path = Path(domain.root) / domain.reader.codebooks_dir / f"{codebook_id}.md"
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    m = re.match(r"<!--\s*validated_norm_version:\s*(\S+)\s*-->\n?", text)
    return Codebook(codebook_id, path, text, hashlib.sha256(raw).hexdigest(), tuple(domain.reader.judged_fields),
                    m.group(1) if m else None)


def stability_path(domain, codebook: Codebook) -> Path:
    return Path(domain.root) / domain.reader.codebooks_dir / "stability" / f"{codebook.sha}.json"
```

```python
# corpus_engine/reader/render.py
"""Byte-identical to the legacy pipeline/run_map.py build_payload (the Stage 1 golden prompts)."""
from __future__ import annotations
from corpus_engine.reader.codebook import Codebook
from corpus_engine.reader.model import CaseText, Unit


def render_unit(codebook: Codebook, unit: Unit, texts: list[CaseText], worker: str) -> str:
    text = codebook.text
    if text.startswith("<!--"):                      # strip the metadata comment line, never shown to the model
        text = text.split("\n", 1)[1] if "\n" in text else ""
    parts = [text]
    parts.append(f"\n\n# Batch {unit.meta['batch_id']} ({unit.meta['era_partition']} x {unit.meta['jurisdiction']})\n"
                 f'Set "worker": "{worker}" and "batch_id": "{unit.meta["batch_id"]}" on every record.\n')
    signals = unit.meta.get("signals", {})
    for t in texts:
        sig_lines = "\n".join(f"  - {s['selector_id']} v{s['selector_version']}: ...{s['matched_text'][:160]}..."
                              for s in signals.get(t.case_id, signals.get(str(t.case_id), [])))
        parts.append(f"\n## case_id {t.case_id} — {t.name}, {t.cite} ({t.court}, {t.jurisdiction} {t.year})\n"
                     f"Retrieval provenance:\n{sig_lines}\n\n### Opinion text\n{t.raw_text}\n")
    return "".join(parts)
```

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_reader_render.py -q` — Expected: 2 passed. If a golden differs, diff the first differing line: the legitimate causes are a case missing from `corpus-tiny.db` (report, do not adjust) or a `\r\n` in the golden (already normalized in the test).
```bash
git add corpus_engine/reader/codebook.py corpus_engine/reader/render.py domains/str-right-to-let/codebooks tests/test_reader_render.py
git commit -m "reader: codebooks v1 (frozen) and v2 (ADR-0004 fields); rendering byte-identical to the golden prompts"
```

---

### Task 3: Parsing and the quote gate

**Files:**
- Create: `corpus_engine/reader/parse.py`, `corpus_engine/reader/gate.py`, `tests/test_reader_parse_gate.py`

**Interfaces:**
- Consumes: `corpus_engine.verification.verify_quote(quote_text, case_row) -> {status, raw_span, reporter_page[, fuzzy_score]}`; `CaseText`.
- Produces: `strip_fences(text) -> str`; `parse_records(text, case_ids: Sequence[int], *, required=("case_id","relevant","polarity","quotes")) -> list[dict] | None` (one JSON array; every case id present; every record has the required keys; else None); `split_unit(unit) -> tuple[Unit, Unit]` (halves by case order, ids `<id>-a`, `<id>-b`); `gate_record(rec: dict, case: CaseText, judged_fields) -> RecordResult` (relevant-false ⇒ quotes cleared, status `ok`; else each quote verified, failed dropped, unsupported judged fields nulled with `nulled_fields`, `extraction_status` `ok | partial | extraction-invalid`); `gate_unit(records, texts, case_ids, judged_fields, unit_id) -> tuple[RecordResult, ...]` (adds a stub `{"case_id", "relevant": None, "gate_notes": "missing from response"}` with status `missing` for absent cases).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reader_parse_gate.py
import shutil
from corpus_engine import store
from corpus_engine.reader.gate import gate_record, gate_unit
from corpus_engine.reader.model import Unit
from corpus_engine.reader.parse import parse_records, split_unit, strip_fences
from corpus_engine.reader.sources import StoreCaseSource

J = ("characterization", "polarity", "holding_summary")

def test_parse_accepts_clean_and_fenced_rejects_partial():
    recs = '[{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    assert len(parse_records(recs, [1, 2])) == 2
    assert len(parse_records("```json\n" + recs + "\n```", [1, 2])) == 2 and strip_fences("```\n[1]\n```") == "[1]"
    assert parse_records(recs, [1, 2, 3]) is None                         # case 3 unaccounted
    assert parse_records('[{"case_id": 1, "relevant": true}]', [1]) is None  # missing required keys
    assert parse_records(recs[:-10], [1, 2]) is None                       # truncated
    a, b = split_unit(Unit("u", (1, 2, 3, 4, 5), {"batch_id": "u"}))
    assert a.id == "u-a" and a.case_ids == (1, 2, 3) and b.case_ids == (4, 5) and b.meta["batch_id"] == "u"

def test_gate_drops_paraphrase_nulls_field_keeps_exact_and_stubs_missing(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    cid = conn.execute("SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1").fetchone()[0]
    t = StoreCaseSource(conn).fetch([cid])[0]
    exact = t.raw_text[500:620]
    rec = {"case_id": cid, "relevant": True, "polarity": "favorable", "characterization": "license", "holding_summary": "x",
           "quotes": [{"text": exact, "supports": "polarity"}, {"text": "The court plainly held something it never said here.", "supports": "characterization"}]}
    r = gate_record(dict(rec), t, J)
    assert r.dropped_quotes == 1 and r.nulled_fields == ("characterization", "holding_summary") and r.record["polarity"] == "favorable"
    assert r.record["characterization"] is None and r.record["quotes"][0]["status"] == "verified" and r.gate_status == "partial"
    irr = gate_record({"case_id": cid, "relevant": False, "polarity": "irrelevant", "quotes": [{"text": "zzz"}]}, t, J)
    assert irr.record["quotes"] == [] and irr.gate_status == "ok"
    out = gate_unit([rec], [t], (cid, 424242), J, "u")
    assert [x.case_id for x in out] == [cid, 424242] and out[1].gate_status == "missing" and out[1].record["relevant"] is None
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.reader.parse`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/reader/parse.py
from __future__ import annotations
import json
from typing import Sequence
from corpus_engine.reader.model import Unit

REQUIRED = ("case_id", "relevant", "polarity", "quotes")


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        i = t.find("[")
        t = t[i:] if i >= 0 else t
    return t.strip()


def parse_records(text: str, case_ids: Sequence[int], *, required=REQUIRED) -> list[dict] | None:
    t = strip_fences(text); start, end = t.find("["), t.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        recs = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(recs, list) or not all(isinstance(r, dict) for r in recs):
        return None
    if not {int(c) for c in case_ids} <= {r.get("case_id") for r in recs}:
        return None
    if not all(set(required) <= set(r) for r in recs):
        return None
    return recs


def split_unit(unit: Unit) -> tuple[Unit, Unit]:
    ids = list(unit.case_ids); k = (len(ids) + 1) // 2
    return (Unit(f"{unit.id}-a", tuple(ids[:k]), unit.meta), Unit(f"{unit.id}-b", tuple(ids[k:]), unit.meta))
```

```python
# corpus_engine/reader/gate.py
"""The quote gate runs inside the driver (ADR-0011): nothing unverified leaves it."""
from __future__ import annotations
from corpus_engine.reader.model import CaseText, RecordResult
from corpus_engine.verification import verify_quote


def gate_record(rec: dict, case: CaseText, judged_fields) -> RecordResult:
    rec = dict(rec)
    if rec.get("relevant") is False:
        rec["quotes"] = []; rec["extraction_status"] = "ok"
        return RecordResult(int(rec["case_id"]), rec, "ok", 0, ())
    case_row = {"raw_text": case.raw_text, "norm_text": case.norm_text, "page_map": case.page_map}
    kept, supported, dropped = [], set(), 0
    for q in rec.get("quotes") or []:
        v = verify_quote((q or {}).get("text", ""), case_row)
        if v["status"] == "failed":
            dropped += 1; continue
        kept.append({**q, **v})
        if q.get("supports"):
            supported.add(q["supports"])
    rec["quotes"] = kept; nulled = []
    for f in judged_fields:
        if rec.get(f) is not None and f not in supported:
            rec[f] = None; nulled.append(f)
    if nulled:
        rec["nulled_fields"] = nulled
    status = "ok" if not dropped and not nulled else ("partial" if kept else "extraction-invalid")
    rec["extraction_status"] = status
    return RecordResult(int(rec["case_id"]), rec, status, dropped, tuple(nulled))


def gate_unit(records: list[dict], texts: list[CaseText], case_ids, judged_fields, unit_id: str) -> tuple[RecordResult, ...]:
    by_id = {int(r["case_id"]): r for r in records if isinstance(r, dict) and r.get("case_id") is not None}
    tx = {t.case_id: t for t in texts}; out = []
    for cid in case_ids:
        cid = int(cid)
        if cid in by_id and cid in tx:
            out.append(gate_record(by_id[cid], tx[cid], judged_fields))
        else:
            out.append(RecordResult(cid, {"case_id": cid, "relevant": None, "polarity": None, "quotes": [],
                                          "gate_notes": "missing from response", "extraction_status": "missing"}, "missing", 0, ()))
    return tuple(out)
```

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_reader_parse_gate.py -q` — Expected: 2 passed.
```bash
git add corpus_engine/reader/parse.py corpus_engine/reader/gate.py tests/test_reader_parse_gate.py
git commit -m "reader: response parsing with split retry units; quote gate over corpus_engine.verification"
```

---

### Task 4: Providers — scripted, cassette, OpenRouter, Codex CLI

**Files:**
- Create: `corpus_engine/reader/providers/__init__.py`, `providers/scripted.py`, `providers/cassette.py`, `providers/openrouter.py`, `providers/codex_cli.py`, `tests/test_reader_providers.py`

**Interfaces:**
- Produces:
  - `ScriptedProvider(responses: Sequence[str] | Callable[[Request], str], *, cost_per_call=0.001)` — `name="scripted"`; returns the next canned text; counts calls in `.calls`.
  - `CassetteProvider(dir: Path, *, fallback: Provider | None = None)` — `name="cassette"`; key = `sha256(pin.label | system | user)`; hit ⇒ replay `Response` from `<dir>/<key>.json`; miss ⇒ fallback (recording it) or `ReaderError("cassette miss")`.
  - `OpenRouterProvider(api_key, *, transport=None, timeout=300, base="https://openrouter.ai/api/v1")` — `name="openrouter"`; POST `/chat/completions` with `model`, `messages`, `temperature`, `max_tokens`, `response_format={"type":"json_schema","json_schema":{...}}` when `req.json_schema`, and for pins with `provider_name`: `"provider": {"order": [provider_name], "allow_fallbacks": False, "quantizations": [precision]}` (precision only when set); `usage: {"include": True}`; retries on 429/5xx/transport errors with `RETRY_DELAYS` copied from `corpus_engine/indexer/embedders.py`; reads `choices[0].message.content`, `usage.prompt_tokens/completion_tokens/cost`, top-level `provider`; `transport` is an injectable callable `(url, json, headers, timeout) -> (status, json)` defaulting to httpx. `probe_model(model_id) -> dict | None` GETs `/models` once (cached) and returns the entry.
  - `CodexCliProvider(cli_model: str, *, runner=subprocess.run, timeout=900, exe="codex")` — `name="codex-cli"`; runs `[exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--model", cli_model, "--json", "-"]` with the rendered prompt on stdin; parses stdout as JSON-lines events, taking the text of the **last** event whose `item.type == "agent_message"` (fallback: the last line that parses as an object with `text`), token counts from any event carrying `usage`/`token_usage` (0 if absent), `tool_version` from `[exe, "--version"]` (run once, cached); `is_available() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reader_providers.py
import json, pytest
from corpus_engine.reader.model import ModelPin, Request, ReaderError
from corpus_engine.reader.providers.cassette import CassetteProvider
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider

PIN = ModelPin("deepseek/deepseek-v4-flash", "deepseek", "DeepInfra", "fp8")

def test_scripted_and_cassette_record_and_replay(tmp_path):
    s = ScriptedProvider(["[1]", "[2]"]); req = Request(PIN, "hello")
    c = CassetteProvider(tmp_path, fallback=s)
    assert c.complete(req).text == "[1]" and s.calls == 1
    assert c.complete(req).text == "[1]" and s.calls == 1                       # replayed, not re-asked
    assert c.complete(Request(PIN, "other")).text == "[2]" and s.calls == 2
    with pytest.raises(ReaderError, match="cassette miss"):
        CassetteProvider(tmp_path).complete(Request(PIN, "never seen"))

def test_openrouter_sends_pin_and_schema_reads_cost_and_retries():
    sent = []; calls = {"n": 0}
    def transport(url, json_body, headers, timeout):
        calls["n"] += 1; sent.append(json_body)
        if calls["n"] == 1:
            return 429, {"error": "slow"}
        return 200, {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.00012}, "provider": "DeepInfra"}
    import corpus_engine.reader.providers.openrouter as m
    m.time.sleep = lambda s: None
    p = OpenRouterProvider("k", transport=transport)
    r = p.complete(Request(PIN, "u", json_schema={"type": "array"}))
    assert r.text == "[]" and r.cost_usd == 0.00012 and r.input_tokens == 10 and r.provider_reported["provider"] == "DeepInfra"
    body = sent[-1]
    assert body["model"] == PIN.model_id and body["provider"] == {"order": ["DeepInfra"], "allow_fallbacks": False, "quantizations": ["fp8"]}
    assert body["response_format"]["type"] == "json_schema" and body["temperature"] == 0.0 and calls["n"] == 2
    body2 = []; p2 = OpenRouterProvider("k", transport=lambda u, j, h, t: (body2.append(j) or (200, {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}})))
    p2.complete(Request(ModelPin("anthropic/claude-sonnet-5", "anthropic"), "u"))
    assert "provider" not in body2[0] and "response_format" not in body2[0]

def test_codex_cli_parses_events_and_records_version():
    class P:  # fake CompletedProcess
        def __init__(self, out, code=0): self.stdout = out; self.stderr = ""; self.returncode = code
    def runner(cmd, **kw):
        if cmd[1] == "--version":
            return P("codex-cli 9.9.9\n")
        assert cmd[:3] == ["codex", "exec", "--sandbox"] and "--model" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5.6-terra"
        events = [{"type": "item.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "draft"}},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "[{\"case_id\": 1}]"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}]
        return P("\n".join(json.dumps(e) for e in events) + "\n")
    p = CodexCliProvider("gpt-5.6-terra", runner=runner)
    r = p.complete(Request(ModelPin("codex-cli", "openai"), "prompt"))
    assert r.text == '[{"case_id": 1}]' and r.input_tokens == 100 and r.tool_version == "codex-cli 9.9.9" and r.cost_usd is None
    assert p.is_available()
    bad = CodexCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("codex")))
    assert not bad.is_available()
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.reader.providers`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/reader/providers/scripted.py
from __future__ import annotations
from typing import Callable, Sequence
from corpus_engine.reader.model import Request, Response


class ScriptedProvider:
    name = "scripted"
    def __init__(self, responses: Sequence[str] | Callable[[Request], str], *, cost_per_call: float = 0.001):
        self._r = responses; self.calls = 0; self.cost = cost_per_call
    def complete(self, req: Request) -> Response:
        text = self._r(req) if callable(self._r) else self._r[min(self.calls, len(self._r) - 1)]
        self.calls += 1
        return Response(text, len(req.user) // 4, len(text) // 4, self.cost, {"provider": "scripted"}, "stop")
```

```python
# corpus_engine/reader/providers/cassette.py
from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ReaderError, Request, Response


class CassetteProvider:
    name = "cassette"
    def __init__(self, dir: Path, *, fallback=None):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True); self.fallback = fallback
    @staticmethod
    def key(req: Request) -> str:
        return hashlib.sha256(f"{req.pin.label}|{req.system or ''}|{req.user}".encode("utf-8")).hexdigest()
    def complete(self, req: Request) -> Response:
        p = self.dir / f"{self.key(req)}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8")); return Response(**d)
        if self.fallback is None:
            raise ReaderError(f"cassette miss for {req.pin.label} ({self.key(req)[:12]})")
        r = self.fallback.complete(req)
        p.write_bytes(json.dumps(asdict(r), sort_keys=True).encode("utf-8"))
        return r
```

```python
# corpus_engine/reader/providers/openrouter.py
from __future__ import annotations
import time
import httpx
from corpus_engine.indexer.embedders import RETRY_DELAYS
from corpus_engine.reader.model import ReaderError, Request, Response


def _httpx_transport(url, json_body, headers, timeout):
    r = httpx.post(url, json=json_body, headers=headers, timeout=timeout)
    try:
        body = r.json()
    except ValueError:
        body = {"error": r.text[:300]}
    return r.status_code, body


class OpenRouterProvider:
    name = "openrouter"
    def __init__(self, api_key: str, *, transport=None, timeout: int = 300, base: str = "https://openrouter.ai/api/v1"):
        self.key, self.transport, self.timeout, self.base = api_key, transport or _httpx_transport, timeout, base
        self._models: dict | None = None

    def _body(self, req: Request) -> dict:
        body = {"model": req.pin.model_id, "messages": ([{"role": "system", "content": req.system}] if req.system else [])
                + [{"role": "user", "content": req.user}], "temperature": req.temperature, "max_tokens": req.max_tokens,
                "usage": {"include": True}}
        if req.pin.provider_name:
            prov = {"order": [req.pin.provider_name], "allow_fallbacks": False}
            if req.pin.precision:
                prov["quantizations"] = [req.pin.precision]
            body["provider"] = prov
        if req.json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "records", "schema": req.json_schema}}
        return body

    def complete(self, req: Request) -> Response:
        last = ""
        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                status, body = self.transport(f"{self.base}/chat/completions", self._body(req),
                                              {"Authorization": f"Bearer {self.key}"}, self.timeout)
            except (httpx.TransportError, OSError) as exc:
                last = f"transport error: {exc!r}"
                if delay == 0:
                    raise ReaderError(f"{last} after {attempt + 1} attempts") from exc
                time.sleep(delay); continue
            if status == 200 and body.get("choices"):
                ch = body["choices"][0]; u = body.get("usage") or {}
                return Response(ch.get("message", {}).get("content") or "", int(u.get("prompt_tokens") or 0),
                                int(u.get("completion_tokens") or 0), (float(u["cost"]) if u.get("cost") is not None else None),
                                {"provider": body.get("provider"), "model": body.get("model"), "id": body.get("id")},
                                ch.get("finish_reason") or "")
            last = f"{status}: {str(body)[:200]}"
            if status == 429 or status >= 500:
                if delay == 0:
                    break
                time.sleep(delay); continue
            raise ReaderError(last)
        raise ReaderError(f"openrouter failed after {len(RETRY_DELAYS)} attempts; last {last}")

    def probe_model(self, model_id: str) -> dict | None:
        if self._models is None:
            r = httpx.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"}, timeout=60)
            self._models = {m["id"]: m for m in r.json().get("data", [])}
        return self._models.get(model_id)
```

```python
# corpus_engine/reader/providers/codex_cli.py
"""Checker transport: the Codex command-line tool via subprocess, as in cycles 1-3 (user decision, ADR-0007 amendment)."""
from __future__ import annotations
import json, subprocess
from corpus_engine.reader.model import ReaderError, Request, Response


class CodexCliProvider:
    name = "codex-cli"
    def __init__(self, cli_model: str, *, runner=subprocess.run, timeout: int = 900, exe: str = "codex"):
        self.cli_model, self.runner, self.timeout, self.exe = cli_model, runner, timeout, exe
        self._version: str | None = None

    def version(self) -> str | None:
        if self._version is None:
            try:
                p = self.runner([self.exe, "--version"], capture_output=True, text=True, timeout=60)
                self._version = (p.stdout or "").strip() or None
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                self._version = None
        return self._version

    def is_available(self) -> bool:
        return self.version() is not None

    def complete(self, req: Request) -> Response:
        cmd = [self.exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--model", self.cli_model, "--json", "-"]
        try:
            p = self.runner(cmd, input=req.user, capture_output=True, text=True, timeout=self.timeout, encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise ReaderError(f"codex cli unavailable: {exc!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ReaderError("codex cli timed out") from exc
        if p.returncode != 0:
            raise ReaderError(f"codex exited {p.returncode}: {(p.stderr or '')[:300]}")
        text, usage = "", {}
        for line in (p.stdout or "").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                text = item["text"]
            for k in ("usage", "token_usage"):
                if isinstance(ev.get(k), dict):
                    usage = ev[k]
        if not text:
            raise ReaderError("codex cli produced no agent_message")
        return Response(text, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), None,
                        {"provider": "codex-cli", "cli_model": self.cli_model}, "stop", self.version())
```

`providers/__init__.py` exports the four classes.

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_reader_providers.py -q` — Expected: 3 passed.
```bash
git add corpus_engine/reader/providers tests/test_reader_providers.py
git commit -m "reader: scripted, cassette, OpenRouter (pinned, schema, retries) and Codex CLI providers"
```

---

### Task 5: Cache, pre-flight, and the read loop

**Files:**
- Create: `corpus_engine/reader/cache.py`, `corpus_engine/reader/driver.py`, `tests/test_reader_driver.py`
- Modify: `corpus_engine/reader/__init__.py`

**Interfaces:**
- Produces:
  - `ResponseCache(dir)`: `key(codebook_sha, pin, unit, prompt) -> str` = `sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{','.join(map(str, sorted(unit.case_ids)))}|{prompt}")`; `get(key) -> Response | None`; `put(key, response)`.
  - `preflight(plan, codebook, cases, provider, checker, *, store_norm_version: str | None, families: Mapping) -> StopReason | None`: checks `norm_version` (when the codebook declares one and a store version is known), `stability` (a file at `stability_path` exists unless `plan.kind == "stability"`), `families` (reader vs checker family differ; family = `families.get(model_id, pin.family)`), `checker_available` (Codex `is_available()` when a checker is configured), `pin` (`provider.probe_model(model_id)` returns an entry when the provider has `probe_model`).
  - `Reader(provider, cases, *, checker=None, cache: ResponseCache | None = None, log=print, sleep=time.sleep, clock=time.time, domain=None)` with `.read(plan) -> ReadingOutcome`.
  - `plan_batch_extraction(batches: list[dict], codebook_id, pin, budget, *, worker, checker_pin=None, sample_pct=10) -> Plan`; `plan_reread(records, codebook_id, pin, budget, *, worker) -> Plan` (one unit per record's case); `plan_judgment(case_ids, question, codebook_id, pin, budget, *, worker) -> Plan` (kind `judgment`, meta carries `question`); `agreement(a: list[dict], b: list[dict], fields) -> dict[str, float]` (share of case ids present in both where the field values are equal; `None` vs `None` counts as agreement).
  - `resume_command(plan, run_dir) -> str` = `f".venv\\Scripts\\python pipeline\\read.py --plan {run_dir}\\plan.json --resume"` (3B supplies `pipeline/read.py`; the string is what the outcome carries).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reader_driver.py
import json, shutil, time
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader, agreement, plan_batch_extraction, preflight
from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.sources import StoreCaseSource

PIN = ModelPin("anthropic/claude-haiku-4.5", "anthropic")

def _batches(repo_root, n=3):
    files = sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json"))[:n]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]

def _answer(conn):
    def f(req):
        ids = [int(l.split()[2]) for l in req.user.splitlines() if l.startswith("## case_id ")]
        recs = []
        for cid in ids:
            raw = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
            recs.append({"case_id": cid, "relevant": True, "polarity": "favorable", "characterization": "license", "holding_summary": "h",
                         "quotes": [{"text": raw[300:420], "supports": "polarity"}, {"text": raw[300:420], "supports": "characterization"},
                                    {"text": "not in the opinion at all, a paraphrase", "supports": "holding_summary"}],
                         "worker": "claude", "batch_id": "x"})
        return json.dumps(recs)
    return f

def test_read_gates_caches_budgets_and_reports(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    prov = ScriptedProvider(_answer(conn), cost_per_call=0.4); cache = ResponseCache(tmp_path / "cache")
    plan = plan_batch_extraction(_batches(repo_root), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude")
    (tmp_path / "stab").mkdir()
    out = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom).read(plan)
    assert out.stop.kind == "budget:usd" and len(out.units) == 2 and prov.calls == 2 and out.spend_usd == 0.8
    recs = out.records
    assert recs and all(r["holding_summary"] is None for r in recs) and all(r["polarity"] == "favorable" for r in recs)
    assert all(r["extraction_status"] == "partial" for r in recs) and out.resume_command.endswith("--resume")
    assert out.manifest["codebook_sha"] and out.manifest["model_pin"] == PIN.label
    out2 = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom).read(plan)   # resume: cached units are free
    assert prov.calls == 3 and out2.stop.kind == "done" and len(out2.units) == 3 and sum(u.cache_hit for u in out2.units) == 2

def test_checker_sampling_and_disagreements(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    reader = ScriptedProvider(_answer(conn))
    def flip(req):
        recs = json.loads(_answer(conn)(req))
        for r in recs: r["polarity"] = "adverse"
        return json.dumps(recs)
    checker = ScriptedProvider(flip)
    plan = plan_batch_extraction(_batches(repo_root, 10), "mapper-v1", PIN, Budget(), worker="claude",
                                 checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=100)
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom).read(plan)
    assert checker.calls == 10 and out.disagreements and all(d.field == "polarity" for d in out.disagreements)
    plan10 = plan_batch_extraction(_batches(repo_root, 10), "mapper-v1", PIN, Budget(), worker="claude",
                                   checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=10)
    c2 = ScriptedProvider(flip)
    Reader(ScriptedProvider(_answer(conn)), StoreCaseSource(conn), checker=c2, log=lambda *_: None, domain=dom).read(plan10)
    assert 0 <= c2.calls <= 3

def test_preflight_refuses_same_family_and_missing_checker(tmp_path, fixture_db, repo_root):
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude", checker_pin=ModelPin("x", "anthropic"))
    s = preflight(plan, cb, None, ScriptedProvider(["[]"]), ScriptedProvider(["[]"]), store_norm_version=None, families={})
    assert s is not None and s.kind == "preflight:families"
    plan2 = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude", checker_pin=ModelPin("codex-cli", "openai"))
    missing = CodexCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    assert preflight(plan2, cb, None, ScriptedProvider(["[]"]), missing, store_norm_version=None, families={}).kind == "preflight:checker_available"

def test_agreement():
    a = [{"case_id": 1, "polarity": "favorable", "relevant": True}, {"case_id": 2, "polarity": None, "relevant": False}]
    b = [{"case_id": 1, "polarity": "adverse", "relevant": True}, {"case_id": 2, "polarity": None, "relevant": False}, {"case_id": 3}]
    assert agreement(a, b, ("polarity", "relevant")) == {"polarity": 0.5, "relevant": 1.0}
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.reader.driver`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/reader/cache.py
from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ModelPin, Response, Unit


class ResponseCache:
    def __init__(self, dir: Path):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True)
    @staticmethod
    def key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str:
        ids = ",".join(map(str, sorted(unit.case_ids)))
        return hashlib.sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}".encode("utf-8")).hexdigest()
    def get(self, key: str) -> Response | None:
        p = self.dir / f"{key}.json"
        return Response(**json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None
    def put(self, key: str, r: Response) -> None:
        (self.dir / f"{key}.json").write_bytes(json.dumps(asdict(r), sort_keys=True).encode("utf-8"))
```

```python
# corpus_engine/reader/driver.py
from __future__ import annotations
import hashlib, time
from pathlib import Path
from typing import Mapping
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import Codebook, load_codebook, stability_path
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import (Budget, Disagreement, ModelPin, Plan, ReaderError, ReadingOutcome, Request,
                                        StopReason, Unit, UnitResult)
from corpus_engine.reader.parse import parse_records, split_unit
from corpus_engine.reader.render import render_unit

ENGINE_VERSION = "reader-v1"
COMPARE_FIELDS = ("relevant", "polarity", "characterization")


def plan_batch_extraction(batches, codebook_id: str, pin: ModelPin, budget: Budget, *, worker: str,
                          checker_pin: ModelPin | None = None, sample_pct: int = 10) -> Plan:
    units = tuple(Unit(b["batch_id"], tuple(int(c["case_id"]) for c in b["cases"]),
                       {"batch_id": b["batch_id"], "era_partition": b["era_partition"], "jurisdiction": b["jurisdiction"],
                        "signals": {int(c["case_id"]): c.get("signals", []) for c in b["cases"]}}) for b in batches)
    return Plan("batch_extraction", units, codebook_id, pin, budget, worker, checker_pin, sample_pct)


def plan_reread(records, codebook_id, pin, budget, *, worker) -> Plan:
    units = tuple(Unit(f"reread-{r['case_id']}", (int(r["case_id"]),),
                       {"batch_id": f"reread-{r['case_id']}", "era_partition": r.get("era_partition", "?"),
                        "jurisdiction": r.get("jurisdiction", "?"), "signals": {}}) for r in records)
    return Plan("reread", units, codebook_id, pin, budget, worker)


def plan_judgment(case_ids, question: str, codebook_id, pin, budget, *, worker) -> Plan:
    units = tuple(Unit(f"judge-{c}", (int(c),), {"batch_id": f"judge-{c}", "era_partition": "?", "jurisdiction": "?",
                                                 "signals": {}, "question": question}) for c in case_ids)
    return Plan("judgment", units, codebook_id, pin, budget, worker)


def agreement(a, b, fields) -> dict[str, float]:
    ba = {int(r["case_id"]): r for r in a if r.get("case_id") is not None}
    bb = {int(r["case_id"]): r for r in b if r.get("case_id") is not None}
    common = sorted(set(ba) & set(bb)); out = {}
    for f in fields:
        out[f] = (sum(1 for c in common if ba[c].get(f) == bb[c].get(f)) / len(common)) if common else 0.0
    return out


def resume_command(plan: Plan, run_dir: Path | None) -> str:
    rd = str(run_dir) if run_dir else "runs\\<run>"
    return f".venv\\Scripts\\python pipeline\\read.py --plan {rd}\\plan.json --resume"


def _sampled(unit_id: str, pct: int) -> bool:
    return int(hashlib.sha256(unit_id.encode()).hexdigest()[:8], 16) % 100 < pct


def preflight(plan: Plan, codebook: Codebook, cases, provider, checker, *, store_norm_version, families: Mapping,
              domain=None) -> StopReason | None:
    if codebook.validated_norm_version and store_norm_version and codebook.validated_norm_version != store_norm_version:
        return StopReason("preflight:norm_version", f"{codebook.validated_norm_version} != {store_norm_version}")
    if domain is not None and plan.kind != "stability" and not stability_path(domain, codebook).exists():
        return StopReason("preflight:stability", f"no stability record for {codebook.id} ({codebook.sha[:12]})")
    if plan.checker_pin is not None:
        fr = families.get(plan.pin.model_id, plan.pin.family); fc = families.get(plan.checker_pin.model_id, plan.checker_pin.family)
        if fr == fc:
            return StopReason("preflight:families", f"reader and checker are both {fr}")
        if checker is not None and hasattr(checker, "is_available") and not checker.is_available():
            return StopReason("preflight:checker_available", getattr(checker, "name", "checker"))
    if hasattr(provider, "probe_model") and provider.probe_model(plan.pin.model_id) is None:
        return StopReason("preflight:pin", f"{plan.pin.model_id} not served")
    return None


class Reader:
    def __init__(self, provider, cases, *, checker=None, cache: ResponseCache | None = None, log=print,
                 sleep=time.sleep, clock=time.time, domain=None, run_dir: Path | None = None, store_norm_version=None):
        self.provider, self.cases, self.checker, self.cache = provider, cases, checker, cache
        self.log, self.sleep, self.clock, self.domain, self.run_dir, self.norm = log, sleep, clock, domain, run_dir, store_norm_version

    def _codebook(self, plan: Plan) -> Codebook:
        if self.domain is None:
            raise ReaderError("Reader needs a domain to load codebooks")
        return load_codebook(self.domain, plan.codebook_id)

    def _ask(self, plan: Plan, cb: Codebook, unit: Unit, pin: ModelPin, worker: str, provider, spend: list, tokens: list):
        texts = self.cases.fetch(unit.case_ids)
        prompt = render_unit(cb, unit, texts, worker)
        key = ResponseCache.key(cb.sha, pin, unit, prompt) if self.cache else None
        resp = self.cache.get(key) if key else None; hit = resp is not None
        if resp is None:
            resp = provider.complete(Request(pin, prompt))
            if key:
                self.cache.put(key, resp)
            spend[0] += resp.cost_usd or 0.0; tokens[0] += resp.input_tokens; tokens[1] += resp.output_tokens
        return texts, resp, hit

    def read(self, plan: Plan) -> ReadingOutcome:
        t0 = self.clock(); cb = self._codebook(plan)
        families = self.domain.reader.families if self.domain is not None else {}
        judged = cb.judged_fields
        stop = preflight(plan, cb, self.cases, self.provider, self.checker, store_norm_version=self.norm, families=families,
                         domain=self.domain if plan.kind != "stability" else None)
        units, disagreements, spend, tokens, n_paid = [], [], [0.0], [0, 0], 0
        if stop is None:
            stop = StopReason("done")
            for unit in plan.units:
                b = plan.budget
                if b.max_usd is not None and spend[0] >= b.max_usd:
                    stop = StopReason("budget:usd", f"{spend[0]:.2f} >= {b.max_usd}"); break
                if b.max_units is not None and n_paid >= b.max_units:
                    stop = StopReason("budget:units", str(n_paid)); break
                if b.max_wall_seconds is not None and self.clock() - t0 >= b.max_wall_seconds:
                    stop = StopReason("budget:wall", f"{self.clock() - t0:.0f}s"); break
                try:
                    texts, resp, hit = self._ask(plan, cb, unit, plan.pin, plan.worker, self.provider, spend, tokens)
                    n_paid += 0 if hit else 1
                    recs = parse_records(resp.text, unit.case_ids)
                    if recs is None:                                   # split retry, once
                        recs = []
                        for half in split_unit(unit):
                            _, r2, h2 = self._ask(plan, cb, half, plan.pin, plan.worker, self.provider, spend, tokens)
                            n_paid += 0 if h2 else 1
                            part = parse_records(r2.text, half.case_ids)
                            if part is None:
                                recs = None; break
                            recs += part
                    if recs is None:
                        units.append(UnitResult(unit.id, "parse_failed", (), resp, hit, "unparseable after split")); continue
                    results = gate_unit(recs, texts, unit.case_ids, judged, unit.id)
                    units.append(UnitResult(unit.id, "ok", results, resp, hit))
                    if self.checker is not None and plan.checker_pin is not None and _sampled(unit.id, plan.sample_pct):
                        _, cresp, _ = self._ask(plan, cb, unit, plan.checker_pin, "checker", self.checker, spend, tokens)
                        crecs = parse_records(cresp.text, unit.case_ids) or []
                        cby = {int(r["case_id"]): r for r in crecs}
                        for rr in results:
                            cr = cby.get(rr.case_id)
                            if cr is None:
                                continue
                            for f in COMPARE_FIELDS:
                                if rr.record.get(f) != cr.get(f):
                                    disagreements.append(Disagreement(unit.id, rr.case_id, f, rr.record.get(f), cr.get(f)))
                    self.log(f"{unit.id}: {len(results)} records, {sum(r.dropped_quotes for r in results)} quotes dropped"
                             + (" (cache)" if hit else ""))
                except ReaderError as exc:
                    units.append(UnitResult(unit.id, "failed", (), None, False, str(exc)[:300])); self.log(f"{unit.id}: FAILED {exc}")
        manifest = {"engine_version": ENGINE_VERSION, "codebook_id": cb.id, "codebook_sha": cb.sha, "model_pin": plan.pin.label,
                    "checker_pin": plan.checker_pin.label if plan.checker_pin else None, "sample_pct": plan.sample_pct,
                    "provider": getattr(self.provider, "name", "?"),
                    "provider_reported": sorted({str((u.response.provider_reported or {}).get("provider")) for u in units if u.response}),
                    "tool_version": next((u.response.tool_version for u in units if u.response and u.response.tool_version), None),
                    "worker": plan.worker, "kind": plan.kind}
        return ReadingOutcome(plan, units, disagreements, round(spend[0], 6), tokens[0], tokens[1], self.clock() - t0, stop,
                              manifest, resume_command(plan, self.run_dir))
```

`corpus_engine/reader/__init__.py`: `from corpus_engine.reader.driver import Reader, agreement, plan_batch_extraction, plan_judgment, plan_reread, preflight, ENGINE_VERSION` plus the model exports.

Note for the implementer: the first driver test expects the stability pre-flight to pass on the fixture — create `domains/str-right-to-let/codebooks/stability/<sha of mapper-v1>.json` in Task 5 with `{"codebook": "mapper-v1", "note": "cycles 001-003 ran this codebook; stability grandfathered (ADR-0009 amendment pending v2 measurement)"}` and commit it (the sha is printed by `load_codebook`). v2 gets its record in Task 7.

- [ ] **Step 4: Run to verify pass, commit** — `.venv\Scripts\python -m pytest tests/test_reader_driver.py -q` — Expected: 4 passed.
```bash
git add corpus_engine/reader tests/test_reader_driver.py domains/str-right-to-let/codebooks/stability
git commit -m "reader: response cache, pre-flight, read loop with quote gate, budget stops, checker sampling, resume"
```

---

### Task 6: Scorer, selection rule, kit build and export (tools run once)

**Files:**
- Create: `corpus_engine/reader/measure.py`, `tools/build_reader_kit.py`, `tools/export_reader_kit.py`, `tests/test_reader_measure.py`, `data/reader/kit-v1/{kit.json, sample-50.json, batches/}` (generated)
- Modify: `domains/str-right-to-let/domain.yaml` (`reader.kit_sha256`)

**Interfaces:**
- Produces:
  - `Kit` JSON: `{"version": "v1", "built_at", "reference": [{case_id, source: "human"|"machine", relevant, polarity, who_was_letting, era, jurisdiction}], "batches": [{batch_id, era_partition, jurisdiction, cases: [{case_id, signals}]}], "texts": {case_id: {cite, name, court, jurisdiction, year, raw_text, norm_text, page_map}}}`; `load_kit(path) -> (reference: list[dict], batches: list[dict], source: InlinedCaseSource)`; `kit_sample_50(reference) -> list[int]` (deterministic: `random.Random(20260904).sample(human_ids, 50)`).
  - `score_candidate(outcome: ReadingOutcome, reference: list[dict]) -> dict` with `fidelity` (kept quotes ÷ (kept + dropped) over relevant records), `agreement_human` (per field + `macro` over `relevant, polarity, who_was_letting` on `source == "human"` cases), `agreement_machine_irrelevant` (share of `source == "machine"` cases the candidate marked `relevant == False`), `schema_compliance` (records ÷ cases), `accepted` (records with `extraction_status` in `ok|partial` and `relevant` not None), `cost_per_accepted` (`spend_usd / accepted`, `inf` if 0), `spend_usd`, `wall_seconds`, `provider_reported`, `failed_units`.
  - `select_reader(scores: dict[str, dict], *, fidelity_floor=0.97, agreement_bar=0.85) -> dict` `{winner, rule, survivors, eliminated, shortfall: bool}` per the Global Constraints bar.
  - `stability_agreement(out_a, out_b, fields) -> dict[str, float]` (wraps `agreement`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reader_measure.py
import math
from corpus_engine.reader.measure import select_reader, score_candidate
from corpus_engine.reader.model import Budget, ModelPin, Plan, ReadingOutcome, RecordResult, Response, StopReason, Unit, UnitResult

def _out(recs, dropped, spend):
    rr = tuple(RecordResult(r["case_id"], r, r.get("extraction_status", "ok"), d, ()) for r, d in zip(recs, dropped))
    u = UnitResult("u", "ok", rr, Response("", 1, 1, spend, {"provider": "P"}, "stop"), False)
    return ReadingOutcome(Plan("k", (Unit("u", tuple(r["case_id"] for r in recs)),), "cb", ModelPin("m", "f"), Budget(), "w"),
                          [u], [], spend, 1, 1, 2.0, StopReason("done"), {}, "")

def test_score_candidate_fields():
    ref = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
           {"case_id": 2, "source": "human", "relevant": True, "polarity": "adverse", "who_was_letting": "commercial_operator"},
           {"case_id": 3, "source": "machine", "relevant": False, "polarity": "irrelevant", "who_was_letting": None}]
    recs = [{"case_id": 1, "relevant": True, "polarity": "favorable", "who_was_letting": "householder", "quotes": [1, 2, 3], "extraction_status": "ok"},
            {"case_id": 2, "relevant": True, "polarity": "favorable", "who_was_letting": "commercial_operator", "quotes": [1], "extraction_status": "partial"},
            {"case_id": 3, "relevant": False, "polarity": "irrelevant", "quotes": [], "extraction_status": "ok"}]
    s = score_candidate(_out(recs, [0, 1, 0], 0.30), ref)
    assert s["fidelity"] == 4 / 5 and s["agreement_human"]["polarity"] == 0.5 and s["agreement_human"]["relevant"] == 1.0
    assert abs(s["agreement_human"]["macro"] - (1.0 + 0.5 + 1.0) / 3) < 1e-9 and s["agreement_machine_irrelevant"] == 1.0
    assert s["accepted"] == 3 and abs(s["cost_per_accepted"] - 0.10) < 1e-9 and s["schema_compliance"] == 1.0

def test_select_reader_rule():
    S = lambda fid, mac, cpa: {"fidelity": fid, "agreement_human": {"macro": mac}, "cost_per_accepted": cpa}
    r = select_reader({"a": S(0.99, 0.90, 0.05), "b": S(0.98, 0.92, 0.01), "c": S(0.90, 0.99, 0.001)})
    assert r["winner"] == "b" and r["eliminated"] == ["c"] and r["shortfall"] is False
    r2 = select_reader({"a": S(0.99, 0.80, 0.05), "b": S(0.98, 0.83, 0.01)})
    assert r2["winner"] == "b" and r2["shortfall"] is True and "highest-agreement" in r2["rule"]
    r3 = select_reader({"a": S(0.5, 0.99, 0.01)})
    assert r3["winner"] is None and r3["eliminated"] == ["a"]
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: corpus_engine.reader.measure`.

- [ ] **Step 3: Implement**

```python
# corpus_engine/reader/measure.py
from __future__ import annotations
import json, math, random
from pathlib import Path
from corpus_engine.reader.driver import agreement
from corpus_engine.reader.model import CaseText, ReadingOutcome
from corpus_engine.reader.sources import InlinedCaseSource

BAR_FIELDS = ("relevant", "polarity", "who_was_letting")
KIT_SEED = 20260904


def load_kit(path: Path):
    k = json.loads(Path(path).read_text(encoding="utf-8"))
    texts = {int(c): CaseText(int(c), t["cite"], t["name"], t["court"], t["jurisdiction"], t["year"], t["raw_text"], t["norm_text"], t["page_map"])
             for c, t in k["texts"].items()}
    return k["reference"], k["batches"], InlinedCaseSource(texts)


def kit_sample_50(reference: list[dict]) -> list[int]:
    human = sorted(r["case_id"] for r in reference if r["source"] == "human")
    return sorted(random.Random(KIT_SEED).sample(human, min(50, len(human))))


def score_candidate(outcome: ReadingOutcome, reference: list[dict]) -> dict:
    ref = {int(r["case_id"]): r for r in reference}
    recs = outcome.records; by_id = {int(r["case_id"]): r for r in recs if r.get("case_id") is not None}
    kept = sum(len(r.record.get("quotes") or []) for u in outcome.units for r in u.records if r.record.get("relevant"))
    dropped = sum(r.dropped_quotes for u in outcome.units for r in u.records if r.record.get("relevant"))
    fidelity = kept / (kept + dropped) if (kept + dropped) else 0.0
    human = [r for r in reference if r["source"] == "human"]
    ag = agreement([by_id[c] for c in by_id if c in ref and ref[c]["source"] == "human"], human, BAR_FIELDS)
    ag["macro"] = sum(ag[f] for f in BAR_FIELDS) / len(BAR_FIELDS)
    machine = [r for r in reference if r["source"] == "machine"]
    mi = (sum(1 for r in machine if by_id.get(r["case_id"], {}).get("relevant") is False) / len(machine)) if machine else None
    n_cases = sum(len(u.records) for u in outcome.units) or sum(len(u.case_ids) for u in outcome.plan.units)
    accepted = sum(1 for r in recs if r.get("extraction_status") in ("ok", "partial") and r.get("relevant") is not None)
    return {"fidelity": fidelity, "agreement_human": ag, "agreement_machine_irrelevant": mi,
            "schema_compliance": (len(recs) / n_cases) if n_cases else 0.0, "accepted": accepted,
            "cost_per_accepted": (outcome.spend_usd / accepted) if accepted else math.inf, "spend_usd": outcome.spend_usd,
            "wall_seconds": round(outcome.wall_seconds, 1), "provider_reported": outcome.manifest.get("provider_reported"),
            "failed_units": outcome.failed_units, "stop": outcome.stop.kind}


def select_reader(scores: dict[str, dict], *, fidelity_floor: float = 0.97, agreement_bar: float = 0.85) -> dict:
    eliminated = sorted(k for k, s in scores.items() if s["fidelity"] < fidelity_floor)
    survivors = {k: s for k, s in scores.items() if k not in eliminated}
    if not survivors:
        return {"winner": None, "rule": "no candidate cleared the fidelity floor", "survivors": [], "eliminated": eliminated, "shortfall": True}
    over = {k: s for k, s in survivors.items() if s["agreement_human"]["macro"] >= agreement_bar}
    if over:
        w = min(over, key=lambda k: (over[k]["cost_per_accepted"], k))
        return {"winner": w, "rule": f"cheapest cost per accepted record among survivors with macro agreement >= {agreement_bar}",
                "survivors": sorted(survivors), "eliminated": eliminated, "shortfall": False}
    w = max(survivors, key=lambda k: (survivors[k]["agreement_human"]["macro"], -survivors[k]["cost_per_accepted"]))
    return {"winner": w, "rule": f"no survivor reached {agreement_bar}; highest-agreement survivor chosen (shortfall disclosed)",
            "survivors": sorted(survivors), "eliminated": eliminated, "shortfall": True}


def stability_agreement(out_a: ReadingOutcome, out_b: ReadingOutcome, fields=BAR_FIELDS) -> dict[str, float]:
    return agreement(out_a.records, out_b.records, fields)
```

```python
# tools/build_reader_kit.py
"""One-time: freeze the reader kit (spec §6): 155 human-reviewed ledger records + 45 machine-irrelevant reads, texts inlined."""
import hashlib, json, random, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                  # noqa: E402
from corpus_engine.domain import load_domain                                     # noqa: E402
from corpus_engine.ledger import open_ledger                                     # noqa: E402
from corpus_engine.ranker.labels import labelled_reads, read_extractions         # noqa: E402
from corpus_engine.reader.measure import KIT_SEED, kit_sample_50                 # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                         # noqa: E402

if __name__ == "__main__":
    dom = load_domain(); out = ROOT / dom.reader.kit_path
    if out.exists():
        sys.exit(f"{out} exists; a new kit is a new version")
    conn = store.connect(); view = open_ledger(domain=dom).view()
    human = []
    for cid in view.state.order:
        if view.state.in_file.get(cid) and view.reviewed(cid):
            r = view.state.records[cid]
            human.append({"case_id": int(cid), "source": "human", "relevant": bool(r.get("relevant")), "polarity": r.get("polarity"),
                          "who_was_letting": r.get("who_was_letting")})
    labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    neg = [l for l in labels if l.label == 0]; rng = random.Random(KIT_SEED)
    strata = {}
    for l in neg:
        strata.setdefault((l.era, l.jurisdiction), []).append(l)
    picked = []
    quota = max(1, 45 // len(strata))
    for k in sorted(strata):
        picked += rng.sample(strata[k], min(quota, len(strata[k])))
    picked = picked[:45]
    machine = [{"case_id": l.case_id, "source": "machine", "relevant": False, "polarity": "irrelevant", "who_was_letting": None} for l in picked]
    reference = human + machine
    ids = [r["case_id"] for r in reference]
    meta = {r[0]: r for r in conn.execute(f"SELECT case_id, era_partition, jurisdiction FROM cases WHERE case_id IN ({','.join('?'*len(ids))})", ids)}
    for r in reference:
        r["era"], r["jurisdiction"] = meta[r["case_id"]][1], meta[r["case_id"]][2]
    sig = {}
    for i in range(0, len(ids), 500):
        ch = ids[i:i+500]
        for cid, sid, ver, mt in conn.execute(f"SELECT case_id, selector_id, selector_version, matched_text FROM signals WHERE case_id IN ({','.join('?'*len(ch))})", ch):
            sig.setdefault(cid, []).append({"selector_id": sid, "selector_version": ver, "matched_text": mt or ""})
    groups = {}
    for r in sorted(reference, key=lambda r: r["case_id"]):
        groups.setdefault((r["era"], r["jurisdiction"]), []).append(r["case_id"])
    batches, n = [], 0
    for (era, jur), cids in sorted(groups.items()):
        for j in range(0, len(cids), 18):
            n += 1
            batches.append({"batch_id": f"kit-v1-batch-{n:03d}", "era_partition": era, "jurisdiction": jur,
                            "cases": [{"case_id": c, "signals": sig.get(c, [])[:6]} for c in cids[j:j+18]]})
    texts = {str(t.case_id): {"cite": t.cite, "name": t.name, "court": t.court, "jurisdiction": t.jurisdiction, "year": t.year,
                              "raw_text": t.raw_text, "norm_text": t.norm_text, "page_map": t.page_map} for t in StoreCaseSource(conn).fetch(ids)}
    kit = {"version": "v1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": KIT_SEED, "reference": reference, "batches": batches, "texts": texts}
    out.parent.mkdir(parents=True, exist_ok=True); (out.parent / "batches").mkdir(exist_ok=True)
    out.write_bytes(json.dumps(kit, sort_keys=True).encode("utf-8"))
    for b in batches:
        (out.parent / "batches" / f"{b['batch_id']}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    (out.parent / "sample-50.json").write_bytes(json.dumps(kit_sample_50(reference)).encode("utf-8"))
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"kit: {len(human)} human + {len(machine)} machine = {len(reference)} cases, {len(batches)} batches, {sum(len(t['raw_text']) for t in texts.values()):,} chars")
    print("sha256:", h, "-> set reader.kit_sha256 in domain.yaml")
```

```python
# tools/export_reader_kit.py
"""Regenerate the self-contained external kit (C:\\Users\\marcu\\Desktop\\str-mapper-experiment) from data/reader/kit-v1."""
import json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine.domain import load_domain                                     # noqa: E402
if __name__ == "__main__":
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\marcu\Desktop\str-mapper-experiment")
    dom = load_domain(); kit = json.loads((ROOT / dom.reader.kit_path).read_text(encoding="utf-8"))
    (dst / "batches").mkdir(parents=True, exist_ok=True); (dst / "reference").mkdir(exist_ok=True); (dst / "prompts").mkdir(exist_ok=True)
    for b in kit["batches"]:
        for c in b["cases"]:
            c["opinion_text"] = kit["texts"][str(c["case_id"])]["raw_text"]
        (dst / "batches" / f"{b['batch_id']}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    (dst / "reference" / "human.json").write_bytes(json.dumps(kit["reference"], indent=1).encode("utf-8"))
    shutil.copy(ROOT / "domains" / dom.name / dom.reader.codebooks_dir / f"{dom.reader.codebook}.md", dst / "prompts" / "mapper.md")
    (dst / "KIT-VERSION").write_bytes(b"kit-v1 (human-adjudicated reference; regenerated by tools/export_reader_kit.py)\n")
    print("exported", len(kit["batches"]), "batches to", dst)
```

- [ ] **Step 4: Tests, then build the kit once, pin the hash**

Run: `.venv\Scripts\python -m pytest tests/test_reader_measure.py -q` — Expected: 2 passed.
Run: `.venv\Scripts\python tools\build_reader_kit.py` (live DB read-only, ledger, extractions). Expected: `155 human + 45 machine = 200 cases`, ≈ 12–20 batches, a sha256. Put the hash (quoted) into `domain.yaml` `reader.kit_sha256`. Check `git check-ignore -v data/reader/kit-v1/kit.json` — if `data/` rules ignore it, add `!data/reader/` negations (the kit is ~5–10 MB of text; committing it is intended). Run `.venv\Scripts\python tools\export_reader_kit.py` and confirm the external directory has `batches/`, `reference/human.json`, `prompts/mapper.md`, `KIT-VERSION`; do not commit the external directory (outside the repo).

- [ ] **Step 5: Commit**
```bash
git add corpus_engine/reader/measure.py tools/build_reader_kit.py tools/export_reader_kit.py tests/test_reader_measure.py data/reader/kit-v1 domains/str-right-to-let/domain.yaml .gitignore
git commit -m "reader: scorer and pre-registered selection rule; kit v1 frozen (155 human + 45 machine) and exported"
```

---

### Task 7: The measurement run, winner's checks, report, ADR amendment, docs

**Files:**
- Create: `tools/measure_reader.py`, `data/reader/measurement-v1/manifest.json` (generated), `reports/reader-measurement.md`, `domains/str-right-to-let/codebooks/stability/<mapper-v2 sha>.json` (generated)
- Modify: `domains/str-right-to-let/domain.yaml` (`reader.model`), `docs/adr/0007-*.md` (amendment), `reports/handoff-cycle-004.md` (item 7), `docs/superpowers/specs/2026-09-04-stage-3a-reader-driver-design.md` (§4 raw_text correction), `CONTEXT.md` (vocabulary), `README.md` (one line)

- [ ] **Step 1: Write the measurement tool**

```python
# tools/measure_reader.py
"""Pre-registered reader-model measurement (spec §6). One shared Budget across all candidates; every response cached."""
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from corpus_engine import store                                                          # noqa: E402
from corpus_engine.domain import load_domain                                             # noqa: E402
from corpus_engine.ranker.labels import sha256_file                                      # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                     # noqa: E402
from corpus_engine.reader.codebook import load_codebook, stability_path                  # noqa: E402
from corpus_engine.reader.driver import Reader, plan_batch_extraction                    # noqa: E402
from corpus_engine.reader.measure import load_kit, score_candidate, select_reader, stability_agreement  # noqa: E402
from corpus_engine.reader.model import Budget, ModelPin, Plan, Unit                      # noqa: E402
from corpus_engine.reader.providers.openrouter import OpenRouterProvider                 # noqa: E402

OPEN_PRECISIONS = ("bf16", "fp8")


def pin_for(cand: dict, prov: OpenRouterProvider) -> ModelPin | None:
    if not cand.get("pin_open"):
        return ModelPin(cand["model_id"], cand["family"])
    info = prov.probe_model(cand["model_id"])
    if not info:
        return None
    # pick the first endpoint serving an allowed precision; OpenRouter lists endpoints at /models/{id}/endpoints
    import httpx
    eps = httpx.get(f"{prov.base}/models/{cand['model_id']}/endpoints", headers={"Authorization": f"Bearer {prov.key}"}, timeout=60).json()
    for e in (eps.get("data") or {}).get("endpoints", []):
        q = (e.get("quantization") or "").lower()
        if q in OPEN_PRECISIONS:
            return ModelPin(cand["model_id"], cand["family"], e.get("provider_name") or e.get("name"), q)
    return None


def run_candidate(label, pin, kit_batches, source, dom, prov, budget_state, cache, log):
    plan = plan_batch_extraction(kit_batches, dom.reader.codebook, pin, Budget(max_usd=budget_state["remaining"]), worker="reader")
    out = Reader(prov, source, cache=cache, log=log, domain=dom).read(plan)
    budget_state["remaining"] -= out.spend_usd; budget_state["spent"] += out.spend_usd
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--max-usd", type=float, default=50.0); ap.add_argument("--only", default=None)
    a = ap.parse_args(); dom = load_domain(); kit_path = ROOT / dom.reader.kit_path
    if dom.reader.kit_sha256 and sha256_file(kit_path) != dom.reader.kit_sha256:
        sys.exit("kit sha256 does not match domain.yaml; never edit the kit")
    reference, batches, source = load_kit(kit_path)
    key = store.env_value("OPENROUTER_API_KEY") or sys.exit("no OPENROUTER_API_KEY")
    prov = OpenRouterProvider(key); cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    out_dir = ROOT / "data" / "reader" / "measurement-v1"; out_dir.mkdir(parents=True, exist_ok=True)
    cb = load_codebook(dom, dom.reader.codebook)
    sp = stability_path(dom, cb)
    if not sp.exists():   # the measurement itself is the stability run for v2: grant a provisional record, replaced in step 3
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_bytes(json.dumps({"codebook": cb.id, "provisional": True, "note": "measurement in progress"}).encode())
    budget = {"remaining": a.max_usd, "spent": 0.0}; scores, pins, skipped = {}, {}, {}
    for cand in dom.reader.candidates:
        if a.only and cand["model_id"] != a.only:
            continue
        pin = pin_for(cand, prov)
        if pin is None:
            skipped[cand["model_id"]] = "no bf16/fp8 endpoint or model not served"; print("SKIP", cand["model_id"]); continue
        print(f"== {pin.label}  (remaining ${budget['remaining']:.2f})")
        out = run_candidate(pin.label, pin, batches, source, dom, prov, budget, cache, print)
        scores[pin.model_id] = score_candidate(out, reference); pins[pin.model_id] = pin.label
        s = scores[pin.model_id]
        print(f"   fidelity={s['fidelity']:.4f} macro={s['agreement_human']['macro']:.4f} cpa=${s['cost_per_accepted']:.4f} spend=${s['spend_usd']:.2f} stop={s['stop']}")
        if budget["remaining"] <= 0:
            print("budget exhausted"); break
    sel = select_reader(scores)
    manifest = {"kit_sha256": dom.reader.kit_sha256, "codebook": cb.id, "codebook_sha": cb.sha, "budget_usd": a.max_usd, "spent_usd": round(budget["spent"], 4),
                "pins": pins, "skipped": skipped, "scores": scores, "selection": sel, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if sel["winner"]:
        w = sel["winner"]; wpin = next(p for c in dom.reader.candidates if c["model_id"] == w for p in [pin_for(c, prov)])
        # batch-size pair: 5-case batches over the same kit
        small = []
        for b in batches:
            for j in range(0, len(b["cases"]), 5):
                small.append({**b, "batch_id": f"{b['batch_id']}-s{j // 5 + 1}", "cases": b["cases"][j:j+5]})
        out5 = run_candidate(w + ":b5", wpin, small, source, dom, prov, budget, cache, print)
        manifest["batch_size_pair"] = {"b18": scores[w], "b5": score_candidate(out5, reference)}
        # stability: two reads of the 50-case sample (cache key differs by unit id so the second read is paid)
        ids50 = json.loads((ROOT / dom.reader.stability_sample).read_text(encoding="utf-8"))
        sb = [b for b in batches]
        def sub(tag):
            units = []
            for b in sb:
                cs = [c for c in b["cases"] if c["case_id"] in ids50]
                if cs: units.append({**b, "batch_id": f"{b['batch_id']}-{tag}", "cases": cs})
            return units
        o1 = run_candidate(w + ":stab1", wpin, sub("st1"), source, dom, prov, budget, cache, print)
        o2 = run_candidate(w + ":stab2", wpin, sub("st2"), source, dom, prov, budget, cache, print)
        stab = stability_agreement(o1, o2); manifest["stability"] = stab
        stable = all(v >= 0.90 for v in stab.values())
        sp.write_bytes(json.dumps({"codebook": cb.id, "codebook_sha": cb.sha, "model_pin": wpin.label, "sample": dom.reader.stability_sample,
                                   "agreement": stab, "stable": stable, "ts": manifest["ts"]}, indent=1).encode("utf-8"))
        manifest["winner_pin"] = wpin.label; manifest["spent_usd"] = round(budget["spent"], 4)
    (out_dir / "manifest.json").write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    print(json.dumps(sel, indent=1)); print(f"total spent ${budget['spent']:.2f}")
    print("set reader.model in domain.yaml to:", manifest.get("winner_pin"))
```

- [ ] **Step 2: Run the measurement (user-approved, $50 ceiling)**

Pre-checks: GPU not needed; `OPENROUTER_API_KEY` in `.env`; credits ≥ $50 (`GET /credits`). Run: `.venv\Scripts\python tools\measure_reader.py --max-usd 50` in the foreground (timeout 60 min; expect 20–40 min). If it stops on budget before all candidates ran, the manifest records which ran; re-running resumes from the cache. Record the printed selection, spend, skipped candidates (and why), the batch-size pair, and the stability result. Set `domain.yaml` `reader.model` to `{model_id, family, provider_name, precision}` of the winner (byte-safe write). Commit `data/reader/measurement-v1/manifest.json`, the stability record, and `data/reader/cache/` is **not** committed (add `data/reader/cache/` to `.gitignore`).

- [ ] **Step 3: Report and docs**

`reports/reader-measurement.md`: the candidate table (pin as served, fidelity, per-field and macro agreement, machine-irrelevant agreement, schema compliance, accepted, cost per accepted, spend, wall), skipped candidates with reasons, the selection with the rule applied and whether a shortfall was disclosed, the batch-size pair, the stability result, total spend vs the $50 ceiling, the kit sha and codebook sha, and the decisions recorded (checker via Codex CLI at the user's direction; no quantization pair; pinning).
`docs/adr/0007-*.md`: append `## Amendment 2026-09-04` with those decisions and the measured winner.
`reports/handoff-cycle-004.md` item 7: mark done with the winner and a pointer to the report.
Spec §4: replace "`norm_text`" with "`raw_text` (as the legacy mapper and the Stage 1 goldens; the gate normalizes)".
`CONTEXT.md`: add Plan/Unit, Codebook, Quote gate, Reference set/kit, Accepted record, Reader/checker (glossary style).
`README.md`: one line under the tools section for `tools\measure_reader.py`.

- [ ] **Step 4: Full suite, commit**

Run: `.venv\Scripts\python -m pytest tests -q` — Expected: green.
```bash
git add tools/measure_reader.py data/reader/measurement-v1 domains/str-right-to-let reports/reader-measurement.md docs/adr/0007-*.md reports/handoff-cycle-004.md docs/superpowers/specs/2026-09-04-stage-3a-reader-driver-design.md CONTEXT.md README.md .gitignore
git commit -m "reader measurement v1: ten candidates under the pre-registered bar; winner pinned; ADR-0007 amended"
```

---

## Self-review notes (done while writing)

- Spec coverage: §3 module/ports/adapters → T1, T4, T5; §4 codebooks/render/pre-flight/stability → T2, T5, T7; §5 read loop/gate/budget/cache/checker → T3, T5; §6 kit + measurement + selection + pairs → T6, T7; §7 errors → T3/T4/T5 (failed/parse_failed/missing/pre-flight); §8 tests → each task; §9 rollout → T6/T7; ADR-0007 amendment and handoff → T7.
- Type consistency: `RecordResult/UnitResult/ReadingOutcome` fields identical across T1/T3/T5/T6; `Request/Response` identical across T1/T4/T5; `render_unit(codebook, unit, texts, worker)` used identically in T2 and T5; `agreement()` defined once (T5) and reused (T6); `Budget`/`StopReason` kinds as listed in Global Constraints.
- Deviation recorded: `raw_text` rendering (matches goldens) — spec corrected in T7. Stability for `mapper-v1` is grandfathered with an explicit record (cycles 001–003 ran it); v2's record is produced by the measurement.
