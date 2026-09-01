# Ledger — common-caller design

Summary:
1. One logical record set with `cycle` as a field; per-cycle JSONL files are the store's sharding; no caller names a file.
2. Canonical state = snapshot + append-only patch log (`data/ledger/patches.jsonl`, who/when/why/field/old/new); `verify()` proves snapshot == replay.
3. One write seam: `with ledger.session(who, why, cycle) as s:` with four verbs (admit, adjudicate, remap, annotate); adjudications, remaps, hygiene passes, hard-coded corrections, citator results are all the same kind of patch.
4. One read seam for numbers: `counts(by=..., **filters)` -> TwoTierCount with no .total/.__int__/.__add__; `matrix()` -> TraditionMatrix with empty_cells().
5. Review tier derived from the patch log (human-reviewed iff any Human patch touched a judged field), never stored as truth.

## Types
```python
CaseId = int; Cycle = str
JudgedField = Literal["relevant","polarity","who_was_letting","duration_of_occupancy","characterization","under_30_days","restriction_nature","right_characterization"]
Annotation = Literal["flag","note","citator_status"]
@dataclass(frozen=True) class Human: reviewer_id: str
@dataclass(frozen=True) class Reader: model: str; prompt_version: str
@dataclass(frozen=True) class Mechanical: script: str; version: str
Authority = Human | Reader | Mechanical

@dataclass(frozen=True)
class Patch:
    case_id: CaseId; field: JudgedField | Annotation; old: object; new: object
    authority: Authority; why: str; at: str; note: str | None = None; supporting_quote: str | None = None

@dataclass(frozen=True)
class Adjudication:
    case_id: CaseId; field: JudgedField | None; value: object
    note: str | None = None; flags: tuple[str, ...] = (); accepted_recommendation: str | None = None

def open_tradition(*, domain, store=None) -> Ledger
def open_argument_side(*, domain, store=None) -> Ledger

class Ledger:
    def session(self, *, who: Authority, why: str, cycle: Cycle, now=utcnow) -> ContextManager[Session]
    def records(self, **filters) -> Sequence[Record]
    def record(self, case_id) -> Record
    def counts(self, *, by=(), **filters) -> CountTable
    def matrix(self, *, min_count=1) -> TraditionMatrix
    def seed_set(self) -> SeedSet            # human-reviewed favorable + stable hash
    def history(self, case_id) -> Sequence[Patch]
    def manifest(self, cycle) -> Sequence[ManifestEntry]
    def verify(self) -> VerifyReport

class Session:
    def admit(self, verified: Iterable[dict], *, stratum=None) -> None
    def adjudicate(self, decisions: Iterable[Adjudication]) -> None
    def remap(self, verified: Iterable[dict], *, reader: Reader) -> None
    def annotate(self, case_ids, *, flag=None, note=None, citator_status=None) -> None
    report: ApplyReport

@dataclass(frozen=True)
class TwoTierCount:
    human_reviewed: int; machine_only: int
    def as_claim(self, noun) -> str   # "710 relevant cases (138 human-reviewed, 572 machine-only; lower bound)"
class CountTable(Mapping[tuple, TwoTierCount]): total: TwoTierCount; render_markdown()
class TraditionMatrix: cell(era, region, letting_tier, duration); empty_cells(); render_markdown(collapse=())
```

## Invariants
(i) home cycle fixed at admission; (ii) judged field changes only via Human or Reader authority — Mechanical may touch annotations only (UnauthorizedPatch); (iii) Reader patch on a judged field must carry supporting_quote; (iv) patches appended never edited; (v) tier derived; (vi) relevant:false records stay in the file, excluded from counts by default; (vii) v1 records keep null v2 fields; remap merges field-wise, never replaces wholesale (apply_adjudications.py:69-71 discarded review history); (viii) argument-side records never reach counts/matrix/seed_set (NotTraditionEvidence).
Ordering: admit precedes adjudicate/remap in a session; patches apply in log order; session writes all-or-nothing (temp + rename).
Errors: UnknownCase (today apply_adjudications.py:79-80, :98-99 silently continue), UnknownField/UnknownValue (validated against codebook — the build_review_queue.py:68 key mismatch fails loudly), UnauthorizedPatch, StaleSnapshot, SchemaVersionMismatch, MissingSupportingQuote.
Config: Domain value (era bounds, jurisdiction->region, letting-tier map, codebook values). Performance: eager load, ~50 ms, O(n) counts.

## Usage
```python
led = ledger.open_tradition(domain=domain)
with led.session(who=Human("marcus"), why="cycle-004 adjudication", cycle="cycle-004") as s:
    s.admit(verified_records, stratum=strata)
    s.remap(remap_records, reader=Reader("claude-opus", "mapper-v2"))
    s.adjudicate(review.decisions_for("cycle-004"))
led.counts().total.as_claim("relevant cases"); led.matrix().empty_cells()
```
Hygiene passes (polarity_review.py:130-165, relevance_recheck.py:49-66) become s.adjudicate([...]) under a why.

## Hides
File layout/globbing (citator_prescreen.py:30 reads only cycle-001); JSONL byte reproduction (ensure_ascii=True, default separators, key order, sort by year, trailing newline); patch append/replay; tier derivation; review.status/flags/notes rendering; the two hard-coded corrections migrated to seed patches; field-wise remap merge; manifest assembly incl. relevant:false reads from runs/; codebook validation; bucketing; seed hashing; atomic write + staleness check.

## Dependencies
LedgerStore internal seam: JsonlLedgerStore / InMemoryLedgerStore. Corpus store: local-substitutable, manifest metadata only. Domain: in-process value. Clock/identity injected at session(). LLM: NOT a dependency (staging moves to reader driver). Git: not wired (git show is the recipe).

## Trade-offs
annotate() near pass-through, kept to keep citator results in the same log. verify() full replay, rare. Schema v3 field = codebook entry + remap. SQLite = new store adapter. Mutable cycle is the expensive change; answer is a superseded_by patch.

## Characterization plan
1. Backfill the two hard-coded corrections as Human patches with the exact note strings (apply_adjudications.py:145-147, :153-155) plus one admission event per record.
2. Byte-for-byte rebuild of cycle-001/002/003 from verified/ + remap verified/ + adjudications json; sha256 equals git HEAD. Writer must reproduce json.dumps defaults, no indent, "\n".join + "\n", sort by year or 0 with admission order tiebreak, review as last key.
3. Hygiene replay: polarity re-review decisions then relevance re-check verdicts; ledgers match HEAD; history shows 31 + 5 patches.
4. Count regression pinned: 710 relevant, 368/196/128, 138 human-adjudicated, 138 favorable householder.
5. Behaviour tests on a 12-record in-memory fixture.
