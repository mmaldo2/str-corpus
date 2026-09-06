# Stage 3B slice 2: cycle-004 map runner, ledger admission, review queue

Date: 2026-09-06. Status: approved in conversation (design rounds 1 and 2, thirteen decisions,
four design sections, 2026-09-05/06). Predecessors: the Stage 3A driver spec
(docs/superpowers/specs/2026-09-04-stage-3a-reader-driver-design.md) and slice 1
(docs/superpowers/specs/2026-09-05-stage-3b-slice-1-subscription-reader-design.md).
Authority on conflicts: this spec, then ADR-0007 (override section, 2026-09-05), ADR-0004,
CONTEXT.md, reports/ranking-cycle-004.md sections 3 and 5.

## 1. Goal

Read the cycle-004 candidate pool (1,845 ranked batches, 32,795 cases, five eras, ten
jurisdictions) with the pinned reader on the user's Claude subscription under a per-cell budget
that stops on yield; admit the accepted records to the ledger as machine-only records with full
provenance; assemble a priority-ordered human review queue of at most 150 cards per round and
turn the user's decisions into human-basis patches; publish the updated two-tier counts and a
cycle-004 map report.

(Corrected 2026-09-06: ten jurisdictions, not eleven — the batches carry Cal., Conn., D.C., La.,
Mass., N.J., N.Y., Ohio, Pa., Tex.; see the plan-writer's ruling in
`.superpowers/sdd/2026-09-06-stage-3b-slice-2-map-runner/progress.md` and the cell table in
`reports/map-cycle-004.md`.)

Out of scope (slice 3): re-reading cycles 1-3 under mapper-v3; freezing ranker-heldout-v2 from
the new human-reviewed labels and re-running the classifier ship rule; running the Gemini
screen (designed here, off by default); a nightly scheduler.

## 2. Decisions inherited (binding)

- D1 (Q1). Slice = map runner + admission + review queue for cycle 004; the Gemini screen is
  designed in with an off switch and not run; cycles 1-3 re-read deferred.
- D2 (Q2, Q7). Per-cell budget stops on yield with a hard cap: a cell stops when its last three
  COMPLETED batches (54 cases at 18 per batch) yielded two or fewer relevant accepted records
  combined, or when it reaches its cap. Cap per era x jurisdiction cell = the era's 0.25
  rank-score depth in batches (reports/ranking-cycle-004.md section 5: pre-1860 32, 1860-1900
  32, 1900-1930 59, 1930-1970 139, 1970-2020 111; total 373 batches) split across the era's
  jurisdictions in proportion to each cell's pool size, rounded up, minimum one batch. Window
  (3), threshold (2) and the depth column (0.25) are runner flags recorded in the manifest.
- D3 (Q3). Two tiers only. Map records are machine-only with reader basis; the human-reviewed
  tier is reached only through the user's review decisions. Checker agreement is recorded on the
  record, never a tier.
- D4 (Q4, Q10). Review queue sections in priority order: (1) favorable AND under_thirty_days
  yes; (2) householder letting by the night (who_was_letting householder AND
  duration_of_occupancy nights); (3) reader/checker disagreements; (4) polarity mixed;
  (5) gate-erased judged fields on relevant records; (6) fuzzy quote matches (auto-accepted when
  mechanical trivial-ocr AND reader ocr-ok, as Stage 1). Cap 150 cards per round; the rest wait
  for the next round in the same order. A record appears once, in its highest section, with its
  other reasons listed on the card.
- D5 (Q5). Codex CLI checker on a 10% unit sample during the map (sha256(unit id) % 100 < 10,
  as the driver does) and on 100% of the records selected for the queue before the page is
  built.
- D6 (Q6). One detached process per invocation with per-process unit and wall-clock caps,
  resumable from cache; the user launches it; no scheduler.
- D7 (Q8). The ledger admits every mapper-v3 field (section 9). The quote-support rule extends
  to all six mapper-v3 judged fields for records whose patch basis carries prompt_version
  mapper-v3; records read under mapper-v1 keep the three-field rule. Canonical field names are
  the reader's: `under_thirty_days` and `owner_freedom_characterization` replace the
  never-populated ledger names `under_30_days` and `right_characterization` in domain.yaml and
  fold.py (no data migration is needed: no ledger record ever carried either old name — verified
  2026-09-06 over cycles 001-003).
- D8 (Q9). Basis for reader-set values: model "claude-opus-5@claude-cli", prompt_version
  "mapper-v3:<first 12 of the codebook sha>", run_id "cycle-004-shard-01". The sampled checker
  verdict is appended to review.notes; the unit's cache key is written in the patch note.
- D9 (Q11). Two commands: the map runner reads and writes the manifest; the admit tool turns
  accepted records into patches with --dry-run and --apply; the runner never writes the ledger.
