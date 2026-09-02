import bisect
import json

from rapidfuzz import fuzz

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION, normalize, normalize_text  # noqa: E402

FUZZY_THRESHOLD = 92.0


def page_for_offset(page_map: list, raw_offset: int):
    starts = [p[0] for p in page_map]
    i = bisect.bisect_right(starts, raw_offset) - 1
    return page_map[max(0, i)][1]


def verify_quote(quote_text: str, case_row: dict) -> dict:
    """Returns {status, raw_span, reporter_page} with status in
    verified | verified-fuzzy | failed."""
    qnorm = normalize_text(quote_text)
    norm_text = case_row["norm_text"]
    idx = norm_text.find(qnorm)
    if idx >= 0 and qnorm:
        _, offsets = normalize(case_row["raw_text"])
        raw_start = offsets[idx]
        raw_end = offsets[min(idx + len(qnorm) - 1, len(offsets) - 1)] + 1
        return {
            "status": "verified",
            "raw_span": [raw_start, raw_end],
            "reporter_page": page_for_offset(case_row["page_map"], raw_start),
        }
    if not qnorm:
        return {"status": "failed", "raw_span": None, "reporter_page": None}
    # fuzzy: best window of comparable length
    n = len(qnorm)
    best_score, best_pos = 0.0, -1
    step = max(20, n // 4)
    for pos in range(0, max(1, len(norm_text) - n + 1), step):
        window = norm_text[pos : pos + n + step]
        score = fuzz.partial_ratio(qnorm, window)
        if score > best_score:
            best_score, best_pos = score, pos
            if score == 100.0:
                break
    if best_score >= FUZZY_THRESHOLD:
        _, offsets = normalize(case_row["raw_text"])
        raw_start = offsets[min(best_pos, len(offsets) - 1)]
        return {
            "status": "verified-fuzzy",
            "raw_span": [raw_start, raw_start + n],
            "reporter_page": page_for_offset(case_row["page_map"], raw_start),
            "fuzzy_score": best_score,
        }
    return {"status": "failed", "raw_span": None, "reporter_page": None}


def load_case(conn, case_id: int) -> dict | None:
    row = conn.execute(
        """SELECT raw_text, norm_text, page_map, norm_version FROM cases
           WHERE case_id=?""",
        (case_id,),
    ).fetchone()
    if not row:
        return None
    if row[3] != NORM_VERSION:
        raise RuntimeError(
            f"case {case_id} normalized at v{row[3]}, verifier at v{NORM_VERSION}: re-ingest"
        )
    return {"raw_text": row[0], "norm_text": row[1], "page_map": json.loads(row[2])}


def verify_record(conn, rec: dict) -> dict:
    case_row = load_case(conn, rec["case_id"])
    if case_row is None:
        rec["extraction_status"] = "extraction-invalid"
        rec["invalid_reason"] = "case not in corpus"
        return rec
    # relevant:false records carry no doctrine; quotes optional (§8 rule 4)
    if rec.get("relevant") is False:
        rec["quotes"] = []
        rec["extraction_status"] = "ok"
        return rec
    supported_ok: set[str] = set()
    kept_quotes = []
    any_failed = False
    for q in rec.get("quotes", []):
        v = verify_quote(q.get("text", ""), case_row)
        if v["status"] == "failed":
            any_failed = True
            continue
        kept_quotes.append({**q, **v})
        if q.get("supports"):
            supported_ok.add(q["supports"])
    rec["quotes"] = kept_quotes
    # null every doctrinal field whose support died (spec §8 hard requirement)
    for field in ("characterization", "polarity", "holding_summary"):
        if rec.get(field) is not None and field not in supported_ok:
            rec[field] = None
            rec.setdefault("nulled_fields", []).append(field)
    if any_failed or rec.get("nulled_fields"):
        rec["extraction_status"] = "extraction-invalid" if not kept_quotes else "partial"
    else:
        rec["extraction_status"] = "ok"
    return rec
