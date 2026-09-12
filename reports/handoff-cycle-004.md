# Handoff — pre-run phase before cycle 004

**Rewritten 2026-09-01 (evening) after the strategy grilling session.**
Authoritative spec remains `sprint-one-handoff-corpus-pipeline (1).md`
including its Amendments blocks (2026-08-28 and 2026-09-01); the decisions
themselves live in `docs/adr/`; the vocabulary in `CONTEXT.md`. This
document is the operational state and the order of work.

## Where the record stands (cycles 001–003)

- Corpus: TX/PA/LA/NY, 1,301,147 unique cases (1799–2020), FTS + Qwen3-0.6B
  embeddings (3.88M chunks, 512d int8), `data/db/corpus.db` (~30 GB).
- Ledgers: `data/ledger/cycle-00{1,2,3}.jsonl`. Per
  `open_ledger().view().counts().total.as_claim("relevant cases")`: **693
  relevant cases (133 human-reviewed, 560 machine-only; lower bound)**
  (2026-09-05: was 710 / 150 human-reviewed before the Stage-3B reference
  adjudication — the user judged 17 reviewed cases irrelevant across two review
  pages; see item 7).
  Tradition-matrix pre-1860 householder count (favorable, from
  `view().matrix()`): 2 (1 human-reviewed, 1 machine-only).
  `tools/apply_retraction_cascade.py` (Stage 1 final-review fix wave): 11
  records left with a judged field unsupported by a dropped quote after
  the bootstrap's cascade-off replay were nulled and routed to human
  review (favorable count 368 -> 367; case 7664513's polarity was one of
  the fields nulled). The backfill patches carry a rule-only basis
  (`Basis(rule_id="retraction-cascade-v1")`, no reviewer) since a
  retraction to None is not a human judgment of the record, so the
  150/560 tier split is unchanged.
- Tradition matrix (favorable, by jurisdiction × era):
  La. 2/9/28/11/3, N.Y. 14/89/68/22/16, Pa. 2/11/16/10/16, Tex. 2/8/20/13/8
  for pre-1860 / 1860-1900 / 1900-1930 / 1930-1970 / 1970-2020.
  Favorable householder (137, was 138) by era × duration
  (nights/weeks/months/unclear): pre-1860 1/0/0/1; 1860-1900 0/1/18/22;
  1900-1930 2/9/12/28; 1930-1970 0/5/11/8; 1970-2020 4/2/7/6. **The founding and
  antebellum era is the empty cell.** Re-derived 2026-09-05 from
  `view().matrix()` after the reference adjudication; the favorable total is
  unchanged at 367 and the `owner` tier, empty since Stage 1, now holds 9
  (the `letting_tiers` key was misspelled `owner_nonresident`).
- Recall (gold v1, development set): brief-letting 6/9, treatise 22/29.
  Precision trend 28% → 12% → 6.6%.
- Citator: nothing is citator-checked (`reports/citator-prescreen.md`).
- Known integrity issues, all addressed by ADRs: ontology loop never closed
  (~300 free-text concepts per cycle vs 10 ontology ids); three live
  cumulative counts; gold set single-source (Zaatari) with a 9-case
  denominator; polarity drift in cycles 1–2 only partially re-reviewed;
  adverse ontology concepts have empty anchor lists; `model_rev` absent
  from embedding selectors; duplicate selector ids across version bumps.
- **Superseded 2026-09-06 by the cycle-004 map** (item 11, `reports/map-cycle-004.md`): the
  693/367/137 figures and the four-jurisdiction tradition matrix above are the cycles-001-003
  baseline this section is titled for. Current published counts (`open_ledger().view().counts()`)
  are relevant 2,939 (133 human-reviewed, 2,806 machine-only), favorable 1,261 (58/1,203),
  favorable+householder 326 (19/307) — pending the still-open review round 1 decisions. The
  tradition matrix now spans ten jurisdictions and is not re-derived here; see the map report's
  per-cell table for the cycle-004 breakdown.

## Decisions (see docs/adr/ for reasoning)

