# Handoff — start of cycle 004 (jurisdiction expansion)

**Written 2026-09-01 for a fresh session.** Authoritative spec remains
`sprint-one-handoff-corpus-pipeline (1).md` incl. its Amendments block;
this document is the operational state and the agreed direction.

## Where the record stands (cycles 001–003, fully human-adjudicated)

- Corpus: TX/PA/LA/NY, 1,301,147 unique cases (1799–2020), FTS + Qwen3
  embeddings (3.88M chunks), `data/db/corpus.db` (~30 GB).
- Ledgers: `data/ledger/cycle-00{1,2,3}.jsonl`. **Cumulative: 710
  relevant cases — 368 favorable / 196 adverse / 128 mixed; 138 favorable
  householder cases (12 nights / 19 weeks / 46 months).** N.Y. 409,
  Pa. 107, Tex. 99, La. 95. 150 records carry human adjudication.
- Polarity is judged from the OWNER'S right to let (pro-tenant = adverse);
  prompts fixed 2026-09-01; ledgers re-reviewed (31 flips applied) and
  9 reviewer-flagged records relevance-rechecked (5 dropped).
- Recall (post-hygiene gold set): brief-letting 6/9 = 66.7%, treatise
  22/29 = 75.9%. Remaining misses: Smith v. Decker, Latimer v. Hess
  (recommend doctrine re-tag), Ruhl v. Kauffman & Runge (accepted miss).
- Precision trend on this corpus: 28% → 12% → 6.6% — the lexicon net is
  near its floor here; do not run a fourth deep read of the same pool.
- Citator: NOTHING is citator-checked. Pre-screen memo for 13 priority
  cases at `reports/citator-prescreen.md` (Shvekh confirmed overruled per
  Slice of Life; Tarr healthy at 59 citing).

## Agreed direction

Objective is an eventual **federal** suit (Glucksberg framing), which
rewards national breadth over four-state depth. Order of work:
1. **Cycle 004 — jurisdiction expansion** (this handoff).
2. Cycle 005 — English Reports (CommonLII) for the common-law inheritance.
3. Federal argument-side pass (F./F.2d/F.3d zoning + property-rights line,
   STR losses, CourtListener post-2020) once the record has breadth.
4. Citation-graph expansion after breadth exists.

## Proposed states for cycle 004 (ranked)

Criteria: treatise-anchor density (`data/gold/treatise_anchors_full.md`),
reporter depth on static.case.law (case counts), regional diversity for a
"national tradition" showing, and STR-litigation salience.

| Rank | State | CAP cases | Why |
|---|---|---|---|
| 1 | Massachusetts | 93k | Densest treatise anchors (White v. Maynard, Porter, Swain, Dutton, Peaks, Bianchi); founding-era colonial lodging law |
| 2 | Illinois | 187k | Large reporter; Cochran v. Tuttle anchor; Chicago rooming-house/zoning era; Koch/De Lano region |
| 3 | California | 144k | Polack v. Shafer anchor; large modern STR docket; western tradition |
| 4 | Ohio | 154k | Linwood Park v. Van Dusen anchor; Euclid's home state (zoning-era origin) |
| 5 | Missouri | 140k | Messerly v. Mercer anchor; Hoffmann v. Kinealy (nonconforming-use) cited in STR briefs |
| 6 | Florida | 329k | Largest non-NY reporter; STR-heavy jurisdiction today; Southern-region coverage |
| 7 | Washington | 106k | Kohne v. White anchor; Pacific NW; active STR ordinances |
| 8 | New Jersey | 116k | Nekrilov venue; Downs v. Sea Bright zoning anchor |
| 9 | Georgia / N. Carolina | 172k / 118k | Southern breadth; Atlantic coastal vacation-rental tradition |
| 10 | Connecticut | 58k | Osborn v. Darien anchor; small, cheap |

Recommendation: **cycle 004 = ranks 1–5** (Mass., Ill., Cal., Ohio, Mo. —
~720k cases, five regions, five treatise-anchored lines). Six states in one
cycle is fine if disk/GPU time allows (≈ 1.5 days embedding total at the
observed ~90 chunks/s).

Note: CAP also carries **"United States" — 1.84M federal cases** from the
same source; the federal argument-side pass (step 3) can use the identical
download/ingest path with a jurisdiction filter of "U.S.".

