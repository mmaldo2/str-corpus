"""Ledger side of the parallel-report merge (spec 2026-10-04 section 6.6): which copy of a
decision the ledger keeps, and the `duplicate_of` patches that take the other copies out of
every count. A copy's record stays in its cycle file with its fields as they were."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence
from corpus_engine.ledger.types import Basis, Patch

DUPLICATE_FIELD = "duplicate_of"
RULE_ID = "parallel-report-merge-v1"


def precedence(view, reviewed: set[int]) -> Callable:
    """Sort key for the members of a parallel-report group, best first: a relevant ledger
    record, then any ledger record, then none; within that, human-reviewed, then more
    verified quotes, then the official reporter, then the lowest case id. `reviewed` is
    `view.reviewed_ids()`, computed once by the caller."""
    def key(m) -> tuple:
        rec = view.state.records.get(m.case_id)
        tier = 2 if rec is None else (0 if rec.get("relevant") is True else 1)
        verified = sum(1 for q in (rec or {}).get("quotes") or () if q.get("status") == "verified")
        return (tier, m.case_id not in reviewed, -verified, not m.official, m.case_id)
    return key


@dataclass
class Reconciled:
    patches: list[Patch] = field(default_factory=list)
    for_user: list[dict] = field(default_factory=list)


def reconcile(view, merges: Mapping[int, int], *, run_id: str,
              judged: Sequence[str]) -> Reconciled:
    """`merges` is loser -> winner from the corpus. For each group with two or more ledger
    records: a human-set judged value on another relevant copy that differs from the winner's
    puts the group on the user's list and patches nothing (that copy stays counted until
    decided). A `relevant` disagreement also goes on the user's list (reason "relevant"), but
    still takes every OTHER relevant copy out of the count with `duplicate_of = winner`,
    provided the winner is itself relevant and the copy holds no differing human value.
    Otherwise every other relevant copy gets `duplicate_of = winner`. Idempotent."""
    groups: dict[int, list[int]] = defaultdict(list)
    for loser, winner in merges.items():
        groups[int(winner)].append(int(loser))
    out = Reconciled()
    recs = view.state.records
    for winner in sorted(groups):
        in_ledger = [c for c in [winner] + sorted(groups[winner]) if c in recs]
        if len(in_ledger) < 2:
            continue
        readings = {c: recs[c].get("relevant") for c in in_ledger
                    if recs[c].get("relevant") is not None}
        disagree = True in readings.values() and False in readings.values()
        if disagree:
            out.for_user.append({"winner": winner, "members": in_ledger, "reason": "relevant",
                                 "detail": {str(c): v for c, v in readings.items()}})
            if readings.get(winner) is not True:
                continue
        counted = [c for c in in_ledger if readings.get(c) is True]
        if len(counted) < 2:
            continue
        if winner not in counted:
            out.for_user.append({"winner": winner, "members": in_ledger,
                                 "reason": "winner-not-counted", "detail": {}})
            continue
        others = [c for c in counted if c != winner]
        diffs = {}
        for c in others:
            prov = view.provenance(c)
            fields = [f for f in judged
                      if prov.get(f) == "human" and recs[c].get(f) != recs[winner].get(f)]
            if fields:
                diffs[str(c)] = {f: [recs[c].get(f), recs[winner].get(f)] for f in fields}
        if diffs and not disagree:
            out.for_user.append({"winner": winner, "members": in_ledger,
                                 "reason": "human-value", "detail": diffs})
            continue
        for c in others:
            if str(c) in diffs or recs[c].get(DUPLICATE_FIELD) == winner:
                continue
            out.patches.append(Patch(c, "set", DUPLICATE_FIELD, winner,
                                     f"parallel report of {winner}: one decision, counted once",
                                     Basis(rule_id=RULE_ID, run_id=run_id),
                                     cycle=view.state.cycles.get(c)))
    return out
