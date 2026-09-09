"""Admission: a map's accepted records become machine-only ledger records (spec section 8).

Three rules shape this module.

The record is re-derived from the RESPONSE CACHE, not from the extraction file the runner
wrote. The extraction files are gitignored, derived and editable; the cache entry is the
provider's own answer, addressed by a key the manifest recorded. Re-parsing and re-gating it
here means the admitted value is exactly what the gate accepted, and it means admission can be
re-run after a gate change without buying anything.

A unit's manifest row carries EVERY key that unit used - the whole-unit key, plus the `-a`/`-b`
split-half keys when a parse failure split it - so admission reproduces the driver's own
fallback without re-deriving any key of its own: the whole unit's records when the whole
parsed, the halves' records otherwise. A manifest written before that amendment records a
single string; that shape is still accepted, and only then are the half keys re-derived here
(`_derived_half_keys`), which is the one path in this module that has to agree with the driver
about how a key is composed.

The judged values arrive as `set` patches with the D8 reader basis rather than riding inside
the `admit` body. `admit` never checks `Basis.can_judge()`, so a value carried only in the body
would enter the ledger with no judging authority recorded against it; a `set` under
`Basis(model=..., prompt_version=..., run_id=...)` is what makes the record a machine-only
judgment with provenance (D3), and what a later human decision supersedes. The same basis is
put on the `admit` patch too, because `fold._record_admitting_prompt` keys the quote-support
rule off the LATEST admit patch carrying a prompt_version: an admit under a bare basis would
leave a mapper-v3 record folding under the mapper-v1 three-field cascade (D7).

Only the JUDGMENT is the model's. The admitted record's identity - `cite`, `court`,
`jurisdiction`, `year` - is taken from the store row the gate ran against, never from the
record the reader wrote. Every one of those is an optional, nullable, model-emitted property of
the mapper-v3 schema that the quote gate does not touch, so a hallucinated citation, a
misremembered court, or a `jurisdiction` that disagrees with the cell the batch came from would
otherwise become that record's identity in the ledger - and `jurisdiction` and `year` are
exactly the fields the published counts and the era analysis slice on. `worker`, `batch_id` and
`schema_version` are stamped from what admission KNOWS for the same reason.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Mapping, Sequence

from corpus_engine.ledger.fold import FLAG_PREFIX
from corpus_engine.ledger.types import Basis, Patch
# The section-G card's shape belongs to the queue that renders it (T7). Imported rather than
# re-spelled here: one shape, two producers, and a fourth key added at one end only would be a
# card the other end cannot read.
from corpus_engine.mapper.queue import CONFLICT_KEYS, CONFLICT_KINDS
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.driver import COMPARE_FIELDS, schema_for
from corpus_engine.reader.gate import gate_unit
from corpus_engine.reader.model import Request, Unit, effort_of
from corpus_engine.reader.parse import parse_records, split_unit
from corpus_engine.reader.render import render_unit
from corpus_engine.reader.schema import record_schema, schema_sha

# The value fields, in patch order. After D7 every name here is BOTH the reader's and the
# ledger's; there is no translation table left to drift.
MAPPER_FIELDS = ("relevance_score", "polarity", "who_was_letting", "duration_of_occupancy",
                 "characterization", "under_thirty_days", "owner_freedom_characterization",
                 "restriction_nature", "holding_summary", "doctrinal_concepts",
                 "new_terms_observed")
# What the `admit` body carries: identity, the relevance verdict, the verified quotes, and the
# gate's own account of what it did. Never a judged value.
IDENTITY_FIELDS = ("case_id", "schema_version", "cite", "court", "jurisdiction", "year",
                   "relevant", "quotes", "worker", "batch_id", "extraction_status",
                   "nulled_fields", "gate_notes")
# D8's prompt_version is `mapper-v3:<sha12>`, and `fold.supported_fields` raises on a version
# segment it does not know. Admission is therefore only defined for a mapper-v3 map: a v1/v2
# manifest is refused here rather than admitted under a support rule it was never read under.
CODEBOOK_ID = "mapper-v3"
# Every record admitted here is by construction a mapper-v3 record, so the version is stamped
# rather than carried through from whatever the model happened to put in the field.
SCHEMA_VERSION = 3
WHY = "map admission"
# The worker the map was read under. It is what the record is stamped with, and it is what the
# pre-amendment key derivation has to re-render the prompt as. LIMITATION: the manifest does not
# record the worker (`MapRunner.worker` is constructor-configurable and `_manifest` omits it), so
# a map read under any other worker would be stamped wrongly here and, on the compatibility path
# only, would derive half keys that address nothing. `worker_of` reads the manifest first so the
# fix is a manifest field, not a change here.
WORKER = "reader"


def worker_of(manifest: Mapping) -> str:
    """The worker the map was read under: the manifest's own, when it records one (see WORKER)."""
    return str(manifest.get("worker") or WORKER)


