"""The pure state transition: one patch in, one record changed."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any
from corpus_engine.ledger.types import Patch, UNSET, UnknownCase, DuplicateRecord, MissingBasis, UnknownField

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
SUPPORTED_BY_PROMPT = {
    "mapper-v1": SUPPORTED,
    "mapper-v3": ("characterization", "polarity", "holding_summary",
                  "owner_freedom_characterization", "restriction_nature", "under_thirty_days"),
}
REVIEW_DEFAULT = {"status": "machine", "flags": [], "notes": []}


def supported_fields(prompt_version: str | None) -> tuple[str, ...]:
    """The support rule for a record admitted under `prompt_version`.

    D8 spells the basis as `mapper-v3:<first 12 of the codebook sha>`, so the lookup is on
    the part before the colon: the rule follows the codebook version, not the particular
    file hash, and a codebook edit that keeps the version keeps the rule."""
    if not prompt_version:
        return SUPPORTED
    return SUPPORTED_BY_PROMPT.get(str(prompt_version).split(":", 1)[0], SUPPORTED)


def quote_supports(quote: dict) -> tuple[str, ...]:
    """Which judged fields a quote is offered in support of, whichever shape it arrived in.

    mapper-v1 wrote a bare string; mapper-v3's schema makes `supports` an array, and a set
    literal over the raw value (`{q.get("supports") for q in quotes}`, which is what this
    module did) raises `unhashable type: 'list'` on the first drop_quote against an admitted
    cycle-004 record - taking the whole `Ledger.apply` with it. Same normalisation as
    `corpus_engine.reader.gate._supports`, so the gate and the fold can never disagree about
    what a quote supports."""
    s = quote.get("supports")
    if isinstance(s, str):
        return (s,) if s else ()
    if isinstance(s, (list, tuple, set)):
        return tuple(x for x in s if isinstance(x, str) and x)
    return ()


@dataclass
class State:
    records: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    cycles: dict[int, str] = field(default_factory=dict)
    in_file: dict[int, bool] = field(default_factory=dict)
    # The prompt version each record was ADMITTED under, so `drop_quote` can pick the right
    # support rule. A side map, exactly like `cycles`: putting it on the record itself would
    # add a key to every rendered line and break the byte-identical snapshot replay.
    prompts: dict[int, str] = field(default_factory=dict)


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
            state.prompts[p.case_id] = p.basis.prompt_version or ""
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        state.prompts[p.case_id] = p.basis.prompt_version or ""
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
