# The cycle-004 tail map (shard 02): 3,006 cases under a fixed budget on classifier v2

Date: 2026-09-09. Run id `cycle-004-shard-02`. Spec: docs/superpowers/specs/2026-09-08-stage-3b-slice-3-ranker-v2-tail-map-reread-design.md (sections 5 and 8, decisions D4-D6). Companions: reports/ranking-v2.md (the ranker), reports/map-cycle-004.md (shard 01, the first 6,831 cases of this cycle).

## 1. What ran

- **Ordering.** The 25,955 unread cases of the cycle-004 pool (32,795 packed into shard 01, minus the 6,840 that shard 01 read) were re-scored by **classifier v2** and re-packed into 1,465 batches of 18 in descending score (`pipeline/rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01 --exclude-read`; shard-manifest.json records the source run, the excluded ids and the ranker digest `95ab3005979b3f6f`). v2 ships by D6 (average precision 0.8274 against fusion's 0.7860 on held-out v2, both views); it trailed classifier v1 by 0.0045 on that slice, and the user chose to ship it on 2026-09-08 because 32 of the slice's 293 rows were in v1's training data (reports/ranking-v2.md).
- **Reader.** `claude-cli/claude-opus-5@claude-cli:-`, effort `low`, codebook `mapper-v3` (sha `f92016681314`), response schema `be8cb3909d96`, max_tokens 64000, read timeout 1500 s, on the Claude subscription. Checker `codex-cli@-:-` (Codex CLI on its subscription) sampled at 10% of units.
- **Budget (D4).** `--case-budget 3000`: the runner walked batches in **global rank order across all cells** (`flags.order = global`), stopped when the cases read reached the budget, and used **no cell caps** (every cell records `cap: none`). The slice-2 yield-floor rule stayed on: a cell whose last 3 completed batches yielded 2 or fewer relevant records is skipped thereafter (window 3, threshold 2).
- **Invocations.** One field invocation (started 2026-09-08T23:57:33, ended 2026-09-09T03:39:04, 3.7 h wall including the two-batch dry run), preceded by a two-batch dry run under `--case-budget 36 --dry-run-batches 2` whose two units then replayed from the cache at no cost. Stop reason: `budget:cases`.
- **Screen (D5).** Off, never run (`screen_requested: false`, 0 screen-pinned units).

## 2. Cells read

34 of the 50 cells were reached before the budget ran out; 3 stopped on the yield floor; 16 were never reached. "Not reached" is the common case in a budgeted run and is not a stop.

| era | jurisdiction | pool batches | batches read | cases read | relevant | irrelevant | stop |
|---|---|---|---|---|---|---|---|
| pre-1860 | Cal. | 14 | 1 | 18 | 0 | 18 | budget ran out |
| pre-1860 | Conn. | 16 | 1 | 18 | 0 | 18 | budget ran out |
| pre-1860 | D.C. | 9 | 0 | 0 | 0 | 0 | not reached |
| pre-1860 | La. | 26 | 0 | 0 | 0 | 0 | not reached |
| pre-1860 | Mass. | 24 | 4 | 72 | 10 | 62 | budget ran out |
| pre-1860 | N.J. | 19 | 1 | 18 | 0 | 18 | budget ran out |
| pre-1860 | N.Y. | 33 | 0 | 0 | 0 | 0 | not reached |
| pre-1860 | Ohio | 18 | 1 | 18 | 0 | 18 | budget ran out |
| pre-1860 | Pa. | 30 | 0 | 0 | 0 | 0 | not reached |
| pre-1860 | Tex. | 19 | 0 | 0 | 0 | 0 | not reached |
| 1860-1900 | Cal. | 25 | 1 | 18 | 0 | 18 | budget ran out |
| 1860-1900 | Conn. | 18 | 0 | 0 | 0 | 0 | not reached |
| 1860-1900 | D.C. | 15 | 1 | 18 | 0 | 18 | budget ran out |
| 1860-1900 | La. | 11 | 0 | 0 | 0 | 0 | not reached |
| 1860-1900 | Mass. | 26 | 4 | 72 | 17 | 55 | budget ran out |
| 1860-1900 | N.J. | 25 | 1 | 18 | 9 | 9 | budget ran out |
| 1860-1900 | N.Y. | 29 | 0 | 0 | 0 | 0 | not reached |
| 1860-1900 | Ohio | 20 | 1 | 18 | 0 | 18 | budget ran out |
| 1860-1900 | Pa. | 15 | 0 | 0 | 0 | 0 | not reached |
| 1860-1900 | Tex. | 13 | 0 | 0 | 0 | 0 | not reached |
| 1900-1930 | Cal. | 30 | 3 | 54 | 8 | 46 | budget ran out |
| 1900-1930 | Conn. | 17 | 0 | 0 | 0 | 0 | not reached |
| 1900-1930 | D.C. | 14 | 1 | 18 | 0 | 18 | budget ran out |
| 1900-1930 | La. | 12 | 0 | 0 | 0 | 0 | not reached |
| 1900-1930 | Mass. | 26 | 5 | 90 | 11 | 79 | budget ran out |
| 1900-1930 | N.J. | 31 | 3 | 54 | 22 | 32 | budget ran out |
| 1900-1930 | N.Y. | 23 | 0 | 0 | 0 | 0 | not reached |
| 1900-1930 | Ohio | 26 | 5 | 90 | 6 | 84 | yield floor: last 3 batches yielded 2 relevant accepted records, at or under 2 |
| 1900-1930 | Pa. | 23 | 0 | 0 | 0 | 0 | not reached |
| 1900-1930 | Tex. | 49 | 0 | 0 | 0 | 0 | not reached |
| 1930-1970 | Cal. | 47 | 8 | 144 | 18 | 126 | yield floor: last 3 batches yielded 2 relevant accepted records, at or under 2 |
| 1930-1970 | Conn. | 28 | 6 | 108 | 19 | 89 | budget ran out |
| 1930-1970 | D.C. | 5 | 0 | 0 | 0 | 0 | not reached |
| 1930-1970 | La. | 39 | 1 | 18 | 6 | 12 | budget ran out |
| 1930-1970 | Mass. | 31 | 5 | 90 | 7 | 83 | yield floor: last 3 batches yielded 2 relevant accepted records, at or under 2 |
| 1930-1970 | N.J. | 34 | 11 | 198 | 37 | 161 | budget ran out |
| 1930-1970 | N.Y. | 54 | 5 | 90 | 36 | 54 | budget ran out |
| 1930-1970 | Ohio | 33 | 12 | 216 | 31 | 185 | budget ran out |
| 1930-1970 | Pa. | 46 | 1 | 18 | 3 | 15 | budget ran out |
| 1930-1970 | Tex. | 68 | 1 | 18 | 2 | 16 | budget ran out |
| 1970-2020 | Cal. | 41 | 14 | 252 | 107 | 145 | budget ran out |
| 1970-2020 | Conn. | 32 | 7 | 126 | 20 | 106 | budget ran out |
| 1970-2020 | D.C. | 15 | 2 | 36 | 1 | 35 | budget ran out |
| 1970-2020 | La. | 59 | 1 | 18 | 1 | 17 | budget ran out |
| 1970-2020 | Mass. | 38 | 22 | 396 | 117 | 279 | budget ran out |
| 1970-2020 | N.J. | 34 | 15 | 270 | 138 | 132 | budget ran out |
| 1970-2020 | N.Y. | 64 | 8 | 144 | 49 | 95 | budget ran out |
| 1970-2020 | Ohio | 38 | 11 | 198 | 45 | 153 | budget ran out |
| 1970-2020 | Pa. | 46 | 3 | 54 | 24 | 30 | budget ran out |
| 1970-2020 | Tex. | 57 | 1 | 18 | 6 | 12 | budget ran out |

Totals: 167 batches, 3006 cases, **750 relevant** (25%), 2256 irrelevant, 0 failed units, 0 cases lost, 4 units re-read after a split (batches 049, 055, 150, 177; all completed).

## 3. The budget boundary (the D5 test)

- First batch bought: `cycle-004-shard-02-batch-005` (1970-2020 Mass.), mean rank score 0.9949. Last batch bought: `cycle-004-shard-02-batch-185`, mean rank score 0.7012, global position 181 of 1,465.
- Yield of the first ten batches bought: 81 of 180 relevant (45%). Yield of the **last ten**: 29 of 180 (16%); batches 175-185 yielded 1, 0, 4, 0, 2, 0, 9, 6, 1, 6.
- The next unread batches (186-190) sit at mean scores 0.701-0.696; nothing separates them from the last ones bought.

**Plainly: the last cells were still yielding above the floor when the budget ran out.** The yield floor is 2 relevant per 3 batches (about 4%); the last ten batches ran at 16%, and every reached cell except three was stopped by the budget, not by yield. Under D5 that is the evidence on which the Gemini screen is reconsidered. The competing fact is cost: this run was inside the Max subscription (no charge), so the case for a screen is wall clock, not money; a second budgeted invocation on the same order (`--case-budget 6000` resumes from the cache) buys the next 3,000 cases at the same rate of about 80 s a batch.

## 4. Checker

17 of 175 units were sampled (10%, 306 cases). Disagreements across the sampled cases: relevant 74, polarity 79, characterization 79 (232 in all). As in shard 01 the checker disagrees most on relevance at the margin and on polarity; the review rounds' 100% Codex pass over the queue is where these become cards (see the round handoffs).

## 5. Failures

None. `failed_units` 0, `units_not_ok` 0, `cases_lost` 0. Four units hit the split-and-retry path and completed on the retry.

## 6. Cost

175 reader units (24,207,783 input / 1,336,517 output tokens) and 17 checker units over 3.7 h. `spend_usd` is 0.0 by construction: both CLIs bill their subscriptions and this run stayed inside the Max plan's included usage. **This is not a charge.** At list prices the reader tokens would have been about $154.

## 7. Published counts

Via `open_ledger().view().counts()`, two-tier, before and after admission (`tools/admit_map.py --run-id cycle-004-shard-02 --apply`: 10,983 patches, `replay_ok=True`, fold rejections 0):

| claim | before | after |
|---|---|---|
| relevant records | 2,716 (821 human-reviewed, 1,895 machine-only; lower bound) | 3,466 (821 human-reviewed, 2,645 machine-only; lower bound) |
| favorable | 1,229 (379 / 850) | 1,501 (379 / 1,122) |
| favorable householder | 303 (80 / 223) | 341 (80 / 261) |

Every new record is machine-only until a review round moves it; the rounds over this shard and the cycles 1-3 re-read are recorded in the round handoffs and reports/reread-cycles-001-003.md.

## 8. Reproduction

```
.venv/Scripts/python pipeline/rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01 --exclude-read
.venv/Scripts/python tools/map_reader.py --run-id cycle-004-shard-02 --case-budget 3000 --max-wall-seconds 86400
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --dry-run
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --apply
```

Re-running the map line replays every completed unit from `data/reader/cache/` for free and continues from the budget boundary if the budget is raised; the re-rank refuses to overwrite an existing pool without `--force`.
