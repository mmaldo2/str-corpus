# Stage 3B slice 1: subscription reader, codebook v3, reference v2, remeasurement

Date: 2026-09-05. Status: approved in conversation (design calls A, B, C answered 2026-09-05).
Predecessor: docs/superpowers/specs/2026-09-04-stage-3a-reader-driver-design.md (the driver this
slice extends). Authority on conflicts: this spec, then ADR-0007 (amendment 2026-09-05), ADR-0004,
CONTEXT.md.

## 1. Goal

Make the reader run on the user's Claude subscription through the Claude Code CLI, repair the
three measurement defects the polarity diagnosis found (quote-gate erasure over formatting,
relevance leaking into polarity, undefined `mixed`), harden the kit reference with the user's
adjudications, and remeasure the finalists under a pre-registered bar so `reader.model` is pinned
on evidence before the cycle-004 map is read.

Out of scope (slice 2): the cycle-004 map runner and its per-cell budget, the map's review queue,
ledger admission of map records, the checker sampling run at scale.

## 2. Decisions inherited (binding)

- D1. The reader runs on the Claude subscription via `claude -p` as a subprocess, Codex CLI on its
  subscription as checker (user decision, ADR-0007 amendment 2026-09-05; the licence concern is
  recorded there and is not re-raised in code or docs beyond that note).
- D2 (call A). `mixed` is defined as in section 5. `irrelevant` is no longer a polarity value.
- D3 (call B). The who-was-letting reference for the 154 never-reviewed kit cases is the value at
  least 4 of the 5 finalist candidates agreed on under mapper-v2; the remaining splits go to the
  user on a second review page.
- D4 (call C). Remeasurement bar: fidelity floor 0.97; decided rate >= 0.90 per judged field;
  agreement among decided >= 0.85 macro over relevant, polarity, who_was_letting. Among survivors
  a subscription candidate wins if its macro is within 0.02 of the best; otherwise the highest
  macro wins. If no survivor clears 0.85 the highest-agreement survivor is chosen and the
  shortfall disclosed (as in 3A).
