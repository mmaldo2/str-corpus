"""The map runner (spec section 6, D6, D9).

One `plan_batch_extraction` per batch, through the same `Reader` the measurement used, so the
gate, the cache, the split retry, the checker sample and the budget stop all behave exactly as
they were measured. The runner adds only what is above one read: the order of the cells, when
a cell has stopped paying, the per-PROCESS ceilings, and the manifest.

Two things it deliberately does NOT do. It never writes the ledger - admission is a separate
tool over the same cache (D9), so a map can be re-read and re-admitted independently. And it
never treats the extraction files as authoritative: they are a derived convenience, gitignored,
and Task 7 re-parses and re-gates from the response cache instead.

Unit accounting (R11). `--max-units` is a ceiling on READER requests only, and it counts every
reader request the process made - a split half, and a request that raised before it returned,
are units that were spent. Checker (Codex) requests are counted separately as `checker_units`
and are never capped by `--max-units`: sampling the reader at 10% is part of what a map IS
(D5), so cutting the checker off to buy one more batch would be trading the evidence for the
volume. Both counters come from a wrapper around the provider's `complete`, not from the
`UnitResult`s: a cached split half is invisible in the outcome, and a request that raised
leaves no `Response` at all.

What `--max-units` actually guarantees (task-5-review finding 2). The ceiling is checked
BETWEEN batches, and one read can buy up to three reader requests (the unit plus two split
halves). So a batch begun with the last unit left, whose response will not parse, spends two
requests past the ceiling - `max_units + DRIVER_UNIT_HEADROOM - 1` reader requests worst case,
once, because the loop breaks on the next iteration. It is a ceiling with a bounded, one-shot
overrun, not an exact count, and it is written that way in `--help` and in the manifest
(`max_units_note`). The headroom is not shrinkable to zero: the driver counts reader and
checker requests against one budget, so an exact remainder would cut a sampled unit's checker
off for arithmetic reasons (driver N2).

Lost cases (final-review I3). A unit can COMPLETE and still not answer for every case in
its batch: `cycle-004-shard-01-batch-146` came back with 9 of its 18 cases missing after the
split retry, and because the unit completed it is not a failed unit, a resume replays it from
cache, and nothing ever re-asks for those 9. They are recorded per unit as `cases_lost`,
summed into the cell and the totals, and `--retry-lost` re-plans them as fresh units - so a
partial parse costs a re-ask, not nine cases silently missing from the corpus and from the
labelled negatives the next cycle's ranker trains on. A failed unit is a different thing and
stays a different number: it did not complete, it consumed no cell walk, and a resume re-reads
it. `failed_units` counts units that did not complete, `failures` lists units whose status was
not "ok", and `cases_lost` counts cases a unit that DID complete never answered for.

Merging (task-5-review finding 3). `runs/<run-id>/map-manifest.json` is the tracked record of
what a subscription window bought, and a `--cells` sub-run or a dry run reads a strict subset
of it. Every run therefore MERGES into what is already on disk (`merge_manifest`) rather than
replacing it, on the pattern `tools/measure_reader.py` established after a `--only` re-run
silently dropped four candidates from the measurement (I8)."""
from __future__ import annotations
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.screen import Screen
from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW, CellProgress
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.driver import ENGINE_VERSION, plan_batch_extraction, schema_for
from corpus_engine.reader.model import Budget, ModelPin, Request, effort_of
from corpus_engine.reader.parse import split_unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.schema import record_schema, schema_sha

MAP_RESUME_TOOL = "tools\\map_reader.py"
MANIFEST_SCHEMA = "map-manifest-v1"
DEFAULT_MAX_WALL_SECONDS = 21600            # 6 h, the same window the measurement used
UNIT_MARGIN_PCT = 10                        # headroom for split halves and checker units
# The driver's stop kinds that mean "this process is done", as opposed to "this unit failed".
PROCESS_STOPS = ("budget:units", "budget:wall", "budget:usd")
# Headroom handed to the driver's own unit budget on top of the reader units still allowed.
# The runner's cap is enforced BETWEEN batches (one batch per read), so the driver's budget is
# only a runaway guard; it has to be loose enough that a unit's split halves and its checker
# call are never cut off half way, which would record a checker as `failed:budget` for no
# reason other than arithmetic (driver N2). See the module docstring for what this costs.
DRIVER_UNIT_HEADROOM = 3
# Cases per retry unit. The same 18 the shard packed its batches at (domain.yaml
# `sharding.batch_size`): a retry is a fresh read of the same size, not a special small one.
RETRY_UNIT_SIZE = 18
MAX_UNITS_NOTE = (
    "--max-units is a ceiling on READER requests, checked between batches. One read can buy "
    "the unit plus two split halves, so a run can exceed it by at most DRIVER_UNIT_HEADROOM-1 "
    "(2) requests, once, when the last batch it begins will not parse. Checker requests are "
    "counted separately as checker_units and are never capped by it.")
