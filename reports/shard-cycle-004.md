# Cycle 004 shard — `cycle-004-shard-01` (2026-09-04)

First run of the Stage 2B selector engine (`corpus_engine.selector`, engine v2) over the
fully embedded cycle-004 corpus. Launched detached:
`.venv\Scripts\python -u pipeline/shard.py --run-id cycle-004-shard-01`
(logs `runs/shard-cycle-004.log` / `.err`; manifest `runs/cycle-004-shard-01/shard-manifest.json`).

## Plan and run

| | |
|---|---|
| Active selectors | 38 (36 v3 + `citation-graph-38`, `relevance-feedback-39`) |
| Plan units | 946, 0 skips (dry run and real run agree) |
| Coverage rows written | 946 (`coverage_v2` now 1,514 incl. 568 migrated legacy rows) |
| Union chunk matrix | 50 partitions, 13,452,039 rows (memmapped scratch, freed after the run) |
| Wall clock | 11:05 to 11:22 (matrix build ~7 min; 946 units ~10 min) |
| Already-read exclusion | 6,069 case ids (extractions ∪ ledger manifests; sha256 in the manifest) |

## Signals

40,115 signals on 29,996 distinct cases (previous four runs combined: 22,516 signals).

| Selector | Signals |
|---|---|
| relevance-feedback-39@v1 | 12,328 |
| embed-householder-letting-21@v2 | 10,163 |
| embed-zoning-paying-occupants-22@v2 | 5,683 |
| adverse-embed-regulation-29@v1 | 4,618 |
| embed-short-letting-23@v1 | 2,626 |
| citation-graph-38@v1 | 1,577 |
| roomers-boarders-14@v1 | 691 |
| incident-of-ownership-11@v1 | 642 |

Cases by jurisdiction: N.Y. 4,157 · Cal. 3,609 · Mass. 3,241 · N.J. 3,198 · Pa. 3,148 ·
Ohio 3,079 · Tex. 3,043 · La. 2,719 · Conn. 2,502 · D.C. 1,300.
Cases by era: pre-1860 3,813 · 1860-1900 5,014 · 1900-1930 5,916 · 1930-1970 7,489 ·
1970-2020 7,764. **The pre-1860 cell is no longer empty at the candidate stage.**

## Batches

1,845 batches of up to 18 cases → **32,795 cases to map** (`runs/cycle-004-shard-01/batches/`).
Mapping waits on Stage 3 (reader driver, reader-model measurement) and on a budget the
user approves.

## Recall gate (development gold; ADR-0003 held-out split not yet built)

| Tier | v3 baseline | cycle-004 | |
|---|---|---|---|
| brief-letting (headline) | 6/9 | **6/9** | unchanged |
| treatise | 22/29 | **24/29** | +2 |
| brief-all | 17/63 | **20/63** | +3 |

Non-decreasing on every tier: **PASS**. Misses unchanged: Smith v. Decker (2255813),
Latimer v. Hess (10223945) — both pending the relevance/doctrine re-tag noted in the
handoff — and Ruhl v. Kauffman & Runge (2204609).

## Observations for the planner

- `relevance-feedback-39` returned 12,328 cases ≈ `top_k` 250 in 49 of 50 partitions:
  the `min_cosine` 0.40 threshold is not binding on the 4B index. Either the cap or the
  threshold should be re-tuned before this pool is mapped, or the pool ranked (Stage 2C).
- The five vector selectors contribute 35,418 of the 40,115 signals; lexical selectors
  contribute little outside the four original states because their coverage rows were
  migrated (already covered) and only the six new jurisdictions ran.
- 32,795 candidates is ~4x the previous largest shard; the precision trend (28% → 12% →
  6.6%) argues for ranking before mapping rather than mapping everything.
