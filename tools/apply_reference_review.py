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

A reviewer who DECIDES a field also supersedes any older `needs-review:<field>` flag standing
on it (an earlier `unsure`, or one the retraction cascade wrote when the supporting quote was
dropped): the field is not unsure any more, and leaving the flag would keep the case out of
agreement for a field the user has in fact adjudicated. `adopt` and `set` therefore clear that
one flag in the same patch set, and only that one - a flag naming a different field, on a
field this page did not decide, is untouched.

A page applied before this rule existed CANNOT be fixed by re-running it: every `review.notes`
patch this tool writes interpolates the field's *current* value (`"{field} {old!r} -> {value!r}
({decision})"`), so a second run over an already-applied page re-emits a fresh note for every
decision that page made, restating the old value as if it had just changed. The ledger is
append-only, so those notes cannot be removed afterward. Use `tools/clear_superseded_flags.py`
instead - it takes its authority from the same saved page but emits only the clearing patches,
nothing else. This is why `main()` refuses to apply a page under a `--run-id` that already has
patches in the ledger unless `--force` is passed.

Adopting `irrelevant` on polarity is not a polarity at all (D2): it sets `relevant` false and
nulls polarity and who_was_letting. It also wins over any value decision the same page carries
for that case on another field -- a case the reviewer put out of the corpus carries no labels,
and without this the later field would simply re-set what `irrelevant` had just nulled.

SCOPE OF THAT RULING: `irrelevant` is enforced per page, over the decisions of the page being
applied. A LATER PAGE must also consult the ledger's current `relevant` flag -- a case an
earlier page ruled irrelevant reads `relevant: false` in `view().state.records` and must not
receive a value on any field from a later page. This tool does not do that for you; pass such
cases in already excluded, or extend `_irrelevant_cases` to union the records' `relevant` flag.

The vocabulary is NOT frozen here. Accepted values come from `corpus_engine/reader/schema.py`
(`POLARITY_VALUES`, `WHO_VALUES`, plus null), which is the schema the reader answers under, and
the fields come from the domain's `judged_fields` or `--fields`. A later page that splits a
category works unchanged once the schema carries the new value.

Usage:
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved <page> --dry-run
  .venv\\Scripts\\python tools\\apply_reference_review.py --saved <page> --run-id reference-v3
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

from corpus_engine.domain import Domain, load_domain                # noqa: E402
from corpus_engine.ledger import LedgerView, open_ledger            # noqa: E402
from corpus_engine.ledger.fold import apply_patch                   # noqa: E402
from corpus_engine.ledger.log import provisional_seqs               # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                 # noqa: E402
from corpus_engine.reader.schema import FLAG_PREFIX, POLARITY_VALUES, WHO_VALUES  # noqa: E402

STATE_RE = re.compile(r'<script[^>]*id="review-state"[^>]*>(.*?)</script>', re.S)
DECISIONS = ("keep", "adopt", "set", "unsure")
IRRELEVANT = "irrelevant"
RUN_ID = "reference-v2"
NULLS = (None, "null", "")
# The reader's schema is the vocabulary, not a literal kept in step by hand. `irrelevant` is
# the page's extra polarity option (D2), not a polarity, so it is added here and nowhere else.
VALUES = {"polarity": frozenset(POLARITY_VALUES) | {IRRELEVANT, None},
          "who_was_letting": frozenset(WHO_VALUES) | {None}}
FIELDS = tuple(VALUES)


def fields_for(domain: Domain) -> tuple[str, ...]:
    """The fields a review page may decide: the domain's judged fields, in the domain's own
    order, restricted to those this tool has a vocabulary for."""
    return tuple(f for f in domain.judged_fields if f in VALUES)


def _label(run_id: str) -> str:
    """The prose form of a run id, for `why` and note prefixes: `reference-v2` -> `reference v2`.
    Provenance rides on the run id so a second page's patches are never content-deduped
    against this one's (patch_id hashes `why` and `basis`)."""
    return run_id.replace("-", " ")


