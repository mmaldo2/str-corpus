from __future__ import annotations
import json, math, random
from pathlib import Path
from corpus_engine.reader.driver import agreement
from corpus_engine.reader.model import CaseText, ReadingOutcome
from corpus_engine.reader.sources import InlinedCaseSource

BAR_FIELDS = ("relevant", "polarity", "who_was_letting")
KIT_SEED = 20260904


def load_kit(path: Path):
    k = json.loads(Path(path).read_text(encoding="utf-8"))
    texts = {int(c): CaseText(int(c), t["cite"], t["name"], t["court"], t["jurisdiction"], t["year"], t["raw_text"], t["norm_text"], t["page_map"])
             for c, t in k["texts"].items()}
    return k["reference"], k["batches"], InlinedCaseSource(texts)


def kit_sample_50(reference: list[dict]) -> list[int]:
    human = sorted(r["case_id"] for r in reference if r["source"] == "human")
    return sorted(random.Random(KIT_SEED).sample(human, min(50, len(human))))


def score_candidate(outcome: ReadingOutcome, reference: list[dict]) -> dict:
    ref = {int(r["case_id"]): r for r in reference}
    recs = outcome.records
    # Controller ruling: stub records for failed/partial units carry extraction_status
    # "missing" and relevant: None; they must not count as accepted and must be excluded
    # from agreement (relevant: None would otherwise disagree with every reference row).
    missing_records = sum(1 for r in recs if r.get("extraction_status") == "missing")
    non_missing = [r for r in recs if r.get("extraction_status") != "missing"]
    by_id = {int(r["case_id"]): r for r in non_missing if r.get("case_id") is not None}
    kept = sum(len(r.record.get("quotes") or []) for u in outcome.units for r in u.records if r.record.get("relevant"))
    dropped = sum(r.dropped_quotes for u in outcome.units for r in u.records if r.record.get("relevant"))
    fidelity = kept / (kept + dropped) if (kept + dropped) else 0.0
    human = [r for r in reference if r["source"] == "human"]
    ag = agreement([by_id[c] for c in by_id if c in ref and ref[c]["source"] == "human"], human, BAR_FIELDS)
    ag["macro"] = sum(ag[f] for f in BAR_FIELDS) / len(BAR_FIELDS)
    machine = [r for r in reference if r["source"] == "machine"]
    mi = (sum(1 for r in machine if by_id.get(r["case_id"], {}).get("relevant") is False) / len(machine)) if machine else None
    n_cases = sum(len(u.records) for u in outcome.units) or sum(len(u.case_ids) for u in outcome.plan.units)
    accepted = sum(1 for r in non_missing if r.get("extraction_status") in ("ok", "partial") and r.get("relevant") is not None)
    return {"fidelity": fidelity, "agreement_human": ag, "agreement_machine_irrelevant": mi,
            "schema_compliance": (len(non_missing) / n_cases) if n_cases else 0.0, "accepted": accepted,
            "missing_records": missing_records,
            "cost_per_accepted": (outcome.spend_usd / accepted) if accepted else math.inf, "spend_usd": outcome.spend_usd,
            "wall_seconds": round(outcome.wall_seconds, 1), "provider_reported": outcome.manifest.get("provider_reported"),
            "failed_units": outcome.failed_units, "stop": outcome.stop.kind}


def select_reader(scores: dict[str, dict], *, fidelity_floor: float = 0.97, agreement_bar: float = 0.85) -> dict:
    eliminated = sorted(k for k, s in scores.items() if s["fidelity"] < fidelity_floor)
    survivors = {k: s for k, s in scores.items() if k not in eliminated}
    if not survivors:
        return {"winner": None, "rule": "no candidate cleared the fidelity floor", "survivors": [], "eliminated": eliminated, "shortfall": True}
    over = {k: s for k, s in survivors.items() if s["agreement_human"]["macro"] >= agreement_bar}
    if over:
        w = min(over, key=lambda k: (over[k]["cost_per_accepted"], k))
        return {"winner": w, "rule": f"cheapest cost per accepted record among survivors with macro agreement >= {agreement_bar}",
                "survivors": sorted(survivors), "eliminated": eliminated, "shortfall": False}
    w = max(survivors, key=lambda k: (survivors[k]["agreement_human"]["macro"], -survivors[k]["cost_per_accepted"]))
    return {"winner": w, "rule": f"no survivor reached {agreement_bar}; highest-agreement survivor chosen (shortfall disclosed)",
            "survivors": sorted(survivors), "eliminated": eliminated, "shortfall": True}


def stability_agreement(out_a: ReadingOutcome, out_b: ReadingOutcome, fields=BAR_FIELDS) -> dict[str, float]:
    return agreement(out_a.records, out_b.records, fields)
