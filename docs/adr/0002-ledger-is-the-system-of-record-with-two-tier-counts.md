---
status: accepted
date: 2026-09-01
---

# The ledger is the system of record, mutated only through one module, and every count is two-tier

Three scripts rewrote the ledger files in place, three different cumulative
totals were live at once, 15 null-polarity records appeared in no total, and
79% of relevant records had never been touched by a human yet were counted
alongside the adjudicated ones. We decided: the JSONL ledger in git stays
canonical; a single ledger module owns every write and appends a patch
event (who, when, why, old, new) per mutation; a per-cycle manifest records
every case read with its outcome; and every published number is stated
separately for human-reviewed and machine-only records, derived from one
function, never blended.

## Considered options

- Move the ledger into SQLite with provenance tables: better queries, but
  loses git-diffable history, which is the audit trail a methods section
  cites.
- Keep ad hoc scripts and fix the counts by hand: this is how the three
  live numbers happened.

## Consequences

Reviewer identity is recorded per adjudication so agreement can be
computed later. The review page remains publishable as a shareable artifact,
but a separate attorney review tier was considered and dropped: the
attorney is unlikely to adjudicate directly. Hard-coded one-off corrections
baked into pipeline code (a specific case id, a specific risk-cite list)
become patch events in the log.
