---
status: accepted
date: 2026-09-01
---

# Extraction schema v2: versioned, with fields the level-of-generality argument actually needs

The v1 schema forced modern STR plaintiffs (owners letting a whole second
home) into either "householder" or "commercial operator", corrupting both
tiers; could not say whether an occupancy was under thirty days, which is
the opponent's exact framing; and carried no distinction between a
restriction upheld and a prohibition upheld on adverse records. We decided
to add a schema version field and four nullable fields: a third
who-was-letting value (non-resident owner of a single dwelling), a
three-valued under-thirty-days field, a restriction-nature field on adverse
records (licensing, conditions, zoning exclusion, outright prohibition), and
the court's characterization of the owner's freedom (incident of ownership,
lawful ordinary use, regulated privilege, not stated). Each requires a
supporting quote like every other judged field. Reporter page returns to the
reader instructions, which had dropped a spec requirement.

## Considered options

- Numeric duration estimate instead of a three-valued field: invites false
  precision from readers.
- Full remap of all 715 records: costs a full cycle; instead, old records
  keep null v2 fields and only favorable and adverse records are remapped,
  which doubles as the human-review pass ADR-0002 requires.
- Defer until after cycle 004: would mean a second remap later over a
  larger ledger.

## Consequences

Schema v2 plus reader prompt v2 become the frozen codebook (ADR-0009).
Any consumer of ledger records must tolerate null v2 fields on v1 records.
