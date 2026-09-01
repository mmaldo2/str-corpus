# Sprint One Handoff: STR Historical Corpus Pipeline
## Agentic MapReduce over the American Case Law Record

**Audience:** Claude Code session (builder) + human reviewer
**Companion doc:** `str-property-rights-corpus-research.md` (legal context, source compendium, motivation)
**Pattern reference:** Cognition, *Agentic MapReduce* (July 2026), https://devin.ai/blog/agentic-map-reduce

---

## 1. Context and Sprint Goal

We are building a pipeline to recover historical case law on the right to let one's property short-term ("lodger," "boarder," "letting of lodgings," etc.) from the complete corpus of published American case law. The legal theories this feeds (state retroactivity clauses, state due-course-of-law clauses, *Glucksberg*-style history-and-tradition claims) are historical-evidence tests; the evidence is invisible to modern search because the vocabulary has turned over. See the companion doc for the full argument.

The architecture is Agentic MapReduce with one modification: because the historical lexicon is *unknown at the start and discovered iteratively*, the Plan stage re-runs each cycle, fed by the Reduce stage's discoveries. The loop:

```
Plan → Shard → Map → Reduce → Verify
  ▲                     │
  └── lexicon updates ──┘
```

**Sprint one delivers:**

1. Local, era/jurisdiction-partitioned indexes over CAP data for the target states.
2. The gold-standard evaluation set harvested from existing STR litigation briefs.
3. The versioned selector artifact (seed lexicon) and the deterministic Shard stage with signal provenance and a coverage matrix.
4. One full Plan→Shard→Map→Reduce→Verify cycle on a capped budget, with recall against the gold set measured and reported per-selector.

**Explicitly out of scope for sprint one** (see §12): English Reports ingestion, COFEA/COHA integration, CourtListener incremental sync, citator automation, Buzz/multi-harness wiring.

---

## 2. Stage Mapping

| Cognition stage | Our stage | Agentic? | Sprint-one implementation |
|---|---|---|---|
| Plan (author selectors) | Lexicon construction from treatise seeds + prior-cycle discoveries | Yes | Planner agent + human review of `selectors.yaml` before each Shard run |
| Shard (deterministic pass) | FTS + pinned-embedding retrieval over era-partitioned indexes → signals → bounded batches | No | Python CLI, fully reproducible, emits provenance |
| Map (per-shard reasoning) | Extraction workers filling the structured case schema | Yes | Parallel subagent sessions, one per batch |
| Reduce (synthesize) | Dedupe, ontology update, doctrinal-line synthesis, favorable/adverse sorting | Yes | Single reducer session over compressed worker outputs only |
| Verify (reproduce findings) | Deterministic verbatim-quote validation + human citator gate | Mostly no | Quote checker CLI; citator check is manual in sprint one |

Design principles carried over from the pattern:

- **Selectors are the falsifiable artifact.** Version-controlled, human-readable, testable against the gold set. A retrieval claim is only as good as the selector file that produced it.
- **Signals carry provenance.** Every candidate case records which selector fired, at what version, on what matched text. Workers receive provenance; recall debugging depends on it.
- **Reduce consumes conclusions, not transcripts.** Workers emit structured JSON; the reducer never re-reads full opinions.
- **Pay for the diff.** A coverage matrix (selector-version × corpus-partition) ensures re-runs after lexicon updates only shard with *new or changed* selectors.

---

## 3. Repository Layout

```
str-corpus/
├── README.md
├── data/
│   ├── raw/                  # CAP downloads (gitignored)
│   ├── db/corpus.db          # SQLite: cases, fts, embeddings, signals, coverage
│   └── gold/gold.jsonl       # evaluation set
├── selectors/
│   ├── selectors.yaml        # THE versioned selector artifact
│   └── CHANGELOG.md          # human-readable selector history
├── ontology/
│   └── ontology.yaml         # concept → era-specific surface forms → anchor cases
├── pipeline/
│   ├── ingest.py             # CAP → SQLite
│   ├── index.py              # FTS5 + embeddings
│   ├── shard.py              # selectors → signals → batches (deterministic)
│   ├── verify_quotes.py      # verbatim-quote validation (deterministic)
│   ├── eval_recall.py        # gold-set recall, per-selector attribution
│   └── kwic.py               # concordance/collocation CLI for the Planner
├── prompts/
│   ├── planner.md
│   ├── mapper.md
│   └── reducer.md
├── runs/                     # per-run outputs: batches, extractions, reports
└── reports/
    └── cycle-001.md          # human-facing findings report per cycle
```

