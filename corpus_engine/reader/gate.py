"""The quote gate runs inside the driver (ADR-0011): nothing unverified leaves it."""
from __future__ import annotations
from corpus_engine.reader.model import CaseText, RecordResult
from corpus_engine.verification import verify_quote


def gate_record(rec: dict, case: CaseText, judged_fields) -> RecordResult:
    rec = dict(rec)
    if rec.get("relevant") is False:
        rec["quotes"] = []; rec["extraction_status"] = "ok"
        return RecordResult(int(rec["case_id"]), rec, "ok", 0, ())
    case_row = {"raw_text": case.raw_text, "norm_text": case.norm_text, "page_map": case.page_map}
    kept, supported, dropped = [], set(), 0
    for q in rec.get("quotes") or []:
        v = verify_quote((q or {}).get("text", ""), case_row)
        if v["status"] == "failed":
            dropped += 1; continue
        kept.append({**q, **v})
        if q.get("supports"):
            supported.add(q["supports"])
    rec["quotes"] = kept; nulled = []
    for f in judged_fields:
        if rec.get(f) is not None and f not in supported:
            rec[f] = None; nulled.append(f)
    if nulled:
        rec["nulled_fields"] = nulled
    status = "ok" if not dropped and not nulled else ("partial" if kept else "extraction-invalid")
    rec["extraction_status"] = status
    return RecordResult(int(rec["case_id"]), rec, status, dropped, tuple(nulled))


def gate_unit(records: list[dict], texts: list[CaseText], case_ids, judged_fields, unit_id: str) -> tuple[RecordResult, ...]:
    by_id = {int(r["case_id"]): r for r in records if isinstance(r, dict) and r.get("case_id") is not None}
    tx = {t.case_id: t for t in texts}; out = []
    for cid in case_ids:
        cid = int(cid)
        if cid in by_id and cid in tx:
            out.append(gate_record(by_id[cid], tx[cid], judged_fields))
        else:
            out.append(RecordResult(cid, {"case_id": cid, "relevant": None, "polarity": None, "quotes": [],
                                          "gate_notes": "missing from response", "extraction_status": "missing"}, "missing", 0, ()))
    return tuple(out)
