"""Apply the user's saved reference-adjudication page to the ledger (spec section 7).

`tools/make_reference_review.py` renders the contested kit reference labels as a page that
saves its own decision state back into itself; the saved page IS the record. This reads that
state and emits ledger patches with the user as basis, exactly as pipeline/polarity_review.py's
apply path does:

  keep   -> no patch
  adopt  -> set the field to the model majority value
  set    -> set the field to the value the reviewer chose
  unsure -> a `needs-review:<field>` flag; the field is excluded from agreement for that case
            (D6) and the case stays in the kit for fidelity and for its other fields

Adopting `irrelevant` on polarity is not a polarity at all (D2): it sets `relevant` false and
nulls polarity and who_was_letting. It also wins over any value decision the same page carries
for that case on another field -- a case the reviewer put out of the corpus carries no labels,
and without this the later field would simply re-set what `irrelevant` had just nulled.

Usage:
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved <page> --dry-run
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved <page>
"""
from __future__ import annotations
import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                       # noqa: E402
from corpus_engine.ledger import LedgerView, open_ledger           # noqa: E402
from corpus_engine.ledger.fold import apply_patch                  # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                # noqa: E402

STATE_RE = re.compile(r'<script[^>]*id="review-state"[^>]*>(.*?)</script>', re.S)
FIELDS = ("polarity", "who_was_letting")
DECISIONS = ("keep", "adopt", "set", "unsure")
IRRELEVANT = "irrelevant"
FLAG_PREFIX = "needs-review:"
RUN_ID = "reference-v2"
NULLS = (None, "null", "")
VALUES = {"polarity": {"favorable", "adverse", "mixed", IRRELEVANT, None},
          "who_was_letting": {"householder", "commercial_operator", "non_resident_owner",
                              "unclear", None}}


def _value(field: str, raw):
    return None if raw in NULLS else raw


def read_state(html: str) -> list[dict]:
    """The decisions a saved page carries, validated. A page that was never saved carries
    `[]`, and applying nothing silently would look exactly like applying everything."""
    m = STATE_RE.search(html)
    if not m:
        raise ValueError("no review-state block in this page; is it the page make_reference_review.py wrote?")
    raw = json.loads(m.group(1))
    if not isinstance(raw, list) or not raw:
        raise ValueError("the page carries no decisions; save the page after deciding, then re-run")
    out = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ValueError(f"decision {i} is not an object: {d!r}")
        field = d.get("field")
        if field not in FIELDS:
            raise ValueError(f"decision {i}: field {field!r} is not one of {FIELDS}")
        decision = d.get("decision")
        if decision not in DECISIONS:
            raise ValueError(f"decision {i}: decision {decision!r} is not one of {DECISIONS}")
        value = _value(field, d.get("value"))
        if decision in ("adopt", "set") and value not in VALUES[field]:
            raise ValueError(f"decision {i}: value {value!r} is not a {field} value")
        out.append({"case_id": int(d["case_id"]), "field": field, "decision": decision,
                    "value": value, "note": (d.get("note") or "").strip()})
    return out


def _irrelevant_cases(decisions: Sequence[dict]) -> set[int]:
    """Cases the page puts out of the corpus. Their other fields are not labels any more."""
    return {int(d["case_id"]) for d in decisions
            if d["field"] == "polarity" and d["decision"] in ("adopt", "set")
            and _value("polarity", d.get("value")) == IRRELEVANT}


