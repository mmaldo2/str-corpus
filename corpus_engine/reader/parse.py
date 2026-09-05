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


def _top_level(t: str) -> tuple[bool, list | None]:
    """What actually decodes at the top of `t` (position 0), not just what character comes
    first. A response can carry prose before its JSON - `"Cf. {id.} below: [...]"` has a
    `{` earlier in the text than its real answer, but that `{` never decodes as JSON on its
    own, so it must not be mistaken for the top-level value (review finding, task-1-review).

    Returns `(is_object, records_or_None)`. When the top level decodes to an object, R1
    applies: only its `records` key is ever consulted, never scanned for a bare array
    nested in some other key - so the caller must not fall back to the bare-array scan in
    that case, whether or not `records` was there. When the top level is anything else
    (not an object at all, or nothing decodes at position 0), `is_object` is False and the
    caller falls back to scanning the text for a bare array."""
    dec = json.JSONDecoder()
    try:
        obj, _end = dec.raw_decode(t, 0)
    except json.JSONDecodeError:
        return False, None
    if not isinstance(obj, dict):
        return False, None
    return True, (obj["records"] if isinstance(obj.get("records"), list) else None)


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
    is_object, wrapped = _top_level(t) if t else (False, None)
    if is_object:
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
