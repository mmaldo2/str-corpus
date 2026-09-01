# Reader driver — common-caller design

Summary:
1. One function executes a reading plan — run_reading(plan, deps) — with plan_batch_extraction(...) making the cycle's resumable, budget-capped batch run a three-line call.
2. Quote gate inside the driver; driver owns the void-then-remap policy (remap_queue in the outcome).
3. Three shapes share the seam via a Codebook value (prompt, schema, gate policy, compare fields) plus pre-rendered ReadingItems.
4. Four ports, each with 2+ adapters: ChatTransport (OpenRouter / Anthropic-native / Codex / replay), CaseTextSource (store / kit-inlined / mapping), RunArtifacts (files / memory), Pacer (real / fake).
5. Characterization on three golden layers: rendered payload bytes, replayed extraction bytes into verified/ bytes, disagreement lines.

## Types
```python
class GatePolicy(StrEnum): CODEBOOK; SUPPORTING_QUOTE; NONE
@dataclass(frozen=True) class Codebook: id; version; prompt_text; json_schema; required_fields; gate: GatePolicy; compare_fields; account_for_every_item=True; content_hash
@dataclass(frozen=True) class ReadingItem: key: str; case_id: int | None; header: str; context: str = ""
@dataclass(frozen=True) class ReadingUnit: unit_id; artifact_name; items; preamble=""
@dataclass(frozen=True) class ModelPin: model; provider_order=(); allow_fallbacks=False; quantization=None; effort=None; temperature=0.0; max_output_tokens=32_000; structured_output=True
@dataclass(frozen=True) class Budget: max_usd=None; max_units=None; max_wall_seconds=None; pause_after_consecutive_rate_limits=3
@dataclass(frozen=True) class CheckerPolicy: model: ModelPin; every_nth_unit=10; transport_name="codex"
@dataclass(frozen=True) class ReadingPlan: run_id; task: Codebook; units; model; budget=Budget(); checker=None; concurrency=2; retries_per_unit=1; split_on_parse_failure=True
class StopReason(StrEnum): COMPLETE; BUDGET; RATE_LIMITED; WALL_CLOCK; CANCELLED
@dataclass(frozen=True) class ReadingOutcome: run_id; stop_reason; units_total; units_read; units_cached; units_failed; records (gated); remap_queue; disagreements; metadata: RunMetadata; cost_usd; resume_command

def plan_batch_extraction(run_id, *, codebook, model, budget=Budget(), checker=None, batch_size=None, deps) -> ReadingPlan
def plan_reread(case_ids, *, codebook, model, group_size=8, run_id, deps) -> ReadingPlan
def plan_judgment(items, *, codebook, model, group_size=5, run_id) -> ReadingPlan
def run_reading(plan, deps) -> ReadingOutcome
@dataclass class ReaderDeps: cases: CaseTextSource; artifacts: RunArtifacts; transports: Mapping[str, ChatTransport]; pacer: Pacer = RealPacer()
```

## Invariants
Every item accounted for (retry -> split -> fail the unit; never partial write). Nothing unverified leaves; extractions/ (raw) and verified/ (gated) both written before a unit is done. Never degrade tier. Codebook identity checked on resume (CodebookMismatch). Every reading logged in runs/<run>/reads.jsonl with read_key = sha256(codebook_hash | pin | sorted item keys) — checkpoint and certification-reuse record.
Per-unit failures are data; exceptions only for ConfigurationError, CodebookMismatch, CorpusNormMismatch, BudgetMisconfigured. 429/5xx => backoff via Pacer; after N consecutive => StopReason.RATE_LIMITED with everything durable. Budget in USD/units/wall-clock replaces --max-batches.

## Dependencies
ChatTransport true external: OpenRouterTransport (body pin), AnthropicNativeTransport (submit+poll inside), CodexExecTransport; ReplayTransport, ScriptedTransport. CaseTextSource local-substitutable promoted to port: StoreCaseText, InlinedCaseText (kit), MappingCaseText. RunArtifacts: FileRunArtifacts / MemoryRunArtifacts. Pacer: Real/Fake. Quote gate: no port (direct call to engine.verification.verify_record).

## Trade-offs
ReadingItem.header/context pre-rendered by caller (captions belong in domains/); plan_batch_extraction renders for the common case. Anthropic Batch: adapter submits and polls, blocking a worker; add complete_many rather than go async. Per-unit cache (not per-case) keeps artifact files byte-comparable. Gate inside means a textnorm bump needs engine.verification.regate_run(run_id).

## Characterization
1. Payload bytes: capture build_payload for batch-001 as golden; driver's rendered unit byte-identical under PayloadLayout.MAPPER_V1.
2. Verified bytes: ReplayTransport.from_extractions over corpus-mini.db seeded with cycle-003 case ids; every verified/batch-NNN.json byte-identical.
3. Extraction bytes round-trip.
4. Disagreement lines for batch-001 as a sorted multiset on (case_id, field).
5. Parse tolerance table (fenced, prose-wrapped, missing case, missing required field).
6. Resume and cap: max_units=3 then re-run => 3 cached, zero re-requests; delete one extraction => exactly that unit re-requested.
7. Ledger suite meets at verified/.
