# Stage 2C — Candidate ranking: design

**Date:** 2026-09-04. **Status:** approved in conversation, pending written review.
**Authority above this document:** `docs/adr/0001`, `0003`, `0005`, `0009`, `0010`, `0011`;
`docs/design/2026-09-01-module-interfaces/README.md`; `CONTEXT.md`.
**Depends on:** Stage 2B merged (main `b56c2ed`); cycle-004 shard `cycle-004-shard-01`
(946 units, 40,115 signals, 1,845 batches, 32,795 unread candidates).

## 1. Purpose

Order the candidate pool before mapping so that a fixed map budget reads the cases most
likely to be relevant letting law, without changing which cases are candidates. The
precision trend across cycles (28% → 12% → 6.6%) and a cycle-004 pool four times larger
than any before make ordering the difference between a usable map step and an
unaffordable one.

Decisions taken in the brainstorm:

| Decision | Choice |
|---|---|
| What ranking changes | **Order only.** Batches are emitted in ranked order within each era × jurisdiction cell; the map step budgets how many batches to read. The candidate pool and the `signals` table are untouched. |
| Positive label | **Ledger relevant** (710 today), both polarities. Human-reviewed records weighted 3, machine-only 1. Negatives: cases read and marked irrelevant (5,406 today), weight 1. |
| Held-out set | A frozen, stratified 25% slice of the labelled reads (`data/eval/ranker-heldout-v1.jsonl`), never trained on. The recall gold (v1, 183 entries) keeps its separate recall role. |
| Reranker | Built as an adapter and **measured on held-out only**; switched on only if it clears a pre-registered bar (§6). Used as shipped, never tuned. |
| Trigram side-index | Deferred to a follow-on; it is candidate generation, not ranking. |
| Approach | Feature classifier (logistic regression) behind a `Ranker` port, with a fixed-weight fusion baseline it must beat. |

## 2. Vocabulary

- **Candidate**: a non-duplicate case with at least one signal in the run and not already read.
- **Labelled read**: a case with a verdict — ledger relevant (positive) or extraction marked
  irrelevant (negative). A case the ledger retracted to not-relevant is a negative.
- **Cell**: one (era, jurisdiction) pair, as in the tradition matrix.
- **Ranker**: a module implementing the port in §3; identified by `ranker_id`.
- **Held-out slice**: the frozen evaluation set of labelled reads. **Training set**: all
  other labelled reads.

## 3. Module: `corpus_engine/ranker/`

One seam, one interface:

```python
class Ranker(Protocol):
    ranker_id: str                      # e.g. "null", "fusion:v1", "classifier:v1", "qwen3-reranker-4b:<rev7>"
    def digest(self) -> str             # 16 hex; model bytes + config, "" for null
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]
```

Contract: every requested id gets a finite float, higher is better; ids are scored from
signals of `run_id` only; `score` performs no writes; two calls with the same inputs
return identical values.

Files:

| File | Responsibility |
|---|---|
| `ports.py` | `Ranker` protocol; `NullRanker` (legacy density order); `FusionRanker` (§5.3). |
| `features.py` | `feature_layout(domain, selectors) -> FeatureLayout`; `case_features(conn, run_id, case_ids, layout) -> np.ndarray`. One function shared by training and scoring. |
| `labels.py` | `labelled_reads(domain, runs_dir, ledger) -> list[Label]`; `build_heldout(...)`, `load_heldout(path) -> HeldOut`; hash checks. |
| `classifier.py` | `ClassifierRanker(model_path)`; `train(...)`; model file format. |
| `reranker.py` | `QwenReranker(model, revision, query, *, batch=8)`; refuses to load if a query embedder is resident. |
| `evaluate.py` | `average_precision`, `precision_at`, per-cell and human-only views; `compare(baseline, candidate, heldout) -> Report`. |
| `store.py` (`corpus_engine/store.py`) | `rankings` table DDL (§7). |

Domain configuration (`domains/str-right-to-let/domain.yaml`):

```yaml
ranking:
  default: classifier          # null | fusion | classifier | reranker
  classifier_version: v1
  fusion: {lexical_weight: 0.5, cosine_weight: 0.5}
  reranker:
    model: Qwen/Qwen3-Reranker-4B
    revision: <pinned sha, resolved by tools/pin_reranker.py>
    query: >
      A judicial opinion about a householder, owner, or lessee letting rooms,
      lodgings, or a dwelling to lodgers, boarders, roomers, or short-term
      occupants, or about regulation of that practice.
    bar_ap_delta: 0.05
  heldout: data/eval/ranker-heldout-v1.jsonl
  heldout_sha256: <recorded by tools/build_ranker_heldout.py>
```

`corpus_engine` stays domain-agnostic: the query text, weights, and file names come from
the domain.

## 4. Labels and the held-out slice

**Sources.** Positives: `open_ledger(domain).view()` records with `relevant == True`
(weight 3 when `reviewed(cid)`, else 1). Negatives: every extraction record under
`runs/*/extractions*/*.json` with `relevant` false and a case id not relevant in the
ledger (weight 1). Duplicates (`is_duplicate_of IS NOT NULL`) and cases with no verdict
are excluded.

