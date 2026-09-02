"""Citation-graph stage (ADR-0005): cites_to + PageRank from CAP volume metadata."""
from __future__ import annotations
import io, json, multiprocessing as mp, sqlite3, time, zipfile
from pathlib import Path
from corpus_engine.ingest.rows import graph_rows


def graph_rows_from_zip(zip_path: Path) -> tuple[list[tuple], list[tuple]]:
    with zipfile.ZipFile(zip_path) as zf:
        meta_name = next((n for n in zf.namelist() if n.endswith("CasesMetadata.json")), None)
        if not meta_name:
            return [], []
        cases_meta = json.load(io.TextIOWrapper(zf.open(meta_name), encoding="utf-8"))
    ct_all, pr_all = [], []
    for cm in cases_meta:
        ct, pr = graph_rows(cm)
        ct_all.extend(ct); pr_all.extend(pr)
    return ct_all, pr_all


def _worker(zip_path: str):
    try:
        return zip_path, graph_rows_from_zip(Path(zip_path))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        return zip_path, (f"{type(e).__name__}: {e}",)


def backfill_graph(conn: sqlite3.Connection, raw_dir: Path, *, workers: int = 6, log=print) -> tuple[int, int]:
    done = {r[0] for r in conn.execute("SELECT zip_key FROM graph_log")}
    keys = [r[0] for r in conn.execute("SELECT zip_key FROM ingest_log") if r[0] not in done]
    paths = [str(raw_dir / f"{k}.zip") for k in keys]
    log(f"{len(keys)} zips to backfill; workers={workers}")
    n_zips = n_rows = 0
    pool = None
    if workers <= 1:
        results = map(_worker, paths)
    else:
        pool = mp.Pool(workers)
        results = pool.imap_unordered(_worker, paths, chunksize=8)
    try:
        for i, (zp, res) in enumerate(results, 1):
            key = f"{Path(zp).parent.name}/{Path(zp).stem}"
            if isinstance(res, tuple) and len(res) == 1:
                log(f"[{i}/{len(keys)}] ERROR {key}: {res[0]}"); continue
            ct, pr = res
            conn.executemany("INSERT OR IGNORE INTO cites_to VALUES (?,?,?,?,?,?,?,?)", ct)
            conn.executemany("UPDATE cases SET pagerank=?, pagerank_pct=? WHERE case_id=?", [(a, b, c) for c, a, b in pr])
            conn.execute("INSERT OR REPLACE INTO graph_log VALUES (?,?)", (key, time.strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
            n_zips += 1; n_rows += len(ct)
            if i % 500 == 0 or i == len(keys):
                log(f"[{i}/{len(keys)}] {n_rows} cites_to rows so far")
    finally:
        if pool is not None:
            pool.close(); pool.join()
    return n_zips, n_rows
