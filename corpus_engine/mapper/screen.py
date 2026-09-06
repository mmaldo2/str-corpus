"""The optional relevance screen (spec section 7, D10). OFF by default; not run in slice 2.

When a cell stops on `yield_floor` with cap remaining, the cheap fallback reader
(`reader.fallback_model`, google/gemini-3.7-flash through OpenRouter) reads the remainder under
the SAME codebook and only its `relevant` answer is consumed. Cases it calls relevant are
re-batched at `SCREEN_BATCH_SIZE` into `pinned_units()`, which the PINNED reader - the same
subscription model the map itself uses - reads in full, in the same cell, before the runner
moves on. Only the pinned reader's records are ever admitted toward yield or admission: the
measurement found the fallback's relevance call unstable across repeat reads
(reports/reader-measurement-v2.md, handoff item 7c), so its verdict is trusted only enough to
narrow the remainder, never to supply a record itself.

Controller ruling R2: the screen never re-derives whether a cell has stopped. `MapRunner`
computes the `CellStop` from its own `CellProgress` and hands it in (`maybe_run(cell, stop, *,
batch_source, progress)`); the screen triggers only when that stop is `yield_floor` with
batches still under the cap - a cell that reached its cap has no remainder to screen, so
`cap_reached` never triggers this at all.

R3: `to_json()` always carries the same five keys the runner's off block does (state, enabled,
max_usd, screened_units, hits), plus `spend_usd` and `hit_case_ids` once the screen is on.
`Screen.off()` is the runner's default in place of the old `NullScreen` - same reading (`None`
from `maybe_run` means "the cell's block is unchanged"), same shape from `to_json()`.

The dollar ceiling is checked BEFORE every paid request (tools/measure_reader.py's rule, kept
here): a request is refused while the ceiling is already reached, rather than issued and then
regretted. That check always reads driver-tracked spend (`self.spend_usd`); it never calls
OpenRouter's `/credits` endpoint itself. Instead, `_reconcile` trues `self.spend_usd` up
against `/credits` once per triggered run (post-hoc, mirroring `tools/measure_reader.py`'s
`reconcile`/`settle` - called once a run finishes, not before every request in it) - the
2026-09-05 measurement found the two disagree in both directions. A failed probe (network
blip, timeout) is caught and logged; the screen degrades to driver-tracked spend rather than
letting an unhandled exception out of `maybe_run` and killing the cell (review finding 1)."""
from __future__ import annotations
from typing import Mapping, Sequence

from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.yield_stop import CellProgress, CellStop
from corpus_engine.reader.driver import plan_batch_extraction
from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.schema import record_schema

SCREEN_MAX_USD = 5.0
SCREEN_BATCH_SIZE = 18


class ScreenBudgetExceeded(Exception):
    """The screen's own ceiling. Raised before a request, never after one."""


def fallback_pin(dom) -> ModelPin:
    """The fallback model's pin, straight off `domain.yaml`'s `reader.fallback_model` - never
    a made-up default, so a domain with no fallback configured fails loudly instead of
    screening on whatever the pinned reader happens to be."""
    f = dict(dom.reader.fallback_model or {})
    return ModelPin(f["model_id"], f["family"], f.get("provider_name"), f.get("precision"),
                    f.get("extra") or {})


def remaining_batches(cell: Cell, progress: CellProgress) -> tuple[str, ...]:
    """What the cap allowed and the cell did not read, in rank order."""
    return cell.capped_ids[progress.attempted_batches:]


def rebatch(case_ids: Sequence[int], batches: Mapping[str, dict], *, era: str, jurisdiction: str,
            prefix: str, size: int = SCREEN_BATCH_SIZE) -> list[dict]:
    """The screen's hits, packed into units the pinned reader can read. Each case row is
    carried over from the batch it was screened in, so retrieval provenance (the signals the
    codebook renders) survives the re-batching."""
    by_id: dict[int, dict] = {}
    for b in batches.values():
        for c in b.get("cases") or []:
            by_id[int(c["case_id"])] = c
    rows = [by_id[int(cid)] for cid in case_ids if int(cid) in by_id]
    out = []
    for i in range(0, len(rows), size):
        out.append({"batch_id": f"{prefix}-{i // size + 1:03d}", "ranker_id": "screen",
                    "era_partition": era, "jurisdiction": jurisdiction,
                    "cases": rows[i:i + size]})
    return out


