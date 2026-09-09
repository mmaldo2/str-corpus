# Cycle-004 tail map (shard 02) review, round 1 — handoff addendum

Read `review-round-1-handoff.md`, `review-round-3-handoff.md`, `review-round-3b-handoff.md`
and `review-round-4-handoff.md` first; this addendum changes only what follows and does not
repeat their rules (the four decisions, the polarity / mixed / relevance definitions and
vocabularies, the relevance-overturn path available on any card, how a section-E card's
`erased_value` is decided, or how an F card's quote is kept or dropped).

## What this round is

The cycle-004 tail: 3,006 cases the shard-01 map never reached, re-ranked by classifier v2
and read under a 3,000-case budget (reports/map-cycle-004-shard-02.md). 750 came back
relevant; the review queue over them holds **213 cards in one round** (nothing deferred).
Every record on a card is machine-only today; a `keep` or `set` moves it into the
human-reviewed tier, an `unsure` leaves it machine-only and flagged.

Cards: `reports/review-round-s02-1-cards.json` and `-part1..8.md` (full opinion text on every
card). Page: https://claude.ai/code/artifact/0dcc7b08-8b76-48fc-8175-c38e0ff9b5df

## Composition

| section | cards | decide |
|---|---|---|
| A. Favorable + under thirty days | 24 | `polarity` |
| B. Householder nights | 1 | `who_was_letting` |
| C. Checker disagreements (from the 10% sample read during the map) | 28 | `relevant` 11, `polarity` 12, `characterization` 5 |
| D. Polarity mixed | 66 | `polarity` |
| E. Judged fields erased by the quote gate | 82 | `under_thirty_days` 47, `owner_freedom_characterization` 26, `characterization` 9 |
| F. Fuzzy quote match | 12 | `quotes` |

Section G (re-read conflicts) is empty in this round: it belongs to the cycles 1–3 re-read,
whose round follows separately.

## No checker opinion this round

The 100% Codex pass over the queue failed on every card: the OpenAI usage limit was hit
before the first unit ran ("try again at Sep 15th, 2026 9:40 PM"). The checker file
(`runs/cycle-004-shard-02/review-round-1-checker.json`) records 213 `failed` entries, so
**`adopt` is not available on any card** — the tool refuses it. Decide from the opinion text
with `keep`, `set` or `unsure`. The C cards still carry the checker's opinion from the map's
own 10% sample (that is why they are C cards); treat it as one more reading, not a vote.

## Decisions file

Write decisions to `runs/cycle-004-shard-02/review-round-1-decisions-<name>.json` in the usual
schema — a list of `{"case_id", "field", "decision", "value", "note"}` — one entry per card,
`field` = the card's `decide_field`, `value` only on `set` (vocabulary values exactly as the
codebook lists them; a relevance overturn is `{"field": "relevant", "decision": "set",
"value": false}` and needs the full opinion, which every card has). `unsure` is a decision,
not an omission: every card gets an entry.

Apply (dry run first; the user confirms card by card before the real apply):

```
.venv\Scripts\python tools\apply_map_review.py --queue runs\cycle-004-shard-02\review-round-1.json --decisions runs\cycle-004-shard-02\review-round-1-decisions-<name>.json --assisted-by "<name>" --run-id map-cycle-004-shard-02-round-1 --dry-run
```
