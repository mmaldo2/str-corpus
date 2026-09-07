# Cycle-004 map review, round 1 — handoff for a first pass

You are doing a first pass on 150 case-law records for a legal-history corpus project
tracking the historical right of a property owner to let rooms or a dwelling short-term.
This document is self-contained: you do not have access to the project's repository, only
the two files described below and this one.

## Purpose

Every record here has already been read by a machine reader and, on 150 of them, by a
second machine reader from a different model family (the "checker"). A human reviewer will
make the final call on each record, but wants a first pass drafted for them: for every card,
propose a decision and write one line of reasoning. The human will read your reasoning and
either accept it or override it — you are doing triage, not final adjudication. Nothing you
write is applied to the project's records directly; it is confirmed, case by case, by a
human before anything changes.

## The input files

**`review-round-1-cards.json`** — a JSON array of 150 objects, one per card. Read this one
programmatically. Each object has:

- `case_id` — the record's numeric id.
- `section`, `section_title` — which of six queues the card fell into and why (see below).
- `name`, `cite`, `court`, `jurisdiction`, `year` — the case's identity. `name` is often
  `null`; older reporters did not always preserve a case caption.
- `decide_field` — the ONE field this card asks you to decide. Every card decides exactly
  one field; do not decide any other field on the same record.
- `reader` — the first machine reader's answers on eight fields: `relevant`, `polarity`,
  `who_was_letting`, `duration_of_occupancy`, `characterization`, `under_thirty_days`,
  `owner_freedom_characterization`, `restriction_nature`. This is the value that stands
  unless you decide otherwise.
- `checker` — the second reader's answers on three of those fields (`relevant`, `polarity`,
  `characterization`), or `null` if the card has no second opinion for `decide_field`
  (adopting is then not available; see below).
- `holding_summary` — a plain-language statement of what the court held, written by the
  first reader.
- `quotes` — verbatim passages the reader extracted from the opinion, each with a `supports`
  list naming which fields that passage backs. These are the only evidence you have; you
  were not given the full opinion text.
- `nulled_fields` — fields the reader answered but a mechanical check erased because no
  quote supported them. A card in section E decides one of these.
- `other_reasons` — other queues this same record also qualified for, informational only.
- `courtlistener_url` — a search link for the case on CourtListener, for a spot check if you
  have web access. Not required to make a call.

**`review-round-1-cards.md`** — the same 150 cards as readable prose, one heading per card,
grouped by section. Use this if you are reading rather than parsing; it carries the same
facts as the JSON, nothing more.

### The six sections

A record appears once, in the highest-priority section it qualifies for:

- **A. Favorable and under thirty days** — the reader called the case favorable to the
  owner's right to let, in a dispute about occupancy under thirty days. This is the central
  claim the corpus exists to support, so these cards decide `polarity`.
- **B. Householder letting by the night** — a householder (not a commercial operator)
  letting rooms by the night, the closest historical analogue to a short-term rental. Decide
  `who_was_letting`.
- **C. Reader / checker disagreement** — the two readers answered differently on relevance,
  polarity, or characterization. Decide whichever of those fields they disagreed on.
- **D. Polarity mixed** — the reader could not put the case cleanly on one side. Decide
  `polarity`.
- **E. Judged fields erased by the quote gate** — the reader answered a field but no
  verbatim quote backed it, so a mechanical check nulled it. The value shown is what
  survived, not what the reader originally said. Decide the nulled field.
- **F. Fuzzy quote match** — the reader's supporting quote matched the opinion only
  approximately, more than routine OCR noise would explain. Decide `quotes`: is the
  underlying claim still trustworthy, or does it need a full re-read?

Round 1 populated only sections A (126 cards) and B (24 cards); no card in this round
decides relevance directly by section, but relevance is nonetheless the live dispute this
round turns on — see below.

## The judgment rules

These are the rules the machine readers were themselves instructed to apply, copied
verbatim from the project's codebook (`mapper-v3`). Apply the same rules to the same
question when you decide a card.

**Polarity direction** (this is the single most load-bearing rule in the whole project —
read it twice):

