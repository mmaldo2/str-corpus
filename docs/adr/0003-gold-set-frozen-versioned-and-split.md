---
status: accepted
date: 2026-09-01
---

# The gold set is frozen as version 1, every re-tag is logged, and it is split into development and held-out halves

The headline recall denominator had shrunk from 15 to 9 cases through
re-tagging, all 9 came from a single litigation (Zaatari), and two of the
three remaining misses were themselves proposed for re-tagging. Selectors
were being tuned against the same cases recall was reported on. We decided
to freeze the current gold set as version 1; treat every later re-tag as a
versioned, logged event with a stated reason; designate the Zaatari-derived
entries as the development set; and build a held-out set, never used for
tuning, from the RECAP district-court briefs, the historical citations in
the federal STR opinions themselves, and a random half of the treatise
anchors.

## Considered options

- Random split of the existing set: would place already-tuned-on cases in
  the held-out half.
- No split, broaden only: leaves the circularity intact.

## Consequences

Recall claims cite the held-out set. The development set may keep shrinking
through honest re-tags without that ever improving the reported number.
The treatise tier remains reported separately because those cases also seed
the lexicon (spec amendment A9).
