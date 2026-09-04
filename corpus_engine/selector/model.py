from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Mapping
import yaml

ENGINE_VERSION = "v2"   # stable candidate sort (ADR-0011)


class SelectorSpecError(ValueError): ...


@dataclass(frozen=True, slots=True)
class Partition:
    era: str
    jurisdiction: str
    @property
    def key(self) -> str:
        return f"{self.era}|{self.jurisdiction}"


SelectorKey = tuple[str, int]


@dataclass(frozen=True)
class KindSpec:
    required: tuple[str, ...]
    optional: dict[str, Any] = field(default_factory=dict)


KIND_SPECS: dict[str, KindSpec] = {
    "fts_phrase": KindSpec(("pattern",), {"index": "raw"}),
    "fts_near": KindSpec(("pattern",), {"index": "raw"}),
    "regex": KindSpec(("pattern",)),
    "embedding": KindSpec(("query_text",), {"top_k": 50, "min_cosine": 0.5, "model_rev": None}),
    "citation_graph": KindSpec(("seed_set",), {"direction": "both"}),
    "relevance_feedback": KindSpec(("seed_set",), {"top_k": 50, "min_cosine": 0.5}),
}


@dataclass(frozen=True)
class Selector:
    id: str
    version: int
    kind: str
    concept: str
    polarity: str
    era_scope: tuple[str, ...]
    jurisdiction_scope: tuple[str, ...]
    params: Mapping[str, Any]
    author: str = ""
    rationale: str = ""
    status: str = "active"

    @property
    def key(self) -> SelectorKey:
        return (self.id, self.version)

    @property
    def label(self) -> str:
        return f"{self.id}@v{self.version}"

    def digest(self) -> str:
        d = asdict(self); d.pop("rationale"); d.pop("author")
        d["params"] = dict(sorted(dict(self.params).items()))
        return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:16]


def _scope(value, universe: tuple[str, ...], selector_id: str, scope_name: str) -> tuple[str, ...]:
    if value in (None, "all"):
        return tuple(universe)
    if isinstance(value, str):
        raise SelectorSpecError(f"{selector_id}: {scope_name} must be a list or \"all\", not a bare string")
    scope_list = tuple(value)
    for v in scope_list:
        if v not in universe:
            raise SelectorSpecError(f"{selector_id}: {scope_name} contains unknown value {v}")
    return scope_list


def parse_selector(raw: dict, *, eras, jurisdictions) -> Selector:
    for f in ("id", "version", "concept", "type", "polarity"):
        if f not in raw:
            raise SelectorSpecError(f"selector missing {f}: {raw.get('id')}")
    kind = raw["type"]
    if kind not in KIND_SPECS:
        raise SelectorSpecError(f"{raw['id']}: unknown selector type {kind}")
    spec = KIND_SPECS[kind]
    params: dict[str, Any] = {}
    for p in spec.required:
        if p not in raw:
            raise SelectorSpecError(f"{raw['id']}: {kind} requires {p}")
        params[p] = raw[p]
    for p, default in spec.optional.items():
        params[p] = raw.get(p, default)
    return Selector(id=raw["id"], version=int(raw["version"]), kind=kind, concept=raw["concept"],
                    polarity=raw["polarity"], era_scope=_scope(raw.get("era_scope"), tuple(eras), raw["id"], "era_scope"),
                    jurisdiction_scope=_scope(raw.get("jurisdiction_scope"), tuple(jurisdictions), raw["id"], "jurisdiction_scope"),
                    params=params, author=raw.get("author", ""), rationale=raw.get("rationale", ""),
                    status=raw.get("status", "active"))


def load_selectors(domain, *, include_retired: bool = False) -> list[Selector]:
    raw = yaml.safe_load(Path(domain.selectors_path).read_text(encoding="utf-8"))
    out, seen = [], set()
    for r in raw:
        if not include_retired and r.get("status") != "active":
            continue
        s = parse_selector(r, eras=domain.eras, jurisdictions=domain.jurisdictions)
        if s.key in seen:
            raise SelectorSpecError(f"duplicate selector {s.label}")
        seen.add(s.key); out.append(s)
    return out


@dataclass(frozen=True)
class SeedSet:
    name: str
    case_ids: tuple[int, ...]
    hash: str

    @staticmethod
    def build(name: str, ids) -> "SeedSet":
        cids = tuple(sorted({int(i) for i in ids}))
        h = hashlib.sha256(",".join(map(str, cids)).encode()).hexdigest()[:16]
        return SeedSet(name, cids, h)


@dataclass(frozen=True)
class Signal:
    case_id: int; selector_id: str; selector_version: int
    matched_text: str; char_span: tuple[int, int]
    chunk_id: int | None; cosine: float | None
    partition: Partition


@dataclass(frozen=True)
class SignalRef:
    selector_id: str; selector_version: int; run_id: str; cosine: float | None


@dataclass(frozen=True)
class Skip:
    key: SelectorKey; partitions: tuple[Partition, ...]; reason: str


@dataclass(frozen=True)
class PlanUnit:
    key: SelectorKey; partition: Partition; fingerprint: str


@dataclass(frozen=True)
class ShardPlan:
    run_id: str; units: tuple[PlanUnit, ...]; skips: tuple[Skip, ...]; selectors_digest: str


@dataclass
class ShardReport:
    plan: ShardPlan
    signals_written: dict
    batches_written: int
    batch_dir: Path | None
    cases_batched: int
    excluded_already_read: int
    manifest: dict
