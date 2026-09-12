"""A small validator over schema.json: required keys and JSON types per path."""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA = json.loads((Path(__file__).with_name("schema.json")).read_text(encoding="utf-8"))
_TYPES = {"string": str, "integer": int, "number": (int, float), "object": dict, "array": list, "null": type(None)}


def _ok(value, spec: str) -> bool:
    return any(isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
               for t in spec.split("|"))


def validate(doc: dict) -> list[str]:
    problems = []
    for path, keys in SCHEMA["required"].items():
        node = doc
        for part in [p for p in path.split(".") if p]:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            if path:
                problems.append(path)
            continue
        for k, spec in keys.items():
            full = f"{path}.{k}" if path else k
            if k not in node or not _ok(node[k], spec):
                problems.append(full)
    return sorted(set(problems))