# The `screen` block a run with no screen writes. `corpus_engine.mapper.screen.Screen.off()`
# (Task 6) is the runner's default, and its `to_json()` reproduces this shape verbatim, so a
# consumer never has to branch on whether the screen exists - only what its block says.
SCREEN_OFF = {"state": "off", "enabled": False, "max_usd": 0.0, "screened_units": 0, "hits": 0}
CELL_SCREEN_OFF = {"state": "off"}
# Totals that count what was BOUGHT rather than what the map now holds, and that therefore
# accumulate across the processes that wrote this manifest instead of being recomputed from the
# cells. Summing is right, and is not double counting: a resume replays its units from the
# response cache and so adds exactly zero to every one of these, while two `--cells` runs over
# different cells each add what they really spent. `process` records the same figures for the
# one process that wrote this document.
# NOT `screen_pinned_units`: that counts pinned batches WALKED, and a resume re-runs the screen,
# re-pins the same units and buys none of them again (re-review B). It is derived from the cells
# like every other holding-count; what this process walked is in the `process` block.
CUMULATIVE_TOTALS = ("units", "checker_units", "input_tokens", "output_tokens", "spend_usd",
                     "unpriced_requests", "wall_seconds")


@dataclass(frozen=True)
class RunnerCaps:
    max_units: int
    max_wall_seconds: float


@dataclass
class MapOutcome:
    cells: list
    units: int
    wall_seconds: float
    stop: str
    manifest: dict
    manifest_path: Path
    resume_command: str


class _CountingProvider:
    """Counts `complete` calls, including the ones that raise (R11).

    Wrapping the provider is the only place every paid request is visible: a cache hit never
    reaches it, a split half does, and a request that raised increments before the call so the
    unit it cost is not lost. Everything else - `name`, `is_available`, `probe_model`,
    `version` - is forwarded, and forwarded by absence too: `hasattr(wrapper, "probe_model")`
    is False when the wrapped provider has none, which is what the driver's preflight asks."""

    def __init__(self, inner, counts: dict, key: str):
        self._inner, self._counts, self._key = inner, counts, key

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def complete(self, req):
        self._counts[self._key] = self._counts.get(self._key, 0) + 1
        return self._inner.complete(req)


def default_max_units(cells: Sequence[Cell]) -> int:
    """Every batch the caps allow, plus a tenth. The margin is not generosity: a unit whose
    response will not parse buys two split halves, and a sampled unit buys a checker call."""
    return math.ceil(sum(c.cap_batches for c in cells) * (1 + UNIT_MARGIN_PCT / 100))


def relevant_accepted(unit) -> int:
    """Accepted records this unit contributed that the reader called relevant. `accepted` is
    the measurement's definition (spec section 2 as amended): parsed, gated, and back with a
    decided `relevant` - status "ok" or "partial", never "missing"."""
    return sum(1 for r in unit.records
               if r.record.get("extraction_status") in ("ok", "partial")
               and r.record.get("relevant") is True)


def irrelevant_accepted(unit) -> int:
    return sum(1 for r in unit.records
               if r.record.get("extraction_status") in ("ok", "partial")
               and r.record.get("relevant") is False)


def accepted_records(unit) -> int:
    """Cases this unit actually came back with an answer for. A failed unit contributes one
    `_missing_stub` per case, and counting those as cases read inflated a failed batch into a
    full one in the number Task 8's report quotes (review finding 6)."""
    return sum(1 for r in unit.records
               if r.record.get("extraction_status") in ("ok", "partial"))


def answered_case_ids(unit) -> list[int]:
    """The cases this unit came back with a record for at all.

    Wider than `accepted_records`, deliberately: a record the gate emptied is
    `extraction-invalid` rather than accepted, but it exists, it is admitted, and re-asking
    for it would buy a case the corpus already holds. Only a `missing` stub means the response
    never carried that case."""
    return sorted(r.case_id for r in unit.records
                  if r.record.get("extraction_status") != "missing")


def lost_case_ids(unit) -> list[int]:
    """The cases a COMPLETED unit dropped (I3).

    A unit that parsed, was folded into the cell and counted toward its yield, but that simply
    had no record for these ids - the driver's own `missing` stubs. They are not failures: the
    unit's status can be "ok", `failed_units` does not count it, and a resume replays it from
    cache, so nothing re-asks for them unless `--retry-lost` does.

    A unit that did NOT complete contributes none: every one of its cases is missing, the batch
    is in `failed_units`, and re-reading the batch is what recovers it."""
    if not unit_completed(unit):
        return []
    answered = set(answered_case_ids(unit))
    return sorted(r.case_id for r in unit.records if r.case_id not in answered)


def unit_completed(unit) -> bool:
    """Whether this batch counts toward the yield window (spec section 5): status ok, or
    partial with at least one accepted record. A failed or wholly unparsed unit does not."""
    if unit.status == "ok":
        return True
    if unit.status == "partial_parse":
        return any(r.record.get("extraction_status") in ("ok", "partial") for r in unit.records)
    return False


def unit_keys(unit: Mapping) -> list:
    """Every cache key a unit row records, in whatever shape recorded it. A row written before
    the split-half fix carries `cache_key: str`; one written since carries `cache_keys: list`.
    Reading both means an older manifest is merged forward rather than refused, and it is why
    `derived` cannot raise on a row it did not write (re-review A)."""
    keys = unit.get("cache_keys")
    if keys is None:
        keys = unit.get("cache_key")
    if isinstance(keys, str):
        return [keys] if keys else []
    return [k for k in (keys or []) if k]


