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
    """Score a ranker against a labelled set and, per cell, against the reviewed view.

    The "reviewed view" (`rv` below, and `ap_reviewed`/`n_reviewed` in the returned dict)
    is reviewed positives plus *all* negatives - not a human-reviewed subset. Negatives
    come from machine extraction verdicts (`relevant is False`), never human-adjudicated
    (see `corpus_engine.ranker.labels.labelled_reads`, which hardcodes `reviewed=False` on
    every one). So `ap_reviewed` measures ranking of human-confirmed positives against
    machine-labelled negatives, and label noise in those negatives flows straight into it.
    """
    y = np.array([l.label for l in labels]); s = np.array([scores[l.case_id] for l in labels]); w = np.array([l.weight for l in labels])
    rv = np.array([l.reviewed or l.label == 0 for l in labels])       # reviewed positives + all negatives (machine
                                                                       # extraction verdicts, not human adjudications)
    out = {"n_all": int(len(labels)), "ap_all": average_precision(y, s), "p50_all": precision_at(y, s, 50), "p200_all": precision_at(y, s, 200),
           "n_reviewed": int(rv.sum()), "ap_reviewed": average_precision(y[rv], s[rv]) if rv.any() else 0.0, "per_cell": {}}
    cells = sorted({(l.era, l.jurisdiction) for l in labels})
    for era, jur in cells:
        m = np.array([(l.era, l.jurisdiction) == (era, jur) for l in labels])
        out["per_cell"][f"{era}|{jur}"] = {"n": int(m.sum()), "ap": average_precision(y[m], s[m]), "p50": precision_at(y[m], s[m], 50)}
    return out


def compare(a: dict, b: dict) -> dict:
    return {k: round(b[k] - a[k], 6) for k in ("ap_all", "ap_reviewed", "p50_all", "p200_all")}


def ships(classifier: dict, fusion: dict) -> bool:
    """D6, exactly as Stage 2C pre-registered it: the classifier becomes `ranking.default`
    only if its average precision EXCEEDS fusion's on BOTH views - all held-out reads, and the
    reviewed view. No margin, no tie-break, no per-cell override: `>` on both, or it does not
    ship. It lives here so the tool that decides and the report that explains the decision
    cannot drift apart."""
    return (classifier["ap_all"] > fusion["ap_all"]
            and classifier["ap_reviewed"] > fusion["ap_reviewed"])
