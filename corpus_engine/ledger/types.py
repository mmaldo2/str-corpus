from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Literal

Op = Literal["admit", "set", "append", "drop_quote", "migrate"]


class _Unset:
    def __repr__(self): return "UNSET"
UNSET = _Unset()


class LedgerError(Exception): ...
class UnknownCase(LedgerError): ...
class DuplicateRecord(LedgerError): ...
class MissingBasis(LedgerError): ...
class UnknownField(LedgerError): ...
class NotTraditionEvidence(LedgerError): ...
class StaleSnapshot(LedgerError): ...


@dataclass(frozen=True)
class Basis:
    reviewer: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    run_id: str | None = None
    rule_id: str | None = None

    def kind(self) -> Literal["human", "reader", "rule", "none"]:
        if self.reviewer:
            return "human"
        if self.model:
            return "reader"
        if self.rule_id:
            return "rule"
        return "none"

    def can_judge(self) -> bool:
        return bool(self.reviewer) or bool(self.model and self.prompt_version and self.run_id)

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Patch:
    case_id: int
    op: Op
    field: str
    new: Any
    why: str
    basis: Basis
    cycle: str | None = None
    seq: int = 0
    at: str = ""
    patch_id: str = ""
    old: Any = UNSET

    def to_json(self) -> dict:
        d = {"seq": self.seq, "patch_id": self.patch_id, "at": self.at, "case_id": self.case_id,
             "cycle": self.cycle, "op": self.op, "field": self.field, "new": self.new,
             "why": self.why, "basis": self.basis.to_json()}
        if self.old is not UNSET:
            d["old"] = self.old
        return d

    @staticmethod
    def from_json(d: dict) -> "Patch":
        return Patch(case_id=d["case_id"], op=d["op"], field=d["field"], new=d["new"], why=d["why"],
                     basis=Basis(**d.get("basis", {})), cycle=d.get("cycle"), seq=d.get("seq", 0),
                     at=d.get("at", ""), patch_id=d.get("patch_id", ""),
                     old=d["old"] if "old" in d else UNSET)


@dataclass(frozen=True)
class TierCount:
    human_reviewed: int
    machine_only: int

    def as_claim(self, noun: str) -> str:
        return (f"{self.human_reviewed + self.machine_only} {noun} "
                f"({self.human_reviewed} human-reviewed, {self.machine_only} machine-only; lower bound)")

    def __int__(self):
        raise TypeError("two-tier counts are never blended (ADR-0002)")

    def __add__(self, other):
        raise TypeError("two-tier counts are never blended (ADR-0002)")


@dataclass(frozen=True)
class SeedSet:
    case_ids: tuple[int, ...]
    hash: str
