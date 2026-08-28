"""Shard stage (spec §7) — fully deterministic.

Reads selectors/selectors.yaml, diffs against the coverage matrix, runs only
(selector-version x partition x jurisdiction) pairs not yet covered, emits
signals with full provenance, groups signal-bearing cases into bounded
batches homogeneous by era x jurisdiction.

Selector types: fts_phrase, fts_near, regex, embedding.
Determinism: FTS queries are deterministic; regex is deterministic; the
embedding selector is deterministic given (pinned model revision, query_text,
min_cosine, top_k) — all recorded on the selector and in the signal.

Usage:
    python pipeline/shard.py --run-id cycle-001-shard-01 [--dry-run]
    python pipeline/shard.py --batches-only --run-id ...   # regroup existing signals
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
SELECTORS = ROOT / "selectors" / "selectors.yaml"
RUNS = ROOT / "runs"

BATCH_SIZE = 18  # spec: 15-20 cases, homogeneous era x jurisdiction

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES cases(case_id),
    selector_id TEXT, selector_version INTEGER,
    matched_text TEXT, char_span_start INTEGER, char_span_end INTEGER,
    chunk_id INTEGER, cosine REAL,
    era_partition TEXT, jurisdiction TEXT,
    run_id TEXT, ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_case ON signals(case_id);
CREATE INDEX IF NOT EXISTS idx_signals_selector ON signals(selector_id, selector_version);
CREATE TABLE IF NOT EXISTS coverage (
    selector_id TEXT, selector_version INTEGER,
    era_partition TEXT, jurisdiction TEXT,
    run_id TEXT, ts TEXT, n_signals INTEGER,
    PRIMARY KEY (selector_id, selector_version, era_partition, jurisdiction)
);
"""

ERAS = ["pre-1860", "1860-1900", "1900-1930", "1930-1970", "1970-2020"]
JURISDICTIONS = ["Tex.", "Pa.", "La.", "N.Y."]


def load_selectors() -> list[dict]:
    sel = yaml.safe_load(SELECTORS.read_text(encoding="utf-8"))
    active = [s for s in sel if s.get("status") == "active"]
    for s in active:
        for field in ("id", "version", "concept", "type", "polarity"):
            if field not in s:
                raise ValueError(f"selector missing {field}: {s}")
    return active


def selector_scopes(s: dict) -> list[tuple[str, str]]:
    eras = s.get("era_scope") or ERAS
    if eras == "all":
        eras = ERAS
    juris = s.get("jurisdiction_scope") or JURISDICTIONS
    if juris == "all":
        juris = JURISDICTIONS
    return [(e, j) for e in eras for j in juris]


def ctx(text: str, start: int, end: int, pad: int = 200) -> str:
    return text[max(0, start - pad) : end + pad]


def run_fts(conn, s: dict, era: str, jur: str) -> list[dict]:
    table = "fts_raw" if s.get("index", "raw") == "raw" else "fts_porter"
    rows = conn.execute(
        f"""SELECT c.case_id, c.norm_text FROM {table}
            JOIN cases c ON c.case_id = {table}.rowid
            WHERE {table} MATCH ?
              AND c.era_partition = ? AND c.jurisdiction = ?
              AND c.is_duplicate_of IS NULL""",
        (s["pattern"], era, jur),
    ).fetchall()
    out = []
    # locate first literal phrase occurrence for provenance context
    phrases = [p.lower() for p in re.findall(r'"([^"]+)"', s["pattern"])]
    for case_id, norm_text in rows:
        span = (0, 0)
        matched = ""
        for ph in phrases:
            i = norm_text.find(ph)
            if i >= 0:
                span = (i, i + len(ph))
                matched = ctx(norm_text, *span)
                break
        if not matched:
            matched = norm_text[:400]
        out.append(
            {"case_id": case_id, "matched_text": matched,
             "span": span, "chunk_id": None, "cosine": None}
        )
    return out


