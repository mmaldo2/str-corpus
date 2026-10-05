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


def _norm(reporter: str) -> str:
    return re.sub(r"\s+", "", reporter).casefold()


def _tiers(preference) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A jurisdiction's preference is {"official": [...], "reprint": [...]}; a plain list is all
    official."""
    if isinstance(preference, Mapping):
        return tuple(preference.get("official", ())), tuple(preference.get("reprint", ()))
    return tuple(preference), ()


def reporter_tier(cite: str, preference) -> str:
    """"official", "reprint" or "unknown" for this cite under the jurisdiction's preference."""
    official, reprint = _tiers(preference)
    r = _norm(reporter_of(cite))
    if r and r in {_norm(x) for x in official}:
        return "official"
    if r and r in {_norm(x) for x in reprint}:
        return "reprint"
    return "unknown"


def order_cites(cites: Iterable[str], preference) -> list[str]:
    """Official reports first (in list order), then reporters on neither list (alphabetically), then
    regional and unofficial reprints (in list order), so a reporter missing from the lists can never
    put a reprint ahead of an official report. Reporters match ignoring spaces and case. CAP sometimes
    stores two cites in one string ("110 App. Div. 218; 48 Misc. Rep. 177"), so each string is split
    on ";", and a part with no number in it ("Judgment accordingly.") is not a cite and is dropped."""
    official, reprint = _tiers(preference)
    rank_official = {_norm(r): i for i, r in enumerate(official)}
    rank_reprint = {_norm(r): i for i, r in enumerate(reprint)}
    uniq = list(dict.fromkeys(part.strip() for c in cites if c for part in c.split(";")
                              if part.strip() and any(ch.isdigit() for ch in part)))

    def key(cite: str) -> tuple:
        r = _norm(reporter_of(cite))
        if r in rank_official:
            return (0, rank_official[r], cite)
        if r in rank_reprint:
            return (2, rank_reprint[r], cite)
        return (1, 0, cite)
    return sorted(uniq, key=key)


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
