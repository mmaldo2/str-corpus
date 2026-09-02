from corpus_engine import store
def build_fts(conn, log=print) -> None:
    store.ensure_fts(conn)
    for table in ("fts_porter", "fts_raw"):
        conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')"); conn.commit()
        n = conn.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH 'the'").fetchone()[0]
        log(f"{table}: rebuilt ({n} docs match 'the')")
