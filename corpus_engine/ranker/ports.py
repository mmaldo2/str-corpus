from __future__ import annotations
import hashlib, json
from typing import Protocol, Sequence
import numpy as np
from corpus_engine.ranker.features import FeatureLayout, best_cosine, lexical_density, signal_summary


def round6(x) -> float:
    return round(float(np.float32(x)), 6)


class Ranker(Protocol):
    ranker_id: str
    def digest(self) -> str: ...
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]: ...


class NullRanker:
    """Legacy order: distinct-selector density (the batch packer breaks ties by case_id)."""
    ranker_id = "null"
    def digest(self) -> str:
        return ""
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        return {c: float(len({l.split("@v")[0] for l in summ[c].selectors})) for c in ids}


class FusionRanker:
    ranker_id = "fusion:v1"
    def __init__(self, layout: FeatureLayout, lexical_weight: float, cosine_weight: float):
        self.layout, self.wl, self.wc = layout, float(lexical_weight), float(cosine_weight)
    def digest(self) -> str:
        cfg = json.dumps({"wl": self.wl, "wc": self.wc, "lexical": self.layout.lexical_labels}, sort_keys=True)
        return hashlib.sha256(cfg.encode()).hexdigest()[:16]
    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        return {c: round6(self.wl * lexical_density(summ[c], self.layout) + self.wc * max(0.0, best_cosine(summ[c])))
                for c in ids}


def _dim(conn) -> int:
    return int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))


def load_ranker(domain, conn, ranker_id: str | None):
    from corpus_engine.selector.model import load_selectors
    from corpus_engine.ranker.features import feature_layout
    rid = (ranker_id or domain.ranking.default or "null").split(":")[0]
    if rid == "null":
        return NullRanker()
    layout = feature_layout(domain, load_selectors(domain), _dim(conn))
    if rid == "fusion":
        f = domain.ranking.fusion
        return FusionRanker(layout, f["lexical_weight"], f["cosine_weight"])
    if rid == "classifier":
        from corpus_engine.ranker.classifier import ClassifierRanker   # Task 5
        return ClassifierRanker.from_domain(domain)
    if rid == "reranker":
        from corpus_engine.ranker.reranker import QwenReranker         # Task 7
        return QwenReranker.from_domain(domain)
    raise ValueError(f"unknown ranker {ranker_id!r}")
