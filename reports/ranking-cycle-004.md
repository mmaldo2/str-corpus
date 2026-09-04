# Cycle-004 ranking: re-pack, metrics, score distribution

**Date:** 2026-09-04. **Run:** `cycle-004-shard-01` (946 units, 40,115 signals,
32,795 unread candidate pool). **Shipped ranker:** `classifier:v1`
(`data/ranker/v1/model.npz`, digest `a489a2dc960adb5b`, trained at commit `5674128`).

## 1. What ran

`.venv\Scripts\python pipeline\rank.py --run-id cycle-004-shard-01` scored the full pool
with `classifier:v1`, wrote one `rankings` row per pool case, and rewrote
`runs/cycle-004-shard-01/batches/` in ranked order.

```
classifier:v1: 1845 batches, 32795 cases -> runs\cycle-004-shard-01\batches (6069 already-read excluded)
```

- Batches: 1,845 (unchanged from the shard).
- Cases packed: 32,795.
- Already-read excluded: 6,069.
- `runs/cycle-004-shard-01/shard-manifest.json` gained:
  `"ranker": {"digest": "a489a2dc960adb5b", "ranker_id": "classifier:v1", "reranked_at": "2026-09-04T14:52:59"}`.
- Every batch JSON carries top-level `"ranker_id": "classifier:v1"` and per-case
  `"rank_score"`.

### Before / after verification (read-only)

| Check | Before | After | Expected |
|---|---|---|---|
| `signals` rows, `run_id='cycle-004-shard-01'` | 40,115 | 40,115 | unchanged |
| `coverage_v2` rows | 1,514 | 1,514 | unchanged |
| `rankings` rows | table did not exist (`ensure_schema`/`migrate` creates it) | `classifier:v1`: 32,795 | one row per pool case for the ranker used |

`signals` and `coverage_v2` were untouched by the re-pack, as required by the design
(`docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md` §7).

## 2. Metrics table (held-out, n=1,533)

From `data/ranker/v1/manifest.json` (fusion, classifier) and
`data/ranker/reranker-22e6836/manifest.json` (reranker, delta vs. classifier baseline):

| Ranker | ap_all | ap_reviewed | p50_all | p200_all |
|---|---|---|---|---|
| fusion:v1 | 0.3775 | 0.1251 | 0.700 | 0.345 |
| **classifier:v1 (shipped)** | **0.6942** | **0.3238** | **0.920** | **0.600** |
| qwen3-reranker-4b:22e6836 | 0.4983 | 0.1570 | 0.740 | 0.465 |
| reranker delta vs. classifier | -0.1959 | -0.1669 | -0.180 | -0.135 |

n_all = 1,533; n_reviewed = 1,386 (human-reviewed subset) for all three rows.

### Ship rule and bar

- **Ship rule (§5.4):** `classifier:v1` becomes the domain default only if its held-out AP
  exceeds fusion's on both views (all labels, human-reviewed only). It does on both
  (0.6942 > 0.3775 all; 0.3238 > 0.1251 reviewed) — `ranking.default` was set to
  `classifier` (i.e. `classifier:v1`) at commit `823ad24`.
- **Reranker bar (§6):** the reranker becomes the default only if its held-out AP beats the
  shipped default by >= 0.05 absolute on both views. It does not — it is **worse** than
  `classifier:v1` on every metric (`clears_bar: false`, `bar_ap_delta: 0.05`,
  digest `931368aef90230b4`). The reranker is measured and recorded, not shipped; the pool
  was not reranked.

## 3. Per-cell held-out AP, shipped ranker (top 10 cells by n)

From `data/ranker/v1/manifest.json` -> `metrics.classifier.per_cell`:

