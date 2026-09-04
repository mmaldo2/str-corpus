"""Batch packing: group signal-bearing cases into homogeneous era x
jurisdiction batches with the spec §7 priority order. Moved verbatim from
pipeline/shard.py emit_batches; the only change is that gold ids and the
already-read exclusion set are explicit inputs instead of globals, which
is what makes the output reproducible (ADR-0009)."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path


def build_batches(conn: sqlite3.Connection, run_id: str, *,
                  gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18) -> list[dict]:
    rows = conn.execute(
        """SELECT s.case_id, s.era_partition, s.jurisdiction,
                  s.selector_id, s.selector_version, s.matched_text,
                  s.char_span_start, s.char_span_end, s.chunk_id, s.cosine, s.run_id
           FROM signals s ORDER BY s.era_partition, s.jurisdiction, s.case_id"""
    ).fetchall()
    by_case: dict = {}
    for r in rows:
        e = by_case.setdefault(
            r[0], {"case_id": r[0], "era_partition": r[1], "jurisdiction": r[2], "signals": []})
        e["signals"].append(
            {"selector_id": r[3], "selector_version": r[4], "matched_text": r[5],
             "char_span": [r[6], r[7]], "chunk_id": r[8], "cosine": r[9], "run_id": r[10]})
    groups: dict = {}
    for e in by_case.values():
        groups.setdefault((e["era_partition"], e["jurisdiction"]), []).append(e)
    if exclude_ids:
        for key in groups:
            groups[key] = [e for e in groups[key] if e["case_id"] not in exclude_ids]
        groups = {k: v for k, v in groups.items() if v}
    pending = []
    for (era, jur), cases in sorted(groups.items(), key=lambda kv: str(kv[0])):
        cases.sort(key=lambda e: (-len({s["selector_id"] for s in e["signals"]}), e["case_id"]))
        for i in range(0, len(cases), batch_size):
            chunk = cases[i:i + batch_size]
            pending.append({
                "era_partition": era, "jurisdiction": jur, "cases": chunk,
                "_gold": sum(1 for e in chunk if e["case_id"] in gold_ids),
                "_density": max(len({s["selector_id"] for s in e["signals"]}) for e in chunk)})
    pending.sort(key=lambda b: (-b["_gold"], -b["_density"]))
    for n, batch in enumerate(pending, 1):
        batch.pop("_gold"), batch.pop("_density")
        batch["batch_id"] = f"{run_id}-batch-{n:03d}"
    return pending


def pack_batches(conn: sqlite3.Connection, run_id: str, out_dir: Path, *,
                 gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18) -> int:
    batches = build_batches(conn, run_id, gold_ids=gold_ids, exclude_ids=exclude_ids, batch_size=batch_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.json"):
        old.unlink()
    for n, batch in enumerate(batches, 1):
        (out_dir / f"batch-{n:03d}.json").write_text(json.dumps(batch, indent=1), encoding="utf-8")
    return len(batches)
