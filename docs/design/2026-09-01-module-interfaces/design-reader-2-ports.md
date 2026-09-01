# Reader driver — ports-and-adapters design

Summary:
1. One deep module corpus.reader, one method Reader.read(plan) -> ReadingOutcome, reads cases under a codebook; grouping, retry, halving, per-group caching, checker sampling, quote gate, run-metadata recording behind it.
2. Two ports: Provider (true external LLM) and CaseSource (remote-owned corpus store).
3. Provider adapters: OpenRouter transport, recorded cassette, legacy subprocess CLI (+ AnthropicBatch if Claude wins); CaseSource adapters: SQLite store, inlined-text source (experiment kit + fixtures).
4. Kit and checker are not separate code paths: kit = Reader over InlineCaseSource across N ModelPins; checker = a second ReadingPlan on a sample; agreement() is one pure function used by kit, checker, and the stability check.
5. Quote gate inside the driver; extractions/ and verified/ reproduced byte-for-byte by replaying a cassette against the fixture corpus.

## Ports
```python
@dataclass(frozen=True) class ModelPin: model_id; provider_order: tuple[str, ...] = (); allow_fallbacks=False; quantization=None; effort=None; temperature=0.0; max_output_tokens=32_000
@dataclass(frozen=True) class Completion: text; usage (input/output/cached); resolved_model; resolved_endpoint; finish_reason; latency_ms; response_sha256
class Provider(Protocol):
    name: str; supports_json_schema: bool
    def complete(self, *, prompt, model: ModelPin, response_schema, timeout_s) -> Completion
ProviderTransient (retry/backoff) | ProviderOverlong (halve group) | ProviderExhausted (stop cleanly) | ProviderMisconfigured (fail fast)

@dataclass(frozen=True) class CaseText: case_id; cite; name; court; jurisdiction; year; raw_text; norm_text; page_map; norm_version
class CaseSource(Protocol):
    def load(self, case_ids) -> Mapping[int, CaseText]
```
CaseText carries norm_text/page_map/norm_version because the gate lives inside the driver (contrast four independent SELECT raw_text sites: run_map.py:39-44, pre_review.py:52-54, polarity_review.py:86-88, relevance_recheck.py:38-40).

## Codebook (data)
```python
@dataclass(frozen=True) class QuoteGatePolicy: supported_fields; fuzzy_threshold=92.0; skip_when_irrelevant=True
@dataclass(frozen=True)
class Codebook:
    id; version; prompt; response_schema; required_fields; key_field; every_key_required
    render_case: Callable[[CaseText, Mapping], str]; quote_gate: QuoteGatePolicy | None; compare_fields; sha256
def load_codebook(domain_dir, codebook_id, version) -> Codebook
```

## Plan and results
```python
@dataclass(frozen=True) class ReadingGroup: group_id; case_ids; header=""; context: Mapping[int, Mapping] = {}
@dataclass(frozen=True) class CheckerPlan: model: ModelPin; codebook; sample_every=10; compare_fields
@dataclass(frozen=True) class ReadingPlan: run_id; codebook; model: ModelPin; groups; checker=None; concurrency=2; timeout_s=900; min_group_size=1; resume=True
def group_cases(case_ids, *, size, run_id, key=None) -> tuple[ReadingGroup, ...]
@dataclass(frozen=True) class Reading: case_id; group_id; record (post-gate); raw_record; status: ok|partial|extraction-invalid|missing; reading_id = sha256(codebook.sha|pin|group_id|case_ids|rendered prompt)
@dataclass(frozen=True) class Disagreement: case_id; field; group_id; reader_value; checker_value
@dataclass(frozen=True) class ReadingOutcome: readings (plan order); failures; disagreements; stats; stopped_early
class Reader:
    def __init__(self, *, provider, cases, log: ReadingLog, sleep=time.sleep)
    def read(self, plan) -> ReadingOutcome
def agreement(a, b, fields) -> (disagreements, rates)
```

## Invariants
Every key accounted for (else halve). Nothing ungated escapes. Never degrade tier. Idempotent resume keyed on content (codebook sha, pin, case ids, rendered prompt), not filename. Deterministic given a Provider (results re-sorted to plan order). Checker never writes the record. Halved subgroups keep parent ordinal (batch-007a/b).
Errors: ProviderTransient backoff 20/60/180s x3; Overlong/parse => halve recursively to min_group_size, size-1 failure => status missing; Exhausted => drain, flush, return stopped_early; Misconfigured => raise; missing case => status missing; norm_version mismatch => StaleCorpusError before any call; checker failure logged never fails plan.
ReadingLog (internal): one JSONL line per reading: reading_id, run_id, group_id, case_ids, codebook id/version/sha, pin fields, usage, latency, outcome, response_sha256, ts; supersedes map-usage.jsonl (raw envelope kept under provider_usage_raw). Source for methods appendix, kit cost-per-accepted-record, certification reuse.

## Dependencies
Provider true external (OpenRouterProvider with body pin; AnthropicBatchProvider; SubprocessCliProvider transitional; RecordedProvider; ScriptedProvider). CaseSource remote-owned (SqliteCaseSource; InlineCaseSource — the kit's own source). Verification, textnorm in-process. Codebooks in-process data (domains/str/codebooks/{extraction-v2, remap-v1, adjudicate-v1, fuzzy-review-v1, polarity-v1, relevance-recheck-v1}.md + schemas). Log local-substitutable internal.
Kit: corpus/reader/kit.py build_kit(plan, out_dir), score_kit(kit_dir, model); deletes the 80-line scorer string in make_experiment_kit.py:82-164 (a drifting fork of verify_quote).

## Trade-offs
SqliteCaseSource near pass-through, earned by InlineCaseSource. ReadingGroup.context loosely typed (domain shapes stay out of engine). Reading.record is Mapping (ledger owns the record type; v1/v2 coexistence). Anthropic Batch: adapter blocks internally; add complete_many later if needed. Per-model prompt tuning deliberately expensive. Planner/Reducer stay outside.

## Characterization
A. Freeze cassette + golden prompts at the pre-refactor commit: build_payload per batch -> prompts/batch-NNN.txt; extractions as replies keyed by prompt sha.
B. Prompt-rendering equivalence for all batches byte-for-byte (catches reordering, separators, matched_text[:160] truncation at run_map.py:58-60).
C. extractions/ reproduction (indent=1, no sort_keys, no trailing newline).
D. verified/ reproduction from checked-in extractions through the gate — strongest, no provider; pins extraction_status, nulled fields, quotes[].status/raw_span/reporter_page, fuzzy_score; norm_version mismatch must fail loudly.
E. Checker: replay extractions-codex vs extractions through agreement(); serialize to disagreements.jsonl line-for-line.
F. Ledger closure belongs to the ledger suite; meets at verified/.
Behavioural tests with ScriptedProvider: halving, backoff with injected sleep, clean stop + resume, cache invalidation on codebook bump, checker failure isolation, identical ModelPin on every request.