## How to run cycle 004

```powershell
# 1. extend targets and download (add jurisdictions to TARGET_JURISDICTIONS
#    in pipeline/download.py and pipeline/ingest.py; names as in
#    ReportersMetadata: "Mass.", "Ill.", "Cal.", "Ohio", "Mo.")
.venv\Scripts\python pipeline\download.py --concurrency 4
.venv\Scripts\python pipeline\ingest.py                  # incremental; dedupe pass at end
.venv\Scripts\python pipeline\index.py fts               # rebuild both FTS tables
.venv\Scripts\python pipeline\index.py embed --batch 48  # incremental: only new cases
# 2. gold: add treatise anchors for the new states (treatise_anchors_full.md
#    OOC table) via build_gold.py add-treatise after extending the md table
# 3. selectors: v3 (36 active) shards the new partitions automatically via
#    the coverage matrix — add JURISDICTIONS to shard.py ERAS/JURISDICTIONS
#    lists first. Retire sro-35 or scope to 1930-1970 (cycle-003 §4).
.venv\Scripts\python pipeline\shard.py --run-id cycle-004-shard-01 --exclude-mapped
.venv\Scripts\python pipeline\eval_recall.py             # gate: non-decreasing
# 4. Map (user approves budget), then the standard review pipeline (README)
```

Watch-outs learned the hard way: OOM if any step `fetchall()`s the whole
corpus (stream); SQLite writer contention between shard and embed (use
busy_timeout, don't run both); `build_review_queue` must not clobber reader
verdicts (fixed); a JSON-parse-failing batch is mapped as two halves;
credits exhaustion looks like `claude exited 1` — re-run, cache resumes.

## Decided 2026-09-01
- **Cycle 004 states: Massachusetts, Illinois, California, Ohio, Missouri**
  (D.C. considered and declined). The next session will open with a
  high-level strategy conversation (grilling) before the run; the two side
  tasks below are intended to be knocked out during that pre-run phase.

## Side tasks for the pre-run phase (cheap; no corpus build)

### A. Argument-side file (federal framing authority)
Not tradition evidence — the cases a federal brief is *framed* with: the
level-of-generality line (Moore v. East Cleveland, Belle Terre, Euclid,
Penn Central), Glucksberg/Dobbs/Bruen methodology, and the STR decisions
(Nekrilov 3d Cir.; Hignell-Stark I & II, Marfil, Bodin 5th Cir.; Zaatari
Tex. App.; Ladd Pa.; Slice of Life Pa.; Tarr Tex.). ~50 cases. Fetch
individually via CourtListener (token in `.env`, respect the 125/day
limiter in `citator_prescreen.py`), run each through the mapper for the
structured record + verified quotes, and keep them in a SEPARATE ledger
(`data/ledger/argument-file.jsonl`) — never mixed into the tradition
evidence counts. Half a day. Reason it's built by hand: federal courts
don't make lodging law; this material is small, known, and not hidden
behind vocabulary drift, so the pipeline's recall machinery adds nothing.

### B. RECAP brief harvest (gold-set breadth)
`build_gold.py fetch` with `COURTLISTENER_API_TOKEN` set pulls the free
district-court RECAP filings for Nekrilov (D.N.J. 16646707), Marfil
(W.D. Tex. 17024209), Bodin (E.D. La. 69644320); then `harvest` adds their
historical citations (with cited_for contexts and domain tags) to
`gold.jsonl`. Wire the rate limiter into `build_gold.fetch_recap` first
(it currently has none). Filter docket entries to briefs/memoranda before
downloading. Appellate briefs remain absent from RECAP; PACER only via a
user-approved purchase list (Amendment A10).

## Pending / optional
- Relevance/doctrine re-tag of Smith v. Decker and Latimer in the gold set.
- Mapper-model experiment kit for Codex/Qwen at
  `C:\Users\marcu\Desktop\str-mapper-experiment` (self-contained).
- CourtListener token in `.env` (125 req/day limiter in
  `citator_prescreen.py`); RECAP brief harvest for Nekrilov/Marfil/Bodin
  district dockets still not run.
- Attorney-facing report artifact needs refresh with corrected cumulative
  numbers (`reports/attorney-report.html`).
