"""Relevance re-check for ledger records the reviewer flagged as possibly
irrelevant. Third reader answers the schema's relevance question; records
judged irrelevant are set relevant=false in their ledger (annotated), so
they leave the counts but stay in the file for audit.

Usage: python pipeline/relevance_recheck.py <case_id> [<case_id> ...]
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pre_review import claude_call, parse_json_array

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
LEDGERS = sorted((ROOT / "data" / "ledger").glob("cycle-*.jsonl"))


def main() -> int:
    ids = [int(a) for a in sys.argv[1:]]
    conn = sqlite3.connect(DB)
    payload = (
        "Relevance re-check. A case is RELEVANT to this ledger only if it "
        "materially bears on compensated occupancy of another's dwelling or "
        "rooms (lodgers, boarders, roomers, letting rooms/houses/camps for "
        "pay), its legal character, or its regulation — as a matter the court "
        "actually decided or reasoned about. A case where letting is mere "
        "background to an unrelated dispute (a remedy question, a procedural "
        "point, a tort about premises, a rent-control administrative matter "
        "with no holding about the letting itself) is NOT relevant.\n"
        "Output ONLY a JSON array: "
        '{"case_id": ..., "relevant": true|false, "justification": "1-2 sentences"}\n'
    )
    for cid in ids:
        r = conn.execute(
            "SELECT cite, decision_year, jurisdiction, raw_text FROM cases WHERE case_id=?",
            (cid,)).fetchone()
        payload += (f"\n## case_id {cid} — {r[0]} ({r[2]} {r[1]})\n### Opinion text\n"
                    f"{r[3]}\n")
    verdicts = {v["case_id"]: v for v in (parse_json_array(claude_call(payload)) or [])
                if isinstance(v, dict)}
    out_dir = ROOT / "runs" / "relevance-recheck"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "verdicts.json").write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
    dropped = 0
    for f in LEDGERS:
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        for row in rows:
            v = verdicts.get(row["case_id"])
            if v is None:
                continue
            rv = row.setdefault("review", {"status": "machine", "flags": [], "notes": []})
            if v.get("relevant") is False:
                row["relevant"] = False
                rv["notes"].append(
                    f"relevance re-check 2026-09-01 -> irrelevant (user flag + reader): "
                    f"{v.get('justification')}")
                dropped += 1
            else:
                rv["notes"].append(
                    f"relevance re-check 2026-09-01 -> relevant confirmed: {v.get('justification')}")
            rv["status"] = "human-adjudicated"
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    for cid, v in verdicts.items():
        print(f"{cid}: {'IRRELEVANT' if v.get('relevant') is False else 'relevant'} — {v.get('justification')}")
    print(f"dropped {dropped} of {len(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