def run_regex(conn, s: dict, era: str, jur: str) -> list[dict]:
    pat = re.compile(s["pattern"], re.IGNORECASE)
    rows = conn.execute(
        """SELECT case_id, norm_text FROM cases
           WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL""",
        (era, jur),
    ).fetchall()
    out = []
    for case_id, norm_text in rows:
        m = pat.search(norm_text)
        if m:
            out.append(
                {"case_id": case_id, "matched_text": ctx(norm_text, m.start(), m.end()),
                 "span": (m.start(), m.end()), "chunk_id": None, "cosine": None}
            )
    return out


_EMBED_CACHE: dict = {}


def run_embedding(conn, s: dict, era: str, jur: str) -> list[dict]:
    import numpy as np

    meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
    model_rev = meta.get("revision", "")
    if s.get("model_rev") and s["model_rev"] != model_rev:
        raise ValueError(
            f"selector {s['id']} pinned model_rev {s['model_rev']} != index {model_rev}"
        )
    unchunked = conn.execute(
        """SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL
           AND norm_text != '' AND case_id NOT IN (SELECT DISTINCT case_id FROM chunks)"""
    ).fetchone()[0]
    if unchunked:
        raise RuntimeError(
            f"embedding index incomplete: {unchunked} cases unchunked — "
            "an embedding selector over a partial index would silently "
            "under-cover; finish index.py embed first"
        )
    if "matrix" not in _EMBED_CACHE:
        rows = conn.execute(
            """SELECT ch.chunk_id, ch.case_id, ch.char_start, ch.char_end,
                      ch.embedding, ch.embed_scale, c.era_partition, c.jurisdiction
               FROM chunks ch JOIN cases c ON c.case_id = ch.case_id
               WHERE c.is_duplicate_of IS NULL"""
        ).fetchall()
        M = np.stack(
            [np.frombuffer(r[4], dtype=np.int8).astype(np.float32) * r[5] for r in rows]
        ) if rows else np.zeros((0, 1), dtype=np.float32)
        _EMBED_CACHE["matrix"] = M
        _EMBED_CACHE["rows"] = rows
    if "model" not in _EMBED_CACHE:
        from sentence_transformers import SentenceTransformer

        _EMBED_CACHE["model"] = SentenceTransformer(
            meta["model"], revision=model_rev or None,
            device="cuda" if _cuda() else "cpu",
        )
    model = _EMBED_CACHE["model"]
    M, rows = _EMBED_CACHE["matrix"], _EMBED_CACHE["rows"]
    dim = int(meta.get("dim", "512"))
    q = model.encode([s["query_text"]], prompt_name="query", convert_to_numpy=True)[0][:dim]
    q = q / (np.linalg.norm(q) + 1e-12)
    sims = M @ q if len(M) else np.zeros(0)
    idx = [
        i for i in np.argsort(-sims)
        if rows[i][6] == era and rows[i][7] == jur
    ][: int(s.get("top_k", 50))]
    out = []
    seen_cases = set()
    for i in idx:
        if sims[i] < float(s.get("min_cosine", 0.5)):
            break
        chunk_id, case_id, cs, ce = rows[i][0], rows[i][1], rows[i][2], rows[i][3]
        if case_id in seen_cases:
            continue
        seen_cases.add(case_id)
        text = conn.execute(
            "SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?",
            (cs + 1, min(ce - cs, 400), case_id),
        ).fetchone()[0]
        out.append(
            {"case_id": case_id, "matched_text": text, "span": (cs, ce),
             "chunk_id": chunk_id, "cosine": float(sims[i])}
        )
    return out


def _cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


RUNNERS = {"fts_phrase": run_fts, "fts_near": run_fts, "regex": run_regex,
           "embedding": run_embedding}


