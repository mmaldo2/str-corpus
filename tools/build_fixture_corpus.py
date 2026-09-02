"""Build tests/fixtures/corpus-tiny.db from the live corpus. Run once:
    .venv\\Scripts\\python tools\\build_fixture_corpus.py
"""
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "corpus-tiny.db"

# Real chunks/embed_meta DDL, copied verbatim from pipeline/index.py:33-57
# (fts_porter/fts_raw match there too).
FIXTURE_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_porter USING fts5(norm_text, content='cases', content_rowid='case_id', tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS fts_raw USING fts5(norm_text, content='cases', content_rowid='case_id', tokenize='unicode61');
CREATE TABLE IF NOT EXISTS chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER REFERENCES cases(case_id), seq INTEGER, char_start INTEGER, char_end INTEGER, embedding BLOB, embed_scale REAL, UNIQUE (case_id, seq));
CREATE TABLE IF NOT EXISTS embed_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def case_ids() -> list[int]:
    ids: set[int] = set()
    for n in range(1, 6):
        b = json.loads((ROOT / f"runs/cycle-003-shard-01/batches/batch-{n:03d}.json").read_text(encoding="utf-8"))
        ids.update(c["case_id"] for c in b["cases"])
    for line in (ROOT / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("case_id"):
            ids.add(json.loads(line)["case_id"])
    for f in (ROOT / "data/ledger").glob("cycle-*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("review", {}).get("status") != "machine":
                    ids.add(r["case_id"])
    return sorted(ids)


def main() -> int:
    ids = case_ids()
    src = store.connect(wal=False)
    if OUT.exists():
        OUT.unlink()
    dst = sqlite3.connect(OUT)
    store.ensure_schema(dst)
    dst.executescript(FIXTURE_SCHEMA)
    cols = [r[1] for r in src.execute("PRAGMA table_info(cases)")]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        rows = src.execute(f"SELECT {','.join(cols)} FROM cases WHERE case_id IN ({ph})", chunk).fetchall()
        dst.executemany(f"INSERT INTO cases ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", rows)
        dst.executemany("INSERT INTO citations VALUES (?,?,?,?)",
                        src.execute(f"SELECT case_id, cite, cite_norm, type FROM citations WHERE case_id IN ({ph})", chunk).fetchall())
        dst.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                        src.execute(f"SELECT chunk_id, case_id, seq, char_start, char_end, embedding, embed_scale FROM chunks WHERE case_id IN ({ph})", chunk).fetchall())
    dst.executemany("INSERT INTO embed_meta VALUES (?,?)", src.execute("SELECT key, value FROM embed_meta").fetchall())
    dst.execute("INSERT INTO fts_porter(fts_porter) VALUES ('rebuild')")
    dst.execute("INSERT INTO fts_raw(fts_raw) VALUES ('rebuild')")
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    print(f"{len(ids)} cases -> {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
