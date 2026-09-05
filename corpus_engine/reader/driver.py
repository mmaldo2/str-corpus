from __future__ import annotations
import hashlib, time
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import Codebook, load_codebook, stability_path
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import (Budget, Disagreement, ModelPin, Plan, ReaderError, ReadingOutcome, Request,
                                        StopReason, Unit, UnitResult, RecordResult)
from corpus_engine.reader.parse import parse_records, split_unit
from corpus_engine.reader.render import render_unit

ENGINE_VERSION = "reader-v1"
COMPARE_FIELDS = ("relevant", "polarity", "characterization")


def plan_batch_extraction(batches, codebook_id: str, pin: ModelPin, budget: Budget, *, worker: str,
                          checker_pin: ModelPin | None = None, sample_pct: int = 10) -> Plan:
    units = tuple(Unit(b["batch_id"], tuple(int(c["case_id"]) for c in b["cases"]),
                       {"batch_id": b["batch_id"], "era_partition": b["era_partition"], "jurisdiction": b["jurisdiction"],
                        "signals": {int(c["case_id"]): c.get("signals", []) for c in b["cases"]}}) for b in batches)
    return Plan("batch_extraction", units, codebook_id, pin, budget, worker, checker_pin, sample_pct)


def plan_reread(records, codebook_id, pin, budget, *, worker) -> Plan:
    units = tuple(Unit(f"reread-{r['case_id']}", (int(r["case_id"]),),
                       {"batch_id": f"reread-{r['case_id']}", "era_partition": r.get("era_partition", "?"),
                        "jurisdiction": r.get("jurisdiction", "?"), "signals": {}}) for r in records)
    return Plan("reread", units, codebook_id, pin, budget, worker)


def plan_judgment(case_ids, question: str, codebook_id, pin, budget, *, worker) -> Plan:
    units = tuple(Unit(f"judge-{c}", (int(c),), {"batch_id": f"judge-{c}", "era_partition": "?", "jurisdiction": "?",
                                                 "signals": {}, "question": question}) for c in case_ids)
    return Plan("judgment", units, codebook_id, pin, budget, worker)


def agreement(a, b, fields) -> dict[str, float]:
    ba = {int(r["case_id"]): r for r in a if r.get("case_id") is not None}
    bb = {int(r["case_id"]): r for r in b if r.get("case_id") is not None}
    common = sorted(set(ba) & set(bb)); out = {}
    for f in fields:
        out[f] = (sum(1 for c in common if ba[c].get(f) == bb[c].get(f)) / len(common)) if common else 0.0
    return out


def resume_command(plan: Plan, run_dir: Path | None) -> str:
    rd = str(run_dir) if run_dir else "runs\\<run>"
    return f".venv\\Scripts\\python pipeline\\read.py --plan {rd}\\plan.json --resume"


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


