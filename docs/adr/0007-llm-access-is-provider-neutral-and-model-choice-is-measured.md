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
