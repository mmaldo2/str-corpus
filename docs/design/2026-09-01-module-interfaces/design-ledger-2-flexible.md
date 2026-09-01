# Ledger — flexibility-maximizing design

Summary:
1. One logical record set per ledger name (tradition, argument-side, future domains) keyed by case_id; cycle a field; per-cycle .jsonl files a projection the module owns.
2. Every mutation is a Patch — adjudication, remap, polarity re-review, relevance re-check, citator, hard-coded corrections, schema-v2 migration — six ops differing only in PatchSource.
3. Replay authoritative, snapshot committed: record = fold(apply_patch, base_from_verified_extraction, patches_in_seq_order); JSONL is a materialization checked against the fold.
4. Five doors: apply, read, tally, history, account.
5. review.status/review tier and nulled_fields are DERIVED, unpatchable values computed from patch provenance.

```python
@dataclass(frozen=True) class LedgerConfig: ledger_id; codebook: Codebook; facets: Facets; store: RecordStore; log: PatchLog; extractions: ExtractionSource; revisions: RevisionResolver = SeqResolver(); clock
class Governance(Enum): JUDGED; CURATORIAL (review.flags/notes, tags, citator_status); IDENTITY (patchable only by migrate); DERIVED (review.status, review_tier, nulled_fields, extraction_status)
class Op(Enum): ADMIT; SET; RETRACT (remove a quote/flag); ANNOTATE; LINK (external verdict: citator, pin-cite); MIGRATE
@dataclass(frozen=True) class PatchSource: kind: human|reader|rule|migration; reviewer; model; prompt_version; codebook_version; run_id; rule_id; fingerprint()
@dataclass(frozen=True) class Origin: run_id; batch_file; record_sha256
@dataclass(frozen=True) class Support: quote_sha256; supports; reporter_page
@dataclass(frozen=True) class PatchProposal: case_id; op; path; new; source; reason (required non-empty); support; origin (ADMIT); supersedes
@dataclass(frozen=True) class Patch(PatchProposal): patch_id (blake2b content); seq; group_id; at; old (captured by module)

class Ledger:
    def apply(self, proposals, *, note, dry_run=False) -> ApplyResult
    def read(self, q: Q = Q.all(), *, at: Revision = HEAD) -> RecordSet
    def tally(self, spec: TallySpec, *, at=HEAD) -> Tally
    def history(self, case_id, *, field=None) -> Sequence[Patch]
    def account(self, cycle, *, at=HEAD) -> Manifest
class Q: all(); eq(field, value); tier(t); facet(name, value); cycle(c); flagged(prefix); composes with & | ~   (cap at these seven)
@dataclass(frozen=True) class TallySpec: by: tuple[str, ...] = (); where: Q = Q.all(); label = ""
@dataclass(frozen=True) class TwoTier: human_reviewed; machine_only; __int__ raises TypeError
@dataclass(frozen=True) class Tally: spec; ledger_id; as_of; at; cells: Mapping[tuple, TwoTier]; total; empty_cells; digest; markdown()  # the only renderer reports may use
@dataclass(frozen=True) class RecordSet: records; as_of; case_ids(); digest() (seed-set hash)
@dataclass(frozen=True) class ApplyResult: group_id; admitted; rejected: (proposal, reason); no_op; head
class Revision: HEAD; at_seq(n); at_time(t); at_commit(sha)
```

## Invariants
1. One write door (test greps package for ledger path literals outside engine/ledger/).
2. Judged fields change only under authority (human+reviewer, or reader+model+prompt_version+codebook_version) — AuthorityError.
3. Support rule: non-null judged value requires support on the patch or an existing quote with supports == field (absorbs verify_quotes.py:123-127) — UnsupportedValueError.
4. Retraction cascades: RETRACT of a quote nulls every judged field left unsupported, recorded as DERIVED recomputation (absorbs apply_adjudications.py:130-140 where the Shvekh quote drop leaves polarity standing unsupported).
5. Derived fields unpatchable (DerivedFieldError); review_tier = human-reviewed iff some JUDGED patch has source.kind == human.
6. Ledger isolation: single-ledger by construction; no cross-ledger tally.
7. Manifest superset: read(Q.cycle(c)) ⊆ account(c) relevant entries and len(account(c)) == verified extraction records in that cycle's runs — AccountingError at apply (would have caught 715-vs-710).
8. Identity immutability.
9. Snapshot fidelity: store.materialize() bytes == serialization of fold(log.replay()) — MaterializationDrift; checked in strict mode and CI.
Ordering: seq assigned at apply, dense; patches in one call share group_id; apply atomic. Replay orders by seq never by at (browser timestamps untrustworthy). Field insertion order is part of the artifact: fold mutates in place; MIGRATE appends v2 fields at the end. ADMIT precedes any patch on the same case.
Non-errors: identical patch re-applied => no_op; SET to same value => no_op (+ANNOTATE if reason new).
Performance: full replay < 150 ms; HEAD read uses snapshot ~40 ms; past read forces replay; case_id -> seq[] index for history.

