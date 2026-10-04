"""Parallel reports: one decision printed in two reporters, kept as two cases because CAP's
metadata for neither copy cites the other (spec 2026-10-04 section 6). Candidates share
jurisdiction, court, decision year and normalized case name across at least two reporters;
opinion-text containment decides. Merges are recorded in `parallel_reports` so `undo` clears
exactly them and never the citation-based marks `dedupe.py` made."""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

MIN_NAME_CHARS = 6        # shorter normalized names ("in re", initials) group unrelated cases
MIN_SHINGLES = 50         # word 5-grams; below this two memorandum decisions match on boilerplate
SIZE_RATIO = (0.5, 2.0)
TABLE = """CREATE TABLE IF NOT EXISTS parallel_reports (
    loser INTEGER PRIMARY KEY REFERENCES cases(case_id),
    winner INTEGER NOT NULL REFERENCES cases(case_id),
    score REAL, method TEXT NOT NULL, run_id TEXT, ts TEXT)"""
_WORD = re.compile(r"[a-z0-9]+")


def normalize_name(name: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split())


def dates_compatible(a: str | None, b: str | None) -> bool:
    """CAP dates come at year, month or day precision ("1908", "1908-04", "1908-04-24"); two
    are compatible when the less precise one is a prefix of the other."""
    a, b = a or "", b or ""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def shingles(text: str | None, n: int) -> frozenset[str]:
    w = _WORD.findall((text or "").lower())
    return frozenset(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))


def containment(a: frozenset, b: frozenset) -> float:
    small = min(len(a), len(b))
    return len(a & b) / small if small else 0.0


def size_ratio_ok(a: frozenset, b: frozenset) -> bool:
    return bool(a and b) and SIZE_RATIO[0] <= len(a) / len(b) <= SIZE_RATIO[1]


@dataclass(frozen=True)
class Member:
    case_id: int
    cite: str
    reporter: str
    decision_date: str
    official: bool


@dataclass(frozen=True)
class Group:
    jurisdiction: str
    court: str
    year: int | None
    name: str
    era: str
    members: tuple[Member, ...]


def candidate_groups(conn) -> list[Group]:
    acc: dict[tuple, list[Member]] = defaultdict(list)
    era: dict[tuple, str] = {}
    for cid, name, cite, court, jur, date, year, ep, reporter, official in conn.execute(
            """SELECT c.case_id, c.name_abbreviation, c.cite, c.court, c.jurisdiction,
                      c.decision_date, c.decision_year, c.era_partition, c.reporter,
                      EXISTS(SELECT 1 FROM citations t WHERE t.case_id = c.case_id
                             AND t.cite = c.cite AND t.type = 'official')
               FROM cases c WHERE c.is_duplicate_of IS NULL"""):
        key = normalize_name(name)
        if len(key) < MIN_NAME_CHARS:
            continue
        k = (jur or "", court or "", year, key)
        acc[k].append(Member(int(cid), cite or "", reporter or "", date or "", bool(official)))
        era[k] = ep or ""
    out = []
    for k in sorted(acc, key=lambda k: (k[0], k[1], k[2] or 0, k[3])):
        ms = acc[k]
        if len({m.reporter for m in ms}) > 1:
            out.append(Group(k[0], k[1], k[2], k[3], era[k],
                             tuple(sorted(ms, key=lambda m: m.case_id))))
    return out


def corpus_precedence(m: Member) -> tuple:
    return (not m.official, m.case_id)


def pick_winner(members: Sequence[Member],
                precedence: Callable[[Member], tuple] = corpus_precedence) -> Member:
    return min(members, key=precedence)


def _texts(conn, ids: Sequence[int]) -> dict[int, str]:
    ph = ",".join("?" * len(ids))
    return {int(c): t or "" for c, t in conn.execute(
        f"SELECT case_id, norm_text FROM cases WHERE case_id IN ({ph})", list(ids))}