| Cell | n | ap | p50 |
|---|---|---|---|
| 1900-1930\|N.Y. | 270 | 0.6862 | 0.480 |
| 1860-1900\|N.Y. | 223 | 0.7608 | 0.500 |
| 1900-1930\|La. | 140 | 0.5792 | 0.160 |
| 1900-1930\|Pa. | 122 | 0.7187 | 0.120 |
| 1860-1900\|Pa. | 118 | 0.3998 | 0.060 |
| 1860-1900\|Tex. | 104 | 0.3333 | 0.060 |
| 1860-1900\|La. | 93 | 0.3149 | 0.060 |
| 1930-1970\|Tex. | 78 | 0.5054 | 0.180 |
| 1930-1970\|N.Y. | 50 | 0.9052 | 0.340 |
| 1970-2020\|N.Y. | 50 | 0.6596 | 0.360 |

The held-out slice only covers 4 of the pool's 10 jurisdictions (Tex., Pa., La., N.Y.) —
it was frozen against the labelled-read population as it existed when
`tools/build_ranker_heldout.py` ran, before the cycle-004 jurisdiction expansion added six
more: Cal., Mass., N.J., Ohio, Conn., D.C. (verified read-only against the live pool:
`SELECT DISTINCT c.jurisdiction FROM rankings r JOIN cases c ON c.case_id=r.case_id WHERE
r.ranker_id='classifier:v1'` returns exactly these ten). AP for the six newly-added
jurisdictions has no held-out coverage yet; treat their pool scores as extrapolated from
the same model, not separately validated.

## 4. Pool score distribution — `classifier:v1`, all 32,795 pool cases

Deciles of `rankings.score` (`ranker_id='classifier:v1'`), read-only query against
`data/db/corpus.db`:

| Percentile | Score |
|---|---|
| 0th (min) | 0.000000 |
| 10th | 0.002202 |
| 20th | 0.006423 |
| 30th | 0.014058 |
| 40th | 0.026347 |
| 50th (median) | 0.046326 |
| 60th | 0.080827 |
| 70th | 0.142270 |
| 80th | 0.258646 |
| 90th | 0.508222 |
| 100th (max) | 0.999997 |

Mean score: 0.1538. The distribution is heavily right-skewed — half the pool scores below
0.05, and only the top decile clears 0.51 — consistent with the shipped classifier's high
`p50`/low `p200` profile on held-out data (it front-loads precision into a small top slice
rather than spreading score mass evenly).

## 5. Batches by mean rank_score, per era (for map-budget selection)

Computed from the 1,845 batch JSON files' per-case `rank_score` (mean per batch), against
thresholds 0.5 and 0.25:

| Era | Batches | mean > 0.5 | mean > 0.25 |
|---|---|---|---|
| pre-1860 | 244 | 13 | 32 |
| 1860-1900 | 233 | 16 | 32 |
| 1900-1930 | 316 | 27 | 59 |
| 1930-1970 | 519 | 74 | 139 |
| 1970-2020 | 533 | 55 | 111 |
| **Total** | **1,845** | **185** | **373** |

A batch is 18 cases. Reading every batch whose mean rank_score exceeds 0.25 (373 batches,
~6,714 cases) would cover roughly a fifth of the pool while concentrating on the
highest-scoring material in every era; the 0.5 cut (185 batches, ~3,330 cases) is a
tighter, higher-confidence slice. Map budget should be set per cell from this table plus
the per-cell held-out AP in §3, not as one global cutoff — 1930-1970 and 1970-2020 alone
hold 70% of the batches clearing 0.25. Per the §3 caveat, cells in the six jurisdictions
added in the cycle-004 expansion (Cal., Mass., N.J., Ohio, Conn., D.C.) have no held-out
AP at all — their budgets in this table should be set more conservatively than the
four held-out-covered jurisdictions until they get their own validation.

## 6. Recorded decisions

### (a) Spec §4 amendment: features from the union of a case's signals across runs

The design's §4 "Same run for both sides" paragraph said training, held-out evaluation,
and scoring features would all come from the signals of the run being ranked (`run_id`
alone). The shipped implementation does not do this: `corpus_engine/ranker/features.py`'s
`case_features(conn, case_ids, layout, ...)` queries `signals` by `case_id` with no
`run_id` filter — the union across all runs.

