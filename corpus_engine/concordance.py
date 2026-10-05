"""Concordance over the corpus full-text index (spec 2026-10-04-ledger-answers-running-log,
section 5).

Counts are of canonical opinions (`is_duplicate_of IS NULL`) that match, per era partition and
jurisdiction. `fts_raw` matches exact words ("lodger" and "lodgers" differ); `fts_porter`
(`stem=True`) matches stems. An expression (`expr=True`) is FTS5 syntax passed through unquoted
- `NEAR(a b, 10)`, a prefix `lodg*`, `OR`; a plain term is matched as words (`fts_string`)."""
from __future__ import annotations
from collections import defaultdict
from typing import Mapping, Sequence


def fts_string(term: str) -> str:
    """A plain term as one FTS5 string, so punctuation ("short-term", "owner's") and operator
    words (NOT, AND) are matched as words; an embedded double quote is escaped and a trailing *
    stays a prefix."""
    t = term.strip()
    star = t.endswith("*")
    core = t[:-1].rstrip() if star else t
    return '"' + core.replace('"', '""') + '"' + ("*" if star else "")


def fts_query(term: str, *, expr: bool = False) -> str:
    t = term.strip()
    return t if expr else fts_string(t)


def _table(stem: bool) -> str:
    return "fts_porter" if stem else "fts_raw"


def cell_counts(conn, term: str, *, expr: bool = False, stem: bool = False,
                jur: str | None = None) -> dict[tuple[str, str], int]:
    """{(era, jurisdiction): canonical opinions matching}."""
    t = _table(stem)
    q = (f"SELECT c.era_partition, c.jurisdiction, count(*) FROM {t} "
         f"JOIN cases c ON c.case_id = {t}.rowid "
         f"WHERE {t} MATCH ? AND c.is_duplicate_of IS NULL")
    params: list = [fts_query(term, expr=expr)]
    if jur:
        q += " AND c.jurisdiction = ?"
        params.append(jur)
    q += " GROUP BY 1, 2"
    return {(e, j): n for e, j, n in conn.execute(q, params)}


def denominators(conn) -> dict[tuple[str, str], int]:
    """Canonical opinions per (era, jurisdiction): the denominators of every rate (one scan)."""
    return {(e, j): n for e, j, n in conn.execute(
        "SELECT era_partition, jurisdiction, count(*) FROM cases "
        "WHERE is_duplicate_of IS NULL GROUP BY 1, 2")}


def rate(matches: int, opinions: int) -> float | None:
    """Matches per 1,000 opinions; None when the cell holds no opinions."""
    return round(1000 * matches / opinions, 3) if opinions else None


def by_era(cells: Mapping[tuple[str, str], int]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for (era, _), n in cells.items():
        out[era] += n
    return dict(out)


def _era_order(eras) -> list[str]:
    return sorted(eras, key=lambda e: (not str(e).startswith("pre"), str(e)))


def era_table(cells: Mapping[tuple[str, str], int], dens: Mapping[tuple[str, str], int], *,
              jur: str | None = None, eras: Sequence[str] | None = None) -> dict[str, dict]:
    """era -> {"matches", "opinions", "rate"}; with `jur`, the denominators are that jurisdiction's."""
    order = list(eras) if eras is not None else _era_order({e for e, _ in dens})
    out = {}
    for e in order:
        m = sum(n for (ce, _), n in cells.items() if ce == e)
        d = sum(n for (de, j), n in dens.items() if de == e and (jur is None or j == jur))
        out[e] = {"matches": m, "opinions": d, "rate": rate(m, d)}
    return out


def earliest(conn, term: str, *, expr: bool = False, stem: bool = False, jur: str | None = None,
             n: int = 5, tokens: int = 16) -> list[dict]:
    """The `n` earliest canonical opinions matching, with a highlighted context line."""
    t = _table(stem)
    q = (f"SELECT c.case_id, c.cite, c.name_abbreviation, c.decision_year, c.jurisdiction, "
         f"snippet({t}, 0, '[', ']', '...', {int(tokens)}) FROM {t} "
         f"JOIN cases c ON c.case_id = {t}.rowid "
         f"WHERE {t} MATCH ? AND c.is_duplicate_of IS NULL AND c.decision_year IS NOT NULL")
    params: list = [fts_query(term, expr=expr)]
    if jur:
        q += " AND c.jurisdiction = ?"
        params.append(jur)
    q += " ORDER BY c.decision_year, c.case_id LIMIT ?"
    params.append(int(n))
    return [{"case_id": cid, "cite": cite, "name": name, "year": year, "jurisdiction": j,
             "context": snip}
            for cid, cite, name, year, j, snip in conn.execute(q, params)]
