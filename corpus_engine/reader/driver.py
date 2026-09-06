from __future__ import annotations
import hashlib, time
from dataclasses import replace
from typing import Mapping
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import Codebook, load_codebook, stability_path
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import (Budget, Disagreement, ModelPin, Plan, ReaderError, ReadingOutcome, Request,
                                        StopReason, Unit, UnitResult, RecordResult, effort_of)
from corpus_engine.reader.parse import parse_records, split_unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.schema import record_schema, schema_sha

ENGINE_VERSION = "reader-v1"
COMPARE_FIELDS = ("relevant", "polarity", "characterization")
# The family whose OpenRouter requests need schema.py's "openai-strict" dialect (2026-09-05:
# every request to openai/gpt-5.6-terra failed HTTP 400 "Invalid schema for response_format"
# against the default dialect). Picked here, in the request planner, rather than inside
# OpenRouterProvider, so the cache key below hashes the schema actually sent.
OPENAI_STRICT_FAMILY = "openai"


def plan_batch_extraction(batches, codebook_id: str, pin: ModelPin, budget: Budget, *, worker: str,
                          checker_pin: ModelPin | None = None, sample_pct: int = 10,
                          json_schema: dict | None = None, resume_tool: str = "") -> Plan:
    units = tuple(Unit(b["batch_id"], tuple(int(c["case_id"]) for c in b["cases"]),
                       {"batch_id": b["batch_id"], "era_partition": b["era_partition"], "jurisdiction": b["jurisdiction"],
                        "signals": {int(c["case_id"]): c.get("signals", []) for c in b["cases"]}}) for b in batches)
    return Plan("batch_extraction", units, codebook_id, pin, budget, worker, checker_pin, sample_pct,
                json_schema, resume_tool)


def plan_reread(records, codebook_id, pin, budget, *, worker, json_schema: dict | None = None) -> Plan:
    units = tuple(Unit(f"reread-{r['case_id']}", (int(r["case_id"]),),
                       {"batch_id": f"reread-{r['case_id']}", "era_partition": r.get("era_partition", "?"),
                        "jurisdiction": r.get("jurisdiction", "?"), "signals": {}}) for r in records)
    return Plan("reread", units, codebook_id, pin, budget, worker, json_schema=json_schema)


def plan_judgment(case_ids, question: str, codebook_id, pin, budget, *, worker,
                  json_schema: dict | None = None) -> Plan:
    units = tuple(Unit(f"judge-{c}", (int(c),), {"batch_id": f"judge-{c}", "era_partition": "?", "jurisdiction": "?",
                                                 "signals": {}, "question": question}) for c in case_ids)
    return Plan("judgment", units, codebook_id, pin, budget, worker, json_schema=json_schema)


def agreement(a, b, fields) -> dict[str, float]:
    """Per-field agreement over the case ids present in BOTH lists.

    The denominator is the intersection, so a record that never arrived - a failed
    unit's stub, a case missing from a response - is excluded rather than counted as a
    disagreement. Agreement therefore measures the reads that happened; how many did
    not is `schema_compliance` / `missing_records` in `measure.score_candidate`. A
    caller comparing two runs of different coverage has to read both numbers."""
    ba = {int(r["case_id"]): r for r in a if r.get("case_id") is not None}
    bb = {int(r["case_id"]): r for r in b if r.get("case_id") is not None}
    common = sorted(set(ba) & set(bb)); out = {}
    for f in fields:
        out[f] = (sum(1 for c in common if ba[c].get(f) == bb[c].get(f)) / len(common)) if common else 0.0
    return out


RESUME_TOOL = "tools\\measure_reader.py"        # the tool the measurement passes as plan.resume_tool


def resume_command(plan: Plan) -> str:
    """A literal CLI line that re-runs this plan (spec section 5); the response cache
    makes the units already bought free.

    It has to name a program that exists AND that built this plan. 3A hard-coded
    tools/measure_reader.py for every batch_extraction plan, which was true while the
    measurement was the only caller and stops being true the moment the map runner exists
    (slice 2). The plan now carries its own tool; a plan that names none gets no command,
    and `manifest["resume"]` says why."""
    if plan.kind == "batch_extraction" and plan.resume_tool:
        return f".venv\\Scripts\\python {plan.resume_tool} --only {plan.pin.model_id}"
    return ""


def resume_note(plan: Plan) -> str:
    if plan.kind == "batch_extraction" and plan.resume_tool:
        return f"re-run through {plan.resume_tool}; units already in the response cache are free"
    return (f"no runner recorded for this {plan.kind!r} plan (the planner passed no resume_tool); "
            f"resume_command is empty by design")


def _sampled(unit_id: str, pct: int) -> bool:
    return int(hashlib.sha256(unit_id.encode()).hexdigest()[:8], 16) % 100 < pct


