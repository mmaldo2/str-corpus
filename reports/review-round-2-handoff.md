# Cycle-004 map review, round 2 — handoff addendum (checker disagreements, mixed polarity)

This is an addendum to `reports/review-round-1-handoff.md` (round 1) and
`reports/review-round-1b-handoff.md` (round 1b). Read those first — they are not repeated
here. Everything they say still applies: the project's purpose, the six sections and their
priority order, the judgment rules and vocabularies (polarity direction, mixed, relevance, the
closed value sets), the four decision types (`keep`/`adopt`/`set`/`unsure`) and what each
means, the round-1b relevance-overturn decision (available on any card, whatever field it
decides), and the constraints on your output (never invent facts beyond the evidence, don't
change `case_id` or `field`, cover every card exactly once). This addendum states only what is
different for round 2.

## This round's composition

250 cards, capped at the round's own budget, drawn from three sections:

- **B. Householder letting by the night** — 1 card. Decide `who_was_letting`, exactly as
  round 1's handoff describes.
- **C. Reader / checker disagreement** — 100 cards. The reader and a second machine reader
  (the checker) answered differently on `relevant`, `polarity`, or `characterization` for
  these cases. Broken down by the field actually in dispute: `relevant` 41, `polarity` 33,
  `characterization` 26.
- **D. Polarity mixed** — 149 cards. The reader could not put the case cleanly on one side.
  Decide `polarity`.

Sections A, E, and F are empty this round (A was exhausted in rounds 1/1b; no card queued
into E or F this time). Every card in this round carries the full opinion text — see
`opinion_text` below.

## How to decide a section-C card

`decide_field` on a section-C card is whichever field the reader and the checker disagreed on
— `relevant`, `polarity`, or `characterization`, never a field they agreed on even if you
notice something else looks wrong. Both values are on the card: `reader` carries the first
reader's answer (the value that stands unless you decide otherwise) and `checker` carries the
second reader's answer for the same field, shown prominently in the exported markdown as
"Reader says X; checker says Y" so the disagreement is the first thing you see, not something
you have to cross-reference. You have the full opinion text this round (not just extracted
quotes), so read it and decide which reader has the better-supported answer:

- `adopt` — the checker's value is right. This is the only path that can carry `relevant`
  false: a section-C card whose `decide_field` is `relevant` itself has a queued record that
  is already `relevant: true` on the ledger, so a checker disagreement on it can only ever be
  a checker saying `false` — the tool applies the same relevant/polarity/who_was_letting
  cascade this decision writes as round 1b's relevance-overturn `set` does (the case carries
  neither polarity nor who_was_letting once it is out of the corpus). `checker` `relevant:
  true` never happens (a queued case already reads `relevant: true`), so there is nothing for
  `adopt` to do on that direction.
- `keep` — the reader's value is right; the checker's disagreement does not hold up against
  the full opinion.
- `set` — neither reader nor checker is right; the full opinion supports a third value from
  the field's vocabulary.
- `unsure` — the full opinion genuinely does not settle which reader is right. Should be rare
  with the whole opinion in hand, same as round 1b.

On a section-C card whose `decide_field` is `polarity` or `characterization` (not `relevant`),
you may still write the standalone relevance-overturn decision from round 1b's handoff
(`{"case_id", "field": "relevant", "decision": "set", "value": false, "note"}`) instead of
deciding the card's own field, if the full opinion shows the case does not belong in the
corpus at all — that option is available on every card in every round, not only section C.

## How to decide a section-D card

`decide_field` is `polarity`. The reader already called this case `mixed`; with the full
opinion in front of you, decide whether it really is mixed under the codebook's definition —
quote the specific passage in your `note` — or whether it should actually be `favorable` or
`adverse`:

> Mixed means the same opinion both recognizes the owner's freedom to let on one point and
> restricts it on another, and both are holdings rather than remarks in passing. If only one
> side is a holding, follow the holding and note the tension in the summary. An owner who wins
> on a ground unrelated to letting is not favorable; judge only what the court decided about
> letting.

- `keep` — the case genuinely holds both ways; cite the two holdings your `note` is quoting.
- `set` — only one side is actually a holding (the other is dicta, or unrelated to letting);
  set `favorable` or `adverse` to match the real holding, quoting it.
- `unsure` — the full opinion does not make clear which parts are holdings.
- The standalone relevance-overturn decision is available here too, same as any card.

## The input files

Same shape as round 1/1b's exports (`tools/export_review_cards.py`), with two differences this
round: every card carries `opinion_text` (the controller ran the export with
`--full-text-sections C,D`, so B's one card has none — it does not need the full text to
decide `who_was_letting`), and section-C cards carry the reader/checker contrast called out
above, both in the JSON (`reader`/`checker` blocks) and highlighted in the markdown.

## Required output

One JSON object per card, covering all 250 cards in this round's export exactly once — 250
entries, no more, no fewer, no duplicates. Same schema as round 1/1b
(`{"case_id", "field", "decision", "keep"|"adopt"|"set"|"unsure", "value", "note"}`), plus the
standalone relevance-overturn shape wherever it applies
(`{"case_id", "field": "relevant", "decision": "set", "value": false, "note"}`). Save it to:

```
runs/cycle-004-shard-01/review-round-2-decisions-astra.json
```

## How the human will apply your output

```
.venv\Scripts\python tools\apply_map_review.py --decisions runs\cycle-004-shard-01\review-round-2-decisions-astra.json ^
    --queue runs\cycle-004-shard-01\review-round-2.json --checker runs\cycle-004-shard-01\review-round-2-checker.json ^
    --run-id map-cycle-004-round-2 --assisted-by "GPT Astra" --dry-run
```

`--run-id map-cycle-004-round-2` matters here for the same reason it mattered in round 1b:
rounds 1 and 1b already have patches in the ledger under their own run ids, and the tool
refuses to re-apply under a run id that already has patches (every `review.notes` patch
interpolates the field's *current* value, so a second run under the same id would re-emit a
fresh, misleading note for every decision an earlier round already made). This round needs its
own id, distinct from both of theirs.

The dry run prints every decision against the record's current value without changing
anything, so the human reviews your reasoning card by card — including every adopt on a
section-C `relevant` card and every standalone relevance overturn — before anything is
applied. Every decision is checked against this round's own queue manifest first, exactly as
in rounds 1 and 1b: a `case_id` not among the 250 this round covers, a `field` that is neither
the card's own `decide_field` nor `relevant`, or a `relevant` decision that does not resolve to
`false` (or that targets a case already `relevant: false`) is refused by name before any
decision is applied. Once satisfied, the human re-runs the same command without `--dry-run`,
then commits the applied decisions file alongside this handoff.

## A note on rounds after this one

Later rounds will populate section E (a judged field the quote gate erased for lack of a
supporting quote — the exported card will carry `erased_value`, the reader's original answer
before the gate nulled it, alongside the field's current `null`) and section F (a quote that
matched the opinion only approximately — decide whether the underlying claim is still
trustworthy or needs a full re-read). Both sections are outside this round's 250 cards and
need no decision from you here.
