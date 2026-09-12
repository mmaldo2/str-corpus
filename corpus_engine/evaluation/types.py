"""Result types every measure returns. Frozen dataclasses; `to_json`-able via `asdict`."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Estimate:
    value: float | None
    n: int
    lo: float | None
    hi: float | None
    status: str                       # "ok" | "undefined" | "unavailable"


UNAVAILABLE = Estimate(None, 0, None, None, "unavailable")


@dataclass(frozen=True)
class Uncertainty:
    type: str                         # "sampling" | "assumption" | "none"
    level: float | None               # 0.95 for a Wilson interval; None otherwise
    method: str                       # "wilson" | "scenarios" | "none"


@dataclass(frozen=True)
class Provenance:
    inputs: tuple[tuple[str, str, str], ...] = ()     # (path, sha256, role)
    run_ids: tuple[str, ...] = ()
    ledger_seqs: dict = field(default_factory=dict)   # e.g. {"reporting": 51234}


@dataclass(frozen=True)
class Envelope:
    method_version: str
    population: str
    exclusions: tuple[str, ...]
    uncertainty: Uncertainty
    limitations: tuple[str, ...]
    provenance: Provenance


def as_dict(obj: Any) -> Any:
    """`dataclasses.asdict` that also turns tuples into lists, for JSON."""
    def fix(v):
        if isinstance(v, tuple):
            return [fix(x) for x in v]
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {str(k): fix(x) for k, x in v.items()}
        return v
    return fix(asdict(obj))
