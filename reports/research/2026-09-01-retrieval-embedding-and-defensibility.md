# Retrieval, embedding, and methodology options for the right-to-let corpus

Research run 2026-09-01 by a background agent (web research only). Numbers
marked *(derived)* are arithmetic anchored to published figures;
*(unverified)* rests on a secondary source or an unreadable table. Decisions
taken on this report: ADR-0005, ADR-0006, ADR-0009.

## 1. Embedding models

Qwen3-Embedding family (model cards https://huggingface.co/Qwen/Qwen3-Embedding-0.6B,
https://huggingface.co/Qwen/Qwen3-Embedding-8B; paper arXiv 2506.05176;
Apache-2.0, 32K context, matryoshka):

| | 0.6B | 4B | 8B |
|---|---|---|---|
| Native dim | 1024 | 2560 | 4096 |
| MTEB(Eng v2) Retrieval | 61.83 | 68.46 | 69.44 |
| MLEB legal avg nDCG@10 | 77.13 | 81.96 | 82.96 |
| bf16 weights | ~1.2 GB | ~8 GB | ~16.4 GB |

0.6B to 4B is worth +6.6 English retrieval points and +4.8 legal points;
4B to 8B adds about +1. MLEB (Isaacus, arXiv 2510.19365,
https://huggingface.co/blog/isaacus/introducing-mleb) is the only
independent legal retrieval benchmark with these models; all its corpora are
modern, none OCR'd 19th-century text. On MLEB voyage-3-large scores 85.71 and
voyage-law-2 only 79.63 (below Qwen3-4B). The model card says omitting the
query-side `Instruct:` prefix costs 1-5%: confirm selectors use it.

Other open models: nothing commercially licensed that fits 16 GB beats
Qwen3-4B on retrieval. BGE-M3 (MIT) is 8-13 MLEB points behind but has
sparse and ColBERT heads. NV-Embed-v2, Linq-Embed, jina-v3 are
non-commercial. KaLM-Embedding-Gemma3-12B needs ~24 GB.

Paid APIs at ~450 tokens/chunk, 10M chunks = 4.5B tokens: voyage-4-lite $90,
voyage-law-2 / voyage-4-large $540, voyage-3-large $810, OpenAI 3-large $585,
Gemini embedding-001 $675 (batch ~$340). Hosted open Qwen3-Embedding via
DeepInfra/OpenRouter: $0.01 per M tokens, so ~$45 at 10M chunks (verified
separately 2026-09-01: https://deepinfra.com/Qwen/Qwen3-Embedding-4B/api,
https://openrouter.ai/qwen/qwen3-embedding-8b).

512d + int8 cost: MRL paper (arXiv 2205.13147) near-flat to 1/8 native dims;
Arctic-Embed 2.0 retains 98% at 256/1024; voyage-3-large 1024-int8 is 0.31%
below 2048-float; OpenAI 3-large at 256/3072 loses 4%; a May 2026 patent
benchmark (arXiv 2605.24297) reports 96-97% retention for Qwen3 at 512d
*(unverified)*. int8 scalar quantization retains ~97% without rescoring and
~99% with 4x oversample rescoring (https://huggingface.co/blog/embedding-quantization).
Net: 3-5% combined loss, half trivially recoverable. 10M x 1024d int8 = 10.2 GB
fits in 32 GB RAM; store full-dim int8, rescore top-4k with a float query.

Throughput *(derived)*: 90 chunks/s x 450 tokens = ~40k tok/s, ~36% of the
RTX 5080's practical bf16 peak. Tuned ceiling ~150 chunks/s.

| Model | est. chunks/s | 4M chunks | 10M chunks |
|---|---|---|---|
| 0.6B | ~90 to ~150 | 12.5 h / 7.5 h | 31 h / 19 h |
| 4B | ~12 to ~20 | 3.9 d / 2.3 d | 9.6 d / 5.8 d |
| 8B (FP8) | ~6 | 8 d | 20 d |

OCR and archaic English: OHRBench (arXiv 2412.02592): BGE-M3 retrieval falls
70.0 to 45-59 under real OCR; semantic noise causes ~50% degradation and
"dense retrieval's stronger comprehension does not provide robustness."
Bazzo et al. (ECIR 2020): degradation begins at 5% WER; stemming helps.
Impresso "Cheap Character Noise for OCR-Robust Multilingual Embeddings"
(ACL Findings 2025; https://aclanthology.org/2026.lrec-1.71/): contrastive
fine-tuning with synthetic character noise gives "considerable improvements"
with negligible clean-text loss. No evaluation of any modern embedder on
19th-century legal English exists; HistWords suggests frequent terms drift
slowly, so the real problem is period coinages, i.e. vocabulary coverage.

## 2. Cross-encoder rerankers

| Model | Params | Key scores | est. pairs/s on 5080 *(derived)* | 200k pairs |
|---|---|---|---|---|
| Qwen3-Reranker-0.6B | 0.6B | MTEB-R 65.80; FollowIR 5.41 | ~120 | ~28 min |
| bge-reranker-v2-m3 | 568M | MTEB-R 57.03; FollowIR -0.01 | ~120 | ~28 min |
| mxbai-rerank-large-v2 | 1.5B | BEIR 57.5-61.4 | ~50 | ~1.1 h |
| Qwen3-Reranker-4B | 4B | MTEB-R 69.76; FollowIR 14.84 | ~18 | ~3 h |
| Qwen3-Reranker-8B | 8B | MTEB-R 69.02; FollowIR 8.05 | ~5-10 | 6-11 h |
| Ettin-150M / answerai-colbert-small | 150M / 33M | MTEB-R 0.599 / BEIR 53.8 | ~400 / >600 | 8 / 3 min |

Sources: arXiv 2506.05176 Table 4; https://huggingface.co/blog/ettin-reranker;
https://huggingface.co/jinaai/jina-reranker-v3.5. 5080 figures FLOP-scaled
from H100, +/-50%.

Gains: RankGPT (arXiv 2304.09542) BEIR BM25 43.4 to 47.2 (monoBERT) to 51.4
(monoT5-3B); Anthropic contextual retrieval post (Sept 2024): top-20 failure
5.7% to 2.9% (hybrid) to 1.9% (plus reranker). Reranker choice matters as
much as adding one (bge-m3 57.0 vs Qwen3-4B 69.8 over identical
candidates). Rubric-style instructions: Qwen3-Reranker's template supports
an `<Instruct>` string; FollowIR shows the 4B follows instructions far
better than 0.6B or bge-m3; BTZSC (arXiv 2603.11991) found rerankers given
label descriptions are the best zero-shot classifiers. Recommendation:
Qwen3-Reranker-4B with the rubric as instruct, via vLLM sequence-classification
(https://docs.vllm.ai/en/v0.9.2/examples/offline_inference/qwen3_reranker.html).

## 3. Hybrid fusion and vector index

RRF (Cormack, Clarke, Buettcher SIGIR 2009) is the no-tuning option. Bruch,
Gai, Ingber (arXiv 2210.11934): convex combination of min-max normalized
scores beats RRF in- and out-of-domain (MS MARCO nDCG@1000 0.454 vs 0.425);
alpha 0.6-0.8 toward semantic is robust. This corpus is the case where CC
wins: cosine is calibrated (already thresholded at 0.43-0.45), BM25 is
unbounded. ~700 positives suffice to grid-search alpha.

Index: at 10M x 512d with a few hundred offline queries per cycle, ANN is not
warranted (FAISS guidance: Flat for few searches). Filtered ANN degrades
recall (arXiv 2602.11443); exact search sidesteps it. sqlite-vec remains
pre-v1 brute force. Plan: int8 memmap ordered by (era, jurisdiction); query
batch as one f16/int8 matmul on GPU; note numpy int8 `@` does not hit BLAS.

## 4. Chunking

Chroma (July 2024): ~200 tokens best for fact QA; "Rethinking Chunk Size"
(arXiv 2505.21700): 512-1024 wins for broader context. Legal holdings spread
across paragraphs, so 300-600 tokens. LegalBench-RAG (arXiv 2408.10343):
naive 500-char chunks had higher R@64 (76.4 vs 62.2) and the Cohere
reranker hurt. CLERC (arXiv 2406.17186, CAP data): zero-shot IR 48.3%
R@1000. Score documents by max over chunks (arXiv 2606.18781). Metadata
prefix ("Utilizing Metadata for Better RAG", arXiv 2601.11863, ECIR 2026):
consistently beats plain chunks, year and entity fields strongest. Late
chunking (arXiv 2409.04701) +1.4-1.9 nDCG, Qwen3 last-token pooling
compatibility unverified. Contextual retrieval needs an LLM pass over the
corpus (~10B tokens); last. FTS side: Porter stemming evidence-backed for
OCR; add an FTS5 trigram side-index over a small high-value vocabulary.

## 5. Query strategies for vocabulary drift, ranked by recall gain per cost

1. Relevance feedback from the ~700 positives. Kats, van der Putten,
   Scholtes (arXiv 2311.15110): cumulative vector summing of judged-relevant
   documents beat Rocchio and keyword expansion, cutting iterations to 80%
   recall by 18-59%. Cluster positives by sub-issue and era; query per-cluster
   centroids plus per-positive kNN; union. Zero GPU-hours.
2. Citation-graph snowballing. Greenhalgh and Peacock (BMJ 2005): 51% of
   sources from snowballing vs 30% from protocol searches. "Fenced
   Citation-Context Retrieval" (arXiv 2607.17142): +16.1 R@1000 over tuned
   BM25 on CLERC; fence by date; watch popularity bias. CAP metadata carries
   cites_to (verified locally 2026-09-01).
3. Query-only linear adapter (Chroma, May 2024), competitive with full
   fine-tuning from ~1,500 pairs; minutes of GPU; no re-embed. Full
   contrastive fine-tune (GPL arXiv 2112.07577; LEMUR arXiv 2602.09570) and
   Impresso's OCR-noise recipe fold into one re-embed pass.
4. LLM multi-query per era / HyDE: gains shrink against strong
   instruction-tuned embedders and concentrate where the LLM already knows
   the document (arXiv 2504.14175). Cheap vocabulary bridge; weakest evidence.
5. Contextual retrieval / late chunking: last.

## 6. Corpus-linguistics and history-and-tradition defensibility

Standards: Lee and Mouritsen, "The Corpus and the Critics" (88 U. Chi. L.
Rev. 275, 2021): describe search parameters, publish coded concordance lines
and replication instructions, report per-sense counts with an explicit
ambiguous bucket. Slocum and Gries (94 S. Cal. L. Rev. Postscript 13,
2020): rigor, dispersion, frozen corpus version. Tobia (134 Harv. L. Rev.
726): the Nonappearance Fallacy. Lee and Phillips, "Data-Driven Originalism"
(167 U. Pa. L. Rev. 261): coding-bias practices; double-blind multiple
coders. Split-corpus pre-registration (exploratory 20-40% / confirmatory
60-80%) is emerging in Applied Corpus Linguistics (2024). Cautionary tale:
Health Freedom Defense Fund v. Biden (M.D. Fla. 2022), dismantled in
"Unmasking Textualism" (122 Colum. L. Rev. F. 192).

Courts: Rasabout (2015 UT 72) full protocol in concurrence, majority
objected to research not subject to adversarial briefing; Wilson v. Safelite
(6th Cir. 2019) flagged culling; Garibay v. Fox (Ariz. 2025) urged
adversarial testing; Snap v. Vidal (C.D. Cal. 2024) credited expert corpus
testimony. BYU's CUSC (~6.8M CAP documents, https://lcl.byu.edu/projects/corpus-of-us-caselaw-cusc/)
is the case-law corpus courts have seen. No judicial opinion accepting or
rejecting an LLM-assisted survey of case law was found; "Prompting from the
bench" (arXiv 2510.25356) shows LLM meaning judgments are prompt-unstable.
Distinguish LLM-as-classifier validated against a human gold set from
LLM-as-oracle.

Bruen/Rahimi practice: Bruen n.6 endorses party presentation and doubts
three colonial regulations suffice; Rahimi rejects "use it or lose it" from
regulatory absence. Duke's Repository of Historical Gun Laws carries the
disclaimer to imitate: absence from the database does not mean absence of
the law. This survey argues from presence; state counts as lower bounds
over reported, digitized opinions.

Machine-coding standards: Hall and Wright (96 Cal. L. Rev. 63): codebook
frozen after pilot, multiple coders, reliability reported. Choi (2024, SSRN
4536852): tune on a small sample, test once on held-out, pre-register,
validate against humans. Egami et al., "Design-based Supervised Learning"
(arXiv 2306.04746): even 90%-accurate machine labels bias estimates; correct
with a random human-coded subsample. Krippendorff alpha >= 0.80 reliable;
Cohen kappa 0.61-0.80 substantial.

Reporting checklist: (1) corpus provenance, snapshot date, coverage vs CAP's
~6.7M; (2) every query string, model version, threshold, run date; (3) hit
funnel per stage; (4) codebook written before coding with an ambiguous
category; (5) recall against the gold set plus a random human-coded sample;
(6) coder count, blinding, kappa/alpha, adjudication rule; (7) LLM model,
prompt text, prompt-stability check, FP/FN asymmetry; (8) frequencies with
denominators and dispersion by decade and state; (9) limitations; (10)
pre-specified plan with logged deviations; (11) delivered by a declarant
open to adversarial testing, mapped to Daubert factors.

## 7. Technology-assisted review and recall estimation

Cormack and Grossman CAL (SIGIR 2014): 75% recall with 3-16x fewer reads;
TREC Total Recall 2016: recall 0.93 at R+1000 reads, 0.96 at 2R+1000.
Goldilocks (ECIR 2022, arXiv 2105.01044): logistic regression beat BERT on
TAR. Ali, Tan, Wang (2025): embedding-space separability explains work
saved (R=0.81). Train logistic regression / SetFit on the ~7,000 labels over
existing embeddings; check separability first. The 28% to 12% to 6.6%
precision curve is the classic knee (Cormack and Grossman 2016), accepted by
courts as stopping evidence but a heuristic.

Case law: Da Silva Moore (S.D.N.Y. 2012) reasonableness not perfection; Rio
Tinto (2015) TAR is "black letter law"; In re Broiler Chicken (N.D. Ill.
2018) protocol: sample 500 responsive, 500 non-responsive, 2,000
TAR-excluded, blind SME coding, recall = found / (found + scaled misses),
70-80% "consistent with" adequacy
(https://cloudnine.com/wp-content/uploads/2018/07/In-re-Broiler-Chicken-Antitrust-Litig._2018-07-19-20_22_07-0400.pdf).
EDRM TAR Guidelines (2019): 75-85% recall. Cormack et al., "Unbiased
Validation of TAR" (SIGIR 2024): estimates valid only from blind assessments.

Recall arithmetic at 1.3M documents *(derived, prevalence ~0.055%)*: a
null-set sample of n with zero relevant found bounds elusion at ~3/n;
n=2,399 certifies recall >= ~30%; n=10,000 >= 65%; n=38,700 >= 88%;
n=100,000 >= 95%. QBCB (arXiv 2108.12746) with r=30 seeds needs ~55,000
random reads. Use beta-binomial intervals (Webber, ACM TOIS 2013) and
stratify by classifier score. Practical implication: a defensible bound
needs tens of thousands of null-set LLM reads with human blind adjudication
of positives and a nested human sample of negatives. LLM-as-assessor:
Thomas et al. (SIGIR 2024) GPT-4 vs TREC assessors kappa 0.64 vs 0.52
human-human.

## Recommendations ranked by recall gain per GPU-hour and per human-hour

1. Positive-example relevance feedback. Zero GPU; a few human hours.
2. Citation snowballing from verified cases. Zero GPU; free data.
3. Classifier on the ~7,000 labels to rank the candidate pool. Minutes of
   GPU; attacks the 6.6% precision problem; court-accepted approach.
4. Convex-fusion tuning, FTS trigram side-index, reranker over the fused
   union (Qwen3-Reranker-4B with rubric, ~3 GPU-hours per 200k pairs).
5. Query-only linear adapter. Minutes of GPU.
6. One bundled re-embed: Qwen3-4B, metadata prefix, 1024d int8 with
   rescoring. Do once, after 1-5 settle candidate generation.
7. Per-era LLM query expansion. Cheap; weakest evidence.
8. Recall certification plan: budget 25k-40k reads, pre-register, adopt the
   reporting checklist now.
9. Contextual retrieval / late chunking: not before 1-6.

## Could not verify

Qwen3 per-dimension quality at 512 vs 1024; Qwen3 embedding or reranker
throughput on a 4090/5080; RTX 5080 dense bf16 peak; FP8 kernels on sm_120;
Qwen3 pooling compatibility with late chunking; Impresso deltas; Cohere
embed-v4 price; sqlite-vec ANN semantics; full texts of SIGIR 2014/2016 and
Da Silva Moore; whether Judging Ordinary Meaning specifies sampling rules;
any judicial treatment of an LLM-assisted case survey (none found); any
Second Amendment amicus with a formal methodology appendix (none found).