def score_group(conn, group: Group, winner: Member) -> list[dict]:
    """Every other member against the winner: word 3- and 5-gram containment and the guards."""
    others = [m for m in group.members if m.case_id != winner.case_id]
    texts = _texts(conn, [winner.case_id] + [m.case_id for m in others])
    w3, w5 = shingles(texts.get(winner.case_id), 3), shingles(texts.get(winner.case_id), 5)
    rows = []
    for m in others:
        o3, o5 = shingles(texts.get(m.case_id), 3), shingles(texts.get(m.case_id), 5)
        rows.append({"winner": winner.case_id, "loser": m.case_id,
                     "winner_cite": winner.cite, "loser_cite": m.cite,
                     "jurisdiction": group.jurisdiction, "court": group.court,
                     "year": group.year, "era": group.era, "name": group.name,
                     "c3": round(containment(w3, o3), 4), "c5": round(containment(w5, o5), 4),
                     "date_ok": dates_compatible(winner.decision_date, m.decision_date),
                     "size_ok": size_ratio_ok(w5, o5),
                     "long_enough": min(len(w5), len(o5)) >= MIN_SHINGLES})
    return rows


def passes_guards(row: Mapping) -> bool:
    return bool(row["date_ok"] and row["size_ok"] and row["long_enough"])


def ensure_table(conn) -> None:
    conn.execute(TABLE)
    conn.commit()


def apply_merges(conn, pairs: Iterable[tuple[int, int, float]], *, method: str, run_id: str,
                 ts: str, log=None) -> dict:
    """Mark each loser `is_duplicate_of` its winner and record the merge. A loser already
    recorded is skipped (a re-run); a pair whose winner or loser is no longer canonical is
    skipped as stale, which also stops a chain inside one run. A loser that other cases already
    point at is skipped as "target" (merging it would chain them through a non-canonical case);
    the target set is read once per run - the column sits behind the opinion text, so a per-pair
    lookup would re-read the table - and kept current as merges land. Calls `log(msg)` (if given)
    at each 5,000-merge commit for progress tracking."""
    ensure_table(conn)
    n = {"applied": 0, "already": 0, "stale": 0, "target": 0}
    targets = {int(r[0]) for r in conn.execute(
        "SELECT DISTINCT is_duplicate_of FROM cases WHERE is_duplicate_of IS NOT NULL")}
    for winner, loser, score in pairs:
        if conn.execute("SELECT 1 FROM parallel_reports WHERE loser=?", (loser,)).fetchone():
            n["already"] += 1
            continue
        marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases WHERE case_id IN (?, ?)",
                                  (winner, loser)))
        if winner not in marks or loser not in marks or marks[winner] is not None \
                or marks[loser] is not None:
            n["stale"] += 1
            continue
        if loser in targets:
            n["target"] += 1
            continue
        conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=? AND is_duplicate_of IS NULL",
                     (winner, loser))
        conn.execute("INSERT INTO parallel_reports (loser, winner, score, method, run_id, ts) "
                     "VALUES (?,?,?,?,?,?)", (loser, winner, score, method, run_id, ts))
        targets.add(winner)
        n["applied"] += 1
        if n["applied"] % 5000 == 0:
            conn.commit()
            if log:
                log(f"{n['applied']} merged so far: {n}")
    conn.commit()
    return n


def undo_merges(conn, method: str) -> int:
    ensure_table(conn)
    rows = conn.execute("SELECT loser, winner FROM parallel_reports WHERE method=?",
                        (method,)).fetchall()
    for loser, winner in rows:
        conn.execute("UPDATE cases SET is_duplicate_of=NULL WHERE case_id=? AND is_duplicate_of=?",
                     (loser, winner))
    conn.execute("DELETE FROM parallel_reports WHERE method=?", (method,))
    conn.commit()
    return len(rows)


def winner_map(conn) -> dict[int, int]:
    """loser -> winner for every recorded merge; empty before any merge (no table yet)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='parallel_reports'").fetchone():
        return {}
    return {int(l): int(w) for l, w in conn.execute("SELECT loser, winner FROM parallel_reports")}


def losers_among(conn, case_ids: Iterable[int]) -> set[int]:
    """The ids among `case_ids` marked a duplicate of another case, by any rule."""
    ids = sorted({int(c) for c in case_ids})
    out: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        out |= {int(r[0]) for r in conn.execute(
            f"SELECT case_id FROM cases WHERE case_id IN ({ph}) AND is_duplicate_of IS NOT NULL",
            chunk)}
    return out
