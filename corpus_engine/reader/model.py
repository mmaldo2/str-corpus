from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping


class ReaderError(Exception): ...


@dataclass(frozen=True)
class ModelPin:
    model_id: str
    family: str
    provider_name: str | None = None
    precision: str | None = None
    extra: Mapping = field(default_factory=dict)
    @property
    def label(self) -> str:
        return f"{self.model_id}@{self.provider_name or '-'}:{self.precision or '-'}"


@dataclass(frozen=True)
class Request:
    # max_tokens has to cover reasoning tokens too: on a reasoning-native model the
    # trace is billed and counted against this cap, and at 16000 the 2026-09-04
    # measurement's first attempt got finish_reason=length with empty content on
    # full batches. 64000 is at or under every ADR-0007 candidate's completion cap.
    pin: ModelPin; user: str; system: str | None = None; json_schema: dict | None = None
    max_tokens: int = 64000; temperature: float = 0.0


@dataclass(frozen=True)
class Response:
    text: str; input_tokens: int; output_tokens: int; cost_usd: float | None
    provider_reported: Mapping; finish_reason: str; tool_version: str | None = None


@dataclass(frozen=True)
class CaseText:
    case_id: int; cite: str; name: str; court: str; jurisdiction: str; year: int | None
    raw_text: str; norm_text: str; page_map: list; provenance: tuple = ()


@dataclass(frozen=True)
class Budget:
    max_usd: float | None = None; max_units: int | None = None; max_wall_seconds: float | None = None


@dataclass(frozen=True)
class StopReason:
    kind: str; detail: str = ""


@dataclass(frozen=True)
class Unit:
    id: str; case_ids: tuple[int, ...]; meta: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class Plan:
    kind: str; units: tuple[Unit, ...]; codebook_id: str; pin: ModelPin; budget: Budget; worker: str
    checker_pin: ModelPin | None = None; sample_pct: int = 10


@dataclass(frozen=True)
class RecordResult:
    case_id: int; record: dict; gate_status: str; dropped_quotes: int; nulled_fields: tuple[str, ...]


@dataclass(frozen=True)
class UnitResult:
    # `retried` marks a unit whose first response would not parse and that only came back
    # after the split retry. Its status is still "ok" - the records are as good as any
    # other - but 3B's review queue wants to know which cases needed a second ask (m5).
    unit_id: str; status: str; records: tuple[RecordResult, ...]; response: Response | None; cache_hit: bool; error: str = ""
    checker: str | None = None; checker_response: Response | None = None; retried: bool = False


@dataclass(frozen=True)
class Disagreement:
    unit_id: str; case_id: int; field: str; reader_value: object; checker_value: object


@dataclass
class ReadingOutcome:
    plan: Plan; units: list; disagreements: list; spend_usd: float; input_tokens: int; output_tokens: int
    wall_seconds: float; stop: StopReason; manifest: dict; resume_command: str
    @property
    def records(self) -> list[dict]:
        return [r.record for u in self.units for r in u.records]
    @property
    def failed_units(self) -> list[str]:
        return [u.unit_id for u in self.units if u.status != "ok"]
