# Stage 3A — Reader driver and reader-model measurement: design

**Date:** 2026-09-04. **Status:** approved in conversation, pending written review.
**Authority above this document:** `docs/adr/0004`, `0007`, `0009`, `0011`;
`docs/design/2026-09-01-module-interfaces/README.md` (reader driver hybrid); `CONTEXT.md`.
**Depends on:** Stage 2C merged (main `18f632e`); `corpus_engine.verification` (Stage 1);
the 155 human-reviewed ledger records; the cycle-004 ranked batches (`runs/cycle-004-shard-01`).
**Stage 3B (separate spec):** ledger admission of extractions, checker disagreements into the
review queue, the review page, and the cycle-004 map run with a per-cell budget.

## 1. Purpose and decisions

Replace the headless-CLI mapper (`pipeline/run_map.py`) with a provider-neutral reader
driver, then choose the reader model by a pre-registered measurement against
human-adjudicated references.

| Decision | Choice |
|---|---|
| Scope split | 3A = driver + measurement (this spec); 3B = review pipeline + map. |
| Reference set | Rebuilt from the **155 human-reviewed ledger records** (relevance, polarity, who-was-letting), plus a stratified **45-case sample of machine-marked irrelevant reads** flagged `reference: machine`, scored separately and never counted toward the bar. |
| Checker | **Codex command-line tool via subprocess with subscription sign-in, as in cycles 1–3 — the user's decision.** The controller's concern (subscription credentials in automated use; unmeasurable cost; the tool's own harness wrapping the prompt) is recorded, not acted on. The adapter pins the model by flag and records the tool version. |
| Quantization drift | **Not measured.** Open models are pinned to a named bf16/fp8 provider with fallbacks disabled; a candidate with no such endpoint is skipped and the skip recorded. Replaces ADR-0007's fp8-vs-fp4 pair. |
| Long-context drift | Batch-size pair (18-case vs 5-case) on the **winner only**. |
| Measurement budget | **$50 ceiling**, enforced by the driver's `Budget`. |
| Bar (pre-registered) | Quote fidelity < 97% eliminates. Among survivors: cheapest cost per accepted record with agreement ≥ 85% on relevance, polarity, who-was-letting. If none ≥ 85%: highest-agreement survivor, shortfall disclosed in the methods appendix. |
| Approach | One driver, two case sources: the measurement runs through the same driver, renderer, parser, and quote gate as production. |

## 2. Vocabulary (added to `CONTEXT.md` with the implementation)

- **Plan / Unit**: a reading plan is an ordered list of units; a unit is one request (one batch of cases under one codebook and model pin).
- **Codebook**: the versioned extraction instructions (`domains/<domain>/codebooks/mapper-vN.md`), hashed at load.
- **Quote gate**: verification of every quote against source text (exact, then fuzzy ≥ 92); a judged field left without a surviving supporting quote is nulled.
- **Reference set / kit**: the frozen human-adjudicated cases (plus the machine-labelled irrelevant sample) the candidates are measured on.
- **Accepted record**: a record that parsed, passed the gate, and kept its judged fields.
- **Reader / checker**: the model that produces records / the second-family model that re-reads a 10% sample for disagreement.

## 3. Module: `corpus_engine/reader/`

Surface (approved hybrid):

```python
Reader(provider, cases, *, checker=None, log=print, sleep=time.sleep, clock=time.time)
    .read(plan) -> ReadingOutcome
plan_batch_extraction(batches, codebook, model_pin, budget, *, worker) -> Plan
plan_reread(records, codebook, model_pin, budget) -> Plan
plan_judgment(cases, question, codebook, model_pin, budget) -> Plan
agreement(a: list[dict], b: list[dict], fields) -> dict[field, float]
```

Ports:

```python
class Provider(Protocol):
    name: str                                   # "openrouter", "codex-cli", "cassette", "scripted"
    def complete(self, req: Request) -> Response
class CaseSource(Protocol):
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]   # CaseText(case_id, cite, court, year, jurisdiction, norm_text, provenance)
```

`Request(model_pin: ModelPin, system: str | None, user: str, json_schema: dict | None, max_tokens, temperature=0)`;
`ModelPin(model_id, provider_name: str | None, precision: str | None, family: str, extra: Mapping)`;
`Response(text, input_tokens, output_tokens, cost_usd: float | None, provider_reported: Mapping, finish_reason, tool_version: str | None)`.

Adapters: `providers/openrouter.py` (`OpenRouterProvider(api_key, *, timeout=300)` — OpenAI-compatible chat completions; `provider: {order: [name], allow_fallbacks: false, quantizations: [precision]}` for open models; `response_format: {type: json_schema}` when the model supports it, else plain; retry schedule identical to `corpus_engine/indexer/embedders.py` `RETRY_DELAYS`; reads `usage.cost` and `provider`); `providers/codex_cli.py` (`CodexCliProvider(model: str, *, timeout=900)` — `codex exec --sandbox read-only --skip-git-repo-check --model <model> --json -`, parses the tool's JSON event stream for the final message and token counts; records `codex --version`); `providers/cassette.py` (`CassetteProvider(dir, *, fallback=None)` — replays by request content hash; records when a fallback provider is given); `providers/scripted.py` (canned responses for unit tests).
Case sources: `StoreCaseSource(conn)`; `InlinedCaseSource(cases: Mapping[int, CaseText])`.

Files: `model.py` (frozen types: `Plan`, `Unit`, `Budget`, `StopReason`, `ReadingOutcome`, `UnitResult`, `RecordResult`, `Disagreement`), `ports.py`, `providers/*.py`, `sources.py`, `codebook.py` (load + sha + stability lookup), `render.py`, `parse.py`, `gate.py`, `cache.py`, `driver.py`, `measure.py`.

`corpus_engine` stays domain-agnostic: codebook text, field names that are "judged", the checker sample rate, the two-family rule's family labels, and the reference-set path come from `domain.yaml` (`reader:` section) and the codebook.

## 4. Codebooks, rendering, pre-flight

- `domains/str-right-to-let/codebooks/mapper-v1.md` = the frozen text of `prompts/mapper.md` (copied byte-for-byte; `prompts/mapper.md` stays as the historical file the Stage 1 goldens reference). `mapper-v2.md` adds the ADR-0004 fields: `schema_version: 2`, `who_was_letting` gains `non_resident_owner`, `under_thirty_days: yes|no|unclear`, `restriction_nature` on adverse records, `owner_freedom_characterization`; each judged field needs a supporting quote.
- `render.py`: request = codebook + `# Batch <id> (<era> x <jurisdiction>)` header naming worker and batch id + per case: id, cite/name/court/year, provenance (selector ids and matched text), `### Opinion text`, `raw_text` (as the legacy mapper and the Stage 1 goldens; the gate normalizes). Under `mapper-v1.md` the rendering is byte-identical to the Stage 1 golden prompts (`tests/golden/prompts/`).
- Pre-flight (before any paid request): (1) `store` norm version == the codebook's `validated_norm_version`; (2) a stability record exists at `domains/<domain>/codebooks/stability/<codebook sha>.json` (or the plan is itself the stability run); (3) the model pin resolves (model id exists; for open models the named provider serves it at the required precision) — probed with a metadata request, not a completion; (4) reader and checker families differ. Failure ⇒ `StopReason("preflight:<check>")`, nothing spent.
- Stability check (ADR-0009): the winner reads the fixed fifty-case sample (`domains/.../codebooks/stability/sample-50.json`, frozen from the reference set) twice; per-field self-agreement is recorded; the codebook is "stable" if agreement ≥ 90% on the three judged fields.

## 5. The read loop

For each unit in plan order:
1. Render; compute `cache_key = sha256(codebook_sha | model_pin | unit.id | sorted case ids | rendered prompt)`.
2. Cache hit ⇒ use the stored raw response. Miss ⇒ `Budget` check (spend, units, wall) ⇒ `provider.complete` ⇒ store the raw response in `runs/<run>/cache/<key>.json` (also under `data/reader/cache/` for the measurement) before parsing.
3. Parse: one JSON array, one record per case (fences stripped). Failure ⇒ split the unit into two halves and re-request each (once); still failing ⇒ `UnitResult(status="parse_failed")`, raw kept.
4. Gate: every quote verified (`corpus_engine.verification.verify_quote`, exact then fuzzy ≥ 92); failed quotes dropped; a judged field with no surviving `supports` quote is nulled and `gate_notes` records it. Every case in the unit gets a record (missing ⇒ a stub with `relevant: null`, `gate_notes: "missing from response"`).
5. Checker: if `hash(unit.id) % 100 < sample_pct` and a checker is configured, render the same unit for the checker (worker name differs), parse + gate the same way, and record `Disagreement(case_id, field, reader_value, checker_value)` for relevance, polarity, characterization.
6. Append `UnitResult`; update spend/tokens/wall.

Stop conditions: budget exhausted (`budget:usd|units|wall`), pre-flight failure, or plan end. The outcome carries `resume_command` (a literal CLI line re-running the same plan; the cache makes completed units free).

`ReadingOutcome`: units, records (verified), dropped-quote and nulled-field counts, disagreements, spend, tokens, wall seconds, stop reason, manifest `{codebook_sha, model_pin, provider_reported, tool_version, checker_pin, sample_pct, engine_version}`.

## 6. Measurement

`tools/build_reader_kit.py` (run once; refuses to overwrite): the 155 human-reviewed ledger records with human values of `relevant`, `polarity`, `who_was_letting`, plus 45 machine-irrelevant reads sampled with `random.Random(20260904)` stratified by era × jurisdiction, flagged `reference: "machine"`. Texts inlined; packed 18 per batch by era × jurisdiction like production. Written to `data/reader/kit-v1/{kit.json, batches/}`; sha256 pinned in `domain.yaml` `reader.kit_sha256`; the external kit at `C:\Users\marcu\Desktop\str-mapper-experiment` is regenerated from it by `tools/export_reader_kit.py` (self-contained artifact).

`tools/measure_reader.py`: candidates from `domain.yaml` `reader.candidates` (the ADR-0007 ten with OpenRouter ids and, for open models, a pinned provider + precision):

| Candidate | OpenRouter id | Pin |
|---|---|---|
| Claude Sonnet 5 | `anthropic/claude-sonnet-5` | — |
| Claude Opus 5 | `anthropic/claude-opus-5` | — |
| Claude Haiku 4.5 | `anthropic/claude-haiku-4.5` | — |
| Gemini 3.7 Flash | `google/gemini-3.7-flash` | — |
| GPT-5.6 Terra | `openai/gpt-5.6-terra` | — |
| DeepSeek V4 Pro | `deepseek/deepseek-v4-pro` | named provider, bf16/fp8 |
| GLM-5.3 | `z-ai/glm-5.3` | named provider, bf16/fp8 |
| MiniMax M3 | `minimax/minimax-m3` | named provider, bf16/fp8 |
| DeepSeek V4 Flash | `deepseek/deepseek-v4-flash` | named provider, bf16/fp8 |
| Qwen 3.8 27B | `qwen/qwen3.8-27b` | named provider, bf16/fp8 |

One shared `Budget(max_usd=50)` across the run; each candidate reads the kit through the driver with `InlinedCaseSource`; every raw response cached. Per candidate: quote fidelity (passed / total quotes), agreement vs human labels on the three fields (macro over fields and per field), agreement on the machine-irrelevant sample (separate), schema compliance, cost per accepted record, wall time, provider/precision actually served. Selection per §1's bar. Then, winner only: the batch-size pair (18 vs 5) and the stability check. Outputs: `data/reader/measurement-v1/manifest.json` (all scores, pins, cache keys), `reports/reader-measurement.md`, and `domain.yaml` `reader.model` set to the winner's pin.

ADR-0007 amendment: checker transport (user decision, concern recorded), quantization pair replaced by pinning, batch-size pair on the winner only, the bar's no-survivor rule.

## 7. Errors

Provider error after the retry schedule ⇒ unit failed with the last status; the outcome's resume command re-runs failed units. Parse failure after the split ⇒ `parse_failed`, raw kept. Missing case in a response ⇒ stub record, never dropped. Pre-flight or budget ⇒ clean stop with a named reason. Codex CLI missing or unauthenticated ⇒ pre-flight failure naming the tool.

## 8. Testing (offline: cassette and scripted providers)

- Rendering under `mapper-v1.md` reproduces the ten Stage 1 golden prompts byte-for-byte.
- Parser: clean array, fenced array, truncated response, split retry.
- Gate: paraphrased quote dropped and its field nulled; exact quote kept; fuzzy ≥ 92 kept with `fuzzy` status; every case accounted.
- Budget: each limit stops with its reason and a correct resume command; completed units survive.
- Cache: a recorded response is returned without a provider call; key changes when the codebook changes.
- Checker sampling: stable 10% by unit id; two-family pre-flight refuses a same-family pair.
- Codex adapter against a fake subprocess emitting the tool's JSON events; missing tool ⇒ pre-flight failure.
- OpenRouter adapter against a fake HTTP transport: pin/fallback fields sent, `usage.cost` read, retry on 429/5xx, json_schema requested when the model supports it.
- Scorer on a synthetic kit reproduces known fidelity/agreement; selection rule tested on constructed tables (all clear; none clear fidelity; survivors below 85).

## 9. Rollout

1. Build the driver and adapters; goldens green.
2. Build and freeze `kit-v1`; regenerate the external kit.
3. Run the measurement under the $50 ceiling; apply the bar; run the winner's batch-size pair and stability check; write the report and set `reader.model`.
4. Amend ADR-0007; update the handoff (item 7 done).

## 10. Out of scope (3B)

Ledger admission, review queue and page, checker-disagreement routing to review, the cycle-004 map, per-cell budget.
