"""Gold-set recall evaluation (spec §9, amendment A9).

Metrics:
- Shard recall (HEADLINE): fraction of tier=brief gold cases present in the
  indexed corpus that emitted >=1 signal. Tier=treatise reported separately.
- Per-selector attribution: which selectors fired per gold hit; misses listed
  for planner postmortem.
- End-to-end recall: gold cases surviving Map with relevant=true (when
  extraction files exist for the run).

Usage:
    python pipeline/eval_recall.py [--run-id cycle-001] [--json]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.selector.engine import attribution  # noqa: E402

DB = ROOT / "data" / "db" / "corpus.db"
GOLD = ROOT / "data" / "gold" / "gold.jsonl"
RUNS = ROOT / "runs"


def load_gold() -> list[dict]:
    if not GOLD.exists():
        return []
    return [
        json.loads(line)
        for line in GOLD.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate(run_id: str | None) -> dict:
    conn = sqlite3.connect(DB)
    gold = load_gold()
    attr = attribution(conn, [g["case_id"] for g in gold if g.get("case_id")])
    report: dict = {"tiers": {}, "misses": [], "hits": []}
    for tier in ("brief-letting", "brief-all", "treatise"):
        if tier == "brief-letting":
            entries = [
                g for g in gold
                if g.get("tier") == "brief" and g.get("domain") == "letting"
            ]
        elif tier == "brief-all":
            entries = [g for g in gold if g.get("tier") == "brief"]
        else:
            entries = [g for g in gold if g.get("tier") == "treatise"]
        in_corpus = [g for g in entries if g.get("case_id")]
        hits = []
        misses = []
        for g in in_corpus:
            sels = attr[g["case_id"]]
            if sels:
                hits.append({**g, "selectors": sorted({f"{r.selector_id}@v{r.selector_version}" for r in sels})})
            else:
                misses.append(g)
        report["tiers"][tier] = {
            "total": len(entries),
            "resolved_in_corpus": len(in_corpus),
            "signaled": len(hits),
            "shard_recall": round(len(hits) / len(in_corpus), 3) if in_corpus else None,
        }
        if tier == "brief-letting":
            report["hits"] = hits
            report["misses"] = misses

    # end-to-end recall from extraction files, if present
    if run_id:
        ext_dir = RUNS / run_id / "extractions"
        if ext_dir.exists():
            relevant_ids = set()
            for f in ext_dir.glob("*.json"):
                for rec in json.loads(f.read_text(encoding="utf-8")):
                    if rec.get("relevant"):
                        relevant_ids.add(rec["case_id"])
            brief_ids = {
                g["case_id"] for g in gold if g.get("tier") == "brief" and g.get("case_id")
            }
            surviving = brief_ids & relevant_ids
            report["end_to_end"] = {
                "gold_in_corpus": len(brief_ids),
                "surviving_map": len(surviving),
                "recall": round(len(surviving) / len(brief_ids), 3) if brief_ids else None,
            }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = evaluate(args.run_id)
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    for tier, m in report["tiers"].items():
        label = "HEADLINE" if tier == "brief-letting" else "secondary"
        print(
            f"{tier:9} ({label}): {m['signaled']}/{m['resolved_in_corpus']} signaled "
            f"of {m['total']} entries -> shard recall {m['shard_recall']}"
        )
    if report.get("end_to_end"):
        e = report["end_to_end"]
        print(f"end-to-end: {e['surviving_map']}/{e['gold_in_corpus']} -> {e['recall']}")
    if report["misses"]:
        print("\nMISSES (planner postmortem required per §6):")
        for g in report["misses"]:
            print(f"  {g.get('name') or g['cite']}  [{g['cite']}]  case_id={g['case_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
