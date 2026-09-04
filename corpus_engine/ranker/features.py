"""One feature function for training and scoring (spec §5.1). Features come from the union
of a case's signals across runs; the batch pool is all-runs too."""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np

VECTOR_KINDS = {"embedding", "relevance_feedback"}
LEXICAL_KINDS = {"fts_phrase", "fts_near", "regex"}


@dataclass(frozen=True)
class FeatureLayout:
    selector_labels: tuple[str, ...]
    vector_labels: tuple[str, ...]
    lexical_labels: tuple[str, ...]
    eras: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    dim: int

    @property
    def names(self) -> list[str]:
        return ([f"sel:{s}" for s in self.selector_labels] + ["n_selectors"]
                + [f"cos:{v}" for v in self.vector_labels]
                + ["pagerank_pct", "pagerank_missing", "log_len", "ocr_confidence", "ocr_missing"]
                + [f"era:{e}" for e in self.eras] + [f"jur:{j}" for j in self.jurisdictions]
                + [f"vec:{i}" for i in range(self.dim)])

    @property
    def size(self) -> int:
        return len(self.names)

    def to_json(self) -> dict:
        return {"selector_labels": list(self.selector_labels), "vector_labels": list(self.vector_labels),
                "lexical_labels": list(self.lexical_labels), "eras": list(self.eras),
                "jurisdictions": list(self.jurisdictions), "dim": self.dim}

    @staticmethod
    def from_json(d: dict) -> "FeatureLayout":
        return FeatureLayout(tuple(d["selector_labels"]), tuple(d["vector_labels"]), tuple(d["lexical_labels"]),
                             tuple(d["eras"]), tuple(d["jurisdictions"]), int(d["dim"]))


def feature_layout(domain, selectors, dim: int) -> FeatureLayout:
    labels = tuple(s.label for s in selectors)
    return FeatureLayout(labels, tuple(s.label for s in selectors if s.kind in VECTOR_KINDS),
                         tuple(s.label for s in selectors if s.kind in LEXICAL_KINDS),
                         tuple(domain.eras), tuple(domain.jurisdictions), dim)


@dataclass(frozen=True)
class CaseSignals:
    selectors: frozenset[str]
    best_cosine: dict           # label -> max cosine
    best_chunk_id: int | None   # chunk of the highest-cosine signal (ties: lowest chunk_id)


def _batched(ids, n=500):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def signal_summary(conn, case_ids) -> dict[int, CaseSignals]:
    sel: dict[int, set] = {}; cos: dict[int, dict] = {}; best: dict[int, tuple] = {}
    for chunk in _batched(case_ids):
        ph = ",".join("?" * len(chunk))
        for cid, sid, ver, chunk_id, c in conn.execute(
                f"SELECT case_id, selector_id, selector_version, chunk_id, cosine FROM signals WHERE case_id IN ({ph})", chunk):
            label = f"{sid}@v{ver}"
            sel.setdefault(cid, set()).add(label)
            if c is not None:
                d = cos.setdefault(cid, {})
                d[label] = max(d.get(label, -1.0), float(c))
                key = (-float(c), chunk_id if chunk_id is not None else 1 << 62)
                if cid not in best or key < best[cid][0]:
                    best[cid] = (key, chunk_id)
    return {cid: CaseSignals(frozenset(sel.get(cid, ())), cos.get(cid, {}), best.get(cid, (None, None))[1])
            for cid in case_ids}


def best_cosine(cs: CaseSignals) -> float:
    return max(cs.best_cosine.values()) if cs.best_cosine else 0.0


def lexical_density(cs: CaseSignals, layout: FeatureLayout) -> float:
    if not layout.lexical_labels:
        return 0.0
    return len(cs.selectors & set(layout.lexical_labels)) / len(layout.lexical_labels)


def _chunk_vector(conn, chunk_id: int | None, case_id: int, dim: int) -> np.ndarray:
    row = None
    if chunk_id is not None:
        row = conn.execute("SELECT embedding, embed_scale FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT embedding, embed_scale FROM chunks WHERE case_id=? ORDER BY seq LIMIT 1", (case_id,)).fetchone()
    out = np.zeros(dim, np.float32)
    if row is None or row[0] is None:
        return out
    v = np.frombuffer(row[0], dtype=np.int8).astype(np.float32) * float(row[1] or 1.0)
    out[:min(dim, len(v))] = v[:dim]
    return out


def case_features(conn, case_ids, layout: FeatureLayout, *, summary: dict | None = None) -> np.ndarray:
    ids = [int(c) for c in case_ids]
    summary = summary if summary is not None else signal_summary(conn, ids)
    idx = {n: i for i, n in enumerate(layout.names)}
    X = np.zeros((len(ids), layout.size), np.float32)
    meta: dict[int, tuple] = {}
    for chunk in _batched(ids):
        ph = ",".join("?" * len(chunk))
        for cid, pr, ocr, ln, era, jur in conn.execute(
                f"SELECT case_id, pagerank_pct, ocr_confidence, length(norm_text), era_partition, jurisdiction "
                f"FROM cases WHERE case_id IN ({ph})", chunk):
            meta[cid] = (pr, ocr, ln, era, jur)
    v0 = idx["vec:0"]
    for row, cid in enumerate(ids):
        cs = summary.get(cid) or CaseSignals(frozenset(), {}, None)
        for label in cs.selectors:
            if f"sel:{label}" in idx:
                X[row, idx[f"sel:{label}"]] = 1.0
        X[row, idx["n_selectors"]] = len(cs.selectors)
        for label, c in cs.best_cosine.items():
            if f"cos:{label}" in idx:
                X[row, idx[f"cos:{label}"]] = c
        pr, ocr, ln, era, jur = meta.get(cid, (None, None, None, None, None))
        X[row, idx["pagerank_pct"]] = 0.0 if pr is None else float(pr)
        X[row, idx["pagerank_missing"]] = 1.0 if pr is None else 0.0
        X[row, idx["log_len"]] = math.log1p(ln or 0)
        X[row, idx["ocr_confidence"]] = 0.0 if ocr is None else float(ocr)
        X[row, idx["ocr_missing"]] = 1.0 if ocr is None else 0.0
        if f"era:{era}" in idx:
            X[row, idx[f"era:{era}"]] = 1.0
        if f"jur:{jur}" in idx:
            X[row, idx[f"jur:{jur}"]] = 1.0
        X[row, v0:v0 + layout.dim] = _chunk_vector(conn, cs.best_chunk_id, cid, layout.dim)
    return X