**Held-out build** (`tools/build_ranker_heldout.py`, run once): stratify labelled reads by
(era, jurisdiction, label), sample 25% of each stratum with `random.Random(20260904)`,
round up so every stratum with ≥ 2 members contributes ≥ 1; write one JSON line per case
`{case_id, label, weight, reviewed, era, jurisdiction}`; print counts per stratum and the
file's sha256. The hash is recorded in the ranker manifest and in an amendment to
ADR-0003. The file is committed and never edited; a v2 is a new file.

**Discipline.** `train()` loads the held-out file, verifies its sha256 against the value
in `domain.yaml` (`heldout_sha256`), and refuses to train if any held-out id appears in
the training ids or if the hash differs.

**Same run for both sides.** Features for training, held-out evaluation, and scoring are
all computed from the signals of the run being ranked (`run_id`), so the two sides see one
engine. Labelled reads that carry no signal in that run are dropped from training and
from the evaluation view (counts reported in the manifest); today 2,832 of the 6,116
labelled reads carry cycle-004 signals (562 positive, 2,270 negative). The held-out file
still freezes ids, not features, so a later run re-derives features for the same ids.

**Amendment, 2026-09-04 (union of runs).** The paragraph above is superseded: features for
training, held-out evaluation, and scoring are computed from the **union of a case's
signals across all runs**, not the signals of `run_id` alone. `case_features` takes
`case_ids` and queries `signals` by case id with no `run_id` filter. The cycle-004 batch
pool is not self-contained: at re-pack time a live query found 5,606 of the pool's 32,795
unread cases carry no `cycle-004-shard-01` signal at all, only signals from cycles
001-003 (the plan's working note put this figure at 2,799; the live count at report time
was higher, see `reports/ranking-cycle-004.md`). Scoping features to `run_id` would zero
out every feature for those cases regardless of what an earlier cycle's selectors found.
On the label side the same widening is required for a different reason: every labelled
read has signals only from the run it was actually read under (its own cycle), never from
`cycle-004-shard-01`, so a `run_id`-scoped query would starve training of features
entirely. The union keeps one feature-computation path for both sides, at the cost of a
case's features reflecting whichever selectors have ever run over it rather than only the
current run's.

**What it measures.** Ranking quality within the pool the old selectors surfaced. It says
nothing about recall; recall stays with the gold set and `pipeline/eval_recall.py`.

## 5. Features, model, baseline

### 5.1 Features (`features.py`)

Computed per case from existing tables, from the union of the case's signals across all
runs (see the §4 amendment), not scoped to a single `run_id`:

| Block | Features |
|---|---|
| Selector evidence | one indicator per active selector `(id, version)` that fired; count of distinct selectors; per vector selector its best cosine (0 if absent) |
| Case metadata | `pagerank_pct` (+ missing indicator); era one-hot; jurisdiction one-hot; `log1p(len(norm_text))`; `ocr_confidence` (+ missing indicator) |
| Text | the dequantized 1024-d vector of the case's best chunk: the chunk of its highest-cosine signal, else the case's first chunk |

The layout is derived from the domain (eras, jurisdictions), the active selector list, and
the embedding dim, and is stored in the model manifest. Deliberately excluded: the
case's raw signal count from the *current* engine (it would leak the new engine's habits
into labels made under the old one). Missing values are explicit indicators, never silent
zeros.

### 5.2 Model (`classifier.py`)

`sklearn.linear_model.LogisticRegression(penalty="l2", class_weight="balanced",
max_iter=2000)`, `C` chosen by 5-fold cross-validation **inside the training set** over
`{0.01, 0.03, 0.1, 0.3, 1, 3}` on average precision; sample weights from §4. Features are
standardized with statistics from the training set only. `train()` writes
`data/ranker/<version>/model.npz` (coefficients, intercept, scaler mean/scale) and
`manifest.json`:

```json
{"ranker_id": "classifier:v1", "trained_at": "...", "commit": "...", "layout": {...},
 "train": {"n_pos": ..., "n_neg": ..., "sha256_ids": "..."}, "heldout": {"path": "...", "sha256": "..."},
 "cv_C": 0.1, "metrics": {"classifier": {...}, "fusion": {...}}}
```

`ClassifierRanker.digest()` = sha256 of `model.npz` bytes, first 16 hex.

### 5.3 Fusion baseline (`ports.py`)

`score = w_l * lexical_density + w_c * best_cosine`, where `lexical_density` = distinct
lexical selectors fired ÷ number of active lexical selectors, and `best_cosine` = max
cosine over the case's vector signals (0 if none). Weights from `domain.yaml`. No
training. It is the number the classifier must beat.

### 5.4 Ship rule

`classifier:v1` is the domain default only if its held-out average precision exceeds the
fusion baseline's on **both** views (all labels; human-reviewed labels only). Otherwise
`fusion:v1` is the default and the manifest says so.

