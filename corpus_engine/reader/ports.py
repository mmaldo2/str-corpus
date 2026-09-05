from __future__ import annotations
from typing import Protocol, Sequence
from corpus_engine.reader.model import CaseText, Request, Response


class Provider(Protocol):
    name: str
    def complete(self, req: Request) -> Response: ...


class CaseSource(Protocol):
    def fetch(self, case_ids: Sequence[int]) -> list[CaseText]: ...