| ADR | Decision |
|---|---|
| 0001 | Tradition matrix with no empty cells is the definition of done |
| 0002 | Ledger module owns writes; patch log; per-cycle manifest; two-tier counts |
| 0003 | Gold set frozen v1; re-tags logged; development (Zaatari) vs held-out split |
| 0004 | Schema v2: version field, non-resident owner, under-30-days, restriction nature, right characterization; targeted remap |
| 0005 | Citation graph from CAP `cites_to` at ingest, backfilled; one-hop bidirectional selector, seed hash |
| 0006 | Qwen3-Embedding-4B, hosted bulk embed (~$18 now, ~$45 at 10M chunks), local queries, full-dim int8 + rescoring, metadata prefix |
| 0007 | API-key access through one provider-neutral module; model by pre-registered kit measurement; Codex stays checker |
| 0008 | Cycle 004 = Mass., Conn., N.J., Cal., Ohio + Fed. Cas., U.S., D.C.; English Reports alongside; Ill./Mo. deferred |
| 0009 | Frozen codebook + stability check; generated methods appendix; certification plan; page-image pin-cite gate |
| 0010 | Staged package refactor along audited seams; domains/ directory; characterization tests; fixture DB; parallel ingest |

Also agreed (not ADR-worthy): candidate-generation additions in order —
relevance-feedback selector type, classifier ranking of the candidate pool,
convex fusion, trigram side-index, optional reranker; ontology becomes a
versioned closed enum with a proposals field and a merge step that runs;
review page publishable as an artifact; reviewer identity recorded.

## Order of work (pre-run phase)

1. **Download for cycle 004** — started 2026-09-01 in the background
   (`runs/download-cycle-004.log`; 5,888 volumes across 209 reporters).
   `pipeline/download.py` now carries the new jurisdictions and the federal
   reporter slugs (`f-cas`, `us`, `dc`).
2. **Refactor** (ADR-0010) — **Stage 1 done: see
   docs/superpowers/plans/2026-09-01-refactor-stage-1-foundations.md.
   Stage 2A done (citation graph backfill and ingest; see item 6). Stage 2B
   done (selector engine, `corpus_engine.selector`; `pipeline/shard.py` and
   `pipeline/eval_recall.py` are wrappers). Only Stage 3 (reader driver,
   verification, review, kit) plans follow.**
3. **Ledger reconciliation** (ADR-0002): patch log, manifest, two-tier
   counts, null-polarity records resolved, hard-coded corrections moved to
   patch events.
4. **Schema v2 + codebook v2** (ADR-0004, 0009): prompt-stability check on a
   50-case sample; targeted remap of favorable + adverse records feeding the
   review queue.
5. **Gold set** (ADR-0003): freeze v1; split; wire the CourtListener rate
   limiter into `build_gold.fetch_recap`; RECAP harvest for Nekrilov
   (D.N.J. 16646707), Marfil (W.D. Tex. 17024209), Bodin (E.D. La.
   69644320); harvest historical citations from the federal STR opinions
   themselves; add treatise anchors for the new states.
6. **Citation graph** (ADR-0005): backfilled (2A Task 4); `citation-graph-38` and `relevance-feedback-39` active at v4; first run at the cycle-004 shard.
   - **Backfill run 2026-09-02**: `tools/backfill_citation_graph.py --workers 6`
     over the live corpus (9,204 zips named in `ingest_log`) — `(9204,
     17267453)` (zips processed, cites_to rows inserted incl. duplicates
     collapsed by `INSERT OR IGNORE` to 16,793,558 distinct rows). Zero zip
     errors. A second run confirmed resumability: `(0, 0)`.
   - **PageRank coverage (corrected 2026-09-02, round 2)**: among
     non-duplicate (canonical) cases, 1,093,876 of 1,301,849 carry a
     non-null `pagerank` — **84.0% coverage**. By jurisdiction
     (non-duplicate): N.Y. 673,080 total / 119,486 null (82.2% coverage),
     La. 204,257 / 46,974 null (77.0%), Pa. 192,313 / 23,961 null (87.5%),
     Tex. 232,199 / 17,552 null (92.4%). (The raw-row DB-wide figure,
     1,282,367 of 1,915,819, i.e. 67%, is lower only because it blends in
     613,970 duplicate rows — of which just 188,491 (30.7%) carry
     pagerank — that are not part of the canonical case count and are not
     the figure to cite.) Coverage varies widely by volume because CAP's
     own metadata omits `analysis.pagerank` for many cases — examples:
     `ad2d/1` (1,770 cases, 493 with pagerank, 28%) and `ad2d/202` (1,014
     cases, 916 with pagerank, 90%). The backfill stores every pagerank
     value the metadata provides and nothing else (verified: DB
     non-null-pagerank count equals metadata-with-pagerank count exactly
     for `ad2d/1`, 493 = 493), so the coverage figures reflect upstream
     data completeness, not a backfill defect.
