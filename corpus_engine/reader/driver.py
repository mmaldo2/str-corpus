from __future__ import annotations
import hashlib, time
from pathlib import Path
from typing import Mapping
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import Codebook, load_codebook, stability_path
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import (Budget, Disagreement, ModelPin, Plan, ReaderError, ReadingOutcome, Request,
                                        StopReason, Unit, UnitResult)
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


def preflight(plan: Plan, codebook: Codebook, cases, provider, checker, *, store_norm_version, families: Mapping,
              domain=None) -> StopReason | None:
    if codebook.validated_norm_version and store_norm_version and codebook.validated_norm_version != store_norm_version:
        return StopReason("preflight:norm_version", f"{codebook.validated_norm_version} != {store_norm_version}")
    if domain is not None and plan.kind != "stability" and not stability_path(domain, codebook).exists():
        return StopReason("preflight:stability", f"no stability record for {codebook.id} ({codebook.sha[:12]})")
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

    def _ask(self, plan: Plan, cb: Codebook, unit: Unit, pin: ModelPin, worker: str, provider, spend: list, tokens: list):
        texts = self.cases.fetch(unit.case_ids)
        prompt = render_unit(cb, unit, texts, worker)
        key = ResponseCache.key(cb.sha, pin, unit, prompt) if self.cache else None
        resp = self.cache.get(key) if key else None; hit = resp is not None
        if resp is None:
            resp = provider.complete(Request(pin, prompt))
            if key:
                self.cache.put(key, resp)
            spend[0] += resp.cost_usd or 0.0; tokens[0] += resp.input_tokens; tokens[1] += resp.output_tokens
        return texts, resp, hit

    def read(self, plan: Plan) -> ReadingOutcome:
        t0 = self.clock(); cb = self._codebook(plan)
        families = self.domain.reader.families if self.domain is not None else {}
        judged = cb.judged_fields
        stop = preflight(plan, cb, self.cases, self.provider, self.checker, store_norm_version=self.norm, families=families,
                         domain=self.domain if plan.kind != "stability" else None)
        units, disagreements, spend, tokens, n_paid = [], [], [0.0], [0, 0], 0
        if stop is None:
            stop = StopReason("done")
            for unit in plan.units:
                b = plan.budget
                if b.max_usd is not None and spend[0] >= b.max_usd:
                    stop = StopReason("budget:usd", f"{spend[0]:.2f} >= {b.max_usd}"); break
                if b.max_units is not None and n_paid >= b.max_units:
                    stop = StopReason("budget:units", str(n_paid)); break
                if b.max_wall_seconds is not None and self.clock() - t0 >= b.max_wall_seconds:
                    stop = StopReason("budget:wall", f"{self.clock() - t0:.0f}s"); break
                try:
                    texts, resp, hit = self._ask(plan, cb, unit, plan.pin, plan.worker, self.provider, spend, tokens)
                    n_paid += 0 if hit else 1
                    recs = parse_records(resp.text, unit.case_ids)
                    if recs is None:                                   # split retry, once
                        recs = []
                        for half in split_unit(unit):
                            _, r2, h2 = self._ask(plan, cb, half, plan.pin, plan.worker, self.provider, spend, tokens)
                            n_paid += 0 if h2 else 1
                            part = parse_records(r2.text, half.case_ids)
                            if part is None:
                                recs = None; break
                            recs += part
                    if recs is None:
                        units.append(UnitResult(unit.id, "parse_failed", (), resp, hit, "unparseable after split")); continue
                    results = gate_unit(recs, texts, unit.case_ids, judged, unit.id)
                    units.append(UnitResult(unit.id, "ok", results, resp, hit))
                    if self.checker is not None and plan.checker_pin is not None and _sampled(unit.id, plan.sample_pct):
                        _, cresp, _ = self._ask(plan, cb, unit, plan.checker_pin, "checker", self.checker, spend, tokens)
                        crecs = parse_records(cresp.text, unit.case_ids) or []
                        cby = {int(r["case_id"]): r for r in crecs}
                        for rr in results:
                            cr = cby.get(rr.case_id)
                            if cr is None:
                                continue
                            for f in COMPARE_FIELDS:
                                if rr.record.get(f) != cr.get(f):
                                    disagreements.append(Disagreement(unit.id, rr.case_id, f, rr.record.get(f), cr.get(f)))
                    self.log(f"{unit.id}: {len(results)} records, {sum(r.dropped_quotes for r in results)} quotes dropped"
                             + (" (cache)" if hit else ""))
                except ReaderError as exc:
                    units.append(UnitResult(unit.id, "failed", (), None, False, str(exc)[:300])); self.log(f"{unit.id}: FAILED {exc}")
        manifest = {"engine_version": ENGINE_VERSION, "codebook_id": cb.id, "codebook_sha": cb.sha, "model_pin": plan.pin.label,
                    "checker_pin": plan.checker_pin.label if plan.checker_pin else None, "sample_pct": plan.sample_pct,
                    "provider": getattr(self.provider, "name", "?"),
                    "provider_reported": sorted({str((u.response.provider_reported or {}).get("provider")) for u in units if u.response}),
                    "tool_version": next((u.response.tool_version for u in units if u.response and u.response.tool_version), None),
                    "worker": plan.worker, "kind": plan.kind}
        return ReadingOutcome(plan, units, disagreements, round(spend[0], 6), tokens[0], tokens[1], self.clock() - t0, stop,
                              manifest, resume_command(plan, self.run_dir))
