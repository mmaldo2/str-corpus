# Selector engine — interface design (flexibility-maximizing)

Summary:
1. SelectorEngine presents five verbs (plan, run, batches, probe, attribution) over six frozen value types (Partition, SelectorRef, Selector, Signal, SeedSet, BatchRecipe), absorbing all of shard.py.
2. Selectors stay declarative data with an opaque params mapping; each kind's behaviour lives in a registered Retriever, so citation_graph, relevance_feedback, trigram need zero engine change.
3. Ranking is a separate composition of registered RankStages named by a BatchRecipe, applied after signals are persisted, so eval_recall always sees attribution before truncation.
4. Partition is an ordered tuple of named axes supplied by DomainSpec, making new corpora partitions (federal reporters, English Reports) and a second domain a config change rather than a schema fork.
5. Four ports earn two-plus adapters each (QueryEncoder, SeedResolver, ScorerSource, BatchSink); SQLite taken concretely; coverage rows gain a retriever fingerprint that turns ADR-0006's mixed-model rule into an enforced Deferred.

## Governing choice
A selector is declarative data with an opaque params mapping; each selector kind contributes a Retriever registered under that kind's name. The engine never reads pattern/query_text/top_k/min_cosine (today shard.py does at lines 84, 95, 140, 204, 220, 225). Ranking is NOT inside sharding: retrieval writes signals (uncapped), ranking is a separately invoked composition of named stages.

## Interface

```python
@dataclass(frozen=True, slots=True, order=True)
class Partition:
    axes: tuple[tuple[str, str], ...]   # (("era","1860-1900"), ("jurisdiction","Pa."))
    @property
    def key(self) -> str: ...

@dataclass(frozen=True, slots=True, order=True)
class SelectorRef: id: str; version: int

@dataclass(frozen=True, slots=True)
class Selector:
    ref: SelectorRef; kind: str; concept: str; polarity: str
    params: Mapping[str, Any]     # OPAQUE to the engine
    scope: ScopeExpr; seeds: SeedSpec | None; status: str
    provenance: Mapping[str, str]
    def digest(self) -> str: ...

@dataclass(frozen=True, slots=True)
class Signal:
    case_id: int; selector: SelectorRef; partition: Partition
    matched_text: str; span: tuple[int, int]; chunk_id: int | None
    score: float | None; evidence: Mapping[str, Any]   # hop_direction, seed_case_id, fts_rank

@dataclass(frozen=True, slots=True)
class SeedSet:
    origin: str; case_ids: tuple[int, ...]
    def digest(self) -> str: ...

class Retriever(Protocol):
    kind: ClassVar[str]
    def precheck(self, ctx, sel, part) -> Ready | Deferred: ...
    def fingerprint(self, ctx, sel) -> str: ...        # index/model/seed state
    def signals(self, ctx, sel, part) -> Iterator[Signal]: ...

class RankStage(Protocol):
    name: ClassVar[str]
    def apply(self, ctx, cands, cfg) -> Sequence[Candidate]: ...

class SelectorEngine:
    def __init__(self, store, domain, *, encoder, seeds, scorers=NO_SCORERS, registry=DEFAULT): ...
    def plan(self, *, scope=ALL, force=False) -> ShardPlan: ...          # pure; no writes, no model load
    def run(self, plan, run_id, ts) -> ShardResult: ...
    def batches(self, recipe: BatchRecipe, sink: BatchSink, *, run_id, select=ALL) -> BatchSet: ...
    def probe(self, sel, part, *, limit=25) -> list[Signal]: ...         # Planner surface; writes nothing
    def attribution(self, case_ids) -> Mapping[int, frozenset[SelectorRef]]: ...

@dataclass(frozen=True, slots=True)
class BatchRecipe:
    group_by: tuple[str, ...] = ("era", "jurisdiction")
    size: int = 18
    stages: tuple[tuple[str, Mapping[str, Any]], ...] = (("exclude_mapped", {}), ("density", {}), ("gold_first", {}))
    emitter: str = "batch-v1"
    def digest(self) -> str: ...
```

## Invariants
- plan() is a pure function of (domain selectors, coverage rows, scope); safe during embedding.
- Determinism: identical (domain digest, coverage state, seed digests, retriever fingerprints, recipe digest) => identical plan digest and batch bytes. Selectors iterated in (id, version) order; partitions in axis order; signals ordered (partition, case_id, selector); every stage breaks ties on case_id.
- A signal is never written without its coverage row in the same transaction; a Deferred unit writes neither.
- Coverage rows carry the retriever fingerprint; re-running a covered unit whose fingerprint differs raises CoverageConflict unless force=True. Mixed embed models => Deferred, not silent mixing.
- attribution() reads signals only, never batches. probe() writes nothing.

## Errors
SelectorSpecError from plan() before I/O; CoverageConflict from run(); RetrieverFailed wraps retriever exceptions; Deferred is a value; batch emission all-or-nothing per run directory.

## Configuration
DomainSpec: axes(), selectors(), seed_specs(), gold_case_ids(), recipe(). CorpusStore (busy_timeout=120000, transactions), QueryEncoder, SeedResolver.

## Performance
plan() milliseconds. run() retriever-bound; embedding matrix built once per run via ctx.resources.get(key, factory), released on return. batches() holds all signals in memory; select scope lets a 10M-chunk corpus emit per era.

## Dependencies
- CorpusStore/SignalStore (SQLite): local-substitutable; no port (fixture db is the same adapter).
- QueryEncoder: true external; LocalQueryEncoder / RecordedEncoder; third adapter = hosted endpoint.
- SeedResolver: remote-but-owned seam keeping the engine from importing the ledger module; LedgerSeedResolver / FrozenSeedResolver.
- ScorerSource: true external; PinnedFileScorers (artifact hash in ShardResult) / ConstantScorer.
- BatchSink: DirectorySink / MemorySink (MemorySink is the characterization harness).

## Trade-offs
High leverage: new selector kind = retriever class + YAML block; new ranking stage = one function + recipe entry; second domain = a directory; Partition axes make new corpora partition values. Thin: with two axes Partition is over-general today; params/evidence are Mapping[str, Any] (mitigated by per-retriever params schema validated in plan()); ctx.resources is a shared-mutable escape hatch. Adding a partition axis costs a coverage migration (composite PK -> partition_key TEXT) plus a batch-v2 emitter. Cross-batch global ranking state would break the per-group stage contract.

## Characterization plan
1. Batch replay: dump cycle-003 signals + gold to a fixture; engine.batches(RECIPE_V1, MemorySink(), run_id="cycle-003-shard-01"); byte-compare 632 files.
2. Signal replay on fixture db with RecordedEncoder for FTS/NEAR/regex selectors: matched_text (±200-char window, first-literal-phrase rule) and spans exact.
3. Plan replay: plan() against coverage restored to pre-cycle-003 state yields exactly the units whose coverage rows carry run_id='cycle-003-shard-01'.
4. Attribution parity with eval_recall.py output for the frozen gold set.
5. Downstream edge: case-id set across emitted batches equals case-id set in runs/cycle-003-shard-01/extractions*/.
