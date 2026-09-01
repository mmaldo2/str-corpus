"""The pure state transition: one patch in, one record changed."""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any
from corpus_engine.ledger.types import Patch, UNSET, UnknownCase, DuplicateRecord, MissingBasis, UnknownField

JUDGED_DEFAULT = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                  "characterization", "holding_summary", "under_30_days",
                  "restriction_nature", "right_characterization")
SUPPORTED = ("characterization", "polarity", "holding_summary")
REVIEW_DEFAULT = {"status": "machine", "flags": [], "notes": []}


@dataclass
class State:
    records: dict[int, dict] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    cycles: dict[int, str] = field(default_factory=dict)
    in_file: dict[int, bool] = field(default_factory=dict)


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
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        return UNSET
    rec = state.records.get(p.case_id)
    if rec is None:
        raise UnknownCase(str(p.case_id))
    if p.op == "set":
        if p.field in judged and not p.basis.can_judge():
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
        to_drop = [q for q in before if q.get("text") == p.new]
        rec["quotes"] = [q for q in before if q.get("text") != p.new]
        if cascade:
            dropped_fields = {q.get("supports") for q in to_drop}
            supported = {q.get("supports") for q in rec["quotes"]}
            for f in dropped_fields:
                if f in SUPPORTED and rec.get(f) is not None and f not in supported:
                    rec[f] = None
                    rec.setdefault("nulled_fields", []).append(f)
        return to_drop
    if p.op == "migrate":
        rec["schema_version"] = p.new["schema_version"]
        for k, v in p.new.items():
            if k != "schema_version" and k not in rec:
                rec[k] = v
        return UNSET
    raise UnknownField(f"unknown op {p.op}")
