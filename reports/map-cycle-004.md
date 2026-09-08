# Cycle 004 map — `cycle-004-shard-01` (2026-09-06)

First run of the Stage 3B slice 2 map runner over the cycle-004 candidate pool built by the
2026-09-04 shard. Read all 50 cells (five eras x ten jurisdictions) to their per-cell budget or
yield floor, admitted every accepted record to the ledger as a machine-only record, and ran the
first review round. Spec:
`docs/superpowers/specs/2026-09-06-stage-3b-slice-2-map-runner-design.md`.

## Headline

- **50 of 50 cells read**, 380 of 399 capped batches (95%), 6,831 cases, **2,246 relevant
  accepted / 4,594 irrelevant accepted**, 0 failed units; **9 cases were lost** to one unit
  that completed without answering for them and were recovered by a retry (see Lost cases).
- 47 cells stopped on their depth cap; **3 stopped on the yield floor** (window 3, threshold 2)
  before reaching cap: `pre-1860|Pa.` (4 of 5 batches), `1930-1970|Tex.` (10 of 21),
  `1970-2020|Tex.` (7 of 14).
- Two detached processes: a 6 h wall-cap run, then a 24 h resume that finished `stop=done`.
- Admitted 6,831 records as 30,398 patches (`3dce174`); published relevant moved 693 -> 2,939
  (133 human-reviewed unchanged, 2,806 machine-only).
- Review round 1 selected 150 of 903 qualifying records (`0a5e84e`); Codex checked 100% of the
  150 and disputed relevance on 46. Round 1 was decided on 2026-09-06: a first pass drafted
  by GPT Astra, confirmed card by card by the user — 73 keep, 9 set, 1 adopt (83 records into
  the human-reviewed tier) and 67 unsure, which stay machine-only with a needs-review flag.

## What was read

Per-cell batches completed / cap, stop reason (`cap` = depth cap reached, `yield` = yield
floor), relevant accepted, and cases read. Source: `runs/cycle-004-shard-01/map-manifest.json`
`cells` block.

