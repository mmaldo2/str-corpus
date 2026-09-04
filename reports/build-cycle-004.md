# Cycle 004 Corpus Build — Part A (ingest, FTS, citation graph)

**Date:** 2026-09-02
**Branch:** refactor/stage-2a
**Scope:** Steps 1–2 of `task-7-brief.md` only. Step 3 (consistency gate),
Step 4 (hosted embedding), and item 10 of `reports/handoff-cycle-004.md`
remain pending — see "Pending" below.

## Step 1: Ingest

Command: `.venv\Scripts\python pipeline\ingest.py --workers 6` (log:
`runs/ingest-cycle-004.log`).

- `15084 zips; 10309 already ingested; 4775 to do; workers=6`
- Zip errors: **0**
- `dedupe: 4151133 duplicate pairs resolved`
- `cases: 2831313 (957172 marked duplicate)`

The run started fully buffered (Python's default stdout buffering when
redirected to a file suppressed progress output); it was killed after ~2
minutes and restarted with `-u` for unbuffered logging. No work was lost —
`ingest_log` resume picked up the zips the first attempt had already
committed (already-ingested count rose from the ~9,206 baseline to 10,309
before the restart's `to do` count was read).

### Cases by jurisdiction (non-duplicate)

`SELECT jurisdiction, count(*) FROM cases WHERE is_duplicate_of IS NULL GROUP BY 1 ORDER BY 2 DESC`

| Jurisdiction | Cases |
|---|---|
| N.Y. | 673,130 |
| Tex. | 232,199 |
| La. | 204,257 |
| Pa. | 192,565 |
| Cal. | 143,071 |
| Ohio | 110,932 |
| N.J. | 90,105 |
| Mass. | 86,279 |
| U.S. | 78,856 |
| Conn. | 46,533 |
| D.C. | 16,094 |
| Ark. | 113 |
| S.C. | 2 |
| Del. | 2 |
| Utah | 1 |
| N.H. | 1 |
| Fla. | 1 |

Total unique (non-duplicate) cases: **1,874,141** (sums to the row above).
Total rows in `cases` (including duplicates): 2,831,313.

The small stray counts (Ark., S.C., Del., Utah, N.H., Fla.) are incidental
cases picked up from the federal/multi-state reporters (`f-cas`, `us`,
`us-app-dc`) whose metadata tags a non-target jurisdiction; not investigated
further as part of this task.

## Step 2: FTS rebuild and citation graph backfill

### FTS rebuild

Command: `.venv\Scripts\python pipeline\index.py fts` (log:
`runs/index-fts-cycle-004.log`).

- `fts_porter: rebuilt (2405829 docs match 'the')`
- `fts_raw: rebuilt (2405829 docs match 'the')`

Both tables now hold 2,831,313 rows (== total `cases` rows; FTS is built
over all cases, duplicates included — shard queries exclude duplicates at
query time per the module docstring). The 2,405,829 figure ("docs match
'the'") is lower than the row count because it only counts documents
containing that specific token, not every row.

### Citation graph backfill

Command: `.venv\Scripts\python tools\backfill_citation_graph.py --workers 6`
(log: `runs/graph-cycle-004.log`).

- `migrate: []`
- `5880 zips to backfill; workers=6`
- Result tuple (zips processed, `cites_to` rows inserted this run):
  **`(5880, 6450595)`**
- `cases with pagerank: 1783248`

`graph_log` resume correctly limited the run to the newly ingested zips only
(5,880, close to the 5,888 estimate in the brief).

Post-backfill totals (queried directly):
- `cites_to` row count (whole table, cumulative): **23,040,585**
- Cases with non-null `pagerank`: 1,783,248

## Timings

| Step | Started | Finished | Notes |
|---|---|---|---|
| Ingest (restart) | 02:22:29 | ~02:30 (dedupe ran after) | zip parse phase finished in ~7 min at workers=6; dedupe self-join then ran, total wall time from restart to `cases:` line under the notification window |
| FTS rebuild | 11:40:32 | before 11:41:32 (< 60s observed) | far under the 30–60 min estimate |
| Graph backfill | 12:18:43 | before next bounded poll returned | zip parse + insert phase, minutes as expected |

(Some steps ran across a gap in active supervision; exact elapsed times are
approximate from process-start timestamps and log content rather than a
continuous stopwatch. All completions were verified against `ps` showing no
running python process and the expected terminal log line present.)

## Concerns

- **Buffered stdout on first ingest attempt.** The very first ingest launch
  produced no log output for ~2 minutes because Python buffers stdout when
  it isn't a tty. It was killed and restarted with `-u`; no data was lost
  (ingest resumes via `ingest_log`), but this is worth carrying into future
  runs — always launch ingest/index/backfill scripts with `-u` (or
  equivalent flushing) when the log needs to be polled live.
- **Stray non-target jurisdictions** (Ark., S.C., Del., Utah, N.H., Fla.;
  122 cases total) appeared in the post-ingest jurisdiction breakdown. Not
  investigated — flagged here for whoever picks up Stage 2B/2C in case it
  affects partition or selector logic.
- Dedupe pass (self-join warned about in the task instructions) completed
  without incident — no MemoryError, no need for `--skip-dedupe`.

## Part B: hosted embedding (7b) — complete 2026-09-03

**Gate (Step 3).** Hosted-vs-local consistency check on 1,000 chunks
(`tools/embed_consistency_check.py --n 1000`): mean cosine 0.9999, p5 0.9999,
min 0.9998 (bar 0.99) -- PASS. Local side ran the pinned
`Qwen/Qwen3-Embedding-4B` (rev `5cf2132a`) fp16 on the RTX 5080; hosted side
`qwen/qwen3-embedding-4b` via OpenRouter (routed to DeepInfra).

**Estimate vs actual.** `tools/estimate_embed_cost.py` (500-case sample):
1,874,141 cases, ~6.11B tokens, $61.13 at the $0.01/M the research note had
recorded. The real price is $0.020/M (per-request `usage.cost` and
DeepInfra's list price), so the run cost roughly double; the user raised the
ceiling to $65 and then to $130 (ADR-0006 amendments). **Final OpenRouter
account usage: $112.22**, implying ~5.6B billed tokens (the sample
over-estimated tokens by ~8%). `embed_runs.tokens_used` holds
1,716,164,114 -- only the last two legs, which ran the post-review code
that persists the counter.

**Run.** `pipeline/index.py embed --hosted --confirm --concurrency 8`,
single full-corpus pass under run key `qwen3-4b-1024-int8` (dim 1024,
int8 symmetric per-vector, 400-token chunks with 40 overlap, metadata
prefix). Wall clock 2026-09-02 14:04 to 2026-09-03 22:01 with five
restarts, all resume-safe (the loop skips cases that already have chunks
under the run and flushes whole cases per transaction): wrong interpreter
(no numpy); an uncaught `httpx.ReadTimeout` on the first 16-worker flush;
a throttling burst that exhausted the 4-attempt retry schedule at 45,000
cases; and two external kills of the session-managed background task, after
which the final leg ran as a detached process. Fixes made during the run:
`--concurrency` with a scaling flush window (debb507), transport-error
retries with a 300 s read timeout (dc11f68), an ~11-minute retry schedule
(7f494f3). Throughput: ~12 cases/s at 4 workers, ~16 cases/s (~120
chunks/s) at 8; 16 workers timed out, i.e. the provider, not local CPU,
was the limit (the process idled at ~10% of one core). Local fp16 on the
5080 measured 27.6 chunks/s, so hosted was ~4x faster than the card.

**Verification (read-only, after completion).**

| Check | Result |
|---|---|
| Canonical cases (`is_duplicate_of IS NULL`) | 1,874,141 |
| ... with non-empty `norm_text` (eligible) | 1,874,141 |
| Chunks under `qwen3-4b-1024-int8` | 14,112,409 |
| `partition_runs()` | 61 (era, jurisdiction) partitions, every one exactly `{qwen3-4b-1024-int8}` |
| Chunks under the legacy run `qwen3-0.6b-512-int8` | 392, on 185 cases that are all **duplicates** (184 Pa., 1 La.) marked by the cycle-004 dedupe; inert for search (duplicates are excluded from partitions and selectors) |
| `embed_runs` | legacy row rev `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` / 512d / 1000+150, provider local; new row rev `5cf2132abc99cad020ac570b19d031efec650f2b` / 1024d / 400+40, provider openrouter |

The 392 stale legacy chunks are left in place (removal is a one-line
`DELETE FROM chunks WHERE embed_run != 'qwen3-4b-1024-int8'`, deferred to
the user). The legacy revision constant in `corpus_engine/store.py` was
corrected to the full 40-char sha the live `embed_meta` recorded, since
`register_run` now compares revisions exactly (8575632).

**Not done here.** English Reports (no CAP source; hand-curated under
ADR-0008). Query-time local embedding of selector queries with the same
pinned 4B model is Stage 2B.
