"""The pure state transition: one patch in, one record changed."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any
from corpus_engine.ledger.types import Patch, UNSET, UnknownCase, DuplicateRecord, MissingBasis, UnknownField
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


def _record_admitting_prompt(state: "State", case_id: int, basis, *,
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
            state.records[p.case_id] = rec          # same position in state.order
            state.in_file[p.case_id] = bool(rec.get("relevant"))
            _record_admitting_prompt(state, p.case_id, p.basis, admit=True)
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
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
            _record_admitting_prompt(state, p.case_id, p.basis)
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
        rec["schema_version"] = p.new["schema_version"]
        for k, v in p.new.items():
            if k != "schema_version" and k not in rec:
                rec[k] = v
        return UNSET
    raise UnknownField(f"unknown op {p.op}")
