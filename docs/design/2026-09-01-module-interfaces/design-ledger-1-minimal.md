# Ledger — minimal-interface design

Summary:
1. Three entry points: open_ledger() -> Ledger.view() (every read) and Ledger.apply() (every write); all else frozen value types.
2. One logical record set keyed by case_id; cycle is a field; the three JSONL files are a rendering detail.
3. Every mutation is one Patch with one closed Basis (reviewer OR model+prompt_version+run_id); deterministic basis alone cannot change a judged field.
4. Snapshot canonical, append-only log is the audit trail, apply() asserts replay == snapshot; view(as_of=...) reproduces the record at any past point (patch id, seq, timestamp, or git rev).
5. Counts and matrix exist only as view.counts / view.matrix built from TierCount with no .total.

```python
def open_ledger(*, root=None, name: "tradition"|"argument" = "tradition", domain=None) -> Ledger
class Ledger:
    def view(self, *, as_of=None) -> LedgerView
    def apply(self, patches: Iterable[Patch], *, at=None, dry_run=False) -> PatchResult

Op = Literal["admit", "set", "append", "drop_quote"]
@dataclass(frozen=True, slots=True) class Basis: reviewer=None; model=None; prompt_version=None; run_id=None; deterministic=None  # "quote-gate"|"remap-merge"|"migration"
@dataclass(frozen=True, slots=True)
class Patch:
    case_id: int; op: Op; field: str; new: Any; why: str; basis: Basis
    cycle: str | None = None  # admit only
    at=None; old=_UNSET; patch_id=""; seq=0   # filled by apply()
@dataclass(frozen=True) class PatchResult: applied; skipped (duplicate patch_id); rejected (dry_run); files_written; snapshot_digest; replay_ok
@dataclass(frozen=True) class TierCount: human_reviewed: int; machine_only: int   # no .total, no __int__, no __add__
@dataclass(frozen=True) class Counts: admitted; relevant; polarity: Mapping[str|None, TierCount]; who_was_letting; by_jurisdiction; by_era; quotes_verified; quotes_fuzzy
Cell = tuple[era, region, letting_tier, duration]
@dataclass(frozen=True) class TraditionMatrix: cells: Mapping[Cell, TierCount]; empty_cells(minimum=1, tier="human_reviewed"|"either"); is_done(minimum)
@dataclass(frozen=True) class SeedSet: case_ids (sorted; human-reviewed favorable only); hash (sha256 over ids + as_of)
@dataclass(frozen=True) class LedgerView: name; as_of; seq; records: Mapping[int, Record]; manifest: Manifest; counts; matrix (NotTraditionEvidence when name != tradition); seed_set; history(case_id); render() -> Mapping[filename, bytes]
```
An admit patch carries a verified extraction record (incl. relevant:false ones). A remap merge is a group of set patches sharing basis.run_id; may not target review.*. Citator result = set on citator.status. The two hard-coded corrections become seeded patches with basis.reviewer.

## Invariants
Admit only with a gated record (QuoteGateNotPassed). Judged field changes only with reviewer or (model, prompt_version, run_id) (MissingBasis). Review tier derived (human_reviewed iff a reviewer patch touched a judged field); rendered review.status is a decision kind kept for byte fidelity, not what counts use. One case_id, one home cycle file (DuplicateRecord). relevant:false stays in its file, leaves counts.relevant. Argument ledger has no matrix; no code path unions two views. Log append-only; patch_id content-addressed => re-applying a hygiene pass is a no-op (unlike polarity_review.cmd_apply which appends duplicate notes today).
Ordering: admit precedes set in a batch; set on unknown case => UnknownCase; apply atomic (temp + rename) with exclusive data/ledger/.lock.
Config: repo root + domains/<domain>/ (era bounds, jurisdiction->region, judged-field table, letting-tier map, codebook version). No DB, no API, no network.
Performance: open no I/O; first view ~120 ms memoized per as_of; past view replays O(patches); apply rewrites only touched cycle files.

## Hides
Cycle->file routing and year sort; canonical key-order table + JSON flags for byte-identical renders; replay, content addressing, idempotence, locking, atomic write; tier derivation and tier/decision-kind split; era/region/letting-tier/duration binning incl. owner_nonresident -> tier 2 and null-polarity bucketing (so the 15 nulls stop vanishing); v1/v2 coexistence (view exposes v2 keys as None on v1 records; renderer omits them from v1 lines until a v2 patch lands, so cycle-001.jsonl stays byte-identical); manifest projection (in this module, a second projection of the same log — two owners of "what happened to this case" is the failure ADR-0002 forbids); seed-set hash; migration of hard-coded corrections into log rows.

## Dependencies
Domain spec in-process value. Filesystem local-substitutable — NO port and no store= parameter (a MemoryStore would exist solely to be injected). Git for as_of=<rev> via subprocess. corpus.db, LLM, CourtListener NOT dependencies. Module takes no injected adapter at its interface.

## Trade-offs
apply() gives validation and logging only (that is the value). as_of git resolution has one consumer (methods appendix) — delete if unused after cycle 004. view.manifest empty for cycles 1-3 until a one-time harvest of admit-patches from runs/*/verified/ backfills relevant:false reads (~a day; only way ADR-0002's manifest is satisfied retroactively). New judged field = one row in field table + key-order table. SQLite = private store rewrite. New ledger = name=. New matrix axis = one line + renderer.

## Characterization
1. Freeze digests of the three ledgers, three adjudication files, verified/ listings.
2. Round-trip identity: render() of a view loaded from current files == current bytes (proves key-order table + JSON flags first).
3. Migration replay: migrate.patches_from_artifacts derives the log (admits from verified/ + remap; decisions from adjudications A/B/C/D mirroring apply_adjudications.main(); hygiene from polarity-review + relevance-recheck; corrections); apply into tmp_path; render == repo bytes for all three files.
4. replay_ok True after each migration stage.
5. Counts reproduce handoff figures: 715/710; 368/196/128/15/3; 560 machine-only vs 150 human-touched (138/11/1).
6. Time travel: view(as_of=<seq before polarity re-review>) reproduces cycle-003.md pre-review 400/173/124 and 148 fav householder; after => 369/200/128.
7. Matrix reproduces the handoff grids; empty_cells(minimum=3) names pre-1860 cells.
8. Idempotence and rejection tests.
