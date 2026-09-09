"""Batch packing: group signal-bearing cases into homogeneous era x
jurisdiction batches with the spec §7 priority order. Moved verbatim from
pipeline/shard.py emit_batches; the only change is that gold ids and the
already-read exclusion set are explicit inputs instead of globals, which
is what makes the output reproducible (ADR-0009)."""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path


def persist_rankings(conn: sqlite3.Connection, run_id: str, ranker_id: str, scores: dict[int, float], ts: str) -> None:
    conn.executemany("INSERT OR REPLACE INTO rankings (run_id, ranker_id, case_id, score, ts) VALUES (?,?,?,?,?)",
                     [(run_id, ranker_id, cid, float(s), ts) for cid, s in sorted(scores.items())])
    conn.commit()


def build_batches(conn: sqlite3.Connection, run_id: str, *,
                  gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18,
                  ranker=None, ts: str | None = None, restrict_ids: set[int] | None = None) -> list[dict]:
    rows = conn.execute(
        """SELECT s.case_id, s.era_partition, s.jurisdiction,
                  s.selector_id, s.selector_version, s.matched_text,
                  s.char_span_start, s.char_span_end, s.chunk_id, s.cosine, s.run_id
           FROM signals s ORDER BY s.era_partition, s.jurisdiction, s.case_id, s.rowid"""
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
    if restrict_ids is not None:
        # The pool this run may consider at all: a re-rank of one earlier run's tail packs
        # that run's cases and no others, even though `signals` holds every case the selectors
        # have ever hit. Applied BEFORE the exclusion, so the manifest's excluded count is
        # about the restricted pool - the number an operator can check against the map.
        for key in list(groups):
            groups[key] = [e for e in groups[key] if e["case_id"] in restrict_ids]
        groups = {k: v for k, v in groups.items() if v}
    if exclude_ids:
        for key in groups:
            groups[key] = [e for e in groups[key] if e["case_id"] not in exclude_ids]
        groups = {k: v for k, v in groups.items() if v}
    scores: dict[int, float] | None = None
    if ranker is not None:
        from corpus_engine.ranker.ports import round6
        pool = [e["case_id"] for cases in groups.values() for e in cases]
        scores = {cid: round6(s) for cid, s in ranker.score(conn, run_id, pool).items()}
        persist_rankings(conn, run_id, ranker.ranker_id, scores, ts or time.strftime("%Y-%m-%dT%H:%M:%S"))
    pending = []
    for (era, jur), cases in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if scores is None:
            cases.sort(key=lambda e: (-len({s["selector_id"] for s in e["signals"]}), e["case_id"]))
        else:
            cases.sort(key=lambda e: (-scores[e["case_id"]], e["case_id"]))
            for e in cases:
                e["rank_score"] = scores[e["case_id"]]
        for i in range(0, len(cases), batch_size):
            chunk = cases[i:i + batch_size]
            b = {"era_partition": era, "jurisdiction": jur, "cases": chunk,
                 "_gold": sum(1 for e in chunk if e["case_id"] in gold_ids),
                 "_density": max(len({s["selector_id"] for s in e["signals"]}) for e in chunk)}
            if scores is not None:
                b["ranker_id"] = ranker.ranker_id
                b["_mean"] = sum(scores[e["case_id"]] for e in chunk) / len(chunk)
            pending.append(b)
    if scores is None:
        pending.sort(key=lambda b: (-b["_gold"], -b["_density"]))
    else:
        pending.sort(key=lambda b: (-b["_gold"], -b["_mean"], f"{b['era_partition']}|{b['jurisdiction']}"))
    for n, batch in enumerate(pending, 1):
        batch.pop("_gold"), batch.pop("_density"), batch.pop("_mean", None)
        batch["batch_id"] = f"{run_id}-batch-{n:03d}"
    return pending


def pack_batches(conn: sqlite3.Connection, run_id: str, out_dir: Path, *,
                 gold_ids: set[int], exclude_ids: set[int], batch_size: int = 18,
                 ranker=None, ts: str | None = None, restrict_ids: set[int] | None = None) -> int:
    batches = build_batches(conn, run_id, gold_ids=gold_ids, exclude_ids=exclude_ids, batch_size=batch_size,
                            ranker=ranker, ts=ts, restrict_ids=restrict_ids)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.json"):
        old.unlink()
    for n, batch in enumerate(batches, 1):
        # write_bytes, not write_text: `write_text` translates \n to \r\n on Windows,
        # and every other artefact this branch writes goes out as UTF-8 LF. NO trailing
        # newline: `tests/test_packing_char.py` pins these files byte for byte against the
        # committed cycle-003 pool, so the bytes are fixed by that characterization.
        (out_dir / f"batch-{n:03d}.json").write_bytes(
            json.dumps(batch, indent=1).encode("utf-8"))
    return len(batches)
