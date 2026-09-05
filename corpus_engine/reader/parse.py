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


def parse_records(text: str, case_ids: Sequence[int], *, required=REQUIRED) -> list[dict] | None:
    t = strip_fences(text); start, end = t.find("["), t.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        recs = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(recs, list) or not all(isinstance(r, dict) for r in recs):
        return None
    if not {int(c) for c in case_ids} <= {r.get("case_id") for r in recs}:
        return None
    if not all(set(required) <= set(r) for r in recs):
        return None
    return recs


def split_unit(unit: Unit) -> tuple[Unit, Unit]:
    ids = list(unit.case_ids); k = (len(ids) + 1) // 2
    return (Unit(f"{unit.id}-a", tuple(ids[:k]), unit.meta), Unit(f"{unit.id}-b", tuple(ids[k:]), unit.meta))