- D10 (Q12). The Gemini screen: when a cell stops on yield before its cap and the screen is
  enabled, google/gemini-3.7-flash (reader.fallback_model) reads the cell's remaining cases up
  to the cap under the same codebook; only `relevant` is consumed; cases it marks relevant are
  read in full by the pinned reader. Off by default; its own dollar ceiling.
- D11 (Q13). The slice ends with reports/map-cycle-004.md, updated published counts, handoff
  items, and glossary entries; ranker-heldout-v2 is slice 3.
- D12. Reader pin per ADR-0007 override: reader.model claude-cli/claude-opus-5 (effort low,
  batch size 18, mapper-v3, read timeout 1500 s); reader.fallback_model gemini-3.7-flash;
  checker codex-cli gpt-5.6-terra.
- D13. Terms-of-use considerations for the subscription route are the user's (ADR-0007
  amendment 2026-09-05); not re-raised.

## 3. Vocabulary (CONTEXT.md additions, glossary only)

- **Map**: one pass of the reader over a cycle's ranked candidate pool under a budget; produces
  accepted records and a map manifest. Avoid: run, crawl.
- **Cell**: an era x jurisdiction slice of the candidate pool; the unit the budget is set on.
- **Yield**: relevant accepted records per completed batch in a cell; the quantity the stop rule
  watches.
- **Admission**: turning a map's accepted records into machine-only ledger records with reader
  basis. Avoid: import, load.
- **Review queue**: the priority-ordered set of admitted records a human decides on in one
  round; six sections, capped. Avoid: backlog.
- **Screen**: an optional relevance-only pass by the fallback reader over a cell's remainder.

## 4. Cells and caps (`corpus_engine/mapper/cells.py`)

