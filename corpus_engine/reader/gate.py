"""The quote gate runs inside the driver (ADR-0011): nothing unverified leaves it."""
from __future__ import annotations
from dataclasses import replace
from corpus_engine.reader.model import CaseText, RecordResult
from corpus_engine.verification import verify_quote
from corpus_engine.quotes import quote_supports as _supports

DUPLICATE_NOTE = "duplicate records for this case_id in the response; the last one was kept"

# _supports is corpus_engine.quotes.quote_supports under its old local name: the
# codebook asks for one field name, but a passage genuinely can carry two findings and
# models say so (the 2026-09-05 measurement had deepseek-v4-flash return
# `["characterization", "under_thirty_days"]`, which a bare `set.add` on the raw value
# died on -- `unhashable type: 'list'` -- taking the whole candidate down with it). The
# gate and the ledger's drop_quote cascade must never disagree about what a quote
# supports, so this is one helper, not two copies (review finding 5). It lives in
# corpus_engine.quotes rather than in the ledger: the reader is upstream of the ledger, and
# importing downstream to read a response was the dependency the wrong way round (M4).


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
        supported.update(_supports(q))
    rec["quotes"] = kept; nulled = []
    for f in judged_fields:
        if rec.get(f) is not None and f not in supported:
            rec[f] = None; nulled.append(f)
    if nulled:
        rec["nulled_fields"] = nulled
    status = "ok" if not dropped and not nulled else ("partial" if kept else "extraction-invalid")
    rec["extraction_status"] = status
    return RecordResult(int(rec["case_id"]), rec, status, dropped, tuple(nulled))


def _index(records: list[dict]) -> tuple[dict, set]:
    """Last record for a case id wins, as before - but which ids arrived more than once is
    now recorded rather than silently dropped (m4)."""
    by_id, dupes = {}, set()
    for r in records:
        if not isinstance(r, dict) or r.get("case_id") is None:
            continue
        try:
            cid = int(str(r["case_id"]).strip())
        except (TypeError, ValueError):
            continue
        if cid in by_id:
            dupes.add(cid)
        by_id[cid] = r
    return by_id, dupes


def _note(res: RecordResult, note: str) -> RecordResult:
    rec = dict(res.record)
    rec["gate_notes"] = f"{rec['gate_notes']}; {note}" if rec.get("gate_notes") else note
    return replace(res, record=rec)


def gate_unit(records: list[dict], texts: list[CaseText], case_ids, judged_fields, unit_id: str) -> tuple[RecordResult, ...]:
    by_id, dupes = _index(records)
    tx = {t.case_id: t for t in texts}; out = []
    for cid in case_ids:
        cid = int(cid)
        if cid in by_id and cid in tx:
            res = gate_record(by_id[cid], tx[cid], judged_fields)
            out.append(_note(res, DUPLICATE_NOTE) if cid in dupes else res)
        else:
            out.append(RecordResult(cid, {"case_id": cid, "relevant": None, "polarity": None, "quotes": [],
                                          "gate_notes": "missing from response", "extraction_status": "missing"}, "missing", 0, ()))
    return tuple(out)
