# Stage 3B slice 3: reviewer protection, ranker v2, the cycle-004 tail map, the cycles 1-3 re-read

Date: 2026-09-08. Status: approved in conversation (round 1 with two value questions answered;
the screen dropped from scope; 2026-09-08). Predecessors: slice 2
(docs/superpowers/specs/2026-09-06-stage-3b-slice-2-map-runner-design.md) and Stage 2C
(docs/superpowers/specs/2026-09-04-stage-2c-candidate-ranking-design.md). Authority on conflicts:
this spec, then the slice-2 spec, ADR-0007, ADR-0004, CONTEXT.md.

## 1. Goal

Protect human decisions in the ledger from being overwritten by later machine reads; retrain
the candidate ranker on the cycle-004 human labels and re-evaluate it under the pre-registered
ship rule on a second, frozen held-out slice that covers all ten jurisdictions; re-rank the
unread cycle-004 tail and map it under a fixed case budget with the existing runner; re-read
the 693 relevant records of cycles 1-3 under mapper-v3 so the oldest records carry the same
fields as cycle 004, with every conflict against a human value going to a review card; run the
review rounds those produce with the existing tooling; publish the counts and a report.

Out of scope: the Gemini screen (designed in slice 2, stays off; revisited only if the tail
map's last cells still yield well at the budget boundary); re-reading the 5,374 irrelevant
records of cycles 1-3 (nothing to fill); the reranker; a nightly scheduler; Stage 4.

## 2. Decisions (binding)

- D1 (Q1). Order: reviewer protection (section 3) -> ranker v2 (section 4) -> tail map
  (section 5) -> cycles 1-3 re-read (section 6) -> review rounds (section 7) -> report.
- D2 (Q2). A field value carrying a reviewer basis is never overwritten by a non-reviewer
  patch. The ledger enforces it (section 3); a re-read that disagrees with a human value is
  recorded as a conflict and becomes a review card, never a value change.
- D3 (Q3). Held-out slice v2: positives are human-reviewed relevant records; negatives are the
  human-confirmed non-letting cases (relevance overturned by a reviewer); no machine-only label
  enters the slice, so it measures the ranker against people. Stratified by era x jurisdiction,
  ceil(25%) per stratum as v1, frozen at a new path with a pinned sha; v1 is never edited.
- D4 (Q4). The tail map runs under a fixed case budget, default 3,000 cases (about 170 batches
  of 18), spent top-down on the re-ranked order across all cells, with the slice-2 yield-floor
  rule (window 3, threshold 2) still stopping quiet cells.
- D5 (Q5). No Gemini screen. Opus alone on the subscription; if at the budget boundary the
  last cells still yield above the floor, the report says so and the screen is reconsidered.
- D6 (Q6). Classifier ship rule exactly as Stage 2C wrote it: classifier v2 ships as
  `ranking.default` only if its average precision exceeds fusion's on BOTH views (all held-out
  reads, human-reviewed reads) on held-out v2; no margin. If it fails, the tail map runs on the
  existing classifier v1 ordering under the same budget, and the report says which.
- D7. Re-read scope: the 693 relevant records of cycles 001-003 (as of the current view),
  read under mapper-v3 by the pinned reader in 18-case batches; irrelevant records are not
  re-read. A re-read may fill an empty field and may replace a reader- or rule-basis value; it
  may never touch a reviewer-basis value (D2). A re-read that returns relevant false on a
  record a human judged relevant is a conflict card, never an overturn.
