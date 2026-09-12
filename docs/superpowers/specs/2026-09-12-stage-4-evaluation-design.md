# Stage 4, sub-project 1: the evaluation package — design

Date: 2026-09-12. Status: approved in brainstorm (user), reviewed section by section by GPT
Astra through the Codex CLI; this document records the agreed design. Reader of the
evaluation: the user. Consumers of its JSON: the methods-appendix generator (sub-project 2)
and the demo report's methodology page (sub-project 3).

## 1. Goal

Answer "how good is the corpus" with five measures an opposing expert could check, from
inputs that are frozen and named, and leave the numbers in a machine-readable file the
methods appendix can quote without re-deriving them.

The five measures, decided by the user:

| # | measure | headline | new work it needs |
|---|---|---|---|
| 1 | gold recovery | share of the eligible gold cases the corpus carries as relevant, with a per-stage funnel | none beyond the package |
| 2 | machine-tier precision | share of a random sample of machine-only relevant records that survive a blind human reading | the audit sample and round (section 4) |
| 3 | field accuracy | on the same sample, agreement of draw-time polarity and who_was_letting with the human's values | same |
| 4 | reviewer agreement | Claude vs GPT Astra, and each vs the user, per round and selection rule; the blind audit round separately | the rounds registry (section 6) |
| 5 | unread-tail coverage | relevant cases plausibly left in the 15,263 unread shard-02 cases, as three scenarios | none beyond the package |

## 2. Non-goals and standing rules

- No new reading of unread cases; the tail is estimated, not measured. The Gemini screen
  design (reports/map-cycle-004-shard-02.md §10) stays the route to a measurement.
- No codebook change; relevance stays broad (user decision 2026-09-12).
- No API spend. The audit's model passes run on the Claude subscription (opus subagents)
  and the Codex subscription (`tools/first_pass_codex.py`); the checker is optional and not
  a vote.
- Published counts come only from `open_ledger().view().counts()`.
- Human-tier writes happen only through the apply tool with the user's own decisions.
- LF / UTF-8 byte-safe writes everywhere (`export_review_cards.write_text` contract).

## 3. The package: `corpus_engine/evaluation/`

Pure functions over the ledger view and explicit inputs. Nothing in the package writes a
file or reads the network. One module per measure, one result type per measure, one
composed `Evaluation`.

```
corpus_engine/evaluation/
  __init__.py      re-exports the result types and `evaluate()`
  stats.py         wilson_interval(k, n, z=1.96) -> (lo, hi); cohens_kappa(pairs) -> float | None
  types.py         Envelope + one frozen dataclass per measure + Evaluation
  gold.py          gold_recovery(gold_rows, view, store_conn, map_manifests) -> GoldRecovery
  precision.py     precision_and_accuracy(sample_manifest, outcomes) -> Precision
  agreement.py     agreement(registry, files) -> Agreement
  coverage.py      tail_coverage(bands_table) -> Coverage
  summary.py       evaluate(view, inputs) -> Evaluation; to_json(ev) -> dict
  schema.json      the JSON contract (section 5)
```

### 3.1 The envelope every measure carries

```python
@dataclass(frozen=True)
class Envelope:
    method_version: str                 # bumped when the measure's definition changes
    population: str                     # what was counted, one sentence
    exclusions: tuple[str, ...]         # what was left out and why, one sentence each
    uncertainty: Uncertainty            # type: "sampling" | "assumption" | "none"; level; method
    limitations: tuple[str, ...]        # plain sentences the report prints verbatim
    provenance: Provenance              # inputs: (path, sha256, role)...; run_ids; ledger seqs
```

Every estimate that carries an interval is an `Estimate(value, n, lo, hi, status)` where
`status` is `"ok"`, `"undefined"` (e.g. kappa with one category), or `"unavailable"` (the
input does not exist yet). Never a bare float.

### 3.2 Measure 1: gold recovery (`gold.py`)

Inputs: the gold rows (`data/gold/gold.jsonl`, 183 entries; `gold-domain-overrides.json`),
the view, the store's case table (for "resolved to a case"), every map manifest under
`runs/*/map-manifest.json` (for "read", "failed", "lost"), and the ledger's history (for
"reader negative" vs "withdrawn in review").

