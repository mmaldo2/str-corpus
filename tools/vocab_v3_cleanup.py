"""One-off: null the two ledger records still carrying the legacy polarity value
`irrelevant` on an otherwise-relevant case (task-7-review finding 5).

`irrelevant` was page-1's shorthand for "this case is not relevant" (D2), applied to
`polarity` before that rule existed. Cases 608729 and 10225079 hold `relevant: true` with
`polarity: "irrelevant"` - a legacy vocabulary value mapper-v3's schema
(`corpus_engine/reader/schema.py::POLARITY_VALUES`) has no such entry for. The kit already
normalises this correctly (a polarity outside `POLARITY_VALUES` reads as undecided, not as a
value a reader can disagree with - see `corpus_engine/reader/measure.py::_decided`), so this
tool does not change what anything is scored against. It only replaces the stale literal in
the ledger with an honest `null`, through the ledger API, so the source of truth stops
carrying a value its own schema does not recognise.

This is a rule-basis correction, not a human judgment of either case's polarity: it says
"irrelevant is not a polarity value", not "this case is/isn't favorable". `relevant` and
`who_was_letting` are untouched - only `polarity` was outside the schema.

Run once: .venv\\Scripts\\python tools\\vocab_v3_cleanup.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.ledger import open_ledger                        # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                 # noqa: E402
from corpus_engine.reader.schema import POLARITY_VALUES             # noqa: E402

CASES = (608729, 10225079)
RUN_ID = "vocab-v3-cleanup-2026-09-05"
NOTE = "mapper-v3 vocabulary: irrelevant is not a polarity value; undecided"
WHY = ("vocab-v3-cleanup: legacy vocabulary value 'irrelevant' found in polarity on a "
       "relevant record; mapper-v3's schema has no such polarity value, so the field is "
       "undecided, not adjudicated one way or the other (task-7-review finding 5)")


def main() -> int:
    led = open_ledger()
    view = led.view()
    basis = Basis(rule_id="vocab-v3-cleanup", run_id=RUN_ID)
    patches: list[Patch] = []
    for cid in CASES:
        rec = view.record(cid)
        if rec.get("polarity") in POLARITY_VALUES or rec.get("polarity") is None:
            print(f"  {cid}: polarity is already {rec.get('polarity')!r}; nothing to do")
            continue
        if rec.get("polarity") != "irrelevant":
            raise SystemExit(f"{cid}: expected polarity 'irrelevant', found {rec.get('polarity')!r}; "
                             f"refusing to touch a value this tool was not built for")
        patches.append(Patch(cid, "set", "polarity", None, WHY, basis))
        patches.append(Patch(cid, "append", "review.notes", NOTE, WHY, basis))
    print(f"{len(CASES)} case(s) checked -> {len(patches)} patch(es)")
    res = led.apply(patches, note="vocab v3 cleanup: irrelevant is not a polarity value")
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; replay_ok={res.replay_ok}")
    rel = view.counts().total
    fav = view.counts(polarity="favorable").total
    favh = view.counts(polarity="favorable", who_was_letting="householder").total
    print(f"before: relevant {rel.human_reviewed + rel.machine_only} | "
          f"favorable {fav.human_reviewed + fav.machine_only} | "
          f"favorable+householder {favh.human_reviewed + favh.machine_only}")
    after = led.view()
    rel2 = after.counts().total
    fav2 = after.counts(polarity="favorable").total
    favh2 = after.counts(polarity="favorable", who_was_letting="householder").total
    print(f"after:  relevant {rel2.human_reviewed + rel2.machine_only} | "
          f"favorable {fav2.human_reviewed + fav2.machine_only} | "
          f"favorable+householder {favh2.human_reviewed + favh2.machine_only}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
