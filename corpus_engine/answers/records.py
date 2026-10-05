"""Ledger answers: select counted records, build case rows, and summarise them in two tiers
(spec 2026-10-04-ledger-answers-running-log, sections 3-4). Read-only on the ledger and corpus."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Iterable, Mapping, Sequence
from corpus_engine.ledger.tally import counted_records
from corpus_engine.store import era_partition

FIELDS = ("who_was_letting", "polarity", "characterization", "owner_freedom_characterization",
          "duration_of_occupancy", "under_thirty_days", "restriction_nature", "holding_summary")
REVIEWER_COLUMNS = ("reviewer_verdict", "reviewer_field", "reviewer_value", "reviewer_note")
COLUMNS = (("case_name", "citations", "year", "era", "jurisdiction", "court") + FIELDS
           + ("quote", "quote_page", "review_tier", "case_id") + REVIEWER_COLUMNS)


def era_of(rec: Mapping, domain) -> str:
    return era_partition(rec.get("year"), domain.era_bounds)


def matches(rec: Mapping, era: str, mapping: Mapping[str, Sequence]) -> bool:
    return all((era if f == "era" else rec.get(f)) in vals for f, vals in mapping.items())


def _pattern(term: str) -> re.Pattern:
    t = term.strip()
    if t.endswith("*"):
        return re.compile(r"\b" + re.escape(t[:-1]), re.I)
    return re.compile(r"\b" + re.escape(t) + r"\b", re.I)


def record_text_hits(records: Iterable[Mapping], terms: Sequence[str], where: Sequence[str]) -> set[int]:
    pats = [_pattern(t) for t in terms]
    hits = set()
    for r in records:
        texts = []
        if "quotes" in where:
            texts += [q.get("text") or "" for q in r.get("quotes") or ()]
        if "holding_summary" in where:
            texts.append(r.get("holding_summary") or "")
        if any(p.search(t) for p in pats for t in texts):
            hits.add(int(r["case_id"]))
    return hits


def _fts_term(term: str) -> str:
    t = term.strip()
    star = t.endswith("*")
    core = t[:-1] if star else t
    return (f'"{core}"' + ("*" if star else "")) if " " in core else t


def opinion_text_hits(conn, case_ids: Iterable[int], terms: Sequence[str]) -> set[int]:
    """Opinion-text matches through `fts_raw`, restricted to `case_ids`."""
    expr = " OR ".join(_fts_term(t) for t in terms)
    ids = sorted({int(c) for c in case_ids})
    hits: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        hits |= {int(r[0]) for r in conn.execute(
            f"SELECT rowid FROM fts_raw WHERE fts_raw MATCH ? AND rowid IN ({ph})", [expr, *chunk])}
    return hits


def select(view, domain, question, *, conn=None) -> list[dict]:
    recs = []
    for r in counted_records(view):
        era = era_of(r, domain)
        if not matches(r, era, question.population):
            continue
        if question.any_of and not any(matches(r, era, m) for m in question.any_of):
            continue
        recs.append(r)
    if question.text_match:
        terms, where = question.text_match["terms"], question.text_match["in"]
        hits = record_text_hits(recs, terms, where)
        if "opinion" in where:
            if conn is None:
                raise ValueError(f"{question.id}: text_match in opinion needs a corpus connection")
            hits |= opinion_text_hits(conn, [r["case_id"] for r in recs], terms)
        recs = [r for r in recs if int(r["case_id"]) in hits]
    return sorted(recs, key=lambda r: (r.get("year") or 0, r["case_id"]))


def names_and_courts(conn, case_ids: Iterable[int]) -> dict[int, tuple[str, str]]:
    ids = sorted({int(c) for c in case_ids})
    out = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, name, court in conn.execute(
                f"SELECT case_id, name_abbreviation, court FROM cases WHERE case_id IN ({ph})", chunk):
            out[int(cid)] = (name or "", court or "")
    return out


def _first_verified_quote(rec: Mapping) -> Mapping:
    return next((q for q in rec.get("quotes") or () if q.get("status") == "verified"), {})


def case_rows(records: Iterable[Mapping], *, domain, reviewed: set[int],
              names: Mapping[int, tuple[str, str]], citations: Mapping[int, Sequence[str]]) -> list[dict]:
    rows = []
    for r in records:
        cid = int(r["case_id"])
        name, court = names.get(cid, ("", ""))
        q = _first_verified_quote(r)
        row = {"case_name": name, "citations": "; ".join(citations.get(cid) or [r.get("cite") or ""]),
               "year": r.get("year"), "era": era_of(r, domain), "jurisdiction": r.get("jurisdiction"),
               "court": court}
        row.update({f: r.get(f) for f in FIELDS})
        row.update({"quote": q.get("text", ""), "quote_page": q.get("reporter_page", ""),
                    "review_tier": "human-reviewed" if cid in reviewed else "machine-only",
                    "case_id": cid})
        row.update({c: "" for c in REVIEWER_COLUMNS})
        rows.append(row)
    return rows


def summary(records: Iterable[Mapping], *, domain, reviewed: set[int],
            group_by: Sequence[str]) -> dict:
    """Two-tier counts: total, by jurisdiction x era, and by the question's grouping. Never a
    blended total (ADR-0002)."""
    total = [0, 0]
    cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    groups: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in records:
        tier = 0 if int(r["case_id"]) in reviewed else 1
        era = era_of(r, domain)
        total[tier] += 1
        cells[(r.get("jurisdiction"), era)][tier] += 1
        groups[tuple(era if f == "era" else r.get(f) for f in group_by)][tier] += 1
    order = {e: i for i, e in enumerate(domain.eras)}
    return {
        "total": {"human_reviewed": total[0], "machine_only": total[1]},
        "by_jurisdiction_era": [
            {"jurisdiction": j, "era": e, "human_reviewed": h, "machine_only": m}
            for (j, e), (h, m) in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), order.get(kv[0][1], 99)))],
        "by_group": [
            {"key": dict(zip(group_by, k)), "human_reviewed": h, "machine_only": m}
            for k, (h, m) in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0]))],
    }


def earliest_per_jurisdiction(records: Iterable[Mapping], mapping: Mapping[str, Sequence], *,
                              domain, reviewed: set[int] = frozenset()) -> list[dict]:
    best: dict[str, Mapping] = {}
    for r in records:
        if not matches(r, era_of(r, domain), mapping):
            continue
        j = r.get("jurisdiction")
        key = (r.get("year") or 9999, r["case_id"])
        if j not in best or key < (best[j].get("year") or 9999, best[j]["case_id"]):
            best[j] = r
    return [{"jurisdiction": j, "case_id": int(r["case_id"]), "year": r.get("year"), "cite": r.get("cite"),
             "review_tier": "human-reviewed" if int(r["case_id"]) in reviewed else "machine-only"}
            for j, r in sorted(best.items(), key=lambda kv: str(kv[0]))]
