# Cycle-004 map review, round 4 — handoff addendum (the last round of cycle 004)

Read `review-round-1-handoff.md`, `review-round-3-handoff.md` and `review-round-3b-handoff.md`
first; this addendum changes only what follows and does not repeat their rules (the four
decisions, the polarity/mixed/relevance definitions and vocabularies, the relevance-overturn
path available on any card, or how a section-E card's `erased_value` is decided).

## This round's composition

258 cards, drawn from two sections plus one leftover D card:

- **D. Polarity mixed** — 1 card. Decide `polarity`, exactly as round 2/3's D cards.
- **E. Judged fields erased by the quote gate** — 228 cards, broken down by the field each
  card decides: `under_thirty_days` 152, `owner_freedom_characterization` 63,
  `characterization` 7, `restriction_nature` 6.
- **F. Fuzzy quote match** — 29 cards, new this round (F was empty in round 3). Decide
  `quotes`.

Sections A, B and C are empty this round.

Unlike round 3 (where B's one card and every E card carried no `opinion_text`) and round 3b
(full text only for the 148 held-out cards), **every card in round 4 carries the full opinion
text**, D and F included. Round 3's lesson was that quotes alone settled almost nothing on the
E cards that came back unsure — 91 of round 3b's 148 held-out cards were erased-field cards —
so this round does not repeat that experiment: every card gets the full opinion from the start.

## The 228 E cards

Decide exactly as round 3b's E cards: from the full opinion text (not just the surviving
quotes), first decide relevance, then decide the erased field —

- If the opinion does not bear on compensated occupancy of another's dwelling or rooms, its
  legal character, or its regulation, overturn relevance
  (`{"field": "relevant", "decision": "set", "value": false, "note": ...}`) and output nothing
  else for that card.
- Otherwise, decide the card's own `decide_field`: `set` the erased value shown on the card
  when the opinion supports it, `set` a different vocabulary value when the opinion supports
  that instead, or `keep` to leave the field empty when the opinion is silent on it even with
  the full text in hand. `unsure` should be rare with full text available — use it only when
  the opinion itself leaves the question genuinely open.

## The one D card

Decide exactly as round 2/3's D cards: `polarity`, full text in hand, `mixed` only if both
sides are real holdings, else `favorable`/`adverse`.

## The 29 F cards — fuzzy quote match

Each F card shows two things: the reader's own quote (in `quotes`, the same shape every card
carries) and, separately, a `fuzzy` block — one entry per quote the mechanical gate matched
only approximately, each carrying that quote's `text` again, `source` (the closest passage the
gate actually found in the opinion, the window it scored the match against), `classification`
(the gate's own trivial-ocr / needs-human call), `quote_coverage`, and `auto_accepted`. Every F
card in this round has `auto_accepted: false` on at least one fuzzy entry — that is why a human
is looking at it at all; a card can still carry a *second*, already `auto_accepted: true` entry
alongside it (one case this round does), and that one is not yours to decide.

With the full opinion text also on the card this round, do not stop at the `source` window —
read the passage in context in `opinion_text` before deciding.

- `keep` — the quote is a faithful rendering of the opinion's passage: OCR noise, punctuation
  differences, a dropped or transposed word, nothing that changes what the passage says. The
  quote and everything it supports stand unchanged.
- `set`, value = the quote's own exact text (copied verbatim from the card, not paraphrased),
  when the passage differs in substance from what the quote claims, or the passage does not
  exist in the opinion at all — the quote is not a real match and should be dropped. A card
  with more than one fuzzy entry needing a decision may pass a list of the exact texts to drop
  instead of a single string; do not include an entry whose own `auto_accepted` was already
  `true` — that one was never queued for a decision. Dropping a quote also silently drops
  whatever judged field that quote alone supported (the ledger's own cascade), so read what a
  quote supports before deciding.
- `unsure` — the full opinion still does not settle whether the passage is a faithful match
  (e.g. the reporter page is missing or illegible at that point) — send it back rather than
  guessing.
- The relevance-overturn path is available here exactly as on any other card, whatever its own
  `decide_field`: an F card's fuzzy quote is not the only thing worth a second look once the
  full opinion is in hand.

`adopt` is not offered on an F card: the checker never answers `quotes` (its three fields are
`relevant`, `polarity`, `characterization`), so no F card carries a checker value to adopt.

## Input files and full-text export

Same shape as round 3b's export (`tools/export_review_cards.py`), run with no
`--full-text-sections` restriction — every card gets `opinion_text` — and `--chunks` so the
output stays readable:

```
.venv\Scripts\python tools\export_review_cards.py --queue runs\cycle-004-shard-01\review-round-4.json ^
    --full-text --chunks 12 --out-stem reports\review-round-4-cards
```

(~258 cards, mean opinion length ~15k characters, so `--chunks 12` keeps each part under
roughly 350 KB.) A section-E card's `erased_value` is attached automatically, same as rounds 3
and 3b; an F card's `fuzzy` block (above) is attached automatically for every F card, same as
every other field the export has always carried straight from the queue manifest.

## Required output

One JSON object per card, covering all 258 cards in this round's export exactly once — 258
entries, no more, no fewer, no duplicates. Same schema as every prior round
(`{"case_id", "field", "decision": "keep"|"adopt"|"set"|"unsure", "value", "note"}`), plus the
standalone relevance-overturn shape wherever it applies. Save it to:

```
runs/cycle-004-shard-01/review-round-4-decisions-astra.json
```

## How the human will apply the output

```
.venv\Scripts\python tools\apply_map_review.py --decisions runs\cycle-004-shard-01\review-round-4-decisions-astra.json ^
    --queue runs\cycle-004-shard-01\review-round-4.json --run-id map-cycle-004-round-4 ^
    --assisted-by "GPT Astra" --dry-run
```

`--checker` is left to its documented default (`<queue>-checker.json`, i.e.
`runs/cycle-004-shard-01/review-round-4-checker.json`) rather than named explicitly. `--run-id
map-cycle-004-round-4` is its own id, distinct from every earlier round's, for the same reason
it mattered in rounds 2, 3 and 3b: the tool refuses to re-apply under a run id that already has
patches in the ledger.

The dry run prints every decision against the record's current value before anything is
applied, including every `drop_quote` an F-card `set` writes and every `set`/`keep` on a
section-E card. Every decision is checked against this round's own queue manifest first, exactly
as in every prior round. Once satisfied, the human re-runs the same command without `--dry-run`,
then commits the applied decisions file alongside this handoff — the last round of cycle 004.