def prompt_version(codebook_sha: str) -> str:
    """D8. The codebook version plus the first 12 of its sha, so the support rule
    (`fold.supported_fields`) resolves on the version and the provenance names the file."""
    return f"{CODEBOOK_ID}:{str(codebook_sha)[:12]}"


def basis_for(manifest: Mapping) -> Basis:
    """D8: model "<model>@<provider>", prompt_version "mapper-v3:<sha12>", run_id the run.

    Both halves of the model string come from the pin label the manifest recorded
    (`claude-cli/claude-opus-5@claude-cli:-` -> `claude-opus-5@claude-cli`) rather than being
    spelled here, so a map read under some other pin says so instead of claiming the
    subscription's."""
    codebook_id = str(manifest.get("codebook_id") or "")
    if codebook_id != CODEBOOK_ID:
        raise ValueError(f"admission is defined for {CODEBOOK_ID} only; this map was read under "
                         f"{codebook_id!r}, whose quote-support rule is not mapper-v3's")
    label = str(manifest.get("reader_pin") or "")
    model_id, _, rest = label.partition("@")
    provider = rest.partition(":")[0]
    if not provider or provider == "-":
        provider = model_id.rpartition("/")[0] or "-"
    return Basis(model=f"{model_id.rpartition('/')[2]}@{provider}",
                 prompt_version=prompt_version(str(manifest.get("codebook_sha") or "")),
                 run_id=str(manifest.get("run_id") or ""))


@dataclass(frozen=True)
class AdmittedRecord:
    case_id: int
    cell_key: str
    batch_id: str
    # The key that produced THIS record: the whole-unit key, or the `-a`/`-b` key when the
    # unit's response would not parse and the gate ran over a half. Recording the half rather
    # than the unit is what makes the note re-derivable on its own.
    cache_key: str
    record: dict
    checker_note: str = ""


def _cell_units(manifest: Mapping):
    """(cell_key, unit_id, [cache keys]) for every unit the manifest recorded a key for, in
    the manifest's own cell order. A unit row carries a list of keys after the Task-5 review
    amendment and a bare string before it; both are read."""
    cells = manifest.get("cells") or {}
    for cell_key in (manifest.get("cell_order") or list(cells)):
        cell = cells.get(cell_key) or {}
        for unit_id, keys in (cell.get("cache_keys") or {}).items():
            if isinstance(keys, str):
                keys = [keys] if keys else []
            yield cell_key, unit_id, [str(k) for k in (keys or ()) if k]


def _row_completed(row: Mapping) -> bool:
    """`runner.unit_completed`, read off the row the runner wrote instead of off a live
    `UnitResult`: status "ok", or "partial_parse" with at least one case read."""
    return (row.get("status") == "ok"
            or (row.get("status") == "partial_parse" and (row.get("cases_read") or 0) > 0))


