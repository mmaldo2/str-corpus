"""The review round (spec section 9, D4/D5).

Seven sections in a fixed priority order. A record appears ONCE, in its highest section, with
its other reasons listed on the card - a queue that showed the same case four times would
spend the round's 150 cards on twenty cases. What does not fit waits for the next round in
the same order; nothing is dropped, and the deferred ids are written into the queue manifest
so the next round starts exactly where this one stopped.

Section G (spec section 7) is the one exception: it is built from re-read conflicts on
records a human ALREADY reviewed, so it is exempt from both the one-appearance rule (one G
card per conflicting field, not per record) and the reviewed-record filter (a G card exists
BECAUSE the record is reviewed).

The checker runs on every queued record before the page is built (D5), so the card can show
what a second family said about the case the user is about to decide. `check_queue` is that
pass; the statuses it reports for one queued case are exactly four, and every consumer (the
page, the manifest, T9's live step) may see any of them:

  ok               the checker returned a record for this case and it parsed
  unparsed         the checker answered but its response would not parse for this case
                   (the unit failed to parse, or this case came back as a gate stub)
  failed:<msg>     the checker's unit raised; `<msg>` is the driver's own error text
  missing          the queued case is in no unit result at all - the budget stopped the
                   read before it was asked, or the plan never reached it

`ok` and `missing` are the two a caller is most tempted to conflate: "the checker said
nothing" and "the checker was never asked" are different facts about a card.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from rapidfuzz import fuzz

from corpus_engine.reader.driver import COMPARE_FIELDS, plan_reread

QUEUE_CAP = 150
SECTIONS = (("G", "reread_conflict", "Re-read conflicts with a human decision"),
            ("A", "favorable_under_thirty", "Favorable and under thirty days"),
            ("B", "householder_nights", "Householder letting by the night"),
            ("C", "checker_disagreement", "Reader / checker disagreement"),
            ("D", "polarity_mixed", "Polarity mixed"),
            ("E", "gate_erased", "Judged fields erased by the quote gate"),
            ("F", "fuzzy_quote", "Fuzzy quote match"))
SECTION_OF = {key: sec for sec, key, _t in SECTIONS}
# The dict a section-G card is built from. ONE shape, two producers: what
# `tools/admit_map.py --reread` writes to runs/<run-id>/reread-conflicts.json, and what
# `conflicts_from_view` renders the fold's own rejected attempts into.
CONFLICT_KEYS = ("case_id", "field", "human_value", "human_basis", "human_at",
                 "reread_value", "reread_basis", "kind", "cell_key", "batch_id")
CONFLICT_KINDS = ("value", "relevant_false")
# The four statuses `check_queue` reports (module docstring). `failed:` is a prefix; the
# driver's error text follows it.
CHECK_STATUSES = ("ok", "unparsed", "failed:", "missing")
# D5's checker pass is a re-read, one case per unit, under the checker's own pin. Named here
# so the queue manifest can record WHICH path was taken (R10) instead of the reader having to
# infer it from the pin alone.
CHECKER_PLAN_KIND = "reread"
CHECKER_WORKER = "checker"
# Stage 1's mechanical rule (pipeline/pre_review.py cmd_fuzzy), unchanged.
FUZZY_COVERAGE = 0.92
FUZZY_MAX_RUN = 4
_WORD = re.compile(r"[a-z0-9]+")


def checker_path(pin, *, unit_cap: int) -> dict:
    """What the queue manifest records about the checker pass (R10): the plan type, the pin
    and the unit cap it ran under. A round whose checker answers came from `plan_judgment`,
    or from the reader's own pin, is not the round this module describes, and the manifest
    has to be able to say which one it was."""
    return {"plan": CHECKER_PLAN_KIND, "worker": CHECKER_WORKER,
            "pin": getattr(pin, "label", str(pin)) if pin is not None else None,
            "cases_per_unit": 1, "unit_cap": unit_cap, "sample_pct": 100}


def classify_fuzzy(quote_text: str, source_text: str) -> dict:
    """Stage 1's character-level rule: all-tiny substitutions are OCR noise, anything else is
    a real mismatch and needs a human.

    Only quote-side (a-side) mismatch runs count: the source window carries context the quote
    never claimed to include, so a b-side insertion is not evidence of anything."""
    a = " ".join(_WORD.findall((quote_text or "").lower()))
    b = " ".join(_WORD.findall((source_text or "").lower()))
    sm = difflib.SequenceMatcher(a=a, b=b)
    runs = [i2 - i1 for op, i1, i2, _j1, _j2 in sm.get_opcodes() if op in ("replace", "delete")]
    coverage = 1 - (sum(runs) / max(1, len(a)))
    trivial = coverage >= FUZZY_COVERAGE and (not runs or max(runs) <= FUZZY_MAX_RUN)
    return {"classification": "trivial-ocr" if trivial else "needs-human",
            "quote_coverage": round(coverage, 3), "miss_runs": runs}


def source_window(quote_text: str, case_text: str, *, pad: int = 140) -> str:
    """The stretch of the opinion the quote was matched against, with a little context.

    The same stepped `partial_ratio` scan `corpus_engine/verification.py` uses to place a
    fuzzy quote, so the window a reviewer reads is the window the gate scored - and so the
    classifier is never handed a hundred-kilobyte opinion as its `b` side."""
    q = (quote_text or "").strip()
    if not q or not case_text:
        return (case_text or "")[:1200]
    idx = case_text.find(q)
    if idx >= 0:
        return case_text[max(0, idx - pad):idx + len(q) + pad]
    n = len(q)
    step = max(20, n // 4)
    best, pos = -1.0, 0
    lowered = case_text.lower()
    ql = q.lower()
    for i in range(0, max(1, len(case_text) - n + 1), step):
        score = fuzz.partial_ratio(ql, lowered[i:i + n + step])
        if score > best:
            best, pos = score, i
        if best == 100.0:
            break
    return case_text[max(0, pos - pad):pos + n + step + pad]


def fuzzy_quotes(record: Mapping, case_text: str) -> tuple[dict, ...]:
    """Every quote the gate matched only fuzzily, classified.

    AUTO-ACCEPT (D4, resolved): Stage 1 paired the mechanical rule with a reader `ocr-ok`
    pass. This slice runs no such pass, so the second signal is the reader's own gate outcome
    on the same record: `extraction_status == "ok"` and nothing nulled means the reader
    transcribed this opinion faithfully everywhere else. A record the gate already had to
    touch does not get the benefit of the doubt."""
    clean = record.get("extraction_status") == "ok" and not (record.get("nulled_fields") or ())
    out = []
    for q in record.get("quotes") or ():
        if q.get("status") != "verified-fuzzy":
            continue
        window = source_window(q.get("text", ""), case_text)
        cls = classify_fuzzy(q.get("text", ""), window)
        out.append({**q, **cls, "case_id": record.get("case_id"), "source": window,
                    "auto_accepted": bool(clean and cls["classification"] == "trivial-ocr")})
    return tuple(out)


def reasons_for(record: Mapping, *, disagreements: Sequence[Mapping],
                fuzzy_needs_human: bool) -> tuple[str, ...]:
    """Every section this record qualifies for, in D4's priority order. Empty for a record
    that is not relevant: an irrelevant read carries no judged values to adjudicate."""
    if not record.get("relevant"):
        return ()
    out = []
    if record.get("polarity") == "favorable" and record.get("under_thirty_days") == "yes":
        out.append("favorable_under_thirty")
    if (record.get("who_was_letting") == "householder"
            and record.get("duration_of_occupancy") == "nights"):
        out.append("householder_nights")
    if any(d.get("field") in COMPARE_FIELDS for d in disagreements):
        out.append("checker_disagreement")
    if record.get("polarity") == "mixed":
        out.append("polarity_mixed")
    if record.get("nulled_fields"):
        out.append("gate_erased")
    if fuzzy_needs_human:
        out.append("fuzzy_quote")
    return tuple(out)


CARD_VALUE_FIELDS = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                     "characterization", "under_thirty_days", "owner_freedom_characterization",
                     "restriction_nature")


@dataclass(frozen=True)
class QueueCard:
    case_id: int
    section: str
    reason: str
    other_reasons: tuple[str, ...]
    record: dict
    disagreements: tuple[dict, ...] = ()
    fuzzy: tuple[dict, ...] = ()
    # The re-read disagreement this card exists for (section G only), in `CONFLICT_KEYS`
    # shape. A plain dict, not a dataclass: it is read from a JSON file, rendered into a page
    # and read back out of the queue manifest, and one shape through all three is worth more
    # than a type.
    conflict: dict | None = None

    @property
    def decide_field(self) -> str:
        """The field this card's decision applies to (R4). A card is an invitation to decide
        ONE thing; without this the page would have to guess from the section, and section C
        (whatever field the checker contradicted) and E (whatever field the gate erased)
        cannot be guessed at all."""
        if self.reason == "reread_conflict":
            return str((self.conflict or {}).get("field") or "polarity")
        if self.reason in ("favorable_under_thirty", "polarity_mixed"):
            return "polarity"
        if self.reason == "householder_nights":
            return "who_was_letting"
        if self.reason == "checker_disagreement":
            for d in self.disagreements:
                if d.get("field") in COMPARE_FIELDS:
                    return str(d["field"])
            return "polarity"
        if self.reason == "gate_erased":
            nulled = list(self.record.get("nulled_fields") or ())
            return str(nulled[0]) if nulled else "polarity"
        return "quotes"

    def to_json(self) -> dict:
        r = self.record
        return {"case_id": self.case_id, "section": self.section, "reason": self.reason,
                "other_reasons": list(self.other_reasons),
                "decide_field": self.decide_field,
                "cite": r.get("cite"), "name": r.get("name"), "court": r.get("court"),
                "jur": r.get("jurisdiction"), "year": r.get("year"),
                "values": {f: r.get(f) for f in CARD_VALUE_FIELDS},
                "holding_summary": r.get("holding_summary"),
                "quotes": list(r.get("quotes") or ()),
                "nulled_fields": list(r.get("nulled_fields") or ()),
                "extraction_status": r.get("extraction_status"),
                "disagreements": [dict(d) for d in self.disagreements],
                "fuzzy": [dict(f) for f in self.fuzzy],
                "conflict": dict(self.conflict) if self.conflict else None}


@dataclass
class Queue:
    run_id: str
    cards: tuple[QueueCard, ...]
    deferred: tuple[int, ...]
    cap: int = QUEUE_CAP
    # Fuzzy quotes the mechanical rule accepted without a human (D4). Not cards - they are
    # the audit trail the caller writes to runs/<run-id>/fuzzy-auto-accepted.json, so that
    # "the reviewer never saw this quote" is a recorded decision rather than an absence.
    auto_accepted: tuple[dict, ...] = ()

    def by_section(self) -> dict[str, list[QueueCard]]:
        out: dict[str, list[QueueCard]] = {sec: [] for sec, _k, _t in SECTIONS}
        for c in self.cards:
            out[c.section].append(c)
        return out

    def to_json(self) -> dict:
        by = self.by_section()
        return {"run_id": self.run_id, "cap": self.cap,
                "titles": {sec: title for sec, _k, title in SECTIONS},
                "sections": {sec: [c.to_json() for c in cards] for sec, cards in by.items()},
                "deferred": list(self.deferred),
                "fuzzy_auto_accepted": [dict(f) for f in self.auto_accepted]}


def _disagreements_by_case(manifest: Mapping) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for cell in (manifest.get("cells") or {}).values():
        for d in cell.get("checker_disagreements") or ():
            out.setdefault(int(d["case_id"]), []).append(dict(d))
    return out


def admitted_case_ids(view, run_id: str) -> list[int]:
    """The cases this run admitted, in admission order. `view.patches` is the authority: the
    run id lives on the admit patch's basis, and nothing on the record itself says which run
    put it there."""
    seen: set[int] = set()
    out: list[int] = []
    for p in view.patches:
        if p.op == "admit" and p.basis.run_id == run_id and p.case_id not in seen:
            seen.add(p.case_id)
            out.append(p.case_id)
    return out


def conflicts_from_view(view) -> list[dict]:
    """The fold's own rejected writes, as section-G cards (D2, spec section 3).

    Belt to `reread-conflicts.json`'s braces. The re-read tool declines to EMIT a patch the
    fold would reject, so in the ordinary case this returns nothing; anything it does return is
    a write some other path attempted and the ledger refused, and that is exactly the thing
    that must not disappear silently."""
    out = []
    for case_id, rows in sorted(view.conflicts().items()):
        for row in rows:
            field = row["field"]
            human_basis, human_at = {}, 0
            for p in view.history(case_id):
                if p.basis.reviewer and p.op == "set" and p.field == field:
                    human_basis, human_at = p.basis.to_json(), int(p.seq)
            out.append({"case_id": int(case_id), "field": field,
                        "human_value": row.get("standing"), "human_basis": human_basis,
                        "human_at": human_at, "reread_value": row.get("attempted"),
                        "reread_basis": row.get("by") or {},
                        "kind": "relevant_false" if field == "relevant" else "value",
                        "cell_key": "", "batch_id": ""})
    return out


def select_queue(view, run_id: str, *, manifest: Mapping, cases, cap: int = QUEUE_CAP,
                 sections=SECTIONS, conflicts: Sequence[Mapping] = ()) -> Queue:
    """Priority order, one appearance per record, then the cap. Deferred cards keep their
    order so the next round starts exactly where this one stopped.

    A record the ledger already carries a human decision for is not queued again: the round
    exists to move machine-only records to human-reviewed (D3), and re-asking a case the user
    has already adjudicated spends a card on a decision that is made.

    Section G is the one exception to both rules (spec section 7): it is built FIRST, from
    `conflicts` rather than from `view`'s admitted records, and BEFORE the reviewed-record
    filter below - a G card exists precisely because a human already decided the field, so the
    A-F rule that skips a reviewed record would throw away every card the re-read exists to
    raise. One card per conflicting FIELD, so a case with two disagreements gets two cards -
    the only place the "one appearance per record" rule does not hold."""
    g_cards: list[QueueCard] = []
    for c in sorted(conflicts, key=lambda c: (int(c["case_id"]), str(c["field"]))):
        rec = view.state.records.get(int(c["case_id"]))
        if rec is None:
            continue
        g_cards.append(QueueCard(int(c["case_id"]), "G", "reread_conflict", (), rec, (), (),
                                 conflict=dict(c)))
    dis = _disagreements_by_case(manifest)
    ids = admitted_case_ids(view, run_id) or list(view.state.order)
    pairs = []
    for cid in ids:
        rec = view.state.records.get(cid)
        if rec is None or view.reviewed(cid):
            continue
        pairs.append((cid, rec))
    # One fetch for every case that has a fuzzy quote, not one per case: the queue is built
    # over a whole run's admissions and the store is on the other side of a query each time.
    fuzzy_ids = [cid for cid, rec in pairs
                 if any(q.get("status") == "verified-fuzzy" for q in rec.get("quotes") or ())]
    texts = {int(t.case_id): t.norm_text for t in cases.fetch(fuzzy_ids)} if fuzzy_ids else {}
    cards: list[QueueCard] = list(g_cards)
    accepted: list[dict] = []
    for cid, rec in pairs:
        fuzzy = fuzzy_quotes(rec, texts.get(cid, "")) if cid in texts else ()
        accepted += [f for f in fuzzy if f["auto_accepted"]]
        needs_human = any(not f["auto_accepted"] for f in fuzzy)
        reasons = reasons_for(rec, disagreements=dis.get(cid, ()), fuzzy_needs_human=needs_human)
        if not reasons:
            continue
        cards.append(QueueCard(cid, SECTION_OF[reasons[0]], reasons[0], tuple(reasons[1:]),
                               rec, tuple(dis.get(cid, ())), fuzzy))
    order = {key: i for i, (_s, key, _t) in enumerate(sections)}
    cards.sort(key=lambda c: (order[c.reason], c.case_id, c.decide_field))
    return Queue(run_id, tuple(cards[:cap]), tuple(c.case_id for c in cards[cap:]), cap,
                 tuple(accepted))


def _unit_status(unit, result) -> str:
    """One queued case's checker status, from the unit that carried it (module docstring)."""
    status = getattr(unit, "status", "ok")
    if status == "parse_failed":
        return "unparsed"
    if status == "failed":
        return f"failed:{(getattr(unit, 'error', '') or 'unit failed')[:120]}"
    if (getattr(result, "record", None) or {}).get("extraction_status") == "missing":
        return "unparsed"
    return "ok"


