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

## v2 — cycle 002 (planner-cycle-002) — PENDING HUMAN REVIEW

From cycle-001 discoveries and gold-miss postmortems:
- NEW housekeeping-unit-31 (zoning term of art, Long Beach line)
- NEW boarding-variants-32 (worker-observed period variants)
- NEW zoning-power-residence-33 (adverse; Spann/Lombardo gold-miss fix)
- tourist-home-15 v1->v2: + tourist camp/cabin/lodge/house, auto camp,
  motor court ("motel" excluded for precision; revisit if under-covered)
- embed-zoning-paying-occupants-22 v1->v2: top_k 250, min_cosine 0.43
  (gold-miss fix for dense Texas partitions)
33 active selectors (2 retired). Recall gate: shard recall must be
non-decreasing vs cycle-001 baseline (brief-letting 33.3%, treatise 72.4%).

(v2 approved by user 2026-08-30 with Map budget 150 batches.)

## v3 — cycle 003 (planner-cycle-003) — PENDING HUMAN REVIEW

- NEW apartment-hotel-34 (neutral; Hancock v. Rand line)
- NEW sro-35 (adverse; modern regulatory stratum)
- NEW motel-near-36 (neutral; proximity solves the motel flood)
- NEW rent-houses-37 (favorable; Holmes/Coalson postmortem — period Texas
  vernacular "rent houses")
- embed-householder-letting-21 v1->v2: top_k 250, floor 0.43 (Gouhenant/
  Ruhl misses buried in long non-letting opinions)
- RETIRED sojourner-19 (near-zero yield, proper-name noise)
Recall gate: non-decreasing vs post-hygiene baseline (brief-letting 3/9 =
33.3%; treatise 72.4%).

(v3 approved by user 2026-08-31 with Map budget 150 batches.)
v3 recall gate PASSED (2026-08-31): brief-letting 3/9 -> 6/9 (66.7%),
treatise 21/29 -> 22/29 (75.9%), brief-all 14/63 -> 17/63. Gouhenant and
Holmes/Coalson recovered (rent-houses-37 + embed-21 v2). Remaining misses:
Smith v. Decker, Latimer v. Hess (no letting vocabulary), Ruhl.