## 6. Reranker and its pre-registered bar

`QwenReranker` wraps `Qwen/Qwen3-Reranker-4B` at a pinned revision via
`sentence_transformers.CrossEncoder` (or the model's documented `transformers` scoring
recipe if `CrossEncoder` does not support it — the adapter hides which). One pair per
case: the domain query (§3) against the case's best chunk text (same chunk as §5.1).
Score = the relevance logit. Batch 8, fp16, GPU; refuses to load if
`torch.cuda.memory_allocated()` shows another 4B-class model resident.

**Bar (recorded here before any measurement):** the reranker becomes the default only if
its held-out average precision exceeds the classifier's (or the fusion baseline's, if that
is the shipped default) by **≥ 0.05 absolute on both views**. It is never tuned. The
measurement (`tools/measure_reranker.py`, ~1,500 pairs, minutes on the RTX 5080) writes
its numbers into `data/ranker/reranker-<rev7>/manifest.json` and the ranking report
whichever way it goes.

Cost of a full-pool rerank if it clears: ~32,795 pairs ≈ 30 min locally. Hosting is not
used: the job is small, the model must stay pinned, and rerank endpoints are not a
standard hosted API.

## 7. Packing, persistence, determinism

`build_batches(conn, run_id, *, gold_ids, exclude_ids, batch_size=18, ranker=None)`:

- `ranker=None`: the current code path, byte-for-byte (`tests/test_packing_char.py`).
- with a ranker: score all candidates once; write `rankings` rows in one transaction
  (`INSERT OR REPLACE`); within each cell sort by `(-score, case_id)`; order batches by
  `(-mean_score, cell_key)`; gold cases keep their existing front bump. Each batch JSON
  gains `"ranker_id"` at the top and `"rank_score"` per case.
- scores are float32 rounded to 6 decimals before sorting (a last-ulp BLAS difference
  cannot reorder two cases).

`rankings(run_id TEXT, ranker_id TEXT, case_id INTEGER, score REAL, ts TEXT,
PRIMARY KEY (run_id, ranker_id, case_id))` — added to `store.SCHEMA` and `migrate()`.

The shard manifest gains `"ranker": {"ranker_id", "digest"}`. `pipeline/shard.py` gains
`--ranker <id>` (default: the domain's) and `--no-rank`. New `pipeline/rank.py --run-id
<run> [--ranker <id>]` re-scores and re-packs an existing run's batches **without
re-running selectors** (deletes and rewrites the batch directory; signals untouched).

Determinism (ADR-0009): same model file + same signals + same candidate set ⇒ identical
`rankings` rows and identical batch bytes.

## 8. Errors

- Model layout ≠ current selectors/domain ⇒ refuse with the differing selector or field
  named (means retrain, not score).
- Held-out hash mismatch or overlap ⇒ refuse to train.
- Reranker with a resident 4B model ⇒ refuse to load.
- A candidate with no chunk at all ⇒ text block zeros + missing indicator (logged count).

## 9. Testing

Fixtures only (`tests/fixtures/corpus-tiny.db`, `cycle-003-signals.db`, small synthetic
label files); the real reranker runs only in `tools/measure_reranker.py`.

- golden: `build_batches(ranker=None)` bytes unchanged; `NullRanker` order == density order.
- port: every adapter returns finite floats for every id; determinism across two calls.
- features: training and scoring produce identical vectors; layout round-trips through the
  manifest; lexical-only case gets its first chunk's vector; missing indicators set.
- labels/held-out: stratification counts; hash refusal; overlap refusal; retracted case is
  a negative; weights.
- classifier: `train()` on a synthetic labelled fixture beats chance; model file loads and
  scores; layout mismatch refused with the selector named.
- packing with a ranker: sort order, batch order, `rank_score`/`ranker_id` present,
  rounding tie test, `rankings` rows written once.
- reranker adapter with a fake cross-encoder: pair construction, batching, scores keyed by
  case id; resident-model refusal.
- `pipeline/rank.py`: re-pack leaves `signals` and `coverage_v2` unchanged.

## 10. Rollout (this stage maps nothing)

1. Build and freeze `ranker-heldout-v1.jsonl`; amend ADR-0003 with its hash and role.
2. Train `classifier:v1`; record held-out metrics vs. fusion; apply the ship rule (§5.4).
3. Pin the reranker revision; measure on held-out; apply the bar (§6).
4. `pipeline/rank.py --run-id cycle-004-shard-01` with the winning ranker; verify signals
   and coverage untouched; batches carry `ranker_id`.
5. `reports/ranking-cycle-004.md`: metrics table (fusion / classifier / reranker × all /
   human-reviewed), the decision, per-cell top-50 precision, and the pool's score
   distribution so the map budget can be chosen per cell.

## 11. Out of scope

Mapping; the trigram side-index; polarity ranking; TF-IDF text features (add only if the
held-out numbers show the chunk vector is not carrying the text signal); any change to
selectors, signals, or coverage.
