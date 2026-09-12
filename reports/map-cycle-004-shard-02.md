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

Every new record is machine-only until a review round moves it.

**The review round (2026-09-09).** The queue over the 750 relevant records held 213 cards in one round (A 24, B 1, C 28, D 66, E 82, F 12; nothing deferred), each with the full opinion and the Codex checker's reading (the 100% pass failed on the OpenAI usage limit at first and was re-run after the user reset it: 213 of 213 ok). Two independent first passes read every card, Claude (eight opus agents) and GPT Astra; under the user's rule that an erased field stays empty when the opinion is silent, they agreed on 134 cards, applied as one set with an assisted-by note naming both readers (591 patches). The 79 disagreements went to the user with both readers' notes on each card: 47 keep, 7 set, 5 adopt, **20 withdrawn as not letting cases** (238 patches). The disagreements were mostly appetite for relevance (hotel torts, shelters, zoning cases that only quote a rooming-house clause) and whether a mixed polarity resolves to a side. After the round: relevant 3,373 (1,274 human-reviewed, 2,099 machine-only), favorable 1,482 (625 / 857), favorable householder 328 (144 / 184); 28 of the shard's 750 relevant records were withdrawn on review, and the rest of its reviewed records moved into the human tier.

## 9. The second budget (2026-09-09): a floor per cell, then the global order again

After the first review round the user chose density per era and jurisdiction over raw count
(the litigation claim is historical and jurisdiction-spanning, and the untouched early cells
are where a Glucksberg argument needs evidence). The runner gained `--cell-floor N`: before the
global walk resumes, it reads the top N unread batches of every cell that has fewer than N
read, best score first across cells. The second invocation was
`--case-budget 6000 --cell-floor 3` (budgets are cumulative; the 167 batches of the first
pass replayed from the cache), preceded by a live check that replayed the first pass and
bought two floor batches.

- **What ran.** 167 more batches, 2,997 cases, **460 relevant** (15%); 77 floor batches over
  31 thin cells, then 90 in global order from score 0.93 (the head of the three cells the
  yield floor had stopped) down to about 0.45. 0 failed units; 9 cases lost to one partial
  parse and re-read with `--retry-lost` (1 relevant). 47 of the 50 cells have now been read
  at least once; only pre-1860 D.C., Louisiana and Texas remain untouched by this shard, and
  the first two of those are in the floor's reach next time. Cumulative for the shard: 334
  batches, 6,012 cases, 1,211 relevant.
- **Yield by score band, second pass.** 0.6-0.7: 17% (54 batches); 0.5-0.6: 16% (58);
  0.4-0.5: 17% (23); 0.3-0.4: 8% (10); below 0.3: 9% (21, almost all floor batches in thin
  cells). The floor reached as deep as global position 967 (score 0.05) and still returned
  about one relevant case in eleven, which is the density argument in one number: the
  classifier's score is a poor guide inside the early cells, whose training signal is thin.
- **Where the floor landed.** 1900-1930 N.Y. 20 relevant from 3 batches, 1860-1900 N.Y. 15
  from 3, 1860-1900 Pa. 12 from 3, 1930-1970 Tex. 14 from 4, pre-1860 Mass. 11 from 4, and
  single-digit first entries in cells that held nothing from this map before (1860-1900 N.J.,
  Conn., La.; 1900-1930 Conn., La., Tex.). The zeros (pre-1860 Ohio, D.C.; 1860-1900 Cal.)
  are information too.
- **The D5 test, again.** The global-order boundary moved from score 0.70 to about 0.45 and
  the yield there is 16-17%, still four times the floor. The next band (0.3-0.45, about 2,400
  cases) yielded 8% where the floor sampled it. The screen stays deferred: the decision rule
  set at this brainstorm was "design the screen when the next band's expected yield falls
  under about ten percent", and the next band is now at the line.
- **Published counts** (two-tier, via `view().counts()`): relevant 3,373 -> **3,834** (1,274
  human-reviewed / 2,560 machine-only), favorable 1,482 -> **1,666**, favorable householder
  328 -> **363**. Review round 2 over the new records: 147 cards (A 13, C 16, D 28, E 80,
  F 10), nothing deferred.
- **Round 2 (2026-09-10).** Codex 147/147; Claude (six opus agents) and GPT Astra read
  every card blind to each other under the settled rules (an erased field stays empty when
  the opinion is silent; a withdrawal is its own decision). They agreed on 103 cards,
  applied as one set (470 patches). On the 44 disagreements the user adopted Astra's
  decisions in bulk rather than deciding card by card (247 patches; the assisted-by note
  says so): 32 withdrawals, 6 sets, 1 adopt, 5 keeps. The disagreements were almost all
  relevance appetite at the deep end of the curve - dormitories, workers'-comp board,
  zoning cases that only quote a rooming-house clause - and Astra was the stricter reader.
  After the round: relevant 3,834 -> **3,786** (1,373 human-reviewed, 2,413 machine-only),
  favorable **1,658** (670 / 988), favorable householder **361** (153 / 208). Of the second
  pass's 460 relevant records, 48 were withdrawn on review.