def _missing_stub(case_id: int, note: str) -> RecordResult:
    return RecordResult(case_id, {"case_id": case_id, "relevant": None, "polarity": None, "quotes": [],
                                   "gate_notes": note, "extraction_status": "missing"}, "missing", 0, ())


class _BudgetStop(Exception):
    """Internal signal only: raised by _ReadState.check_budget(), caught by the unit loop."""
    def __init__(self, reason: StopReason):
        super().__init__(reason.kind)
        self.reason = reason


class _ReadState:
    """Per-read() mutable counters. Budget is checked here, right before any paid
    request (reader, split-half, or checker) - a cache hit never calls check_budget()."""
    def __init__(self, budget: Budget, clock, t0: float):
        self.budget, self.clock, self.t0 = budget, clock, t0
        self.spend = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.n_paid = 0
        self.unpriced_requests = 0

    def check_budget(self) -> None:
        b = self.budget
        if b.max_usd is not None and self.spend >= b.max_usd:
            raise _BudgetStop(StopReason("budget:usd", f"{self.spend:.2f} >= {b.max_usd}"))
        if b.max_units is not None and self.n_paid >= b.max_units:
            raise _BudgetStop(StopReason("budget:units", str(self.n_paid)))
        if b.max_wall_seconds is not None and self.clock() - self.t0 >= b.max_wall_seconds:
            raise _BudgetStop(StopReason("budget:wall", f"{self.clock() - self.t0:.0f}s"))

    def record_paid(self, resp) -> None:
        self.spend += resp.cost_usd or 0.0
        self.input_tokens += resp.input_tokens
        self.output_tokens += resp.output_tokens
        self.n_paid += 1
        if resp.cost_usd is None:
            self.unpriced_requests += 1


# Transports that report no per-call price. A usd budget over one of them is not a budget:
# `_ReadState.spend` would stay at 0.0 for every request and the ceiling would never trip.
UNPRICED_PROVIDERS = ("codex-cli", "claude-cli")


def preflight(plan: Plan, codebook: Codebook, cases, provider, checker, *, store_norm_version, families: Mapping,
              domain=None) -> StopReason | None:
    if codebook.validated_norm_version and store_norm_version and codebook.validated_norm_version != store_norm_version:
        return StopReason("preflight:norm_version", f"{codebook.validated_norm_version} != {store_norm_version}")
    if domain is not None and plan.kind != "stability" and not stability_path(domain, codebook).exists():
        return StopReason("preflight:stability", f"no stability record for {codebook.id} ({codebook.sha[:12]})")
    if plan.budget.max_usd is not None and getattr(provider, "name", None) in UNPRICED_PROVIDERS:
        return StopReason("preflight:budget_unpriced",
                          f"{getattr(provider, 'name', '?')} reports no per-call cost; a usd budget "
                          f"cannot be enforced - use max_units / max_wall_seconds")
    if plan.checker_pin is not None:
        fr = families.get(plan.pin.model_id, plan.pin.family); fc = families.get(plan.checker_pin.model_id, plan.checker_pin.family)
        if fr == fc:
            return StopReason("preflight:families", f"reader and checker are both {fr}")
        if checker is not None and hasattr(checker, "is_available") and not checker.is_available():
            return StopReason("preflight:checker_available", getattr(checker, "name", "checker"))
    if hasattr(provider, "probe_model") and provider.probe_model(plan.pin.model_id) is None:
        return StopReason("preflight:pin", f"{plan.pin.model_id} not served")
    return None