def unanswered_cases(manifest: Mapping, *, batch_source, cache: ResponseCache) -> dict:
    """Cell key -> the case ids no cached response of that cell answers for (I3).

    The same question `runner.lost_cases` answers off the unit rows, asked of the CACHE - which
    is the only place that can answer it for a manifest written before `cases_lost` existed.
    Such a row records how many cases its unit dropped (`status_counts.missing: 9` on
    `cycle-004-shard-01-batch-146`) but not which, and the ids are what a retry needs.

    It is `records_from_manifest` without the gate: parse the whole unit's cached response,
    fall back to the two split halves exactly as the driver did, and take the difference
    against the batch's own case ids. No case texts, no store, nothing bought.

    Cases answered by ANY unit of the cell are subtracted, so a case a retry unit has since
    recovered is not offered again, and running this twice over the same map plans the same
    work twice only if that work is genuinely still undone. Units that did not complete
    contribute nothing: those are failed units, and a resume re-reads the whole batch."""
    cells = manifest.get("cells") or {}
    out: dict[str, list[int]] = {}
    for cell_key in (manifest.get("cell_order") or list(cells)):
        cell = cells.get(cell_key) or {}
        keys_by_unit = cell.get("cache_keys") or {}
        missing: list[int] = []
        answered: set[int] = set()
        for row in cell.get("units") or []:
            unit_id = row.get("unit_id")
            if not unit_id or unit_id not in batch_source:
                continue
            keys = keys_by_unit.get(unit_id) or []
            keys = [keys] if isinstance(keys, str) else [str(k) for k in keys if k]
            unit = _unit_for(batch_source.get(unit_id))
            if parse_records(_cached_text(cache, keys[0] if keys else "") or "",
                             unit.case_ids) is not None:
                answered.update(unit.case_ids)
                continue
            halves = [h for h in split_unit(unit) if h.case_ids]
            got: set[int] = set()
            for half, hkey in zip(halves, list(keys[1:]) + [""] * len(halves)):
                if parse_records(_cached_text(cache, hkey) or "", half.case_ids) is not None:
                    got.update(half.case_ids)
            answered.update(got)
            if _row_completed(row):
                missing.extend(c for c in unit.case_ids if c not in got)
        rest = sorted(set(missing) - answered)
        if rest:
            out[cell_key] = rest
    return out


def checker_notes(manifest: Mapping, *, case_ids_by_unit: Mapping | None = None) -> dict[int, str]:
    """One `review.notes` line per case in a unit the checker was sampled on (D8).

    A disagreement names the field and both answers. A case in a sampled unit with no
    disagreement against it gets the WEAKER claim the manifest can actually support: the unit
    was sampled and nothing was recorded against this case. It deliberately does not say the
    checker agreed - `checker_status == "ok"` means the checker's response PARSED, not that it
    carried a record for every case in the unit, and `driver.read` only ever compares the cases
    the checker returned (`cr = cby.get(rr.case_id); if cr is None: continue`). A case the
    checker silently omitted therefore produces no disagreement, and calling that agreement
    would put a provenance claim about a read that never happened into the ledger under a
    reader basis. Saying "the checker read this case and agreed" needs the runner to record
    which cases the checker returned per unit; until the manifest carries that, this is the
    true statement.

    A unit whose checker call FAILED gets nothing at all: it is not in `checker_status` as
    "ok", so "the checker never answered" stays distinct from both of the above.

    `case_ids_by_unit` is what makes the sampled line possible - the manifest records which
    UNITS were sampled, not which cases they held. Called without it (the shape T8 asks for)
    the result is the disagreements alone."""
    pin = str(manifest.get("checker_pin") or "checker").partition("@")[0]
    by_case: dict[int, list[str]] = {}
    sampled_units: list[str] = []
    for cell in (manifest.get("cells") or {}).values():
        for d in cell.get("checker_disagreements") or ():
            by_case.setdefault(int(d["case_id"]), []).append(
                f"{d['field']} {d['reader_value']!r} vs {d['checker_value']!r}")
        # `checker_status` is written for sampled units only, so its keys ARE the sample.
        sampled_units += [u for u, st in (cell.get("checker_status") or {}).items() if st == "ok"]
    out = {cid: f"checker:{pin}: " + "; ".join(parts) for cid, parts in by_case.items()}
    sampled = (f"checker:{pin}: unit sampled, no disagreement recorded on "
               f"{', '.join(COMPARE_FIELDS)}")
    for unit_id in sampled_units:
        for cid in (case_ids_by_unit or {}).get(unit_id, ()):
            out.setdefault(int(cid), sampled)
    return out


