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
sys.path.insert(0, str(ROOT))
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.bootstrap import _relevance_patches
from corpus_engine.ledger.fold import State

DB = ROOT / "data" / "db" / "corpus.db"


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

    led = open_ledger()
    head = led.view()
    trial = State(records=dict(head.state.records), order=list(head.state.order),
                  cycles=dict(head.state.cycles), in_file=dict(head.state.in_file))
    patches = _relevance_patches(ROOT, load_domain().reviewer_default, trial,
                                 why_prefix="relevance re-check:")
    res = led.apply(patches, note="relevance re-check")
    for cid, v in verdicts.items():
        print(f"{cid}: {'IRRELEVANT' if v.get('relevant') is False else 'relevant'} — {v.get('justification')}")
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; replay_ok={res.replay_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
