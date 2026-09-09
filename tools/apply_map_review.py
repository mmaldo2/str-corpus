r"""Apply the saved map review page to the ledger (spec section 9).

The same path tools/apply_reference_review.py takes - `read_state` on the saved page, then
reviewer-basis patches - with the map round's own vocabulary and run id:

  keep   -> no value patch (the reader's value stands), review.status human-adjudicated
  adopt  -> set the field to the CHECKER's value for that case and field
  set    -> set the field to the value the reviewer chose
  unsure -> a `needs-review:<field>` flag and a note; the field waits for a full read

`adopt` means the checker here, not a model majority: this round's second opinion is one
reader from a different family, and a card that offered no checker value offers no adopt.

SECTION F / `quotes`: `set` on `quotes` is the one decision whose value is not a vocabulary
value but the exact text of the fuzzy quote to drop (a string, or a list of strings for a card
with more than one fuzzy quote needing a decision) - copied straight off the card's `fuzzy`
block. It writes a `drop_quote` patch per quote (the same op the Stage 1 bootstrap used for its
own section B, `corpus_engine/ledger/bootstrap.py`), never a `set` on the whole `quotes` field,
because `fold.apply_patch`'s `set` op replaces the record's entire quotes list rather than
removing one quote from it. The ledger's own cascade (`fold.apply_patch`, `drop_quote`) then
nulls any judged field that dropped quote alone supported - this tool only names the quote. A
value that does not match any quote currently on the record is refused by name, not silently
ignored. `keep` on `quotes` (the quote stands as verified) and `unsure` (send the record for a
full read) need no such handling and take the same generic path every other field's `keep` and
`unsure` take.

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
every card, and `patches_for` is what actually enforces `set`/`adopt`-to-`False`-only. A
SECTION-G card whose conflicting field IS `relevant` (the re-read's `relevant_false` kind)
does not take this path: the section-G branch owns it, because that decision also has to
clear the `needs-review:relevant` flag the re-read raised and name the decision it
supersedes.

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

`--queue <json>` is REQUIRED in both modes, not only for `--decisions`. Since section G it
is no longer just a validation input: `card_index` is what tells a G decision apart from an
ordinary one, and the `--checker` default is derived from its path. A saved slice-3 page
applied without it would silently lose every G semantic and, on an `adopt`, read another
round's checker answers. An `adopt` for a case the checker file never answered for is refused
by name rather than becoming a `set <field> None`.

`--assisted-by "<name>"` marks a `--decisions` run as a first pass a model drafted: every
applied decision's `review.notes` patch gets an extra note ("first pass drafted by <name>;
confirmed by the reviewer"), and the run's own tag records the same fact in every `why`
string this run writes - so the human-reviewed tier stays honest about model assistance
rather than reading identically to a page the reviewer decided unaided.

  .venv\Scripts\python tools\apply_map_review.py --queue <json> --saved <page> --dry-run
  .venv\Scripts\python tools\apply_map_review.py --queue <json> --saved <page> \
      --checker <json> --run-id map-cycle-004-round-1
  .venv\Scripts\python tools\apply_map_review.py --queue <json> --decisions <json> \
      --checker <json> --assisted-by "GPT Astra" --dry-run
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


def _with_relevant(fields: Sequence[str]) -> tuple[str, ...]:
    """The round's decide fields plus `relevant`: a withdrawal (`relevant`/`set`/false) is
    legal on ANY card, so the page's withdraw control and a decisions file may carry it in a
    round none of whose cards decides relevance."""
    return tuple(dict.fromkeys(tuple(fields) + ("relevant",)))


def read_page(html: str, fields: Sequence[str]) -> list[dict]:
    """The decisions a saved page carries, validated against the vocabulary - one function, so
    the tool and its tests can never read a page under different rules."""
    fields = _with_relevant(fields)
    return arr.read_state(html, fields=fields, values=values_for(fields))


def read_decisions(raw, fields: Sequence[str]) -> list[dict]:
    """The decisions a `--decisions` file carries, validated by the exact same per-item rules
    a saved page's state block is: vocabulary check per field (I1), decision one of
    `keep|adopt|set|unsure`, field one of the round's decide fields. `raw` is the file's own
    parsed JSON - a bare list, not a page - so this calls the shared validator directly
    rather than going through `read_page`'s HTML parsing."""
    fields = _with_relevant(fields)
    try:
        return arr._decisions_from_list(raw, fields=fields, values=values_for(fields))
    except ValueError as exc:
        if str(exc) == "no decisions to apply":
            raise ValueError("the decisions file carries no decisions") from None
        raise