def derived(units: Sequence[Mapping]) -> dict:
    """A cell's aggregates, computed from its unit rows and never accumulated beside them, so
    `checker_sampled` can no more disagree with the unit that says it was sampled than a sum
    can disagree with its own addends. That is also what makes a merge exact: a `--retry-lost`
    run adds one row to a cell of twenty-one and the cell's counts follow it, where an
    accumulator carried on the cell document would have been taken whole from whichever process
    walked further and would have kept the pre-retry figure (I3).

    Every field is read with `.get`: this runs over rows from a manifest ON DISK as well as
    over this process's own, and it runs inside `run()`'s `finally`, where a `KeyError` would
    cost the write and mask whatever exception was already propagating."""
    rows = [u for u in units if u.get("unit_id")]
    lost = {c for u in rows for c in (u.get("cases_lost") or [])}
    # A retry unit records the ids it ANSWERED, so a case recovered by a later unit stops being
    # a lost case of the cell without anything having to rewrite the row that lost it.
    answered = {c for u in rows for c in (u.get("cases_answered") or [])}
    return {
        "cases_lost": sorted(lost - answered),
        "records": sum(u.get("records") or 0 for u in rows),
        "cases_read": sum(u.get("cases_read") or 0 for u in rows),
        "relevant_accepted": sum(u.get("relevant_accepted") or 0 for u in rows),
        "irrelevant_accepted": sum(u.get("irrelevant_accepted") or 0 for u in rows),
        "units_retried_after_split": sum(1 for u in rows if u.get("retried")),
        "failures": [{"unit_id": u["unit_id"], "status": u.get("status"),
                      "error": u.get("error") or ""} for u in rows if u.get("status") != "ok"],
        "cache_keys": {u["unit_id"]: unit_keys(u) for u in rows if unit_keys(u)},
        "checker_sampled": [u["unit_id"] for u in rows
                            if (u.get("checker") or {}).get("sampled")],
        "checker_status": {u["unit_id"]: (u.get("checker") or {}).get("status", "none")
                           for u in rows if (u.get("checker") or {}).get("sampled")},
        "checker_disagreements": [d for u in rows
                                  for d in ((u.get("checker") or {}).get("disagreements") or [])],
        "checker_units": sum(1 for u in rows if (u.get("checker") or {}).get("sampled")),
    }


def merge_cell(prior: Mapping, fresh: Mapping) -> dict:
    """One cell, read by two processes. The unit rows are unioned (the fresher row wins for a
    unit both read), and the WALK - `yield_series`, `batches_*`, `stop`, the counters - is
    taken whole from whichever process got further through the cell, because those fields
    describe one traversal and mixing two of them describes neither.

    A resume re-walks a cell from cache for free, so a `--cells` re-run is the more complete
    walk and wins; a `--dry-run-batches 1` over a cell already fully read is not, so the full
    walk survives it and only the dry run's (identical, cached) unit rows are folded in."""
    base = fresh if fresh.get("batches_attempted", 0) >= prior.get("batches_attempted", 0) else prior
    rows = {u["unit_id"]: u for u in (prior.get("units") or []) if u.get("unit_id")}
    rows.update({u["unit_id"]: u for u in (fresh.get("units") or []) if u.get("unit_id")})
    order = [u["unit_id"] for u in (base.get("units") or []) if u.get("unit_id")]
    order += [uid for uid in rows if uid not in set(order)]
    doc = dict(base)
    doc["units"] = [rows[uid] for uid in order]
    doc.update(derived(doc["units"]))
    return doc


def merge_manifest(prior: Mapping, fresh: Mapping) -> dict:
    """Fold this process's map into the manifest already on disk (review finding 3).

    Whole-manifest fields belong to the fresher process, as in `tools/measure_reader.py`.
    `cells` merges cell by cell through `merge_cell`; `cell_order` keeps the order the prior
    manifest recorded and appends whatever cells this process added, so a `--cells` run cannot
    re-order the map. The purchase counters in `CUMULATIVE_TOTALS` accumulate - see that
    constant for why that is not double counting - and every other total is recomputed from the
    merged cells by the caller."""
    merged = {**prior, **fresh}
    # Every prior cell is re-derived from its own unit rows, not copied through: a cell this
    # process did not read may have been written in an older row shape (`unit_keys`), and a
    # merged manifest that mixed two shapes would hand admission keys it cannot see.
    cells = {key: {**doc, **derived((doc or {}).get("units") or [])}
             for key, doc in (prior.get("cells") or {}).items()}
    for key, doc in (fresh.get("cells") or {}).items():
        cells[key] = merge_cell(cells[key], doc) if key in cells else doc
    merged["cells"] = cells
    order = [k for k in (prior.get("cell_order") or []) if k in cells]
    order += [k for k in (fresh.get("cell_order") or []) if k not in set(order)]
    merged["cell_order"] = order + [k for k in cells if k not in set(order)]
    pt, ft = prior.get("totals") or {}, fresh.get("totals") or {}
    merged["totals"] = {**ft, **{k: round((pt.get(k) or 0) + (ft.get(k) or 0), 6)
                                 for k in CUMULATIVE_TOTALS if k in pt or k in ft}}
    return merged


