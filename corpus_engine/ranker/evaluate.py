from __future__ import annotations
import numpy as np


def average_precision(y, s, w=None) -> float:
    y = np.asarray(y, float); s = np.asarray(s, float); w = np.ones_like(y) if w is None else np.asarray(w, float)
    if y.sum() == 0:
        return 0.0
    order = np.lexsort((np.arange(len(s)), -s))          # score desc, stable
    y, w = y[order], w[order]
    tp = np.cumsum(y * w); n = np.cumsum(w)
    return float((tp / n * y * w).sum() / (y * w).sum())


def precision_at(y, s, k: int) -> float:
    y = np.asarray(y, float); s = np.asarray(s, float)
    order = np.lexsort((np.arange(len(s)), -s))[:k]
    return float(y[order].mean()) if len(order) else 0.0


def evaluate_scores(labels, scores: dict) -> dict:
    y = np.array([l.label for l in labels]); s = np.array([scores[l.case_id] for l in labels]); w = np.array([l.weight for l in labels])
    rv = np.array([l.reviewed or l.label == 0 for l in labels])       # "human-reviewed view" = reviewed positives + all negatives
    out = {"n_all": int(len(labels)), "ap_all": average_precision(y, s), "p50_all": precision_at(y, s, 50), "p200_all": precision_at(y, s, 200),
           "n_reviewed": int(rv.sum()), "ap_reviewed": average_precision(y[rv], s[rv]) if rv.any() else 0.0, "per_cell": {}}
    cells = sorted({(l.era, l.jurisdiction) for l in labels})
    for era, jur in cells:
        m = np.array([(l.era, l.jurisdiction) == (era, jur) for l in labels])
        out["per_cell"][f"{era}|{jur}"] = {"n": int(m.sum()), "ap": average_precision(y[m], s[m]), "p50": precision_at(y[m], s[m], 50)}
    return out


def compare(a: dict, b: dict) -> dict:
    return {k: round(b[k] - a[k], 6) for k in ("ap_all", "ap_reviewed", "p50_all", "p200_all")}