7. **Reader-model measurement** (ADR-0007) — **v1 DONE 2026-09-04/05, v2 DONE
   2026-09-05 and it supersedes v1.**
   - *v1* (`reports/reader-measurement.md`): ten candidates over kit v1 under
     `mapper-v2`, $41.67 of $50. Winner `anthropic/claude-opus-5` at macro
     0.7075. **Nobody met the 0.85 bar** and **`mapper-v2` failed its stability
     check** on `polarity` (0.82). That is what sent the codebook to Stage 3B.
   - *v2* (`reports/reader-measurement-v2.md`, manifest
     `data/reader/measurement-v2/manifest.json`) — **the slice-1 remeasurement is
     done.** Five finalists over kit v2 (same 195 cases, relabelled) under
     `mapper-v3`: two on the Claude subscription through the CLI, three on
     OpenRouter. $6.91 of a $10 ceiling (lowered from D5's $15 before any
     purchase because the balance was $10.49), plus 46 subscription units and
     ~47 min of wall clock at no charge.
     **Winner `google/gemini-3.7-flash`** (fidelity 1.0000, macro 0.8363,
   USER OVERRIDE 2026-09-05: `reader.model` is `claude-cli/claude-opus-5` on the
   subscription (ADR-0007, override section); gemini is `reader.fallback_model`.
     $0.0051 per accepted record), now set as `reader.model` in `domain.yaml`.
     **The 0.85 bar was still not met** — the shortfall rule fired again, though
     the gap fell from 0.14 to 0.014. Three things to carry into the maps:
     (a) `z-ai/glm-5.3` had the field's best macro (0.8512, above the bar) and
     was eliminated on the pre-registered decided-rate floor, `polarity` 0.8983
     against 0.90 — one case out of 118; (b) the D4 subscription tie-break did
     **not** fire, `claude-cli/claude-opus-5` being 0.0243 behind against a 0.02
     window, so the pin is not the subscription reader the user prefers and
     overriding it is the user's call; (c) **`mapper-v3` is stable** (0.92 /
     0.97 / 0.94 on decided answers, bar 0.90) but the winner's *relevance call*
     is not — its second read of the fifty-case sample decided polarity and
     `who_was_letting` on only 72% of the cases the first read decided. Do not
     treat a Gemini `relevant: false` as settled without the checker.
   - *Reference*: kit v2's labels come from two user review pages (82 + 28
     decisions) and a 4-of-5 model consensus that confirmed all 70 of the
     never-reviewed `who_was_letting` labels it settled. Corpus counts moved
     710 → 693 relevant, favorable 367 unchanged, favorable householder
     138 → 137. Three cases carry an excluded field (D6).
   - *Cycle-004 map, empirical (2026-09-06, `reports/map-cycle-004.md`)*: the
     override pin (`claude-cli/claude-opus-5`) read all 6,831 pool cases at a
     measured **$479.96 list-price equivalent** (~$1.26/batch, ~$0.070/case) —
     zero actual spend since the user upgraded to Max 20x mid-run. The
     instability this item flagged in the winner's *relevance* call (not
     polarity/characterization) shows up again at map scale: the review-round
     checker (Codex) disputed relevance on 46 of the top 150 favorable cases,
     while agreeing with polarity 94% of the time where both decided. This
     confirms the checker-sample design (D5) was load-bearing, not decorative.
8. **DC demo report**: refreshed attorney report built on the tradition
   matrix drilling to verified quotes with pin cites, plus a one-case
   walkthrough and a methodology page. Ships before cycle 004 maps.
9. **Argument-side file** (side task A, unchanged): ~50 federal framing
   cases, separate ledger `data/ledger/argument-file.jsonl`.
10. **Ingest + index** for cycle 004 + federal tradition set — **DONE**
    2026-09-03: 15,084 zips ingested, FTS rebuilt, citation graph +
    PageRank backfilled, and the whole corpus embedded under one run
    (`qwen3-4b-1024-int8`, hosted via OpenRouter; $112.22 total). 392
    inert legacy 0.6B chunks remain on 185 already-duplicate cases (left
    in place, not replaced; see the build report). Figures and verification in
    `reports/build-cycle-004.md`. English Reports not ingested (no CAP
    source; still a hand-curated item under ADR-0008).
