# OCR-noise robustness, long-context quality, and provider mechanics

Two sub-studies run 2026-09-01 by background agents. Decisions taken on
these: ADR-0007, ADR-0009.

## Part A. LLMs reading OCR-noisy text

### OHRBench (arXiv 2412.02592, ICCV 2025; https://github.com/opendatalab/OHR-Bench)

8,561 document images / 8,498 QA pairs across 7 domains including Law.
Semantic Noise (real OCR errors from image distortions at mild/moderate/
severe) and Formatting Noise. LLMs: Qwen2-7B, Qwen2-72B, Llama-3.1-8B.
Headline (Llama-3.1-8B + BGE-M3): ground truth overall F1 36.1 / retrieval
70.0; best OCR (Qwen2.5-VL-72B) 31.1 / 59.2; worst (Nougat) 14.5 / 41.2.
"Semantic Noise results in nearly a 50% performance decline for most
retrievers and LLMs"; larger LLMs are more robust (Qwen2-72B +9.4% correct
over Qwen2-7B under OCR errors).

### Follow-ups with per-model numbers

- InduOCRBench (arXiv 2605.00911, ACL 2026 Industry): HistoryBooks column:
  Qwen3-VL-235B 87.1, Hunyuan-OCR 84.7, Gemini-2.5 Pro 78.9, MinerU2 0.1,
  GPT-4o 0.0. "82.9% OCR accuracy yet only 52.8% RAG accuracy": character
  accuracy can mask semantic loss.
- MultiOCR-QA (arXiv 2502.16781, CIKM 2025): historical documents, raw vs
  corrected OCR. English Llama-3.3-70B Contains 63.90 -> 50.39 (-21.3%).
  Larger models more resilient but still hit hard.
- Character-level perturbation (arXiv 2510.14365): under 30% typos
  DeepSeek-Reasoner 74.8, Llama-3.1-70B 62.5, Qwen3-235B 50.3; ranking
  DeepSeek > Qwen > Llama; larger > smaller.
- Enterprise perturbation consistency (arXiv 2601.06341): GPT 5.2 91.01,
  GPT 4.1 90.20, Ministral 3 8B 89.40, Llama 3.1 8B 69.52.

### Historical OCR and LLMs

- "OCR Error Post-Correction with LLMs in Historical Documents: No Free
  Lunches" (arXiv 2502.01205): 18th-c. English CER improvement GPT-4o
  +58.1%, Llama-3.1-70B +38.7%, Gemma-2-27B +35.6%; every open model
  worsened Finnish Fraktur.
- "Evaluating LLMs for Historical Document OCR" (arXiv 2510.06743): 18th-c.
  Russian Civil font full-page CER: Gemini-2.5-Pro 3.36, Gemini-2.5-Flash
  4.94, Qwen-2.5-VL 5.81, Claude-3.5 6.79, GPT-4.1 7.90, GPT-4o 9.23. All
  models err more on archaic characters.
- Multimodal post-correction (arXiv 2504.00414): German directories
  1754-1870, Transkribus CER 3.67% -> Gemini 2.0 Flash 0.84%, GPT-4o 1.00%
  with image plus text.
- HIPE-OCRepair (arXiv 2607.08143): over-correction on low-noise inputs is
  a recurring failure.
- Chronicling America English: CLOCR-C (arXiv 2408.17428); BLN600
  19th-c. British newspapers Llama-2 fine-tune cut CER 54.51%.

Implication for this project: the reader never performs OCR; it reads OCR
text. Vision matters only for the pin-cite check against page images
(ADR-0009), and the transcription-fidelity evidence above (Gemini Pro line,
Qwen VL leading; all models normalizing archaic forms) is what a
twenty-page fidelity test should confirm before choosing that model.

## Part B. Long-context quality at 32k-128k