| Era | Jurisdiction | Batches | Cap | Stop | Relevant | Cases |
|---|---|---|---|---|---|---|
| pre-1860 | Cal. | 3 | 3 | cap | 3 | 54 |
| pre-1860 | Conn. | 3 | 3 | cap | 3 | 54 |
| pre-1860 | D.C. | 2 | 2 | cap | 0 | 36 |
| pre-1860 | La. | 4 | 4 | cap | 12 | 72 |
| pre-1860 | Mass. | 4 | 4 | cap | 21 | 72 |
| pre-1860 | N.J. | 4 | 4 | cap | 11 | 72 |
| pre-1860 | N.Y. | 5 | 5 | cap | 26 | 90 |
| pre-1860 | Ohio | 3 | 3 | cap | 5 | 54 |
| pre-1860 | Pa. | 4 | 5 | yield | 6 | 72 |
| pre-1860 | Tex. | 4 | 4 | cap | 4 | 72 |
| 1860-1900 | Cal. | 4 | 4 | cap | 26 | 72 |
| 1860-1900 | Conn. | 3 | 3 | cap | 17 | 54 |
| 1860-1900 | D.C. | 3 | 3 | cap | 11 | 54 |
| 1860-1900 | La. | 2 | 2 | cap | 2 | 36 |
| 1860-1900 | Mass. | 5 | 5 | cap | 37 | 90 |
| 1860-1900 | N.J. | 4 | 4 | cap | 30 | 72 |
| 1860-1900 | N.Y. | 5 | 5 | cap | 43 | 90 |
| 1860-1900 | Ohio | 4 | 4 | cap | 10 | 72 |
| 1860-1900 | Pa. | 3 | 3 | cap | 8 | 54 |
| 1860-1900 | Tex. | 3 | 3 | cap | 12 | 54 |
| 1900-1930 | Cal. | 8 | 8 | cap | 47 | 144 |
| 1900-1930 | Conn. | 4 | 4 | cap | 21 | 72 |
| 1900-1930 | D.C. | 4 | 4 | cap | 8 | 72 |
| 1900-1930 | La. | 3 | 3 | cap | 17 | 54 |
| 1900-1930 | Mass. | 7 | 7 | cap | 25 | 126 |
| 1900-1930 | N.J. | 8 | 8 | cap | 60 | 144 |
| 1900-1930 | N.Y. | 6 | 6 | cap | 61 | 108 |
| 1900-1930 | Ohio | 7 | 7 | cap | 53 | 126 |
| 1900-1930 | Pa. | 6 | 6 | cap | 20 | 108 |
| 1900-1930 | Tex. | 12 | 12 | cap | 52 | 216 |
| 1930-1970 | Cal. | 18 | 18 | cap | 130 | 324 |
| 1930-1970 | Conn. | 11 | 11 | cap | 39 | 198 |
| 1930-1970 | D.C. | 3 | 3 | cap | 1 | 54 |
| 1930-1970 | La. | 15 | 15 | cap | 63 | 270 |
| 1930-1970 | Mass. | 12 | 12 | cap | 65 | 216 |
| 1930-1970 | N.J. | 13 | 13 | cap | 84 | 234 |
| 1930-1970 | N.Y. | 21 | 21 | cap | 192 | 369 |
| 1930-1970 | Ohio | 13 | 13 | cap | 81 | 234 |
| 1930-1970 | Pa. | 18 | 18 | cap | 98 | 324 |
| 1930-1970 | Tex. | 10 | 21 | yield | 39 | 180 |
| 1970-2020 | Cal. | 12 | 12 | cap | 143 | 216 |
| 1970-2020 | Conn. | 9 | 9 | cap | 55 | 162 |
| 1970-2020 | D.C. | 4 | 4 | cap | 7 | 72 |
| 1970-2020 | La. | 16 | 16 | cap | 53 | 288 |
| 1970-2020 | Mass. | 10 | 10 | cap | 102 | 180 |
| 1970-2020 | N.J. | 9 | 9 | cap | 96 | 162 |
| 1970-2020 | N.Y. | 18 | 18 | cap | 202 | 324 |
| 1970-2020 | Ohio | 11 | 11 | cap | 47 | 198 |
| 1970-2020 | Pa. | 13 | 13 | cap | 79 | 234 |
| 1970-2020 | Tex. | 7 | 14 | yield | 19 | 126 |

Era subtotals: pre-1860 36 batches / 91 relevant / 648 cases; 1860-1900 36 / 196 / 648;
1900-1930 65 / 364 / 1,170; 1930-1970 134 / 792 / 2,403; 1970-2020 109 / 803 / 1,962. Ten
jurisdictions throughout (Cal., Conn., D.C., La., Mass., N.J., N.Y., Ohio, Pa., Tex.) — see the
spec correction in section "Corrections" below.

