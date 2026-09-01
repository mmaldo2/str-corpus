# Selector engine — minimal interface (two verbs, one plan)

Summary:
1. One config type, ShardPlan (required: store, domain, run_id; everything else defaulted), plus two verbs: shard(plan) -> ShardResult and attribution(plan, case_ids) -> Mapping[int, tuple[SignalRef, ...]].
2. A selector is frozen data; each selector type has a runner behind an internal seam, so citation_graph, relevance_feedback, and trigram add zero interface.
3. Ranking/fusion lives inside shard() as a declarative RankingPolicy on the plan; signals are persisted before ranking, which only orders and truncates batch emission.
4. Seed sets ride in as plan.seeds; the engine canonicalizes and SHA-256s them into the coverage key, so changed seeds are automatically uncovered.
5. commit=False writes nothing and still returns batches as data, which makes the 632 cycle-003 batch files reproducible byte-for-byte.

## Types

```python
@dataclass(frozen=True, slots=True)
class Selector:
    id: str; version: int; concept: str; type: str; polarity: str
    status: str; author: str; rationale: str
    pattern: str | None = None            # fts_phrase | fts_near | regex | trigram
    index: str = "raw"                    # raw | porter | trigram
    query_text: str | None = None         # embedding
    top_k: int = 50; min_cosine: float = 0.5
    model_rev: str | None = None
    seed_set: str | None = None           # citation_graph | relevance_feedback
    direction: str = "both"               # citation_graph: cited | citing | both
    era_scope: tuple[str, ...] | str = "all"
    jurisdiction_scope: tuple[str, ...] | str = "all"

@dataclass(frozen=True, slots=True)
class DomainView:
    name: str; version: str
    selectors: tuple[Selector, ...]
    eras: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    gold_case_ids: frozenset[int]

@dataclass(frozen=True, slots=True)
class SeedSet:
    name: str
    case_ids: tuple[int, ...]
    provenance: str

@dataclass(frozen=True, slots=True)
class RankingPolicy:
    mode: str = "none"                     # none | fusion | classifier | rerank
    lexical_weight: float = 0.5
    classifier_path: str | None = None
    reranker: str | None = None
    max_cases: int | None = None

@dataclass(frozen=True, slots=True)
class ShardPlan:
    store: CorpusStore
    domain: DomainView
    run_id: str
    seeds: Mapping[str, SeedSet] = field(default_factory=dict)
    ranking: RankingPolicy = RankingPolicy()
    exclude_case_ids: frozenset[int] = frozenset()
    batch_size: int = 18
    commit: bool = True
    only: tuple[tuple[str, int], ...] = ()
    batches_only: bool = False
    embedder: QueryEmbedder | None = None

def shard(plan: ShardPlan) -> ShardResult: ...
def attribution(plan: ShardPlan, case_ids: Iterable[int]) -> Mapping[int, tuple[SignalRef, ...]]: ...

@dataclass(frozen=True, slots=True)
class ShardResult:
    batches: tuple[Batch, ...]
    new_signals: int
    covered: tuple[CoverageRow, ...]       # incl. seed_hash
    skipped: tuple[Skip, ...]
    manifest: Mapping[str, Any]            # selectors+versions+hashes, embed model/rev/dim/quant, seed hashes, ranking policy, batch_size, corpus counts
    def write_batches(self, out_dir: Path) -> int: ...
```

## Invariants
1. Signals persisted before ranking; ranking orders/truncates batch emission only.
2. Coverage key = (selector_id, selector_version, era, jurisdiction, seed_hash); changed seeds re-run automatically.
3. Determinism: identical plan + index => byte-identical batches. Iteration: domain.selectors x domain.eras x domain.jurisdictions order; batch order (-gold_count, -density, era, jurisdiction, first case_id).
4. commit=False writes nothing.
5. Validation precedes work: every fatal error raises before the first write.

## Error modes
SelectorError (validation); MixedIndexError (embedding scope spans partitions embedded by different models; fatal at validation); SeedSetMissingError; IndexIncompleteError (non-fatal: pair left uncovered, in ShardResult.skipped); StoreBusyError.

## Performance
Embedding matrix built once per shard() call and released on return (replaces module-global _EMBED_CACHE at shard.py:132). One similarity pass per selector version reused across partitions. Write lock per (selector, partition) commit.

## Dependencies
| Dependency | Category | Production | Test |
|---|---|---|---|
| SQLite corpus | local-substitutable | CorpusStore on corpus.db | CorpusStore on fixture db |
| Query embedder | true-external | SentenceTransformerEmbedder (rev from embed_meta) | RecordedEmbedder (npz query_text -> vector) |
| Ranking classifier/reranker | local-substitutable | file path in RankingPolicy | mode="none" or toy model |
| Batch files | local-substitutable | write_batches | compare result.batches as data |
| Domain artifacts | in-process | DomainView from domain loader | literal DomainView |

Only one port at the external interface: QueryEmbedder.

## Characterization plan
A. Batch replay: shard(ShardPlan(run_id="cycle-003-shard-01", batches_only=True, commit=False, exclude_case_ids=<recorded>)) re-emits from persisted signals; assert json.dumps(batch, indent=1) equals each of the 632 files byte-for-byte; golden sha256 per file in tests/golden. Forces a design fix: already_mapped_ids() (shard.py:256-267) globs runs/*/extractions*/ at call time, so exclusion must become an explicit recorded plan input.
B. Signal replay on fixture db with RecordedEmbedder: case_id set, char_span, matched_text, cosine to float32 identity.
C. Attribution replay: reproduce eval_recall's per-case selector lists and cycle-003 gate numbers (6/9, 22/29, 17/63).
