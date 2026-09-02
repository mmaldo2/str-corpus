"""One-time backfill: apply the retraction cascade to records the bootstrap
replay left unsupported (bootstrap ran with cascade=False for byte fidelity
with the pre-ledger scripts; see corpus_engine/ledger/bootstrap.py and ADR-0011).

For every in-file record with truthy `relevant`, for each judged field in
("characterization", "polarity", "holding_summary") that is non-null and has
no surviving quote whose `supports` names it, this nulls the field and
routes the record to human review -- the same support rule `drop_quote`
enforces live, applied retroactively for the human-confirmed quote drops
the bootstrap replay carried through without it.

Run once: python tools/apply_retraction_cascade.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.fold import SUPPORTED
from corpus_engine.ledger.types import Basis, Patch

WHY = ("retraction cascade: the quote supporting this field was dropped as a "
       "human-confirmed mismatch at cycle close (bootstrap replayed with the "
       "cascade off); field nulled and routed to human review under the rule "
       "approved 2026-09-01 (ADR-0011)")


def find_unsupported(v) -> list[tuple[int, str]]:
    """[(case_id, field), ...] for every in-file relevant record whose
    history contains a drop_quote (i.e. is even eligible for the bootstrap's
    cascade-off to have left it unsupported) and that now has a non-null
    judged field in SUPPORTED that no surviving quote supports.

    Scoped to drop_quote history, not every relevant record: most records
    were never given a per-field supporting quote in the first place (that
    is a separate, pre-existing data-completeness matter for ~530 records,
    not something the bootstrap's cascade=False choice caused) -- only a
    record that actually had a quote dropped can have been left unsupported
    BY the cascade running off.
    """
    dropped_cids = {p.case_id for p in v.patches if p.op == "drop_quote"}
    out = []
    for cid in v.state.order:
        if not v.state.in_file.get(cid) or cid not in dropped_cids:
            continue
        rec = v.record(cid)
        if not rec.get("relevant"):
            continue
        supported = {q.get("supports") for q in rec.get("quotes", [])}
        for field in SUPPORTED:
            if rec.get(field) is not None and field not in supported:
                out.append((cid, field))
    return out


def main() -> int:
    led = open_ledger()
    v = led.view()
    unsupported = find_unsupported(v)
    # Rule-only basis: a retraction removes a claim, it is not a human
    # judgment of the record, so it carries no reviewer (fold.py permits
    # setting a judged field to None under any basis; see test_ledger_fold.py).
    basis = Basis(rule_id="retraction-cascade-v1")
    patches: list[Patch] = []
    for cid, field in unsupported:
        patches.append(Patch(cid, "set", field, None, WHY, basis))
        patches.append(Patch(cid, "append", "review.flags", f"needs-review:{field}", WHY, basis))
    print(f"{len(unsupported)} unsupported judged field(s) across "
          f"{len({cid for cid, _ in unsupported})} case(s):")
    for cid, field in unsupported:
        print(f"  {cid}: {field}")
    res = led.apply(patches, note="retraction cascade backfill")
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; replay_ok={res.replay_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
