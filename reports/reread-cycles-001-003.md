# The cycles 1-3 re-read under mapper-v3: fills, replacements, and the conflicts the protection rule shielded

Date: 2026-09-09. Run id `cycles-001-003-reread`. Spec: docs/superpowers/specs/2026-09-08-stage-3b-slice-3-ranker-v2-tail-map-reread-design.md (sections 3, 6, 7, 8; decisions D2, D7, D8). Companions: reports/map-cycle-004-shard-02.md, the round handoffs under reports/review-round-reread-*.

## 1. What ran

- **Source.** The 693 case ids with `relevant: true` admitted in cycle-001, cycle-002, cycle-003, taken from the ledger view at log head seq 42984 and frozen in `runs/cycles-001-003-reread/case-ids.json`. Every one had a live store row (0 missing).
- **Reader.** `claude-cli/claude-opus-5@claude-cli:-`, effort `low`, codebook `mapper-v3` (sha `f92016681314`), the same response schema, batch size and timeout as the cycle-004 map, on the Claude subscription; checker `codex-cli@-:-` sampled at 10% (5 units, 49 field disagreements across them). 18-case units grouped by era x jurisdiction cell, case-id order within a cell: 48 batches over 20 cells.
- **Yield stop off.** `flags.threshold = -1` and every cell `cap: none`: the yield-floor rule that stops a quiet cell in a map makes no sense on a re-read, whose whole point is to reach every listed record. It did: 693 of 693 read, 0 failed units, 0 cases lost, 0 split-retries.
- **Invocations.** A two-batch dry run (94 s; inspected, admission paper-run, reported to the user before the field run), then the field run, which was interrupted by a machine restart after batch 18 and relaunched; the relaunch replayed the 18 finished units from the cache at no cost and read the remaining 30 in 58 min. The manifest's token totals (3,366,609 in / 349,969 out) cover the units the second invocation actually bought; the first invocation's 18 units are in the cache and in the extractions but not in these totals. `spend_usd` 0.0 by construction: this is not a charge.
- **The re-read's own verdict.** 636 relevant, 57 irrelevant (under mapper-v3's definition, which has no `irrelevant` polarity and defines `mixed`).

## 2. Fills, replacements, agreements, conflicts per field

Admission (`tools/admit_map.py --run-id cycles-001-003-reread --reread --apply`): 693 records, 5,133 patches, `replay_ok=True`. Rules (spec section 6, D7): a re-admit under mapper-v3 moves each record to the six-field support rule and carries every current value forward; then per judged field, **fill** when the current value is empty, **replace** when the current value has reader or rule provenance, **agree** when equal, **conflict** (skip, flag, card) when the current value has human provenance and the re-read differs, **skipped** when the re-read had nothing to say (null on a relevant record, or any field on a record the re-read called irrelevant).

| field | fill | replace | agree | conflict | skipped |
|---|---|---|---|---|---|
| `relevant` | 0 | 47 | 0 | 10 | 0 |
| `polarity` | 11 | 198 | 443 | 24 | 7 |
| `who_was_letting` | 0 | 235 | 437 | 11 | 0 |
| `characterization` | 85 | 101 | 428 | 21 | 1 |
| `holding_summary` | 60 | 573 | 0 | 3 | 0 |
| `under_thirty_days` | 471 | 0 | 0 | 0 | 165 |
| `owner_freedom_characterization` | 587 | 0 | 0 | 0 | 49 |
| `restriction_nature` | 338 | 0 | 0 | 0 | 298 |
| `duration_of_occupancy` | 2 | 219 | 415 | 0 | 0 |
| `doctrinal_concepts` | 0 | 633 | 3 | 0 | 0 |
| `new_terms_observed` | 0 | 191 | 41 | 0 | 404 |
| `relevance_score` | 0 | 561 | 75 | 0 | 0 |

