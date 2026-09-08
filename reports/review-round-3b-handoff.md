# Cycle-004 map review, round 3b — handoff for a first pass (full text)

Read `review-round-1-handoff.md` and `review-round-3-handoff.md` first; this addendum changes
only what follows.

## What this round is

148 cards from round 3 that could not be settled from quotes and a holding summary alone:
55 where the first pass proposed that the case is not a letting case, and 93 marked unsure
(91 of them erased-field cards). Every card in this round now carries the FULL opinion text
(`opinion_text`), so relevance can be judged the way round 1b judged it.

Files: `review-round-3b-cards.json` (148 cards, full text) and
`review-round-3b-cards-part1.md` .. `-part6.md`.

## How to decide

- First decide relevance from the full text, using the codebook definition quoted in the
  round-1 handoff. If the case does not bear on compensated occupancy of another's dwelling or
  rooms, its legal character, or its regulation, output
  `{"case_id": ..., "field": "relevant", "decision": "set", "value": false, "note": ...}`
  and nothing else for that card. A prior proposal to overturn is not evidence; decide afresh.
- Otherwise decide the card's own `decide_field` as in round 3: for an erased field, `set` the
  erased value when the opinion supports it, `set` a different vocabulary value when it supports
  that, `keep` to leave the field empty when the opinion is silent on it; for a mixed card, keep
  mixed only if both sides are holdings, else `set` favorable or adverse.
- `unsure` should now be rare; use it only when the opinion itself leaves the question open.

## Output

One entry per card, 148 entries, to
`runs/cycle-004-shard-01/review-round-3b-decisions-astra.json`. Same JSON shape as before.
The human confirms each call; apply is
`tools/apply_map_review.py --decisions <file> --queue runs/cycle-004-shard-01/review-round-3b.json --run-id map-cycle-004-round-3b --assisted-by "GPT Astra"`
(dry run first).
