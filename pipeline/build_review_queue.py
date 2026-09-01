"""Build the human-review queue inputs for a run:
  runs/<run>/review-queue.json  (fuzzy, disagreements, nulled, householder_nights)
  runs/<run>/fuzzy-diffs.json   (quote vs corpus text at the fuzzy match)

Usage: python pipeline/build_review_queue.py --run-id cycle-002-shard-01
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    run = ROOT / "runs" / ap.parse_args().run_id
    c = sqlite3.connect(DB)
    c.execute("PRAGMA busy_timeout=60000")

    def caseinfo(cid):
        r = c.execute(
            "SELECT cite, name_abbreviation, decision_year, jurisdiction, court "
            "FROM cases WHERE case_id=?", (cid,)).fetchone()
        return ({"cite": r[0], "name": r[1], "year": r[2], "jur": r[3], "court": r[4]}
                if r else {})

    recs = []
    for f in sorted((run / "verified").glob("*.json")):
        recs.extend(json.loads(f.read_text(encoding="utf-8")))

    fuzzy, diffs = [], []
    for r in recs:
        for q in r.get("quotes", []):
            if q.get("status") == "verified-fuzzy":
                fuzzy.append({**caseinfo(r["case_id"]), "case_id": r["case_id"],
                              "quote": q.get("text", ""), "supports": q.get("supports"),
                              "score": q.get("fuzzy_score"), "page": q.get("reporter_page")})
                if q.get("raw_span"):
                    s, e = q["raw_span"]
                    src = c.execute(
                        "SELECT substr(raw_text, ?, ?) FROM cases WHERE case_id=?",
                        (max(1, s - 30), (e - s) + 90, r["case_id"])).fetchone()[0]
                    diffs.append({"case_id": r["case_id"], "quote": q["text"],
                                  "source": src.replace("\n", " "),
                                  "score": q.get("fuzzy_score"),
                                  "page": q.get("reporter_page"),
                                  "supports": q.get("supports")})

    dis, seen = [], set()
    dpath = run / "disagreements.jsonl"
    if dpath.exists():
        for line in dpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                k = (d["case_id"], d["field"], d["batch_id"])
                if k in seen:
                    continue
                seen.add(k)
                dis.append({**d, **caseinfo(d["case_id"])})

    nulled = [{**caseinfo(r["case_id"]), "case_id": r["case_id"],
               "nulled": r.get("nulled_fields"), "who": r.get("who_was_letting"),
               "duration": r.get("duration_of_occupancy"),
               "holding": (r.get("holding_summary") or "(nulled)")[:250],
               "notes": (r.get("notes") or "")[:200]}
              for r in recs
              if r.get("relevant") and "polarity" in (r.get("nulled_fields") or [])]

    hxn = [{**caseinfo(r["case_id"]), "case_id": r["case_id"],
            "characterization": r.get("characterization"),
            "holding": r.get("holding_summary"),
            "quotes": [{"t": q.get("text"), "p": q.get("reporter_page"),
                        "s": q.get("status")} for q in r.get("quotes", [])]}
           for r in recs
           if r.get("relevant") and r.get("polarity") == "favorable"
           and r.get("who_was_letting") == "householder"
           and r.get("duration_of_occupancy") == "nights"]

    (run / "review-queue.json").write_text(json.dumps(
        {"fuzzy": fuzzy, "disagreements": dis, "nulled": nulled,
         "householder_nights": hxn}, indent=1), encoding="utf-8")
    # preserve classifications/recommendations from earlier passes when
    # regenerating (a rebuild must never erase reader verdicts)
    dpath = run / "fuzzy-diffs.json"
    if dpath.exists():
        prev = {(d["case_id"], d["quote"]): d
                for d in json.loads(dpath.read_text(encoding="utf-8"))}
        for d in diffs:
            old = prev.get((d["case_id"], d["quote"]))
            if old:
                for k in ("classification", "quote_coverage", "miss_runs",
                          "recommendation", "justification", "corrected_quote"):
                    if k in old:
                        d[k] = old[k]
    dpath.write_text(json.dumps(diffs, indent=1), encoding="utf-8")
    print(f"fuzzy {len(fuzzy)} | disagreements {len(dis)} | nulled {len(nulled)} "
          f"| householder x nights {len(hxn)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