Eligible frame: gold entries with `tier == "brief" and domain == "letting"` (35, of which 9
resolve) plus `tier == "treatise"` (32, of which 29 resolve). Brief-doctrine entries (116)
are reported as inventory only; they are authorities the brief cited for doctrine, not
letting cases a relevance reader should find. Citations are de-duplicated on `cite_norm`
(181 unique of 183) and cases on `case_id` (88 unique).

Per tier (`brief-letting`, `treatise`) and for the union, the funnel:

| stage | definition |
|---|---|
| entries | gold rows in the tier |
| resolved | rows with a `case_id` in the store |
| signaled | resolved cases with at least one selector or ranker signal (`corpus_engine.selector.engine.attribution`, as `pipeline/eval_recall.py` uses it) |
| read | resolved cases in any map manifest's completed units (cumulative across runs) |
| relevant | resolved cases whose ledger record has `relevant` true at the reporting seq |
| relevant, human-reviewed | of those, `view.reviewed()` true |

Recovery = relevant / resolved, with a Wilson interval, labelled **recovery** (a benchmark
built from the briefs and treatises the project started from; no documented held-out split),
not generalisable recall. The unresolved rows (91) are listed by cite as an ingest coverage
gap. Every miss is listed with the stage it was lost at: `unresolved`, `unsignaled`,
`unread`, `read-failed`, `reader-negative` (the reader said not relevant and no human
overturned it), `withdrawn` (a human set relevant false; the reviewer and run id shown).
Cumulative recovery is the headline; a per-run column shows which run first carried each hit.

### 3.3 Measures 2 and 3: precision and field accuracy (`precision.py`)

Inputs: the frozen sample manifest and the audit outcomes (section 4). The measure never
reads the live view for the sampled records: applying the audit moves them out of the
machine tier, so the population is the frame **at draw time**.

Definitions, all over the 150 with explicit handling of `unresolved` outcomes (counted,
listed, excluded from the rate's denominator, and reported as a limitation):

- precision = records the user's final `relevant` is true / decided records; Wilson 95%.
- polarity accuracy = records whose draw-time polarity equals the user's final polarity /
  records the user found relevant; Wilson 95%. Likewise who_was_letting.
- joint correctness = records where relevant, polarity and who_was_letting all match / decided
  records (withdrawals count as a joint miss).
- confusion matrices for polarity (3x3 plus "withdrawn") and who_was_letting (4x4 plus
  "withdrawn"), draw-time value by row, adjudicated by column.
- the favorable-householder subgroup: its sample size and the same rates, reported with the
  interval so its weakness is visible rather than implied.

Also carried: the user's initial (pre-reveal) values versus final values, as a count of
revisions per field, so the report can say how often seeing the model readings changed the
human's answer.

### 3.4 Measure 4: reviewer agreement (`agreement.py`)

Inputs: the rounds registry (section 6) and the files it names. Comparison unit: a
(case_id, field) card. Outcomes are compared on the **substantive label** the decision
yields (the value after `keep` resolves to the card's current value, `set` to its value,
`adopt` to the checker's value, a withdrawal to `relevant:false`, `unsure` to its own
category); action agreement (keep/set/unsure) is kept as a secondary table. Two withdrawals
agree; a withdrawal against any field value disagrees; the other fields of a withdrawn card
are not counted.

Per round: raw agreement and Cohen's kappa per decide field for Claude vs Astra; the same
for Claude vs user and Astra vs user where the user decided card by card, labelled
**exposure-affected** (the user saw both readers' notes and, on disagreement pages, only the
disagreements); the bulk-adopted rounds (shard-02 2b and 4b, and any re-read round the
registry marks so) are listed under exclusions with their card counts. Each table names the
round's selection rule (the queue's section rules) so nobody reads the number as
corpus-wide reliability. The audit round is reported in its own table as **blind agreement**
(both readers from the opinion alone; the user pre-reveal), the only number the appendix
should call inter-rater reliability. Kappa with a single observed category is `undefined`.