class Screen:
    def __init__(self, reader_factory, *, fallback_pin, codebook, max_usd: float = SCREEN_MAX_USD,
                 log=print, spend_probe=None):
        self.reader_factory, self.pin, self.codebook = reader_factory, fallback_pin, codebook
        self.max_usd, self.log = float(max_usd), log
        self.spend_probe = spend_probe
        self.spend_usd = 0.0
        self.units = 0
        self.hits = 0
        self.hit_case_ids: list[int] = []
        # This cell's hits, rebatched for the pinned reader (R10) - see `pinned_units()`.
        # Reset at the start of every `maybe_run`: a pending set belongs to the cell that
        # produced it, never to whatever cell the runner reads next.
        self._pinned: list[dict] = []

    @classmethod
    def off(cls) -> "Screen":
        """The screen a run with no `--screen` builds (R2/R3). `MapRunner` defaults to this
        in place of the old `NullScreen`, so a consumer never has to branch on whether the
        screen exists - only what its block says. Its `maybe_run` returns `None`, the same
        reading `NullScreen` gave the runner, and its `to_json()` is the runner's `SCREEN_OFF`
        shape verbatim."""
        return cls(None, fallback_pin=None, codebook=None, max_usd=0.0, log=lambda *_: None)

    @classmethod
    def from_domain(cls, dom, *, cache, cases, codebook, max_usd=SCREEN_MAX_USD, log=print):
        """Wire the screen to the fallback model through OpenRouter. Only a caller that passes
        `--screen` reaches this; slice 2 never does - `tools/map_reader.py` logs that the flag
        is accepted but constructs no screen of any kind - so nothing here runs this slice."""
        import os
        from corpus_engine.reader.driver import Reader
        from corpus_engine.reader.providers.factory import credits_remaining
        from corpus_engine.reader.providers.openrouter import OpenRouterProvider
        from corpus_engine.textnorm_version import NORM_VERSION
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ScreenBudgetExceeded("--screen needs OPENROUTER_API_KEY; the fallback reader "
                                       "is an OpenRouter model and the subscription cannot serve it")
        prov = OpenRouterProvider(key)
        pin = fallback_pin(dom)
        before = credits_remaining(prov)

        def factory():
            return Reader(prov, cases, cache=cache, log=log, domain=dom,
                          store_norm_version=f"v{NORM_VERSION}")

        def probe() -> float:
            # Real spend since this screen started, off OpenRouter's own ledger - not the
            # driver-tracked total, which the measurement found can disagree with what was
            # actually charged in both directions (tools/measure_reader.py's `reconcile`).
            return before - credits_remaining(prov)

        return cls(factory, fallback_pin=pin, codebook=codebook, max_usd=max_usd, log=log,
                   spend_probe=probe)

    def _reconcile(self) -> None:
        """True `self.spend_usd` up against OpenRouter's own ledger once per triggered run
        (called once, post-hoc, from the end of `maybe_run` - never from `_check_budget`,
        so a probe never runs per request). A failed probe is logged and left as
        driver-tracked spend rather than raised (review finding 1): the measurement tool's
        `reconcile` degrades the same way. A no-op when this screen has no probe wired
        (`Screen.off()`, or a caller that built one without `spend_probe`)."""
        if self.spend_probe is None:
            return
        try:
            real = self.spend_probe()
        except Exception as exc:                                     # noqa: BLE001
            self.log(f"screen: credits probe failed ({exc!r}); "
                     f"falling back to driver-tracked spend ${self.spend_usd:.4f}")
            return
        self.log(f"screen: real spend ${real:.4f} (driver-tracked ${self.spend_usd:.4f})")
        self.spend_usd = real

    def _check_budget(self) -> None:
        """The measurement tool's rule, kept: a request is refused while the ceiling is
        already reached, rather than issued and then regretted - checked against whatever
        `self.spend_usd` currently holds (driver-tracked, periodically trued up by
        `_reconcile`), never against a fresh probe (review finding 2)."""
        if self.spend_usd >= self.max_usd:
            raise ScreenBudgetExceeded(f"screen spend {self.spend_usd:.2f} >= ceiling {self.max_usd:.2f}")

    def to_json(self) -> dict:
        if self.reader_factory is None:
            return {"state": "off", "enabled": False, "max_usd": 0.0,
                    "screened_units": 0, "hits": 0}
        return {"state": "on", "enabled": True, "max_usd": self.max_usd,
                "screened_units": self.units, "hits": self.hits,
                "spend_usd": round(self.spend_usd, 4), "hit_case_ids": list(self.hit_case_ids)}

    def pinned_units(self) -> list[dict]:
        """The current cell's hits, re-batched at `SCREEN_BATCH_SIZE` and ready for the PINNED
        reader to read - through the same `plan_batch_extraction` + `Reader` the map itself
        uses - in this cell, before the runner moves on (R10, D10). Empty until a `maybe_run`
        call actually triggers and finds hits; replaced (never accumulated) by the next one."""
        return list(self._pinned)

    def maybe_run(self, cell: Cell, stop: CellStop | None, *, batch_source,
                 progress: CellProgress) -> dict | None:
        """D10's trigger, then the screen. `stop` is the runner's own `CellStop` (R2): this
        method never calls `progress.should_stop()` itself, so the trigger cannot drift from
        the yield module's rule. Returns `None` when the screen is off (`Screen.off()`), the
        same reading `NullScreen` gave the runner; otherwise always a dict for the cell's
        manifest block."""
        self._pinned = []
        if self.reader_factory is None:
            return None
        rest = remaining_batches(cell, progress)
        if stop is None or stop.kind != "yield_floor" or not rest:
            return {"state": "not_triggered", "screened_batches": 0, "screened_cases": 0,
                    "hits": 0, "hit_case_ids": [], "rebatched": [], "units": 0, "spend_usd": 0.0}
        doc = {"state": "ran", "screened_batches": 0, "screened_cases": 0, "hits": 0,
               "hit_case_ids": [], "rebatched": [], "units": 0, "spend_usd": 0.0}
        seen: dict[str, dict] = {}
        hits: list[int] = []
        for batch_id in rest:
            try:
                self._check_budget()
            except ScreenBudgetExceeded as exc:
                self.log(f"{cell.key}: screen stopped at its ceiling ({exc})")
                doc["state"] = "ceiling"
                break
            batch = batch_source.get(batch_id)
            seen[batch_id] = batch
            plan = plan_batch_extraction(
                [batch], self.codebook.id if self.codebook else "", self.pin,
                Budget(max_usd=max(self.max_usd - self.spend_usd, 0.0)), worker="reader",
                json_schema=(record_schema(self.codebook) if self.codebook else None))
            out = self.reader_factory().read(plan)
            self.spend_usd += out.spend_usd
            paid = sum(1 for u in out.units if not u.cache_hit and u.response is not None)
            self.units += paid
            doc["units"] += paid
            doc["screened_batches"] += 1
            doc["screened_cases"] += len(batch["cases"])
            # ONLY `relevant` is consumed. Everything else the fallback said is discarded -
            # only the pinned reader's records are ever admitted toward yield/admission (D10).
            hits += [int(r["case_id"]) for r in out.records if r.get("relevant") is True]
        self._reconcile()          # post-hoc, once per triggered run (review finding 2)
        self.hits += len(hits)
        self.hit_case_ids += hits
        doc["hits"] = len(hits)
        doc["hit_case_ids"] = hits
        doc["spend_usd"] = round(self.spend_usd, 4)
        self._pinned = rebatch(hits, seen, era=cell.era, jurisdiction=cell.jurisdiction,
                               prefix=f"screen-{cell.era}-{cell.jurisdiction}")
        doc["rebatched"] = [b["batch_id"] for b in self._pinned]
        return doc