def preflight(plan: Plan, codebook: Codebook, cases, provider, checker, *, store_norm_version, families: Mapping,
              domain=None) -> StopReason | None:
    if codebook.validated_norm_version and store_norm_version and codebook.validated_norm_version != store_norm_version:
        return StopReason("preflight:norm_version", f"{codebook.validated_norm_version} != {store_norm_version}")
    if domain is not None and plan.kind != "stability" and not stability_path(domain, codebook).exists():
        return StopReason("preflight:stability", f"no stability record for {codebook.id} ({codebook.sha[:12]})")
    if plan.budget.max_usd is not None and getattr(provider, "name", None) == "codex-cli":
        return StopReason("preflight:budget_unpriced", "codex-cli reports no per-call cost; a usd budget cannot be enforced")
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
                 sleep=time.sleep, clock=time.time, domain=None, run_dir: Path | None = None, store_norm_version=None):
        self.provider, self.cases, self.checker, self.cache = provider, cases, checker, cache
        self.log, self.sleep, self.clock, self.domain, self.run_dir, self.norm = log, sleep, clock, domain, run_dir, store_norm_version

    def _codebook(self, plan: Plan) -> Codebook:
        if self.domain is None:
            raise ReaderError("Reader needs a domain to load codebooks")
        return load_codebook(self.domain, plan.codebook_id)

    def _ask(self, plan: Plan, cb: Codebook, unit: Unit, pin: ModelPin, worker: str, provider, state: _ReadState):
        texts = self.cases.fetch(unit.case_ids)
        prompt = render_unit(cb, unit, texts, worker)
        key = ResponseCache.key(cb.sha, pin, unit, prompt) if self.cache else None
        resp = self.cache.get(key) if key else None; hit = resp is not None
        if resp is None:
            state.check_budget()                       # before any paid request; a cache hit never trips it
            resp = provider.complete(Request(pin, prompt))
            if key:
                self.cache.put(key, resp)
            state.record_paid(resp)
        return texts, resp, hit

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
                    split_failed_ids: set[int] = set()
                    if recs is None:                                   # split retry, once
                        recs = []
                        for half in split_unit(unit):
                            _, r2, h2 = self._ask(plan, cb, half, plan.pin, plan.worker, self.provider, state)
                            part = parse_records(r2.text, half.case_ids)
                            if part is None:
                                split_failed_ids.update(half.case_ids)
                            else:
                                recs.extend(part)
                        if len(split_failed_ids) == len(unit.case_ids):
                            stub = tuple(_missing_stub(cid, "unit parse failed") for cid in unit.case_ids)
                            units.append(UnitResult(unit.id, "parse_failed", stub, resp, hit, "unparseable after split"))
                            continue
                    ok_ids = [c for c in unit.case_ids if c not in split_failed_ids]
                    results = list(gate_unit(recs, texts, ok_ids, judged, unit.id)) if ok_ids else []
                    if split_failed_ids:
                        results += [_missing_stub(cid, "parse failed (split half)")
                                    for cid in unit.case_ids if cid in split_failed_ids]
                        order = {c: i for i, c in enumerate(unit.case_ids)}
                        results.sort(key=lambda r: order[r.case_id])
                    status = "partial_parse" if split_failed_ids else "ok"
                    units.append(UnitResult(unit.id, status, tuple(results), resp, hit))
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
                        units[-1] = replace(units[-1], checker=checker_status, checker_response=checker_resp)
                    self.log(f"{unit.id}: {len(results)} records, {sum(r.dropped_quotes for r in results)} quotes dropped"
                             + (" (cache)" if hit else ""))
                except _BudgetStop as bs:
                    stop = bs.reason; break
                except ReaderError as exc:
                    stub = tuple(_missing_stub(cid, f"unit failed: {exc}") for cid in unit.case_ids)
                    units.append(UnitResult(unit.id, "failed", stub, None, False, str(exc)[:300]))
                    self.log(f"{unit.id}: FAILED {exc}")
        manifest = {"engine_version": ENGINE_VERSION, "codebook_id": cb.id, "codebook_sha": cb.sha, "model_pin": plan.pin.label,
                    "checker_pin": plan.checker_pin.label if plan.checker_pin else None, "sample_pct": plan.sample_pct,
                    "provider": getattr(self.provider, "name", "?"),
                    "provider_reported": sorted({str((u.response.provider_reported or {}).get("provider")) for u in units if u.response}),
                    "tool_version": next((u.response.tool_version for u in units if u.response and u.response.tool_version), None),
                    "worker": plan.worker, "kind": plan.kind,
                    "checker_provider_reported": sorted({str((u.checker_response.provider_reported or {}).get("provider"))
                                                         for u in units if u.checker_response}),
                    "checker_tool_version": next((u.checker_response.tool_version for u in units
                                                  if u.checker_response and u.checker_response.tool_version), None),
                    "checker_unparsed": sum(1 for u in units if u.checker == "unparsed"),
                    "unpriced_requests": state.unpriced_requests}
        return ReadingOutcome(plan, units, disagreements, round(state.spend, 6), state.input_tokens, state.output_tokens,
                              self.clock() - t0, stop, manifest, resume_command(plan, self.run_dir))
