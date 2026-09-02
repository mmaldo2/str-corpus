"""Apply the human's saved review decisions to produce the adjudicated
cycle ledger — the durable record cycle 002 builds on.

Inputs: decisions-final.json (from the review artifact), the section data
(same assembly as make_review), verified extractions, remap records +
adjudications.
Outputs:
  data/adjudications/cycle-001.json   raw decisions mapped to entities
  data/ledger/cycle-001.jsonl         adjudicated relevant-case ledger,
                                       written by the ledger itself
"""

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_review import load_data

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.bootstrap import _cycle_patches

import argparse as _ap

_args = _ap.ArgumentParser()
_args.add_argument("--run-id", default="cycle-001-shard-02")
RUN = _args.parse_args().run_id
CYCLE = RUN.split("-shard")[0]


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
    (adj_dir / f"{CYCLE}.json").write_text(
        json.dumps(adjudications, indent=1), encoding="utf-8"
    )

    # ---- build and apply the ledger patches for this cycle
    led = open_ledger()
    trial = copy.deepcopy(led.view().state)
    patches = _cycle_patches(ROOT, CYCLE, RUN, load_domain().reviewer_default, trial)
    patches = [replace(p, why=p.why.replace("bootstrap:", f"{CYCLE} close:", 1)) for p in patches]
    res = led.apply(patches, note=f"{CYCLE} adjudication")
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; replay_ok={res.replay_ok}")
    print(led.view().counts(by=("polarity",)).render_markdown())
    return 0


if __name__ == "__main__":
    sys.exit(main())
