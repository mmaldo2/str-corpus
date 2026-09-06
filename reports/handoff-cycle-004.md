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

    **Slice 2 (next): the cycle-004 map runner and its per-cell budget.** The
    reader is now pinned (`reader.model` = `google/gemini-3.7-flash`, effort
    `low`, batch size 18) and the kit is v2 under `mapper-v3`, so the map runner
    inherits a measured reader and a stable codebook rather than choosing either.
    Two things it must carry from item 7: the winner is priced (~$0.005 per
    accepted record, so a per-cell budget is expressible in dollars as well as in
    cases read), and its relevance call is the unstable part, so the checker
    sample is load-bearing rather than decorative. If the user overrides the pin
    to `claude-cli/claude-opus-5`, the budget becomes units and wall clock
    instead, and the map runner must handle both kinds.

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
