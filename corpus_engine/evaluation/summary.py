"""Compose the five measures and the published counts into one Evaluation; JSON out."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from corpus_engine.evaluation.types import as_dict
from corpus_engine.evaluation.gold import GoldRecovery
from corpus_engine.evaluation.precision import Precision
from corpus_engine.evaluation.agreement import Agreement
from corpus_engine.evaluation.coverage import Coverage

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class Inputs:
    gold: GoldRecovery
    precision: Precision
    agreement: Agreement
    coverage: Coverage


@dataclass(frozen=True)
class Evaluation:
    evaluation_id: str
    generated_at: str
    cycle: str
    code: dict
    ledger: dict
    gold_recovery: GoldRecovery
    precision: Precision
    agreement: Agreement
    coverage: Coverage


def _tier(c) -> dict:
    return {"human_reviewed": c.total.human_reviewed, "machine_only": c.total.machine_only}


def ledger_content_sha256(ledger_dir: Path) -> str:
    h = hashlib.sha256()
    names = ["patches.jsonl"] + sorted(p.name for p in ledger_dir.glob("cycle-*.jsonl"))
    for n in names:
        p = ledger_dir / n
        if p.exists():
            h.update(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return h.hexdigest()


def evaluate(view, inputs: Inputs, *, cycle: str, reporting_seq: int, content_sha256: str,
             code: dict, generated_at: str = "") -> Evaluation:
    from datetime import datetime, timezone
    ledger = {"reporting_seq": reporting_seq, "content_sha256": content_sha256,
              "counts": {"relevant": _tier(view.counts()),
                         "favorable": _tier(view.counts(polarity="favorable")),
                         "favorable_householder": _tier(view.counts(polarity="favorable", who_was_letting="householder"))}}
    return Evaluation(f"{cycle}-{reporting_seq}-{content_sha256[:8]}",
                      generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      cycle, dict(code), ledger, inputs.gold, inputs.precision, inputs.agreement, inputs.coverage)


def to_json(ev: Evaluation) -> dict:
    return {"schema_version": SCHEMA_VERSION, "evaluation_id": ev.evaluation_id, "generated_at": ev.generated_at,
            "cycle": ev.cycle, "code": ev.code, "ledger": ev.ledger,
            "gold_recovery": as_dict(ev.gold_recovery), "precision": as_dict(ev.precision),
            "agreement": as_dict(ev.agreement), "coverage": as_dict(ev.coverage)}
