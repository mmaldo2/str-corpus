---
status: accepted
date: 2026-09-01
supersedes: spec amendment A6 (mapper tier and execution); the Codex checker role and the never-degrade rule survive
---

# Readers run through API-key access behind one provider-neutral module; the model is chosen by a pre-registered measurement; Codex stays the checker

Readers ran as headless subscription-CLI invocations. That exhausted the
subscription's usage window (the user bought extra credits), made cost per
record unmeasurable, wrapped every call in the CLI's own system prompt, and
sits outside Anthropic's licence terms, which reserve subscription
credentials for interactive use and direct automated use to API keys. We
decided: one LLM-call module with an OpenAI-compatible transport (through
OpenRouter, which covers Claude and current open-weight models) and an
optional native Anthropic backend used only if a Claude model wins and the
batch discount matters; model, provider endpoint, quantization, and effort
recorded in every run's metadata; the reader model selected by running the
experiment kit over an approved candidate list against human-adjudicated
references under a pre-registered bar (quote fidelity at or above 97
percent, agreement at or above 85 percent on relevance, polarity, and
who-was-letting; then cheapest cost per accepted record); and OpenAI Codex
retained as the cross-family checker regardless of which family the reader
comes from.

## Considered options

- Commit to Claude: defensible on quality, but at a fiftieth of the price
  several open models score within a few points on legal benchmarks, and the
  quote gate catches a weaker model's failures deterministically.
- Commit to open models now: unmeasured; verbatim-copying fidelity on OCR
  text is unbenchmarked for every current family.
- Replace Codex with Claude as checker when the reader is open: rejected;
  two families is the requirement and Codex carries three cycles of
  disagreement history.

## Consequences

Per-cycle reader cost falls from a subscription window to roughly $2 to $70
depending on the winner, which makes the recall certification pass
(ADR-0009) affordable. Open models are pinned to a named fp8 or bf16
endpoint with fallbacks disabled; OpenRouter's own batch mode cannot pin a
provider, so reproducible open-model runs use standard requests. Candidate
list approved 2026-09-01: Claude Sonnet 5, Claude Opus 5, Claude Haiku 4.5,
Gemini 3.7 Flash, GPT-5.6 Terra, DeepSeek V4 Pro, GLM-5.3, MiniMax M3,
DeepSeek V4 Flash, Qwen 3.8 27B; one fp8-versus-fp4 pair and two batch-size
pairs are run to measure quantization and long-context drift.

## Amendment 2026-09-05

The measurement ran. Ten approved candidates over the frozen kit
(`data/reader/kit-v1/kit.json`, 195 cases: 155 human-adjudicated, 40
machine-judged irrelevant) under codebook `mapper-v2`; full result in
`reports/reader-measurement.md`, manifest in
`data/reader/measurement-v1/manifest.json`. $41.78 charged against the $50 the
user approved.

**Measured winner: `anthropic/claude-opus-5`** (closed-weight, so no provider or
precision pin; OpenRouter served it from "Claude Platform on AWS"), quote
fidelity 0.9975, macro agreement 0.7075, $0.0498 per accepted record. Written to
`domains/str-right-to-let/domain.yaml` as `reader.model`.

**The agreement bar was not met by anyone.** The pre-registered rule is
fidelity floor 0.97, then agreement at or above 0.85 on relevance, polarity and
who-was-letting, then cheapest cost per accepted record. Three candidates fell at
the fidelity floor (`claude-haiku-4.5` 0.9274, `deepseek-v4-pro` 0.9228,
`deepseek-v4-flash` 0.8988); of the seven survivors the best macro agreement was
0.7075. The cost tie-break therefore never opened, and the rule's disclosed
fallback applied: the highest-agreement survivor is chosen and **the shortfall is
recorded rather than the bar lowered**. Had the bar been met, `deepseek-v4-flash`
at $0.0006 per accepted record would have won on cost — 83x cheaper than the
model actually selected.