### 3.5 Measure 5: unread-tail coverage (`coverage.py`)

Inputs: a **bands table**, `runs/evaluation/shard-02-bands.json` (tracked). The batches and
extractions under `runs/cycle-004-shard-02/` are gitignored, so `tools/evaluate.py
--build-bands` derives the table once where they exist and commits it: per batch, batch id,
cell, ranker score, cases, read (yes/no), relevant records read, with the sha256 of the map
manifest and of each batch file it came from. The measure reads only the table. From the read
batches, yield per **case** (relevant records / cases read) by ranker-score band (0.05-wide);
from the unread batches, cases per band. Three scenarios, each an estimated relevant count:

1. the tail yields at the rate of the lowest read band with at least 200 cases;
2. at half that rate;
3. at the observed 11% below score 0.3.

No scenario is called a bound. Limitations printed: batches were read in a rule-driven,
adaptively stopped order; unsignaled cases and reader false negatives are unmeasured; the
estimate is over shard-02 candidates only.

### 3.6 Summary (`summary.py`)

`evaluate(view, inputs) -> Evaluation` composes the five results plus the published counts
(tiered relevant; favorable; favorable householder from `view.counts()`), the reporting seq
and ledger content hash, the git revision, the command line, and the Python and package
versions. `to_json` produces the contract in section 5.

## 4. The audit sample and its blind round

Runs first: measures 2 and 3 read its outputs.

### 4.1 The draw: `tools/draw_audit_sample.py`

`--seed <int> --n 150 --out runs/audit-cycle-004/`. Frame: every record in the view at head
seq with `relevant` true and `view.reviewed(case_id)` false, sorted by case id.
`random.Random(seed).sample(frame, n)`. Writes, and never rewrites (a redraw is a new
directory):

- `sample-manifest.json`: `drawn_at`, `ledger_head_seq`, `ledger_content_sha256`, `frame_size`,
  `frame_sha256` (sha256 of the sorted ids joined by LF), `seed`, `method`, `n`, `tool_revision`
  (git sha), `brief_sha256`, and `records`: in draw order, each with `case_id`, the full judged
  record at draw time (every judged field, quotes, holding_summary), the reader `run_id` and
  `prompt_version` that produced it, the ranker score and band, the era x jurisdiction cell,
  and `opinion_sha256`.
- `opinions/<case_id>.txt`: the store's `norm_text` the readers and the user read (tracked;
  ~2 MB).
- `audit-queue.json`: the review-queue shape (`run_id: "audit-cycle-004"`, `titles`, `sections`)
  with one section `H` ("Audit sample: relevance, polarity, who was letting") and one card per
  record carrying `decide_fields: ["relevant", "polarity", "who_was_letting"]`. Cards carry
  no `values`, no `quotes`, no `holding_summary`, no `reason`.

### 4.2 Blind cards: `tools/export_review_cards.py --audit`

Audit mode renders cite, name, court, jurisdiction, year, the CourtListener link, and the
full opinion text, nothing else. The JSON twin carries the same fields. Existing modes are
unchanged.

### 4.3 The audit brief: `reports/review-audit-brief.md`

Derived from the standing first-pass brief's vocabulary and polarity rule, with the
decisions replaced: from the opinion alone, state `relevant` (true|false); if true, state
`polarity` and `who_was_letting`; each with a one-line note quoting the deciding fact. Output
per card: exactly three entries `{case_id, field, decision: "set", value, note}`, or exactly
one `{case_id, field: "relevant", decision: "set", value: false, note}`. No `keep`, `adopt`
or `unsure`. A card the reader cannot read (truncated or garbled text) gets one entry
`{case_id, field: "relevant", decision: "unresolved", note}`; `unresolved` is an audit
status, never a ledger value.

### 4.4 Isolated model readers

Both passes run from a directory holding only the brief and the blind cards, with no access
to the repo's handoffs, manifests or ledger:

- `tools/first_pass_codex.py --audit --workdir <dir>`: the Codex provider runs with that
  working directory; the prompt is the audit brief plus one blind card; parsing accepts
  three entries or one withdrawal or one unresolved, all-or-nothing per card; validation
  requires the three fields, the vocabularies, no duplicates; resume is keyed by card and
  brief hash, so a changed brief re-asks every card.
