# Reader driver — minimal-interface design

Summary:
1. One workhorse: ReaderDriver.read(plan) -> ReadingReport serves batch extraction, single re-read, adjudication, fuzzy-quote review, polarity re-review, relevance re-check, stability check, and the experiment-kit sweep.
2. Interface is "read cases under a codebook", not "read batches"; grouping, split-on-parse-failure, retry, resume, checker sampling, disagreement computation are hidden policy.
3. Quote gate inside the driver; callers only see post-gate records.
4. Exactly one port: Transport (one method), four adapters (OpenRouter, native Anthropic Batch, codex exec subprocess, recorded replay). Corpus store, verification, codebook injected in-process, not ported.
5. Characterization: replay extractions/ through the driver as a fixture transport and assert verified/ byte-identical (151 files).

## Interface
```python
class ReaderDriver:
    def __init__(self, *, corpus: CorpusStore, codebook: Codebook, transport: Transport, runs_dir: Path, config: ReaderConfig = ReaderConfig())
    def read(self, plan: ReadingPlan) -> ReadingReport

ReaderConfig: concurrency=3, group_size=18, retries=1, checker_sample=0.10, checker_model, provider_pin, effort, artifact_layout: "v1-legacy"|"v2", sleep, now

@dataclass(frozen=True) class Subject: case_id: int | None; group: str; vars: Mapping[str, Any]
@dataclass(frozen=True)
class ReadingPlan:
    run_id: str; task: str   # "extract"|"remap"|"adjudicate"|"fuzzy-review"|"polarity"|"relevance"|"stability"
    subjects: Sequence[Subject]
    models: Sequence[str] = ()          # () -> task's pinned model; >1 -> kit sweep
    checker: str | None | "" = None     # None default; "" none
    group_size: int | None = None; concurrency: int | None = None; resume: bool = True
@dataclass(frozen=True) class Reading: reading_id; case_id; group; task; model; provider_served; codebook_version; status: ok|partial|extraction-invalid|unread; record: dict | None; usage: Usage
@dataclass(frozen=True) class ReadingReport: run_id; task; readings; disagreements; unread; metadata: RunMetadata; def records(model=None)

class Transport(Protocol):
    id: str
    def complete(self, req: TransportRequest) -> TransportReply
TransportRequest: model, system, user, json_schema, max_output_tokens, temperature, provider (pin body), effort, idempotency_key
TransportReply: text, usage, model_served, provider_served, raw
TransportBlocked(retry_after_s); TransportFailed; ReaderError: UnknownTask, MissingSubjectVars, CodebookNotFrozen, NormVersionMismatch
```

## Invariants
Every subject appears once per model. Every record has passed the gate. Tier never degrades (provider fallbacks disabled). Idempotent per (run_id, task, group, model) with resume. Codebook version + norm_version immutable per run. Pre-flight: norm_version check and codebook stability-check pass before the first request (zero tokens on misconfig). Checker readings checkpointed separately (fixes run_map.py:139-176 where crash during codex leaves group cached but unchecked). Checker sampling by stable hash of group, not enumeration index (run_map.py:196-197 changes the sample when --max-batches changes).
Failure is data (unread), not exceptions; TransportBlocked pauses all workers. Split ladder: retry -> halves -> per subject.
Payload assembled codebook-first for prefix caching (map-usage.jsonl shows 166k cached tokens); reordering multiplies cost.

## Dependencies
LLM true external: OpenRouterTransport, AnthropicBatchTransport, CodexSubprocessTransport; test ReplayTransport, ScriptedTransport. Corpus store local-substitutable — no port (fixture DB). Verification in-process. Codebook/domain dir local-substitutable. Runs dir tmp_path. Clock/sleep injected callables.

## Trade-offs
Subject.vars free-form (task declares required keys; MissingSubjectVars before spend). models as a plan flag rather than second entry point. Anthropic Batch async: adapter blocks on poll; read() resumable across restarts via the reading log. Gate inside deliberately awkward to move out.

## Characterization
1. Gate+write: ReplayTransport from extractions/*.json; run with artifact_layout v1-legacy; assert verified/*.json byte-identical (151 batches, ~2,700 records, all verify_record branches).
2. Parse path: wrap extractions in fence/prose shapes; parsed equals file.
3. Payload snapshot: freeze today's build_payload over ten batches as golden; new assembler reproduces char-for-char.
4. Checker/disagreements as a set (as_completed order nondeterministic); legacy index-mod sampling reproduces same groups.
5. Resume and failure ladder with ScriptedTransport.
6. Downstream ledger: apply_adjudications over reproduced verified/ + decisions-final.json => cycle-003.jsonl byte-identical.
7. Cost guard: cached/input ratio not below observed.