def _unit_for(batch: Mapping) -> Unit:
    """The same `Unit` `driver.plan_batch_extraction` built for this batch - identical id,
    case ids and meta, so `split_unit` splits it the same way and a re-rendered prompt is
    byte-identical to the one the read sent."""
    return Unit(batch["batch_id"], tuple(int(c["case_id"]) for c in batch["cases"]),
                {"batch_id": batch["batch_id"], "era_partition": batch["era_partition"],
                 "jurisdiction": batch["jurisdiction"],
                 "signals": {int(c["case_id"]): c.get("signals", []) for c in batch["cases"]}})


def _derived_half_keys(manifest: Mapping, unit: Unit, halves, *, codebook, pin, cases,
                       families: Mapping) -> list[str]:
    """The `-a`/`-b` keys for a manifest that recorded only the whole-unit key.

    Only reachable on the pre-amendment manifest shape. It has to compose the key exactly as
    `MapRunner._cache_key` did - same schema dialect (`driver.schema_for`), same max_tokens
    and effort - which is why the manifest's own `max_tokens` / `effort` are preferred over
    this process's defaults: an offline re-derivation must address what the RUN sent."""
    sent = schema_for(record_schema(codebook), codebook, pin, dict(families or {}))
    max_tokens = int(manifest.get("max_tokens") or Request.max_tokens)
    effort = str(manifest.get("effort") or effort_of(pin))
    out = []
    for half in halves:
        if not half.case_ids:
            out.append("")
            continue
        prompt = render_unit(codebook, half, cases.fetch(half.case_ids), worker_of(manifest))
        out.append(ResponseCache.key(codebook.sha, pin, half, prompt,
                                     schema_sha=schema_sha(sent), max_tokens=max_tokens,
                                     effort=effort))
    return out


def _cached_text(cache: ResponseCache, key: str) -> str | None:
    if not key:
        return None
    resp = cache.get(key)
    return None if resp is None else resp.text


def _with_identity(record: Mapping, case, unit_id: str, worker: str) -> dict:
    """The gated record with its identity replaced by what admission KNOWS.

    `cite`, `court`, `jurisdiction` and `year` come from the store row the gate just verified
    the quotes against; `worker`, `batch_id` and `schema_version` from the map itself. All
    seven are optional, nullable, model-emitted properties of the mapper-v3 schema that the
    gate never touches, so leaving them as the reader wrote them would let a hallucinated
    citation or a `jurisdiction` that contradicts the cell become the record's identity in the
    ledger - and `jurisdiction` and `year` are what the published counts and the era analysis
    slice on. The model's judgment is still entirely the model's; only its bookkeeping is
    overridden."""
    return {**record, "cite": case.cite, "court": case.court, "jurisdiction": case.jurisdiction,
            "year": case.year, "worker": worker, "batch_id": unit_id,
            "schema_version": SCHEMA_VERSION}