def emit_batches(conn, run_id: str) -> int:
    """Group all signal-bearing cases (across all runs) that are not yet in
    any batch file for this run, homogeneous by era x jurisdiction."""
    rows = conn.execute(
        """SELECT s.case_id, s.era_partition, s.jurisdiction,
                  s.selector_id, s.selector_version, s.matched_text,
                  s.char_span_start, s.char_span_end, s.chunk_id, s.cosine, s.run_id
           FROM signals s ORDER BY s.era_partition, s.jurisdiction, s.case_id"""
    ).fetchall()
    by_case: dict = {}
    for r in rows:
        e = by_case.setdefault(
            r[0], {"case_id": r[0], "era_partition": r[1], "jurisdiction": r[2],
                   "signals": []}
        )
        e["signals"].append(
            {"selector_id": r[3], "selector_version": r[4], "matched_text": r[5],
             "char_span": [r[6], r[7]], "chunk_id": r[8], "cosine": r[9],
             "run_id": r[10]}
        )
    groups: dict = {}
    for e in by_case.values():
        groups.setdefault((e["era_partition"], e["jurisdiction"]), []).append(e)
    out_dir = RUNS / run_id / "batches"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.json"):
        old.unlink()
    gold_ids: set[int] = set()
    gold_file = ROOT / "data" / "gold" / "gold.jsonl"
    if gold_file.exists():
        for line in gold_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cid = json.loads(line).get("case_id")
                if cid:
                    gold_ids.add(cid)
    pending = []
    for (era, jur), cases in sorted(groups.items(), key=lambda kv: str(kv[0])):
        # within a group: multi-selector cases first (signal density, §7)
        cases.sort(key=lambda e: (-len({s["selector_id"] for s in e["signals"]}), e["case_id"]))
        for i in range(0, len(cases), BATCH_SIZE):
            chunk = cases[i : i + BATCH_SIZE]
            pending.append(
                {
                    "era_partition": era, "jurisdiction": jur, "cases": chunk,
                    "_gold": sum(1 for e in chunk if e["case_id"] in gold_ids),
                    "_density": max(
                        len({s["selector_id"] for s in e["signals"]}) for e in chunk
                    ),
                }
            )
    # across groups: gold-bearing batches first (§7 priority a), then density
    pending.sort(key=lambda b: (-b["_gold"], -b["_density"]))
    for n, batch in enumerate(pending, 1):
        batch.pop("_gold"), batch.pop("_density")
        batch["batch_id"] = f"{run_id}-batch-{n:03d}"
        (out_dir / f"batch-{n:03d}.json").write_text(
            json.dumps(batch, indent=1), encoding="utf-8"
        )
    print(f"{len(pending)} batches -> {out_dir}")
    return len(pending)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batches-only", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.executescript(SCHEMA)

    if args.batches_only:
        emit_batches(conn, args.run_id)
        return 0

    selectors = load_selectors()
    print(f"{len(selectors)} active selectors")
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    total_new = 0
    for s in selectors:
        for era, jur in selector_scopes(s):
            covered = conn.execute(
                """SELECT 1 FROM coverage WHERE selector_id=? AND selector_version=?
                   AND era_partition=? AND jurisdiction=?""",
                (s["id"], s["version"], era, jur),
            ).fetchone()
            if covered:
                continue
            if args.dry_run:
                print(f"would run {s['id']} v{s['version']} on {era} x {jur}")
                continue
            try:
                hits = RUNNERS[s["type"]](conn, s, era, jur)
            except RuntimeError as e:
                # e.g. embedding index incomplete: leave (selector, partition)
                # uncovered — no coverage row, a later run picks it up
                print(f"SKIP {s['id']} v{s['version']} {era} x {jur}: {e}")
                continue
            conn.executemany(
                """INSERT INTO signals (case_id, selector_id, selector_version,
                     matched_text, char_span_start, char_span_end, chunk_id,
                     cosine, era_partition, jurisdiction, run_id, ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (h["case_id"], s["id"], s["version"], h["matched_text"],
                     h["span"][0], h["span"][1], h["chunk_id"], h["cosine"],
                     era, jur, args.run_id, ts)
                    for h in hits
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?)",
                (s["id"], s["version"], era, jur, args.run_id, ts, len(hits)),
            )
            conn.commit()
            total_new += len(hits)
            if hits:
                print(f"{s['id']} v{s['version']} {era} x {jur}: {len(hits)} signals")
    print(f"{total_new} new signals")
    if not args.dry_run:
        emit_batches(conn, args.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