## Hides
The fold per op incl. retraction cascade, null-fill on MIGRATE, in-place key order. Admissibility checks. The five resolution blocks (A/B/C/D + corrections) become one table (section, decision) -> patch op owned by the review module; ledger validates. Two-tier derivation and legacy status vocabulary emitted for compatibility. Materialization/file layout/sort/separators/trailing newline; relevant:false records stay in file, out of counts. Facet derivation (era from year, region from jurisdiction — no region mapping exists anywhere today, invented in exactly one place; letting tier incl. owner_nonresident; duration bucketing). Idempotency/dedup via patch_id. Manifest projection + stratum from the same ADMIT event. v1/v2 coexistence.

## Dependencies
RecordStore local-substitutable: JsonlStore (legacy layout for tradition) / MemoryStore / SqliteStore (read cache past ~20k records). PatchLog: JsonlPatchLog (data/ledger/<ledger>/patches/<cycle>.jsonl) / MemoryLog. ExtractionSource: RunDirSource / MemorySource / FixtureDirSource. RevisionResolver: GitResolver / SeqResolver (weakest port; collapse into PatchLog if at_commit unused). Codebook+facets, clock, reviewer identity: in-process, not ports. LLM/CourtListener/SQLite corpus: not dependencies — hygiene passes, remap, citator, reader driver hand in proposals (polarity_review.py shrinks from LLM caller + file rewriter to LLM caller).

## Trade-offs
High leverage: new patch source = function returning proposals; second ledger = config; second domain = Codebook + Facets data. Thin: history() near pass-through (fold into read(with_history=True) if trivial); Revision.at_commit speculative; Q risks becoming a query language (cap at seven constructors); Op.LINK arguably SET on curatorial (kept because external verdicts are re-fetchable and superseded wholesale). Expensive by design: per-field provenance nested in the record (breaks byte fidelity); cross-ledger analysis (belongs in citation-graph module).

## Characterization
Step 1 bootstrap the log from committed artifacts: ADMIT from verified/ in sorted(glob) order (apply_adjudications.py:62-64), remap overrides (:65-70); section C, D, A, B patches in the source script's block order (:76, :94, :116, :130) — order matters since A can overwrite a status C set; Shvekh SET (human) and Slice-of-Life ANNOTATE (rule); polarity re-review; relevance re-check.
Step 2 golden bytes per cycle. Three hazards expected to fail first: (a) record order — hygiene passes preserve original order while apply_adjudications writes fresh dicts sorted by year, so hygiene-touched cycle files have a different record order than a fresh build; the store must persist record order in the log, not re-sort on replay; (b) json.dumps defaults, ensure_ascii; (c) note text byte-identical incl. embedded dates (polarity_review.py:153-154, relevance_recheck.py:59).
Step 3 adjudication round-trip via review module reproduces adjudications json (indent=1, savedAt).
Step 4 number regression: 710; 368/196/128/15/3; status 560/138/11/1; derived tier maps to legacy vocabulary exactly (150 human-reviewed); cycle-003.md cites two totals — both become assertions, stale one deleted.
Step 5 accounting invariant across cycles — expected to FAIL (715 read vs 710 relevant, relevant:false in runs/ only); written first and xfail with issue reference.
Step 6 replay determinism and time travel (pre-re-review favorable 400).
Step 7 isolation: argument ledger admit leaves tradition tally unchanged.
