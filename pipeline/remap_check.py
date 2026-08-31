"""Codex cross-check over the re-mapped records; emit field disagreements."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pre_review import MAPPER_PROMPT, case_text
from run_map import call_codex, parse_records

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="cycle-001-shard-02")
    run_id = ap.parse_args().run_id
    remap_run = run_id.split("-shard")[0] + "-remap"
    conn = sqlite3.connect(ROOT / "data" / "db" / "corpus.db")
    remap = json.loads(
        (ROOT / "runs" / remap_run / "verified" / "remap-001.json")
        .read_text(encoding="utf-8")
    )
    queue = json.loads(
        (ROOT / "runs" / run_id / "review-queue.json").read_text(encoding="utf-8")
    )["nulled"]
    info = {e["case_id"]: e for e in queue}
    header = (
        MAPPER_PROMPT.read_text(encoding="utf-8")
        + "\n\n# NOTE\nCopy quotes EXACTLY as printed including OCR errors.\n"
    )
    all_out = []
    for i in range(0, len(remap), 7):
        grp = remap[i : i + 7]
        payload = header + f'\nSet "worker": "codex", "batch_id": "remap-check-{i//7}".\n'
        for r in grp:
            e = info.get(r["case_id"], {})
            name, cite = e.get("name"), e.get("cite")
            payload += (
                f"\n## case_id {r['case_id']} — {name}, {cite} "
                f"({e.get('jur')} {e.get('year')})\n### Opinion text\n"
                f"{case_text(conn, r['case_id'])}\n"
            )
        fake_batch = {"cases": [{"case_id": r["case_id"]} for r in grp]}
        recs = parse_records(call_codex(payload), fake_batch)
        if recs:
            all_out.extend(recs)
        print(f"group {i//7}: {'ok ' + str(len(recs)) if recs else 'PARSE FAIL'}")
    (ROOT / "runs" / remap_run / "codex-check.json").write_text(
        json.dumps(all_out, indent=1), encoding="utf-8"
    )
    by = {r["case_id"]: r for r in all_out}
    dis = []
    for r in remap:
        o = by.get(r["case_id"])
        if not o:
            continue
        for f in ("relevant", "polarity", "characterization"):
            if r.get(f) != o.get(f):
                dis.append(
                    {"case_id": r["case_id"], "field": f,
                     "claude": r.get(f), "codex": o.get(f)}
                )
    (ROOT / "runs" / remap_run / "remap-disagreements.json").write_text(
        json.dumps(dis, indent=1), encoding="utf-8"
    )
    print(
        f"checked: {len(all_out)} | field disagreements: {len(dis)} "
        f"| cases: {len({d['case_id'] for d in dis})}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