def card_index(queue_doc: Mapping) -> dict[tuple[int, str], dict]:
    """(case_id, decide_field) -> the card the round queued.

    Keyed on the FIELD as well as the case because section G queues one card per conflicting
    field, so a case can carry two cards and a case-only key would silently drop one."""
    out: dict[tuple[int, str], dict] = {}
    for cards in (queue_doc.get("sections") or {}).values():
        for c in cards or ():
            out[(int(c["case_id"]), str(c["decide_field"]))] = dict(c)
    return out


def check_against_queue(decisions: Sequence[dict], queue_doc: Mapping) -> None:
    """A `--decisions` file may only answer the questions this round actually asked: every
    case_id has to be a card in `queue_doc` (`Queue.to_json()`), deciding exactly one of that
    case's queued `decide_field`s - a model cannot answer a different field than the one the
    round queued a case on, or answer for a case the round never queued at all. Every bad
    entry is named, case id and reason, and collected rather than raised on the first one, so
    fixing the file takes one pass instead of one exit per re-run - and nothing is written
    until this passes.

    A case usually decides exactly one field, but section G can queue two cards for the same
    case (one per conflicting field, spec section 7), so this collects every `decide_field` a
    case's cards carry rather than assuming there is only one.

    `field == "relevant"` is the one exception, on ANY queued card, whatever that card's own
    `decide_field` is: a card that queues polarity or who_was_letting can still turn out, once
    the reviewer has the full opinion text in front of them, not to be a letting case at all -
    and a card cannot express that through its own decide_field, because every field on offer
    there decides polarity or who it was let by, never whether the case belongs in the corpus.
    `patches_for` is stricter still about what a `relevant` decision may say (`set` to `False`
    only); this function only clears the way for the field to reach it."""
    decide_fields: dict[int, set] = {}
    for cards in (queue_doc.get("sections") or {}).values():
        for c in cards or ():
            decide_fields.setdefault(int(c["case_id"]), set()).add(str(c["decide_field"]))
    errors = []
    for d in decisions:
        cid, field = d["case_id"], d["field"]
        want = decide_fields.get(cid)
        if want is None:
            errors.append(f"case {cid}: not a card in the round's queue manifest")
        elif field not in want and field != "relevant":
            if len(want) == 1:
                errors.append(f"case {cid}: this round's card decides {next(iter(want))!r}, "
                              f"not {field!r}")
            else:
                errors.append(f"case {cid}: this round's cards decide "
                              f"{', '.join(sorted(repr(w) for w in want))}, not {field!r}")
    if errors:
        raise ValueError("; ".join(errors))


