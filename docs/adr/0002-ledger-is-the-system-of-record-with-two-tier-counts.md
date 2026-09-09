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


## Amendment 2026-09-08 — a machine write never overwrites a human decision (D2)

The ledger recorded who wrote a patch but not who decided a *field*, so any later
`set` could overturn an adjudication silently — and slice 3 is about to re-read
cycles 1-3 and map the tail with a machine reader. The fold now tracks per-field
provenance (`human` | `reader` | `rule`, sticky at `human`) and refuses any write
on a human-decided field whose basis carries no reviewer. Reader basis and rule
basis alike: a rule that can quietly undo a judgment is the same hole as a reader
that can, and a rule may still fix such a field through a reviewer or through a
`migrate` op, which is exempt because a vocabulary migration renames a value
rather than judging a case. A refusal is never an exception — `view()` replays
the whole log on every call — so the standing value stays, the attempt is
recorded in `State.conflicts`, and the record is flagged `needs-review:<field>`
(rule id `reviewer-protection`) so the disagreement reaches a review card. A
write of the same value is not an overwrite and is silent: 161 writes in the log
re-state a reviewer's own value from a later `admit` body.

A refused patch is still appended. The log is append-only and the replay is the
truth, so the disagreement is recorded rather than swallowed — but it changed
nothing, so `ApplyResult` reports it under `rejected` and not under `applied`,
and a tool that finds `rejected` non-empty says so and exits non-zero instead of
claiming an admission it did not make. Because a patch carries no `seq` until it
is appended, and the baseline below reads the `seq`, every fold of
not-yet-appended patches stamps the seqs the append will assign
(`ledger.log.provisional_seqs`) — without that, a trial fold or a `--dry-run`
would accept a write the real log refuses.

**The rule is enforced from seq 42984**, the log head on 2026-09-08
(`fold.PROTECTION_FROM_SEQ`). Six writes below that baseline already changed a
reviewer-decided field: seq 7368 (4268287 `polarity`), 7372 (1932707
`polarity`), 7376 (2186819 `characterization`) and 7378 (2186819 `polarity`),
all `retraction-cascade-v1` nulls triggered by a reviewer's own `drop_quote` and
all restored by hand afterwards; and seq 7818 (608729 `polarity`) and 7820
(10225079 `polarity`), the `vocab-v3-cleanup` nulls of the deleted value
`irrelevant`. Enforcing the rule over them would rewrite five committed records
and flag them, so they are grandfathered: still applied, no flag, listed for the
record by `LedgerView.conflicts(historical=True)`. A fresh in-memory replay of
`data/ledger/patches.jsonl` therefore still hashes to the four committed cycle
files, and the published counts are unchanged (2,716 relevant = 821
human-reviewed + 1,895 machine-only; 1,229 favorable; 303 favorable +
householder).
