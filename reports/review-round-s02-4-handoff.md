# Cycle-004 tail map (shard 02) review, round 4 — handoff addendum

Read `review-round-s02-3-handoff.md` first (and the handoffs it builds on); this addendum
changes only what follows.

## What this round is

The high-score leftovers of the tail map (reports/map-cycle-004-shard-02.md §11): the 57
batches above score 0.4 that the per-cell yield floor had stopped in three cells, read on
Opus with the floor off; 1,044 cases, 101 relevant. The queue over them holds **23 cards in
one round** (nothing deferred). Every record on a card is machine-only today.

Cards: `reports/review-round-s02-4-cards.md` (one file, full opinion text on every card) and
its JSON twin `reports/review-round-s02-4-cards.json`.

## Composition

| section | cards | decide |
|---|---|---|
| A. Favorable + under thirty days | 5 | `polarity` |
| C. Checker disagreements (from the 10% sample) | 2 | `relevant` |
| D. Polarity mixed | 6 | `polarity` |
| E. Judged fields erased by the quote gate | 9 | `under_thirty_days` / `owner_freedom_characterization` |
| F. Fuzzy quote match | 1 | `quotes` |

The settled rules stand: an E card stays EMPTY (`keep`) when the opinion is silent; a
relevance withdrawal is its own decision (`{"field": "relevant", "decision": "set",
"value": false}`), never `unsure`. These records come from cells the yield floor had stopped
early, so expect hotel torts and bailment cases where the innkeeper relation is background;
withdraw those.

## Checker

The 100% Codex pass ran over the queue (checker file beside the queue); `adopt` is available.
Decide from the opinion before consulting the checker.

## Decisions file

`runs/cycle-004-shard-02/review-round-4-decisions-<name>.json`, the usual schema, one entry
per card. Apply, dry run first, the user confirming:

```
.venv\Scripts\python tools\apply_map_review.py --queue runs\cycle-004-shard-02\review-round-4.json --decisions runs\cycle-004-shard-02\review-round-4-decisions-<name>.json --assisted-by "<name>" --run-id map-cycle-004-shard-02-round-4 --dry-run
```