def lost_cases(manifest: Mapping) -> dict[str, list[int]]:
    """Cell key -> the cases completed units dropped and no later unit has answered (I3).

    Re-derived from the unit rows through `derived`, so it is right for a manifest written
    before this field existed and for one that has already been retried once."""
    cells = manifest.get("cells") or {}
    order = [k for k in (manifest.get("cell_order") or []) if k in cells]
    order += [k for k in cells if k not in set(order)]
    out = {}
    for key in order:
        ids = derived((cells.get(key) or {}).get("units") or [])["cases_lost"]
        if ids:
            out[key] = ids
    return out


def retry_file_name(batch_id: str) -> str:
    """The file a retry unit is written as: `<run>-retry-004` -> `retry-004.json`, which
    `cells.RETRY_GLOB` serves and `cells.load_batches` ignores."""
    return f"retry-{batch_id.rsplit('-retry-', 1)[-1]}.json"


def plan_retry_units(manifest: Mapping, batch_source, *, size: int = RETRY_UNIT_SIZE,
                     run_id: str = "", lost: Mapping[str, Sequence[int]] | None = None
                     ) -> list[dict]:
    """Fresh batches over every lost case in the manifest, at most `size` cases each (I3).

    `lost` defaults to `lost_cases(manifest)` - what the unit rows themselves record. A caller
    holding the response cache can pass a better map: a manifest written before `cases_lost`
    existed records how many cases a unit dropped (`status_counts.missing`) but not which, and
    `admit.unanswered_cases` recovers the ids exactly, from the same cached responses admission
    re-derives every record from.

    The cases are copied VERBATIM out of the batch files they came from - same case ids, same
    signals, same rank scores - so the retry asks exactly what the first read asked, under a
    new batch id and therefore a new cache key (a replay of the old id would just hand back
    the response that lost them). Cases are grouped by CELL rather than packed across the
    manifest, because a unit's records are folded into one cell and a mixed unit would belong
    to neither.

    A lost case whose batch file is gone cannot be re-planned and is left out; the caller
    compares the number planned against the number lost."""
    run_id = run_id or str(manifest.get("run_id") or "")
    cells = manifest.get("cells") or {}
    taken = set(batch_source.ids())
    out: list[dict] = []
    n = 0
    for key, ids in (lost_cases(manifest) if lost is None else lost).items():
        doc = cells.get(key) or {}
        wanted = {int(c) for c in ids}
        by_case: dict[int, dict] = {}
        unit_of: dict[int, str] = {}
        ranker = ""
        for row in doc.get("units") or []:
            unit_id = row.get("unit_id")
            if not unit_id or unit_id not in batch_source:
                continue
            batch = batch_source.get(unit_id)
            for case in batch.get("cases") or []:
                cid = int(case["case_id"])
                if cid in wanted and cid not in by_case:
                    by_case[cid], unit_of[cid] = case, unit_id
                    ranker = ranker or (batch.get("ranker_id") or "")
        cases = [by_case[c] for c in ids if c in by_case]
        for i in range(0, len(cases), size):
            chunk = cases[i:i + size]
            n += 1
            bid = f"{run_id}-retry-{n:03d}"
            while bid in taken:
                n += 1
                bid = f"{run_id}-retry-{n:03d}"
            taken.add(bid)
            out.append({"batch_id": bid, "ranker_id": ranker,
                        "era_partition": doc.get("era"), "jurisdiction": doc.get("jurisdiction"),
                        "retry_of": sorted({unit_of[int(c["case_id"])] for c in chunk}),
                        "cases": chunk})
    return out


def _quote(arg: str) -> str:
    return f'"{arg}"' if (not arg or any(c in arg for c in ' \t|"')) else arg


