"""Scoring v2 (spec section 6). `field_scores` reports two numbers per field, not one:
`decided_rate` says how often the reader answered at all after the gate, `agreement_decided`
how often it agreed when both sides answered - 3A blended them, so a reader that left
`polarity` null scored the same as one that got `polarity` wrong. `polarity` and
`who_was_letting` are judged only where both sides call the case relevant, so a relevance
miss is scored once, as relevance. `select_reader` applies decision D4, pre-registered
before any read: fidelity floor, then a decided-rate floor per judged field, then the
agreement bar, then a subscription tie-break, with the shortfall disclosed either way."""
from __future__ import annotations
import json, math, random
from pathlib import Path
from corpus_engine.reader.driver import agreement
from corpus_engine.reader.model import CaseText, ReadingOutcome
from corpus_engine.reader.schema import FLAG_PREFIX, POLARITY_VALUES, WHO_VALUES  # noqa: F401 (R3/D7: re-exported)
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


def _decided(field: str, value) -> bool:
    """Whether a side answered this field at all. `irrelevant` is not a polarity value
    (D2): a kit-v1 reference row still carrying it is undecided, not wrong. Likewise a
    `who_was_letting` value outside the schema's enum is undecided, not a disagreement."""
    if value is None:
        return False
    if field == "polarity":
        return value in POLARITY_VALUES
    if field == "who_was_letting":
        return value in WHO_VALUES
    return True


def _case_excluded_fields(record: dict) -> set[str]:
    """R7: the fields excluded from agreement for one case (D6), unioned from two
    sources - the ledger's `needs-review:<field>` flags at `record["review"]["flags"]`,
    and an explicit `excluded_fields` list a kit case row may already carry (Task 7
    writes it at kit-build time). The case stays in the kit for fidelity and for every
    other field regardless of which source names it."""
    fields = set(record.get("excluded_fields") or ())
    flags = (record.get("review") or {}).get("flags") or ()
    fields |= {f[len(FLAG_PREFIX):] for f in flags if f.startswith(FLAG_PREFIX)}
    return fields


def excluded_fields(reference: list[dict]) -> dict[int, set[str]]:
    """D6: fields the reviewer marked `unsure`, per case. The case stays in the kit for
    fidelity and for every other field."""
    out: dict[int, set[str]] = {}
    for r in reference:
        fields = _case_excluded_fields(r)
        if fields:
            out[int(r["case_id"])] = fields
    return out


def field_scores(predictions: list[dict], reference: list[dict], *, fields=BAR_FIELDS,
                 excluded=None) -> dict:
    """Per field: how often the reader decided, and how often it agreed when both decided.

    The denominator for `decided_rate` is the reference-decided cases the reader returned a
    record for; `agreement_decided` runs over the subset where the reader also decided.
    `polarity` and `who_was_letting` are computed only where the reference marks the case
    relevant AND the prediction does, so a relevance miss is scored once, as relevance -
    `n_prediction_irrelevant` records how many cases that removed, because a reader that
    calls everything irrelevant would otherwise shrink its way to a high decided rate."""
    ref = {int(r["case_id"]): r for r in reference}
    pred = {int(r["case_id"]): r for r in predictions if r.get("case_id") is not None}
    ex = {int(k): set(v) for k, v in (excluded or {}).items()}
    out: dict = {}
    for f in fields:
        pool = [c for c in sorted(ref)
                if c in pred and f not in ex.get(c, ()) and _decided(f, ref[c].get(f))]
        gated = pool
        dropped = 0
        if f != "relevant":
            gated = [c for c in pool if ref[c].get("relevant") is True and pred[c].get("relevant") is True]
            dropped = len(pool) - len(gated)
        decided = [c for c in gated if _decided(f, pred[c].get(f))]
        agreed = sum(1 for c in decided if pred[c].get(f) == ref[c].get(f))
        out[f] = {"decided_rate": (len(decided) / len(gated)) if gated else 0.0,
                  "agreement_decided": (agreed / len(decided)) if decided else 0.0,
                  "n_reference_decided": len(gated), "n_both_decided": len(decided),
                  "n_prediction_irrelevant": dropped}
    out["macro"] = sum(out[f]["agreement_decided"] for f in fields) / len(fields)
    return out