**What "accepted record" counts** (spec §2, amended 2026-09-05 by the final review's
I7): a record that parsed and came back through the quote gate with a decided
`relevant` field — `extraction_status` `ok` **or** `partial`. `partial` is the status
of a record that lost one or more judged fields to the gate, so an accepted record is
not necessarily a fully judged one and cost per accepted record is a lower bound on
the cost of one. The spec's original wording ("kept its judged fields") never matched
the implementation or `CONTEXT.md`; the definition was restated rather than the
measured number changed, and nothing above turns on it because the cost tie-break
never opened.

**`mapper-v2` failed its stability check** (ADR-0009): two reads of the frozen
fifty-case sample by the winner agree 0.96 on `relevant` and 0.94 on
`who_was_letting` but only **0.82 on `polarity`**, against a 0.90 bar. Recorded
as `"stable": false`. Polarity is also the field on which the candidate field
separated, and the two facts are most likely one: `mapper-v2` under-specifies
polarity rather than merely making it hard. Revising the codebook is Stage 3B's
work. Until then the model choice above holds only *relative to `mapper-v2`* — a
`mapper-v3` needs its own stability run and its own measurement, because a
codebook that changes what is being judged can change which model judges it best.

Further decisions this measurement records:

- **The fp8-versus-fp4 quantization pair was dropped; pinning covers a different
  risk.** Every open-weight candidate is pinned to a named provider serving bf16 or
  fp8 with fallbacks disabled, so no candidate ran at an unrecorded precision. That
  is not the question the pair was pre-registered to answer — whether aggressive
  quantization degrades reading quality — and **the fp4 comparison is deferred
  rather than answered.** The pin holds precision but not provider: OpenRouter's
  endpoint list is order-dependent and `deepseek-v4-pro` resolved to Baidu on one
  run and StreamLake on the next (both fp8), re-buying its whole kit for $1.51
  because the response cache keys on the pin label. The served provider is therefore
  a measured output, not an input, and should be frozen per candidate before any
  result is called reproducible.
- **Two batch-size pairs became one, on the winner only.** At $9-10 a pass, a
  second pair costs more than the finding is worth. Result: no long-context
  penalty at 18 cases. Five-case batches gain 0.0012 quote fidelity and save
  $0.65 over the kit but *lose* 0.0193 macro agreement. 18-case batches stand.
- **Reasoning effort is pinned to `low` for every candidate** and carried on
  `ModelPin.extra`. Left at each provider's default it is not a recorded quantity
  but a per-family accident: the first attempt saw a five-fold per-case output
  difference between families and truncated at `max_tokens` 16000 (since raised to
  64000, which must also cover billed reasoning tokens). ADR-0007 requires effort
  to be recorded; this is how.
- **The quote gate's per-field rule was relaxed mid-measurement.** Before
  `dfd6c06` each judged field needed its own verified quote; now one verified quote
  may name several fields and all of them stand. The trigger was a crash — a
  list-valued `supports` raised `TypeError`, which is not `ReaderError`, so it
  escaped the driver's per-unit handler and killed a whole candidate — but the fix
  chosen was the looser of two that would have worked. It is the right rule: a
  single passage routinely establishes both the characterization and the polarity,
  and making the model quote the same sentence twice measures compliance with a
  formatting convention rather than fidelity to the text. It cannot admit an
  unverified quote (`verify_quote` still gates entry) and cannot inflate quote
  fidelity (each quote is counted once however many fields it names). Every
  candidate was re-gated under the new rule in the final scoring pass, so all ten
  were scored on identical terms, and the one candidate observed to emit
  list-valued `supports` fell at the fidelity floor either way.
- **Codex remains the checker, invoked through the Codex CLI**, at the user's
  direction. Recorded concern: this is the access route ADR-0007 moved readers
  away from, and whether OpenAI's subscription terms carry an analogue of the
  interactive-use restriction that drove that decision has not been checked. The
  reader is on API-key access; the checker is not.
