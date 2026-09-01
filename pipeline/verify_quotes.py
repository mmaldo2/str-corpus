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
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
RUNS = ROOT / "runs"

sys.path.insert(0, str(ROOT))
from corpus_engine.verification import (FUZZY_THRESHOLD, page_for_offset,  # noqa: E402,F401
                                        verify_quote, load_case, verify_record)


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
