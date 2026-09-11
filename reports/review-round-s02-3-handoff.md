# Cycle-004 tail map (shard 02) review, round 3 — handoff addendum

Read `review-round-s02-2-handoff.md` first (and the handoffs it builds on); this addendum
changes only what follows.

## What this round is

The third budget of the tail map (reports/map-cycle-004-shard-02.md §10): the 13 thin cells
read to a deep floor (1,224 cases, 34 relevant) and the global order read on down to a score
of 0.13 (3,735 cases, 537 relevant). The queue over the new records holds **192 cards in one
round** (nothing deferred). Every record on a card is machine-only today.

Cards: `reports/review-round-s02-3-cards.json` and `-part1..8.md` (full opinion text on every
card). Page: see the controller's message for the link.

## Composition

| section | cards | decide |
|---|---|---|
| A. Favorable + under thirty days | 15 | `polarity` |
| B. Householder nights | 5 | `who_was_letting` |
| C. Checker disagreements (from the 10% sample) | 37 | `polarity` 18, `relevant` 14, `characterization` 5 |
| D. Polarity mixed | 33 | `polarity` |
| E. Judged fields erased by the quote gate | 95 | `owner_freedom_characterization` 54, `under_thirty_days` 39, `restriction_nature` 1, `characterization` 1 |
| F. Fuzzy quote match | 7 | `quotes` |

Section G is empty. The rules settled in round 2 stand: an E card stays EMPTY (`keep`) when
the opinion is silent; a relevance withdrawal is its own decision
(`{"field": "relevant", "decision": "set", "value": false}`), never `unsure`.

This round reaches deeper into the score curve than any before it, so expect more cards
where the letting is incidental colour: read for whether the court decided something about
compensated occupancy of a dwelling or rooms, its legal character, or its regulation.

## Checker

The 100% Codex pass ran over the queue (checker file beside the queue); `adopt` is available.
Decide from the opinion before consulting the checker.

## Decisions file

`runs/cycle-004-shard-02/review-round-3-decisions-<name>.json`, the usual schema, one entry
per card. Apply, dry run first, the user confirming:

```
.venv\Scripts\python tools\apply_map_review.py --queue runs\cycle-004-shard-02\review-round-3.json --decisions runs\cycle-004-shard-02\review-round-3-decisions-<name>.json --assisted-by "<name>" --run-id map-cycle-004-shard-02-round-3 --dry-run
```
