# Cycle-004 tail map (shard 02) review, round 2 — handoff addendum

Read `review-round-s02-1-handoff.md` first (and the handoffs it builds on); this addendum
changes only what follows.

## What this round is

The second budget of the tail map (reports/map-cycle-004-shard-02.md §9): 2,997 more cases
read under a per-cell floor and then the global order, 460 relevant. The queue over them holds
**147 cards in one round** (nothing deferred). Every record on a card is machine-only today.

Cards: `reports/review-round-s02-2-cards.json` and `-part1..6.md` (full opinion text on every
card). Page: see the controller's message for the link.

## Composition

| section | cards | decide |
|---|---|---|
| A. Favorable + under thirty days | 13 | `polarity` |
| C. Checker disagreements (from the 10% sample) | 16 | `relevant` 6, `polarity` 6, `characterization` 4 |
| D. Polarity mixed | 28 | `polarity` |
| E. Judged fields erased by the quote gate | 80 | `under_thirty_days` 38, `owner_freedom_characterization` 38, `polarity` 2, `restriction_nature` 1, `characterization` 1 |
| F. Fuzzy quote match | 10 | `quotes` |

Sections B and G are empty.

## Two rules settled since round 1

- **E cards: empty when silent.** Leave the field empty (`keep`) when the opinion does not
  speak to it; `set unclear` / `set not_addressed` only when the court addresses the question
  and leaves it open. (User rule, 2026-09-09.)
- **Withdrawing a record.** A relevance withdrawal is a decision in its own right:
  `{"field": "relevant", "decision": "set", "value": false}` on any card. On the page it is
  the "Not a letting case" control. Do not use `unsure` for it.

## Checker

The 100% Codex pass ran over the queue (see the checker file beside the queue); `adopt` is
available. Decide from the opinion before consulting the checker; it is one more reading,
not a vote.

## Decisions file

`runs/cycle-004-shard-02/review-round-2-decisions-<name>.json`, the usual schema, one entry
per card. Apply, dry run first, the user confirming:

```
.venv\Scripts\python tools\apply_map_review.py --queue runs\cycle-004-shard-02\review-round-2.json --decisions runs\cycle-004-shard-02\review-round-2-decisions-<name>.json --assisted-by "<name>" --run-id map-cycle-004-shard-02-round-2 --dry-run
```
