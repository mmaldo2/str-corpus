# STR Historical Corpus Pipeline

Agentic MapReduce over the American case law record, recovering historical
authority on the right to let one's property short-term. Spec:
`sprint-one-handoff-corpus-pipeline (1).md` (including the dated Amendments
block, which governs on conflict); legal context:
`str-property-rights-corpus-research (1).md`.

## Reproduce from a clean machine

```powershell
python -m venv .venv                       # Python 3.11
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -r requirements-ranker.txt  # optional: GPU/hub deps for
                                            # corpus_engine\ranker\reranker.py and tools\pin_reranker.py only
.venv\Scripts\python pipeline\download.py  # static.case.law volume zips -> data/raw/  (~20 GB)
.venv\Scripts\python pipeline\ingest.py    # HTML casebody -> data/db/corpus.db
.venv\Scripts\python pipeline\index.py     # FTS5 + Qwen3-Embedding-0.6B (GPU)
.venv\Scripts\python pipeline\build_gold.py
.venv\Scripts\python -m pytest tests\
# STOP: human review of selectors/selectors.yaml before any shard run
.venv\Scripts\python pipeline\shard.py --run-id <run-id> --dry-run  # plan coverage fingerprint
.venv\Scripts\python pipeline\shard.py --run-id cycle-001-shard-01
.venv\Scripts\python pipeline\rank.py --run-id <run> [--ranker <id>]  # re-score + re-pack an existing run's batches
# Map/Reduce driver: see runs/README (headless claude CLI + codex checker)
.venv\Scripts\python pipeline\verify_quotes.py --run-id <run>
.venv\Scripts\python pipeline\eval_recall.py --run-id <run>
```

## Per-cycle review pipeline (after verify_quotes)

```powershell
$R = "cycle-00N-shard-01"
.venv\Scripts\python pipeline\build_review_queue.py --run-id $R     # queues + fuzzy side-by-sides
.venv\Scripts\python pipeline\pre_review.py fuzzy        --run-id $R  # mechanical OCR classification
.venv\Scripts\python pipeline\pre_review.py fuzzy-review --run-id $R  # reader: ocr-ok|mismatch + reason
.venv\Scripts\python pipeline\pre_review.py adjudicate   --run-id $R  # third reader on disagreements
.venv\Scripts\python pipeline\pre_review.py remap        --run-id $R  # re-extract quote-gate-nulled records
.venv\Scripts\python pipeline\verify_quotes.py --run-id cycle-00N-remap
.venv\Scripts\python pipeline\remap_check.py --run-id $R              # codex check on re-mapped records
#   (stage runs/cycle-00N-remap/review-queue.json from remap-disagreements, then:)
.venv\Scripts\python pipeline\pre_review.py adjudicate --run-id cycle-00N-remap
.venv\Scripts\python pipeline\make_review.py --run-id $R               # self-saving review page
# human reviews + saves in the artifact -> extract decisions-final.json, then:
.venv\Scripts\python pipeline\apply_adjudications.py --run-id $R       # data/ledger/cycle-00N.jsonl
```

Every machine recommendation on the page (fuzzy verdicts, disagreement
adjudications, re-map contests) is a recommendation only; the human's
saved decision is the record.

## Layout

Per spec §3. `selectors/selectors.yaml` is the load-bearing versioned artifact;
never edit a selector in place past a shard run — bump `version`. `data/raw`
and `data/db` are gitignored; `data/raw/manifest.jsonl` records exactly which
volume zips (URL, sha256, bytes) were ingested, for reproducibility.

`corpus_engine/` is the domain-agnostic engine (ADR-0010): `store` (paths,
connections, schema), `domain` (loads `domains/<name>/domain.yaml`),
`verification` (the quote gate), `selector.packing` (batch packing),
`reader` (the provider-neutral reader driver: `driver` with the read loop,
`render`/`parse`/`gate`/`cache`, the `Provider` and `CaseSource` ports in
`ports.py`, adapters under `reader/providers/`, and `measure` for the
pre-registered scoring), and
`ledger` (the system of record, ADR-0002: `data/ledger/cycle-*.jsonl` are the
snapshot, `data/ledger/patches.jsonl` the append-only log,
`data/ledger/manifest/` the per-cycle account of every case read). Scripts in
`pipeline/` are thin wrappers during the staged refactor. Every count comes
from `open_ledger().view().counts()`; never compute one by hand.

