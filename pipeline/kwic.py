"""Concordance/collocation CLI for the Planner (spec §3).

    python pipeline/kwic.py kwic "taking in lodgers" [--era 1860-1900] [--jur "N.Y."] [--n 25]
    python pipeline/kwic.py colloc "lodger" [--window 5] [--n 30]
    python pipeline/kwic.py freq "lodger" "boarder" "roomer"   # per-era counts
    python pipeline/kwic.py freq "NEAR(transient lodging, 10)" --expr --stem --rate --by jurisdiction
    python pipeline/kwic.py earliest "tourist home" --stem      # the five earliest uses
"""

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import concordance as cc  # noqa: E402

DB = ROOT / "data" / "db" / "corpus.db"

STOPWORDS = set(
    "the of and to in a is that it was for on as be by at or which with from "
    "this his her he she they them their are were an not no so if but had "
    "have has been would will may can such said its any all one upon".split()
)


def cases_matching(conn, term: str, era: str | None, jur: str | None):
    q = """SELECT c.case_id, c.cite, c.decision_year, c.norm_text
           FROM fts_raw JOIN cases c ON c.case_id = fts_raw.rowid
           WHERE fts_raw MATCH ? AND c.is_duplicate_of IS NULL"""
    params: list = [f'"{term}"' if " " in term else term]
    if era:
        q += " AND c.era_partition = ?"
        params.append(era)
    if jur:
        q += " AND c.jurisdiction = ?"
        params.append(jur)
    return conn.execute(q, params)


def cmd_kwic(conn, args):
    term = args.term.lower()
    shown = 0
    for case_id, cite, year, text in cases_matching(conn, term, args.era, args.jur):
        for m in re.finditer(re.escape(term), text):
            left = text[max(0, m.start() - args.width) : m.start()]
            right = text[m.end() : m.end() + args.width]
            print(f"{cite or case_id} ({year}) | ...{left}[{term}]{right}...")
            shown += 1
            if shown >= args.n:
                return
            break  # one hit per case unless we run short


def cmd_colloc(conn, args):
    term = args.term.lower()
    counter: collections.Counter = collections.Counter()
    docs = 0
    for _, _, _, text in cases_matching(conn, term, args.era, args.jur):
        docs += 1
        for m in re.finditer(re.escape(term), text):
            span = text[max(0, m.start() - 80) : m.end() + 80]
            words = re.findall(r"[a-z]+", span)
            counter.update(
                w for w in words if w not in STOPWORDS and w != term and len(w) > 2
            )
        if docs >= 2000:
            break
    for word, n in counter.most_common(args.n):
        print(f"{n:6}  {word}")


def _eras(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT era_partition FROM cases WHERE era_partition IS NOT NULL ORDER BY era_partition")]


def _fmt(n: int, d: int | None, as_rate: bool) -> str:
    if not as_rate:
        return str(n)
    r = cc.rate(n, d or 0)
    return "-" if r is None else f"{r:g}"


def cmd_freq(conn, args):
    dens = cc.denominators(conn) if args.rate else {}
    eras = _eras(conn)
    unit = "per 1,000 opinions" if args.rate else "opinions matching"
    if args.by == "era":
        print(f"({unit})")
        print("term".ljust(28) + "".join(e.rjust(12) for e in eras))
    for term in args.terms:
        cells = cc.cell_counts(conn, term, expr=args.expr, stem=args.stem, jur=args.jur)
        if args.by == "jurisdiction":
            jurs = sorted({j for _, j in cells} | {j for _, j in dens if not args.jur or j == args.jur})
            print(f"{term}  ({unit})")
            print("era".ljust(12) + "".join(str(j).rjust(9) for j in jurs))
            for e in eras:
                print(e.ljust(12) + "".join(
                    _fmt(cells.get((e, j), 0), dens.get((e, j)), args.rate).rjust(9) for j in jurs))
        else:
            table = cc.era_table(cells, dens, jur=args.jur, eras=eras)
            print(term.ljust(28) + "".join(
                _fmt(table[e]["matches"], table[e]["opinions"], args.rate).rjust(12) for e in eras))


def cmd_earliest(conn, args):
    for r in cc.earliest(conn, args.term, expr=args.expr, stem=args.stem, jur=args.jur, n=args.n):
        print(f"{r['year']}  {r['cite']} ({r['jurisdiction']}) {r['name']} | {r['context']}")


def main(argv=None, db=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kwic")
    k.add_argument("term")
    k.add_argument("--era")
    k.add_argument("--jur")
    k.add_argument("--n", type=int, default=25)
    k.add_argument("--width", type=int, default=60)
    c = sub.add_parser("colloc")
    c.add_argument("term")
    c.add_argument("--era")
    c.add_argument("--jur")
    c.add_argument("--n", type=int, default=30)
    c.add_argument("--window", type=int, default=5)
    f = sub.add_parser("freq")
    f.add_argument("terms", nargs="+")
    f.add_argument("--expr", action="store_true", help="pass each term to FTS5 unquoted (NEAR, prefix*, OR)")
    f.add_argument("--stem", action="store_true", help="use the stemmed index (fts_porter)")
    f.add_argument("--jur")
    f.add_argument("--by", choices=("era", "jurisdiction"), default="era")
    f.add_argument("--rate", action="store_true", help="matches per 1,000 canonical opinions")
    e = sub.add_parser("earliest")
    e.add_argument("term")
    e.add_argument("--expr", action="store_true")
    e.add_argument("--stem", action="store_true")
    e.add_argument("--jur")
    e.add_argument("--n", type=int, default=5)
    args = ap.parse_args(argv)
    conn = sqlite3.connect(f"file:{Path(db or DB).as_posix()}?mode=ro", uri=True)
    {"kwic": cmd_kwic, "colloc": cmd_colloc, "freq": cmd_freq, "earliest": cmd_earliest}[args.cmd](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
