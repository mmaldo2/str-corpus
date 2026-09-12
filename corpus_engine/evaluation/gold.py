"""Measure 1: recovery of the eligible gold cases, with the stage each miss was lost at."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from corpus_engine.evaluation.stats import estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate

METHOD_VERSION = "gold-recovery-1"
READ_FAILED = "read-failed"          # the read_units value for a case whose unit failed


@dataclass(frozen=True)
class TierFunnel:
    entries: int
    resolved: int
    signaled: int
    read: int
    relevant: int
    relevant_human: int
    recovery: Estimate


@dataclass(frozen=True)
class Miss:
    cite: str
    case_id: int | None
    tier: str
    lost_at: str          # unresolved | unsignaled | unread | read-failed | reader-negative | withdrawn
    detail: str


@dataclass(frozen=True)
class GoldRecovery:
    envelope: Envelope
    tiers: dict
    union: TierFunnel
    misses: tuple[Miss, ...]
    unresolved: tuple[dict, ...]
    inventory: dict


def _tier_of(row: Mapping) -> str | None:
    if row.get("tier") == "treatise":
        return "treatise"
    if row.get("tier") == "brief":
        return "brief-letting" if row.get("domain") == "letting" else "brief-doctrine"
    return None


def _dedupe(rows: Sequence[Mapping]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        key = r.get("case_id") or r.get("cite_norm")
        if key in seen:
            continue
        seen.add(key); out.append(dict(r))
    return out


def _lost_at(cid: int, view, signaled, read_units) -> tuple[str, str]:
    if not signaled.get(cid):
        return "unsignaled", "no selector or ranker signal"
    ru = read_units.get(cid)
    if ru is None:
        return "unread", "signaled but never in a completed map unit"
    if ru == READ_FAILED:
        return "read-failed", "its map unit failed"
    for p in view.history(cid):
        if p.op == "set" and p.field == "relevant" and p.new is False and p.basis.reviewer:
            return "withdrawn", f"withdrawn by {p.basis.reviewer} in run {p.basis.run_id}"
    return "reader-negative", f"read in {ru}; the reader said not relevant and no human overturned it"


def _funnel(rows, view, signaled, read_units, misses: list[Miss]) -> TierFunnel:
    resolved = [r for r in rows if r.get("case_id")]
    n_sig = n_read = n_rel = n_hum = 0
    for r in resolved:
        cid = int(r["case_id"])
        rec = view.state.records.get(cid) or {}
        if signaled.get(cid):
            n_sig += 1
        if cid in read_units and read_units[cid] != READ_FAILED:
            n_read += 1
        if rec.get("relevant") is True:
            n_rel += 1
            if view.reviewed(cid):
                n_hum += 1
        else:
            stage, detail = _lost_at(cid, view, signaled, read_units)
            misses.append(Miss(str(r.get("cite")), cid, _tier_of(r) or "", stage, detail))
    return TierFunnel(len(rows), len(resolved), n_sig, n_read, n_rel, n_hum, estimate(n_rel, len(resolved)))


def gold_recovery(gold_rows: Sequence[Mapping], view, *, signaled: Mapping[int, bool],
                  read_units: Mapping[int, str]) -> GoldRecovery:
    rows = _dedupe(gold_rows)
    by_tier = {"brief-letting": [], "treatise": [], "brief-doctrine": []}
    for r in rows:
        t = _tier_of(r)
        if t in by_tier:
            by_tier[t].append(r)
    misses: list[Miss] = []
    tiers = {t: _funnel(by_tier[t], view, signaled, read_units, misses) for t in ("brief-letting", "treatise")}
    union = _funnel(by_tier["brief-letting"] + by_tier["treatise"], view, signaled, read_units, [])
    unresolved = tuple({"cite": r.get("cite"), "tier": _tier_of(r)}
                       for r in by_tier["brief-letting"] + by_tier["treatise"] if not r.get("case_id"))
    doc = by_tier["brief-doctrine"]
    inventory = {"brief-doctrine": {"entries": len(doc), "resolved": sum(1 for r in doc if r.get("case_id"))}}
    env = Envelope(
        METHOD_VERSION,
        "benchmark recovery: the gold brief-letting and treatise cases that resolve to a corpus case "
        "(the briefs and treatises the project started from; no documented held-out split)",
        ("brief-doctrine entries are inventory only: authorities cited for doctrine, not letting cases",
         "unresolved cites are an ingest coverage gap, listed but outside the recovery denominator"),
        Uncertainty("sampling", 0.95, "wilson"),
        ("Recovery is cumulative across every map run; a per-run column names the run that first carried each hit.",
         "The gold set is a benchmark, not a random sample of the population of letting cases."),
        Provenance(inputs=(("data/gold/gold.jsonl", "", "gold"),)))
    return GoldRecovery(env, tiers, union, tuple(misses), unresolved, inventory)
