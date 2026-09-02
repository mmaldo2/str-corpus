---
status: accepted
date: 2026-09-01
---

# The selector engine, ledger, and reader driver take the interfaces recorded in docs/design/2026-09-01-module-interfaces

Three candidate interfaces per module were designed in parallel under
different constraints and compared on depth, locality, and seam placement.
We decided on hybrids, recorded in full in
`docs/design/2026-09-01-module-interfaces/README.md`. The decisions a future
reader will otherwise wonder about: the ledger has no ports at all, because
the filesystem is its own test stand-in and a memory store would exist only
to be injected; the reader driver has exactly two ports, because the
experiment kit is a genuine second case-text adapter and the LLM provider
is a true external with five adapters; the selector engine's coverage rows
carry a retriever fingerprint rather than a separate seed-hash column, so
the mixed-embedding-model rule and seed-set reproducibility are one
mechanism; ranking never touches the signals table, so recall attribution
is measured before truncation; and the quote gate runs inside the reader
driver, so no unverified record can cross that seam.

## Consequences

One latent bug surfaced by the design pass is fixed as a logged version
bump rather than silently: the unstable candidate sort in the embedding
runner (Stage 2). A second suspected bug, that the hard-coded Shvekh quote
drop left a judged field standing without support, was inspected in Stage
1 and found not to exist: the dropped quote supported only who_was_letting,
which the human corrected directly. The retraction cascade is nonetheless
enforced for every future quote drop. Characterization tests reproduce the cycle-003 batches,
verified files, and ledgers byte for byte before either module is
replaced.