def score_candidate(outcome: ReadingOutcome, reference: list[dict], *,
                    spend_usd_override: float | None = None, excluded=None) -> dict:
    ref = {int(r["case_id"]): r for r in reference}
    recs = outcome.records
    # Stub records for failed/partial units carry extraction_status "missing" and
    # relevant: None; they must not count as accepted and must be excluded from agreement.
    missing_records = sum(1 for r in recs if r.get("extraction_status") == "missing")
    non_missing = [r for r in recs if r.get("extraction_status") != "missing"]
    by_id = {int(r["case_id"]): r for r in non_missing if r.get("case_id") is not None}
    kept = sum(len(r.record.get("quotes") or []) for u in outcome.units for r in u.records if r.record.get("relevant"))
    dropped = sum(r.dropped_quotes for u in outcome.units for r in u.records if r.record.get("relevant"))
    fidelity = kept / (kept + dropped) if (kept + dropped) else 0.0
    # R5: agreement (and so macro) is computed over HUMAN reference rows only, as
    # measurement v1 did - a machine-labelled "irrelevant" row belongs to
    # `agreement_machine_irrelevant` below, not to the field-by-field bar.
    human = [r for r in reference if r["source"] == "human"]
    fields = field_scores([by_id[c] for c in by_id if c in ref and ref[c]["source"] == "human"],
                          human, excluded=excluded)
    macro = fields.pop("macro")
    machine = [r for r in reference if r["source"] == "machine"]
    mi = (sum(1 for r in machine if by_id.get(r["case_id"], {}).get("relevant") is False) / len(machine)) if machine else None
    n_cases = sum(len(u.records) for u in outcome.units) or sum(len(u.case_ids) for u in outcome.plan.units)
    accepted = sum(1 for r in non_missing if r.get("extraction_status") in ("ok", "partial")
                   and r.get("relevant") is not None)
    # `accepted` is the pre-registered denominator; `accepted_full` counts only the records
    # whose judged fields all survived the gate, so the gap is how many were partial (I7).
    accepted_full = sum(1 for r in non_missing if r.get("extraction_status") == "ok"
                        and r.get("relevant") is not None)
    responses = [u.response for u in outcome.units if u.response is not None]
    list_costs = [r.raw.get("list_cost_usd") for r in responses if (r.raw or {}).get("list_cost_usd") is not None]
    list_cost_usd = round(sum(list_costs), 6) if list_costs else None
    # R6: "no response carried a cost" is the real signal for a subscription run - a
    # response's own `cost_usd` is the guaranteed contract, never collapsed to 0.0 here.
    # `list_cost_usd` (summed above) is reported alongside, not consulted for this check:
    # a future provider could reuse that raw key for an unrelated annotation next to a
    # genuine non-null `cost_usd`, and trusting it here would silently hide real spend.
    subscription = bool(responses) and all(r.cost_usd is None for r in responses)
    any_cache_hit = any(u.cache_hit for u in outcome.units)
    if subscription:
        # The subscription has no marginal price. A zero is not cheap, it is absent, and an
        # absent price must never win a cost comparison.
        priced, spend_for_cost = False, 0.0
    elif spend_usd_override is not None:
        priced, spend_for_cost = True, spend_usd_override
    elif any_cache_hit:
        priced, spend_for_cost = False, outcome.spend_usd
    else:
        priced, spend_for_cost = True, outcome.spend_usd
    cost_per_accepted = (spend_for_cost / accepted) if (priced and accepted) else math.inf
    return {"fidelity": fidelity, "fields": fields, "macro": macro,
            "agreement_machine_irrelevant": mi,
            "schema_compliance": (len(non_missing) / n_cases) if n_cases else 0.0,
            "accepted": accepted, "accepted_full": accepted_full,
            "missing_records": missing_records, "priced": priced, "list_cost_usd": list_cost_usd,
            "cost_per_accepted": cost_per_accepted, "spend_usd": spend_for_cost,
            "wall_seconds": round(outcome.wall_seconds, 1),
            "provider_reported": outcome.manifest.get("provider_reported"),
            "failed_units": outcome.failed_units, "stop": outcome.stop.kind}