def check_queue(queue: Queue, *, reader_factory, codebook, checker_pin, budget) -> dict[int, dict]:
    """D5's 100% checker pass over the queued records, through the driver's re-read path.

    One `plan_reread` unit per case (a unit of one), under the checker's own pin, so the
    codebook and the gate are the same ones the map ran under and the answer is comparable
    field by field. `checker_path()` is what the manifest records about this."""
    out: dict[int, dict] = {}
    if not queue.cards:
        return out
    rows = [{"case_id": c.case_id, "era_partition": "?",
             "jurisdiction": c.record.get("jurisdiction", "?")} for c in queue.cards]
    plan = plan_reread(rows, codebook.id if codebook is not None else "", checker_pin, budget,
                       worker=CHECKER_WORKER)
    outcome = reader_factory().read(plan)
    by_case: dict[int, str] = {}
    for unit in getattr(outcome, "units", ()) or ():
        for result in getattr(unit, "records", ()) or ():
            by_case[int(result.case_id)] = _unit_status(unit, result)
    for rec in outcome.records:
        cid = rec.get("case_id")
        if cid is None:
            continue
        cid = int(cid)
        out[cid] = {"values": {f: rec.get(f) for f in COMPARE_FIELDS},
                    "status": by_case.get(cid, "ok")}
    for c in queue.cards:
        out.setdefault(c.case_id, {"values": {}, "status": "missing"})
    return out
