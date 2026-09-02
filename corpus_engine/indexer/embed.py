"""Embedding writer: chunk each case, embed through an Embedder, store int8 vectors tagged
with the run that produced them. A case belongs to exactly one run at a time."""
from __future__ import annotations
import queue, sqlite3, threading, time
from dataclasses import dataclass
import numpy as np
from corpus_engine.domain import EmbeddingSpec
from corpus_engine.indexer.chunking import chunk_offsets, embedding_input
from corpus_engine.indexer.embedders import Embedder


@dataclass(frozen=True)
class EmbedRun:
    run_key: str; model: str; revision: str; dim: int; quant: str
    chunk_tokens: int; chunk_overlap: int; prefix_template: str; provider: str

    @staticmethod
    def from_spec(spec: EmbeddingSpec, provider: str) -> "EmbedRun":
        return EmbedRun(spec.run_key, spec.model, spec.revision, spec.dim, spec.quant, spec.chunk_tokens,
                        spec.chunk_overlap, spec.prefix_template, provider)


def quantize(vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
    scales = np.abs(vecs).max(axis=1) / 127.0
    return np.round(vecs / scales[:, None]).astype(np.int8), scales.astype(np.float32)


def register_run(conn: sqlite3.Connection, run: EmbedRun) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO embed_runs
           (run_key, model, revision, dim, quant, chunk_tokens, chunk_overlap, prefix_template, provider, created)
           VALUES (:run_key, :model, :revision, :dim, :quant, :chunk_tokens, :chunk_overlap, :prefix_template, :provider, :created)""",
        {"run_key": run.run_key, "model": run.model, "revision": run.revision, "dim": run.dim, "quant": run.quant,
         "chunk_tokens": run.chunk_tokens, "chunk_overlap": run.chunk_overlap, "prefix_template": run.prefix_template,
         "provider": run.provider, "created": time.strftime("%Y-%m-%dT%H:%M:%S")},
    )
    for k, v in {"model": run.model, "revision": run.revision, "dim": str(run.dim), "chunk_tokens": str(run.chunk_tokens),
                 "chunk_overlap": str(run.chunk_overlap), "quant": run.quant, "run_key": run.run_key}.items():
        conn.execute("INSERT OR REPLACE INTO embed_meta VALUES (?,?)", (k, v))
    conn.commit()


def partition_runs(conn: sqlite3.Connection) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for era, jur in conn.execute("SELECT DISTINCT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL"):
        out[(era, jur)] = set()
    for era, jur, run in conn.execute("""SELECT DISTINCT c.era_partition, c.jurisdiction, ch.embed_run
                                          FROM chunks ch JOIN cases c ON c.case_id = ch.case_id WHERE c.is_duplicate_of IS NULL"""):
        out.setdefault((era, jur), set()).add(run)
    return out


def build_embeddings(conn: sqlite3.Connection, embedder: Embedder, tokenizer, run: EmbedRun, *, batch_size: int = 64,
                     limit: int = 0, partitions=None, log=print) -> int:
    register_run(conn, run)
    where = ["c.is_duplicate_of IS NULL", "c.norm_text != ''",
             "c.case_id NOT IN (SELECT case_id FROM chunks WHERE embed_run = ?)"]
    params: list = [run.run_key]
    if partitions:
        where.append("(" + " OR ".join("(c.era_partition=? AND c.jurisdiction=?)" for _ in partitions) + ")")
        for e, j in partitions:
            params += [e, j]
    q = f"SELECT c.case_id FROM cases c WHERE {' AND '.join(where)} ORDER BY c.case_id"
    if limit:
        q += f" LIMIT {int(limit)}"
    todo = [r[0] for r in conn.execute(q, params)]
    log(f"{len(todo)} cases to chunk+embed under {run.run_key} via {embedder.name}")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    qu: queue.Queue = queue.Queue(maxsize=4000)

    def producer():
        rc = sqlite3.connect(db_path); rc.execute("PRAGMA busy_timeout=120000")
        for cid in todo:
            row = rc.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
            if not row or not row[0]:
                qu.put(("CASE_DONE", cid)); continue
            meta = {"name": row[1], "court": row[2], "year": row[3]}
            for seq, (s, e) in enumerate(chunk_offsets(tokenizer, row[0], run.chunk_tokens, run.chunk_overlap)):
                qu.put((cid, seq, s, e, embedding_input(run.prefix_template, meta, row[0][s:e])))
            qu.put(("CASE_DONE", cid))
        qu.put(None)

    threading.Thread(target=producer, daemon=True).start()
    texts, rows, written = [], [], 0

    def flush():
        nonlocal written
        if not texts:
            return
        q8, scales = quantize(embedder.encode(texts, batch_size=batch_size))
        case_ids = sorted({r[0] for r in rows})
        conn.executemany("DELETE FROM chunks WHERE case_id=?", [(c,) for c in case_ids])
        conn.executemany("INSERT INTO chunks (case_id, seq, char_start, char_end, embedding, embed_scale, embed_run) VALUES (?,?,?,?,?,?,?)",
                         [(cid, seq, s, e, q8[i].tobytes(), float(scales[i]), run.run_key) for i, (cid, seq, s, e) in enumerate(rows)])
        conn.commit()
        written += len(rows); texts.clear(); rows.clear()

    n_done = 0
    while True:
        item = qu.get()
        if item is None:
            break
        if item[0] == "CASE_DONE":
            n_done += 1
            if len(texts) >= batch_size * 8:
                flush()
            if n_done % 1000 == 0:
                flush(); log(f"{n_done}/{len(todo)} cases, {written} chunks written")
            continue
        cid, seq, s, e, text = item
        texts.append(text); rows.append((cid, seq, s, e))
    flush()
    log(f"done: {written} chunks under {run.run_key}")
    return written
