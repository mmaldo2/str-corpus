from __future__ import annotations
from typing import Callable, Sequence
from corpus_engine.reader.model import Request, Response


class ScriptedProvider:
    name = "scripted"
    def __init__(self, responses: Sequence[str] | Callable[[Request], str], *, cost_per_call: float = 0.001):
        self._r = responses; self.calls = 0; self.cost = cost_per_call
    def complete(self, req: Request) -> Response:
        text = self._r(req) if callable(self._r) else self._r[min(self.calls, len(self._r) - 1)]
        self.calls += 1
        return Response(text, len(req.user) // 4, len(text) // 4, self.cost, {"provider": "scripted"}, "stop")
