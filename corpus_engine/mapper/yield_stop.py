"""The per-cell stop rule (spec section 5, D2).

Pure state machine: batches go in, a stop reason comes out. No reader, no clock, no files, so
the rule can be argued about and tested without buying anything.

Named `yield_stop` rather than the spec's `yield` because `yield` is a Python keyword and a
module by that name cannot be imported at all."""
from __future__ import annotations
from dataclasses import dataclass

WINDOW = 3          # completed batches the rule looks back over (D2)
THRESHOLD = 2       # relevant accepted records across that window, at or below which it stops


@dataclass(frozen=True)
class CellStop:
    """Why a cell stopped. `kind` is "yield_floor" or "cap_reached".

    Not called `StopReason`: `corpus_engine.reader.model.StopReason` already carries that name
    for the driver's budget stops, and runner.py handles both in the same function."""
    kind: str
    detail: str = ""

    def to_json(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


class CellProgress:
    def __init__(self, cell_key: str, cap_batches: int):
        self.cell_key = cell_key
        self.cap_batches = int(cap_batches)
        self._series: list[dict] = []       # completed batches only, in read order
        self._failed: list[str] = []

    def add(self, batch_id: str, relevant_accepted: int, completed: bool) -> None:
        """One batch's result. `completed` is the driver's verdict: a unit whose status is
        "ok", or "partial_parse" with at least one accepted record. A failed unit is recorded
        so the manifest can list it and the next invocation can re-read it, but it never
        enters the window - an outage is not evidence that a cell has stopped paying - and it
        does not consume the cap."""
        if completed:
            self._series.append({"batch_id": batch_id, "relevant_accepted": int(relevant_accepted)})
        else:
            self._failed.append(batch_id)

    @property
    def series(self) -> tuple[dict, ...]:
        return tuple(self._series)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(self._failed)

    @property
    def completed_batches(self) -> int:
        return len(self._series)

    @property
    def attempted_batches(self) -> int:
        return len(self._series) + len(self._failed)

    @property
    def relevant_accepted(self) -> int:
        return sum(e["relevant_accepted"] for e in self._series)

    def should_stop(self, *, window: int = WINDOW, threshold: int = THRESHOLD) -> CellStop | None:
        """The cap is checked FIRST. Both rules can be true at once, and the screen (section 7)
        triggers on `yield_floor` with cap remaining - a cell that reached its cap has no
        remainder to screen, so reporting the yield floor there would offer the screen a
        finished cell."""
        if self.completed_batches >= self.cap_batches:
            return CellStop("cap_reached", f"{self.completed_batches} of {self.cap_batches} batches")
        if len(self._series) >= window:
            recent = self._series[-window:]
            got = sum(e["relevant_accepted"] for e in recent)
            if got <= threshold:
                ids = ", ".join(e["batch_id"] for e in recent)
                return CellStop("yield_floor",
                                f"last {window} completed batches ({ids}) yielded {got} "
                                f"relevant accepted records, at or under {threshold}")
        return None

    def to_json(self, *, window: int = WINDOW, threshold: int = THRESHOLD) -> dict:
        stop = self.should_stop(window=window, threshold=threshold)
        return {"yield_series": [dict(e) for e in self._series],
                "failed_units": list(self._failed),
                "relevant_accepted": self.relevant_accepted,
                "batches_completed": self.completed_batches,
                "batches_attempted": self.attempted_batches,
                "stop": stop.to_json() if stop else None}