- Claude: opus subagents, one card chunk each, dispatched with only the brief and their chunk
  file, writing decisions files in the same shape.

### 4.5 The audit page: `tools/make_map_review.py --audit`

One card per record: opinion text and three radio groups (relevant true/false; polarity;
who_was_letting; the last two disabled when relevant is false). A **Lock** control records
the user's initial answer with a timestamp, then reveals a panel with the two readers' values
and notes and, if present, the checker's values. The user may revise after reveal; the page
stores the initial answer, the final answer, and a required reason when they differ. Save
writes the state block as today (`review-state`), with entries
`{case_id, field, decision: "set", value, initial_value, locked_at, revised_reason}`. The
draw-time values are never on the page.

### 4.6 Apply: `tools/apply_map_review.py --audit`

Reads the saved audit page (or a decisions file in the same shape). For every decided
record it writes explicit reviewer-basis `set` patches on all three fields, **equal values
included** (a confirmation is a human decision on the field and must carry field-level human
provenance so the protection rule covers it); a `relevant:false` takes the existing
withdrawal path. Before writing, a **drift check** compares each record's current judged
values with the sample manifest's draw-time values and refuses the whole apply if any
sampled record changed since the draw (`--allow-drift <case_id,...>` overrides one by one,
recorded in the note). `--run-id audit-cycle-004`, `--assisted-by` not accepted in audit mode:
these are the user's own decisions. Records with `unresolved` are skipped and listed.

### 4.7 Outcomes: `runs/audit-cycle-004/outcomes.json`

Written by the apply tool after a successful apply (and by a `--dry-run` to a `-dry` name):
per record, `draw_time` values, `claude`, `astra`, `checker` (or null), `user_initial`,
`user_final`, `revised_reason`, `status` (`decided` | `unresolved`), `applied_seq_range`.
This file, the sample manifest, and the registry entry are the inputs of measures 2-4.

### 4.8 Three-way sheet: `tools/threeway_sheet.py`

The session scratch scripts (`threeway.py`, `agreed_set.py`) move into `tools/` as one
tool with the existing one-field mode (so past sheets can be regenerated) and a `--per-field`
mode for the audit. The audit's sheet is for the user's reconciliation and the agreement
measure; it produces no agreed-set file, because nothing in the audit is applied without
the user.

## 5. The JSON contract (`corpus_engine/evaluation/schema.json`)

```
{
  "schema_version": "1",
  "evaluation_id": "<cycle>-<reporting_seq>-<8 hex of content hash>",
  "generated_at": iso8601, "cycle": "004",
  "code": {"git_revision", "command", "python", "packages": {name: version}},
  "ledger": {"reporting_seq", "content_sha256", "counts": {"relevant": {"human_reviewed", "machine_only"},
             "favorable": {...}, "favorable_householder": {...}}},
  "gold_recovery":  {envelope..., "tiers": {tier: {"funnel": {stage: n}, "recovery": Estimate}},
                     "union": {...}, "misses": [{"cite", "case_id", "tier", "lost_at", "detail"}],
                     "unresolved": [{"cite", "tier"}], "inventory": {"brief_doctrine": {...}}},
  "precision":      {envelope..., "sampling_seq", "frame_size", "n", "decided", "unresolved",
                     "precision": Estimate, "field_accuracy": {field: Estimate},
                     "joint_correctness": Estimate, "confusion": {field: {row: {col: n}}},
                     "subgroups": {"favorable_householder": {...}}, "revisions": {field: n},
                     "drift": {"checked", "changed": [case_id], "disposition"}},
  "agreement":      {envelope..., "rounds": [{"round_id", "kind": "historical"|"audit", "selection_rule",
                     "exposure", "pairs": {pair: {field: {"n", "raw": Estimate, "kappa": Estimate}}}}],
                     "excluded": [{"round_id", "reason", "cards"}], "unregistered_run_ids": [...]},
  "coverage":       {envelope..., "bands": [{"lo", "hi", "read_cases", "relevant", "unread_cases"}],
                     "scenarios": [{"name", "assumption", "estimated_relevant"}]}
}
```

