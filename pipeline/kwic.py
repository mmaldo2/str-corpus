"""Concordance/collocation CLI for the Planner (spec §3).

    python pipeline/kwic.py kwic "taking in lodgers" [--era 1860-1900] [--jur "N.Y."] [--n 25]
    python pipeline/kwic.py colloc "lodger" [--window 5] [--n 30]
    python pipeline/kwic.py freq "lodger" "boarder" "roomer"   # per-era counts
"""

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


def cmd_freq(conn, args):
    eras = [r[0] for r in conn.execute(
        "SELECT DISTINCT era_partition FROM cases WHERE era_partition IS NOT NULL ORDER BY era_partition"
    )]
    print("term".ljust(28) + "".join(e.rjust(12) for e in eras))
    for term in args.terms:
        counts = []
        for era in eras:
            n = conn.execute(
                """SELECT count(*) FROM fts_raw JOIN cases c ON c.case_id = fts_raw.rowid
                   WHERE fts_raw MATCH ? AND c.era_partition = ? AND c.is_duplicate_of IS NULL""",
                (f'"{term}"' if " " in term else term, era),
            ).fetchone()[0]
            counts.append(n)
        print(term.ljust(28) + "".join(str(n).rjust(12) for n in counts))


def main() -> int:
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
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    {"kwic": cmd_kwic, "colloc": cmd_colloc, "freq": cmd_freq}[args.cmd](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