> POLARITY IS JUDGED FROM THE PROPERTY OWNER'S RIGHT TO LET — never from the
> occupant's interests. A ruling that expands an occupant's or tenant's
> rights AGAINST the owner (rent control, eviction protection, "permanent
> tenant" status, statutory tenancy, habitability duties) is ADVERSE unless it
> also affirms the owner's freedom to let. "Pro-tenant" is not "favorable."
> Favorable means the owner's liberty to let, on the owner's terms, was
> recognized, protected, or assumed as lawful.

**Mixed:**

> Mixed means the same opinion both recognizes the owner's freedom to let on
> one point and restricts it on another, and both are holdings rather than
> remarks in passing. If only one side is a holding, follow the holding and
> note the tension in the summary. An owner who wins on a ground unrelated to
> letting is not favorable; judge only what the court decided about letting.

**Relevance** (the field in live dispute — see below):

> `relevant`: does the case bear on compensated occupancy of another's
> dwelling/rooms, its legal character, or its regulation? Procedural cases
> that merely mention a boarding house in passing are `false`.

**Vocabularies** — the closed set of values each field may take:

- `polarity`: `favorable` | `adverse` | `mixed` | `null` (null only when the case is not
  relevant).
- `who_was_letting`: `householder` (owner/family letting part of their own dwelling) |
  `commercial_operator` (business: hotel, boarding house run as enterprise, multiple
  properties) | `non_resident_owner` (owner of a single dwelling who does not live there) |
  `unclear`.
- `duration_of_occupancy`: `nights` | `weeks` | `months` | `unclear` — the occupancy actually
  at issue, from the facts.
- `characterization`: how the COURT classified the arrangement — `lease` | `license` |
  `lodging` | `innkeeping` | `other`.
- `under_thirty_days`: `yes` | `no` | `unclear` — whether the occupancy at issue was under
  thirty days.

Two glossary entries from the project's domain reference (`CONTEXT.md`), stated the same way
the human reviewer thinks about them:

> **Polarity**: Whether a case is favorable, adverse, or mixed for the owner's right to let.
> Judged from the owner's side only. An outcome that protects an occupant against the owner
> is adverse. Mixed means the same opinion both recognizes the owner's freedom to let on one
> point and restricts it on another, and both are holdings rather than remarks in passing; an
> owner who wins on a ground unrelated to letting is not favorable. A case the reader finds
> irrelevant carries no polarity.

> **Who was letting**: Householder, non-resident owner, commercial operator, or unclear.

> **Review tier**: Whether a ledger record's judgments have been confirmed by a human
> (human-reviewed) or rest on machine readers only (machine-only). Every count is reported by
> tier, never blended.

That last one is why this pass matters: your draft decision does not move a record into the
human-reviewed tier by itself. Only the human's confirmation does. Your job is to make that
confirmation fast and well-reasoned, not to substitute for it.

## The decision you are making, per card

Each card gives you `reader` (the first reader's value) and, where available, `checker` (the
second reader's value) for `decide_field`. You choose exactly one of four decisions:

- `keep` — the reader's value stands. Use this when the quotes and holding support what the
  reader said.
- `adopt` — take the CHECKER's value shown on the card. Only available when `checker` is not
  `null` for this field. Use this when the second reader's answer is the better-supported
  one.
- `set` — write a specific value from the field's vocabulary (above), different from both
  reader and checker. Use this when neither answer is right but the quotes support a third
  value.
- `unsure` — flag the card for a full read instead of deciding it. Use this when the quotes
  genuinely do not settle the question one way or the other. This is not a failure; a
  card whose evidence is inconclusive should say so rather than force an answer.

`decide_field` on the card tells you which field your decision is about — never decide a
different field, even if you notice something else looks wrong on the same record; that is
outside this pass's scope.

## The live dispute this round: relevance

The checker disagrees with the first reader about relevance on 46 of the 150 cards in this
round — the checker says "not a letting case" where the reader said "relevant." This is the
single largest source of disagreement in the round, larger than any disagreement over
polarity or characterization, so weigh it carefully wherever it shows up (mainly as a
`checker` value of `relevant: false` sitting beside a `reader` value of `relevant: true`,
even though the card's own `decide_field` may be `polarity` or another field — a card whose
relevance is in question is a card whose polarity call rests on shakier ground).

Reason about it the way the codebook does: relevance is not about whether the case mentions
lodging, boarding, or renting in passing. It asks whether the case bears on compensated
occupancy of another's dwelling or rooms, its legal character, or its regulation. A landlord-
tenant dispute over rent collection procedure that happens to involve a boarding house is not
automatically relevant; a case that turns on whether an occupant was a lodger, a tenant, or a
licensee — or on whether a letting practice could be licensed, zoned, or taxed — is. When a
card's quotes describe the facts of a letting arrangement and the holding turns on it, treat
the case as relevant even if the reader used incidental procedural language elsewhere. When
the quotes show the letting is peripheral to what the court actually decided, side with the
checker.

## Required output

Produce a single JSON file: a list of exactly 150 objects, one for every card in
`review-round-1-cards.json`, each covering that card exactly once. Each object:

```json
{"case_id": 43707, "field": "polarity", "decision": "keep", "value": null,
 "note": "quote confirms the owner's liberty to let was recognized and unrestricted"}
```

- `case_id` — copy from the card. Do not change it.
- `field` — copy the card's `decide_field`. Do not change it, and do not answer a field the
  card did not ask about.
- `decision` — one of `keep`, `adopt`, `set`, `unsure`.
- `value` — `null` unless `decision` is `set` (then a value from the field's vocabulary) or
  `adopt` (then the checker's value shown on the card, for your own bookkeeping — the tool
  that applies your file re-derives this from the checker file itself, so getting it exactly
  right is a courtesy to the human reader, not load-bearing).
- `note` — one line of reasoning, citing the specific quote or the holding summary that
  drove your call. Not a restatement of the decision; say WHY.

Three worked examples, one of each shape you will use most:

```json
[
 {"case_id": 43707, "field": "polarity", "decision": "keep", "value": null,
  "note": "the innkeeper quotes describe the owner's own reasonable rules as lawful and no restriction on the right to let is at issue"},
 {"case_id": 178133, "field": "polarity", "decision": "adopt", "value": null,
  "note": "checker's relevant:false is right - the holding turns on a procedural point unrelated to letting, per the quotes"},
 {"case_id": 890424, "field": "who_was_letting", "decision": "unsure", "value": null,
  "note": "the quotes describe rent collection but never say who owned or occupied the property, so householder vs. commercial cannot be told from what's given"}
]
```

## Constraints

- Never invent facts beyond what the card's quotes and holding summary say. If the quotes do
  not support a call, the call is `unsure`, not a guess dressed as confidence.
- Do not change `case_id` or `field` from what the card gives you.
- Cover every card exactly once — no duplicates, no omissions. 150 cards in, 150 decisions
  out.
- Do not decide a field the card did not ask about, even if you notice a problem with
  another field on the same record.
- `adopt` is only valid when the card's `checker` value for `decide_field` is not `null`.
  Where it is `null`, choose `keep`, `set`, or `unsure` instead.

## How the human will use your output

Save your JSON list to a file, then the human runs:

```
.venv\Scripts\python tools\apply_map_review.py --decisions <your-file.json> \
    --assisted-by "GPT Astra" --dry-run
```

This prints every decision against the record's current value without changing anything, so
the human can review your reasoning card by card before anything is applied. Every decision
you drafted is checked against the round's own queue manifest first — a `case_id` not
actually queued this round, or a `field` that does not match the card's `decide_field`, is
refused by name before any of your decisions are applied, so a mistake in your file cannot
silently answer the wrong question. Once satisfied, the human re-runs the same command
without `--dry-run`. `--assisted-by "GPT Astra"` marks every applied decision's record with a
note that it was first-pass drafted by you and confirmed by the reviewer, so the project's
human-reviewed tier stays honest about which decisions had model assistance.
