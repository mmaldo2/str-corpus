# Cycle-004 map review, round 1b — handoff addendum (unsure cards, full opinion text)

This is an addendum to `reports/review-round-1-handoff.md` (round 1's handoff). Read that
document first — it is not repeated here. Everything it says still applies: the project's
purpose, the six sections and their priority order, the judgment rules and vocabularies
(polarity direction, mixed, relevance, the closed value sets), the four decision types
(`keep`/`adopt`/`set`/`unsure`) and what each means, and the constraints on your output
(never invent facts beyond the evidence, don't change `case_id` or `field`, cover every card
exactly once). This addendum states only what is different for round 1b.

## What's different in round 1b

Round 1's first pass left 67 of its 150 cards `unsure`. Most of that was really a relevance
dispute in disguise: round 1's checker disputed relevance on 46 cards, but every card in round
1 decided `polarity` or `who_was_letting` — no card had a way to say "this is not a letting
case at all," so a genuine relevance disagreement had nowhere to go but `unsure`. Round 1b is
a second first pass over exactly those 67 cards, with two changes: you now have the full text
of each opinion, not just the reader's extracted quotes, and you now have a way to rule a case
out of the corpus on any card, whatever field that card asks about.

## The input files

**`review-round-1b-unsure-cards.json`** — a JSON array of 67 objects, the same card shape
round 1's JSON used (`case_id`, `section`, `section_title`, `name`, `cite`, `court`,
`jurisdiction`, `year`, `decide_field`, `reader`, `checker`, `holding_summary`, `quotes`,
`nulled_fields`, `other_reasons`, `courtlistener_url`) restricted to the 67 cards round 1 left
unsure, plus one new field:

- `opinion_text` — the full text of the court's opinion (the store's normalized text for the
  case; mean length across the corpus is ~15,000 characters, the longest ~55,000). This is
  what round 1 withheld; use it to settle what the extracted quotes alone could not.

**`review-round-1b-unsure-cards-part1.md`** through **`-part4.md`** — the same 67 cards as
readable prose, split into four files by size (never splitting a card) so a model with a
smaller context window can work through the round one file at a time. Each part has the same
section headings and per-card layout round 1's markdown used, with the opinion text appended
after the card's fields under an "Opinion text" heading. Read whichever part(s) you were
given; the four files together cover all 67 cards exactly once, with no overlap.

## The new decision: overturning relevance

On ANY card — whatever `decide_field` it names — you may now submit a second kind of decision
instead of (never in addition to) deciding that field, saying the case does not belong in the
corpus at all:

```json
{"case_id": 331147, "field": "relevant", "decision": "set", "value": false,
 "note": "the opinion is a probate accounting dispute; the boarding house is mentioned only
 to value an asset of the estate, and no holding turns on the letting arrangement itself"}
```

Use it when the full opinion settles that the case does not bear on compensated occupancy of
another's dwelling or rooms, its legal character, or its regulation — the same rule round 1's
handoff quoted from the codebook, restated here because it is the whole test:

> `relevant`: does the case bear on compensated occupancy of another's
> dwelling/rooms, its legal character, or its regulation? Procedural cases
> that merely mention a boarding house in passing are `false`.

A few things this decision is NOT for:

- It is not for registering doubt. If the full opinion leaves the question genuinely open,
  that is `unsure` (below), not a relevance overturn.
- `value` must be `false` (the strings `"false"`/`"False"` are also accepted). `relevant`
  `true` is not an accepted decision — every one of these 67 cards already reads
  `relevant: true` on the record, so `keep` on the card's own field already covers confirming
  that; there is nothing for a `relevant: true` decision to do.
- It replaces the card's own field for that case, not adds to it: do not also submit a
  `polarity` or `who_was_letting` decision for a case you are overturning. The tool nulls
  both of those fields itself, along with setting `relevant` false, in one patch — a case
  ruled out of the corpus carries neither.
- It cannot be used twice on the same case, and cannot be used on a case that is already
  `relevant: false` on the record — there is no relevance left to overturn.

## Otherwise, decide the card's own field as in round 1

For every card where the full opinion confirms this IS a letting case, decide the card's own
`decide_field` exactly as round 1's handoff describes — `keep`, `adopt`, or `set` — citing what
the full opinion (not just the quotes this time) actually shows.

`unsure` is still allowed, but you now have the whole opinion instead of a handful of extracted
quotes, so it should be rare. Reach for it only when the full text genuinely does not settle
the question, not merely because the quotes alone did not — that was round 1's problem, not
this one's.

## Required output

One JSON object per card, covering all 67 cards in `review-round-1b-unsure-cards.json` exactly
once — 67 entries, no more, no fewer, no duplicates. Each entry is either:

- a normal decision on the card's own `decide_field`, in round 1's schema
  (`{"case_id", "field", "decision": "keep"|"adopt"|"set"|"unsure", "value", "note"}`), or
- a relevance-overturn decision for a case that turns out not to be a letting case at all
  (`{"case_id", "field": "relevant", "decision": "set", "value": false, "note"}`).

Same `case_id` and `note` conventions as round 1: copy `case_id` unchanged, and make `note` one
line of reasoning that cites what specifically in the full opinion drove the call. As before,
nothing you write is applied directly — the human confirms every decision, case by case, before
anything changes.

## How the human will apply your output

Save your JSON list to a file, then the human runs:

```
.venv\Scripts\python tools\apply_map_review.py --decisions <your-file.json> \
    --run-id map-cycle-004-round-1b --assisted-by "GPT Astra" --dry-run
```

`--run-id map-cycle-004-round-1b` matters here: round 1 already applied its decisions under
this tool's default run id (`map-cycle-004-round-1`), and the tool refuses to apply a second
time under a run id that already has patches in the ledger (every `review.notes` patch
interpolates the field's *current* value, so a second run under the same id would re-emit a
fresh, misleading note for every decision round 1 already made) — round 1b needs its own id.

The dry run prints every decision against the record's current value without changing
anything, so the human can review your reasoning card by card, including every relevance
overturn, before anything is applied. Every decision is checked against the round's queue
manifest first — a `case_id` not among the 67 this round covers, a `field` that is neither the
card's own `decide_field` nor `relevant`, or a `relevant` decision that is not `set`/`false`
(or that targets a case already `relevant: false`) is refused by name before any of your
decisions are applied, so a mistake in your file cannot silently answer the wrong question or
misfire a relevance override. Once satisfied, the human re-runs the same command without
`--dry-run`, then commits the applied decisions file at
`runs/cycle-004-shard-01/review-round-1b-decisions-astra.json`. `--assisted-by "GPT Astra"`
marks every applied decision's record with a note that it was first-pass drafted by you and
confirmed by the reviewer, so the project's human-reviewed tier stays honest about which
decisions had model assistance.
