"""Parallel ingest: parse zips across processes, write from one process."""
from __future__ import annotations
import multiprocessing as mp
import sqlite3, time, zipfile, json
from dataclasses import dataclass, field
from pathlib import Path
from corpus_engine.domain import Domain, load_domain
from corpus_engine.ingest.rows import CASE_COLUMNS, ZipRows, case_rows_from_zip
from corpus_engine.textnorm_bridge import NORM_VERSION


@dataclass
class IngestReport:
    zips_done: int = 0
    cases_ingested: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _parse(args: tuple[str, str]) -> ZipRows | tuple[str, str]:
    zip_path, domain_name = args
    try:
        return case_rows_from_zip(Path(zip_path), load_domain(domain_name))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        p = Path(zip_path)
        return (f"{p.parent.name}/{p.stem}", f"{type(e).__name__}: {e}")


def write_rows(conn: sqlite3.Connection, rows: ZipRows) -> None:
    conn.executemany(
        f"INSERT OR REPLACE INTO cases ({','.join(CASE_COLUMNS)}) VALUES ({','.join('?' * len(CASE_COLUMNS))})",
        rows.cases)
    conn.executemany("INSERT OR REPLACE INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)", rows.citations)
    conn.executemany("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", rows.cites_to)
    conn.executemany("UPDATE cases SET pagerank=?, pagerank_pct=? WHERE case_id=?",
                     [(raw, pct, cid) for cid, raw, pct in rows.pagerank])


def ingest(conn: sqlite3.Connection, zips: list[Path], domain: Domain, *, workers: int = 6, log=print) -> IngestReport:
    done = {r[0] for r in conn.execute("SELECT zip_key FROM ingest_log WHERE norm_version=?", (NORM_VERSION,))}
    todo = [z for z in zips if f"{z.parent.name}/{z.stem}" not in done]
    log(f"{len(zips)} zips; {len(done)} already ingested; {len(todo)} to do; workers={workers}")
    rep = IngestReport()
    args = [(str(z), domain.name) for z in todo]
    if workers <= 1:
        results = map(_parse, args)
    else:
        pool = mp.Pool(workers)
        results = pool.imap_unordered(_parse, args, chunksize=4)
    try:
        for i, res in enumerate(results, 1):
            if isinstance(res, tuple):
                rep.errors.append(res); log(f"[{i}/{len(todo)}] ERROR {res[0]}: {res[1]}"); continue
            write_rows(conn, res)
            conn.execute("INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?)",
                         (f"{res.slug}/{res.vol}", res.n_total, len(res.cases), NORM_VERSION,
                          time.strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
            rep.zips_done += 1; rep.cases_ingested += len(res.cases)
            if i % 200 == 0 or i == len(todo):
                log(f"[{i}/{len(todo)}] {res.slug}/{res.vol}: {len(res.cases)}/{res.n_total} cases")
    finally:
        if workers > 1:
            pool.close(); pool.join()
    return rep
