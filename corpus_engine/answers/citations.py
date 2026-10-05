"""Every citation of a decision, preferred citation first (spec 2026-10-04-ledger-answers-
running-log, section 3).

A decision's citations are the kept record's own cite, CAP's `citations` rows for it, and the
cites of every case merged into it as a parallel report (and of the case it was merged into, when
the record is itself a merged copy). CAP's `official` type is not used for order: it marks each
case's own cite in every reporter (spec section 10). Order is the jurisdiction's preference list
from the domain, then everything else alphabetically."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Iterable, Mapping, Sequence
from corpus_engine.ingest.parallel import winner_map

_REPORTER = re.compile(r"^\s*\d+\s+(.+?)\s+\d+\s*$")


def reporter_of(cite: str) -> str:
    m = _REPORTER.match(cite or "")
    return m.group(1).strip() if m else ""


def order_cites(cites: Iterable[str], preference: Sequence[str]) -> list[str]:
    """CAP sometimes stores two cites in one string ("110 App. Div. 218; 48 Misc. Rep. 177"),
    so each string is split on ";" before ordering."""
    rank = {r: i for i, r in enumerate(preference)}
    uniq = list(dict.fromkeys(part.strip() for c in cites if c for part in c.split(";") if part.strip()))
    listed = sorted((c for c in uniq if reporter_of(c) in rank), key=lambda c: (rank[reporter_of(c)], c))
    rest = sorted(c for c in uniq if reporter_of(c) not in rank)
    return listed + rest


def citation_sets(conn, case_ids: Iterable[int], *, jurisdiction_of: Mapping[int, str],
                  preference: Mapping[str, Sequence[str]]) -> dict[int, list[str]]:
    ids = [int(c) for c in case_ids]
    winner_of = winner_map(conn)
    members: dict[int, set[int]] = defaultdict(set)
    for loser, winner in winner_of.items():
        members[winner].add(loser)
    group = {cid: {winner_of.get(cid, cid)} | members.get(winner_of.get(cid, cid), set()) for cid in ids}
    every = sorted(set().union(*group.values())) if group else []
    raw: dict[int, list[str]] = defaultdict(list)
    for i in range(0, len(every), 500):
        chunk = every[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, cite in conn.execute(f"SELECT case_id, cite FROM cases WHERE case_id IN ({ph})", chunk):
            raw[cid].append(cite)
        for cid, cite in conn.execute(f"SELECT case_id, cite FROM citations WHERE case_id IN ({ph})", chunk):
            raw[cid].append(cite)
    return {cid: order_cites([c for m in sorted(group[cid]) for c in raw.get(m, [])],
                             preference.get(jurisdiction_of.get(cid), ()))
            for cid in ids}