---

## 4. Data Acquisition

**Target jurisdictions (sprint one):** Texas, Pennsylvania, Louisiana, plus New York (deepest lodger/boarding-house case law and the historical center of the lodging economy — high-yield for lexicon expansion even though it isn't a near-term venue).

**Source:** Caselaw Access Project bulk data — CC0, complete published U.S. case law through 2020, reporter pagination preserved.
- Primary: Hugging Face dataset `free-law/Caselaw_Access_Project` (jurisdiction-filterable parquet/jsonl).
- Alternate: static bulk files at https://case.law/ (organized by reporter volume).
- Pull state-court case law for the four target states **and** the corresponding regional reporters where CAP organizes by reporter (S.W., A., So., N.E./N.Y.). Federal courts: defer except where gold-set cases require specific opinions.

**Gold-set source documents (see §9):** RECAP archive on CourtListener for federal briefs; state-court filings (Zaatari: Texas re:SearchTX / TAMES; Ladd: PA UJS portal) may require manual retrieval — automate what's automatable, emit a `needs-human.md` list for the rest.

**Practical notes:**
- CAP text is OCR from print reporters. Expect artifacts: long-s, hyphenation across line breaks, em-dash noise. Normalize at ingest (see §5) but preserve raw text — quote verification and pin cites must run against a stable canonical text.
- Store CAP's page-break markers; extraction quotes must carry reporter page numbers.

---

## 5. Storage and Indexing

SQLite is sufficient at this scale (four states ≈ low millions of cases; DuckDB acceptable if preferred, but pick one and stay).

**`cases` table (core fields):** `case_id` (CAP id), `cite`, `name`, `court`, `jurisdiction`, `decision_date`, `era_partition`, `reporter`, `raw_text`, `norm_text`, `page_map` (json: char offsets → reporter pages).

**Era partitions:** `pre-1860`, `1860-1900`, `1900-1930`, `1930-1970`, `1970-2020`. Partition boundaries chosen around vocabulary regimes (antebellum common law; postbellum lodging economy; pre-zoning; zoning era; modern). Store as a column; all shard runs and the coverage matrix key on `era_partition × jurisdiction`.

**Text normalization (`norm_text`):** lowercase; collapse whitespace; de-hyphenate line-break splits; normalize long-s and common OCR confusables; strip headnote boilerplate where CAP marks it. Deterministic and versioned (`norm_version` column) — normalization changes invalidate the coverage matrix.

**Indexes:**
- FTS5 over `norm_text` with a porter-ish tokenizer **plus** a raw (unstemmed) index — historical terms of art must be matchable exactly ("demise" stemmed collides with "demised premises" usefully, but "let" is a stopword-adjacent nightmare; selectors need phrase and NEAR queries, so keep both).
- Embeddings: chunk opinions (~1,000-token chunks, 15% overlap), embed with a **pinned open-weights sentence-embedding model**; record model name + revision hash in the DB. Reproducibility of the embedding selector = pinned model + pinned query text + pinned threshold/k. Store vectors in a `chunks` table; brute-force cosine over four states is fine in sprint one (no vector DB dependency).

---

## 6. The Selector Artifact (`selectors.yaml`)

The load-bearing file. Human-reviewed before every Shard run. Schema per selector:

```yaml
- id: lodger-core-01
  version: 3
  concept: lodger_status            # must exist in ontology.yaml
  type: fts_phrase                  # fts_phrase | fts_near | regex | embedding
  pattern: '"taking in lodgers" OR "lodgers and boarders" OR "letting of lodgings"'
  era_scope: [pre-1860, 1860-1900, 1900-1930]
  jurisdiction_scope: all
  polarity: favorable-candidate     # favorable-candidate | adverse-candidate | neutral
  rationale: >
    Core lodger vocabulary from Wood's Landlord & Tenant ch. on lodgers;
    expect householder-letting fact patterns.
  author: planner-agent-cycle-001
  status: active                    # active | retired (never delete; retire)
```

Embedding selectors additionally carry: `query_text`, `model_rev`, `top_k`, `min_cosine`.

**Seed lexicon for cycle one** (Planner starts here; expand via KWIC over the corpus itself before first Shard run):

- *Status terms:* lodger, boarder, roomer, sojourner, inmate (historical sense), paying guest, transient guest
- *Transaction terms:* to let / letting, demise, furnished rooms, furnished apartments, lodging house, boarding house, tourist home, guest house, tenancy at will
- *Doctrinal hinges:* lodger vs. tenant, license vs. lease, exclusive possession, incident of ownership / incidents of property
- *Zoning-era terms:* roomers and boarders (in residential-district cases), single-family use + paying guests, transient occupancy
- *Adverse-candidate selectors (build in parallel):* lodging house license/permit, boarding house nuisance, innkeeper regulation, police power + lodging

**Selector hygiene rules:**
- Never edit a selector in place past a Shard run — bump `version`.
- Every gold-set miss must be attributable: which selector *should* have fired, and the fix is either a pattern change (version bump) or a new selector.
- Retired selectors stay in the file with `status: retired` for audit.

---

## 7. Shard Stage (`shard.py`) — Deterministic

1. Read `selectors.yaml`; diff against the coverage matrix; run only (selector-version × partition) pairs not yet covered.
2. Execute each selector over its scoped partitions. Each hit emits a **signal**:
   ```json
   {"case_id": "...", "selector_id": "lodger-core-01", "selector_version": 3,
    "matched_text": "...±200 chars context...", "char_span": [start, end],
    "chunk_id": null, "run_id": "cycle-001-shard-02"}
   ```
3. Update the **coverage matrix** table: `(selector_id, selector_version, era_partition, jurisdiction, run_id, timestamp, n_signals)`. This is the completeness ledger — the basis for the claim "this query set was run over the entire corpus."
4. Group signals by case; group cases into **bounded batches** of 15–20, homogeneous by `era_partition × jurisdiction` (workers reason better inside one vocabulary regime). A case with signals from multiple selectors ships all its provenance in one batch entry.
5. Emit `runs/<run_id>/batches/batch-NNN.json`.

**Sprint-one budget cap:** cap the Map stage at ~40 batches (~600–800 cases), prioritized by (a) all gold-set cases that produced signals, (b) signal density (cases hit by multiple distinct selectors first). Full sweep is a later-cycle decision once recall and cost-per-case are known.

---

## 8. Map Stage — Extraction Workers

One fresh-context subagent per batch. Worker input: the batch file (signals + provenance) + access to full opinion text by `case_id` + `prompts/mapper.md`. Worker output: one JSON record per case:

```json
{
  "case_id": "...",
  "cite": "...", "court": "...", "year": 1897, "jurisdiction": "NY",
  "relevant": true,
  "relevance_score": 0.85,
  "polarity": "favorable",            // favorable | adverse | mixed | irrelevant
  "who_was_letting": "householder",   // householder | commercial_operator | unclear
  "duration_of_occupancy": "weeks",   // nights | weeks | months | unclear
  "characterization": "license",      // lease | license | lodging | innkeeping | other
  "holding_summary": "≤3 sentences, plain statement of the holding",
  "doctrinal_concepts": ["lodger_status", "license_vs_lease"],
  "new_terms_observed": ["mesne lodger", "..."],   // feeds the Plan stage
  "quotes": [
    {"text": "verbatim passage", "reporter_page": 412,
     "supports": "characterization"}
  ],
  "worker": "claude|codex", "batch_id": "...", "notes": "..."
}
```

**Hard requirements for `prompts/mapper.md`:**
- Every non-null doctrinal field (`characterization`, `polarity`, `holding_summary`) must be supported by at least one quote. No quote → field stays null and the case is flagged.
- Quotes are copied verbatim from the provided opinion text, with reporter page from the page map. No paraphrase inside `quotes[]`.
- `who_was_letting` and `duration_of_occupancy` are first-class: the level-of-generality argument runs on them.
- `new_terms_observed`: any recurring period term for the practice not in the current lexicon. This is the flywheel input.
- Workers must return a record for **every** case in the batch, including `"relevant": false` ones — accounting for every candidate is part of the coverage guarantee.

**Cross-model agreement (budget permitting in sprint one, else cycle two):** run a 10% sample of batches through a second model family with the identical prompt; any case where the two disagree on `relevant`, `polarity`, or `characterization` goes to the human-review queue. Disagreement rate is a reported metric.

---

## 9. Gold Set and Evaluation (`eval_recall.py`) — Build This First

**Harvest:** every historical case citation (pre-1990, non-STR-era) appearing in the party and amicus briefs of: *Zaatari v. Austin*; *Nekrilov v. Jersey City*; *Hignell-Stark v. New Orleans* (I and II); *Marfil v. New Braunfels*; *Bodin v. New Orleans*; *Ladd v. Real Estate Commission*. Federal briefs via RECAP; state filings as retrievable (else `needs-human.md`). Parse citations (eyecite library), resolve to CAP `case_id`s, record `{cite, case_id, source_brief, cited_for}` in `data/gold/gold.jsonl`. Target: 40–60 resolved entries. Supplement (flagged as such) with the treatise-derived anchor cases from the lodger/boarder chapters.

**Metrics, reported every cycle:**
- **Shard recall:** fraction of gold cases (that exist in the indexed partitions) emitting ≥1 signal. *The* headline metric.
- **Per-selector attribution:** for each gold hit, which selectors fired; for each miss, planner-agent postmortem proposing the fix.
- **End-to-end recall:** fraction of gold cases surviving Map with `relevant: true`.
- **Precision proxy:** human spot-check of 30 random `relevant: true` extractions per cycle.
- Cost per case mapped; disagreement rate if cross-model check ran.

A selector change is accepted only if shard recall is non-decreasing on the gold set (or the regression is explicitly waived by the human reviewer).

---

## 10. Verify Stage (`verify_quotes.py`) — Deterministic

For every quote in every extraction:
1. Normalized exact match against the case's `norm_text` (same normalization pipeline, same version). Pass → verified, attach canonical char span + reporter page from page map.
2. Fail → fuzzy match (token-level similarity ≥0.92 over a sliding window) to tolerate OCR noise. Fuzzy pass → `verified-fuzzy`, queued for human eyeball.
3. Fuzzy fail → the quote is dropped and every field it supported is nulled; case is flagged `extraction-invalid` and returns to the re-map queue.

Nothing enters the Reduce stage unverified. **Citator/good-law validation is a manual human gate in sprint one** — the report template carries an explicit `[ ] citator-checked` checkbox per case; nothing is "work-product ready" without it.

---

## 11. Reduce Stage

Single reducer session consuming only verified extraction JSON (never opinion text, never worker transcripts). Responsibilities:

1. **Dedupe/reconcile** multi-batch duplicates and companion cases.
2. **Ontology update:** merge `new_terms_observed` and confirmed characterizations into `ontology.yaml` (concept → era-specific surface forms → anchor cases with cites). Emit a proposed-selector list for the next Plan cycle — *proposals only; the Planner + human author actual selectors.*
3. **Doctrinal-line synthesis:** cross-shard genealogies — e.g., the license-vs-lease lodger line traced across eras and jurisdictions; zoning-era boarder cases grouped by outcome. This is the cross-shard reasoning no worker can do.
4. **Sort the ledger:** favorable file / adverse file / mixed, by jurisdiction, with the who-was-letting × duration matrix tabulated (the level-of-generality evidence table).
5. Emit `reports/cycle-001.md`: findings, metrics (from §9), the evidence tables, selector proposals, and the human-review queue.

---

## 12. Deferred (Sprint Two+) — Do Not Build Now

- English Reports (CommonLII) ingestion; pre-American doctrine.
- COFEA/COHA-driven lexicon expansion (COFEA is a hosted platform — check terms before any programmatic use; manual KWIC sessions are fine meanwhile).
- CourtListener bulk sync for post-2020 and the citation graph (citation-network expansion selectors).
- Citator automation via legal-research APIs.
- Full-corpus sweep beyond the budget cap; remaining-states expansion; the state-by-state litigability matrix export.

---

## 13. Acceptance Criteria (Sprint One Done =)

- [ ] CAP data for TX, PA, LA, NY ingested; `cases` populated with era partitions, page maps, versioned normalization.
- [ ] FTS (stemmed + raw) and pinned-model embedding indexes built; model revision recorded.
- [ ] `gold.jsonl` with ≥40 resolved entries + `needs-human.md` for unresolvable filings.
- [ ] `selectors.yaml` v1 seeded (≥25 active selectors incl. adverse-candidates), human-reviewed.
- [ ] `shard.py` deterministic; signals carry full provenance; coverage matrix populated; re-run of unchanged selectors is a no-op.
- [ ] One capped Map run (≤40 batches) completed; every batch case accounted for.
- [ ] `verify_quotes.py` gating Reduce; zero unverified quotes downstream.
- [ ] `reports/cycle-001.md` with shard recall, per-selector attribution, miss postmortems, doctrinal findings, and next-cycle selector proposals.
- [ ] All of it reproducible from `README.md` on a clean machine.

---

## 14. Goal Prompt for Claude Code

> You are building sprint one of a legal-history corpus pipeline. Read `sprint-one-handoff-corpus-pipeline.md` in full and follow it as the spec; read `str-property-rights-corpus-research.md` for domain context. Build in this order: (1) ingestion + indexing for the four target states from CAP bulk data, (2) the gold-set harvester and `eval_recall.py`, (3) `selectors.yaml` v1 from the seed lexicon — then STOP for human review of the selector file before any shard run, (4) `shard.py` with signal provenance and the coverage matrix, (5) the capped Map run with the extraction schema and `prompts/mapper.md` exactly as specified, (6) `verify_quotes.py`, (7) the Reduce session and `reports/cycle-001.md`. Hard constraints: the Shard and Verify stages must be fully deterministic and reproducible; every extraction quote must be verbatim-verified against source text or discarded; every gold-set miss must be attributed to a selector fix; never mark anything work-product ready without the manual citator checkbox. When ambiguity arises between engineering convenience and evidentiary auditability, choose auditability. Report progress against the §13 acceptance checklist.

---

## 15. Pre-Flight Grilling Session (read before §14 execution)

This spec will first be reviewed in an interactive stress-test session (grilling skill) before any build work begins. Guidance for that session:

**Read both documents first.** This spec plus `str-property-rights-corpus-research.md`. The research doc carries the legal rationale behind the schema decisions — grilling recommendations that ignore it will optimize for engineering convenience over evidentiary value.

**Settled — do not re-litigate without identifying a concrete defect:**
- The five-stage MapReduce architecture with the iterative Plan feedback edge
- Selectors as a versioned artifact with the hygiene rules in §6; signal provenance; the coverage matrix
- The deterministic quote-verification gate before Reduce; manual citator checkbox before work-product status
- Gold-set-and-eval built before any selectors run; recall as the headline metric
- Terminal/headless execution: Map fleet as headless CLI invocations from a logged driver script (no orchestration platform)
- The §13 acceptance criteria as the definition of done

**Open — these are the user's decisions; put each to them with a recommendation:**
1. **Embedding model:** which pinned open-weights model, and where inference runs (local hardware vs. hosted). Model size trades against the user's available compute.
2. **SQLite vs. DuckDB** (spec default: SQLite; either acceptable, choose once).
3. **CAP acquisition route:** Hugging Face parquet vs. case.law static reporter files. *Dispatch a sub-agent to inspect both distributions' current structure before asking.*
4. **Map-run budget:** dollar/token cap for the ≤40-batch run; mapper model tier; whether the cross-model agreement check (§8) runs in sprint one or defers.
5. **New York inclusion** (§4 rationale: lexicon yield, not venue) and whether any additional venue state substitutes or adds.
6. **Era partition boundaries** (§5 defaults are vocabulary-regime estimates, not measurements).
7. **Gold-set rules:** the pre-1990 citation cutoff; how treatise-derived anchors are weighted vs. brief-harvested entries.
8. **Host environment:** target machine, disk budget (four states plus regional reporters plausibly runs to tens of GB), API keys available for the second model family.

**Facts vs. decisions:** anything checkable (CAP file layouts, eyecite capabilities, disk footprints, model benchmarks) is a sub-agent lookup, never a user question. Only genuine trade-offs go to the user.

**Exit protocol:** when the frontier is empty, write every settled answer back into this document as a dated amendment block (`## Amendments — grilling session <date>`), so §14's goal prompt continues to point at a single authoritative spec. Then confirm shared understanding with the user and only then begin the §14 build order.

---

## Amendments — grilling session 2026-08-28

All §15 open decisions settled in an interactive grilling session (Claude Code + user). Facts below marked *(verified)* were checked in-session by sub-agent research or local inspection. Where an amendment conflicts with the body text above, the amendment governs.

### A1. Host environment (§15 Q8)
The build host is the user's local machine: AMD Ryzen 7 9800X3D (8c/16t), 32 GB RAM, NVIDIA RTX 5080, ~500 GB free on C: *(verified)*. Raw downloads are kept on disk in `data/raw/` (no stream-and-discard needed).

### A2. Storage engine (§15 Q2)
**SQLite**, as the spec default. Deciding factor: mature FTS5 (phrase + NEAR, stemmed + raw indexes); DuckDB's FTS is comparatively immature.

### A3. Data acquisition route (§15 Q3) — **supersedes §4's CAP framing**
*(verified)* CAP wound down as an independent service (search disabled Sept 2024; corpus frozen ~2020; merged into CourtListener March 2024). The Hugging Face dataset `free-law/Caselaw_Access_Project` is now **gated behind manual approval** and its text is flattened with **no page-break markers** — failing this spec's pin-cite requirement.

**Decision: ingest from static.case.law volume zips** (ungated; the only bulk format preserving star pagination — page labels in the HTML casebody — plus structured opinions, typed `citations[]`, `cites_to`, OCR confidence). Four states ≈ ~20 GB zipped across ~8,700 volume zips, driven by `ReportersMetadata.json` / `VolumesMetadata.json`. Ingest text and page maps **from the HTML casebody** (page labels like `<a id="p24" class="page-label">`), not the flat JSON text.

Pull official state reporters **and** regional reporters (regionals are required for later eras — e.g., Texas official reports end 1962; post-1962 TX exists only in S.W.2d/3d). **Dedupe parallel-published cases at ingest by citation match, preferring the official-reporter copy.** Known gaps *(verified)*: static.case.law lacks Atlantic 1st ("A."), N.E. 1st, and N.Y.S.2d/3d — acceptable; official reporters cover those strata. Optionally request HF gated access in the background as a future `norm_text` quality upgrade; never block on it.

### A4. Canonical case ID (new, fact-driven)
CAP case id (as carried by static.case.law files) is the corpus **primary key**. Gold-set citations are resolved **locally**: eyecite-normalize each harvested cite, match against our own typed-citations index; unresolved residue goes to the CourtListener Citation Lookup API as a secondary validator, then to `needs-human.md`. Store the CourtListener **cluster ID as an additional column** when known (future §12 CourtListener sync). *(verified: the CL lookup API returns cluster IDs, not CAP ids; no official CAP↔CL crosswalk exists; eyecite's reporters-db covers nominate reporters — Wend., Barb., etc. — with ambiguous-abbreviation collisions disambiguated by date range, which is on us.)*

### A5. Embedding model (§15 Q1)
**Qwen3-Embedding-0.6B** (Apache-2.0; best open-weights legal-retrieval score under 1B — MLEB 77.1; 32K context; matryoshka). Pinned by HF revision hash recorded in the DB per §5. **Matryoshka-truncate to 512d, store int8** (full four-state corpus ≈ ~5 GB of vectors; brute-force cosine stays fast). Indexing runs on the RTX 5080 (~1–2 days); CPU suffices for query-time embedding.

### A6. Model tiers and execution (§15 Q4)
- **Mappers: Sonnet**, as headless `claude` CLI invocations from the logged driver script, on the user's subscription (no API dollars).
- **Planner and Reducer: Fable** (top tier) — one session each per cycle; synthesis is where quality pays.
- **Budget control:** the ≤40-batch cap stands; the driver logs per-batch token usage so cycle-001 reports cost-per-case; on subscription rate limits the driver **pauses and resumes**, never degrades tier.
- **Cross-model agreement check (§8) runs in sprint one** via `codex exec` (Codex CLI 0.145.0, authenticated via the user's ChatGPT subscription — *verified working on host*): read-only sandbox, identical `prompts/mapper.md`, 10% batch sample, Codex default model. Codex is the **checker, never the source of record** — its extractions exist only to be diffed; an outage cannot block the main run. Disagreements on `relevant`/`polarity`/`characterization` → human-review queue; disagreement rate reported.
- The user's local Qwen3 27B (Ollama) has **no sprint-one role** (GPU contention with embedding indexing; ~64k context; quantization risks verbatim-quote fidelity). Recorded as available for a future cheap-triage stage.

### A7. Jurisdictions (§15 Q5)
**Keep New York; add nothing.** The lexicon-yield rationale stands; the coverage matrix makes later state additions cheap (new partitions shard with existing selectors).

### A8. Era partitions (§15 Q6)
§5 boundaries accepted as **v1**. `era_partition` is **derived from `decision_date`** so re-cutting is a recompute, not a re-ingest. After ingest, run seed-term frequency-over-time curves (via `kwic.py`) and let cycle-002 re-cut if the data disagrees — watch the 1900–1930 boundary (*Euclid* 1926 falls mid-partition).

### A9. Gold-set rules (§15 Q7)
- **Pre-1990 cutoff kept** (the gold set tests historical retrieval; modern citations would inflate recall).
- **Two-tier recall:** headline shard-recall computed on **brief-harvested entries only**; treatise-derived anchors reported as a separate recall line (they come from the same treatises that seed the lexicon — counting them in the headline would be circular).
- **Target ≥40 total entries; the mix may flex** between tiers if the brief harvest lands short.

### A10. Brief acquisition (§15 Q3/Q8 residue) — *(verified per source)*
- *Zaatari*: fully free via TAMES (`search.txcourts.gov`, direct PDF links for party + amicus briefs — verified). Scrape gently (site intermittently 502s).
- *Ladd*: **not** publicly retrievable (PA UJS briefs are bar-members-only and post-Oct-2023 filings only). Fallbacks: IJ's case page, Prothonotary request → `needs-human.md`.
- Federal appellate briefs: mostly absent from RECAP (appellate coverage is crowdsourced/thin). District-court RECAP filings for the same litigation are free; several amicus briefs are self-published by the amici.
- **PACER rule: free sources first.** Any PACER purchase happens only from an explicit purchase list (case, document, expected gold-set value, ~$3/brief via recap-fetch) approved by the user before spending. User has a CourtListener account (API token: free) and can obtain PACER access.

### A11. Session facts affecting the research doc
The companion doc's §4.1 table describes CAP as a live service; per A3 it is frozen and merged into CourtListener. Its research value (CC0 corpus, page-preserved citations) is unchanged; only the acquisition mechanics differ.

---

## Amendments — grilling session 2026-09-01

Strategy session before cycle 004 (Claude Code + user), covering the
corpus project's objectives, its role in a fundamental-right-to-let federal
suit, and the architecture pass to precede the next runs. Each decision is
recorded as an ADR in `docs/adr/`; the entries below are the spec-level
consequences. Where an amendment conflicts with the body text or an earlier
amendment, the later amendment governs. Vocabulary is fixed in `CONTEXT.md`.

### A12. Definition of done (new) — ADR-0001
The corpus is done when the tradition matrix (favorable cases by era
partition × region × letting tier × duration) has no empty cells at an
agreed minimum; the §9 recall gate remains a per-cycle guard. Sprint-one
acceptance (§13) is unchanged and satisfied.

### A13. Deliverable and consumers (§1 clarified)
Primary: a litigation-grade evidentiary record for a federal Glucksberg-
framed suit, presented as a historical survey with a methods appendix, with
the state-by-state authority matrix as a first-class output. The engine is
kept reusable behind a domain seam (ADR-0010). First consumer: a property-
rights litigator in D.C. showing non-technical colleagues the method.

### A14. Ledger as system of record; two-tier counts — ADR-0002
The JSONL ledger stays canonical; one module owns writes with an append-only
patch log; a per-cycle manifest records every case read; every published
count is stated for human-reviewed and machine-only records separately.
§11's "every case accounted for" is now checkable from the repository.

### A15. Gold set (§9, A9 extended) — ADR-0003
Gold set frozen as v1; re-tags are versioned, logged events; Zaatari-derived
entries are the development set; held-out set from RECAP briefs, the
historical citations in the federal STR opinions, and half the treatise
anchors; recall claims cite held-out. A9's two-tier reporting stands.

### A16. Extraction schema v2 (§8) — ADR-0004
Adds `schema_version`, a third `who_was_letting` value (non-resident owner
of a single dwelling), `under_30_days` (yes/no/unclear), `restriction_nature`
on adverse records, and the court's characterization of the owner's freedom;
`reporter_page` returns to the reader instructions. Existing records keep
null v2 fields; favorable and adverse records are remapped.

### A17. Citation graph (§12 item advanced) — ADR-0005
`cites_to`, PageRank, and OCR confidence from the CAP volume metadata are
stored at ingest and backfilled; a citation-graph selector type (one hop,
both directions, seeded from human-reviewed favorable + treatise anchors,
seed hash in the coverage matrix) joins the selector vocabulary of §6.

### A18. Embedding (supersedes A5's size and storage) — ADR-0006
Qwen3-Embedding-4B at a pinned revision; bulk embedding through a hosted
endpoint serving the same open weights (paid inference is permitted for
embedding only); query-time embeddings local; a thousand-chunk agreement
check before trust; full-dimension int8 with float rescoring; chunk
metadata prefix; `shard.py` refuses embedding selectors across
mixed-model partitions.

### A19. Reader execution (supersedes A6's mapper tier and CLI execution) — ADR-0007
Readers run through API-key access behind one provider-neutral module
(OpenAI-compatible transport via OpenRouter; native Anthropic backend only
if a Claude model wins). Subscription-CLI execution is retired: it exhausted
the usage window, made cost unmeasurable, and falls outside Anthropic's
terms for automated use. Reader model chosen by a pre-registered experiment-
kit measurement against human-adjudicated references (quote fidelity ≥ 97%,
agreement ≥ 85% on relevance/polarity/who-was-letting, then cheapest per
accepted record) over the approved ten candidates. Codex remains the checker
(A6's checker rules survive); Planner and Reducer remain top-tier sessions.

### A20. Jurisdictions and sources (supersedes A7) — ADR-0008
Cycle 004: Massachusetts, Connecticut, New Jersey, California, Ohio; plus
Federal Cases, United States Reports, and the D.C. reporters fetched by
reporter slug; English Reports ingested alongside as their own partition.
Illinois and Missouri deferred; F./F.2d/F.3d reached via the citation graph
and the hand-built argument-side file. D.C. included on the merits.

### A21. Methodology defensibility (new hard requirement) — ADR-0009
Schema v2 + reader prompt v2 are a frozen codebook, changed only with a
version bump and a 50-case stability check; a methods appendix is generated
from run metadata; the manifest records each read's stratum for a later
classifier-stratified recall certification; quotes destined for work product
pass a page-image pin-cite check against static.case.law's case PDFs.

### A22. Package structure (§3 extended) — ADR-0010
`pipeline/` scripts become a package along the audited seams (store, ingest,
indexer, selector engine, reader driver, verification, review, ledger,
evaluation, domain loader) with a `domains/` directory for everything
STR-specific; staged; characterization tests and a fixture database gate
the refactor; ingest parallelized; scripts kept as thin wrappers one cycle.

### A23. Session facts
The `citations` table holds each case's own reporter citations, not a
citation graph; the raw metadata does (`cites_to` with CAP ids). static.
case.law serves per-case PDFs under each volume's `case-pdfs/`. Hosted
Qwen3-Embedding costs $0.01 per M tokens (~$45 at 10M chunks). Anthropic's
legal page reserves subscription credentials for interactive use.

---

*Companion references: Cognition, "Agentic MapReduce" (https://devin.ai/blog/agentic-map-reduce); Caselaw Access Project (https://case.law/, Hugging Face `free-law/Caselaw_Access_Project`); CourtListener/RECAP (https://www.courtlistener.com/); eyecite citation parser (Free Law Project).*
