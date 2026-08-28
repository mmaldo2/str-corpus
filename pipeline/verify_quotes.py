"""Verify stage (spec §10) — deterministic verbatim-quote validation.

For every quote in every extraction record:
1. normalized exact substring match against the case's norm_text (same
   textnorm version) -> verified; canonical raw char span + reporter page
   attached from the offset map + page_map.
2. else fuzzy match (rapidfuzz partial ratio >= 92 over token windows)
   -> verified-fuzzy, queued for human eyeball.
3. else the quote is dropped, every field it supported is nulled, the case is
   flagged extraction-invalid and returned to the re-map queue.

Nothing unverified passes to Reduce.

Usage:
    python pipeline/verify_quotes.py --run-id cycle-001
Reads  runs/<run-id>/extractions/*.json  (list of extraction records)
Writes runs/<run-id>/verified/<same name>.json + verify-report.json
"""

import argparse
import bisect
import json
import sqlite3
import sys
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textnorm import NORM_VERSION, normalize, normalize_text

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
RUNS = ROOT / "runs"

FUZZY_THRESHOLD = 92.0


def page_for_offset(page_map: list, raw_offset: int):
    starts = [p[0] for p in page_map]
    i = bisect.bisect_right(starts, raw_offset) - 1
    return page_map[max(0, i)][1]


def verify_quote(quote_text: str, case_row: dict) -> dict:
    """Returns {status, raw_span, reporter_page} with status in
    verified | verified-fuzzy | failed."""
    qnorm = normalize_text(quote_text)
    norm_text = case_row["norm_text"]
    idx = norm_text.find(qnorm)
    if idx >= 0 and qnorm:
        _, offsets = normalize(case_row["raw_text"])
        raw_start = offsets[idx]
        raw_end = offsets[min(idx + len(qnorm) - 1, len(offsets) - 1)] + 1
        return {
            "status": "verified",
            "raw_span": [raw_start, raw_end],
            "reporter_page": page_for_offset(case_row["page_map"], raw_start),
        }
    if not qnorm:
        return {"status": "failed", "raw_span": None, "reporter_page": None}
    # fuzzy: best window of comparable length
    n = len(qnorm)
    best_score, best_pos = 0.0, -1
    step = max(20, n // 4)
    for pos in range(0, max(1, len(norm_text) - n + 1), step):
        window = norm_text[pos : pos + n + step]
        score = fuzz.partial_ratio(qnorm, window)
        if score > best_score:
            best_score, best_pos = score, pos
            if score == 100.0:
                break
    if best_score >= FUZZY_THRESHOLD:
        _, offsets = normalize(case_row["raw_text"])
        raw_start = offsets[min(best_pos, len(offsets) - 1)]
        return {
            "status": "verified-fuzzy",
            "raw_span": [raw_start, raw_start + n],
            "reporter_page": page_for_offset(case_row["page_map"], raw_start),
            "fuzzy_score": best_score,
        }
    return {"status": "failed", "raw_span": None, "reporter_page": None}


def load_case(conn, case_id: int) -> dict | None:
    row = conn.execute(
        """SELECT raw_text, norm_text, page_map, norm_version FROM cases
           WHERE case_id=?""",
        (case_id,),
    ).fetchone()
    if not row:
        return None
    if row[3] != NORM_VERSION:
        raise RuntimeError(
            f"case {case_id} normalized at v{row[3]}, verifier at v{NORM_VERSION}: re-ingest"
        )
    return {"raw_text": row[0], "norm_text": row[1], "page_map": json.loads(row[2])}


def verify_record(conn, rec: dict) -> dict:
    case_row = load_case(conn, rec["case_id"])
    if case_row is None:
        rec["extraction_status"] = "extraction-invalid"
        rec["invalid_reason"] = "case not in corpus"
        return rec
    # relevant:false records carry no doctrine; quotes optional (§8 rule 4)
    if rec.get("relevant") is False:
        rec["quotes"] = []
        rec["extraction_status"] = "ok"
        return rec
    supported_ok: set[str] = set()
    kept_quotes = []
    any_failed = False
    for q in rec.get("quotes", []):
        v = verify_quote(q.get("text", ""), case_row)
        if v["status"] == "failed":
            any_failed = True
            continue
        kept_quotes.append({**q, **v})
        if q.get("supports"):
            supported_ok.add(q["supports"])
    rec["quotes"] = kept_quotes
    # null every doctrinal field whose support died (spec §8 hard requirement)
    for field in ("characterization", "polarity", "holding_summary"):
        if rec.get(field) is not None and field not in supported_ok:
            rec[field] = None
            rec.setdefault("nulled_fields", []).append(field)
    if any_failed or rec.get("nulled_fields"):
        rec["extraction_status"] = "extraction-invalid" if not kept_quotes else "partial"
    else:
        rec["extraction_status"] = "ok"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    ext_dir = RUNS / args.run_id / "extractions"
    out_dir = RUNS / args.run_id / "verified"
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"records": 0, "ok": 0, "partial": 0, "invalid": 0,
             "quotes_verified": 0, "quotes_fuzzy": 0, "quotes_dropped": 0}
    remap = []
    for f in sorted(ext_dir.glob("*.json")):
        records = json.loads(f.read_text(encoding="utf-8"))
        out = []
        for rec in records:
            before = len(rec.get("quotes", []))
            rec = verify_record(conn, rec)
            after = len(rec.get("quotes", []))
            stats["records"] += 1
            stats["quotes_dropped"] += before - after
            stats["quotes_verified"] += sum(
                1 for q in rec["quotes"] if q.get("status") == "verified"
            )
            stats["quotes_fuzzy"] += sum(
                1 for q in rec["quotes"] if q.get("status") == "verified-fuzzy"
            )
            key = {"ok": "ok", "partial": "partial"}.get(rec["extraction_status"], "invalid")
            stats[key] += 1
            if rec["extraction_status"] == "extraction-invalid":
                remap.append({"case_id": rec["case_id"], "batch": f.name})
            out.append(rec)
        (out_dir / f.name).write_text(json.dumps(out, indent=1), encoding="utf-8")
    (RUNS / args.run_id / "verify-report.json").write_text(
        json.dumps({"stats": stats, "remap_queue": remap}, indent=1), encoding="utf-8"
    )
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