def select_reader(scores: dict[str, dict], *, subscription=frozenset(), fidelity_floor: float = 0.97,
                  decided_floor: float = 0.90, agreement_bar: float = 0.85, tie_window: float = 0.02,
                  fields=BAR_FIELDS) -> dict:
    """Decision D4, pre-registered in the spec before any read.

    Floors first (fidelity, then decided rate per judged field), then the agreement bar,
    then the tie-break: a subscription candidate within `tie_window` of the best surviving
    macro wins, because the subscription read costs nothing and the difference is inside the
    noise the 3A stability check measured. Cost per accepted record is reported but is not
    part of the rule: D4 has no cost term. The tie-break applies in the shortfall branch too
    (plan-writer resolution): the reason for it - the subscription read costs nothing - does
    not change when nobody clears the agreement bar."""
    eliminated: dict[str, str] = {}
    for k in sorted(scores):
        s = scores[k]
        if s["fidelity"] < fidelity_floor:
            eliminated[k] = f"fidelity {s['fidelity']:.4f} < {fidelity_floor}"
            continue
        low = [f for f in fields if s["fields"][f]["decided_rate"] < decided_floor]
        if low:
            eliminated[k] = ("decided rate below " + f"{decided_floor}" + " on "
                             + ", ".join(f"{f} {s['fields'][f]['decided_rate']:.4f}" for f in low))
    survivors = {k: s for k, s in scores.items() if k not in eliminated}
    if not survivors:
        return {"winner": None, "rule": f"no candidate cleared the fidelity floor {fidelity_floor} "
                                        f"and the decided-rate floor {decided_floor}",
                "survivors": [], "eliminated": eliminated, "shortfall": True, "best_macro": None}
    best = max(s["macro"] for s in survivors.values())
    pool = {k: s for k, s in survivors.items() if s["macro"] >= agreement_bar}
    shortfall = not pool
    if shortfall:
        pool = dict(survivors)
    near = {k: s for k, s in pool.items() if k in set(subscription) and s["macro"] >= best - tie_window}
    if near:
        winner = max(sorted(near), key=lambda k: near[k]["macro"])
        rule = (f"subscription candidate within {tie_window} of the best surviving macro "
                f"({best:.4f})")
    else:
        winner = max(sorted(pool), key=lambda k: pool[k]["macro"])
        rule = "highest macro agreement among survivors"
    if shortfall:
        rule += f"; no survivor reached {agreement_bar} (shortfall disclosed)"
    return {"winner": winner, "rule": rule, "survivors": sorted(survivors), "eliminated": eliminated,
            "shortfall": shortfall, "best_macro": best}


def stability(read_a: list[dict], read_b: list[dict], fields=BAR_FIELDS) -> dict:
    """R12: stability on decided answers. Two reads of the same sample, over the case ids
    present in both; a case where `read_b` went null does not count as instability, it
    counts against `read_b`'s own decided rate. Reports, per field, the agreement among
    cases BOTH reads decided plus the fraction of the common cases `read_b` decided at
    all - the 0.90 bar (spec section 6) applies to `agreement_decided`."""
    a = {int(r["case_id"]): r for r in read_a if r.get("case_id") is not None}
    b = {int(r["case_id"]): r for r in read_b if r.get("case_id") is not None}
    common = sorted(set(a) & set(b))
    out: dict = {}
    for f in fields:
        both_decided = [c for c in common if _decided(f, a[c].get(f)) and _decided(f, b[c].get(f))]
        agreed = sum(1 for c in both_decided if a[c].get(f) == b[c].get(f))
        b_decided = sum(1 for c in common if _decided(f, b[c].get(f)))
        out[f] = {"agreement_decided": (agreed / len(both_decided)) if both_decided else 0.0,
                  "decided_rate_b": (b_decided / len(common)) if common else 0.0}
    return out


def stability_agreement(out_a: ReadingOutcome, out_b: ReadingOutcome, fields=BAR_FIELDS) -> dict[str, float]:
    return agreement(out_a.records, out_b.records, fields)
