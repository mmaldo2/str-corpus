from __future__ import annotations
import json
from typing import Sequence
from corpus_engine.reader.model import Unit

REQUIRED = ("case_id", "relevant", "polarity", "quotes")


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        starts = [i for i in (t.find("["), t.find("{")) if i >= 0]
        t = t[min(starts):] if starts else t
    return t.strip()


def _as_case_id(v) -> int | None:
    """A model that writes `"case_id": "948154"` has answered for the case. Comparing the
    raw values made that a coverage miss, which cost a split retry before the unit was
    written off (m3). Anything that is not an integer spelling is still not a case id."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _wrapped(t: str, start: int) -> list | None:
    """`{"records": [...]}` decoded from `start` - the shape the v3 schema asks for.
    Not a `records`-shaped object at all is a miss, not a fallback: R1 - a top-level
    object is accepted only under the `records` key, never scanned for a bare array
    nested in some other key."""
    dec = json.JSONDecoder()
    try:
        obj, _end = dec.raw_decode(t, start)
    except json.JSONDecodeError:
        return None
    return obj["records"] if isinstance(obj, dict) and isinstance(obj.get("records"), list) else None


def _validated(recs, case_ids: Sequence[int], required) -> list[dict] | None:
    if not all(isinstance(r, dict) for r in recs):
        return None
    if not {int(c) for c in case_ids} <= {_as_case_id(r.get("case_id")) for r in recs}:
        return None
    if not all(set(required) <= set(r) for r in recs):
        return None
    return recs


def parse_records(text: str, case_ids: Sequence[int], *, required=REQUIRED) -> list[dict] | None:
    t = strip_fences(text)
    brace_i, bracket_i = t.find("{"), t.find("[")
    if brace_i != -1 and (bracket_i == -1 or brace_i < bracket_i):
        # the first bracket in the text opens an object: that object is the top level,
        # and only its `records` key is ever consulted (R1) - no fallback to a bare-array
        # scan, which would otherwise find an array nested under some other key.
        wrapped = _wrapped(t, brace_i)
        return _validated(wrapped, case_ids, required) if wrapped is not None else None
    dec = json.JSONDecoder()
    for i in range(len(t)):
        if t[i] == "[":
            try:
                recs, _end = dec.raw_decode(t, i)
            except json.JSONDecodeError:
                continue
            if isinstance(recs, list):
                out = _validated(recs, case_ids, required)
                if out is not None:
                    return out
    return None


def split_unit(unit: Unit) -> tuple[Unit, Unit]:
    ids = list(unit.case_ids); k = (len(ids) + 1) // 2
    return (Unit(f"{unit.id}-a", tuple(ids[:k]), unit.meta), Unit(f"{unit.id}-b", tuple(ids[k:]), unit.meta))