- D8. Provenance: re-read patches carry basis model claude-opus-5@claude-cli, prompt_version
  mapper-v3:<sha12>, run_id "cycles-001-003-reread"; the re-admit under mapper-v3 moves the
  record to the six-field support rule (fold's latest-admit-wins, slice 2). Tail-map patches
  carry run_id "cycle-004-shard-02".
- D9. Review rounds use the slice-2 queue, page, first-pass and apply tooling unchanged,
  except for one new section (section 7). First passes may be drafted by a model with full
  opinion text and are confirmed card by card by the user, recorded as before.
- D10. Terms-of-use considerations for the subscription route remain the user's (ADR-0007).

## 3. Reviewer protection (`corpus_engine/ledger/fold.py`)

`apply_patch` gains provenance precedence for `set` on a judged field: if the field's current
value was set by a patch whose basis carries `reviewer`, a later `set` whose basis does not
carry `reviewer` is REJECTED: the value stands, and the fold records the attempt in
`state.conflicts[case_id]` as `{field, attempted, by: basis, at: seq}` and appends a
`needs-review:<field>` flag with the rejecting rule's basis. A `set` to None (retraction) by a
non-reviewer is likewise rejected on a reviewer-set field. Reviewer-basis and rule-basis
patches that explicitly cite a reviewer decision (`basis.reviewer` set) still apply. The fold
tracks per-field provenance in `state.provenance[case_id][field] = kind` (human | reader |
rule) from every applied set and from the admit body (reader). A fresh replay of
data/ledger/patches.jsonl must reproduce the four cycle files byte-for-byte: the rule changes
nothing in today's data because no such overwrite has occurred — a test proves that claim over
the real log. `LedgerView.conflicts()` exposes the conflicts for the queue.

## 4. Ranker v2 (`corpus_engine/ranker/`, `tools/build_ranker_heldout.py`, `tools/train_ranker.py`)

- `tools/build_ranker_heldout.py --out data/eval/ranker-heldout-v2.jsonl --human-only` builds
  the D3 slice from the ledger view: candidates are records whose relevance was decided by a
  human (review.status human-adjudicated with a reviewer-basis patch on `relevant`, or a
  reviewer-basis polarity/who decision on a record, which confirms relevance) and the human
  relevance overturns; stratified `(era, jurisdiction, label)`, ceil(25%) per stratum, strata
  of fewer than 2 skipped; the file is frozen, its sha pinned in domain.yaml as
  `heldout_v2_sha256` beside v1's; the tool refuses to overwrite. Coverage: all ten
  jurisdictions; the report states per-stratum counts.
- `tools/train_ranker.py --heldout v2 --tag v2` trains classifier v2 on `labelled_reads()`
  excluding BOTH held-out slices, with the same features, weights (human-reviewed positives 3.0,
  machine 1.0) and hyperparameters as v1 unless the plan justifies a change; writes
  `data/ranker/v2/` with digest, and evaluates classifier v2, classifier v1 and fusion on
  held-out v2 (ap_all, ap_reviewed, per-cell AP).
- Ship rule D6 applied by the tool; `ranking.default` in domain.yaml updated only if it ships;
  reports/ranking-v2.md records the numbers, the rule and the outcome.

## 5. The cycle-004 tail map (`pipeline/rank.py`, `corpus_engine/mapper/`, `tools/map_reader.py`)

- Re-rank: `pipeline/rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01
  --exclude-read` re-scores the 1,465 unread batches' cases with the shipped ranker (v2 if
  shipped, else v1) and re-packs them into new 18-case batches under
  runs/cycle-004-shard-02/batches/ in descending score, keeping era_partition and jurisdiction
  on each case; shard-manifest records the source run, the ranker id and digest, and the
  excluded (already read) case ids.
- Map: `tools/map_reader.py --run-id cycle-004-shard-02 --case-budget 3000` — a new flag: the
  runner walks batches in global rank order (not cell order) and stops when
  `cases_read >= budget`; cells still keep their CellProgress and the yield-floor rule skips a
  cell's remaining batches once it stops; cell caps are not used (record `cap: none`). The
  manifest records the budget, the order, and per-cell yield as before. Reader units and wall
  caps as slice 2.
- Admission with `tools/admit_map.py --run-id cycle-004-shard-02` unchanged.

