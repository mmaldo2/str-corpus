"""Measures 2-3: machine-tier precision and field accuracy over the frozen audit sample."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from corpus_engine.evaluation.stats import estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate, UNAVAILABLE

METHOD_VERSION = "precision-1"
FIELDS = ("polarity", "who_was_letting")
WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class Precision:
    envelope: Envelope
    sampling_seq: int
    frame_size: int
    n: int
    decided: int
    unresolved: int
    precision: Estimate
    field_accuracy: dict
    joint_correctness: dict | Estimate
    confusion: dict
    subgroups: dict
    revisions: dict
    drift: dict


def _rates(rows: list[dict]) -> dict:
    """rows: outcome entries with status decided. Returns the estimates and confusions."""
    relevant = [r for r in rows if r["user_final"].get("relevant") is True]
    prec = estimate(len(relevant), len(rows))
    acc, conf = {}, {}
    for f in FIELDS:
        hit = sum(1 for r in relevant if r["draw_time"].get(f) == r["user_final"].get(f))
        acc[f] = estimate(hit, len(relevant))
        m: dict[str, dict[str, int]] = {}
        for r in rows:
            row = str(r["draw_time"].get(f))
            col = WITHDRAWN if r["user_final"].get("relevant") is not True else str(r["user_final"].get(f))
            m.setdefault(row, {}); m[row][col] = m[row].get(col, 0) + 1
        conf[f] = m
    joint = sum(1 for r in relevant if all(r["draw_time"].get(f) == r["user_final"].get(f) for f in FIELDS))
    return {"precision": prec, "field_accuracy": acc, "joint": estimate(joint, len(rows)), "confusion": conf}


def precision_and_accuracy(manifest: Mapping, outcomes: Mapping | None) -> Precision:
    sample = {int(r["case_id"]): r for r in manifest["records"]}
    n = len(sample)
    prov = Provenance(inputs=(("sample-manifest", str(manifest.get("frame_sha256")), "frame"),),
                      ledger_seqs={"sampling": manifest["ledger_head_seq"]})
    if outcomes is None:
        env = Envelope(METHOD_VERSION, f"{n} machine-only relevant records drawn at seq {manifest['ledger_head_seq']}",
                       ("the audit has not yet been read; every estimate is unavailable",),
                       Uncertainty("sampling", 0.95, "wilson"), (), prov)
        return Precision(env, manifest["ledger_head_seq"], manifest["frame_size"], n, 0, 0, UNAVAILABLE,
                         {f: UNAVAILABLE for f in FIELDS}, UNAVAILABLE, {}, {}, {}, {})
    rows_all = []
    for cid_s, o in outcomes["records"].items():
        cid = int(cid_s)
        if cid not in sample:
            raise ValueError(f"case {cid} is not in the sample manifest")
        rows_all.append({"case_id": cid, **o})
    decided = [r for r in rows_all if r["status"] == "decided"]
    unresolved = [r for r in rows_all if r["status"] != "decided"]
    rates = _rates(decided)
    sub_ids = [cid for cid, r in sample.items()
               if r["record"].get("polarity") == "favorable" and r["record"].get("who_was_letting") == "householder"]
    sub_rows = [r for r in decided if r["case_id"] in sub_ids]
    sub = _rates(sub_rows) if sub_rows else {"precision": UNAVAILABLE, "field_accuracy": {}, "joint": UNAVAILABLE, "confusion": {}}
    revisions = {f: sum(1 for r in decided if r["user_initial"].get(f) != r["user_final"].get(f))
                 for f in ("relevant",) + FIELDS}
    limitations = [
        "Precision is the share of DRAW-TIME machine-only relevant records a blind human reading kept; "
        "after the audit those records are human-reviewed, so the live machine tier is a different population.",
        "Field accuracy is conditioned on the records the human found relevant; a withdrawn record counts "
        "against joint correctness, not against a field.",
    ]
    if unresolved:
        limitations.append(f"{len(unresolved)} sampled records were left unresolved (unreadable opinions) and "
                           f"are outside every rate's denominator: " + ", ".join(str(r["case_id"]) for r in unresolved))
    env = Envelope(METHOD_VERSION,
                   f"simple random sample of {n} of the {manifest['frame_size']} machine-only relevant records at seq "
                   f"{manifest['ledger_head_seq']} (seed {manifest['seed']})",
                   tuple(f"case {r['case_id']}: {r['status']}" for r in unresolved),
                   Uncertainty("sampling", 0.95, "wilson"), tuple(limitations), prov)
    return Precision(env, manifest["ledger_head_seq"], manifest["frame_size"], n, len(decided), len(unresolved),
                     rates["precision"], rates["field_accuracy"], rates["joint"], rates["confusion"],
                     {"favorable_householder": {"n": len(sub_ids), "precision": sub["precision"],
                                                "field_accuracy": sub["field_accuracy"]}},
                     revisions, dict(outcomes.get("drift") or {}))
