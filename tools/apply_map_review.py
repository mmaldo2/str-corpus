r"""Apply the saved map review page to the ledger (spec section 9).

The same path tools/apply_reference_review.py takes - `read_state` on the saved page, then
reviewer-basis patches - with the map round's own vocabulary and run id:

  keep   -> no value patch (the reader's value stands), review.status human-adjudicated
  adopt  -> set the field to the CHECKER's value for that case and field
  set    -> set the field to the value the reviewer chose
  unsure -> a `needs-review:<field>` flag and a note; the field waits for a full read

`adopt` means the checker here, not a model majority: this round's second opinion is one
reader from a different family, and a card that offered no checker value offers no adopt.

A decision on a field also clears any `needs-review:<field>` flag it supersedes, through
`apply_reference_review._clear_flag`, so the two tools can never disagree about that rule.

RELEVANCE OVERTURN (round-1b addendum, extended in round 2): every card in a map round decides
polarity or who_was_letting - or, since round 2, `relevant` itself on a section-C card the
checker disputed relevance on - so most cards have no way to say the case is not a letting
case at all except through this path. On ANY card, whatever its own decide_field,
`{"field": "relevant", "decision": "set", "value": false}` (also spelled `"False"`) says
exactly that, and round 2 adds the `adopt` counterpart for a section-C card whose OWN
decide_field is `relevant`: `{"field": "relevant", "decision": "adopt"}` takes the checker's
value for it - always False, since a queued record's relevant is already True and that is the
only value a checker can have disagreed with it about. Either spelling writes the same
patches `apply_reference_review.patches_for` writes for its `irrelevant` polarity adoption -
`relevant` false, `polarity` and `who_was_letting` null, a `review.notes` line,
`review.status` human-adjudicated - because a case out of the corpus carries no polarity or
who_was_letting either way. `relevant` true is not an accepted decision (the reader's value is
already true for every queued case, so `keep` already covers confirming it), and a case
already `relevant` false has no relevance left to overturn. This is the one field a decisions
file may name besides the card's own decide_field; `check_against_queue` waves it through on
every card, and `patches_for` is what actually enforces `set`/`adopt`-to-`False`-only.

EVERY decided value is validated against the field's own vocabulary before any patch is built
(final-review I1). The ledger performs no value validation of its own - `fold.apply_patch`
raises `UnknownField` for an unknown PATH, never for an unknown value - so this is the only
guard between a saved page and the published counts, and `polarity` is the field the headline
`counts(polarity="favorable")` slices on. The vocabulary is read from
`corpus_engine/reader/schema.py`, never re-declared here, so a codebook that adds a value works
without editing this tool; `holding_summary` (free text) and `quotes` (kept or sent for a full
read, never re-typed) are the only two fields with no closed vocabulary, and they are opted out
by name rather than by turning the check off for everything. The check runs twice, deliberately:
`read_state` refuses a bad value on the page, and `patches_for` refuses one again on the value
that will actually be written - which is the only place an `adopt` is caught, because an adopt
takes the CHECKER's value and never the page's.

Re-applying a page is refused for the same reason the reference tool refuses it: every
`review.notes` patch here interpolates the field's CURRENT value, so a second run over an
already-applied page re-emits a fresh note restating the old value as if it had just changed,
and the ledger is append-only. Pass `--force` only if that is really what you want.

`--decisions <json>` is the alternative to `--saved <html>`, for a first pass done by another
model working from files (the exported cards) rather than the self-saving page: a bare JSON
list in the same schema the page's state block embeds - `{case_id, field, decision, value,
note}` - read and validated by exactly the same per-item rules a saved page's state is
(`apply_reference_review._decisions_from_list`). It is checked against the round's own queue
manifest before anything else runs: every case_id must be a card the round actually queued,
deciding exactly that card's `decide_field`, or the whole file is refused - case id and
reason, before a single patch is built - because a decisions file is free-form text a model
wrote, not a page whose every field was rendered from the queue in the first place. Exactly
one of `--saved` / `--decisions` is required.

`--assisted-by "<name>"` marks a `--decisions` run as a first pass a model drafted: every
applied decision's `review.notes` patch gets an extra note ("first pass drafted by <name>;
confirmed by the reviewer"), and the run's own tag records the same fact in every `why`
string this run writes - so the human-reviewed tier stays honest about model assistance
rather than reading identically to a page the reviewer decided unaided.

  .venv\Scripts\python tools\apply_map_review.py --saved <page> --checker <json> --dry-run
  .venv\Scripts\python tools\apply_map_review.py --saved <page> --checker <json> \
      --run-id map-cycle-004-round-1
  .venv\Scripts\python tools\apply_map_review.py --decisions <json> --checker <json> \
      --assisted-by "GPT Astra" --dry-run
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                        # noqa: E402
from corpus_engine.ledger import open_ledger                        # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                 # noqa: E402
from corpus_engine.reader.schema import (CHARACTERIZATION_VALUES,   # noqa: E402
                                         DURATION_VALUES, FLAG_PREFIX,
                                         OWNER_FREEDOM_VALUES, POLARITY_VALUES,
                                         RESTRICTION_VALUES, UNDER_THIRTY_VALUES, WHO_VALUES)

_spec = importlib.util.spec_from_file_location("apply_reference_review",
                                               ROOT / "tools" / "apply_reference_review.py")
arr = importlib.util.module_from_spec(_spec)                        # the flag-clearing rule and
_spec.loader.exec_module(arr)                                       # the state reader live once

DECISIONS = ("keep", "adopt", "set", "unsure")
RUN_ID = "map-cycle-004-round-1"
# Section F decides `quotes`, which is not a judged field and carries no vocabulary: the
# reviewer keeps the fuzzy quote or sends the record for a full read, never re-types it.
EXTRA_FIELDS = ("quotes",)
NULLS = (None, "null", "")
# The page spells `relevant` as a string because an HTML radio has no other kind of value
# (`make_map_review.VOCAB`), while the record, the checker and `counts` all carry a real
# boolean. Both spellings are accepted and the string is converted, so a card that puts a case
# out of the corpus writes `False` rather than the truthy string `"false"`. Both cases of the
# string survive too (`"false"`/`"False"`) - a relevance-overturn decision (below) is typed by
# a model reading files, not clicked off a radio, and is not worth refusing over capitalization.
BOOLS = {"true": True, "false": False}
# The vocabulary each field is validated against (I1), read from the reader's schema. `None`
# means "this field has no closed vocabulary" - the opt-out `apply_reference_review.read_state`
# documents - and exactly two fields get it. `relevant`'s vocabulary carries both letter cases
# of the string so a differently-capitalized value is refused by `_checked`'s message, not by
# the earlier, less specific vocabulary gate in `_decisions_from_list`.
VALUES = {"relevant": frozenset({"true", "false", "True", "False", True, False}),
          "polarity": frozenset(POLARITY_VALUES) | {None},
          "who_was_letting": frozenset(WHO_VALUES) | {None},
          "duration_of_occupancy": frozenset(DURATION_VALUES) | {None},
          "characterization": frozenset(CHARACTERIZATION_VALUES) | {None},
          "under_thirty_days": frozenset(UNDER_THIRTY_VALUES) | {None},
          "owner_freedom_characterization": frozenset(OWNER_FREEDOM_VALUES) | {None},
          "restriction_nature": frozenset(RESTRICTION_VALUES) | {None},
          "holding_summary": None,
          "quotes": None}


def _value(field: str, raw):
    if raw in NULLS:
        return None
    return BOOLS.get(raw.lower(), raw) if field == "relevant" and isinstance(raw, str) else raw


def values_for(fields: Sequence[str]) -> dict:
    """The `values` map `read_state` validates this page against.

    A field with no entry in `VALUES` is refused rather than waved through: it is either a
    codebook this tool has not been taught or a tampered page, and passing `None` for it would
    be the very opt-out I1 exists to close."""
    unknown = [f for f in fields if f not in VALUES]
    if unknown:
        raise ValueError(f"no vocabulary for {unknown}; teach tools/apply_map_review.py "
                         f"before a page may decide them")
    return {f: VALUES[f] for f in fields}


def read_page(html: str, fields: Sequence[str]) -> list[dict]:
    """The decisions a saved page carries, validated against the vocabulary - one function, so
    the tool and its tests can never read a page under different rules."""
    return arr.read_state(html, fields=tuple(fields), values=values_for(fields))


def read_decisions(raw, fields: Sequence[str]) -> list[dict]:
    """The decisions a `--decisions` file carries, validated by the exact same per-item rules
    a saved page's state block is: vocabulary check per field (I1), decision one of
    `keep|adopt|set|unsure`, field one of the round's decide fields. `raw` is the file's own
    parsed JSON - a bare list, not a page - so this calls the shared validator directly
    rather than going through `read_page`'s HTML parsing."""
    try:
        return arr._decisions_from_list(raw, fields=tuple(fields), values=values_for(fields))
    except ValueError as exc:
        if str(exc) == "no decisions to apply":
            raise ValueError("the decisions file carries no decisions") from None
        raise