def _adopted(checker: Mapping, case_id: int, field: str):
    """The checker's value for this case and field, or a refusal naming both.

    An `adopt` says "write what the second reader said". A checker file with no entry for the
    case, or an entry that never answered for this field (a `missing` or `failed:` status
    carries an empty `values` map), has said nothing - and `.get(field)` on it would quietly
    become `set <field> None`, which is a real value patch nulling a field nobody decided.
    Refused by name instead, so the fix is to pass the round's own checker file rather than to
    discover a nulled field in the ledger later (final review, finding 3)."""
    entry = checker.get(case_id)
    if not entry:
        raise ValueError(f"case {case_id}: {field} decided `adopt`, but this round's checker "
                         f"file has no entry for the case - there is no checker value to "
                         f"adopt. Pass the checker file this round was built with, or decide "
                         f"keep/set/unsure.")
    values = entry.get("values") or {}
    if field not in values:
        raise ValueError(f"case {case_id}: {field} decided `adopt`, but the checker's entry "
                         f"for this case answered no {field} (status "
                         f"{entry.get('status', '?')!r}) - there is no checker value to adopt.")
    return _value(field, values[field])


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
                assisted_by: str | None = None, cards: Mapping | None = None) -> list[Patch]:
    """One saved page (or decisions file) -> reviewer-basis patches. Deterministic: case id,
    then field.

    `assisted_by`, when given, marks every patch this call writes as a first pass a model
    drafted: the tag carried in every `why` string records the name, and every decided case
    also gets an extra `review.notes` patch saying so in plain words - the human-reviewed
    tier must stay honest about model assistance, not read identically to a page the
    reviewer decided unaided.

    `cards` (`card_index(queue_doc)`, keyed `(case_id, field)`), when given, is how a
    section-G decision is told apart from an ordinary one - see the branch below."""
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
        card = (cards or {}).get((cid, field)) or {}
        if card.get("section") == "G":
            # Spec section 7. The re-read disagreed with a decision this reviewer already made.
            # `keep` is the default expectation and writes no value; `set` is the reviewer
            # revising their OWN earlier decision, and the note names the decision it
            # supersedes so the ledger records a revision rather than a fresh opinion; `unsure`
            # takes the ordinary flag path. There is no `adopt`: this card's second opinion is
            # the re-read, and it is on the card.
            #
            # This test comes BEFORE the relevance-overturn branch below, and `relevant` is
            # handled inside it, because a G card's conflicting field can BE `relevant` (the
            # `relevant_false` kind) - and the overturn branch clears no flag, names no
            # superseded decision and refuses no `adopt`, so a `relevant` G card taking it
            # would stay flagged for ever (final review, finding 2).
            conflict = card.get("conflict") or {}
            was = conflict.get("human_basis") or {}
            old = (records.get(cid) or {}).get(field)
            if decision == "adopt":
                raise ValueError(f"case {cid}: a section-G card has no checker value to adopt "
                                 f"- its second opinion is the re-read's "
                                 f"{conflict.get('reread_value')!r}, already on the card. "
                                 f"Decide keep, set or unsure.")
            if decision == "keep":
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} {old!r} confirmed by the reviewer against "
                                 f"the mapper-v3 re-read's {conflict.get('reread_value')!r}",
                                 why, basis))
                out += arr._clear_flag(live, records, cid, field, why, basis, tag)
            elif decision == "set":
                value = _checked(cid, field, _value(field, d.get("value")))
                if field == "relevant":
                    # The `relevant_false` card (spec section 7) - the re-read says the case is
                    # not a letting case at all and a human had decided otherwise. `set` to
                    # False is the only meaningful decision on it (`keep` is the opposite and
                    # `True` is what already stands), and it takes the SAME cascade the
                    # ordinary relevance overturn below takes, because a case out of the corpus
                    # carries no polarity or who_was_letting either way. What it must NOT take
                    # is that branch itself: it is a revision of the reviewer's own earlier
                    # decision, the note has to name the decision it supersedes, and the
                    # `needs-review:relevant` flag the re-read raised has to be cleared here or
                    # this card is re-queued for ever (final review, findings 1 and 2).
                    if value is not False:
                        raise ValueError(f"case {cid}: relevant may only be set to False (not "
                                         f"a letting case); relevant true is what already "
                                         f"stands on this card - keep covers it")
                    if (records.get(cid) or {}).get("relevant") is False:
                        raise ValueError(f"case {cid}: already relevant false; no relevance "
                                         f"decision to overturn")
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} {old!r} -> {value!r}; the reviewer revises "
                                 f"their own earlier decision "
                                 f"({was.get('reviewer') or 'reviewer'}, run "
                                 f"{was.get('run_id') or '?'}, seq {conflict.get('human_at')}) "
                                 f"after the mapper-v3 re-read read it as "
                                 f"{conflict.get('reread_value')!r}", why, basis))
                out.append(Patch(cid, "set", field, value, why, basis))
                if field == "relevant":
                    out.append(Patch(cid, "set", "polarity", None, why, basis))
                    out.append(Patch(cid, "set", "who_was_letting", None, why, basis))
                out += arr._clear_flag(live, records, cid, field, why, basis, tag)
            else:                                                   # unsure
                out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why,
                                 basis))
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} left unsure by the reviewer; the human value "
                                 f"stands and the re-read's "
                                 f"{conflict.get('reread_value')!r} waits for a full read",
                                 why, basis))
                live.setdefault(cid, arr._live_flags(records, cid)).append(f"{FLAG_PREFIX}{field}")
            if assisted_by:
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: first pass drafted by {assisted_by}; "
                                 + ("left unsure, not confirmed" if decision == "unsure"
                                    else "confirmed by the reviewer"), why, basis))
            if d.get("note"):
                out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why,
                                 basis))
            if decision != "unsure":
                out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
            continue
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
            #
            # A section-G card whose own conflicting field is `relevant` never reaches here -
            # the G branch above handles it, with the same cascade plus the flag clearing and
            # the superseded-decision note that only a G card owes (finding 2).
            if decision == "adopt":
                value = _adopted(checker, cid, field)
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
            value = _adopted(checker, cid, field)
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
        elif field == "quotes" and decision == "set":
            # Section F decides `quotes`: `set` drops a fuzzy quote the reviewer judged a real
            # mismatch, not routine OCR noise - the same `drop_quote` op the Stage 1 bootstrap
            # used for its own section B (corpus_engine/ledger/bootstrap.py). `value` is the
            # quote's own exact text (as shown on the card's `fuzzy` block), or a list of texts
            # when a card carries more than one fuzzy quote needing a decision - each is
            # dropped by its own patch, never by a blanket "drop everything fuzzy on this
            # record", because a record can carry an already-auto-accepted fuzzy quote (trivial
            # OCR noise) alongside the one a human is actually deciding, and only the decided
            # quote may go. `apply_patch`'s own cascade (fold.py) then nulls any judged field
            # that quote alone supported - this tool only has to name the quote, not the
            # fields it was propping up.
            texts = value if isinstance(value, list) else [value]
            if not texts or any(not isinstance(t, str) or not t for t in texts):
                raise ValueError(f"case {cid}: quotes set value must be the exact text (or a "
                                 f"list of texts) of the fuzzy quote(s) to drop")
            current = {q.get("text") for q in (records.get(cid) or {}).get("quotes") or ()}
            unknown = [t for t in texts if t not in current]
            if unknown:
                raise ValueError(f"case {cid}: quotes set value {unknown!r} does not match any "
                                 f"quote text currently on the record")
            for t in texts:
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: quotes fuzzy match dropped by the reviewer: {t!r}",
                                 why, basis))
                out.append(Patch(cid, "drop_quote", "quotes", t, why, basis))
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
    # A record withdrawn as not a letting case carries no open field question: every
    # `needs-review:*` flag still standing on it is moot and is cleared here, whichever path
    # withdrew it (round 1b, 2026-09-09: four withdrawn records kept their re-read conflict
    # flags and came back as section-G cards in the next round).
    withdrawn = sorted({p.case_id for p in out
                        if p.op == "set" and p.field == "relevant" and p.new is False})
    for cid in withdrawn:
        standing = live.setdefault(cid, arr._live_flags(records, cid))
        if not standing:
            continue
        why = "withdrawn record: field flags moot"
        out.append(Patch(cid, "append", "review.notes",
                         f"{tag}: the reviewer withdrew this record as not a letting case; its "
                         f"open flags ({', '.join(standing)}) are moot and are cleared", why, basis))
        out.append(Patch(cid, "set", "review.flags", [], why, basis))
        live[cid] = []
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--saved", default=None, help="the review page, saved with decisions in it")
    mode.add_argument("--decisions", default=None,
                      help="a JSON list of {case_id, field, decision, value, note} - the same "
                           "schema the page embeds - for a first pass done from files instead "
                           "of the self-saving page")
    ap.add_argument("--queue", required=True,
                    help="the round's queue manifest (Queue.to_json()). REQUIRED in both "
                         "modes: it checks every --decisions entry against a real card, it "
                         "is what tells a section-G decision apart from an ordinary one, and "
                         "it derives the --checker default")
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
    # Hoisted so both --saved and --decisions runs can index the round's own cards
    # (card_index, below) - a section-G decision needs its card to be told apart from an
    # ordinary one, and --saved has no other reason to read the queue manifest at all.
    if not Path(a.queue).exists():
        sys.exit(f"{a.queue}: no such queue manifest")
    queue_doc = json.loads(Path(a.queue).read_text(encoding="utf-8"))
    if a.saved:
        try:
            decisions = read_page(Path(a.saved).read_text(encoding="utf-8"), fields)
        except ValueError as exc:               # a page this tool will not read is not a page
            sys.exit(f"{a.saved}: {exc}")       # to apply half of; nothing is written
    else:
        try:
            raw = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
            decisions = read_decisions(raw, fields)
            check_against_queue(decisions, queue_doc)
        except ValueError as exc:
            sys.exit(f"{a.decisions}: {exc}")
    if not a.checker:
        cand = Path(a.queue).with_name(Path(a.queue).stem + "-checker.json")
        if cand.exists():
            a.checker = str(cand)           # the documented default: <queue>-checker.json
    checker = json.loads(Path(a.checker).read_text(encoding="utf-8")) if a.checker else {}
    led = open_ledger(domain=dom)
    head = led.view()
    if not a.force and arr.run_id_already_applied(head, a.run_id):
        sys.exit(f"run-id {a.run_id!r} already has patches in the ledger; a second apply would "
                 f"re-emit a fresh review.notes patch for every decision. Pass --force only if "
                 f"that is really what you want.")
    patches = patches_for(decisions, head.state.records, dom.reviewer_default,
                          run_id=a.run_id, checker=checker, assisted_by=a.assisted_by,
                          cards=card_index(queue_doc))
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