def patches_for(decisions: Sequence[dict], records: Mapping[int, dict], reviewer: str, *,
                field_order: Sequence[str] = FIELDS, run_id: str = RUN_ID) -> list[Patch]:
    """Ledger patches for one saved page. Deterministic: field order first (so a case
    contested on both fields is written in a fixed order), then case id."""
    basis = Basis(reviewer=reviewer, run_id=run_id)
    order = {f: i for i, f in enumerate(field_order)}
    irrelevant = _irrelevant_cases(decisions)
    out: list[Patch] = []
    for d in sorted(decisions, key=lambda d: (order.get(d["field"], 99), int(d["case_id"]))):
        cid, field, decision = int(d["case_id"]), d["field"], d["decision"]
        value = _value(field, d.get("value"))    # decisions handed straight to this
        if decision == "keep":                   # function have not been through read_state
            continue
        old = (records.get(cid) or {}).get(field)
        why = f"reference v2 adjudication: {field}"
        superseded = cid in irrelevant and not (field == "polarity" and value == IRRELEVANT)
        if superseded and decision != "unsure":
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: {field} {decision} -> {value!r} not applied; the "
                             f"same page adjudicated this case irrelevant, so it carries no {field}",
                             why, basis))
        elif decision == "unsure":
            out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why, basis))
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: {field} left unsure by the reviewer; excluded from "
                             f"agreement for this field (D6)", why, basis))
        elif field == "polarity" and value == IRRELEVANT:
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: polarity {old!r} -> irrelevant; the case is not "
                             f"relevant, so it carries no polarity", why, basis))
            out.append(Patch(cid, "set", "relevant", False, why, basis))
            out.append(Patch(cid, "set", "polarity", None, why, basis))
            out.append(Patch(cid, "set", "who_was_letting", None, why, basis))
        else:
            out.append(Patch(cid, "append", "review.notes",
                             f"reference v2: {field} {old!r} -> {value!r} ({decision})", why, basis))
            out.append(Patch(cid, "set", field, value, why, basis))
        if d.get("note"):
            out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why, basis))
        out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
    return out


def _view_with(view: LedgerView, patches: Sequence[Patch], judged: Sequence[str]) -> LedgerView:
    """The view as it would stand with `patches` in the log, without writing anything:
    the same fold the ledger runs, over a deep copy of the head state."""
    trial = copy.deepcopy(view.state)
    for p in patches:
        apply_patch(trial, p, judged=tuple(judged), cascade=p.cascade)
    return LedgerView(view.name, view.as_of, trial, list(view.patches) + list(patches), view.domain)


def _summary(view: LedgerView) -> str:
    rel, fav = view.counts().total, view.counts(polarity="favorable").total
    return (f"relevant {rel.human_reviewed + rel.machine_only} "
            f"({rel.human_reviewed} human-reviewed, {rel.machine_only} machine-only) | "
            f"favorable {fav.human_reviewed + fav.machine_only} "
            f"({fav.human_reviewed} human-reviewed, {fav.machine_only} machine-only)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--saved", required=True, help="the review page, saved with decisions in it")
    ap.add_argument("--field-order", default=",".join(FIELDS))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    decisions = read_state(Path(a.saved).read_text(encoding="utf-8"))
    dom = load_domain()
    led = open_ledger(domain=dom)
    head = led.view()
    records = head.state.records
    patches = patches_for(decisions, records, dom.reviewer_default,
                          field_order=tuple(f.strip() for f in a.field_order.split(",") if f.strip()))
    counts = {d: sum(1 for x in decisions if x["decision"] == d) for d in DECISIONS}
    print(f"{len(decisions)} decisions {counts} over "
          f"{len({d['case_id'] for d in decisions})} cases -> {len(patches)} patches", flush=True)
    if a.dry_run:
        by_case: dict[int, list[Patch]] = {}
        for p in patches:
            by_case.setdefault(p.case_id, []).append(p)
        for d in sorted(decisions, key=lambda d: (int(d["case_id"]), d["field"])):
            cid = int(d["case_id"])
            mine = [p for p in by_case.get(cid, []) if p.why.endswith(d["field"])]
            print(f"  {cid} {d['field']}: {d['decision']} "
                  f"{(records.get(cid) or {}).get(d['field'])!r} -> {d['value']!r}"
                  f"{'' if mine else '  (no patch)'}", flush=True)
            for p in mine:
                print(f"      {p.op} {p.field} = {p.new!r}", flush=True)
        print(f"before: {_summary(head)}", flush=True)
        print(f"after:  {_summary(_view_with(head, patches, dom.judged_fields))}", flush=True)
    res = led.apply(patches, note="reference v2 adjudication", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    if not a.dry_run:
        print(f"after:  {_summary(led.view())}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
