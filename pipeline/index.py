"""Build retrieval indexes over the ingested corpus.

Two FTS5 indexes over norm_text (spec §5): a porter-stemmed one and a raw
unicode61 one — historical terms of art must be matchable exactly. Both are
external-content tables over `cases` and exclude nothing at build time;
shard.py excludes duplicates at query time.

Embeddings: Qwen3-Embedding-0.6B (Amendment A5), pinned by HF revision,
matryoshka-truncated to 512d, L2-normalized then symmetric int8 per-vector
quantization. Chunks are ~1000 tokens with 15% overlap, boundaries computed
with the model's own tokenizer (deterministic given the pinned revision).
Chunk rows store char offsets into norm_text, not copied text.

Usage:
    python pipeline/index.py fts                 # (re)build both FTS tables
    python pipeline/index.py embed [--batch 64] [--limit N]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "db" / "corpus.db"

EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBED_REVISION = "main"  # resolved to a commit hash and recorded at run time
EMBED_DIM = 512  # matryoshka truncation
CHUNK_TOKENS = 1000
CHUNK_OVERLAP = 150

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_porter USING fts5(
    norm_text, content='cases', content_rowid='case_id',
    tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_raw USING fts5(
    norm_text, content='cases', content_rowid='case_id',
    tokenize='unicode61'
);
"""

CHUNK_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES cases(case_id),
    seq INTEGER,
    char_start INTEGER, char_end INTEGER,
    embedding BLOB,             -- int8[EMBED_DIM]
    embed_scale REAL,           -- dequant: float = int8 * embed_scale
    UNIQUE (case_id, seq)
);
CREATE TABLE IF NOT EXISTS embed_meta (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def build_fts(conn: sqlite3.Connection) -> None:
    conn.executescript(FTS_SCHEMA)
    for table in ("fts_porter", "fts_raw"):
        conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        conn.commit()
        n = conn.execute(
            f"SELECT count(*) FROM {table} WHERE {table} MATCH 'the'"
        ).fetchone()[0]
        print(f"{table}: rebuilt ({n} docs match 'the')")


def chunk_offsets(tokenizer, text: str) -> list[tuple[int, int]]:
    """Deterministic char-offset chunks of ~CHUNK_TOKENS tokens with
    CHUNK_OVERLAP-token overlap, via the pinned tokenizer's offset mapping."""
    enc = tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True,
        truncation=False, verbose=False,
    )
    offsets = enc["offset_mapping"]
    if not offsets:
        return []
    spans = []
    step = CHUNK_TOKENS - CHUNK_OVERLAP
    i = 0
    while i < len(offsets):
        window = offsets[i : i + CHUNK_TOKENS]
        spans.append((window[0][0], window[-1][1]))
        if i + CHUNK_TOKENS >= len(offsets):
            break
        i += step
    return spans


def build_embeddings(conn: sqlite3.Connection, batch_size: int, limit: int) -> None:
    import numpy as np
    import torch
    from huggingface_hub import HfApi
    from sentence_transformers import SentenceTransformer

    conn.executescript(CHUNK_SCHEMA)
    commit = HfApi().model_info(EMBED_MODEL, revision=EMBED_REVISION).sha
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(
        EMBED_MODEL, revision=commit, device=device,
        model_kwargs={"torch_dtype": torch.float16} if device == "cuda" else {},
        tokenizer_kwargs={"padding_side": "left"},
    )
    tokenizer = model.tokenizer
    for k, v in {
        "model": EMBED_MODEL, "revision": commit, "dim": str(EMBED_DIM),
        "chunk_tokens": str(CHUNK_TOKENS), "chunk_overlap": str(CHUNK_OVERLAP),
        "quant": "int8-symmetric-pervector",
    }.items():
        conn.execute("INSERT OR REPLACE INTO embed_meta VALUES (?,?)", (k, v))
    conn.commit()
    print(f"model {EMBED_MODEL}@{commit[:12]} on {device}")

    # ids only — fetching 1.7M full texts at once OOMs the machine
    q = """SELECT case_id FROM cases
           WHERE is_duplicate_of IS NULL
             AND case_id NOT IN (SELECT DISTINCT case_id FROM chunks)
           ORDER BY case_id"""
    if limit:
        q += f" LIMIT {int(limit)}"
    todo_ids = [r[0] for r in conn.execute(q)]
    print(f"{len(todo_ids)} cases to chunk+embed", flush=True)

    buf_texts: list[str] = []
    buf_rows: list[tuple[int, int, int, int]] = []

    def flush() -> None:
        if not buf_texts:
            return
        vecs = model.encode(
            buf_texts, batch_size=batch_size, convert_to_numpy=True,
            normalize_embeddings=False, show_progress_bar=False,
        )[:, :EMBED_DIM]
        vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
        scales = np.abs(vecs).max(axis=1) / 127.0
        q8 = np.round(vecs / scales[:, None]).astype(np.int8)
        conn.executemany(
            """INSERT OR IGNORE INTO chunks
               (case_id, seq, char_start, char_end, embedding, embed_scale)
               VALUES (?,?,?,?,?,?)""",
            [
                (cid, seq, s, e, q8[i].tobytes(), float(scales[i]))
                for i, (cid, seq, s, e) in enumerate(buf_rows)
            ],
        )
        conn.commit()
        buf_texts.clear()
        buf_rows.clear()

    # producer thread: DB reads + CPU tokenization (fast tokenizers release
    # the GIL) feed a queue; main thread keeps the GPU busy encoding.
    import queue
    import threading

    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    q: queue.Queue = queue.Queue(maxsize=4000)

    def producer() -> None:
        read_conn = sqlite3.connect(db_path)
        read_conn.execute("PRAGMA busy_timeout=120000")
        for case_id in todo_ids:
            row = read_conn.execute(
                "SELECT norm_text FROM cases WHERE case_id=?", (case_id,)
            ).fetchone()
            norm_text = row[0] if row else ""
            if not norm_text:
                continue
            for seq, (s, e) in enumerate(chunk_offsets(tokenizer, norm_text)):
                q.put((case_id, seq, s, e, norm_text[s:e]))
            q.put(("CASE_DONE", case_id, None, None, None))
        q.put(None)

    threading.Thread(target=producer, daemon=True).start()
    done_cases = 0
    while True:
        item = q.get()
        if item is None:
            break
        if item[0] == "CASE_DONE":
            done_cases += 1
            # flush only at case boundaries: a mid-case flush + kill would
            # leave a partial case the resume query then skips forever
            if len(buf_texts) >= batch_size * 8:
                flush()
            if done_cases % 1000 == 0:
                flush()
                n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
                print(f"{done_cases}/{len(todo_ids)} cases, {n} chunks", flush=True)
            continue
        case_id, seq, s, e, text = item
        buf_texts.append(text)
        buf_rows.append((case_id, seq, s, e))
    flush()
    n = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    print(f"done: {n} chunks total")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["fts", "embed"])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    if args.stage == "fts":
        build_fts(conn)
    else:
        build_embeddings(conn, args.batch, args.limit)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
