r"""One-off: clear the `needs-review:<field>` flags a reviewer decision has already superseded.

`tools/apply_reference_review.py` now clears the flag in the same patch set as the decision
that supersedes it, but three kit cases (1932707, 4268287, 2186819) were adjudicated on
reference page 1 BEFORE that rule existed, so they still carry the `needs-review:polarity`
flag the retraction cascade wrote when their supporting quote was dropped - and the reader
kit's D6 exclusions, read off those flags, would drop polarity from agreement for three cases
whose polarity the user has in fact decided.

Re-running the page itself is not the way to fix that: the tool writes each note with the
field's CURRENT value in it, so a second run over an already-applied page produces 77 fresh
note patches saying `'adverse' -> 'adverse'`. This tool does only the clearing, and takes its
authority from the same saved page: a flag is cleared only where that page carries an `adopt`
or `set` on that exact field for that exact case. It clears nothing on its own say-so.

Usage:
  .venv\Scripts\python tools\clear_superseded_flags.py --saved <page> --field polarity --dry-run
  .venv\Scripts\python tools\clear_superseded_flags.py --saved <page> --field polarity --cases 1,2,3
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                        # noqa: E402
from corpus_engine.ledger import open_ledger                        # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                 # noqa: E402

_spec = importlib.util.spec_from_file_location("apply_reference_review",
                                               ROOT / "tools" / "apply_reference_review.py")
arr = importlib.util.module_from_spec(_spec)                        # the clearing rule lives in
_spec.loader.exec_module(arr)                                       # one place, not two

RUN_ID = "reference-v2-flagclear"


def superseded(decisions: Sequence[dict], records: Mapping[int, dict], field: str) -> list[int]:
    """The cases whose `needs-review:<field>` flag this page's decisions supersede: the page
    decided a value for that field, and the flag is still standing. Ascending id order."""
    flag = f"{arr.FLAG_PREFIX}{field}"
    decided = {int(d["case_id"]) for d in decisions
               if d["field"] == field and d["decision"] in ("adopt", "set")}
    return sorted(cid for cid in decided if flag in arr._live_flags(records, cid))


def patches_for(cases: Sequence[int], records: Mapping[int, dict], field: str, reviewer: str,
                page: str, *, run_id: str = RUN_ID) -> list[Patch]:
    basis = Basis(reviewer=reviewer, run_id=run_id)
    tag = arr._label(run_id)
    why = f"{tag}: {field} was decided on {page}; the flag it supersedes is cleared"
    live: dict[int, list] = {}
    out: list[Patch] = []
    for cid in cases:
        out += arr._clear_flag(live, records, int(cid), field, why, basis, tag)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--saved", required=True, help="the saved page whose decisions are the authority")
    ap.add_argument("--field", required=True, help="the field whose flag is superseded")
    ap.add_argument("--cases", default=None,
                    help="comma-separated case ids the caller expects; refuses on any mismatch")
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    dom = load_domain()
    led = open_ledger(domain=dom)
    records = led.view().state.records
    # the whole page is validated, not just the decisions on --field: a page this tool
    # cannot fully read is a page whose authority it cannot vouch for.
    decisions = arr.read_state(Path(a.saved).read_text(encoding="utf-8"))
    cases = superseded(decisions, records, a.field)
    if a.cases is not None:
        want = sorted(int(c) for c in a.cases.split(",") if c.strip())
        if want != cases:
            raise SystemExit(f"expected {want}, the page supersedes {cases}; nothing written")
    page = Path(a.saved).name
    patches = patches_for(cases, records, a.field, dom.reviewer_default, page, run_id=a.run_id)
    print(f"{Path(a.saved).name}: {len(cases)} case(s) whose {a.field} flag is superseded "
          f"-> {len(patches)} patches", flush=True)
    for cid in cases:
        print(f"  {cid}: {arr._live_flags(records, cid)} -> "
              f"{[f for f in arr._live_flags(records, cid) if f != arr.FLAG_PREFIX + a.field]}"
              f"   ({a.field} = {(records.get(cid) or {}).get(a.field)!r})", flush=True)
    print(f"before: {arr._summary(led.view())}", flush=True)
    res = led.apply(patches, note=f"clear superseded {a.field} flags", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    if not a.dry_run:
        print(f"after:  {arr._summary(led.view())}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