- RULER (https://github.com/NVIDIA/RULER, leaderboard to 2025-07-21), 32k /
  64k / 128k: Qwen3-235B-A22B 95.1/93.3/90.6; Qwen3-32B 94.4/91.8/85.6;
  Qwen3-30B-A3B 92.4/89.1/79.2; Llama3.1-70B 94.8/88.4/66.6; Mistral-Large-
  2411 94.0/85.9/48.1. No frontier 2026 models.
- NoLiMa (https://github.com/adobe-research/NoLiMa): GPT-4.1 79.8/69.7/64.7;
  GPT-4o 69.7/62.4/56.0; Claude 3.5 Sonnet effective length 4K.
- LongBench v2 (https://longbench2.github.io/): Gemini-2.5-Pro 63.3,
  Qwen3-235B Thinking 60.6, human 53.7; aggregator (unsourced): Qwen3.8 Max
  66.3, Claude Opus 4.5 64.4, Kimi K2.5 61.0, GLM-5 60.8, DeepSeek V4 Pro
  Base 51.5.
- HELMET (https://github.com/princeton-nlp/HELMET): GPT-4o-08 flat
  65.5 -> 64.8 to 128k; Qwen2.5-72B 63.4 -> 38.2; Llama-3.1-70B 61.5 -> 49.7.
- AA-LCR (~100k-token inputs): Kimi K3 82.7; Mercor mirror: GPT-5.5 82.8,
  GPT-5.4 82.5, GPT-5.6 Terra 81.8, Fable 5 81.5; llm-stats mirror:
  Kimi K2.5 0.700, Qwen3.5-397B 0.687, Qwen3.6 Plus 0.683, MiniMax M2.1 0.620.
- MRCR v2 8-needle (via https://yage.ai/share/long-context-benchmark-en-20260315.html):
  Claude Opus 4.6 93.0% @256K; Claude Sonnet 4.6 90.3% @256K; GPT-5.2 77.0%
  @128-256K; Gemini 3 Pro 24.5% @1M.

Summary: demonstrably hold at ~100k+: Claude 4.6 and later, GPT-5.x, Kimi
K3 and K2.5, Qwen 3.5/3.6, Qwen3-235B. Degrade between 32k and 128k: Llama
3.1 70B, Mistral Large, Qwen2.5-72B, Qwen3 14B/32B/30B-A3B, GPT-4o/4.1 on
NoLiMa, Gemini 2.0 Flash, Claude 3.5 Sonnet. Hence the 6-versus-18 batch
runs for the open candidates in the kit.

## Part C. OpenRouter, DeepInfra, and Anthropic mechanics

### Provider routing (https://openrouter.ai/docs/guides/routing/provider-selection)

Request-body `provider` object fields: `order`, `allow_fallbacks` (default
true), `require_parameters`, `data_collection`, `only`, `ignore`,
`quantizations`, `sort`, `zdr`, `max_price`. Pin one endpoint with no
fallback:

```json
{ "provider": { "order": ["deepinfra/fp8"], "allow_fallbacks": false } }
```

Valid `quantizations`: int4, int8, fp4, mxfp4, nvfp4, fp6, fp8, mxfp8,
fp16, bf16, fp32, unknown. Which provider served a request: response
`openrouter_metadata.endpoints[].{provider, selected}`; after the fact
`GET /api/v1/generation?id=<id>` returns provider_name, model, native token
counts, total_cost, latency, finish_reason (no quantization field).
Endpoints API `GET /api/v1/models/{author}/{slug}/endpoints` returns per-
endpoint tag, quantization, context, max output, uptime.

### Quantization quality evidence

Moonshot K2-Vendor-Verifier (https://github.com/MoonshotAI/K2-Vendor-Verifier):
schema accuracy varies by host from 100% (official, Fireworks, DeepInfra) to
73-84% (some vLLM/SGLang/Nebius/Chutes deployments), attributed to missing
guided decoding and configuration more than quantization. Kurtic et al.,
"Give Me BF16 or Give Me Death?" (ACL 2025, https://arxiv.org/abs/2411.02355):
FP8 W8A8 effectively lossless, INT8 1-3% degradation, INT4 W4A16 rivals
8-bit; long-context extraction not isolated.

### Prompt caching and batch

OpenRouter passes Anthropic cache_control breakpoints through; multipliers
Anthropic write 1.25x/2x, read 0.1x; DeepSeek read 0.1x; Moonshot write
free, read 0.25x. OpenRouter beta batch API: 24h window, "typically billed
at 50%", request bodies cannot carry a `provider` object, so batch runs
cannot pin a provider. Anthropic Message Batches: 50% off, 100k requests or
256 MB, 24h, caching stacks. OpenAI batch 50%. Gemini batch 50%. DeepInfra:
no batch discount. DeepSeek direct: off-peak 50% (01:00-04:00 and
06:00-10:00 UTC weekdays); V4-Flash $0.44/$1.32 peak.

### Rate limits and fees

OpenRouter paid models: no documented request cap beyond upstream limits;
`GET /api/v1/key` shows limit and usage. DeepInfra: 200 concurrent requests
per model. OpenRouter fees: 5.5% on Stripe credit purchase, no inference
markup.

### Anthropic direct pricing (https://platform.claude.com/docs/en/about-claude/pricing)

| Model | In | Out | Batch in/out |
|---|---|---|---|
| Fable 5.1 | $10 | $50 | $5 / $25 |
| Opus 5 | $5 | $25 | $2.50 / $12.50 |
| Sonnet 5 | $2 | $10 | $1 / $5 |
| Haiku 4.5 | $1 | $5 | $0.50 / $2.50 |

Claude 4.7+ tokenizer produces ~30% more tokens than earlier models; the
7k/1.1k per-case figures were measured under the earlier tokenizer.

### Subscription terms

https://code.claude.com/docs/en/legal-and-compliance: OAuth (Pro/Max)
credentials "support ordinary use of Claude Code and other native Anthropic
applications"; developers building automated products "should use API key
authentication"; routing requests through Free/Pro/Max credentials on behalf
of users is not permitted. Consumer Terms prohibit automated access except
via an API key. There is no Batches API on subscriptions. This is the
compliance basis for ADR-0007.

## Could not verify

OHRBench per-LLM numbers per noise level; current Fiction.LiveBench
32k/60k/120k scores; contextarena.ai direct; full AA-LCR table; HELMET and
LongBench v2 official numbers for 2026 models; R2ATA per-model results;
whether OpenRouter still returns a top-level `provider` string; cache
multipliers for open-weight hosts on OpenRouter; batch eligibility by
model; Anthropic batch rate limits.
