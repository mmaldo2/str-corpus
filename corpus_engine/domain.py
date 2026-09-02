"""Domain loader: everything STR-specific comes from domains/<name>/domain.yaml
so the engine never imports a domain file by literal path (ADR-0010)."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import yaml
from corpus_engine.store import paths


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
    )