`build_cells(batches, *, era_depth: Mapping[str, int], jurisdictions_by_era) -> list[Cell]`.
`Cell(era, jurisdiction, batch_ids: tuple[str, ...] in rank order, cap_batches: int)`. Batches
come from runs/cycle-004-shard-01/batches/*.json (each carries era_partition, jurisdiction,
cases with rank_score; 18 cases). Cap: `ceil(era_depth[era] * n_cell_batches / n_era_batches)`,
minimum 1. Cells are read in descending order of the mean rank_score of their first `cap_batches`
batches, so the cells most likely to yield are read first in a window that may end early. The manifest records the order and the caps.

## 5. Yield stop (`corpus_engine/mapper/yield.py`)

Pure state machine: `CellProgress.add(batch_id, relevant_accepted: int, completed: bool)`;
`should_stop(window=3, threshold=2) -> StopReason | None` where StopReason in
{yield_floor, cap_reached}. Only completed batches (unit status ok or partial with accepted
records) enter the window; a failed unit is recorded but skipped. Both parameters and each
cell's yield series and stop reason are written to the manifest.

## 6. Runner (`corpus_engine/mapper/runner.py`, `tools/map_reader.py`)

`MapRunner(reader_factory, cells, *, batch_source, cache, manifest_path, caps, log)`;
`run(cells) -> MapOutcome`. For each cell in order, for each batch until stop: one
`plan_batch_extraction([batch], codebook, pin, budget, worker="reader", checker_pin=codex,
sample_pct=10, json_schema=record_schema(codebook), resume_tool=<map_reader command>)`, read
through `Reader(provider, cases, checker=codex, cache, store_norm_version=...)`. Per-process
caps: `--max-units` (default: sum of cell caps in batches, plus 10% margin) and
`--max-wall-seconds` (default 21600); the runner stops cleanly at either, writes the manifest,
and prints the resume command (the same invocation; cache makes it idempotent). Extractions
are written to runs/cycle-004-shard-01/extractions/<batch>.json (gitignored; derived from the
cache) and the manifest to runs/cycle-004-shard-01/map-manifest.json (tracked; small): per cell
progress, yield series, stop reason, units, wall seconds, cache keys per unit, checker
disagreements, failed units, screen state, the reader pin, codebook sha, schema sha, caps and
flags. `--cells era|jurisdiction[,...]` limits the run; `--dry-run-batches N` reads the first N
batches of the first selected cell and prints the same diagnostics as the measurement tool's
dry run. The provider/budget helpers (`provider_for`, `cli_pin`, `budget_for`,
`process_unit_cap`) move from tools/measure_reader.py into
`corpus_engine/reader/providers/factory.py` and the measurement tool imports them (no
behaviour change; its tests keep passing).

## 7. Screen (`corpus_engine/mapper/screen.py`), off by default

`--screen` enables it. When a cell stops on yield_floor with cap remaining, the screen plans
`plan_batch_extraction` over the remaining batches up to the cap with the fallback pin through
OpenRouter under `--screen-max-usd` (default 5.0, checked before every request as the
measurement tool does); records with relevant true are re-batched (18 per unit) and read by the
pinned reader; only the pinned reader's records are admitted. The manifest records screened
units, hits, and spend. Tests cover the trigger, the re-batching and the ceiling; no live run
this slice.

## 8. Admission (`corpus_engine/mapper/admit.py`, `tools/admit_map.py`)

Input: the map manifest and cache (records are re-parsed and re-gated from the cache so the
admitted value is exactly what the gate accepted). For each accepted record with relevant true:
an `admit` patch, then `set` patches per field with the D8 basis. For relevant false records:
an `admit` patch with relevant false and no judged values (they are the irrelevant-read
negatives the ranker's labels use). Field mapping mapper-v3 -> ledger, all names identical
after D7: relevant, relevance_score, polarity, who_was_letting, duration_of_occupancy,
characterization, under_thirty_days, owner_freedom_characterization, restriction_nature,
holding_summary, doctrinal_concepts, new_terms_observed, quotes (text + supports), notes ->
review.notes prefixed "reader:". Support rule: `SUPPORTED_BY_PROMPT = {"mapper-v1": (the three),
"mapper-v3": (the six judged fields)}`; fold's drop_quote cascade looks up the record's admitting
prompt_version. Checker: when the unit was sampled, the disagreement (or agreement) on
relevant/polarity/characterization is appended to review.notes as "checker:<model>: <field>
<value> vs <value>". Guards: `Ledger.apply` validates on a fresh replay; the tool refuses a run
id already applied unless --force; --dry-run prints per-cell counts and the published counts
before/after without writing. Published counts come only from
`open_ledger().view().counts()`.

## 9. Review queue (`corpus_engine/mapper/queue.py`, `tools/make_map_review.py`,
`tools/apply_map_review.py`)

`select_queue(view, run_id, *, cap=150, sections=D4 order) -> Queue` picks admitted records of
this run into sections by the D4 criteria, one appearance per record, priority order, then the
cap. Before the page is built, the checker runs on every queued record (100%) through the
driver's checker path (plan_judgment or a reread with the codex pin; the manifest records which).
The page reuses tools/make_reference_review.py's mechanics (self-saving artifact, STATE marker,
per-card decisions keep / adopt checker / set value / unsure, notes), with six sections, cross
links when a record has several reasons, the quotes and holding summary, and CourtListener
links. `tools/apply_map_review.py` turns the saved page into human-basis patches through the
same path as tools/apply_reference_review.py (reviewer basis, needs-review flags on unsure,
run-id guard, superseded-flag clearing). Cards not decided are carried to the next round.

## 10. Reporting

reports/map-cycle-004.md: cells read, batches and cases per cell, stop reasons, yield curves,
accepted and relevant counts, checker disagreement rate, failed units, subscription units and
wall clock, screen state, the published two-tier counts before/after admission and after the
first review round, and the reproduction commands. Handoff items 7 and 11 updated; CONTEXT.md
gains the section 3 terms; README gains the runner/admit/review commands.

## 11. Error handling

Provider throttling is retried inside ClaudeCliProvider then fails the unit; failed units are
listed in the manifest and re-read by the next invocation (cache misses only). A unit failure
never stops a cell; the yield window ignores it. `_BudgetStop` (units or wall) ends the run
cleanly with the manifest written in a finally block. The runner never writes ledger files; the
admit tool never reads the network. The screen's ceiling is enforced before every paid request.
ANTHROPIC_* and the Bedrock/Vertex/Foundry switches are stripped from every subscription
subprocess (slice 1).

## 12. Testing

Unit: cells (caps from the section 5 table on a fixture of batches; ordering), yield (window,
threshold, failed units ignored, cap), runner with ScriptedProvider (order, resume from cache,
caps stop cleanly, manifest contents, failed unit handling), screen (trigger, re-batching,
ceiling; no network), admit (field mapping, D8 basis, support-rule scoping by prompt_version,
irrelevant admits, checker notes, run-id guard, replay ok, counts unchanged on dry-run), queue
(section criteria, single appearance, priority, cap), page render (six sections, markers,
decision schema), apply (four decisions incl. adopt-checker). Integration: a live dry run of two
batches in one cell on the subscription, inspected (parse, gate, schema, manifest, checker
sample) before the field run; the field run detached with a monitor. Existing suites stay
green; the measurement tool's tests keep passing after the helper relocation.

## 13. Constraints

LF/UTF-8 no BOM/trailing newline; never commit .env, data/db/, data/raw/, data/reader/cache/,
runs/*/batches|extractions (the map manifest is the tracked artefact); no paid request outside
tools/map_reader.py's screen path and the checker's own subscription; subscription calls never
carry an API key; kit-v1/kit-v2 and both measurement manifests untouched; published counts only
via the ledger API.
