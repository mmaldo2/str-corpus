# Reader-model candidates: verified catalogue, benchmark evidence, cost/quality frontier

Research run 2026-09-01 (UTC) by a background agent. Sources: OpenRouter's
live catalogue `https://openrouter.ai/api/v1/models` and per-model
`/endpoints` API, OpenRouter model pages, DeepInfra's live list, Anthropic's
models overview, benchmark pages. Raw JSON snapshots were kept in the
session scratchpad (`or_models.json`, `ep_*.json`, `di_models.json`).
Decision taken on this report: ADR-0007. Cost per case = 7,000 input +
1,100 output tokens.

## 1. Current frontier on OpenRouter (419 models in the live list)

### Closed models

| OpenRouter id | Ctx | In / Out $/M | Max out | Released | Notes |
|---|---|---|---|---|---|
| anthropic/claude-fable-5.1 | 1,000,000 | 10.00 / 50.00 | 128k | 2026-09-01 | Too expensive for a reader. |
| anthropic/claude-opus-5 | 1,000,000 | 5.00 / 25.00 | 128k | 2026-07-24 | `:batch` 2.50/12.50 (direct Anthropic only). |
| anthropic/claude-sonnet-5 | 1,000,000 | 2.00 / 10.00 | 128k | 2026-06-30 | Cache read 0.20; `:batch` 1.00/5.00. |
| anthropic/claude-sonnet-4.6 | 1,000,000 | 3.00 / 15.00 | 128k | 2026-02-17 | Dearer than Sonnet 5. |
| anthropic/claude-haiku-4.5 | 200,000 | 1.00 / 5.00 | 64k | 2025-10-15 | Newest Haiku; retirement not sooner than 2026-10-15 (https://platform.claude.com/docs/en/about-claude/models/overview). |
| openai/gpt-5.6-sol | 1,050,000 | 2.00 / 10.00 | 128k | 2026-07-09 | Flagship tier. |
| openai/gpt-5.6-terra | 1,050,000 | 2.00 / 12.00 | 128k | 2026-07-09 | "Balanced"; `:batch` 1.00/6.00. |
| openai/gpt-5.6-luna | 1,050,000 | 0.20 / 1.20 | 128k | 2026-07-09 | Cost-efficient classification tier. |
| openai/gpt-5.5 | 1,050,000 | 5.00 / 30.00 | 128k | 2026-04-24 | Previous flagship. |
| google/gemini-3.7-flash | 1,048,576 | 0.75 / 3.75 | 65,536 | 2026-08-13 | Cache read 0.075; `:batch` 0.1875/0.9375. |
| google/gemini-3.1-pro-preview | 1,048,576 | 2.00 / 12.00 | 65,536 | 2026-02-19 | Newest Gemini Pro listed. |
| qwen/qwen3.8-max | 1,000,000 | 2.00 / 6.00 | 131k | 2026-08-03 | Alibaba-only endpoint. |
| mistralai/mistral-medium-3-5 | 262,144 | 1.50 / 7.50 | 210k | 2026-04-30 | Dense 128B. |

### Open-weight models

| OpenRouter id | Ctx | Std $/M in/out (cheapest) | Released | Params / providers / quantization |
|---|---|---|---|---|
| deepseek/deepseek-v4-pro-0813 | 1,048,576 | 0.66 / 1.98 (Alibaba 0.58/1.74) | 2026-08-12 | 1.6T / 49B active; DeepSeek first-party (quant unknown), DeepInfra fp8 1.30/2.60, Baseten fp4. |
| deepseek/deepseek-v4-flash-0731 | 1,310,720 | 0.065 / 0.18 (Baidu fp8 0.05/0.10) | 2026-07-31 | 284B / 13B active; 31 endpoints: 14 fp8, 6 fp4, 1 bf16 (Morph 0.10/0.28). |
| qwen/qwen3.8-2.4t-a95b | 1,048,576 | 2.00 / 6.00 | 2026-08-12 | Open Qwen3.8 Max; DeepInfra fp4 at 262k only; SiliconFlow fp8 1M. |
| qwen/qwen3.8-27b | 1,000,000 | 0.425 / 2.55 (Chutes fp8 0.32/2.50) | 2026-08-14 | Dense 27B; DeepInfra unquantized 0.40/3.00 at 262k. |
| moonshotai/kimi-k3 | 1,048,576 | 3.00 / 15.00 (Makora 2.55/12.75) | 2026-07-16 | 2.8T; first-party mxfp4 by design (QAT); DeepInfra bf16 2.85/14.25. |
| moonshotai/kimi-k2.7-code | 262,144 | 0.66 / 3.40 | 2026-06-12 | Coding-tuned; not a fit. |
| z-ai/glm-5.3 | 1,310,720 | 1.40 / 4.40 (AkashML fp8 1.17/3.96) | 2026-08-18 | Reasoning cannot be disabled; 8 fp8, 5 fp4 endpoints. |
| z-ai/glm-5.3-flash | 1,310,720 | 0.075 / 0.25 | 2026-08-26 | JSON mode without schema enforcement. |
| minimax/minimax-m3 | 1,048,576 | 0.30 / 1.20 (CoreWeave fp4 0.23/0.96) | 2026-05-31 | 8 fp8 endpoints; DeepInfra fp8 0.28/1.10 at 524k. |
| xiaomi/mimo-v2.5-pro | 1,050,000 | 0.435 / 0.87 | 2026-04-22 | Schema support unclear (page and API disagree). |
| tencent/hy4-preview | 1,048,576 | 0.834 / 2.50 | 2026-08-28 | Preview only. |
| nvidia/nemotron-3-super-120b-a12b | 1,000,000 | 0.085 / 0.40 | 2026-03-11 | Two endpoints only. |
| google/gemma-4-31b-it | 262,144 | 0.09 / 0.34 | 2026-04-02 | fp4/fp8/bf16 mix. |
| openai/gpt-oss-120b | 131,072 | 0.037 / 0.17 | 2025-08-05 | Native MXFP4; context caps batch at ~12 cases. |
| meta-llama/llama-4-maverick | 1,048,576 | 0.20 / 0.696 | 2025-04-05 | Newest Meta model listed. |

Stale names flagged during the session: moonshotai/kimi-k2.6 (2026-04-20)
and z-ai/glm-5.1 (2026-04-07) still exist but are superseded by Kimi
K3 / K2.7 and GLM-5.3.

## 2. Benchmark evidence

### 2a. OCR-noise robustness (see companion report for the full sub-study)

"Error Patterns in Historical OCR" (https://arxiv.org/abs/2602.14524): a
Qwen VLM lowered CER on 18th-century English but "exhibits selective
linguistic regularization and orthographic normalization that may silently
alter historically meaningful forms", exactly the failure that breaks a
>= 92 fuzzy verbatim check. MultiOCR-QA (https://arxiv.org/abs/2502.16781):
QA systems highly prone to OCR-induced errors. HIPE-OCRepair (arXiv
2607.08143): recurring over-correction on low-noise inputs.

### 2b. Long-context quality (see companion report)

AA-LCR (https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning):
Kimi K3 (max) 82.7%. AA model pages: Claude Sonnet 5 Intelligence Index 55,
"very verbose"; DeepSeek V4 Pro 0813 index 53, 54.1 tok/s. At 40k-120k
tokens per request the pipeline is inside every shortlisted window; the risk
is quality decay, which the kit measures.

### 2c. Verbatim quotation / citation faithfulness

No public benchmark measures exact-span copying across current families.
LongCite/LongBench-Cite (https://arxiv.org/html/2409.02897) citation F1:
Claude-3-sonnet 67.2, GPT-4o 65.6, GLM-4 65.4, Mistral-Large 51.5,
Llama-3.1-70B 40.4. L-CiteEval (https://arxiv.org/html/2410.02115):
Claude-3.5-Sonnet 37.43/58.58, GPT-4o 33.48/56.10, Qwen2-57B 3.82/13.61.
2024-era open models were weak at citing; no current numbers. SEC 8-K
grounded extraction (https://arxiv.org/abs/2607.08346) anchors tags to
verbatim quotes with fuzzy n-gram validation, precision 12% to 96%;
FullCite (https://arxiv.org/abs/2606.07130): LLMs struggle to identify
precise supporting spans. Anthropic Citations API returns cited_text by
char offset, verbatim by construction, a structural advantage if the native
API is used. Vectara hallucination leaderboard (2026-05-11): gpt-5.4-nano
3.1%, gemini-2.5-flash-lite 3.3%, Llama-3.3-70B 4.1%, DeepSeek-V3.2-Exp
5.3%; no current Claude/DeepSeek-V4/Qwen3.8/GLM-5.3 rows.

### 2d. Legal reasoning

Vals AI LegalBench (https://www.vals.ai/benchmarks/legal_bench, 2026-09-01):
Claude Fable 5 88.56; Fable 5.1 88.51; Gemini 3.1 Pro 87.40; Gemini 3.7
Flash 87.26; Claude Opus 5 86.97; GPT-5.6 Sol 86.97; GPT-5.5 86.52; Kimi K3
86.02; MiniMax-M3 85.42; GLM 5.3 84.84; Claude Sonnet 5 83.92; Qwen 3.8 Max
83.61; Qwen 3.8 27B 82.43; DeepSeek V4 Pro 82.36; Claude Haiku 4.5 81.24;
DeepSeek V4 Flash 77.71; Llama 4 Maverick 77.81. Saturated at the top.

Vals Legal Research Bench (https://www.vals.ai/benchmarks/legal_research,
2026-08-30): Claude Opus 5 55.29; Fable 5.1 55.29; GLM 5.3 49.04; GPT-5.6
Sol 48.08; Qwen 3.8 Max 47.60; GLM 5.3 Flash 45.19; Kimi K3 44.23; Claude
Sonnet 5 41.83; DeepSeek V4 Pro 40.87; GPT-5.5 40.38; Gemini 3.7 Flash
34.62; DeepSeek V4 Flash 30.29; Gemini 3.1 Pro 20.67.

### 2e. Structured JSON reliability

Structured Output Benchmark (https://arxiv.org/html/2604.25359; JSON pass /
value accuracy): GPT-5.4 .999/.825; Claude Sonnet 4.6 .984/.809; Gemini 2.5
Flash .983/.822; Qwen3-235B .982/.811; GLM-4.7 .972/.830; GPT-OSS-20B
.858/.693. "Every model produces nearly perfect JSON, yet a sizeable
fraction of leaf values are wrong." BFCL V4 (2026-04-12, ends at GPT-5.2):
Claude Opus 4.5 77.47; Sonnet 4.5 73.24; Gemini 3 Pro 72.51; Haiku 4.5
68.70; Kimi K2 59.06; DeepSeek V3.2-Exp 56.73; Qwen3-235B 52.15. "Capacity,
Not Format" (https://arxiv.org/abs/2606.09410): JSON-constrained reasoning
costs Claude Sonnet ~0 pp, Claude Haiku -36 pp, GPT-4o-mini -28 pp;
reason-then-format recovers most of it. OpenRouter structured outputs are
per-endpoint; supported on Anthropic, OpenAI, Google, DeepSeek, GLM-5.3,
Kimi K3, Qwen3.8-2.4T endpoints; GLM-5.3-Flash and MiMo lack enforcement.

## 3. Cost / quality frontier

| Model | $/case std (cheapest) | `:batch` $/case | LegalBench | Legal Research | Long-context | JSON | Quote |
|---|---|---|---|---|---|---|---|
| Claude Opus 5 | 0.0625 | 0.0313 | 86.97 | 55.29 | - | BFCL 4.5: 77.5 | Citations API |
| GPT-5.5 | 0.0680 | 0.0340 | 86.52 | 40.38 | - | GPT-5.4 .999 | - |
| Kimi K3 | 0.0375 (0.0319) | - | 86.02 | 44.23 | 82.7 | - | - |
| Claude Sonnet 4.6 | 0.0375 | 0.0188 | 82.12 | - | - | .984/.809 | - |
| GPT-5.6 Terra | 0.0272 | 0.0136 | - | - | - | family | - |
| Gemini 3.1 Pro | 0.0272 | 0.0136 | 87.40 | 20.67 | - | family | - |
| Claude Sonnet 5 | 0.0250 | 0.0125 | 83.92 | 41.83 | - | family | Citations API |
| Qwen3.8 2.4T / Max | 0.0206 | - | 83.61 | 47.60 | - | - | - |
| GLM-5.3 | 0.0146 (0.0125) | - | 84.84 | 49.04 | - | GLM-4.7 .972 | - |
| Claude Haiku 4.5 | 0.0125 | 0.0063 | 81.24 | - | - | BFCL 68.7; JSON -36 pp | - |
| Gemini 3.7 Flash | 0.0094 | 0.0023 | 87.26 | 34.62 | - | family | - |
| DeepSeek V4 Pro 0813 | 0.0068 (0.0060) | - | 82.36 | 40.87 | - | DS-V3.2 BFCL 56.7 | - |
| Qwen3.8 27B | 0.0058 (0.0050) | - | 82.43 | - | - | Qwen3.5-35B .974 | - |
| MiMo-V2.5-Pro | 0.0040 | - | - | - | - | unclear | - |
| MiniMax M3 | 0.0034 | 0.0034 | 85.42 | - | - | - | - |
| GLM-5.3 Flash | 0.0008 | 0.0016 | - | 45.19 | - | no enforcement | - |
| DeepSeek V4 Flash 0731 | 0.0007 | 0.0013 | 77.71 | 30.29 | - | - | - |
| gpt-oss-120b | 0.0004 | 0.0017 | - | - | - | .858 (20B) | - |
| GPT-5.6 Luna | 0.0027 | 0.0014 | - | - | - | family | - |

Pareto (cost vs LegalBench): DeepSeek V4 Flash -> MiniMax M3 -> Gemini 3.7
Flash -> Gemini 3.1 Pro. Pareto (cost vs Legal Research): GLM-5.3 Flash ->
GLM-5.3 -> Opus 5. Caveats: GLM-5.3 cannot disable reasoning, so real cost
exceeds the 1.1k output assumption; set Claude effort low for a fair
comparison; none of these columns measures verbatim copying or OCR noise.

## 4. Approved shortlist for the experiment kit (approved 2026-09-01)

| # | Model | Role | Provider to pin | Batch note |
|---|---|---|---|---|
| 1 | anthropic/claude-sonnet-5 | incumbent class | anthropic | 18; effort low |
| 2 | anthropic/claude-opus-5 | quality ceiling | anthropic | 18 |
| 3 | anthropic/claude-haiku-4.5 | cheap Claude floor | anthropic | 18 (126k of 200k) |
| 4 | google/gemini-3.7-flash | best LegalBench per dollar | google-vertex/global | 18 |
| 5 | openai/gpt-5.6-terra | OpenAI representative | openai | 18 |
| 6 | deepseek/deepseek-v4-pro-0813 | top open-weight value | deepseek or deepinfra fp8 | 18 |
| 7 | z-ai/glm-5.3 | strongest open on Legal Research | akashml/fp8 or gmicloud/fp8 | 6 and 18 |
| 8 | minimax/minimax-m3 | mid-price open | deepinfra/fp8 | 18 |
| 9 | deepseek/deepseek-v4-flash-0731 | cost floor | deepinfra/fp8; morph/bf16 as control | 6 and 18 |
| 10 | qwen/qwen3.8-27b | dense-model control | deepinfra unquantized | 18 |

Alternates: moonshotai/kimi-k3, z-ai/glm-5.3-flash, openai/gpt-oss-120b
(max ~12 cases per batch). One model runs on both fp8 and fp4 endpoints to
measure quantization drift in quote fidelity. Pre-registered bar: quote
fidelity >= 97%, agreement with human adjudication >= 85% on relevance,
polarity, who-was-letting; then cheapest cost per accepted record.

## 5. Practical notes

Provider pinning: `/api/v1/models/{id}/endpoints` returns per-provider tag,
quantization, context, max output, prices, uptime; record it with each run.
Pin with the request-body `provider` object (see companion report for the
verified field names). Quantization tags observed: fp8, fp4, int4, bf16,
fp16, mxfp4, unknown; same model at different precision often costs the
same. Prompt caching prices are exposed per model but only the ~1-2k system
prompt repeats; the 40-120k case text is unique per request. OpenRouter's
beta batch endpoint claims 50% but cannot carry a provider pin; Anthropic
direct batch is 50% off.

## Could not verify

Current-model rows on BFCL and Vectara; MiMo-V2.5-Pro schema support;
GPT-5.6 Terra/Luna and GLM-5.3-Flash on Vals LegalBench; whether OpenRouter
`:batch` slugs and the beta batch endpoint are the same mechanism; any
benchmark of exact-span quotation across current families; any benchmark on
19th-century legal English.
