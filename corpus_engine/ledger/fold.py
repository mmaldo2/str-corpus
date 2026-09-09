"""The pure state transition: one patch in, one record changed."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any
from corpus_engine.ledger.types import (Patch, Basis, UNSET, UnknownCase, DuplicateRecord,
                                        MissingBasis, UnknownField)
# M4: the definition lives in corpus_engine.quotes, upstream of both the reader and the
# ledger; re-exported here because the gate, the fold and verification.py all learned it
# from this module and must go on sharing exactly one implementation.
from corpus_engine.quotes import quote_supports

JUDGED_DEFAULT = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                  "characterization", "holding_summary", "under_thirty_days",
                  "restriction_nature", "owner_freedom_characterization")
# The mapper-v1 quote-support rule, and the fallback for a record whose admitting patch
# recorded no prompt version.
SUPPORTED = ("characterization", "polarity", "holding_summary")
# D7: the rule is a property of the codebook that read the record, not of the ledger. A
# mapper-v3 record was asked to support all six judged fields with a quote, so dropping a
# quote must void all six; a mapper-v1 record was only ever asked for three, and widening
# the cascade for it would null fields on evidence that was never demanded.
SUPPORTED_SIX = ("characterization", "polarity", "holding_summary",
                 "owner_freedom_characterization", "restriction_nature", "under_thirty_days")
# mapper-v2 is here because it SHIPPED (domains/str-right-to-let/codebooks/mapper-v2.md) and
# its hard requirement 1 demands a supporting quote for the same six fields mapper-v3 does -
# it differs only in writing `supports` as a bare string. No record carries it today, but a
# legacy record that did would otherwise raise out of `supported_fields` and take the whole
# verification pipeline down (M5).
SUPPORTED_BY_PROMPT = {
    "mapper-v1": SUPPORTED,
    "mapper-v2": SUPPORTED_SIX,
    "mapper-v3": SUPPORTED_SIX,
}
REVIEW_DEFAULT = {"status": "machine", "flags": [], "notes": []}

# The flag a rejected write leaves on the record. It MUST equal
# `corpus_engine.reader.schema.FLAG_PREFIX`; the ledger is upstream of the reader and cannot
# import it, so the two are pinned equal by a test instead of by an import.
FLAG_PREFIX = "needs-review:"
PROVENANCE_KINDS = ("human", "reader", "rule")
# R2: a rejection is a rule speaking, and this is the rule's name. The fold flags the record
# in place while it folds, so it writes no patch of its own; a tool that later records the
# same rejection as a patch (the re-read in T6, the queue in T7) spells its basis
# `Basis(rule_id=PROTECTION_RULE_ID)`.
PROTECTION_RULE_ID = "reviewer-protection"
# D2 protects human decisions from THIS SEQ ON (controller ruling R1). The log head on
# 2026-09-08 was 42984, and six writes below it already changed a field a reviewer had
# decided: seq 7368 (4268287.polarity), 7372 (1932707.polarity), 7376
# (2186819.characterization) and 7378 (2186819.polarity), all `retraction-cascade-v1` nulls
# a reviewer's own `drop_quote` triggered and all restored by hand afterwards; and seq 7818
# (608729.polarity) and 7820 (10225079.polarity), the `vocab-v3-cleanup` nulls of the
# deleted value "irrelevant". Enforcing the rule over them would rewrite five committed
# records and flag them, so history is grandfathered: those six are recorded as conflicts
# with `historical: True`, apply exactly as they always have, and add no flag - which is why
# a fresh replay of the committed log still renders the cycle files byte for byte. Every
# patch after the baseline is judged by the rule.
#
# NEVER refresh this to a later head. Raising it re-grandfathers every disagreement recorded
# since, silently un-protecting decisions the rule has already defended; the number is a fact
# about 2026-09-08 and stays one. Two consequences worth knowing: a patch is judged by its
# seq, so a fold of patches that are NOT YET in the log must stamp the seqs the append will
# assign (`corpus_engine.ledger.log.provisional_seqs`, review finding 1) or the rule reads
# them as history; and a ledger built from scratch (a scratch dir in a test or a rehearsal)
# numbers its patches from 1, so the rule is inert there until it passes this seq - which is
# right for a throwaway ledger and irrelevant to a scratch COPY of the real one, which keeps
# the real seqs.
PROTECTION_FROM_SEQ = 42984


def provenance_kind(basis: Basis) -> str:
    """The provenance a patch writes: human | reader | rule.

    `Basis.kind()` has a fourth answer, "none", for a bare basis. A judged value can only
    reach the fold under a basis that can judge (`MissingBasis`), so a bare basis here is
    either an admit body or a retraction to None - both records of a read, and "reader" is
    the honest name for them."""
    kind = basis.kind()
    return kind if kind in PROVENANCE_KINDS else "reader"


def is_reader_write(basis: Basis) -> bool:
    """Whether this patch is a machine read speaking on its own authority.

    NOT the protection gate - see `is_protected_write`, which D2 widened to every
    non-reviewer basis. Kept because it is the honest name for "a reader wrote this" and the
    re-read tooling asks that question about its own patches."""
    return bool(basis.model) and not basis.reviewer


def is_protected_write(basis: Basis) -> bool:
    """Whether D2's protection applies to this patch: every basis that is not a reviewer.

    A reader re-read is the obvious case, but a rule is protected against too (controller
    ruling): `retraction-cascade-v1` once nulled a human's characterization, and a rule that
    can quietly undo a judgment is the same hole as a reader that can. A rule may still fix
    such a field - through a reviewer, or through a `migrate` op, which is exempt because a
    vocabulary migration renames a value rather than judging a case."""
    return not basis.reviewer


def supported_fields(prompt_version: str | None) -> tuple[str, ...]:
    """The support rule for a record admitted under `prompt_version`.

    D8 spells the basis as `mapper-v3:<first 12 of the codebook sha>`, so the lookup is on
    the part before the colon: the rule follows the codebook version, not the particular
    file hash, and a codebook edit that keeps the version keeps the rule. The lookup is
    exact - no case-folding, no stripping - so a typo (`MAPPER-V3`, `mapper-v3 `) is a bug
    to surface, not a version to guess at.

    `None`/missing/`""` is a legitimate historical state (every mapper-v1 admit patch predates
    this field) and resolves to the mapper-v1 rule. Anything non-empty that doesn't name a
    known codebook version raises: silently narrowing to three fields would leave a
    mapper-v3 record's other judged fields standing on no surviving quote - the exact
    evidence-discipline gap the cascade exists to close - with nothing downstream able to
    tell the difference from a real mapper-v1 record (controller ruling, review finding 1)."""
    if not prompt_version:
        return SUPPORTED
    key = str(prompt_version).split(":", 1)[0]
    if key not in SUPPORTED_BY_PROMPT:
        raise ValueError(f"unknown prompt_version for supported_fields: {prompt_version!r}")
    return SUPPORTED_BY_PROMPT[key]


@dataclass
class State:
    records: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    cycles: dict[int, str] = field(default_factory=dict)
    in_file: dict[int, bool] = field(default_factory=dict)
    # The prompt version each record was ADMITTED under, so `drop_quote` can pick the right
    # support rule. A side map, exactly like `cycles`: putting it on the record itself would
    # add a key to every rendered line and break the byte-identical snapshot replay.
    #
    # The value is the LATEST admit patch that names a `prompt_version` (final-review I2,
    # which reverses the Task-2 fix-round rule that pinned it at first sight): re-reading a
    # record under a new codebook RE-ADMITS it, and the record then stands on the new read's
    # quotes under the new codebook's support rule. Slice 3's first item is exactly that - a
    # re-read of cycles 1-3 under mapper-v3 - and a value pinned at first sight would leave
    # those records folding under the mapper-v1 three-field cascade with their mapper-v3
    # values standing on quotes nothing demanded, which is the gap D7 exists to close.
    #
    # An admit whose basis carries NO `prompt_version` (a reviewer re-admit, a rule-only
    # admit) never changes what is recorded: a re-admit by a human is provenance for the
    # record, not for the read that produced it, and narrowing an already-known mapper-v3
    # rule to mapper-v1 the moment a human re-admits would be the same silent gap from the
    # other side (Task-2 review finding 3, still in force).
    #
    # If no admit patch ever carries one, the fallback is the EARLIEST `set` on a judged
    # field whose own basis does (spec section 8 does not require the D8 basis to live on
    # the admit patch itself - Task 7 puts it there; see the `set` branch below). A `set`
    # never moves a version that is already recorded.
    #
    # Review finding 6: a caller that hand-builds a `State(...)` from a snapshot without
    # passing `prompts` (e.g. to replay a subset of patches against a trial copy) gets an
    # empty map, not an error - every case in it silently reads as the three-field
    # mapper-v1 rule on its next `drop_quote`, even if the real record is mapper-v3. This
    # is legal (missing must stay legal, per finding 1) but easy to trip over; a caller
    # that wants the real rule preserved must copy `prompts` too, the same as it must copy
    # `cycles` and `in_file`.
    prompts: dict[int, str] = field(default_factory=dict)
    # Per-field provenance, `{case_id: {field: kind}}` (D2). Written by every applied `set` on
    # a judged field and by every judged field an `admit` body carries. STICKY AT "human": once
    # a human has decided a field, a rule that later withdraws the value has not un-made the
    # judgment, and a field that quietly reverted to rule provenance would be silently
    # re-fillable by the next machine read. A side map for the same reason as `cycles`.
    provenance: dict[int, dict[str, str]] = field(default_factory=dict)
    # Writes over a human decision, `{case_id: [entry, ...]}`. An entry is
    # {"field", "attempted", "standing", "by", "at", "op", "historical", "by_rule"}, where
    # `by` is the attempting basis and `by_rule` the rule that refused it. `historical` is True
    # for the six writes below `PROTECTION_FROM_SEQ`, which are recorded but still applied;
    # every other entry is a write the fold REFUSED. A rejection never raises: `view()`
    # replays the whole log on every call and a raise would take the corpus down (spec §9).
    conflicts: dict[int, list[dict]] = field(default_factory=dict)


def _record_provenance(state: "State", case_id: int, field_name: str, basis: Basis) -> None:
    """See `State.provenance` for the stickiness rule."""
    fields = state.provenance.setdefault(case_id, {})
    if fields.get(field_name) == "human":
        return
    fields[field_name] = provenance_kind(basis)


def _may_write(state: "State", case_id: int, field_name: str, value, basis: Basis, *,
               seq: int, op: str, standing, target: dict) -> bool:
    """Whether `field_name` may take `value` (D2), recording the attempt when it may not.

    A write of the SAME value is not an overwrite: it changes nothing, so it is neither
    applied nor reported. That is what keeps the 161 value-identical re-admit writes in the
    committed log silent, and it is half of what makes a fresh replay reproduce the four
    cycle files byte for byte; the `PROTECTION_FROM_SEQ` baseline is the other half.
    `target` is the record the flag goes on - on a re-admit that is the NEW record, not the
    one being replaced.

    `seq` decides history from future, so it must be the seq the patch HAS IN THE LOG. A
    `Patch` carries 0 until `PatchLog.append` numbers it, and 0 reads as pre-baseline: every
    fold of not-yet-appended patches stamps them first with
    `corpus_engine.ledger.log.provisional_seqs` (review finding 1)."""
    if state.provenance.get(case_id, {}).get(field_name) != "human":
        return True
    if not is_protected_write(basis):
        return True
    if standing == value:
        return False
    historical = int(seq) <= PROTECTION_FROM_SEQ
    state.conflicts.setdefault(case_id, []).append(
        {"field": field_name, "attempted": value, "standing": standing,
         "by": basis.to_json(), "at": int(seq), "op": op, "historical": historical,
         "by_rule": PROTECTION_RULE_ID})      # R2: the rule that recorded, and refused, this
    if historical:
        return True                        # grandfathered: recorded, but it still applies
    review = target.setdefault("review", copy.deepcopy(REVIEW_DEFAULT))
    flag = f"{FLAG_PREFIX}{field_name}"
    if flag not in review.setdefault("flags", []):
        review["flags"].append(flag)
    return False


def _record_admitting_prompt(state: "State", case_id: int, basis: Basis, *,
                             admit: bool = False) -> None:
    """Record which prompt the record now stands on - see `State.prompts` for the rule.

    `admit=True` and a basis that names a prompt: that read is the record's read now, even
    if an earlier one already recorded a different version (I2). Anything else only fills a
    value that is not there yet, so neither a reviewer's re-admit nor a later `set` can move
    a version a read has already established."""
    version = basis.prompt_version or ""
    if admit and version:
        state.prompts[case_id] = version
    elif not state.prompts.get(case_id):
        state.prompts[case_id] = version


def _resolve(rec: dict, path: str, create: bool = False):
    if "." not in path:
        return rec, path
    head, tail = path.split(".", 1)
    if head != "review":
        raise UnknownField(path)
    if "review" not in rec:
        if not create:
            raise UnknownField(path)
        rec["review"] = copy.deepcopy(REVIEW_DEFAULT)
    return rec["review"], tail


def apply_patch(state: State, p: Patch, *, judged: tuple[str, ...] = JUDGED_DEFAULT,
                cascade: bool = True) -> Any:
    if p.op == "admit":
        rec = copy.deepcopy(p.new)
        if "review" not in rec:
            rec["review"] = copy.deepcopy(REVIEW_DEFAULT)
        if p.case_id in state.records:
            if state.cycles[p.case_id] != p.cycle:
                raise DuplicateRecord(f"{p.case_id} already admitted in {state.cycles[p.case_id]}")
            old = state.records[p.case_id]
            # A re-admit REPLACES the record, so its body is a write of every judged field it
            # names - and a SILENCE about a field a human decided is a write too: the
            # replacement would drop the value. D2 applies to both (controller ruling, fix
            # round 2): a body that carries a different value is refused, and a body that
            # carries no value at all leaves the standing one alone. Nothing was attempted
            # against an omitted field, so it is no conflict and no flag - it is the human's
            # value simply staying where it was.
            protects = is_protected_write(p.basis) and int(p.seq) > PROTECTION_FROM_SEQ
            for f in judged:
                if f in rec:
                    if not _may_write(state, p.case_id, f, rec[f], p.basis, seq=p.seq,
                                      op="admit", standing=old.get(f), target=rec):
                        rec[f] = old.get(f)  # the standing value keeps its place in the record
                elif (protects and f in old
                      and state.provenance.get(p.case_id, {}).get(f) == "human"):
                    # Carried forward at the END of the record: the body chose the key order
                    # and this key was not in it. A re-read must carry every current key
                    # forward itself (ruling R6) if it wants the order preserved.
                    rec[f] = old[f]
            state.records[p.case_id] = rec          # same position in state.order
            state.in_file[p.case_id] = bool(rec.get("relevant"))
            for f in judged:
                if f in rec:
                    _record_provenance(state, p.case_id, f, p.basis)
            _record_admitting_prompt(state, p.case_id, p.basis, admit=True)
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        for f in judged:
            if f in rec:
                _record_provenance(state, p.case_id, f, p.basis)
        _record_admitting_prompt(state, p.case_id, p.basis, admit=True)
        return UNSET
    rec = state.records.get(p.case_id)
    if rec is None:
        raise UnknownCase(str(p.case_id))
    if p.op == "set":
        # A retraction to None removes a claim; it isn't a judgment about the
        # case, so it needs no judging authority. Any non-None value on a
        # judged field is a judgment and still needs one.
        if p.field in judged and p.new is not None and not p.basis.can_judge():
            raise MissingBasis(f"{p.field} on {p.case_id} needs a reviewer or model+prompt_version+run_id")
        # Review finding 2: if no admit patch for this record ever carried a prompt_version
        # (spec section 8 does not require the D8 basis to live on the admit patch itself),
        # the earliest `set` on a judged field whose OWN basis carries one is the fallback
        # source of the admitting prompt. `_record_admitting_prompt` is idempotent past the
        # first non-empty value, so this only ever fires once per record.
        if p.field in judged:
            # Before the gate (review finding 7): recording WHICH READ SPOKE is not a
            # judgment about the case, and D2 must change nothing but the judged value. A
            # value-identical write is a silent no-op, and a record whose only prompt source
            # was one of the 161 of those would otherwise fall back to the mapper-v1 support
            # rule and cascade differently on a later `drop_quote`.
            _record_admitting_prompt(state, p.case_id, p.basis)
            if not _may_write(state, p.case_id, p.field, p.new, p.basis, seq=p.seq, op="set",
                              standing=rec.get(p.field), target=rec):
                return UNSET               # the value stands; the attempt is on the record
            _record_provenance(state, p.case_id, p.field, p.basis)
        target, key = _resolve(rec, p.field, create=True)
        old = target.get(key, UNSET)
        target[key] = p.new
        return old
    if p.op == "append":
        target, key = _resolve(rec, p.field, create=True)
        lst = target.setdefault(key, [])
        if not isinstance(lst, list):
            raise UnknownField(f"{p.field} is not a list")
        lst.append(p.new)
        return UNSET
    if p.op == "drop_quote":
        # The cascade nulls a supported field directly and is deliberately outside D2: the
        # patch that triggers it carries a reviewer basis in all 14 cases in the log, and
        # provenance is sticky, so a cascaded null over a human field keeps `human`
        # provenance and a later machine read still cannot re-fill it.
        before = rec.get("quotes", [])
        rec["quotes"] = [q for q in before if q.get("text") != p.new]
        if cascade:
            supported = {f for q in rec["quotes"] for f in quote_supports(q)}
            for f in supported_fields(state.prompts.get(p.case_id)):
                if rec.get(f) is not None and f not in supported:
                    rec[f] = None
                    rec.setdefault("nulled_fields", []).append(f)
        return [q for q in before if q.get("text") == p.new]
    if p.op == "migrate":
        # Exempt from D2 (controller ruling R1): a vocabulary migration renames a value, it
        # does not judge a case, and it only ever fills a key the record does not have.
        rec["schema_version"] = p.new["schema_version"]
        for k, v in p.new.items():
            if k != "schema_version" and k not in rec:
                rec[k] = v
        return UNSET
    raise UnknownField(f"unknown op {p.op}")
