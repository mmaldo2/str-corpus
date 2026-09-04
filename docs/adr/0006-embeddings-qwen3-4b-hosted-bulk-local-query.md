---
status: accepted
date: 2026-09-01
supersedes: spec amendment A5 (model size and storage), not its pinning rule
---

# Re-embed with Qwen3-Embedding-4B, bulk through a hosted endpoint, queries locally, full-dimension int8

The index used Qwen3-Embedding-0.6B truncated to 512 dimensions and stored
int8. The 4B model scores about 5 to 7 points higher on legal retrieval
benchmarks; the 8B adds barely a point more; the truncation plus int8 costs
an estimated 3 to 5 percent, half recoverable by rescoring. Re-embedding
locally would take four days for the current corpus and eight to ten at
ten million chunks; the same open model at the same pinned revision costs
about $18 now and $45 at ten million chunks through a hosted endpoint, in
hours. We decided to allow paid hosted inference for bulk embedding only,
compute query-time embeddings locally with the same pinned weights, verify
agreement on a thousand-chunk sample before trusting the hosted vectors,
store full 1024-dimension int8 vectors with float rescoring of the top
candidates, prepend a metadata header (case name, court, year) to each
chunk, and have the shard engine refuse to run an embedding selector across
partitions embedded by different models.

## Considered options

- Stay on 0.6B: no cost, but every later cycle inherits the weaker index.
- Paid legal-specialized embedding API: scores below the open 4B on the one
  independent legal benchmark and is not reproducible from pinned weights.
- Rented GPU: dominated by the hosted endpoint on both cost and effort.
- Approximate-nearest-neighbor index: not warranted for a few hundred
  offline queries per cycle; exact search avoids filtered-ANN recall loss.

## Consequences

The new states are embedded with the 4B from the start and the existing
four are backfilled; embedding selectors on the old states pause until the
backfill lands while lexical, citation-graph, and relevance-feedback
selectors continue. Re-embedding on demand becomes cheap enough that a
fine-tune or OCR-noise adaptation can be applied corpus-wide later.

## Amendment 2026-09-02

The full-corpus estimate came in higher than the original $60 ceiling:
1,874,141 cases, ~6.11B tokens, ~$61.13 at $0.01/M tokens. By user decision
the ceiling is raised from $60 to $65 to cover this single run, rather than
splitting it into a two-phase run (existing four states first, new states
second) that would leave the index straddling two runs for longer and cost
more in wall-clock and operational risk than the $1.13 overage is worth.

Before spending, the hosted/local consistency gate this ADR requires was
run: n=1000, mean cosine 0.9999, p5 0.9999, min 0.9998 -- comfortably above
the bar for trusting the hosted vectors. The full-corpus hosted run then
launched as a single pass under the raised $65 ceiling.

## Amendment 2026-09-03 (run complete)

The $0.01/M price the research note called "verified" was wrong: OpenRouter
routes `qwen/qwen3-embedding-4b` to DeepInfra at $0.020/M tokens (confirmed
from the per-request `usage.cost` field and DeepInfra's list price during the
run). At the 200,000-case mark the spend was tracking double the estimate; by
user decision the credit was topped up and the ceiling raised to $130 to
finish the single pass. Final spend on the OpenRouter account: $112.22
(gate, probes, and the full corpus; implies ~5.6B billed tokens against the
6.11B sampled estimate). Wall clock 2026-09-02 14:04 to 2026-09-03 22:01,
including five restarts (interpreter, uncaught read timeout, throttling
burst, and two external kills of the session-managed task; the last leg ran
detached). Sustained throughput ~120 chunks/s at 8 concurrent requests; the
provider throttled harder above that. `domains/str-right-to-let/domain.yaml`
now carries `hosted_usd_per_m_tokens: 0.02`.