class MapRunner:
    def __init__(self, reader_factory: Callable[[], object], cells: Sequence[Cell], *,
                 batch_source, cache: ResponseCache, manifest_path: Path, caps: RunnerCaps,
                 log=print, clock=time.time, codebook=None, pin: ModelPin | None = None,
                 checker_pin: ModelPin | None = None, sample_pct: int = 10, run_id: str = "",
                 extractions_dir: Path | None = None, window: int = WINDOW,
                 threshold: int = THRESHOLD, depth_column: str = "0.25", era_depth=None,
                 screen=None, families=None, flags: dict | None = None, worker: str = "reader",
                 read_timeout_seconds: int | None = None,
                 resume_args: Sequence[str] | None = None, merge: bool = True):
        self.reader_factory, self.cells = reader_factory, list(cells)
        self.batch_source, self.cache = batch_source, cache
        self.manifest_path = Path(manifest_path)
        self.caps, self.log, self.clock = caps, log, clock
        self.codebook, self.pin, self.checker_pin = codebook, pin, checker_pin
        self.sample_pct, self.run_id = int(sample_pct), run_id
        self.extractions_dir = Path(extractions_dir) if extractions_dir else None
        self.window, self.threshold, self.depth_column = int(window), int(threshold), depth_column
        self.era_depth = dict(era_depth or {})
        self.screen = screen if screen is not None else Screen.off()
        self.families = dict(families or {})
        self.flags = dict(flags or {})
        self.worker = worker
        self.read_timeout_seconds = read_timeout_seconds
        self.resume_args = list(resume_args or ())
        self.merge = bool(merge)
        self.schema = record_schema(codebook) if codebook is not None else None
        self._reader = None                 # the last Reader built, for its domain / norm version

    # ---- cache keys, recorded so admission can re-derive the record offline ---------------
    def _families(self) -> dict:
        """The family map the DRIVER will use, whenever it can be seen, because the cache key
        hashes the schema that map selects (`driver.schema_for`). A runner told one thing and
        a reader configured with another would record keys that address nothing - the silent
        failure `schema_for`'s docstring is about."""
        dom = getattr(self._reader, "domain", None)
        if dom is not None:
            return dict(dom.reader.families)
        return self.families

    def _sent_schema(self):
        if self.schema is None or self.codebook is None or self.pin is None:
            return None
        return schema_for(self.schema, self.codebook, self.pin, self._families())

    def _cache_key(self, reader, unit) -> str:
        texts = reader.cases.fetch(unit.case_ids)
        prompt = render_unit(self.codebook, unit, texts, self.worker)
        return ResponseCache.key(self.codebook.sha, self.pin, unit, prompt,
                                 schema_sha=schema_sha(self._sent_schema()),
                                 max_tokens=Request.max_tokens, effort=effort_of(self.pin))

    def _cache_keys(self, reader, planned, unit) -> list[str]:
        """EVERY key this unit's responses live under (review finding 1). A unit whose first
        response would not parse was re-asked as two halves, and those halves' records are the
        ones that were kept - so a manifest recording only the whole-unit key hands admission
        the response that failed and none of the ones that worked, silently. The halves are
        addressed exactly as the driver addressed them: `split_unit`, empty half dropped.

        A recorded key can still address nothing - a unit whose request raised has no cached
        response at all, and a split half never reached before a budget stop has none either.
        `failed` on the unit row says which; admission looks the keys up and skips a miss."""
        keys = [self._cache_key(reader, planned)]
        if getattr(unit, "retried", False):
            keys += [self._cache_key(reader, h) for h in split_unit(planned) if h.case_ids]
        return keys

    def _write_extraction(self, batch_id: str, unit) -> None:
        if self.extractions_dir is None:
            return
        self.extractions_dir.mkdir(parents=True, exist_ok=True)
        doc = {"batch_id": batch_id, "run_id": self.run_id, "status": unit.status,
               "records": [r.record for r in unit.records]}
        (self.extractions_dir / f"{batch_id}.json").write_bytes(
            (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))

    def _budget(self, reader_units: int, t0: float) -> Budget:
        """The PROCESS ceilings, expressed as this read's budget. `max_usd` stays None: the
        subscription reports no per-call price and the driver refuses a usd budget over an
        unpriced provider (`preflight:budget_unpriced`). `max_units` carries headroom over the
        reader units still allowed - see DRIVER_UNIT_HEADROOM and the module docstring."""
        left = max(0, self.caps.max_units - reader_units)
        wall = self.caps.max_wall_seconds - (self.clock() - t0)
        return Budget(max_usd=None, max_units=left + DRIVER_UNIT_HEADROOM,
                      max_wall_seconds=max(1.0, wall))

    def _reader_for(self, counts: dict):
        reader = self.reader_factory()
        if not isinstance(getattr(reader, "provider", None), _CountingProvider):
            reader.provider = _CountingProvider(reader.provider, counts, "reader")
        if reader.checker is not None and not isinstance(reader.checker, _CountingProvider):
            reader.checker = _CountingProvider(reader.checker, counts, "checker")
        self._reader = reader
        return reader

    def _unit_doc(self, unit, keys: list, disagreements, *, retry: bool = False) -> dict:
        """One unit's row in the manifest (R6). The checker block is always present and says
        `"none"` when the unit was not sampled, so "not sampled" and "sampled and silent" are
        never the same reading.

        `cases_lost` says which cases a COMPLETED unit did not answer for (I3); a retry unit
        also records the ids it did answer, which is how `derived` knows a lost case has since
        been recovered."""
        mine = [{"unit_id": d.unit_id, "case_id": d.case_id, "field": d.field,
                 "reader_value": d.reader_value, "checker_value": d.checker_value}
                for d in disagreements if d.unit_id == unit.unit_id]
        resp = unit.response
        return {
            "unit_id": unit.unit_id, "status": unit.status, "cache_hit": bool(unit.cache_hit),
            "retried": bool(unit.retried), "error": unit.error or "",
            # A unit with no response of its own bought nothing that can be looked up; its
            # keys are kept (review finding 7) and this says not to trust them.
            "failed": resp is None,
            "records": len(unit.records),
            "cases_read": accepted_records(unit),
            "cases_lost": lost_case_ids(unit),
            "relevant_accepted": relevant_accepted(unit),
            "irrelevant_accepted": irrelevant_accepted(unit),
            "dropped_quotes": sum(r.dropped_quotes for r in unit.records),
            "nulled_fields": sorted({f for r in unit.records for f in r.nulled_fields}),
            "status_counts": {st: sum(1 for r in unit.records
                                      if r.record.get("extraction_status") == st)
                              for st in ("ok", "partial", "extraction-invalid", "missing")},
            "finish_reason": (resp.finish_reason if resp else None),
            "input_tokens": (resp.input_tokens if resp else None),
            "output_tokens": (resp.output_tokens if resp else None),
            "cache_keys": list(keys),
            "checker": {"sampled": unit.checker is not None,
                        "status": unit.checker or "none",
                        "disagreements": mine},
            **({"retry": True, "cases_answered": answered_case_ids(unit)} if retry else {}),
        }

    def _gate(self, counts: dict, t0: float) -> str | None:
        """The per-PROCESS ceilings, checked before a batch is begun."""
        if counts["reader"] >= self.caps.max_units:
            return "budget:units"
        if self.clock() - t0 >= self.caps.max_wall_seconds:
            return "budget:wall"
        return None

    def _read_batch(self, cell, batch, acc, prog, counts, totals, seen, t0, *,
                    retry: bool = False) -> str | None:
        """One batch through the pinned reader, folded into the cell. Returns a process stop
        kind when the driver ended the process, else None. Screen-pinned batches (R10) come
        through here too, so their units count under `--max-units` and their records count
        toward the cell's yield and toward admission exactly like any other batch's.

        A `retry=True` unit is the one exception to "toward the cell's yield": it is a repair
        of a batch the cell already walked, so it consumes a reader unit and its records join
        the cell, but it does not enter the yield window and does not consume the cap (I3)."""
        reader = self._reader_for(counts)
        plan = plan_batch_extraction(
            [batch], self.codebook.id, self.pin, self._budget(counts["reader"], t0),
            worker=self.worker, checker_pin=self.checker_pin, sample_pct=self.sample_pct,
            json_schema=self.schema, resume_tool=MAP_RESUME_TOOL)
        out = reader.read(plan)
        if out.stop.kind.startswith("preflight:"):
            raise RuntimeError(f"preflight refused the map: {out.stop.kind} {out.stop.detail}")
        totals["input_tokens"] += out.input_tokens
        totals["output_tokens"] += out.output_tokens
        totals["spend_usd"] += out.spend_usd
        totals["unpriced_requests"] += out.manifest.get("unpriced_requests", 0)
        seen["provider"] = out.manifest.get("provider") or seen["provider"]
        seen["provider_reported"].update(
            p for p in (out.manifest.get("provider_reported") or []) if p != "None")
        seen["tool_version"] = seen["tool_version"] or out.manifest.get("tool_version")
        for u in out.units:
            keys = []
            try:
                planned = next(p for p in plan.units if p.id == u.unit_id)
                keys = self._cache_keys(reader, planned, u)
            except Exception as exc:                       # noqa: BLE001
                self.log(f"{u.unit_id}: cache keys not recorded ({exc})")
            acc["units"].append(self._unit_doc(u, keys, out.disagreements, retry=retry))
            self._write_extraction(u.unit_id, u)
            if not retry:
                prog.add(u.unit_id, relevant_accepted(u), unit_completed(u))
            self.log(f"{cell.key} {u.unit_id}: {relevant_accepted(u)} relevant, "
                     f"{counts['reader']}/{self.caps.max_units} units")
        return out.stop.kind if out.stop.kind in PROCESS_STOPS else None

    def run(self, cells: Sequence[Cell] | None = None, *,
            retry_ids: Mapping[str, Sequence[str]] | None = None) -> MapOutcome:
        """The map, or - with `retry_ids` - the lost cases of one (I3).

        A retry walks the retry batches `plan_retry_units` planned for each cell instead of the
        cell's capped head. Everything else is the same run: the same ceilings between batches,
        the same manifest written from the same `finally`, the same merge onto what is on disk.
        The cell's own walk is untouched - no yield window, no cap, no screen - so the merged
        cell keeps the traversal the map made and gains the repair."""
        cells = list(self.cells if cells is None else cells)
        t0 = self.clock()
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        counts = {"reader": 0, "checker": 0, "screen_pinned": 0}
        totals = {"input_tokens": 0, "output_tokens": 0, "spend_usd": 0.0, "unpriced_requests": 0}
        seen = {"provider": None, "provider_reported": set(), "tool_version": None}
        progress: dict[str, CellProgress] = {}
        records: dict[str, dict] = {}
        stop = "done"
        try:
            for cell in cells:
                prog = CellProgress(cell.key, cell.cap_batches)
                progress[cell.key] = prog
                acc = records.setdefault(cell.key, {
                    **cell.to_json(), "units": [],
                    "screen": dict(CELL_SCREEN_OFF), "screen_pinned": [], "wall_seconds": 0.0})
                cell_t0 = self.clock()
                walk = (cell.capped_ids if retry_ids is None
                        else tuple(retry_ids.get(cell.key) or ()))
                for batch_id in walk:
                    if retry_ids is None and prog.should_stop(
                            window=self.window, threshold=self.threshold) is not None:
                        break
                    stop = self._gate(counts, t0) or stop
                    if stop in PROCESS_STOPS:
                        break
                    stop = self._read_batch(cell, self.batch_source.get(batch_id), acc, prog,
                                            counts, totals, seen, t0,
                                            retry=retry_ids is not None) or stop
                    if stop in PROCESS_STOPS:
                        break
                # The cell's stop is the one the WALK ended on, recorded before the screen so
                # the screen's own pinned reads cannot rewrite a `yield_floor` into a
                # `cap_reached` after the fact.
                cell_stop = prog.should_stop(window=self.window, threshold=self.threshold)
                if retry_ids is None and stop not in PROCESS_STOPS:
                    block = self.screen.maybe_run(cell, cell_stop,
                                                  batch_source=self.batch_source, progress=prog)
                    if block:
                        acc["screen"] = dict(block)
                    # R10: the screen only narrows the remainder. Everything it flagged is read
                    # by the PINNED reader, here, in this cell, before the runner moves on.
                    for batch in self.screen.pinned_units():
                        stop = self._gate(counts, t0) or stop
                        if stop in PROCESS_STOPS:
                            break
                        acc["screen_pinned"].append(batch["batch_id"])
                        counts["screen_pinned"] += 1
                        stop = self._read_batch(cell, batch, acc, prog, counts, totals, seen,
                                                t0) or stop
                        if stop in PROCESS_STOPS:
                            break
                acc["cell_stop"] = cell_stop.to_json() if cell_stop else None
                acc["wall_seconds"] = round(self.clock() - cell_t0, 1)
                if stop in PROCESS_STOPS:
                    break
        finally:
            fresh = self._manifest(cells, progress, records, counts, totals, seen, t0,
                                   started, stop)
            manifest, written = self._merge_onto_prior(fresh, counts, totals, t0)
            self._write(written, manifest)
            self.log(f"manifest -> {written}")
            self.log(f"resume: {manifest['resume_command']}")
        return MapOutcome([manifest["cells"][k] for k in manifest["cell_order"]], counts["reader"],
                          round(self.clock() - t0, 1), stop, manifest, written,
                          manifest["resume_command"])

    def _write(self, path: Path, doc: dict) -> None:
        """Whole file or nothing (re-review C). A torn manifest reads as unmergeable, and an
        unmergeable manifest degrades the next subset run back to overwriting the map - so the
        document is built in full, written to a sibling temp file, and moved into place by one
        `os.replace`, which is atomic on Windows and on POSIX alike."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        os.replace(tmp, path)

    def _merge_onto_prior(self, fresh: dict, counts: dict, running: dict,
                          t0: float) -> tuple[dict, Path]:
        """What to write, and where.

        The only caller is `run()`'s `finally`, which may be running with an exception already
        in flight, so a defect in the merge must neither cost the write nor become the thing
        that propagates in the original's place (re-review A). A merge that raises is logged,
        the manifest on disk is left exactly as it was, and THIS process's map is written
        beside it as `<name>.fresh.json`: nothing is lost, nothing is half-written, and the
        original exception still reaches the caller."""
        prior = self._prior()
        if not prior:
            return fresh, self.manifest_path
        try:
            merged = merge_manifest(prior, fresh)
            merged["totals"] = {**merged["totals"],
                                **{k: v for k, v in self._totals(merged["cells"], counts,
                                                                 running, t0).items()
                                   if k not in CUMULATIVE_TOTALS}}
            return merged, self.manifest_path
        except Exception as exc:                        # noqa: BLE001 - see the docstring
            side = self.manifest_path.with_suffix(".fresh.json")
            self.log(f"merge FAILED ({type(exc).__name__}: {exc}); {self.manifest_path} is left "
                     f"as it was and this process's map goes to {side}")
            return fresh, side


    def resume_command(self) -> str:
        """The SAME invocation, verbatim. Resuming a map is re-running the command that
        started it: every unit already in the response cache is replayed for free, so the
        only thing a resume buys is what the last process did not reach."""
        base = f".venv\\Scripts\\python {MAP_RESUME_TOOL}"
        return f"{base} {' '.join(_quote(a) for a in self.resume_args)}" if self.resume_args else base

    def _cell_doc(self, acc: dict, prog: CellProgress) -> dict:
        doc = dict(acc)
        doc.update(prog.to_json(window=self.window, threshold=self.threshold))
        doc["stop"] = doc.pop("cell_stop", doc.get("stop"))
        doc.update(derived(acc["units"]))
        return doc

    def _prior(self) -> dict:
        """The manifest already on disk for THIS run id, when there is a readable one. A file
        from another run, another schema, or a half-written one is ignored rather than merged
        blind - the merge exists to protect a record, not to graft two of them together.

        These checks are necessary and not sufficient: `"map-manifest-v1"` has meant two unit-row
        shapes (`cache_key` before the split-half fix, `cache_keys` since), so a document can
        pass every check here and still be a shape this build did not write. `unit_keys` reads
        both, and `_merge_onto_prior` catches whatever neither anticipated."""
        if not self.merge or not self.manifest_path.exists():
            return {}
        try:
            prior = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.log(f"existing manifest not merged ({type(exc).__name__}: {exc})")
            return {}
        if not isinstance(prior, dict) or prior.get("schema") != MANIFEST_SCHEMA:
            self.log("existing manifest not merged (not a map-manifest-v1 document)")
            return {}
        if prior.get("run_id") != self.run_id:
            self.log(f"existing manifest not merged (run_id {prior.get('run_id')!r})")
            return {}
        return prior

    def _totals(self, cell_docs: Mapping, counts: dict, running: dict, t0: float) -> dict:
        """The map's holdings, summed from the cell documents. Every field is read with `.get`
        for the same reason `derived` is: after a merge these are the cells of a manifest this
        build may not have written, and this runs inside `run()`'s `finally` (re-review A)."""
        def n(cell, key):
            return cell.get(key) or 0

        def ln(cell, key):
            return len(cell.get(key) or [])

        cells = list(cell_docs.values())
        return {
            "cells_read": len(cells),
            "cells_stopped_on_yield": sum(1 for c in cells
                                          if (c.get("stop") or {}).get("kind") == "yield_floor"),
            "cells_stopped_on_cap": sum(1 for c in cells
                                        if (c.get("stop") or {}).get("kind") == "cap_reached"),
            "batches_attempted": sum(n(c, "batches_attempted") for c in cells),
            "batches_completed": sum(n(c, "batches_completed") for c in cells),
            "cases_read": sum(n(c, "cases_read") for c in cells),
            "records": sum(n(c, "records") for c in cells),
            "units": counts["reader"],
            "checker_units": counts["checker"],
            "screen_pinned_units": sum(ln(c, "screen_pinned") for c in cells),
            "relevant_accepted": sum(n(c, "relevant_accepted") for c in cells),
            "irrelevant_accepted": sum(n(c, "irrelevant_accepted") for c in cells),
            "failed_units": sum(ln(c, "failed_units") for c in cells),
            # Three different things, deliberately three numbers (I3): units that did not
            # complete, units whose status was not "ok", and cases a unit that DID complete
            # never answered for. A map can have 0 failed units and still be missing cases.
            "units_not_ok": sum(ln(c, "failures") for c in cells),
            "cases_lost": sum(ln(c, "cases_lost") for c in cells),
            "checker_sampled": sum(ln(c, "checker_sampled") for c in cells),
            "checker_disagreements": sum(ln(c, "checker_disagreements") for c in cells),
            "units_retried_after_split": sum(n(c, "units_retried_after_split") for c in cells),
            "wall_seconds": round(self.clock() - t0, 1),
            "input_tokens": running["input_tokens"],
            "output_tokens": running["output_tokens"],
            "spend_usd": round(running["spend_usd"], 6),
            "unpriced_requests": running["unpriced_requests"],
        }

    def _manifest(self, cells, progress, records, counts, running, seen, t0, started,
                  stop) -> dict:
        cell_docs = {}
        for cell in cells:
            if cell.key not in records:
                continue
            cell_docs[cell.key] = self._cell_doc(records[cell.key], progress[cell.key])
        doc = {
            "schema": MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "cycle": self.run_id.split("-shard")[0],
            "tool": MAP_RESUME_TOOL.replace("\\", "/"),
            "resume_command": self.resume_command(),
            "started_at": started,
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "engine_version": ENGINE_VERSION,
            "reader_pin": self.pin.label if self.pin else None,
            "checker_pin": self.checker_pin.label if self.checker_pin else None,
            "provider": seen["provider"],
            "provider_reported": sorted(seen["provider_reported"]),
            "tool_version": seen["tool_version"],
            "codebook_id": self.codebook.id if self.codebook else None,
            "codebook_sha": self.codebook.sha if self.codebook else None,
            "schema_sha": schema_sha(self._sent_schema()),
            "store_norm_version": getattr(self._reader, "norm", None),
            "effort": effort_of(self.pin) if self.pin else "",
            # What the pool actually handed the reader, not a constant that could drift from
            # it: the widest unit this process read, or null if it read nothing.
            "batch_size": max((u["records"] for c in cell_docs.values() for u in c["units"]),
                              default=None),
            "max_tokens": Request.max_tokens,
            "read_timeout_seconds": self.read_timeout_seconds,
            "sample_pct": self.sample_pct,
            "max_units_note": MAX_UNITS_NOTE,
            # What THIS process bought, as against `totals`, which is what the MAP cost across
            # every process that wrote this manifest. A resume buys nothing and its `process`
            # block says so; `totals.units` still reports the map's real price.
            "process": {"units": counts["reader"], "checker_units": counts["checker"],
                        "screen_pinned_units": counts["screen_pinned"],
                        "wall_seconds": round(self.clock() - t0, 1), "stop": stop},
            "depth_column": self.depth_column,
            "era_depth": dict(self.era_depth),
            "flags": {"window": self.window, "threshold": self.threshold,
                      "depth_column": self.depth_column,
                      "max_units": self.caps.max_units,
                      "max_wall_seconds": self.caps.max_wall_seconds, **self.flags},
            "cell_order": list(cell_docs),
            "cells": cell_docs,
            "totals": self._totals(cell_docs, counts, running, t0),
            "stop": stop,
            "screen": self.screen.to_json(),
        }
        return doc
