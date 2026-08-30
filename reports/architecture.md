# Right-to-Let Corpus Engine — architecture companion

Companion text for `architecture.html` (interactive diagram, published as an
artifact). Built with the architecture-diagram skill conventions: nodes,
flows, steps, modes. Each step's side panel carries a **Litigation value**
line contextualizing the component for the underlying claim: a householder's
right to temporarily alienate — let, lease, rent — their property for
compensation, in the same sense as today's short-term rentals.

## Components (nodes)

| Node | Role | What it is | Litigation relevance |
|---|---|---|---|
| Litigation team | user | Humans at the doctrine layer | Claim framing, citator gate, synthesis — machine-prepared inputs, human judgment |
| static.case.law | seed | 9,252 reporter volumes, 19 GB, sha256 manifest | Complete record = credible continuity claim; manifest = chain of custody |
| Ingest + Normalize | seed | HTML casebody → SQLite; star pagination → page maps; era partitions | Pin-cite fidelity by construction |
| corpus.db | vector | 1.3M unique cases, FTS (stemmed+raw), 3.88M int8 vectors, signals, coverage | The searchable historical record of TX/PA/LA/NY |
| Qwen3 indexer | embed | Pinned-revision embedding model on local GPU | Meaning-based retrieval across vocabulary drift |
| Planner + selectors | orch | selectors.yaml — 30 versioned, human-reviewed retrieval hypotheses incl. 6 adverse | The dictionary reconnecting the modern claim to its dead-vocabulary history |
| Shard engine | orch | Deterministic FTS + cosine retrieval; signals with provenance; coverage matrix | The completeness ledger: "this query set ran over the entire corpus" |
| Map fleet | compute | Headless Sonnet workers, 18 cases/batch, structured schema | who_was_letting × duration = the level-of-generality evidence |
| Codex checker | compute | Second model family, 10% sample, disagreement metric | Methodology defensibility |
| Quote verifier | seed | Verbatim gate (exact/fuzzy≥92); failing quotes null their fields | No hallucinated quote can reach work product |
| Reducer | compute | Fable synthesis: ledger, genealogies, ontology updates, cycle report | Favorable AND adverse files; candor built in |
| Gold set + eval | vector | 92 resolved entries (brief tier + treatise tier), recall per selector | Measured recall = defensible completeness claim |

Roadmap-mode nodes: CourtListener sync (post-2020 + citation graph), English
Reports (the pre-American inheritance).

## Flows

1. **Build the Record** — volumes → normalized, page-mapped corpus → embedded
   geometry. Value: pin-cites and completeness.
2. **Prove Completeness** — briefs/treatises → gold set → recall scored per
   selector; misses drive fixes. Value: benchmarked, defensible method.
3. **Recover Dead Vocabulary** — versioned lexicon → lexical + semantic
   sweeps → provenance-carrying batches. Value: the Glucksberg-grade
   specific evidence conventional search cannot reach.
4. **Read at Scale, Verify Every Quote** — AI readers fill the legal schema;
   cross-model check; deterministic quote gate. Value: brief-grade,
   source-anchored extractions.
5. **Synthesize the Ledger** — evidence tables, adverse file, ontology
   flywheel, human gates, next cycle pays only for the diff. Value: a
   compounding record with a measurable endpoint.

## Modes

- **Sprint one** — what is built and running now.
- **Roadmap** — adds deferred sources (spec §12).

## Numbers shown (as of 2026-08-30)

1,915,819 cases ingested / 1,301,147 unique · 3,882,534 chunks @ 512d int8 ·
30 active selectors · ~4,700 FTS signals + embedding signals in progress ·
255 batches (≤40 mapped in cycle one) · gold: 63 brief-tier + 29 treatise.
