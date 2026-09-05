from __future__ import annotations
from typing import Callable, Sequence
from corpus_engine.reader.model import Request, Response


class ScriptedProvider:
    name = "scripted"
    def __init__(self, responses: Sequence[str] | Callable[[Request], str], *, cost_per_call: float = 0.001):
        self._r = responses; self.calls = 0; self.cost = cost_per_call
    def complete(self, req: Request) -> Response:
        if callable(self._r):
            text = self._r(req)
        else:
            # `responses[min(calls, len - 1)]` silently repeated the last canned response, so
            # a test that made more calls than it scripted still passed (m9). Test double:
            # raising here is meant to fail the test, not to be handled.
            assert self.calls < len(self._r), (
                f"ScriptedProvider exhausted: call {self.calls + 1} with {len(self._r)} responses scripted")
            text = self._r[self.calls]
        self.calls += 1
        return Response(text, len(req.user) // 4, len(text) // 4, self.cost, {"provider": "scripted"}, "stop")
