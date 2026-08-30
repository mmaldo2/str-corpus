"""Apply the human's saved review decisions to produce the adjudicated
cycle ledger — the durable record cycle 002 builds on.

Inputs: decisions-final.json (from the review artifact), the section data
(same assembly as make_review), verified extractions, remap records +
adjudications.
Outputs:
  data/adjudications/cycle-001.json   raw decisions mapped to entities
  data/ledger/cycle-001.jsonl         adjudicated relevant-case ledger
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_review import load_data

ROOT = Path(__file__).resolve().parent.parent
RUN = "cycle-001-shard-02"

# Pa. Commw. STR cases whose reasoning Slice of Life v. Hamilton Twp.,
# 207 A.3d 886 (Pa. 2019), abrogated — flagged per user review note;
# citator verification still required.
SLICE_OF_LIFE_RISK_CITES = {"147 A.3d 947", "154 A.3d 408", "176 A.3d 396",
                            "164 A.3d 633"}
SHVEKH_CASE_ID = 12315742  # user-approved correction: who -> unclear


def main() -> int:
    data = load_data(RUN)
    state = json.loads(
        (ROOT / "runs" / RUN / "decisions-final.json").read_text(encoding="utf-8")
    )

    # ---- map decisions to entities
    adjudications = {"savedAt": (state.get("_meta") or {}).get("savedAt"),
                     "items": []}
    for sec in ("A", "B", "C", "D"):
        for i, e in enumerate(data[sec]):
            st = state.get(f"{sec}-{i}") or {}
            adjudications["items"].append(
                {"section": sec, "index": i, "case_id": e.get("case_id"),
                 "cite": e.get("cite"), "field": e.get("field"),
                 "decision": st.get("decision"), "note": st.get("note"),
                 "citator": bool(st.get("citator")),
                 "recommendation": e.get("recommendation")}
            )
    adj_dir = ROOT / "data" / "adjudications"
    adj_dir.mkdir(parents=True, exist_ok=True)
    (adj_dir / "cycle-001.json").write_text(
        json.dumps(adjudications, indent=1), encoding="utf-8"
    )

    # ---- assemble ledger
    recs = []
    for f in sorted((ROOT / "runs" / RUN / "verified").glob("*.json")):
        recs.extend(json.loads(f.read_text(encoding="utf-8")))
    remap = []
    for f in sorted((ROOT / "runs" / "cycle-001-remap" / "verified").glob("*.json")):
        remap.extend(json.loads(f.read_text(encoding="utf-8")))
    remap_ids = {r["case_id"] for r in remap}
    # replace originals with remap versions
    ledger = {r["case_id"]: dict(r) for r in recs if r["case_id"] not in remap_ids}
    for r in remap:
        ledger[r["case_id"]] = dict(r)
    for r in ledger.values():
        r["review"] = {"status": "machine", "flags": [], "notes": []}

    # C resolutions: user accepted every third-reader recommendation
    for i, e in enumerate(data["C"]):
        st = state.get(f"C-{i}") or {}
        r = ledger.get(e["case_id"])
        if not r or not st.get("decision"):
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"),
                 "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            fieldmap = {"relevant": "relevant", "polarity": "polarity",
                        "characterization": "characterization"}
            f = fieldmap[e["field"]]
            if f == "relevant":
                value = value if isinstance(value, bool) else str(value).lower() == "true"
            r[f] = value
            r["review"]["notes"].append(
                f"{f} adjudicated -> {value} (disagreement resolved, human-confirmed)")
            r["review"]["status"] = "human-adjudicated"

    # D resolutions (remap disagreements)
    for i, e in enumerate(data["D"]):
        st = state.get(f"D-{i}") or {}
        r = ledger.get(e["case_id"])
        if not r or not st.get("decision"):
            continue
        if st["decision"] == "other":
            r["review"]["flags"].append(f"open-question:{e.get('field')}")
            r["review"]["notes"].append(f"user note: {st.get('note')}")
            r["review"]["status"] = "pending-user-question"
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"),
                 "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            f = e["field"]
            if f == "relevant":
                value = value if isinstance(value, bool) else str(value).lower() == "true"
            r[f] = value
            r["review"]["notes"].append(f"{f} adjudicated -> {value}")
            r["review"]["status"] = "human-adjudicated"

    # A decisions
    for i, e in enumerate(data["A"]):
        st = state.get(f"A-{i}") or {}
        r = ledger.get(e["case_id"])
        if not r:
            continue
        if st.get("decision") == "accept":
            r["review"]["status"] = "human-accepted"
        elif st.get("decision") == "needs-work":
            r["review"]["status"] = "needs-work"
        if st.get("note"):
            r["review"]["notes"].append(f"user note: {st['note']}")
        if st.get("citator"):
            r["review"]["flags"].append("citator-checked")

    # B: the single mismatch quote (Shvekh) is dropped
    for i, e in enumerate(data["B"]):
        st = state.get(f"B-{i}") or {}
        if st.get("decision") == "mismatch":
            r = ledger.get(e["case_id"])
            if r:
                r["quotes"] = [q for q in r.get("quotes", [])
                               if q.get("text") != e["quote"]]
                r["review"]["notes"].append(
                    "quote removed: human judged fuzzy match a real mismatch")

    # user-approved Shvekh correction
    shv = ledger.get(SHVEKH_CASE_ID)
    if shv:
        shv["who_was_letting"] = "unclear"
        shv["review"]["notes"].append(
            "who_was_letting corrected householder->unclear per human review: "
            "family resided elsewhere; whole-home VRBO rental of non-primary house")
        shv["review"]["status"] = "human-adjudicated"

    # Slice of Life abrogation-risk flags
    for r in ledger.values():
        if (r.get("cite") or "") in SLICE_OF_LIFE_RISK_CITES:
            r["review"]["flags"].append(
                "abrogation-risk: Slice of Life v. Hamilton Twp., 207 A.3d 886 "
                "(Pa. 2019) — per human review note; verify via citator")

    out_dir = ROOT / "data" / "ledger"
    out_dir.mkdir(parents=True, exist_ok=True)
    relevant = [r for r in ledger.values() if r.get("relevant")]
    with (out_dir / "cycle-001.jsonl").open("w", encoding="utf-8") as f:
        for r in sorted(relevant, key=lambda x: x.get("year") or 0):
            f.write(json.dumps(r) + "\n")
    import collections
    pol = collections.Counter(r.get("polarity") for r in relevant)
    status = collections.Counter(r["review"]["status"] for r in relevant)
    print(f"ledger: {len(relevant)} relevant cases -> data/ledger/cycle-001.jsonl")
    print("polarity:", dict(pol))
    print("review status:", dict(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
