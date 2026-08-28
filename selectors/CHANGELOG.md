# Selector history

## v1 seed — 2026-08-28 (planner-cycle-001, pre-review)

29 selectors authored from the spec §6 seed lexicon plus the treatise anchor
harvest: 20 FTS (phrase/NEAR), 4 embedding, 5 of the 29 adverse-candidates
(24-28) plus adverse embedding (29). All `status: active`, all `version: 1`.

PENDING HUMAN REVIEW — no shard run has consumed this file yet (§14 step 3
hard stop). Reviewer attention flagged on:
- boarding-house-keeping-04 / roomers-boarders-14: highest expected hit
  volume; batches are capped but precision unknown.
- "to let" vocabulary (letting-rooms-07): FTS tokenizes "let" normally
  (no stopwords configured), but the term is high-frequency English; phrase
  forms chosen to compensate.
- Embedding selectors (21-23, 29): min_cosine 0.45 / top_k is a first guess;
  tune against gold-set attribution in cycle 2.
- sojourner-19: may be dominated by settlement/poor-law usage; acceptable as
  lexicon probe, review yield before v2.

## v1 approved — 2026-08-28 (human review: user)

Reviewed and approved as authored, with one addition requested by the user:
homestay-bnb-30 ("homestay" family; freq-checked, carried by "bed and
breakfast" 91 hits 1970-2020). 30 active selectors enter cycle-001.