## 6. The cycles 1-3 re-read (`tools/reread_records.py`)

- Source: the 693 case ids with relevant true admitted in cycles 001-003 (ledger view at run
  time; the list is written to runs/cycles-001-003-reread/case-ids.json and committed).
- Batching: 18-case units in case-id order, one unit per batch, through the same Reader,
  provider and checker sample (10%) as the map; manifest as the map's; cache shared.
- Admission (`tools/admit_map.py --run-id cycles-001-003-reread --reread`): per record, a
  re-admit patch under mapper-v3 (moves the support rule), then per field: fill when the
  current value is None; replace when the current value has reader or rule provenance; SKIP
  and record a conflict when the current value has reviewer provenance and the re-read differs
  (the fold would reject it anyway; the tool avoids emitting the rejected patch and writes the
  conflict flag + note itself). A re-read `relevant false` on a human-judged-relevant record is
  a conflict, never applied. Counts of fill / replace / conflict / agree per field in the
  manifest and report.

## 7. Review rounds

Queue sections gain a seventh, "G. Re-read conflicts with a human decision", placed FIRST in
priority: one card per conflicting field, showing the human value, the re-read value, both
bases, the quotes and the full opinion text; decisions keep (human value stands — the default
expectation), set (a reviewer changes their own earlier decision, recorded as such), unsure.
Then the usual sections A-F over the tail-map and re-read admissions. Cap 250 per round; full
opinion text on every card (slice-2 lesson); Codex at 100% on the queue; first pass by a model,
confirmation by the user, apply with the existing tool (which learns section G's semantics: a
`set` on a G card carries reviewer basis and supersedes the earlier reviewer value, with a note
naming the earlier decision).

## 8. Reporting

reports/ranking-v2.md (held-out v2 composition, AP tables, ship decision); reports/
map-cycle-004-shard-02.md (the tail map: budget, order, yields, cells stopped, whether the last
cells still yielded — the D5 test); reports/reread-cycles-001-003.md (fills / replacements /
conflicts per field, how many human values the protection rule shielded); handoff updated;
CONTEXT.md gains **Provenance** (human | reader | rule, per field) and **Conflict** (a machine
read that disagrees with a human decision; never applied, always carded); published two-tier
counts before and after each step.

## 9. Error handling

Fold rejections never raise on replay: they record and continue. The re-read tool never emits
a patch the fold would reject. The runner and admission behave as slice 2 (manifest in finally,
resume from cache, run-id guards, store-sourced identity). The ranker tools refuse to overwrite
a frozen slice or a shipped model directory.

## 10. Testing

Fold: reviewer-set value survives a reader set (rejected, conflict recorded, flag added);
reader-set value is replaced; retraction by a non-reviewer on a reviewer field rejected;
reviewer re-decision applies; the real patch log replays byte-identically. Held-out v2 builder:
human-only selection, stratification, refusal to overwrite, sha pin. Trainer: excludes both
slices, evaluates three rankers, applies D6 exactly (both views, strict greater). Re-rank:
excludes read cases, packs in score order, manifest provenance. Runner: --case-budget stops at
the budget, global order, yield-floor per cell still applies. Re-read admission: fill / replace
/ conflict / relevant-false-conflict on a fixture with human, reader and rule provenance. Queue:
section G first, its card shape and decision semantics. Live: a two-batch dry run of the
re-read and of the tail map before their field runs; all field runs detached with monitors.

## 11. Constraints

LF/UTF-8 no BOM/trailing newline; never commit .env, data/db/, data/raw/, data/reader/cache/,
runs/*/batches|extractions; no paid request in this slice (Opus on the subscription, Codex on
its subscription; OpenRouter untouched); kit-v1/kit-v2, measurement manifests and held-out v1
never edited; published counts only via the ledger API; no model-assisted decision enters the
human tier without the user's confirmation and the assisted-by note.