`Estimate` = `{"value", "n", "lo", "hi", "status"}`. The generator assembles prose from these
fields; it never recomputes a statistic.

## 6. The rounds registry: `runs/evaluation/rounds.json`

Hand-curated, committed, frozen per evaluation by its hash in provenance. One entry per
review round: `round_id`, `kind`, `queue`, `checker`, `claude`, `astra`, `user` (a decisions
file or a saved page), `selection_rule` (the queue's section letters and their rules, in
words), `user_mode` (`card_by_card` | `bulk_adopted_astra` | `none`), `apply_run_ids`. The
tool reconciles the registry against the ledger: every reviewer-basis `run_id` in the
patches that no entry names is listed as `unregistered_run_ids`, and the evaluation refuses
to publish until each has a disposition in the registry (`"dispositions": {run_id: reason}`).
The registry is listed in full in the report.

## 7. The tool: `tools/evaluate.py`

`--cycle 004 --audit runs/audit-cycle-004 --rounds runs/evaluation/rounds.json --out
reports/evaluation-cycle-004`. Loads inputs, calls `evaluate`, validates the JSON against
the schema, then writes `.json` and `.md` together; a validation failure writes nothing.
Refuses to overwrite an existing `.json` unless `--force`, which first renames the existing
pair to `-rev<N>`. A missing audit directory makes measures 2-3 `unavailable` (the report
says so); the evaluation still publishes, so the gold, agreement and coverage numbers can be
read before the audit is done.

The markdown: a one-screen headline table (measure, headline estimate with interval,
denominator, uncertainty type), then one section per measure (what was measured; the
tables; denominators and exclusions; limitations verbatim; provenance list), then the
registry. Numbers in tables, not prose.

## 8. Testing

- `stats.py` against known values: kappa on a textbook 2x2 (e.g. the Cohen 1960 example),
  Wilson on published cases, the undefined case.
- Each measure on synthetic fixtures built in the test (a small view, gold rows, a sample
  manifest, outcomes, a registry with two rounds), asserting values, denominators,
  exclusions, statuses and provenance; incomplete audits, duplicate ids, undefined kappa,
  registry omissions, and drift failures.
- One frozen regression fixture: shard-02 round 3's queue, checker, Claude, Astra and user
  files copied under `tests/fixtures/evaluation/`, with agreement numbers checked by hand
  once and pinned with the input hashes and `method_version`.
- Contract test: a composed `Evaluation` validates against `schema.json`; a deliberately
  broken one fails.
- Sampler: deterministic draw for a seed; the frame excludes reviewed records; the manifest
  never rewrites.
- Audit apply: equal-value confirmations write reviewer `set` patches; the drift check
  refuses; `unresolved` skips; `--assisted-by` refused.
- Page: the lock-then-reveal flow and the saved state shape, verified headless as before.
- Live smoke: `evaluate` on the committed ledger and registry, unpinned, asserting only
  that the JSON validates and the headline renders; it does not skip when the audit is
  absent (measures 2-3 read `unavailable`).

## 9. Sequencing

1. Package skeleton, stats, types, schema, gold, coverage, agreement, registry, tool (an
   evaluation publishes with measures 2-3 unavailable).
2. Sampler, blind export, audit brief, first-pass audit mode, three-way per-field mode.
3. Draw the sample (the user gives the seed); run the two model passes isolated.
4. Audit page; the user reads all 150 blind; apply; outcomes.
5. Precision measure; re-publish the evaluation with `--force`.

## 10. Parked (not in scope)

- `keep` writes no field patch, so a kept field carries no field-level human provenance and
  the protection rule does not cover it against a later machine write (all rounds to date).
  Fix as its own bounded change: `keep` writes a reviewer `set` of the current value.
- The historical rounds' exposure (readers saw machine values and the checker) is a fact
  the appendix must state; it is not repaired here.
- Ledger patch log size (51.6 MB, over GitHub's recommendation): split or LFS before Stage 4
  adds the audit and the appendix runs.
- The deep-tail screen; the codebook "centrality" signal.