- D5. OpenRouter spend for this slice is capped at $15 total (kit reads for three candidates plus
  the winner's stability and batch-size pair if the winner is an OpenRouter model). The
  subscription has no dollar budget; its ceilings are units and wall-clock.
- D6. Reference labels the user marks `unsure` are excluded from agreement for that field only;
  the case stays in the kit for fidelity and the other fields.

## 3. Claude CLI provider

`corpus_engine/reader/providers/claude_cli.py`, class `ClaudeCliProvider`, `name = "claude-cli"`,
same shape as `CodexCliProvider` (constructor takes `cli_model`, `runner=subprocess.run`,
`timeout`, `exe`; `version()`, `is_available()`, `complete(Request) -> Response`).

Invocation (list argv, never `shell=True`; resolve `exe` with `shutil.which` so the Windows
`.cmd` shim is found):

    claude -p --model <cli_model> --output-format json --effort <effort>
           --tools "" --system-prompt <req.system or codebook default>
           --strict-mcp-config --mcp-config {"mcpServers":{}} --setting-sources ""
           --exclude-dynamic-system-prompt-sections --json-schema <req.json_schema>

with `req.user` on stdin (10 MB cap; a unit whose prompt exceeds 9 MB raises ReaderError before
the call). The subprocess environment MUST have `ANTHROPIC_API_KEY` removed so the call bills the
subscription, never an API key. Measured overhead of this invocation is ~750 input tokens per call
against ~137,000 for a bare `claude -p` (probe 2026-09-05); the flags are load-bearing and each
is named in a test.

Envelope handling: `structured_output` is the response text when present (re-serialised as
JSON), else `result`; `usage.input_tokens + cache_creation_input_tokens + cache_read_input_tokens`
is the input count, `usage.output_tokens` the output; `total_cost_usd` is recorded in
`Response.raw["list_cost_usd"]` but `Response.cost_usd` is None (unpriced: the subscription has
no marginal price) so `score_candidate` marks the candidate unpriced. `is_error: true`, a non-zero
exit, or `api_error_status` set raises ReaderError. Throttling (`api_error_status` 429 or 529, or
`result`/stderr matching usage-limit or overloaded language) is retried inside the provider with
delays [60, 300, 900, 1800, 3600] seconds; after the last delay the provider raises ReaderError
("subscription window exhausted") and the driver marks the unit failed; a later run resumes from
cache. `Response.provider_reported` records `{"provider": "claude-cli", "cli_model", "effort",
"claude_version", "session_id"}`.

Pin: `ModelPin(model_id="claude-cli/<cli_model>", family="anthropic", provider_name="claude-cli",
precision=None, extra={"effort": "low", "cli_model": <full model name>})`. Full model names
(`claude-sonnet-5`, `claude-opus-5`), never aliases, so the pin label is reproducible.

## 4. Request schema

`corpus_engine/reader/schema.py` exposes `record_schema(codebook) -> dict`: a JSON Schema for
`{"records": [Record, ...]}` where Record requires `case_id`, `relevant`; `polarity` is
`enum [favorable, adverse, mixed, null]`; `who_was_letting` is `enum [householder,
commercial_operator, non_resident_owner, unclear, null]`; `quotes` is an array of
`{text: string, supports: array of enum(judged fields + relevant)}` with `minItems 1` when
`relevant` is true (expressed with `if/then`); other fields as mapper-v3 lists them. The schema is
attached to every Request by the planner (`Request.json_schema`); OpenRouter passes it as
`response_format.json_schema`, the CLI as `--json-schema`. `parse.py` accepts both the wrapped
object and a bare array. A schema-validated response can still fail the gate (quote not verbatim);
what it can no longer do is omit `supports` for a judged field it filled.

Cache key widened now, while every read is being re-bought anyway:
`sha256(codebook_sha | pin.label | unit.id | sorted case ids | prompt | schema sha | max_tokens
| effort)`. A test pins the composition. The 3A cache (`data/reader/cache/`) stays on disk for
provenance of measurement v1 and is not read by v2 keys.

## 5. Codebook mapper-v3

`domains/str-right-to-let/codebooks/mapper-v3.md`, `schema_version: 3`, derived from mapper-v2
with these changes and no others:

- Polarity values: `favorable | adverse | mixed | null`. For `relevant: false` records: polarity
  null, who_was_letting null, quotes optional, one-line notes. A relevance miss is scored once.
- Definition added verbatim: "Mixed means the same opinion both recognizes the owner's freedom to
  let on one point and restricts it on another, and both are holdings rather than remarks in
  passing. If only one side is a holding, follow the holding and note the tension in the summary.
  An owner who wins on a ground unrelated to letting is not favorable; judge only what the court
  decided about letting."
- Support rule made explicit with a worked example: `supports` is an array of field names; one
  quote may support several fields; every non-null judged field MUST appear in some quote's
  `supports`; "a judged value not named in any quote's supports list will be erased by the
  verifier". Example shows `"supports": ["polarity", "characterization"]`.
- `who_was_letting` vocabulary unchanged from v2 (non_resident_owner stays: it is the fact
  pattern the suit turns on).
- Header carries `validated_norm_version` as v2 does.

CONTEXT.md polarity entry gains the `mixed` definition and the sentence "A case the reader finds
irrelevant carries no polarity." ADR-0004 gets a one-paragraph amendment pointing here.

## 6. Scoring v2

`corpus_engine/reader/measure.py` reports per field (relevant, polarity, who_was_letting):
`decided_rate` = predictions non-null after the gate over reference-decided cases;
`agreement_decided` = agreement over cases where both sides are decided. Polarity and
who_was_letting are computed only over cases the reference marks relevant AND the prediction
marks relevant. `macro` = mean of the three `agreement_decided` values. Fidelity unchanged.
`select_reader` implements D4 (decided-rate floor, macro bar, subscription tie-break within 0.02,
shortfall rule) and takes a set of subscription candidate labels. Manifest v2 records both
numbers per field, `accepted` and `accepted_full`, per-unit cache keys, per-candidate timeout and
effort, and for subscription candidates `list_cost_usd` beside `priced: false`. Measurement v2
lives in `data/reader/measurement-v2/`; v1 is untouched.

## 7. Reference v2 and kit v2

- `tools/apply_reference_review.py --saved <html> --field-order polarity,who_was_letting` reads
  the decision state a saved review page embeds (the STATE marker make_reference_review.py
  writes), validates it, and emits ledger patches with reviewer basis (the user) exactly as
  pipeline/polarity_review.py's apply path does: `keep` -> no patch; `adopt`/`set` -> set the
  field; adopting `irrelevant` on polarity -> `relevant: false`, polarity null, who null;
  `unsure` -> a `needs-review:<field>` flag and exclusion from agreement (D6). Patches replay
  cleanly (`Ledger.apply` validates on a fresh replay).
- `tools/consensus_reference.py` computes the who-was-letting consensus (D3) from the v1 cache
  via the measurement tool's offline helpers: >= 4 of 5 finalists agree -> a machine-basis patch
  (`model-consensus:mapper-v2:4of5`); otherwise the case goes to a second review page produced by
  make_reference_review.py from a contested-style JSON. The tool prints both counts.
- `tools/build_reader_kit.py --case-ids-from data/reader/kit-v1/kit.json --out data/reader/kit-v2`
  rebuilds the kit with the SAME 195 cases and the patched ledger labels, records per case which
  fields are excluded (D6), writes the sha; `domain.yaml` `reader.kit_path`/`kit_sha256` move to
  v2. kit-v1 is never edited.

## 8. Remeasurement (pre-registered here, before any read)

Candidates: `claude-cli/claude-sonnet-5`, `claude-cli/claude-opus-5` (subscription);
`openai/gpt-5.6-terra`, `z-ai/glm-5.3` (pinned bf16/fp8 as in 3A), `google/gemini-3.7-flash`
(OpenRouter, under D5). Codebook mapper-v3, kit v2, batch size 18, effort low, max_tokens 64000,
read timeout 1500 s for all. Order: a one-batch dry run on the cheapest OpenRouter candidate and
one on Sonnet through the CLI, both inspected (parse, gate, schema, manifest) BEFORE the field
runs. Then all five on the kit; stability (50-case sample, two reads, >= 0.90 per field on
decided answers) and the 18-vs-5 batch-size pair on the winner only. Bar and tie-break: D4.
Outputs: `reports/reader-measurement-v2.md`, manifest v2, `reader.model` re-pinned, mapper-v3
stability record, ADR-0007 result note, handoff item 7 updated.

## 9. Driver residuals folded in

`store_norm_version` becomes a required `Reader` argument (3A final review I10). The split loop
catches `Exception` like the unit loop, keeping the paid first half (N6). `resume_command` for
`batch_extraction` plans names the measurement tool only when the plan came from it; otherwise
an empty string with the manifest note (N4 stays for slice 2's map runner).

## 10. Testing

Unit: provider (scripted runner: argv flags each asserted, env without ANTHROPIC_API_KEY,
envelope parsing incl. structured_output vs result, error and throttle paths with a fake clock);
schema (valid/invalid records, both parse shapes); cache key composition; scoring v2 on a
synthetic reference (decided rate, relevance-gated polarity, unsure exclusion, tie-break within
0.02, shortfall); apply_reference_review on a saved-page fixture (all four decisions, irrelevant
adoption); consensus tool on a fixture; kit v2 build determinism (same ids, new sha). Render
golden for mapper-v3 (byte-stable). The live dry runs in section 8 are the integration test and
are recorded in the report.

## 11. Constraints

LF/UTF-8 no BOM/trailing newline; never commit .env, data/db/, data/raw/, data/reader/cache/,
runs/*/batches|extractions; no paid request outside tools/measure_reader.py; the OpenRouter
ceiling is enforced before every paid request; subscription calls never carry an API key; kit-v1
files are never edited.