Manifest note: `flags` in `map-manifest.json` record the LAST invocation's flags, and the
last invocation was `--retry-lost`, so `case_budget` and `cell_floor` read as unset there;
the field run's flags are in `runs/map-cycle-004-shard-02-b2.log` and in this section.

## 10. The third budget (2026-09-10/11): exhaust the thin cells, then the global order again

Approved as a two-part pass: (1) read the 13 cells that still held fewer than 15 relevant
records (every pre-1860 cell but Louisiana, Massachusetts and New York; every D.C. era;
1860-1900 Ohio; 1900-1930 Connecticut) to a deep floor with the yield floor OFF
(`--cells <13> --case-budget 1920 --cell-floor 40 --threshold -1`; the first attempt with the
yield floor on bought six batches and stopped, because three low-yield batches had already
marked most thin cells as "stopped paying"); (2) the plain global walk (`--case-budget 9000`).

- **Part 1, the thin cells.** 68 batches, 1,224 cases, **34 relevant (3%)**. That is the
  answer about those cells: their reporters hold little more at any score, and the corpus can
  now say so with the batches read rather than assumed.
- **Part 2, the global order.** The Claude weekly limit hit mid-run (2026-09-10; resets
  Thursdays 10am ET): the reader waited out the throttle, 12 units at the tail exhausted
  their retries and were marked failed, the run continued after the reset and stopped on its
  24-hour wall cap; a resume re-read the 12 and, because the budget counter follows the
  walk rather than the manifest's total, bought about 60 more batches before its own stop.
  Together: 208 batches, 3,735 cases, **537 relevant (14%)**, down to global position 747
  (score 0.13). By band: 0.40-0.46 **24%** (540 cases), 0.35-0.40 13%, 0.30-0.35 **18%**,
  below 0.30 **11%** over 2,160 cases.
- **Cumulative for the shard.** 594 batches, 10,692 cases, 1,754 relevant, 0 failed units,
  0 cases lost after `--retry-lost`. Published after admission: relevant 3,786 -> **4,329**
  (1,373 human-reviewed / 2,956 machine-only), favorable **1,925**, favorable householder
  **395**. Round 3 over the new records: 192 cards (A 15, B 5, C 37, D 33, E 95, F 7),
  nothing deferred.
- **Round 3 (2026-09-11).** Codex 192/192; Claude (eight opus agents, from the standing
  brief) and GPT Astra read every card blind to each other. They agreed on 141 cards,
  applied as one set (661 patches); the user decided the 51 disagreements on the page
  (16 keep, 9 set, 1 adopt, 25 withdrawn; 187 patches). Withdrawals ran at a third of the
  round, three times round 1's rate: liquor-licence prosecutions where the inn is
  background, hotel torts and tax cases with no letting question, covenant cases where
  "boarding house" is boilerplate, service and dormitory occupancies with no rent. After the
  round: relevant 4,329 -> **4,262** (1,498 human-reviewed, 2,764 machine-only), favorable
  **1,911** (747 / 1,164), favorable householder **389** (161 / 228). Of the third budget's
  571 relevant records, 67 were withdrawn on review.

**The D5 test, third time, and the finding that changes it.** The yield did not collapse
below a score of 0.3: it held at 11% over 2,160 cases, and the 0.30-0.35 band read at 18%,
higher than the band above it. The classifier's score orders the head of the tail well and
says little inside it - the yield floor of about 4% has not been reached anywhere the global
walk went. What remains unread is 15,263 cases: 1,026 above 0.4 (three cells the per-cell
yield floor stopped early, plus batches the walk had not reached), 1,116 between 0.2 and
0.4, and **13,121 below 0.2**. If the deep band holds even 8-10%, it holds a thousand
relevant records, and the two ways to get them are 700-plus Opus batches (roughly 25 hours
of subscription, across weekly limits) or a Gemini screen at a few tens of dollars that
tells Opus which batches to read. The screen is no longer a wall-clock convenience; it is the
only practical route to the deep tail, and its design is the next decision.

## 8. Reproduction

```
.venv/Scripts/python pipeline/rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01 --exclude-read
.venv/Scripts/python tools/map_reader.py --run-id cycle-004-shard-02 --case-budget 3000 --max-wall-seconds 86400
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --dry-run
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --apply
```

Re-running the map line replays every completed unit from `data/reader/cache/` for free and continues from the budget boundary if the budget is raised; the re-rank refuses to overwrite an existing pool without `--force`.
