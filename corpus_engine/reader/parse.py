from __future__ import annotations
import json
from typing import Sequence
from corpus_engine.reader.model import Unit

REQUIRED = ("case_id", "relevant", "polarity", "quotes")


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        i = t.find("[")
        t = t[i:] if i >= 0 else t
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


def parse_records(text: str, case_ids: Sequence[int], *, required=REQUIRED) -> list[dict] | None:
    t = strip_fences(text)
    dec = json.JSONDecoder()
    for i in range(len(t)):
        if t[i] == "[":
            try:
                recs, end = dec.raw_decode(t, i)
                if isinstance(recs, list) and all(isinstance(r, dict) for r in recs):
                    if not {int(c) for c in case_ids} <= {_as_case_id(r.get("case_id")) for r in recs}:
                        return None
                    if not all(set(required) <= set(r) for r in recs):
                        return None
                    return recs
            except json.JSONDecodeError:
                continue
    return None


def split_unit(unit: Unit) -> tuple[Unit, Unit]:
    ids = list(unit.case_ids); k = (len(ids) + 1) // 2
    return (Unit(f"{unit.id}-a", tuple(ids[:k]), unit.meta), Unit(f"{unit.id}-b", tuple(ids[k:]), unit.meta))
