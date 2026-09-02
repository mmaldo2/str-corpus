import sqlite3


def dedupe(conn: sqlite3.Connection) -> int:
    """Cases sharing a normalized citation are one case; official-reporter
    copy wins (the case whose own reporter matches its official cite)."""
    rows = conn.execute(
        """SELECT c1.case_id AS a, c2.case_id AS b
           FROM citations x
           JOIN citations y ON x.cite_norm = y.cite_norm AND x.case_id < y.case_id
           JOIN cases c1 ON c1.case_id = x.case_id
           JOIN cases c2 ON c2.case_id = y.case_id
           GROUP BY a, b"""
    ).fetchall()
    n = 0
    for a, b in rows:
        ca = conn.execute(
            "SELECT case_id, reporter, cite FROM cases WHERE case_id=?", (a,)
        ).fetchone()
        cb = conn.execute(
            "SELECT case_id, reporter, cite FROM cases WHERE case_id=?", (b,)
        ).fetchone()

        def is_official(row) -> bool:
            t = conn.execute(
                "SELECT type FROM citations WHERE case_id=? AND cite=?",
                (row[0], row[2]),
            ).fetchone()
            return bool(t and t[0] == "official")

        winner, loser = (ca, cb) if is_official(ca) or not is_official(cb) else (cb, ca)
        conn.execute(
            "UPDATE cases SET is_duplicate_of=? WHERE case_id=? AND is_duplicate_of IS NULL",
            (winner[0], loser[0]),
        )
        n += 1
    return n
