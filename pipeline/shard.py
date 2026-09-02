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

sys.path.insert(0, str(ROOT))
from corpus_engine import store  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
_DOMAIN = load_domain()
ERAS = list(_DOMAIN.eras)
JURISDICTIONS = list(_DOMAIN.jurisdictions)


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
    dim = int(meta.get("dim", "512"))
    if "M8" not in _EMBED_CACHE:
        # preallocated arrays, streamed fill: ~2 GB for 3.9M x 512 int8
        # (fetchall + python lists at this scale OOMs a 32 GB machine)
        n = conn.execute(
            """SELECT count(*) FROM chunks ch JOIN cases c ON c.case_id = ch.case_id
               WHERE c.is_duplicate_of IS NULL"""
        ).fetchone()[0]
        M8 = np.empty((n, dim), dtype=np.int8)
        scales = np.empty(n, dtype=np.float32)
        chunk_ids = np.empty(n, dtype=np.int64)
        case_ids = np.empty(n, dtype=np.int64)
        spans = np.empty((n, 2), dtype=np.int32)
        era_codes = np.empty(n, dtype=np.int8)
        jur_codes = np.empty(n, dtype=np.int8)
        era_idx = {e: i for i, e in enumerate(ERAS)}
        jur_idx = {j: i for i, j in enumerate(JURISDICTIONS)}
        cur = conn.execute(
            """SELECT ch.chunk_id, ch.case_id, ch.char_start, ch.char_end,
                      ch.embedding, ch.embed_scale, c.era_partition, c.jurisdiction
               FROM chunks ch JOIN cases c ON c.case_id = ch.case_id
               WHERE c.is_duplicate_of IS NULL"""
        )
        i = 0
        for row in cur:
            M8[i] = np.frombuffer(row[4], dtype=np.int8)
            scales[i] = row[5]
            chunk_ids[i], case_ids[i] = row[0], row[1]
            spans[i] = (row[2], row[3])
            era_codes[i] = era_idx.get(row[6], -1)
            jur_codes[i] = jur_idx.get(row[7], -1)
            i += 1
        _EMBED_CACHE.update(
            M8=M8[:i], scales=scales[:i], chunk_ids=chunk_ids[:i],
            case_ids=case_ids[:i], spans=spans[:i],
            era_codes=era_codes[:i], jur_codes=jur_codes[:i],
            era_idx=era_idx, jur_idx=jur_idx, sims={},
        )
    if "model" not in _EMBED_CACHE:
        from sentence_transformers import SentenceTransformer

        _EMBED_CACHE["model"] = SentenceTransformer(
            meta["model"], revision=model_rev or None,
            device="cuda" if _cuda() else "cpu",
        )
    C = _EMBED_CACHE
    sims_key = f"{s['id']}@v{s['version']}"
    if sims_key not in C["sims"]:
        q = C["model"].encode(
            [s["query_text"]], prompt_name="query", convert_to_numpy=True
        )[0][:dim].astype(np.float32)
        q = q / (np.linalg.norm(q) + 1e-12)
        n = len(C["M8"])
        sims = np.empty(n, dtype=np.float32)
        block = 200_000
        for a in range(0, n, block):
            b = min(a + block, n)
            sims[a:b] = (C["M8"][a:b].astype(np.float32) @ q) * C["scales"][a:b]
        C["sims"] = {sims_key: sims}  # keep only the current selector's pass
    sims = C["sims"][sims_key]
    mask = (C["era_codes"] == C["era_idx"][era]) & (
        C["jur_codes"] == C["jur_idx"][jur]
    )
    cand = np.flatnonzero(mask)
    if not len(cand):
        return []
    order = cand[np.argsort(-sims[cand])][: int(s.get("top_k", 50)) * 3]
    out = []
    seen_cases = set()
    min_cos = float(s.get("min_cosine", 0.5))
    for i in order:
        if sims[i] < min_cos or len(out) >= int(s.get("top_k", 50)):
            break
        case_id = int(C["case_ids"][i])
        if case_id in seen_cases:
            continue
        seen_cases.add(case_id)
        cs, ce = int(C["spans"][i][0]), int(C["spans"][i][1])
        text = conn.execute(
            "SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?",
            (cs + 1, min(ce - cs, 400), case_id),
        ).fetchone()[0]
        out.append(
            {"case_id": case_id, "matched_text": text, "span": (cs, ce),
             "chunk_id": int(C["chunk_ids"][i]), "cosine": float(sims[i])}
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


def already_mapped_ids() -> set[int]:
    """Cases already extracted in any prior run — excluded from new batches
    so each cycle pays only for unread material."""
    ids: set[int] = set()
    for f in RUNS.glob("*/extractions*/*.json"):
        try:
            for r in json.loads(f.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("case_id"):
                    ids.add(r["case_id"])
        except (json.JSONDecodeError, OSError):
            continue
    return ids


def emit_batches(conn, run_id: str, exclude_mapped: bool = False) -> int:
    from corpus_engine.selector.packing import pack_batches
    gold_ids: set[int] = set()
    gold_file = ROOT / "data" / "gold" / "gold.jsonl"
    if gold_file.exists():
        for line in gold_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cid = json.loads(line).get("case_id")
                if cid:
                    gold_ids.add(cid)
    skip_ids = already_mapped_ids() if exclude_mapped else set()
    if skip_ids:
        print(f"excluding {len(skip_ids)} already-mapped cases")
    n = pack_batches(conn, run_id, RUNS / run_id / "batches", gold_ids=gold_ids,
                     exclude_ids=skip_ids, batch_size=BATCH_SIZE)
    print(f"{n} batches -> {RUNS / run_id / 'batches'}")
    return n


def missing_jurisdictions(conn, jurisdictions) -> list[str]:
    """Domain jurisdictions with no cases in the corpus; sharding them would poison coverage."""
    present = {r[0] for r in conn.execute("SELECT DISTINCT jurisdiction FROM cases WHERE is_duplicate_of IS NULL")}
    return [j for j in jurisdictions if j not in present]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batches-only", action="store_true")
    ap.add_argument("--exclude-mapped", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    store.ensure_schema(conn)

    missing = missing_jurisdictions(conn, JURISDICTIONS)
    if missing:
        sys.exit(f"refusing to shard: no cases ingested for {missing}; ingest them first "
                  f"(Stage 2 replaces this guard with fingerprinted coverage)")

    if args.batches_only:
        emit_batches(conn, args.run_id, args.exclude_mapped)
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
        emit_batches(conn, args.run_id, args.exclude_mapped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