def _value(field: str, raw):
    return None if raw in NULLS else raw


def _decisions_from_list(raw, *, fields: Sequence[str],
                         values: Mapping[str, frozenset]) -> list[dict]:
    """The per-item checks every saved decision must pass, whatever container it arrived in:
    field in `fields`, decision in `DECISIONS`, and (except where `values[field]` is `None`,
    the free-text opt-out) the value in the field's own vocabulary. `read_state` calls this
    on the list it pulls out of a saved page's state block; `tools/apply_map_review.py`'s
    `--decisions` path calls it on a bare JSON list read straight off disk - one function, so
    a page and a decisions file can never be validated under different rules."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("no decisions to apply")
    out = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise ValueError(f"decision {i} is not an object: {d!r}")
        field = d.get("field")
        if field not in fields:
            raise ValueError(f"decision {i}: field {field!r} is not one of {tuple(fields)}")
        decision = d.get("decision")
        if decision not in DECISIONS:
            raise ValueError(f"decision {i}: decision {decision!r} is not one of {DECISIONS}")
        value = _value(field, d.get("value"))
        # `None` for a field means "this page has no closed vocabulary for it" - the map
        # round decides fields (`quotes`, and any field a codebook adds) whose accepted
        # values are not a frozenset this tool can hold. Absent that opt-out, the only way
        # to read such a page would be to skip validation for every field, including the
        # two the reference page does have a vocabulary for.
        allowed = values.get(field)
        # `adopt` carries no value of its own (the checker's is looked up at apply time), so a
        # null value on an adopt is not a vocabulary violation; a non-null one must still fit.
        if decision == "set" or (decision == "adopt" and value is not None):
            if allowed is not None and value not in allowed:
                raise ValueError(f"decision {i}: value {value!r} is not a {field} value")
        if False:
            raise ValueError(f"decision {i}: value {value!r} is not a {field} value")
        try:
            case_id = int(d["case_id"])
        except (KeyError, TypeError, ValueError):     # every other malformed input is a
            raise ValueError(f"decision {i}: case_id {d.get('case_id')!r} is not a case id")
        out.append({"case_id": case_id, "field": field, "decision": decision,
                    "value": value, "note": (d.get("note") or "").strip()})
    return out


def read_state(html: str, *, fields: Sequence[str] = FIELDS,
               values: Mapping[str, frozenset] = VALUES) -> list[dict]:
    """The decisions a saved page carries, validated. A page that was never saved carries
    `[]`, and applying nothing silently would look exactly like applying everything."""
    m = STATE_RE.search(html)
    if not m:
        raise ValueError("no review-state block in this page; is it the page make_reference_review.py wrote?")
    raw = json.loads(m.group(1))
    try:
        return _decisions_from_list(raw, fields=fields, values=values)
    except ValueError as exc:
        if str(exc) == "no decisions to apply":
            raise ValueError("the page carries no decisions; save the page after deciding, "
                             "then re-run") from None
        raise


def _live_flags(records: Mapping[int, dict], cid: int) -> list:
    """The review flags a case carries now. They live at `records[cid]["review"]["flags"]`;
    a case with no review block carries none rather than raising."""
    return list(((records.get(cid) or {}).get("review") or {}).get("flags") or ())


def _clear_flag(live: dict, records: Mapping[int, dict], cid: int, field: str,
                why: str, basis: Basis, tag: str) -> list[Patch]:
    """Drop the `needs-review:<field>` flag a reviewer decision on `field` supersedes.

    `review.flags` is a list, so clearing one entry is a `set` of the whole list: `live`
    carries the list as this page has left it so far, so a page that decides two flagged
    fields on one case clears both instead of the second `set` reinstating the first."""
    flag = f"{FLAG_PREFIX}{field}"
    current = live.setdefault(cid, _live_flags(records, cid))
    if flag not in current:
        return []
    kept = [f for f in current if f != flag]
    live[cid] = kept
    return [Patch(cid, "append", "review.notes",
                  f"{tag}: {field} decided by the reviewer, which supersedes the "
                  f"{flag} flag standing on it; flag cleared", why, basis),
            Patch(cid, "set", "review.flags", kept, why, basis)]


def _irrelevant_cases(decisions: Sequence[dict]) -> set[int]:
    """Cases this page puts out of the corpus. Their other fields are not labels any more.
    Page-scoped -- see SCOPE OF THAT RULING in the module docstring."""
    return {int(d["case_id"]) for d in decisions
            if d["field"] == "polarity" and d["decision"] in ("adopt", "set")
            and _value("polarity", d.get("value")) == IRRELEVANT}


def patches_for(decisions: Sequence[dict], records: Mapping[int, dict], reviewer: str, *,
                field_order: Sequence[str] = FIELDS, run_id: str = RUN_ID) -> list[Patch]:
    """Ledger patches for one saved page. Deterministic: field order first (so a case
    contested on both fields is written in a fixed order), then case id."""
    basis = Basis(reviewer=reviewer, run_id=run_id)
    tag = _label(run_id)
    order = {f: i for i, f in enumerate(field_order)}
    irrelevant = _irrelevant_cases(decisions)
    live: dict[int, list] = {}          # review.flags as this page has left them so far
    out: list[Patch] = []
    for d in sorted(decisions, key=lambda d: (order.get(d["field"], 99), int(d["case_id"]))):
        cid, field, decision = int(d["case_id"]), d["field"], d["decision"]
        value = _value(field, d.get("value"))    # decisions handed straight to this
        if decision == "keep":                   # function have not been through read_state
            continue
        old = (records.get(cid) or {}).get(field)
        why = f"{tag} adjudication: {field}"
        superseded = cid in irrelevant and not (field == "polarity" and value == IRRELEVANT)
        if superseded and decision != "unsure":
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {decision} -> {value!r} not applied; the "
                             f"same page adjudicated this case irrelevant, so it carries no {field}",
                             why, basis))
        elif decision == "unsure":
            out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why, basis))
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} left unsure by the reviewer; excluded from "
                             f"agreement for this field (D6)", why, basis))
            live.setdefault(cid, _live_flags(records, cid)).append(f"{FLAG_PREFIX}{field}")
        elif field == "polarity" and value == IRRELEVANT:
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: polarity {old!r} -> irrelevant; the case is not "
                             f"relevant, so it carries no polarity", why, basis))
            out.append(Patch(cid, "set", "relevant", False, why, basis))
            out.append(Patch(cid, "set", "polarity", None, why, basis))
            out.append(Patch(cid, "set", "who_was_letting", None, why, basis))
            out += _clear_flag(live, records, cid, field, why, basis, tag)
        else:
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {old!r} -> {value!r} ({decision})", why, basis))
            out.append(Patch(cid, "set", field, value, why, basis))
            out += _clear_flag(live, records, cid, field, why, basis, tag)
        if d.get("note"):
            out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why, basis))
        out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
    return out


def _view_with(view: LedgerView, patches: Sequence[Patch], judged: Sequence[str]) -> LedgerView:
    """The view as it would stand with `patches` in the log, without writing anything:
    the same fold the ledger runs, over a deep copy of the head state - including the seqs
    the append would assign, without which D2 reads a new patch as history (finding 1)."""
    patches = provisional_seqs(patches, view.as_of)
    trial = copy.deepcopy(view.state)
    for p in patches:
        apply_patch(trial, p, judged=tuple(judged), cascade=p.cascade)
    return LedgerView(view.name, view.as_of, trial, list(view.patches) + list(patches), view.domain)


def run_id_already_applied(view: LedgerView, run_id: str) -> bool:
    """Whether `view`'s log already carries a patch under this exact run id. Re-applying a
    run id is refused by default (see the module docstring): every patch this tool writes
    interpolates the field's current value, so a second run under the same id re-emits a
    fresh, junk note for every decision the first run already made."""
    return any(p.basis.run_id == run_id for p in view.patches)


def _summary(view: LedgerView) -> str:
    rel, fav = view.counts().total, view.counts(polarity="favorable").total
    return (f"relevant {rel.human_reviewed + rel.machine_only} "
            f"({rel.human_reviewed} human-reviewed, {rel.machine_only} machine-only) | "
            f"favorable {fav.human_reviewed + fav.machine_only} "
            f"({fav.human_reviewed} human-reviewed, {fav.machine_only} machine-only)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--saved", required=True, help="the review page, saved with decisions in it")
    ap.add_argument("--fields", default=None,
                    help="comma-separated fields the page may decide (default: the domain's)")
    ap.add_argument("--field-order", default=None,
                    help="comma-separated patch order (default: --fields order)")
    ap.add_argument("--run-id", default=RUN_ID,
                    help=f"run id carried in every patch's basis and why (default {RUN_ID})")
    ap.add_argument("--force", action="store_true",
                    help="apply even though this --run-id already has patches in the ledger. "
                         "Re-running an applied page re-emits a fresh review.notes patch for "
                         "every decision it already made (see the module docstring); normally "
                         "you want tools/clear_superseded_flags.py instead")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    dom = load_domain()
    fields = tuple(f.strip() for f in a.fields.split(",") if f.strip()) if a.fields else fields_for(dom)
    unknown = [f for f in fields if f not in VALUES]
    if unknown:
        raise SystemExit(f"no vocabulary for {unknown}; add it to corpus_engine/reader/schema.py")
    order = tuple(f.strip() for f in a.field_order.split(",") if f.strip()) if a.field_order else fields

    decisions = read_state(Path(a.saved).read_text(encoding="utf-8"), fields=fields)
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and run_id_already_applied(head, a.run_id):
        raise SystemExit(f"run-id {a.run_id!r} already has patches in the ledger; re-running "
                         f"would re-emit a fresh review.notes patch for every decision already "
                         f"applied under it. Use tools/clear_superseded_flags.py to clear a "
                         f"stale flag instead, or pass --force to apply anyway.")
    records = head.state.records
    patches = patches_for(decisions, records, dom.reviewer_default,
                          field_order=order, run_id=a.run_id)
    counts = {d: sum(1 for x in decisions if x["decision"] == d) for d in DECISIONS}
    print(f"run {a.run_id} over fields {fields}", flush=True)
    print(f"{len(decisions)} decisions {counts} over "
          f"{len({d['case_id'] for d in decisions})} cases -> {len(patches)} patches", flush=True)
    if a.dry_run:
        by_why: dict[tuple[int, str], list[Patch]] = {}
        for p in patches:
            by_why.setdefault((p.case_id, p.why), []).append(p)
        tag = _label(a.run_id)
        for d in sorted(decisions, key=lambda d: (int(d["case_id"]), d["field"])):
            cid = int(d["case_id"])
            mine = by_why.get((cid, f"{tag} adjudication: {d['field']}"), [])
            print(f"  {cid} {d['field']}: {d['decision']} "
                  f"{(records.get(cid) or {}).get(d['field'])!r} -> {d['value']!r}"
                  f"{'' if mine else '  (no patch)'}", flush=True)
            for p in mine:
                print(f"      {p.op} {p.field} = {p.new!r}", flush=True)
        print(f"before: {_summary(head)}", flush=True)
        print(f"after:  {_summary(_view_with(head, patches, dom.judged_fields))}", flush=True)
    res = led.apply(patches, note=f"{_label(a.run_id)} adjudication", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    if not a.dry_run:
        print(f"after:  {_summary(led.view())}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