The three fields no cycles 1-3 record ever carried were filled on 1396 record-fields: `owner_freedom_characterization` on 587 records, `under_thirty_days` on 471, `restriction_nature` on 338 (adverse records only, by the codebook). Polarity was replaced on 198 reader-held values and agreed on 443: mapper-v3's owner-centred polarity and its `mixed` definition moved roughly one reader-held polarity in three, which is why cycles 1-3 could not simply be left on mapper-v1 values beside cycle 004. `who_was_letting` was replaced on 235 and agreed on 437. The `relevant` row: 47 machine-only records the re-read found irrelevant were withdrawn (polarity and who nulled), and 10 such verdicts on human-judged records became cards instead.

Two carry-forward rules apply to every re-admitted record: its `nulled_fields` is the union of both reads' minus every field this admission filled, and its `extraction_status` is the worse of the two reads except `ok` when the merged `nulled_fields` is empty and neither read was extraction-invalid. A record the older read had marked `partial` therefore stays `partial` unless the re-read cleared every erased field; in one live record the exception upgraded a `partial` to `ok`.

## 3. How many human values the protection rule shielded

69 conflicts, one card each, none applied:

| field | kind | cards |
|---|---|---|
| `polarity` | value | 24 |
| `characterization` | value | 21 |
| `who_was_letting` | value | 11 |
| `relevant` | relevant_false | 10 |
| `holding_summary` | value | 3 |

The 10 `relevant_false` conflicts are re-read verdicts of "not relevant" on records that carry a human decision on some judged field (D3's logic: a reviewer's polarity or who decision confirms relevance). They are cards, never overturns; on such a record nothing was written at all, not even the re-admit, so the record keeps every quote a human decision rests on.

Fold-level rejections after admission: **0**. That is the expected number, not a coincidence: the re-read tool computes provenance from the same view it patches against and never emits a `set` the fold would refuse; the fold's own protection (`PROTECTION_FROM_SEQ` 42,984, ruling R1) is the backstop, and `admit_map` exits non-zero if `ApplyResult.rejected` is ever non-empty. Each conflict raised a `needs-review:<field>` flag on the record (34 flags before the re-read, 103 after) and a note naming the human decision that made it a card; the flag is what retires a section-G card once a reviewer decides it.

## 4. What section G asked and what the reviewer decided

Re-read round 1 (250 cards, cap 250): G 69 conflict cards first (polarity 24, characterization 21, who_was_letting 11, relevant 10, holding_summary 3), then A 52, B 16, C 24, D 55, E 34; 105 deferred to a later round. Decisions per round are appended below as the rounds are applied.

_(round outcomes to be appended)_

## 5. Published counts

Via `open_ledger().view().counts()`, two-tier:

| claim | before the re-read | after admission |
|---|---|---|
| relevant records | 3,466 (821 human-reviewed, 2,645 machine-only; lower bound) | 3,419 (821 / 2,598) |
| favorable | 1,501 (379 / 1,122) | 1,450 (377 / 1,073) |
| favorable householder | 341 (80 / 261) | 318 (76 / 242) |

The human-reviewed tier did not lose a record (821 before and after): the two-tier movement inside it (favorable 379 to 377, favorable householder 80 to 76) is reader-held polarity or who values replaced on records whose human decision was on another field, which D7 permits and the conflict rule does not reach.

## 6. Reproduction

```
.venv/Scripts/python tools/reread_records.py --plan
.venv/Scripts/python tools/reread_records.py --dry-run-batches 2
.venv/Scripts/python tools/reread_records.py --max-wall-seconds 86400
.venv/Scripts/python tools/admit_map.py --run-id cycles-001-003-reread --reread --dry-run
.venv/Scripts/python tools/admit_map.py --run-id cycles-001-003-reread --reread --apply
```

Re-running the field line replays every finished unit from `data/reader/cache/` for free; `--reread --apply` refuses a run id already admitted and refuses a `--run-id` that differs from the manifest's.
