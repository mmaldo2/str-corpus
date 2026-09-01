"""Targeted polarity re-review of favorable ledger records (hygiene pass
after the cycle-003 finding that pro-occupant outcomes were being marked
favorable).

  python pipeline/polarity_review.py stage     # pick candidates, run third reader
  python pipeline/polarity_review.py apply     # apply saved decisions to ledgers

Candidates: favorable records (all cycle ledgers) whose holding/notes hit
occupant-rights vocabulary. The reader re-judges polarity under the
tightened definition (owner's right to let; pro-tenant is adverse). Only
records whose recommended polarity DIFFERS reach the human queue; the rest
auto-keep and are logged in runs/polarity-review/unchanged.json.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pre_review import claude_call, parse_json_array

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
LEDGERS = sorted((ROOT / "data" / "ledger").glob("cycle-*.jsonl"))
RUN = ROOT / "runs" / "polarity-review"

SUSPECT = re.compile(
    r"rent[- ]control|rent[- ]stabiliz|emergency rent|rent law|rent regulat|OPA|"
    r"statutory tenan|permanent tenant|holdover|evict|dispossess|summary proceeding|"
    r"habitab|implied (warranty|covenant)|fit for (habitation|use)|tenant'?s? right|"
    r"right to occupy|occupan(t|cy) (right|protect)|multiple dwelling law|"
    r"landlord.{0,40}liab|licensee.{0,30}(evict|remove)|lock(ed)? out|"
    r"security deposit|constructive eviction|quiet enjoyment",
    re.IGNORECASE,
)

DEFINITION = (
    "POLARITY IS JUDGED FROM THE PROPERTY OWNER'S RIGHT TO LET — never from the "
    "occupant's interests. favorable = the owner's liberty to let rooms or a "
    "dwelling for compensation, on the owner's terms, was recognized, protected, "
    "or assumed lawful. adverse = regulation or restriction of letting upheld, OR "
    "occupant/tenant rights expanded against the owner (rent control, eviction "
    "protection, statutory or permanent tenancy, habitability duties, limits on "
    "the owner's recovery of possession) without also affirming the owner's "
    "freedom to let. mixed = both. Pro-tenant is NOT favorable."
)


def load_ledgers() -> list[dict]:
    rows = []
    for f in LEDGERS:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["_ledger"] = f.name
                rows.append(r)
    return rows


def cmd_stage() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    rows = load_ledgers()
    fav = [r for r in rows if r.get("relevant") and r.get("polarity") == "favorable"]
    cands = [r for r in fav if SUSPECT.search(
        (r.get("holding_summary") or "") + " " + (r.get("notes") or ""))]
    print(f"favorable records: {len(fav)} | suspect candidates: {len(cands)}")
    recs = []
    for i in range(0, len(cands), 5):
        group = cands[i : i + 5]
        payload = (
            "You are re-judging the POLARITY field of extraction records about "
            "historical American cases on compensated occupancy of another's "
            "dwelling (lodgers, boarders, letting), for litigation on the "
            "OWNER'S right to let property short-term.\n\n" + DEFINITION +
            "\n\nEach record was previously marked 'favorable'. Read the opinion "
            "and decide whether that stands under this definition. Output ONLY a "
            "JSON array, one object per case:\n"
            '{"case_id": ..., "recommendation": "favorable"|"adverse"|"mixed", '
            '"justification": "2-3 sentences grounded in the opinion", '
            '"supporting_quote": "verbatim short passage"}\n'
        )
        for r in group:
            text = conn.execute(
                "SELECT raw_text FROM cases WHERE case_id=?", (r["case_id"],)
            ).fetchone()[0]
            payload += (
                f"\n## case_id {r['case_id']} — {r.get('cite')} ({r.get('jurisdiction')} "
                f"{r.get('year')})\nPrevious holding summary: {r.get('holding_summary')}\n"
                f"### Opinion text\n{text}\n"
            )
        out = parse_json_array(claude_call(payload))
        if out:
            recs.extend(out)
            print(f"group {i//5}: {len(out)} verdicts", flush=True)
        else:
            print(f"group {i//5}: PARSE FAILURE", flush=True)
    by = {r.get("case_id"): r for r in recs if isinstance(r, dict)}
    changed, unchanged = [], []
    for r in cands:
        v = by.get(r["case_id"])
        if not v:
            continue
        entry = {"case_id": r["case_id"], "cite": r.get("cite"),
                 "name": r.get("name") or "", "year": r.get("year"),
                 "jur": r.get("jurisdiction"), "court": r.get("court"),
                 "field": "polarity", "claude": "favorable",
                 "codex": v.get("recommendation"), "batch_id": "polarity-review",
                 "recommendation": v.get("recommendation"),
                 "justification": v.get("justification"),
                 "supporting_quote": v.get("supporting_quote"),
                 "holding": r.get("holding_summary"), "ledger": r["_ledger"]}
        (unchanged if v.get("recommendation") == "favorable" else changed).append(entry)
    (RUN / "unchanged.json").write_text(json.dumps(unchanged, indent=1), encoding="utf-8")
    (RUN / "review-queue.json").write_text(json.dumps(
        {"fuzzy": [], "disagreements": changed, "nulled": [], "householder_nights": []},
        indent=1), encoding="utf-8")
    (RUN / "fuzzy-diffs.json").write_text("[]", encoding="utf-8")
    (RUN / "adjudications.json").write_text(json.dumps(
        [{"case_id": e["case_id"], "field": "polarity",
          "recommendation": e["recommendation"], "justification": e["justification"],
          "supporting_quote": e["supporting_quote"]} for e in changed], indent=1),
        encoding="utf-8")
    print(f"re-judged {len(by)}: {len(unchanged)} stay favorable (auto-keep), "
          f"{len(changed)} recommended changes -> human queue")


def cmd_apply() -> None:
    state = json.loads((RUN / "decisions-final.json").read_text(encoding="utf-8"))
    queue = json.loads((RUN / "review-queue.json").read_text(encoding="utf-8"))["disagreements"]
    decisions = {}
    for i, e in enumerate(queue):
        st = state.get(f"C-{i}") or {}
        d = st.get("decision")
        if not d:
            continue
        value = {"accept-rec": e["recommendation"], "claude": "favorable",
                 "codex": e["recommendation"]}.get(d)
        if d == "other":
            value = None
        decisions[e["case_id"]] = (value, st.get("note"), e["recommendation"])
    applied = 0
    for f in LEDGERS:
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in rows:
            if r["case_id"] in decisions:
                value, note, rec = decisions[r["case_id"]]
                rv = r.setdefault("review", {"status": "machine", "flags": [], "notes": []})
                if value and value != r.get("polarity"):
                    rv["notes"].append(
                        f"polarity {r.get('polarity')} -> {value} (polarity re-review "
                        f"2026-09-01, owner-right-to-let definition; reader rec {rec})")
                    r["polarity"] = value
                    applied += 1
                elif value:
                    rv["notes"].append("polarity re-review: favorable confirmed by human")
                else:
                    rv["flags"].append("polarity-open-question")
                if note:
                    rv["notes"].append(f"user note: {note}")
                rv["status"] = "human-adjudicated"
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"applied {applied} polarity changes across ledgers")


if __name__ == "__main__":
    {"stage": cmd_stage, "apply": cmd_apply}[sys.argv[1]]()
