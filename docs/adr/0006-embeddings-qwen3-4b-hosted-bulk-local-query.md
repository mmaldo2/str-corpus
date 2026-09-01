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
