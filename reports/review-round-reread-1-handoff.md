# Cycles 1-3 re-read review, round 1 — handoff addendum

Read `review-round-1-handoff.md`, `review-round-3b-handoff.md`, `review-round-4-handoff.md` and
`review-round-s02-1-handoff.md` first; this addendum changes only what follows.

## What this round is

The 693 relevant records of cycles 001-003 were re-read under mapper-v3
(reports/reread-cycles-001-003.md). The re-read filled the three fields those records never
had, replaced reader-held values, and — where it disagreed with a value a HUMAN reviewer had
decided in an earlier round — was refused by the ledger and turned into a **section G card**
(69 of them). The queue over the re-read holds 250 cards in this round, G first; 105 more are
deferred to a later round.

Cards: `reports/review-round-reread-1-cards.json` and `-part1..8.md` (full opinion text on
every card). Page: https://claude.ai/code/artifact/65df3b0d-ce2c-429f-ba63-a896a715dfb7

## Composition

| section | cards | decide |
|---|---|---|
| G. Re-read conflicts with a human decision | 69 | `polarity` 24, `characterization` 21, `who_was_letting` 11, `relevant` 10, `holding_summary` 3 |
| A. Favorable + under thirty days | 52 | `polarity` |
| B. Householder nights | 16 | `who_was_letting` |
| C. Checker disagreements (from the 10% sample) | 24 | `polarity` 13, `characterization` 6, `relevant` 5 |
| D. Polarity mixed | 55 | `polarity` |
| E. Judged fields erased by the quote gate | 34 | `under_thirty_days` 24, `owner_freedom_characterization` 9, `restriction_nature` 1 |
| F. Fuzzy quote match | 0 | — |

## Section G, the new section

A G card shows the **human value** (with the reviewer and the round that decided it), the
**re-read value** (mapper-v3, Opus on the subscription), both bases, the quotes and the full
opinion. The record is already human-reviewed; the card asks whether the reviewer, with the
opinion in front of them, stands by the earlier decision.

- `keep` — the human value stands (the expected answer). The `needs-review:<field>` flag the
  conflict raised is cleared and a note records that the value was confirmed against the
  re-read.
- `set <value>` — the reviewer revises their own earlier decision; the patch carries reviewer
  basis and its note names the decision it supersedes. On a `relevant` card, `set relevant
  false` withdraws the record (polarity and who nulled) exactly as a relevance overturn does.
- `unsure` — the flag stays; the record stays human-reviewed on its other fields.
- There is no `adopt` on a G card: the second opinion is the re-read itself, already on the
  card.

A case can carry two G cards (one per conflicting field); the card key is (case_id, field).
Once a G card is decided it retires: later rounds do not re-ask it.

## Checker

The 100% Codex pass ran over the queue: 247 of 247 cases ok (250 cards; a case with two G
cards is read once). `adopt` is available on A-F cards.

## Decisions file and apply

`runs/cycles-001-003-reread/review-round-1-decisions-<name>.json`, the usual schema, one
entry per CARD (a two-G-card case gets two entries, each with its own `field`). Apply, dry run
first, the user confirming card by card:

```
.venv\Scripts\python tools\apply_map_review.py --queue runs\cycles-001-003-reread\review-round-1.json --decisions runs\cycles-001-003-reread\review-round-1-decisions-<name>.json --assisted-by "<name>" --run-id reread-round-1 --dry-run
```