def check_against_queue(decisions: Sequence[dict], queue_doc: Mapping) -> None:
    """A `--decisions` file may only answer the questions this round actually asked: every
    case_id has to be a card in `queue_doc` (`Queue.to_json()`), deciding exactly that card's
    `decide_field` - a model cannot answer a different field than the one the round queued a
    case on, or answer for a case the round never queued at all. Every bad entry is named,
    case id and reason, and collected rather than raised on the first one, so fixing the file
    takes one pass instead of one exit per re-run - and nothing is written until this passes.

    `field == "relevant"` is the one exception, on ANY queued card, whatever that card's own
    `decide_field` is: a card that queues polarity or who_was_letting can still turn out, once
    the reviewer has the full opinion text in front of them, not to be a letting case at all -
    and a card cannot express that through its own decide_field, because every field on offer
    there decides polarity or who it was let by, never whether the case belongs in the corpus.
    `patches_for` is stricter still about what a `relevant` decision may say (`set` to `False`
    only); this function only clears the way for the field to reach it."""
    decide_field = {int(c["case_id"]): c["decide_field"]
                    for cards in (queue_doc.get("sections") or {}).values() for c in cards}
    errors = []
    for d in decisions:
        cid, field = d["case_id"], d["field"]
        want = decide_field.get(cid)
        if want is None:
            errors.append(f"case {cid}: not a card in the round's queue manifest")
        elif field != want and field != "relevant":
            errors.append(f"case {cid}: this round's card decides {want!r}, not {field!r}")
    if errors:
        raise ValueError("; ".join(errors))


