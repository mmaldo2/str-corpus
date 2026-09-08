# Cycle-004 map review, round 3 — handoff addendum (section E, the quote-gate erasures)

This is an addendum to `reports/review-round-1-handoff.md` (round 1) and
`reports/review-round-2-handoff.md` (round 2). Read those first — they are not repeated
here. Everything they say still applies: the project's purpose, the six sections and their
priority order, the judgment rules and vocabularies (polarity direction, mixed, relevance,
the closed value sets), the four decision types (`keep`/`adopt`/`set`/`unsure`) and what each
means, the relevance-overturn decision (available on any card, whatever field it decides,
including its round-2 `adopt` counterpart on a section-C card whose own `decide_field` is
`relevant`), and the constraints on your output (never invent facts beyond the evidence,
don't change `case_id` or `field`, cover every card exactly once). This addendum states only
what is different for round 3.

## This round's composition

250 cards, capped at the round's own budget, drawn from four sections:

- **B. Householder letting by the night** — 1 card. Decide `who_was_letting`, exactly as
  round 1's handoff describes.
- **C. Reader / checker disagreement** — 1 card. Decide whichever field the reader and
  checker disagreed on, exactly as round 2's handoff describes.
- **D. Polarity mixed** — 57 cards. Decide `polarity`, exactly as round 2's handoff
  describes — full opinion text in hand, decide whether the case really is mixed under the
  codebook's definition or should be `favorable`/`adverse`.
- **E. Judged fields erased by the quote gate** — 191 cards, new this round. A field the
  reader answered, but no verbatim quote named it in any quote's `supports`, so the
  mechanical quote gate nulled it before the record ever reached the ledger. Broken down by
  the field each card decides: `under_thirty_days` 132, `owner_freedom_characterization` 46,
  `characterization` 8, `restriction_nature` 3, `holding_summary` 1, `polarity` 1.

Sections A and F are empty this round (A was exhausted in rounds 1/1b; no card queued into F
this time).

## How to decide a section-E card

`decide_field` is the field the quote gate erased — the record's current value for it is
`null`. The card carries two things round 1/2 cards did not both carry together:
`erased_value`, the reader's original answer for that field *before* the gate nulled it
(`tools/export_review_cards.py`'s `attach_erased_values`, read straight from the reader's own
cached response), and the quotes that *did* survive the gate. Your job is to decide, from
those surviving quotes and the holding summary, whether the erased value actually holds up —
the gate did not erase it because the reader was wrong, only because no quote was tagged as
supporting it.

- `set` the field to the erased value shown on the card — when the surviving quotes or the
  holding summary support that value, even though no quote named the field in its `supports`
  list. This is the common case: the reader's original judgment was very often correct; the
  gate is a mechanical citation check, not a correctness check.
- `set` the field to a *different* vocabulary value — when the surviving quotes or the
  holding summary support a value other than the one the gate erased.
- `keep` — leave the field empty. Use this when nothing on the card (neither the surviving
  quotes nor the holding summary) supports any value at all, erased or otherwise; the field
  stays `null`, exactly as the gate left it, but the case still moves into the human-reviewed
  tier, because a reviewer looked at it and made the call that it should stay empty rather
  than genuinely being undecided. `unsure`, below, is the decision for the latter case. `keep`
  writes no value patch — there is nothing to "keep" but the record's own current `null` — and
  otherwise behaves exactly as `keep` does on any other field: a `review.notes` patch
  confirming the (null) value, any `needs-review:<field>` flag it supersedes cleared, and
  `review.status` set to human-adjudicated.
- `unsure` — the card is insufficient to decide either way: the surviving quotes and holding
  summary are silent on this field, and you are not confident enough to affirmatively say the
  field should stay empty. This is the right call whenever the quotes do not settle it — do
  not force a `set` on the strength of the erased value alone if nothing else on the card
  corroborates it, and do not `keep` just because it is the path of least resistance.

E cards carry **no full opinion text** — only the quotes that survived the quote gate and the
holding summary, same as round 1's A/B cards. This is deliberate: 191 of this round's 250
cards are section E, and pulling the full opinion for all of them would make the round far
more expensive to review than the judgment it asks for warrants. It also means `unsure` will
be a materially more common call in section E than it was in round 2's C/D cards, where the
full opinion was in hand — a card whose quotes are silent on the field has no more evidence
available to you than what is on the card, so say so rather than reasoning past it.

Quoted verbatim from the codebook (`domains/str-right-to-let/codebooks/mapper-v3.md`), the
definition and vocabulary for each field this round's E cards decide:

> `under_thirty_days`: `yes` | `no` | `unclear` — whether the occupancy at issue was under
> thirty days.

> `owner_freedom_characterization`: how the court framed the owner's liberty to let:
> `incident_of_ownership` | `regulable_privilege` | `commercial_use` | `not_addressed`.

> `restriction_nature` (adverse records only): `licensing` | `zoning` | `nuisance` |
> `tenant_protection` | `tax` | `other` | `null`.

> `characterization`: how the COURT classified the arrangement: `lease` | `license` |
> `lodging` | `innkeeping` | `other`.

> `holding_summary`: "<= 3 sentences, plain statement of the holding" — free text, no closed
> vocabulary; `set` accepts any string, up to three sentences, that plainly states what the
> court held.

The round's one `polarity` E-card uses the polarity direction and `mixed` rules already given
in round 1's handoff (not repeated here) — the only difference from a round-1/2 polarity card
is that this one arrives with an `erased_value` and no full opinion text.

## The one B card and the one C card

Decide exactly as round 1 (B) and round 2 (C) describe: the B card decides `who_was_letting`
from quotes and holding summary alone; the C card decides whichever field the reader and
checker disagreed on, with the full opinion text in hand (this round exports full text for
sections C and D, same as round 2 — see `--full-text-sections` below).

## The 57 D cards

Decide exactly as round 2's handoff describes: `decide_field` is `polarity`, the full opinion
text is in hand, and the call is whether the case really is `mixed` under the codebook's
definition (both sides holdings, not one holding and one remark) or should be set to
`favorable`/`adverse` to match the real holding.

## The input files

Same shape as round 1/2's exports (`tools/export_review_cards.py`), run with
`--full-text-sections C,D` (so B's one card and every E card carry no `opinion_text`, exactly
as C and D did not in round 2) and with the section-E cards' `erased_value` attached
automatically — the export tool adds it whenever the export contains a section-E card, reading
the run's map manifest, pool batches, and reader cache (all read-only).

## Required output

One JSON object per card, covering all 250 cards in this round's export exactly once — 250
entries, no more, no fewer, no duplicates. Same schema as rounds 1/1b/2
(`{"case_id", "field", "decision": "keep"|"adopt"|"set"|"unsure", "value", "note"}`), plus the
standalone relevance-overturn shape wherever it applies
(`{"case_id", "field": "relevant", "decision": "set", "value": false, "note"}`). Save it to:

```
runs/cycle-004-shard-01/review-round-3-decisions-astra.json
```

## How the human will apply your output

```
.venv\Scripts\python tools\apply_map_review.py --decisions runs\cycle-004-shard-01\review-round-3-decisions-astra.json ^
    --queue runs\cycle-004-shard-01\review-round-3.json --checker runs\cycle-004-shard-01\review-round-3-checker.json ^
    --run-id map-cycle-004-round-3 --assisted-by "GPT Astra" --dry-run
```

`--run-id map-cycle-004-round-3` matters for the same reason it mattered in rounds 1b and 2:
earlier rounds already have patches in the ledger under their own run ids, and the tool
refuses to re-apply under a run id that already has patches. This round needs its own id,
distinct from all of theirs.

The dry run prints every decision against the record's current value without changing
anything, so the human reviews your reasoning card by card — including every `set` on a
section-E card and every `keep` that leaves a field null — before anything is applied. Every
decision is checked against this round's own queue manifest first, exactly as in every prior
round: a `case_id` not among the 250 this round covers, a `field` that is neither the card's
own `decide_field` nor `relevant`, or a value outside the field's own vocabulary is refused by
name before any decision is applied. Once satisfied, the human re-runs the same command
without `--dry-run`, then commits the applied decisions file alongside this handoff.