Tools: `tools\measure_reader.py` runs the pre-registered reader-model
measurement (ADR-0007, bar D4) over the frozen kit and writes a manifest under
`data/reader/`. **Measurement v2 is the current one**: kit v2
(`data/reader/kit-v2/kit.json`, 195 cases) under codebook `mapper-v3`, five
finalists, manifest `data/reader/measurement-v2/manifest.json`, result in
`reports/reader-measurement-v2.md`. Winner `google/gemini-3.7-flash`, pinned as
`reader.model` in `domains/str-right-to-let/domain.yaml`. Measurement v1
(ten candidates, kit v1, `mapper-v2`, `reports/reader-measurement.md`) is frozen
and superseded.

> **Both measurements are finished and paid for** — v1 $41.67 of an approved $50,
> v2 $6.91 of a $10 ceiling plus 46 subscription units at no charge. Running any
> of the lines below again spends real money on any unit not already in
> `data/reader/cache`, and `--only <model id>` re-buys that candidate. A paid
> re-run merges per candidate into the existing manifest and re-decides the
> winner over every candidate on record, so it cannot drop the others - but it is
> still spend, so read the ceiling guard in `resolve_prior_spend` before typing
> it. `--max-usd` may never exceed $15 (spec decision D5), and it is a ceiling per
> MANIFEST DIRECTORY: prior spend is read only from the manifest the run writes,
> so a paid run pointed anywhere but `data/reader/measurement-v2` is refused
> unless `--allow-measurement-dir` is passed with it.

```
:: what v2 ran, in order. THESE SPEND.
.venv\Scripts\python tools\measure_reader.py --dry-run google/gemini-3.7-flash --max-usd 10
.venv\Scripts\python tools\measure_reader.py --dry-run claude-cli/claude-sonnet-5 --max-usd 10
.venv\Scripts\python tools\measure_reader.py --max-usd 10 --prior-spend-usd 0.02
.venv\Scripts\python tools\measure_reader.py --max-usd 10
```

The last line is the merge pass, run after the strict-schema fix landed. It is the
bare command over all five candidates - GPT live under the new dialect, the other
four replayed from cache - not `--only openai/gpt-5.6-terra`, which could not have
produced the manifest that is committed.

A `--dry-run <candidate>` buys one kit batch, writes an inspection file, and
stops without selecting anything; two of them (one OpenRouter candidate, one
subscription candidate) are the gate the spec puts before any field run. A
`claude-cli/*` candidate runs on the user's Claude subscription through the CLI
and is budgeted in units and wall clock, not dollars.

To recompute a manifest's derived records instead - **no request of any kind, no
spend**:

```
.venv\Scripts\python tools\measure_reader.py --annotate-only
.venv\Scripts\python tools\measure_reader.py --annotate-only ^
  --measurement-dir data/reader/measurement-v1 --codebook mapper-v2 ^
  --kit-path data/reader/kit-v1/kit.json ^
  --stability-sample data/reader/kit-v1/sample-50.json
```

The second line is how v1 is re-derived now that `domain.yaml` names `mapper-v3`
and kit v2 by default; without those three flags `--annotate-only` would score
v1's cache against v2's kit. Which cache-key composition each manifest is
addressed with is read off the manifest itself (`cache_key_version`; v1 predates
the field and is recognised by having no `schema_sha`), so neither line can be
pointed at the other's cache. Both reproduce their manifest byte for byte apart
from the derived records the annotation exists to add.

Tests: `.venv\Scripts\python -m pytest tests -q`. Byte-for-byte
characterization tests reproduce cycle-003 batches, verified files, and all
three ledgers from `tests/golden` and `tests/fixtures`.
