"""Domain loader: everything STR-specific comes from domains/<name>/domain.yaml
so the engine never imports a domain file by literal path (ADR-0010)."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import yaml
from corpus_engine.store import paths


@dataclass(frozen=True)
class ShardingSpec:
    batch_size: int = 18
    min_seeds: int = 5


@dataclass(frozen=True)
class RankingSpec:
    default: str = "null"
    classifier_version: str = "v1"
    fusion: Mapping[str, float] = None            # type: ignore[assignment]
    reranker: Mapping[str, object] = None         # type: ignore[assignment]
    heldout: str = ""
    heldout_sha256: str | None = None
    bar_ap_delta: float = 0.05

    def __post_init__(self):
        object.__setattr__(self, "default", self.default or "null")
        object.__setattr__(self, "fusion", dict(self.fusion or {"lexical_weight": 0.5, "cosine_weight": 0.5}))
        object.__setattr__(self, "reranker", dict(self.reranker or {}))


@dataclass(frozen=True)
class ReaderSpec:
    codebooks_dir: str = "codebooks"
    codebook: str = "mapper-v2"
    judged_fields: tuple[str, ...] = ("characterization", "polarity", "holding_summary")
    checker_sample_pct: int = 10
    families: Mapping[str, str] = None            # type: ignore[assignment]
    kit_path: str = ""
    kit_sha256: str | None = None
    candidates: tuple = ()
    model: Mapping | None = None
    stability_sample: str = ""
    checker: Mapping | None = None
    def __post_init__(self):
        object.__setattr__(self, "families", dict(self.families or {}))
        object.__setattr__(self, "judged_fields", tuple(self.judged_fields))
        object.__setattr__(self, "candidates", tuple(dict(c) for c in (self.candidates or ())))
        object.__setattr__(self, "model", dict(self.model) if self.model else None)
        object.__setattr__(self, "checker", dict(self.checker) if self.checker else None)


@dataclass(frozen=True)
class EmbeddingSpec:
    run_key: str; model: str; revision: str; dim: int; quant: str
    chunk_tokens: int; chunk_overlap: int; prefix_template: str
    hosted_provider: str; hosted_model_id: str
    hosted_usd_per_m_tokens: float | None = None  # corpus_engine stays domain-agnostic: None if the domain omits it


@dataclass(frozen=True)
class Domain:
    name: str
    root: Path
    eras: tuple[str, ...]
    era_bounds: tuple[tuple[int, str], ...]
    jurisdictions: tuple[str, ...]
    reporter_slugs: tuple[str, ...]
    regions: Mapping[str, str]
    letting_tiers: Mapping[str, str]
    judged_fields: tuple[str, ...]
    curatorial_fields: tuple[str, ...]
    selectors_path: Path
    ontology_path: Path
    prompts_dir: Path
    gold_path: Path
    reviewer_default: str
    embedding: EmbeddingSpec
    sharding: ShardingSpec
    ranking: RankingSpec
    reader: ReaderSpec


def load_domain(name: str = "str-right-to-let") -> Domain:
    d = paths().domains / name
    cfg = yaml.safe_load((d / "domain.yaml").read_text(encoding="utf-8"))
    repo = paths().root
    bounds = tuple((int(b["upper"]), b["label"]) for b in cfg["era_bounds"])
    return Domain(
        name=name, root=d,
        eras=tuple(b[1] for b in bounds),
        era_bounds=bounds,
        jurisdictions=tuple(cfg["jurisdictions"]),
        reporter_slugs=tuple(cfg.get("reporter_slugs", [])),
        regions=dict(cfg["regions"]),
        letting_tiers=dict(cfg["letting_tiers"]),
        judged_fields=tuple(cfg["judged_fields"]),
        curatorial_fields=tuple(cfg["curatorial_fields"]),
        selectors_path=repo / cfg["paths"]["selectors"],
        ontology_path=repo / cfg["paths"]["ontology"],
        prompts_dir=repo / cfg["paths"]["prompts"],
        gold_path=repo / cfg["paths"]["gold"],
        reviewer_default=cfg.get("reviewer_default", "unknown"),
        embedding=EmbeddingSpec(**cfg["embedding"]),
        sharding=ShardingSpec(**cfg.get("sharding", {})),
        ranking=RankingSpec(**cfg.get("ranking", {})),
        reader=ReaderSpec(**cfg.get("reader", {})),
    )
