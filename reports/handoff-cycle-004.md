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
  `open_ledger().view().counts().total.as_claim("relevant cases")`: **710
  relevant cases (150 human-reviewed, 560 machine-only; lower bound)**.
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
  Favorable householder (138) by era × duration (nights/weeks/months/unclear):
  pre-1860 1/0/0/1; 1860-1900 0/1/16/22; 1900-1930 4/10/12/27;
  1930-1970 0/5/11/7; 1970-2020 7/3/7/4. **The founding and antebellum era
  is the empty cell.**
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
   docs/superpowers/plans/2026-09-01-refactor-stage-1-foundations.md; Stage
   2 (selector engine, citation graph, ingest) and Stage 3 (reader driver,
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
6. **Citation graph** (ADR-0005): metadata-only ingest stage; backfill the
   existing 1.3M cases (also PageRank, OCR confidence); run the selector on
   the four existing states.
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
7. **Reader-model measurement** (ADR-0007): fix the experiment kit's
   reference to human-adjudicated records; run the approved ten candidates
   through OpenRouter; record endpoints and quantization; choose per the
   pre-registered bar; write the result into the methods appendix.
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
11. Shard, recall gate, map (user approves budget), review pipeline.

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
