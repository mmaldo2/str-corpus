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

Tools: `.venv\Scripts\python tools\measure_reader.py --max-usd 50` runs the
pre-registered reader-model measurement (ADR-0007) over the frozen kit and
writes `data/reader/measurement-v1/manifest.json`; result in
`reports/reader-measurement.md`.

> **The measurement is finished and paid for ($41.78 of the approved $50).**
> Running that line again spends real money on any unit not already in
> `data/reader/cache`, and `--only <model id>` re-buys that candidate. To
> recompute the manifest's derived records instead, use
> `.venv\Scripts\python tools\measure_reader.py --annotate-only`, which issues no
> request of any kind. A paid re-run now merges per candidate into the existing
> manifest and re-decides the winner over every candidate on record, so it can no
> longer drop the other nine - but it is still spend, so read the ceiling guard in
> `resolve_prior_spend` before typing it.

Tests: `.venv\Scripts\python -m pytest tests -q`. Byte-for-byte
characterization tests reproduce cycle-003 batches, verified files, and all
three ledgers from `tests/golden` and `tests/fixtures`.