class Reader:
    def __init__(self, provider, cases, *, checker=None, cache: ResponseCache | None = None, log=print,
                 clock=time.time, domain=None, store_norm_version):
        # No `sleep`: the retry schedules live in the provider adapters, so the driver was
        # storing a callable it never used (m10). Same for the old `run_dir`, which only fed
        # the resume line that named a script which does not exist (I9).
        self.provider, self.cases, self.checker, self.cache = provider, cases, checker, cache
        self.log, self.clock, self.domain, self.norm = log, clock, domain, store_norm_version

    def _codebook(self, plan: Plan) -> Codebook:
        if self.domain is None:
            raise ReaderError("Reader needs a domain to load codebooks")
        return load_codebook(self.domain, plan.codebook_id)

    def _schema_for(self, plan: Plan, cb: Codebook, pin: ModelPin) -> dict | None:
        """The schema this pin's request carries. Every family but openai gets
        `plan.json_schema` unchanged (whatever dialect the caller built it with); an
        openai-family pin gets a fresh "openai-strict" schema derived from the same
        codebook, so a family-openai unit and the same unit for another family only
        ever differ by schema sha - never by plan identity or cache-key shape."""
        if plan.json_schema is None:
            return None
        families = self.domain.reader.families if self.domain is not None else {}
        family = families.get(pin.model_id, pin.family)
        if family == OPENAI_STRICT_FAMILY:
            return record_schema(cb, dialect="openai-strict")
        return plan.json_schema

    def _ask(self, plan: Plan, cb: Codebook, unit: Unit, pin: ModelPin, worker: str, provider, state: _ReadState):
        texts = self.cases.fetch(unit.case_ids)
        prompt = render_unit(cb, unit, texts, worker)
        schema = self._schema_for(plan, cb, pin)
        req = Request(pin, prompt, json_schema=schema)
        key = (ResponseCache.key(cb.sha, pin, unit, prompt, schema_sha=schema_sha(schema),
                                 max_tokens=req.max_tokens, effort=effort_of(pin)) if self.cache else None)
        resp = self.cache.get(key) if key else None; hit = resp is not None
        if resp is None:
            state.check_budget()                       # before any paid request; a cache hit never trips it
            resp = provider.complete(req)
            if key:
                self.cache.put(key, resp)
            state.record_paid(resp)
        return texts, resp, hit

    def _assemble(self, unit: Unit, texts, recs, judged, stub_notes: dict[int, str]):
        """Gate the cases that came back, stub the rest, and return them in the unit's own
        case order. `stub_notes` maps a case id to why it has no record."""
        ok_ids = [c for c in unit.case_ids if c not in stub_notes]
        results = list(gate_unit(recs, texts, ok_ids, judged, unit.id)) if ok_ids else []
        results += [_missing_stub(cid, stub_notes[cid]) for cid in unit.case_ids if cid in stub_notes]
        order = {c: i for i, c in enumerate(unit.case_ids)}
        results.sort(key=lambda r: order[r.case_id])
        return tuple(results)

    def read(self, plan: Plan) -> ReadingOutcome:
        t0 = self.clock(); cb = self._codebook(plan)
        families = self.domain.reader.families if self.domain is not None else {}
        judged = cb.judged_fields
        stop = preflight(plan, cb, self.cases, self.provider, self.checker, store_norm_version=self.norm, families=families,
                         domain=self.domain if plan.kind != "stability" else None)
        units, disagreements = [], []
        state = _ReadState(plan.budget, self.clock, t0)
        if stop is None:
            stop = StopReason("done")
            for unit in plan.units:
                try:
                    texts, resp, hit = self._ask(plan, cb, unit, plan.pin, plan.worker, self.provider, state)
                    recs = parse_records(resp.text, unit.case_ids)
                    stub_notes: dict[int, str] = {}
                    retried = False
                    if recs is None:                                   # split retry, once
                        halves = [h for h in split_unit(unit) if h.case_ids]
                        if len(halves) < 2:
                            # A unit of one splits into itself and an EMPTY half, and the driver
                            # then bought a provider request for no cases at all - which parses
                            # vacuously and was recorded as a success (I4). plan_reread and
                            # plan_judgment emit only one-case units, so in 3B that would be one
                            # wasted request for every re-read whose response would not parse.
                            stub = tuple(_missing_stub(cid, "unit parse failed") for cid in unit.case_ids)
                            units.append(UnitResult(unit.id, "parse_failed", stub, resp, hit,
                                                    "unparseable; a single-case unit is never split"))
                            self.log(f"{unit.id}: parse failed; one case, not split")
                            continue
                        recs = []; retried = True; i = 0
                        try:
                            for i, half in enumerate(halves):
                                _, r2, _h2 = self._ask(plan, cb, half, plan.pin, plan.worker, self.provider, state)
                                part = parse_records(r2.text, half.case_ids)
                                if part is None:
                                    for cid in half.case_ids:
                                        stub_notes[cid] = "parse failed (split half)"
                                else:
                                    recs.extend(part)
                        except Exception as exc:            # noqa: BLE001 - see the unit handler
                            # A half that never ran (budget tripped, N1), died on a provider
                            # error (I2), or hit an engine defect (N6) must not take the other
                            # half's paid, parsed records with it: what was bought is kept, only
                            # the rest is stubbed.
                            budget = isinstance(exc, _BudgetStop)
                            detail = "" if budget else f"{type(exc).__name__}: {exc}"
                            note = ("budget stop before split half" if budget else
                                    f"failed on split half ({type(exc).__name__})")
                            for cid in (c for h in halves[i:] for c in h.case_ids):
                                stub_notes[cid] = note
                            units.append(UnitResult(unit.id, "partial_parse",
                                                    self._assemble(unit, texts, recs, judged, stub_notes), resp, hit,
                                                    detail[:1000], retried=True))
                            if budget:
                                raise
                            self.log(f"{unit.id}: split half FAILED {detail}")
                            continue
                        if len(stub_notes) == len(unit.case_ids):
                            stub = tuple(_missing_stub(cid, "unit parse failed") for cid in unit.case_ids)
                            units.append(UnitResult(unit.id, "parse_failed", stub, resp, hit, "unparseable after split",
                                                    retried=True))
                            continue
                    results = self._assemble(unit, texts, recs, judged, stub_notes)
                    status = "partial_parse" if stub_notes else "ok"
                    units.append(UnitResult(unit.id, status, results, resp, hit, retried=retried))
                    if self.checker is not None and plan.checker_pin is not None and _sampled(unit.id, plan.sample_pct):
                        checker_status, checker_resp = None, None
                        try:
                            _, cresp, _ = self._ask(plan, cb, unit, plan.checker_pin, "checker", self.checker, state)
                            checker_resp = cresp
                            crecs = parse_records(cresp.text, unit.case_ids)
                            if crecs is None:
                                checker_status = "unparsed"
                                self.log(f"{unit.id}: checker response unparseable")
                            else:
                                checker_status = "ok"
                                cby = {int(r["case_id"]): r for r in crecs}
                                for rr in results:
                                    cr = cby.get(rr.case_id)
                                    if cr is None:
                                        continue
                                    for f in COMPARE_FIELDS:
                                        if rr.record.get(f) != cr.get(f):
                                            disagreements.append(Disagreement(unit.id, rr.case_id, f, rr.record.get(f), cr.get(f)))
                        except ReaderError as exc:
                            checker_status = f"failed:{str(exc)[:120]}"
                            self.log(f"{unit.id}: checker FAILED {exc}")
                        except _BudgetStop as exc:
                            # patch the unit with the checker outcome before the budget stop propagates,
                            # so it isn't left indistinguishable from "not sampled" (N2).
                            checker_status = "failed:budget"
                            self.log(f"{unit.id}: checker FAILED {exc}")
                            units[-1] = replace(units[-1], checker=checker_status, checker_response=checker_resp)
                            raise
                        except Exception as exc:                       # noqa: BLE001 - see the unit handler
                            checker_status = f"failed:{type(exc).__name__}: {exc}"[:120]
                            self.log(f"{unit.id}: checker FAILED {type(exc).__name__}: {exc}")
                        units[-1] = replace(units[-1], checker=checker_status, checker_response=checker_resp)
                    self.log(f"{unit.id}: {len(results)} records, {sum(r.dropped_quotes for r in results)} quotes dropped"
                             + (" (cache)" if hit else ""))
                except _BudgetStop as bs:
                    stop = bs.reason; break
                except ReaderError as exc:
                    stub = tuple(_missing_stub(cid, f"unit failed: {exc}") for cid in unit.case_ids)
                    units.append(UnitResult(unit.id, "failed", stub, None, False, str(exc)[:1000]))
                    self.log(f"{unit.id}: FAILED {exc}")
                except Exception as exc:                               # noqa: BLE001 - deliberate
                    # An unexpected defect costs one unit, never the whole plan and every paid
                    # response already in it (I1). Not hypothetical: a TypeError raised in
                    # gate.py on a list-valued `supports` escaped `except ReaderError` during
                    # the 2026-09-05 measurement and killed a whole candidate, which was then
                    # recorded as a failed model. The exception type is kept in the status so
                    # an engine defect is never mistaken for a provider failure.
                    detail = f"{type(exc).__name__}: {exc}"
                    stub = tuple(_missing_stub(cid, f"unit failed: {detail}") for cid in unit.case_ids)
                    units.append(UnitResult(unit.id, "failed", stub, None, False, f"failed:{detail}"[:1000]))
                    self.log(f"{unit.id}: FAILED {detail}")
        manifest = {"engine_version": ENGINE_VERSION, "codebook_id": cb.id, "codebook_sha": cb.sha, "model_pin": plan.pin.label,
                    "checker_pin": plan.checker_pin.label if plan.checker_pin else None, "sample_pct": plan.sample_pct,
                    "provider": getattr(self.provider, "name", "?"),
                    "provider_reported": sorted({str((u.response.provider_reported or {}).get("provider")) for u in units if u.response}),
                    "tool_version": next((u.response.tool_version for u in units if u.response and u.response.tool_version), None),
                    "worker": plan.worker, "kind": plan.kind, "resume": resume_note(plan),
                    "checker_provider_reported": sorted({str((u.checker_response.provider_reported or {}).get("provider"))
                                                         for u in units if u.checker_response}),
                    "checker_tool_version": next((u.checker_response.tool_version for u in units
                                                  if u.checker_response and u.checker_response.tool_version), None),
                    "checker_unparsed": sum(1 for u in units if u.checker == "unparsed"),
                    "units_retried_after_split": sum(1 for u in units if u.retried),
                    "unpriced_requests": state.unpriced_requests}
        return ReadingOutcome(plan, units, disagreements, round(state.spend, 6), state.input_tokens, state.output_tokens,
                              self.clock() - t0, stop, manifest, resume_command(plan))