def _checked(case_id: int, field: str, value):
    """The value about to be written, or a refusal naming the case and the field. This catches
    what `read_state` cannot: an `adopt` writes the CHECKER's value, not the page's."""
    allowed = VALUES.get(field)
    if allowed is not None and value not in allowed:
        raise ValueError(f"case {case_id}: {value!r} is not a {field} value "
                         f"({', '.join(sorted(repr(v) for v in allowed))})")
    return value


def patches_for(decisions: Sequence[dict], records: Mapping[int, dict], reviewer: str, *,
                run_id: str = RUN_ID, checker: Mapping | None = None,
                assisted_by: str | None = None) -> list[Patch]:
    """One saved page (or decisions file) -> reviewer-basis patches. Deterministic: case id,
    then field.

    `assisted_by`, when given, marks every patch this call writes as a first pass a model
    drafted: the tag carried in every `why` string records the name, and every decided case
    also gets an extra `review.notes` patch saying so in plain words - the human-reviewed
    tier must stay honest about model assistance, not read identically to a page the
    reviewer decided unaided."""
    basis = Basis(reviewer=reviewer, run_id=run_id)
    tag = arr._label(run_id)
    if assisted_by:
        tag = f"{tag} (assisted by {assisted_by})"
    checker = {int(k): v for k, v in (checker or {}).items()}
    live: dict[int, list] = {}          # review.flags as this page has left them so far
    out: list[Patch] = []
    for d in sorted(decisions, key=lambda d: (int(d["case_id"]), d["field"])):
        cid, field, decision = int(d["case_id"]), d["field"], d["decision"]
        if decision not in DECISIONS:
            raise ValueError(f"case {cid}: decision {decision!r} is not one of {DECISIONS}")
        why = f"{tag}: {field}"
        if field == "relevant" and decision in ("set", "adopt"):
            # The relevance-overturn path (round-1b, spec addendum), and round 2's extension
            # of it: on ANY card, whatever its own decide_field, a reviewer with the full
            # opinion in front of them may rule the case is not a letting case at all - by
            # `set`ting relevant to False directly, or (round 2) by a section-C card whose OWN
            # decide_field is `relevant` `adopt`ing the checker's disagreement, which is only
            # ever False (a queued record's relevant is already True, so the only relevance
            # value a checker can disagree with it about is False). Either way `relevant` true
            # is not accepted here - the reader's value is already true for every queued case,
            # and `keep` already covers confirming it - so this branch only ever writes
            # `False`, never a value patch to `True`. It emits the same patches the reference
            # review's `irrelevant` adoption does (`apply_reference_review.patches_for`): the
            # case carries no polarity or who_was_letting once it is out of the corpus.
            if decision == "adopt":
                value = _value(field, ((checker.get(cid) or {}).get("values") or {}).get(field))
            else:
                value = _value(field, d.get("value"))
            if value is not False:
                raise ValueError(f"case {cid}: relevant may only be set to False (not a "
                                 f"letting case); relevant true is not accepted as a "
                                 f"decision - keep covers it")
            if (records.get(cid) or {}).get("relevant") is False:
                raise ValueError(f"case {cid}: already relevant false; no relevance decision "
                                 f"to overturn")
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: relevance overturned by the reviewer: {d.get('note') or ''}",
                             why, basis))
            out.append(Patch(cid, "set", "relevant", False, why, basis))
            out.append(Patch(cid, "set", "polarity", None, why, basis))
            out.append(Patch(cid, "set", "who_was_letting", None, why, basis))
            if assisted_by:
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: first pass drafted by {assisted_by}; confirmed by "
                                 f"the reviewer", why, basis))
            out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
            continue
        old = (records.get(cid) or {}).get(field)
        if decision == "adopt":
            value = _value(field, ((checker.get(cid) or {}).get("values") or {}).get(field))
        else:
            value = _value(field, d.get("value"))
        if decision in ("adopt", "set"):
            _checked(cid, field, value)
        if decision == "unsure":
            out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why, basis))
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} left unsure by the reviewer; the reader's value "
                             f"stands and the field waits for a full read", why, basis))
            live.setdefault(cid, arr._live_flags(records, cid)).append(f"{FLAG_PREFIX}{field}")
        elif decision == "keep":
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {old!r} confirmed by the reviewer", why, basis))
            out += arr._clear_flag(live, records, cid, field, why, basis, tag)
        else:                                   # adopt | set
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: {field} {old!r} -> {value!r} ({decision})", why, basis))
            out.append(Patch(cid, "set", field, value, why, basis))
            out += arr._clear_flag(live, records, cid, field, why, basis, tag)
        if assisted_by:
            out.append(Patch(cid, "append", "review.notes",
                             f"{tag}: first pass drafted by {assisted_by}; "
                             + ("left unsure, not confirmed" if decision == "unsure"
                                else "confirmed by the reviewer"), why, basis))
        if d.get("note"):
            out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why, basis))
        # Only a decided card is human-adjudicated. An `unsure` card keeps its machine-only
        # status: its flag says a human looked and declined to decide, and LedgerView.reviewed()
        # must not count it in the human-reviewed tier (two-tier claim, D3).
        if decision != "unsure":
            out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--saved", default=None, help="the review page, saved with decisions in it")
    mode.add_argument("--decisions", default=None,
                      help="a JSON list of {case_id, field, decision, value, note} - the same "
                           "schema the page embeds - for a first pass done from files instead "
                           "of the self-saving page")
    ap.add_argument("--queue", default="runs/cycle-004-shard-01/review-round-1.json",
                    help="the round's queue manifest, to check every --decisions entry "
                         "against a real card (ignored for --saved)")
    ap.add_argument("--checker", default=None,
                    help="the check_queue JSON this round was built with")
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--fields", default=None,
                    help="comma-separated fields the page may decide (default: the domain's)")
    ap.add_argument("--assisted-by", default=None,
                    help="a first-pass model's name (--decisions only): every applied "
                         "decision's review.notes patch records that it was drafted by this "
                         "name and confirmed by the reviewer")
    ap.add_argument("--force", action="store_true",
                    help="apply even though this --run-id already has patches in the ledger")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    dom = load_domain()
    fields = (tuple(f.strip() for f in a.fields.split(",") if f.strip()) if a.fields
              else tuple(dom.judged_fields) + EXTRA_FIELDS)
    if a.saved:
        try:
            decisions = read_page(Path(a.saved).read_text(encoding="utf-8"), fields)
        except ValueError as exc:               # a page this tool will not read is not a page
            sys.exit(f"{a.saved}: {exc}")       # to apply half of; nothing is written
    else:
        try:
            raw = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
            decisions = read_decisions(raw, fields)
            queue_doc = json.loads(Path(a.queue).read_text(encoding="utf-8"))
            check_against_queue(decisions, queue_doc)
        except ValueError as exc:
            sys.exit(f"{a.decisions}: {exc}")
    checker = json.loads(Path(a.checker).read_text(encoding="utf-8")) if a.checker else {}
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and arr.run_id_already_applied(head, a.run_id):
        sys.exit(f"run-id {a.run_id!r} already has patches in the ledger; a second apply would "
                 f"re-emit a fresh review.notes patch for every decision. Pass --force only if "
                 f"that is really what you want.")
    patches = patches_for(decisions, head.state.records, dom.reviewer_default,
                          run_id=a.run_id, checker=checker, assisted_by=a.assisted_by)
    counts = {d: sum(1 for x in decisions if x["decision"] == d) for d in DECISIONS}
    print(f"{len(decisions)} decisions {counts} over "
          f"{len({d['case_id'] for d in decisions})} cases -> {len(patches)} patches", flush=True)
    if a.dry_run:
        for d in sorted(decisions, key=lambda d: (int(d["case_id"]), d["field"])):
            cid = int(d["case_id"])
            print(f"  {cid} {d['field']}: {d['decision']} "
                  f"{(head.state.records.get(cid) or {}).get(d['field'])!r} -> "
                  f"{_value(d['field'], d['value'])!r}", flush=True)
    res = led.apply(patches, note=f"{arr._label(a.run_id)} map review", dry_run=a.dry_run)
    print(f"{len(res.applied)} applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    if not a.dry_run:
        v = led.view()
        print(f"after: relevant {v.counts().total.as_claim('records')} | "
              f"favorable {v.counts(polarity='favorable').total.as_claim('records')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