def records_from_manifest(manifest: Mapping, *, batch_source, cache: ResponseCache, codebook,
                          cases, pin, families: Mapping) -> list[AdmittedRecord]:
    """Every accepted record this map bought, re-parsed and re-gated from the cache.

    Mirrors the driver exactly: parse the whole unit, fall back to the split halves on a parse
    failure, then the quote gate over the cases that came back. A unit whose batch file or
    cache entry is gone is skipped rather than guessed at - admission under-claims rather than
    invents. `accepted` is the measurement's definition (spec section 2 as amended): a record
    that parsed, gated, and came back with a DECIDED `relevant`; a missing stub is neither
    admitted nor counted as an irrelevant read.

    The record that comes out carries the STORE's identity, not the model's (`_with_identity`)."""
    judged = tuple(codebook.judged_fields)
    units: list[tuple[str, str, list[str], dict]] = []
    case_ids_by_unit: dict[str, tuple[int, ...]] = {}
    for cell_key, unit_id, keys in _cell_units(manifest):
        if not keys or unit_id not in batch_source:
            continue
        batch = batch_source.get(unit_id)
        units.append((cell_key, unit_id, keys, batch))
        case_ids_by_unit[unit_id] = tuple(int(c["case_id"]) for c in batch["cases"])
    notes = checker_notes(manifest, case_ids_by_unit=case_ids_by_unit)

    worker = worker_of(manifest)
    out: list[AdmittedRecord] = []
    for cell_key, unit_id, keys, batch in units:
        unit = _unit_for(batch)
        texts = cases.fetch(unit.case_ids)
        by_case = {t.case_id: t for t in texts}
        recs = parse_records(_cached_text(cache, keys[0]) or "", unit.case_ids)
        key_of = dict.fromkeys(unit.case_ids, keys[0])
        if recs is None:
            halves = split_unit(unit)
            half_keys = (keys[1:] if len(keys) > 1
                         else _derived_half_keys(manifest, unit, halves, codebook=codebook,
                                                 pin=pin, cases=cases, families=families))
            recs, key_of = [], {}
            for half, hkey in zip(halves, list(half_keys) + [""] * len(halves)):
                part = parse_records(_cached_text(cache, hkey) or "", half.case_ids)
                if part is None:
                    continue                    # this half is unparsed: its cases are stubs
                recs.extend(part)
                key_of.update(dict.fromkeys(half.case_ids, hkey))
        ok_ids = [c for c in unit.case_ids if c in key_of]
        for res in gate_unit(recs, texts, ok_ids, judged, unit_id):
            if res.record.get("extraction_status") == "missing":
                continue
            if res.record.get("relevant") is None:
                continue                        # no decided relevance: not an accepted record
            out.append(AdmittedRecord(res.case_id, cell_key, unit_id, key_of[res.case_id],
                                      _with_identity(res.record, by_case[res.case_id], unit_id,
                                                     worker),
                                      notes.get(res.case_id, "")))
    return out


def counts_by_cell(admitted: Sequence[AdmittedRecord]) -> dict[str, dict]:
    """What `--dry-run` prints: how many records each cell contributes, split by the reader's
    relevance verdict. The irrelevant ones are not waste - they are the labelled negatives the
    next cycle's ranker trains on (spec section 8)."""
    acc: dict[str, dict] = {}
    for a in admitted:
        row = acc.setdefault(a.cell_key, {"records": 0, "relevant": 0, "irrelevant": 0})
        row["records"] += 1
        row["relevant" if a.record.get("relevant") else "irrelevant"] += 1
    return acc


def patches_for(admitted: Sequence[AdmittedRecord], *, manifest: Mapping) -> list[Patch]:
    """The ledger patches for one map. Deterministic: cells in manifest order, then case id."""
    basis = basis_for(manifest)
    cycle = str(manifest.get("cycle") or str(manifest.get("run_id", "")).split("-shard")[0])
    why = f"{cycle} {WHY}"
    cell_order = manifest.get("cell_order") or list(manifest.get("cells") or {})
    order = {k: i for i, k in enumerate(cell_order)}
    out: list[Patch] = []
    for a in sorted(admitted, key=lambda a: (order.get(a.cell_key, len(order)), a.cell_key,
                                             a.case_id)):
        rec = a.record
        body = {f: rec[f] for f in IDENTITY_FIELDS if f in rec}
        body["case_id"] = int(a.case_id)
        relevant = bool(rec.get("relevant"))
        note = f"cache {a.cache_key}; batch {a.batch_id}; cell {a.cell_key}"
        out.append(Patch(a.case_id, "admit", "", body,
                         why if relevant else f"{why}: irrelevant read", basis, cycle=cycle,
                         note=note))
        if not relevant:
            continue                    # an irrelevant read carries no judged values (section 8)
        for field in MAPPER_FIELDS:
            value = rec.get(field)
            if value is None or value == [] or value == "":
                continue                # a None asserts nothing; a set of it would be noise
            out.append(Patch(a.case_id, "set", field, value, f"{why}: {field}", basis,
                             cycle=cycle))
        if str(rec.get("notes") or "").strip():
            out.append(Patch(a.case_id, "append", "review.notes",
                             f"reader: {str(rec['notes']).strip()}", f"{why}: reader notes",
                             basis, cycle=cycle))
        if a.checker_note:
            out.append(Patch(a.case_id, "append", "review.notes", a.checker_note,
                             f"{why}: checker", basis, cycle=cycle))
    return out