This was necessary for two independent reasons:

1. **The batch pool is not self-contained.** `cycle-004-shard-01`'s own signals
   (`run_id='cycle-004-shard-01'`) do not cover every case in its own pool. A live,
   read-only query against the pool used for this re-pack found **5,606 of the 32,795**
   unread pool cases carry no `cycle-004-shard-01` signal at all — only signals from
   cycles 001-003 (the working plan carried a working estimate of 2,799 for this figure;
   the verified count at report time was higher — see the note below). Scoping feature
   extraction to `run_id` would zero out every feature for those cases, degrading their
   scores to the missing-indicator default regardless of what an earlier cycle's
   selectors actually found for them.
2. **Every labelled read carries signals from its own cycle only.** A case read and
   adjudicated under cycle 002, for example, has `signals` rows under
   `run_id='cycle-002-shard-01'`, never under `cycle-004-shard-01`. A `run_id`-scoped
   query at training time would find zero features for essentially the entire labelled
   set when scoring against `cycle-004-shard-01`, which is not usable.

The union keeps one feature-computation code path shared by training, held-out
evaluation, and live scoring (as the design intended), at the cost that a case's features
now reflect whichever selectors have ever been run over it, not only the selectors of the
run currently being packed. This amendment is recorded in
`docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md` §4, dated
2026-09-04, directly after the paragraph it supersedes.

**Note on the 2,799 vs. 5,606 discrepancy.** The task brief supplied 2,799 as the count of
pool cases carrying only cycle 001-003 signals. A read-only re-derivation at report time
(pool = the 32,795 `rankings` rows for `ranker_id='classifier:v1'`; signal run coverage
from `signals.run_id`, distinct values `{cycle-001-shard-01, cycle-001-shard-02,
cycle-002-shard-01, cycle-003-shard-01, cycle-004-shard-01}`) found 5,606 pool cases with
no `cycle-004-shard-01` signal, and confirmed all 32,795 pool cases have at least one
`signals` row (0 with none). The qualitative conclusion — the union-of-runs amendment is
required — holds regardless of which figure is correct; the amendment paragraph and this
report both carry the live, verified figure and flag the discrepancy for the record.

### (b) Environment debt: scikit-learn deprecation, no dependency pin

The installed `scikit-learn` is 1.9.0. `LogisticRegression(penalty="l2", ...)` as used by
`corpus_engine/ranker/classifier.py` relies on the `penalty=` constructor argument, which
scikit-learn has deprecated and scheduled for removal in 1.10. `requirements.txt` in this
repo pins `eyecite`, `httpx`, `lxml`, `numpy`, `pytest`, `PyYAML`, `RapidFuzz`, and
`selectolax`, but does **not** list `scikit-learn` at all — there is no dependency pin for
it today, so a fresh environment build could silently pick up scikit-learn >= 1.10 and
break `train()`/`ClassifierRanker` construction on the removed argument.

**Recommendation:** when a dependency entry for `scikit-learn` is introduced in
`requirements.txt` (or any future `pyproject.toml` dependency list), pin it
`scikit-learn<1.10` until `classifier.py` is updated for the new API, and track the
migration as a follow-on so the pin can eventually be lifted.

## 7. Files touched by this task

- `runs/cycle-004-shard-01/batches/*.json` — rewritten in ranked order (1,845 files).
- `runs/cycle-004-shard-01/shard-manifest.json` — gained `"ranker"`.
- `data/db/corpus.db` — `rankings` table created (schema already present via
  `ensure_schema`/`migrate`) and populated with 32,795 rows for `classifier:v1`;
  `signals` and `coverage_v2` untouched.
- `reports/ranking-cycle-004.md` — this report.
- `reports/handoff-cycle-004.md` — item 11 gained the ranking sentence.
- `docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md` — §4 amendment.
- `README.md` — `pipeline\rank.py` line added under the shard line.