11. Shard, recall gate, map (user approves budget), review pipeline —
    **shard DONE 2026-09-04** (`cycle-004-shard-01`: 946 units, 40,115 signals,
    1,845 batches / 32,795 cases; recall gate PASS, non-decreasing on every tier;
    see `reports/shard-cycle-004.md`). Map waits on Stage 3 and a budget; the
    report's planner observations (relevance-feedback cap saturates; rank before
    map) come first. Ranked with `classifier:v1` (digest `a489a2dc960adb5b`);
    the Qwen3 reranker was measured and not shipped; see
    `reports/ranking-cycle-004.md`; map budget to be chosen per cell.
    A `ranker-heldout-v2` slice must be frozen once cycle-004 reads yield
    labelled reads in the six new states (Cal., Mass., N.J., Ohio, Conn.,
    D.C.), and the ship rule re-run against it.

    **Slice 2: the cycle-004 map runner and its per-cell budget — DONE
    2026-09-06.** Ran under the ADR-0007 override pin (`claude-cli/claude-opus-5`,
    effort low, batch size 18, `mapper-v3`), budget in reader units and wall
    clock (not dollars, since the override reader has no per-token price on the
    subscription): 50 of 50 cells read, 380 of 399 capped batches, 6,831 cases,
    2,246 relevant accepted; 47 cells stopped on their depth cap and 3 on the
    yield floor (`pre-1860|Pa.`, `1930-1970|Tex.`, `1970-2020|Tex.`). Two
    detached processes (a 6 h wall cap, then a 24 h resume that finished
    `stop=done`); 0 failed units. Admitted as 30,398 patches
    (`data/ledger/cycle-004.jsonl`, commit `3dce174`): published relevant
    693 → **2,939** (133 human-reviewed unchanged, 2,806 machine-only),
    favorable 367 → **1,261**, favorable+householder 137 → **326**. Review
    round 1 (`0a5e84e`) selected 150 of 903 qualifying records (section A
    favorable+under-thirty 126, section B householder-by-the-night 24; C–F
    empty; 753 deferred; 23 fuzzy quotes auto-accepted); the Codex checker read
    100% of the 150 and disputed relevance on 46. **The user's decisions on
    round 1 are pending** — `tools/apply_map_review.py` will turn them into
    human-basis patches and move qualifying records into the human-reviewed
    tier once decided. Full detail: `reports/map-cycle-004.md`. The screen
    (D10) stayed off; cycles 1-3 re-read, `ranker-heldout-v2`, and the ship-rule
    re-run remain slice 3.

    **Slice 3 (2026-09-08/09, branch refactor/stage-3b-slice-3) — the three slice-3
    carry-forwards are DONE.** (a) The ledger fold now refuses any non-reviewer
    write over a human-decided field (`PROTECTION_FROM_SEQ` 42,984 grandfathers
    the six historical rule overwrites; `ApplyResult.rejected`; `admit_map`
    exits 3 on a refusal); a machine read that disagrees with a human value is a
    section-G review card, never a value change. (b) Held-out v2 frozen
    (`data/eval/ranker-heldout-v2.jsonl`, 293 human relevance decisions over all
    ten jurisdictions, sha `4146d442e311`); classifier v2 trained on 2,331 pos /
    4,170 neg with both slices excluded: AP 0.8274 vs fusion 0.7860 on both views
    (D6 met) and 0.8319 for v1 on the same slice, 32 of whose rows were in v1's
    training data — the user shipped v2 (`ranking.classifier_version: v2`,
    `reports/ranking-v2.md`). (c) The cycle-004 tail was re-ranked on v2 into
    `cycle-004-shard-02` (1,465 batches / 25,955 unread cases) and read under a
    3,000-case budget in global order: 167 batches, 3,006 cases, **750
    relevant**, 0 failed, 34 cells reached, 3 stopped on the yield floor; the
    last ten batches bought still yielded 16% against a ~4% floor
    (`reports/map-cycle-004-shard-02.md` §3, the D5 test). (d) The 693 relevant
    cycles 1-3 records were re-read under mapper-v3: 1,396 fills on the three
    fields they never had, 198 reader-held polarities replaced, 47 machine-only
    withdrawals, **69 conflicts with human decisions carded and none applied**,
    0 fold rejections; three review rounds (Claude + GPT Astra first passes,
    user confirmation) closed the re-read queue: section G 39 keep / 25 set / 5
    withdrawn (`reports/reread-cycles-001-003.md`). Published: relevant
    **3,405** (1,093 human-reviewed, 2,312 machine-only), favorable **1,465**,
    favorable+householder **326**.

    **Cycle 004 closed (2026-09-12).** The tail map ran in five passes (first budget,
    floor-3 + global, thin-cell exhaustion, global to score 0.13, high-score leftovers;
    reports/map-cycle-004-shard-02.md §9-12): 652 batches, 11,736 cases, 1,855 relevant
    read. Four review rounds (Codex check, Claude and GPT Astra first passes, the user on
    the disagreements) closed with no open queue; from round 4 the Astra pass runs through
    `tools/first_pass_codex.py` (one Codex CLI call per card) instead of by hand. Published
    at the close: relevant **4,351** (1,509 human-reviewed / 2,842 machine-only), favorable
    **1,954**, favorable householder **397**. 15,263 shard cases remain unread (13,121
    below score 0.2) by the user's decision: the yield did not collapse in the tail (11%
    below 0.3), so the deep band plausibly holds ~1,000 relevant records, but their marginal
    value (dense cells, borderline kind) did not justify the Gemini screen now; the screen
    design stays on file in report §10. Parked for Stage 4: a codebook "centrality" signal
    (relevance stays broad). A resume beyond the last budget is `--case-budget <N>` on the
    same run id; the budget counter follows the walk, not the manifest total.
    **Tooling debts from slice 3** were cleared on 2026-09-09 (branch refactor/slice-3-tooling-debts): the
    review page has a "Not a letting case" control that writes the relevance
    withdrawal on any card and the page reader accepts it in any round; every
    reader of a quote's `supports` goes through `quote_supports`, so the
    mapper-v1 bare-string shape on cycles 1-3 quotes needs no data migration;
    `already_read_ids` reads the `{"records": [...]}` extraction shape; the
    checker `unit_cap` already counted distinct cases since the slice-3 fix wave.

    **Measured cost of a corpus-wide vector selector (2026-09-04, live index,
    read-only `probe()`).** One `probe()` of `embed-householder-letting-21@v2`
    on `1900-1930|N.Y.` — whose scope is all 5 eras x 10 jurisdictions, so it
    builds the full matrix — scanned `chunks` once into a **13,452,039 x 1024
    int8** block (13.45M of the 14.11M non-duplicate chunks; the rest fall
    outside the 50 domain partitions): **429 s (7.2 min)** and a **12.83 GiB**
    memory-mapped scratch file, returning 250 signals (cosine 0.71 down to
    0.50 at `min_cosine` 0.43). The block is an `np.memmap`, so it costs
    **+2.2 GiB working set / +2.5 GiB private commit** on top of the process
    baseline, not 12.8 GiB of RAM. The memory high-water mark of the run is not
    the matrix but loading the pinned Qwen3-Embedding-4B query encoder: 15.7
    GiB peak working set and **20.2 GiB private commit** on its own, with the
    whole probe peaking at 17.9 GiB working set / 22.7 GiB commit against a
    32.4 GiB host. Plan the cycle-004 shard accordingly: keep **>= 15 GB free
    on the scratch volume** (`shard(..., scratch_dir=)`), run nothing else
    large beside it, and note that `shard()` now builds **one union matrix for
    the whole run** shared by all five vector selectors — so the 7-minute scan
    and the 12.8 GiB file are paid once, not once per selector, and each
    additional vector selector costs only its own `sims()` pass (a streamed
    gemv over the same block) plus its per-partition top-k. Before the Stage-2B
    final-review fix this was `np.zeros`, two distinct scope keys resident at
    once (~23 GiB committed) on top of the encoder's 20.2 GiB — it would not
    have run.

## Watch-outs (unchanged)

OOM if any step `fetchall()`s the whole corpus; SQLite writer contention
between shard and embed; `build_review_queue` must not clobber reader
verdicts; a JSON-parse-failing batch is mapped as two halves (structured
outputs should retire this); OpenRouter batch mode cannot pin a provider.

## Pending / optional

- Relevance/doctrine re-tag of Smith v. Decker and Latimer (logged per
  ADR-0003 when done).
- Experiment kit at `C:\Users\marcu\Desktop\str-mapper-experiment`
  (reference must be rebuilt from human-adjudicated records).
- CourtListener token in `.env`; 125 req/day limiter in
  `citator_prescreen.py`.
- Colonial and early state lodging/innkeeping statutes as a small
  hand-curated source (ADR-0008).

## Research on file

`reports/research/2026-09-01-retrieval-embedding-and-defensibility.md`,
`2026-09-01-reader-model-frontier.md`,
`2026-09-01-ocr-longcontext-and-provider-mechanics.md`.

## Remote

Code at https://github.com/mmaldo2/str-corpus (branch main). Data
(corpus.db, raw volumes) and `.env` are local-only and gitignored.