# ------------------------------------------------- the cycles 1-3 re-read (spec section 6) ---
REREAD_WHY = "cycles 001-003 re-read"
# The two kinds of disagreement a re-read can have with a human decision. Both become section-G
# cards (spec section 7); neither ever becomes a value change.
CONFLICT_VALUE, CONFLICT_RELEVANT = CONFLICT_KINDS
# The mapper-v3 codebook's own rule for a case the reader finds irrelevant (hard requirement 4:
# `relevant: false`, `polarity: null`, `who_was_letting: null`). A withdrawal that left the
# doctrine of the read it withdraws standing on the record would be a record asserting a
# polarity for a case it also says bears on nothing.
RELEVANT_FALSE_NULLS = ("polarity", "who_was_letting")


@dataclass(frozen=True)
class RereadOutcome:
    patches: list
    conflicts: list
    counts: dict


def _human_decision(view, case_id: int, field: str) -> tuple[dict, int]:
    """(basis, seq) of the reviewer patch a conflict is against - the LAST reviewer `set` on
    that field. The card has to name the decision it is asking the reviewer to revisit, and
    "some human, at some point" is not a thing a reviewer can check."""
    last = None
    for p in view.history(case_id):
        if p.basis.reviewer and p.op == "set" and p.field == field:
            last = p
    return (last.basis.to_json(), int(last.seq)) if last is not None else ({}, 0)


