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


_RUN_FIELDS = ("model", "revision", "dim", "quant", "chunk_tokens", "chunk_overlap", "prefix_template", "provider")


def register_run(conn: sqlite3.Connection, run: EmbedRun) -> None:
    """Register `run` under its run_key. A fresh key is inserted. An existing key is a
    no-op only if every stored field matches `run` exactly; a mismatch on any field
    raises, because a stale row would otherwise launder a changed model/chunking/prefix
    past the coverage fingerprint that depends on this table (see final-review I2)."""
    existing = conn.execute(f"SELECT {', '.join(_RUN_FIELDS)} FROM embed_runs WHERE run_key = ?",
                            (run.run_key,)).fetchone()
    if existing is not None:
        incoming = tuple(getattr(run, f) for f in _RUN_FIELDS)
        mismatches = [f"{field}: {stored!r} != {new!r}"
                     for field, stored, new in zip(_RUN_FIELDS, existing, incoming) if stored != new]
        if mismatches:
            raise ValueError(f"embed_run {run.run_key} already registered with different parameters: "
                             + ", ".join(mismatches))
        return
    conn.execute(
        """INSERT INTO embed_runs
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


def estimate_tokens(conn, tokenizer, run: EmbedRun, *, sample: int = 500, partitions=None) -> tuple[int, int]:
    import random
    where = ["is_duplicate_of IS NULL", "norm_text != ''", "case_id NOT IN (SELECT case_id FROM chunks WHERE embed_run = ?)"]
    params: list = [run.run_key]
    if partitions:
        where.append("(" + " OR ".join("(era_partition=? AND jurisdiction=?)" for _ in partitions) + ")")
        for e, j in partitions:
            params += [e, j]
    ids = [r[0] for r in conn.execute(f"SELECT case_id FROM cases WHERE {' AND '.join(where)}", params)]
    if not ids:
        return 0, 0
    pick = random.Random(0).sample(ids, min(sample, len(ids)))
    total = 0
    for cid in pick:
        text, name, court, year = conn.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
        for s, e in chunk_offsets(tokenizer, text, run.chunk_tokens, run.chunk_overlap):
            total += len(tokenizer(embedding_input(run.prefix_template, {"name": name, "court": court, "year": year}, text[s:e]),
                                   add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"])
    return len(ids), int(total * len(ids) / len(pick))


class BudgetExceeded(RuntimeError):
    """Raised by build_embeddings after a flush has already committed, when accumulated
    spend for this run_key (persisted in embed_runs.tokens_used, which accumulates
    across resumed processes) exceeds --max-usd. The triggering flush's chunks and
    token count are safely on disk before this is raised; build_embeddings otherwise
    keeps its plain `-> int` contract on normal completion."""


def usd_for_tokens(tokens: int | None, usd_per_m_tokens: float | None) -> float | None:
    if tokens is None or usd_per_m_tokens is None:
        return None
    return tokens / 1e6 * usd_per_m_tokens


def build_embeddings(conn: sqlite3.Connection, embedder: Embedder, tokenizer, run: EmbedRun, *, batch_size: int = 64,
                     limit: int = 0, partitions=None, flush_batches: int = 8,
                     usd_per_m_tokens: float | None = None, max_usd: float | None = None, log=print) -> int:
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
        rc = None
        try:
            rc = sqlite3.connect(db_path); rc.execute("PRAGMA busy_timeout=120000")
            for cid in todo:
                row = rc.execute("SELECT norm_text, name_abbreviation, court, decision_year FROM cases WHERE case_id=?", (cid,)).fetchone()
                if not row or not row[0]:
                    qu.put(("CASE_DONE", cid)); continue
                meta = {"name": row[1], "court": row[2], "year": row[3]}
                for seq, (s, e) in enumerate(chunk_offsets(tokenizer, row[0], run.chunk_tokens, run.chunk_overlap)):
                    qu.put((cid, seq, s, e, embedding_input(run.prefix_template, meta, row[0][s:e])))
                qu.put(("CASE_DONE", cid))
        except BaseException as exc:  # noqa: BLE001 -- any producer-thread failure must reach the consumer, not hang it
            qu.put(("PRODUCER_FAILED", exc))
        finally:
            qu.put(None)
            if rc is not None:
                rc.close()

    threading.Thread(target=producer, daemon=True).start()
    texts, rows, written, last_tokens = [], [], 0, 0

    def progress_suffix(tokens_now: int | None) -> str:
        suffix = f", tokens={tokens_now or 0}"
        usd = usd_for_tokens(tokens_now, usd_per_m_tokens)
        if usd is not None:
            suffix += f", usd={usd:.2f}"
        return suffix

    def flush():
        nonlocal written, last_tokens
        if not texts:
            return
        q8, scales = quantize(embedder.encode(texts, batch_size=batch_size))
        case_ids = sorted({r[0] for r in rows})
        conn.executemany("DELETE FROM chunks WHERE case_id=?", [(c,) for c in case_ids])
        conn.executemany("INSERT INTO chunks (case_id, seq, char_start, char_end, embedding, embed_scale, embed_run) VALUES (?,?,?,?,?,?,?)",
                         [(cid, seq, s, e, q8[i].tobytes(), float(scales[i]), run.run_key) for i, (cid, seq, s, e) in enumerate(rows)])
        tokens_now = getattr(embedder, "tokens_used", None)
        if tokens_now is not None:
            delta = tokens_now - last_tokens
            last_tokens = tokens_now
            if delta:
                # Accumulate rather than overwrite: a resumed process starts its own
                # embedder's tokens_used at 0, so only the per-flush delta is added to
                # the total this run_key has spent across every process that has run it.
                conn.execute("UPDATE embed_runs SET tokens_used = COALESCE(tokens_used, 0) + ? WHERE run_key = ?",
                             (delta, run.run_key))
        conn.commit()
        written += len(rows); texts.clear(); rows.clear()

    def check_budget():
        if max_usd is None:
            return
        row = conn.execute("SELECT tokens_used FROM embed_runs WHERE run_key = ?", (run.run_key,)).fetchone()
        total_tokens = (row[0] if row else None) or 0
        usd = usd_for_tokens(total_tokens, usd_per_m_tokens)
        if usd is not None and usd > max_usd:
            log(f"stopping: spend {usd:.2f} exceeds --max-usd {max_usd:.2f}")
            raise BudgetExceeded(f"spend {usd:.2f} exceeds --max-usd {max_usd:.2f}")

    n_done = 0
    while True:
        item = qu.get()
        if item is None:
            break
        if item[0] == "PRODUCER_FAILED":
            raise RuntimeError("producer failed") from item[1]
        if item[0] == "CASE_DONE":
            n_done += 1
            if len(texts) >= batch_size * flush_batches:
                flush(); check_budget()
            if n_done % 1000 == 0:
                flush()
                log(f"{n_done}/{len(todo)} cases, {written} chunks written" + progress_suffix(getattr(embedder, "tokens_used", None)))
                check_budget()
            continue
        cid, seq, s, e, text = item
        texts.append(text); rows.append((cid, seq, s, e))
    flush()
    log(f"done: {written} chunks under {run.run_key}" + progress_suffix(getattr(embedder, "tokens_used", None)))
    return written
