# Selector engine — common-caller design

Summary:
1. Common caller sees two calls: shard(store, domain, run_id) and attribution(store, case_ids); coverage diffing, runner dispatch, embedding passes, seed hashing, ranking, batch packing hidden.
2. Selector = frozen data with opaque params; each kind has a runner behind an internal registry seam.
3. Ranking is a separate stage (Ranker) applied only during batch packing, never to the signals table => attribution is pre-truncation by construction.
4. Two real seams: QueryEmbedder (local pinned model / recorded fixture) and Ranker (priority / fusion+reranker). CorpusStore is an injected parameter, not a seam.
5. pack_batches over a frozen cycle-003 signals fixture must reproduce batch-NNN.json byte-for-byte incl. indent=1 and batch_id as last key.

## Types
```python
SelectorKey = tuple[str, int]
@dataclass(frozen=True, slots=True) class Partition: era: str; jurisdiction: str
@dataclass(frozen=True, slots=True)
class Selector:
    id: str; version: int; kind: str; concept: str; polarity: str
    era_scope: tuple[str, ...]; jurisdiction_scope: tuple[str, ...]
    params: Mapping[str, Any]; author: str; rationale: str
    @property
    def key(self) -> SelectorKey
@dataclass(frozen=True, slots=True) class SeedSet: name: str; case_ids: tuple[int, ...]; hash: str  # sha256:16hex
@dataclass(frozen=True, slots=True) class Signal: case_id; selector_id; selector_version; matched_text; char_span; chunk_id; cosine; partition
@dataclass(frozen=True, slots=True) class SignalRef: selector_id; selector_version; run_id; cosine
@dataclass(frozen=True, slots=True) class RunStamp: run_id: str; ts: str
@dataclass(frozen=True, slots=True) class Skip: key; partitions; reason  # index_incomplete|mixed_embedding_model|seed_unavailable
@dataclass(frozen=True, slots=True) class ShardPlan: stamp; steps: tuple[(SelectorKey, Partition, seed_hash)]; skips; selectors_hash
@dataclass(frozen=True, slots=True) class ShardReport: plan; signals_written; skips; batches_written; batch_dir; cases_batched; cases_excluded_already_read

def shard(store, domain, run_id, *, dry_run=False, stamp=None, embedder=None) -> ShardReport
def attribution(store, case_ids) -> Mapping[int, tuple[SignalRef, ...]]   # missing cases map to ()
def plan(store, domain, *, stamp=None) -> ShardPlan
def pack_batches(store, domain, run_id, *, ranker=None) -> ShardReport
def probe(store, domain, selector, partition, *, limit=50, embedder=None) -> tuple[Signal, ...]
KIND_SPECS: Mapping[str, KindSpec]; def parse_selector(raw, *, eras, jurisdictions) -> Selector

class SelectorDomain(Protocol):
    name; selectors: Sequence[Selector]; eras; jurisdictions; batch_size: int; ranking: Ranker
    exclude_already_read: bool; runs_dir: Path
    def seed_set(self, ref) -> SeedSet; def priority_ids(self) -> frozenset[int]
```
CorpusStore surface: fts_match, partition_cases, norm_text, chunk_vectors(partitions), embedding_meta(partitions), cites(case_ids, direction), write_signals, read_signals, coverage, mark_covered, already_read_case_ids.

## Invariants
Signals never truncated by ranking. (selector-version, partition, seed_hash) commits signals + coverage in one transaction. Skipped pairs get no coverage row. char_span locates; matched_text is padded context (pad=200). Plan order selector-major then era then jurisdiction (embedding pass computed once per selector-version). Idempotent. Coverage PK gains seed_hash ('' unseeded).
Errors: SelectorSpecError at plan; MixedEmbeddingIndex => selector skipped (exception only from probe); IndexIncomplete skip; SeedSetUnavailable (< min_seeds) skip; StoreBusy propagated.
Performance: embedding matmul over the union of in-scope partitions only (not whole corpus) — at 1024d and 10+ jurisdictions the whole-corpus array would exceed 10 GB.

## Dependencies
Corpus store local-substitutable (same SqliteCorpusStore over corpus-tiny.db); QueryEmbedder true external (LocalQueryEmbedder / RecordedEmbedder); Ranker varying in-process (FusionRanker / PriorityRanker); reranker remote-owned injected into FusionRanker; domain in-process; runner registry internal.
kwic/colloc/freq stay a separate concordance module (questions about text, not selectors).

## Characterization
Fixtures: cycle-003-signals.db (signals rows + referenced cases rows — essential, since emit_batches reads ALL runs' signals), corpus-tiny.db, gold-v1, selectors v3, query-vectors-v3.npz.
Test 1: pack_batches reproduces 632 files byte-for-byte — pins group sort key str((era,jur)), intra-group (-distinct_selectors, case_id), cross-group (-gold_count, -density), BATCH_SIZE 18, batch-NNN numbering, char_span as list, indent=1, batch_id last key, no trailing newline.
Test 2: signals byte-for-byte on fixture corpus with RecordedEmbedder.
Test 3: attribution reproduces cycle-003 recall (6/9, 22/29, 17/63; Gouhenant via rent-houses-37 + embed-householder-letting-21@v2).
Test 4: coverage resume after injected failure.
Findings to log: shard.py:220 np.argsort default quicksort is not stable (ties can reorder across NumPy builds; contradicts ADR-0009) — fix kind="stable" + chunk_id tiebreak as a logged engine version bump. emit_batches rewrites the whole batch dir from all runs' signals; exclude_already_read must default True.