Caps came from the era-depth table (`reports/ranking-cycle-004.md` section 5, the 0.25
rank-score column: pre-1860 32, 1860-1900 32, 1900-1930 59, 1930-1970 139, 1970-2020 111 batches,
split across each era's jurisdictions by pool size and rounded up, minimum one batch). The
lowest caps actually assigned were 2 batches (`1860-1900|La.`, `pre-1860|D.C.`); no cell in the
run carried a cap of 1.

## Yield curves

Highest relevant-per-completed-batch: `1970-2020|Cal.` (11.9), `1970-2020|N.Y.` (11.2),
`1970-2020|N.J.` (10.7), `1970-2020|Mass.` (10.2), `1900-1930|N.Y.` (10.2) — all cap-reached,
i.e. still yielding when the budget ran out. `1970-2020|N.Y.`'s 18-batch series ran 15, 17, 15,
16, 11, 9, 12, 13, 7, 12, 10, 12, 11, 7, 5, 10, 9, 11 relevant per batch — no three-batch window
ever fell to 2 or under.

Lowest: `pre-1860|D.C.` (0.0; both batches 0 relevant, cap-reached at 2 — the cell never got a
chance to trip the yield floor because its cap was already the minimum), `1930-1970|D.C.` (0.3;
1, 0, 0), `1860-1900|La.` and `pre-1860|{Cal.,Conn.}` (1.0 each, all cap-reached at their
2-3-batch minimums). The three yield-floor stops: `1930-1970|Tex.` (series 10, 3, 4, 5, 3, 6, 6,
2, 0, 0 — stopped after batch 262, last three yielded 2); `1970-2020|Tex.` (9, 3, 0, 7, 0, 0, 0 —
stopped after batch 378, last three yielded 0); `pre-1860|Pa.` (4, 0, 1, 1 — stopped after batch
374, last three yielded 2). Texas is the only jurisdiction that tripped the yield floor, in both
of its largest-cap eras.

## Lost cases

**9 of the 18 cases in `cycle-004-shard-01-batch-146` (`1930-1970|N.Y.`) were never answered
for, and are not in the corpus.** The unit's first response would not parse, the driver split
it, one half came back and the other did not - so the unit COMPLETED (`status:
"partial_parse"`, `records: 18`, `cases_read: 9`, `status_counts.missing: 9`) and is not a
failed unit. That is why the cell's row reads 369 cases where 21 batches x 18 would be 378,
and why `totals.records` 6,840 exceeds `totals.cases_read` 6,831 by exactly 9.

Those 9 cases are missing from both sides of the map: they are not among the 2,246 relevant
records, and they are not among the 4,585 labelled negatives `ranker-heldout-v2` will train
on. A resume cannot recover them - it replays the unit from the response cache, which holds
the answer that lost them.

The retry ran on 2026-09-06 (`tools/map_reader.py --retry-lost`): the nine case ids
(835703, 880999, 899345, 1008910, 1046562, 2264542, 3223841, 5412641, 5790700) were re-planned
as one fresh unit (`cycle-004-shard-01-retry-001`), read in 13 s, all nine answered - **0
relevant, 9 irrelevant** - and merged into this manifest (`cases_lost` 0; totals 6,840 cases
read, 2,246 relevant, 4,594 irrelevant, 387 reader units). Admission picked them up as nine
relevant-false admit patches (`9 applied, 30398 already present; replay_ok=True`); the
published counts did not move. Every unit row now records `cases_lost`, so a future partial
parse names the cases it dropped rather than leaving the difference between two totals as
the only trace.

## Reader, codebook, schema, caps and flags

| | |
|---|---|
| Reader pin | `claude-cli/claude-opus-5@claude-cli:-`, effort low, batch size 18, read timeout 1500 s |
| Checker pin | `codex-cli@-:-` (gpt-5.6-terra), 10% of units during the map (`sha256(unit id) % 100 < 10`) |
| Codebook | `mapper-v3`, sha `f920166813144f09d3a8a8de575eb860dbcce18a42b46b2270b4b17cc1a52752` |
| Manifest schema | `map-manifest-v1` (`runs/cycle-004-shard-01/map-manifest.json`) |
| Record JSON schema | sha `be8cb3909d96d5bf03c9f16c541e21c37100fca0c8bc6357ef64421b62b65e59` (`manifest.schema_sha`, the schema sent to the model) |
| Yield stop | window 3, threshold 2 (a cell stops when its last 3 completed batches yield <= 2 relevant combined) |
| Screen | off (`screen.state = "off"`, 0 screened units, 0 hits) — designed, not run this slice |
| Store norm version | v1 |
| Tool | `tools/map_reader.py`, `2.1.258 (Claude Code)` |

## Runs and resume

Two detached processes against the same run id (`cycle-004-shard-01`), the second resuming from
cache:

| Process | Started | Stop | Cells | Batches | Cases | Relevant | Reader units | Checker units | Wall |
|---|---|---|---|---|---|---|---|---|---|
| Run 1 | 09:32:33 | `budget:wall` (6 h cap) | 25 | 227 | 4,077 | 1,634 | 231 | 19 | 21,603 s |
| Run 2 | 15:34:22 | `done` | 50 (all) | 380 (all) | 6,831 | 2,246 | 153 new (386 cumulative) | 16 new (35 cumulative) | 11,012 s (32,807 s cumulative) |

Run 1 hit its 6 h `--max-wall-seconds` default; the user's decision was to let it hit that cap
rather than raise it up front, then relaunch with `--max-wall-seconds 86400` so the remainder
would finish in one process — it did, reaching `stop=done` at 380 of 399 capped batches (the
19 batches short of 399 belong to the 3 cells that stopped on their yield floor before their cap).
0 failed units - no unit failed to come back - and 3 units retried after a split across
the whole map (`units_retried_after_split: 3`). One of those three came back partially:
see Lost cases above.

Before the field run, a Codex CLI adapter fix (`9765518`, `67e35bf`) was needed to get the
checker responding; a 2-batch dry run on `1970-2020|Mass.` then read 36 cases, 32 relevant, 0
quotes dropped, 4 `under_thirty_days` values erased by the quote-support gate, at ~96 s/batch (no
checker sample by hash on those 2 units). An admission dry run against that 2-batch manifest
projected 36 records -> 375 patches and counts moving 693 -> 725 relevant / 367 -> 380 favorable
/ 137 -> 139 favorable+householder — not applied; the field run followed immediately.

## Subscription usage and list-equivalent cost

Computed directly from the 421 map-run cache entries under `data/reader/cache/` (386 reader +
35 checker, matching the manifest's `unpriced_requests: 421` exactly; no extrapolation needed):

| | Reader (Claude, 386 units) | Checker (Codex, 35 units) |
|---|---|---|
| Input tokens | 48,261,652 | 2,892,735 |
| Output tokens | 2,866,412 | 239,158 |
| List-price equivalent (`raw.list_cost_usd`) | **$479.96** (all 386 priced) | not tracked (0 of 35 carry a list price) |

Combined reader+checker tokens (51,154,387 in / 3,105,570 out) match the manifest's
`totals.input_tokens` / `totals.output_tokens` exactly. `spend_usd` is 0 throughout — this ran
entirely on the Claude subscription and (for the checker) a ChatGPT/Codex subscription, so the
$479.96 is a list-price-equivalent figure, not a bill.

Per unit of work: **~$1.24 per reader unit, ~$1.26 per completed batch** (380 batches), **~$0.070
per case read** (6,831 cases). This is measured, not extrapolated, and it revises the earlier
in-flight estimate from the first 79 batches (~$1.41/batch, ~$0.078/case, ~$111 list-equivalent,
~151,000 input tokens/batch) downward — the actual whole-map average is ~127,000 input tokens per
reader unit.

The user upgraded the Claude subscription to Max 20x on 2026-09-06 (~12:30, mid-run-1) after
seeing that early per-batch estimate, restoring zero marginal cost for the remainder of the map;
the decision was to keep the Opus pin rather than switch to the Gemini fallback. On the prior 5x
plan, usage beyond the included allowance would have billed at API list rates — the $479.96
figure is what that usage would cost at those rates, not what was actually charged.

## Admission and published counts

Admission (`3dce174`, `tools/admit_map.py --apply`): 6,831 records -> 30,398 patches, replay ok.
Two tiers only (per D3): every admitted record is machine-only with reader basis; the
human-reviewed tier moves only through review decisions, so it is unchanged by admission itself.
Verified against `open_ledger().view().counts()` on 2026-09-06:

| Count | Before map | After admission | Human-reviewed | Machine-only |
|---|---|---|---|---|
| Relevant | 693 | **2,939** | 133 (unchanged) | 2,806 |
| Favorable | 367 | **1,261** | 58 | 1,203 |
| Favorable + householder | 137 | **326** | 19 | 307 |

The machine-only jump (560 -> 2,806 relevant machine-only records) is almost entirely this one
map: it read 6,831 cases across six newly-added jurisdictions (Cal., Mass., N.J., Ohio, Conn.,
D.C.) that had no prior coverage at all, plus deeper reads of the four original jurisdictions
(La., N.Y., Pa., Tex.). The human-reviewed tier is unchanged because admission only ever writes
machine-only basis records (D3); it grows only when review round decisions are applied.

## Review round 1 composition and the checker's second opinion

`tools/make_map_review.py` selected 150 of 903 qualifying admitted records (cap per round;
`0a5e84e`):

| Section | Criterion | Cards |
|---|---|---|
| A | Favorable and under_thirty_days=yes | 126 |
| B | Householder letting by the night | 24 |
| C | Reader/checker disagreement | 0 |
| D | Polarity mixed | 0 |
| E | Judged fields erased by the quote gate | 0 |
| F | Fuzzy quote match | 0 |

Sections C-F were empty this round because A+B alone filled the 150-card cap; 753 records are
deferred to round 2 in the same priority order. 23 fuzzy quote matches were auto-accepted
(mechanical trivial-ocr + gate-verified quote, no second reader this slice per the plan's ruling
2). The Codex checker then read 100% of the 150 queued cards (`review-round-1-checker.json`,
150/150 answered, all `status: ok`) as a second opinion before the page was built and published
(artifact `54b41951-15a4-4bd6-8dbf-8a5f16843146`):

- **Relevance**: Codex disputed relevance on **46 of 150** top-favorable cases (called them not
  relevant where the reader's map admitted them as relevant) — read plainly, this is a real
  disagreement rate on the highest-priority cards, not noise; the user's review round is what
  adjudicates it, and it is exactly the instability item 7 flagged for this reader (relevance is
  the winner's unstable call, polarity/characterization are the stable ones).
- **Polarity**: of the 64 cards where both the reader and Codex committed to a polarity value,
  they **agreed on 60 (94%) and gave opposite values on 4**. Codex gave no polarity opinion at
  all on 83 of the 150 cards the reader did decide (plus 3 where neither decided) — it is
  conservative about answering, not just about agreeing.
- **Characterization**: of the 89 cards where both committed to a value, they agreed on 67 (75%)
  and gave opposite values on 22; Codex gave no opinion on 59 of the cards the reader decided
  (plus 2 where neither decided).

After round 1 (applied 2026-09-06 with `tools/apply_map_review.py --decisions
runs/cycle-004-shard-01/review-round-1-decisions-astra.json --assisted-by "GPT Astra"`, 610
patches, replay ok): relevant 2,939 (216 human-reviewed, 2,723 machine-only); favorable 1,259
(125 human-reviewed; two favorable -> adverse); favorable householder 325 (27 human-reviewed; one
householder -> commercial operator among eight such reclassifications). Every applied decision
carries the note that the first pass was model-drafted and human-confirmed; the 67 unsure cards
wait for a full read (page or round 2).

Round 1b (applied 2026-09-07, run id map-cycle-004-round-1b, 405 patches, replay ok): the 67 unsure
cards were re-read by GPT Astra with the FULL opinion text (reports/review-round-1b-*) and confirmed
by the user: 28 overturned on relevance (not letting cases; relevant false, polarity and who
cleared), 27 polarity kept, 9 values set (6 who -> unclear, 2 polarity -> adverse, 1 -> commercial
operator), 3 still unsure. Published after round 1b: relevant 2,911 (252 human-reviewed, 2,659
machine-only); favorable 1,231 (152 human-reviewed); favorable householder 319 (28 human-reviewed).
Of the 46 cases Codex called irrelevant, 28 were removed and most of the rest stood.

Round 1c (applied 2026-09-07, run id map-cycle-004-round-1c, 16 patches, replay ok): the user
decided the last three cards on a page, without model assistance — 2134894 polarity -> mixed;
3642161 and 9926133 overturned on relevance (a Fourth Amendment hotel-room search and a
burglary-of-habitation case: neither decides anything about the right to let). Round 1 is
closed: all 150 cards decided. Published: relevant 2,909 (253 human-reviewed, 2,656 machine-only);
favorable 1,228 (152 human-reviewed); favorable householder 319 (28 human-reviewed). Round 2 =
the 753 deferred records (sections C-F).

Round 2 (applied 2026-09-07, run id map-cycle-004-round-2, cap 250, 1,207 patches, replay ok): 100
reader/checker disagreements, 149 polarity-mixed cards and 1 householder card, first pass by GPT
Astra with the full opinion text (reports/review-round-2-*), confirmed by the user: 46 relevance
overturns (Codex sided with on 46 of 70 relevance disputes), 24 relevance disputes kept, 17
checker values adopted, 31 reader values kept, 7 third values set; of the 149 mixed cards only 30
stayed mixed under the codebook definition and 91 resolved to a side (56 adverse, 35 favorable);
4 still unsure. Published after round 2: relevant 2,863 (453 human-reviewed, 2,410 machine-only);
favorable 1,267 (220 human-reviewed); mixed 213; favorable householder 321 (39 human-reviewed).
Rounds 3-4 = the 503 deferred records (419 gate-erased fields, 29 fuzzy quotes, 55 mixed).

Round 3 (selected 2026-09-08, cap 250: B 1, C 1, D 57, E 191 gate-erased fields; 257 deferred; Codex
250/250): the first pass (GPT Astra, erased values and surviving quotes for E, full text for D)
was applied in two parts. Round 3a (run id map-cycle-004-round-3, 497 patches, replay ok): 102
confirmed — 52 erased values restored, 1 erased field set otherwise, 36 mixed cards resolved to a
side, 13 kept mixed. The 55 relevance overturns Astra proposed (47 of them on erased-field cards,
which carry no full text) were HELD OUT with the 93 unsure cards for round 3b, which re-reads all
148 with the full opinion text (reports/review-round-3b-*), because round 1b showed relevance
calls need the opinion, not the quotes. Published after 3a: relevant 2,863 (555 human-reviewed,
2,308 machine-only); favorable 1,290 (265 human-reviewed); mixed 177; favorable householder 324.

## Limitations

- **D6 window**: three cases carry an excluded field from the pre-map reference adjudication
  (handoff item 7); unaffected by this map.
- **Screen not run**: the fallback-reader screen (section 7 of the spec) is implemented and
  tested but disabled (`--screen` not passed); no cell's remainder beyond its cap was read by a
  second, cheaper model this slice.
- **Cap floor, corrected**: the lowest per-cell caps assigned were **2 batches**
  (`1860-1900|La.`, `pre-1860|D.C.`) — 2 cells, not 3, and no cell had a cap of 1 despite the
  spec's stated minimum-of-one floor; the floor was simply never binding at this pool's density.
- **D.C. thin**: D.C. is the weakest jurisdiction throughout — 0 relevant in pre-1860 (2 of 2
  batches), 1 in 1930-1970 (3 of 3), single digits elsewhere — consistent with a small pool
  rather than a stopped-early cell (every D.C. cell reached its cap).
- **Identity fields from the store**: admitted cite/court/jurisdiction/year come from the case
  store, never from the model's own record, per the Task 7 review ruling.
- **Checker coverage**: the map itself only checks 10% of units by hash (35 of 386, 324
  field-level disagreements recorded across those samples); the review queue's 100% check is
  the load-bearing second opinion for the highest-priority records, not the map-wide sample.
- **Quote gate**: the quote-support gate erased judged fields when the model set a value without
  naming it in `supports`, most often `under_thirty_days` (in 180 of 386 units) and
  `owner_freedom_characterization` (97); 12 quotes were dropped for failing the verbatim check
  across the whole map.
- **No live screen spend**: `screen.max_usd` (5.0) and its budget check were exercised only in
  tests (ScriptedProvider), not against a real OpenRouter balance.

## Reproduction

```powershell
$R = "cycle-004-shard-01"
.venv\Scripts\python tools\map_reader.py --run-id $R --max-wall-seconds 86400   # resumes from cache, idempotent
.venv\Scripts\python tools\admit_map.py --dry-run
.venv\Scripts\python tools\make_map_review.py --check --queue runs\$R\review-round-1.json --checker runs\$R\review-round-1-checker.json
.venv\Scripts\python -c "from corpus_engine.ledger.ledger import open_ledger; print(open_ledger().view().counts())"
```

## Where recorded

Manifest: `runs/cycle-004-shard-01/map-manifest.json`. Review queue:
`runs/cycle-004-shard-01/review-round-1.json`, `review-round-1-checker.json`,
`reports/review-queue-map-cycle-004.md` / `.html`. Admission commit `3dce174`; review round 1
commit `0a5e84e`. Handoff items 7 and 11 updated alongside this report; spec section 1's
jurisdiction count corrected. Design: `docs/superpowers/specs/2026-09-06-stage-3b-slice-2-map-runner-design.md`. SDD ledger:
`.superpowers/sdd/2026-09-06-stage-3b-slice-2-map-runner/progress.md`.