def reread_patches(admitted: Sequence[AdmittedRecord], *, manifest: Mapping,
                   view) -> RereadOutcome:
    """A re-read of records the ledger already holds, as patches, conflicts and counts (D7).

    Per record: one re-admit under mapper-v3, which moves the record onto the six-field quote
    support rule (`fold.supported_fields`), then per field fill / replace / agree / conflict.

    The re-admit body is the record the ledger holds, with the re-read's identity, quotes and
    gate notes over it, and `relevant` decided below. That is not belt and braces: `apply_patch`
    's `admit` op replaces the whole record, so a body naming only the re-read's fields would
    wipe every value the record already carries - reviewer decisions, doctrinal concepts, and
    the review block's flags and notes included (R6). The values carried through are
    value-identical writes, which the fold treats as no-ops (D2), so nothing about provenance
    moves. The patch's `cycle` is the record's OWN cycle, because a re-admit under any other
    raises `DuplicateRecord`: a re-read fills a record in place, it does not move it.

    A field whose provenance is `human` is never written. If the re-read agrees, that is an
    agreement; if it differs, the tool records a conflict, flags the field and writes a note,
    and emits NO set - it does not emit a patch for the fold to reject, because a rejected
    patch is still a line in an append-only log that every later replay has to re-reject.

    `relevant: false` is the one verdict with two answers (D7). Against a record no human has
    judged it is applied, with the codebook's own cascade (`RELEVANT_FALSE_NULLS`): a reader's
    relevance is a reader's, and the newer codebook's reading of it replaces the older one's.
    Against a record carrying ANY human judgment it is a `relevant_false` conflict and nothing
    is written - applying it would set `in_file` false and drop the record out of its cycle
    file altogether, taking the human's decision with it, which is precisely the thing D2
    exists to stop a machine read doing quietly."""
    basis = basis_for(manifest)
    reread_basis = basis.to_json()
    cell_order = manifest.get("cell_order") or list(manifest.get("cells") or {})
    order = {k: i for i, k in enumerate(cell_order)}
    out: list[Patch] = []
    conflicts: list[dict] = []
    skipped: list[int] = []
    relevant_false: list[int] = []
    by_field: dict[str, dict] = {}

    def count(field: str, kind: str) -> None:
        row = by_field.setdefault(field, {"fill": 0, "replace": 0, "agree": 0, "conflict": 0,
                                          "skipped": 0})
        row[kind] += 1

    def conflict(a, field, human_value, reread_value, kind, into: list) -> None:
        human_basis, human_at = _human_decision(view, a.case_id, field)
        entry = {"case_id": int(a.case_id), "field": field,
                 "human_value": human_value, "human_basis": human_basis,
                 "human_at": human_at, "reread_value": reread_value,
                 "reread_basis": reread_basis, "kind": kind,
                 "cell_key": a.cell_key, "batch_id": a.batch_id}
        # Projected through the queue's own key list, so a card that is missing one raises
        # HERE rather than rendering blank in section G a round later.
        into.append({k: entry[k] for k in CONFLICT_KEYS})
        count(field, "conflict")

    for a in sorted(admitted, key=lambda a: (order.get(a.cell_key, len(order)), a.cell_key,
                                             a.case_id)):
        rec = view.state.records.get(a.case_id)
        if rec is None:
            skipped.append(int(a.case_id))      # a re-read admits nothing the ledger lacks
            continue
        new = a.record
        prov = view.provenance(a.case_id)
        mine: list[dict] = []                   # this record's conflicts, in emission order
        note = f"cache {a.cache_key}; batch {a.batch_id}; cell {a.cell_key}"
        cycle = str(view.state.cycles.get(int(a.case_id)) or manifest.get("cycle") or "")
        relevance = rec.get("relevant")
        withdraw = new.get("relevant") is False and rec.get("relevant") is True
        if withdraw and any(kind == "human" for kind in prov.values()):
            # D7: never an overturn of a human's record. See the docstring.
            conflict(a, "relevant", rec.get("relevant"), False, CONFLICT_RELEVANT, mine)
            relevant_false.append(int(a.case_id))
            withdraw = False
        elif withdraw:
            relevance = False
        body = copy.deepcopy(rec)               # R6: every key the record carries, forward
        body.update({f: new[f] for f in IDENTITY_FIELDS if f in new})
        body["case_id"] = int(a.case_id)
        body["relevant"] = relevance
        out.append(Patch(a.case_id, "admit", "", body, f"{REREAD_WHY}: re-admit under "
                         f"{CODEBOOK_ID}", basis, cycle=cycle, note=note))
        if withdraw:
            # The judged value still arrives as a `set` under the D8 basis, like every other
            # one (this module's docstring): the body is what the record IS, the `set` is what
            # judged it.
            out.append(Patch(a.case_id, "set", "relevant", False,
                             f"{REREAD_WHY}: relevant withdrawn", basis, cycle=cycle))
            count("relevant", "replace")
            for field in RELEVANT_FALSE_NULLS:
                if rec.get(field) is None:
                    count(field, "agree")
                    continue
                out.append(Patch(a.case_id, "set", field, None,
                                 f"{REREAD_WHY}: {field} nulled with the relevance", basis,
                                 cycle=cycle))
                count(field, "replace")
        else:
            for field in MAPPER_FIELDS:
                value = new.get(field)
                current = rec.get(field)
                if prov.get(field) == "human":
                    if value is None or value == "" or value == [] or value == current:
                        count(field, "agree" if value == current else "skipped")
                    else:
                        conflict(a, field, current, value, CONFLICT_VALUE, mine)
                    continue
                if value is None or value == "" or value == []:
                    count(field, "skipped")
                elif current is None:
                    out.append(Patch(a.case_id, "set", field, value,
                                     f"{REREAD_WHY}: {field} filled", basis, cycle=cycle))
                    count(field, "fill")
                elif value == current:
                    count(field, "agree")
                else:
                    out.append(Patch(a.case_id, "set", field, value,
                                     f"{REREAD_WHY}: {field} replaced", basis, cycle=cycle))
                    count(field, "replace")
        for c in mine:
            out.append(Patch(a.case_id, "append", "review.flags",
                             f"{FLAG_PREFIX}{c['field']}", f"{REREAD_WHY}: {c['field']}", basis,
                             cycle=cycle))
            out.append(Patch(a.case_id, "append", "review.notes",
                             f"{REREAD_WHY}: the re-read read {c['field']} as "
                             f"{c['reread_value']!r}; the reviewer's {c['human_value']!r} "
                             f"stands and the disagreement is queued as a review card",
                             f"{REREAD_WHY}: {c['field']}", basis, cycle=cycle))
        conflicts.extend(mine)
    counts = {"records": len(admitted) - len(skipped), "skipped": skipped,
              "conflicts": len(conflicts), "relevant_false_conflicts": relevant_false,
              "by_field": by_field}
    return RereadOutcome(out, conflicts, counts)
