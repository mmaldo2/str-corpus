"""Byte-exact rendering of ledger records. json.dumps defaults are load-bearing:
ensure_ascii=True, separators (', ', ': '), insertion key order, one record per
line, '\n' terminated (matches apply_adjudications.py and the hygiene passes)."""
from __future__ import annotations
import json


def dumps_record(rec: dict) -> str:
    return json.dumps(rec)


def render_cycle(records: list[dict]) -> bytes:
    return "".join(dumps_record(r) + "\n" for r in records).encode("utf-8")


def parse_cycle(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip()]
