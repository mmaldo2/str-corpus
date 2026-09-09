r"""Export the map review round's cards to files (spec section 9 handoff).

`tools/make_map_review.py` renders the queue as a self-saving page. This writes the same
information as plain files instead, for a first pass done by another model working from
files rather than the page: `reports/review-round-1-cards.json` (one object per card,
machine-readable) and its readable twin `reports/review-round-1-cards.md` (one card per
record, headed by section). Everything a card on the page shows, nothing more. Ordering is
deterministic - section in the round's own priority order (G, A-F), then queue order within a
section - so a diff between two exports of the same round is a diff of content, never order.

Input : runs/<run-id>/review-round-<n>.json          (Queue.to_json(), the round's manifest)
        runs/<run-id>/review-round-<n>-checker.json  (check_queue output)
Output: reports/review-round-1-cards.{json,md}

Read-only over the queue and checker files: no network, no reader, no ledger. `--full-text`
adds one more read - the store, through `corpus_engine.reader.sources.StoreCaseSource`, whose
`fetch` only ever runs a `SELECT`.

Three round-1b additions, for a second first-pass round over the cards round 1 left unsure,
with the full opinion text in hand this time:

`--only-unsure <decisions.json>` restricts the export to the case ids a decisions file (the
schema `tools/apply_map_review.py --decisions` reads) marks `"decision": "unsure"` - the round
that needs a second look, not the 150 the first round queued.

`--full-text` adds `opinion_text` to every exported card: the store's `norm_text` for that
case, fetched in one batched call through `StoreCaseSource` rather than one round trip per
card. Mean opinion length across the corpus is ~15k characters, max ~55k - large enough that
a model reading the export may not hold the whole round in context at once, which is what
`--chunks` is for.

`--chunks N` splits the markdown export into N roughly-equal files, `<out-stem>-part<k>.md`,
by total character size (dominated by `opinion_text` when `--full-text` is set) - never
splitting a card across two files. The default, `--chunks 1`, writes the single
`<out-stem>.md` this tool always wrote; passing it explicitly changes nothing.

Round 2 adds two more things, for a round that mixes sections which want full text (C, D)
with sections that do not (B), and that may carry section-E cards in a later round:

`--full-text-sections C,D` restricts `opinion_text` to cards in the named sections, instead of
every card `--full-text` attaches it to - the two are documented above their `argparse`
entries; passing both prefers `--full-text-sections`.

A section-E card (a judged field the quote gate erased) automatically gets `erased_value`: the
value the reader gave that field BEFORE the gate nulled it, read from the unit's own cached
response via the run's map manifest and pool batches (`--map-manifest`, `--batches-dir`,
`--reader-cache`) - `None` when it cannot be recovered. Those three files are only read when
the export actually contains a section-E card.

  .venv\Scripts\python tools\export_review_cards.py \
      --queue runs\cycle-004-shard-01\review-round-1.json
  .venv\Scripts\python tools\export_review_cards.py \
      --only-unsure runs\cycle-004-shard-01\review-round-1-decisions-astra.json --full-text \
      --chunks 4 --out-stem reports\review-round-1b-unsure-cards
  .venv\Scripts\python tools\export_review_cards.py \
      --queue runs\cycle-004-shard-01\review-round-2.json --full-text-sections C,D \
      --chunks 8 --out-stem reports\review-round-2-cards
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                          # noqa: E402
from corpus_engine.mapper.cells import load_batches      # noqa: E402
from corpus_engine.mapper.queue import SECTIONS          # noqa: E402
from corpus_engine.reader.parse import _as_case_id, parse_records  # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource  # noqa: E402

# The card's comparison fields (corpus_engine.mapper.queue.CARD_VALUE_FIELDS), and the
# narrower slice check_queue actually asks the checker for (corpus_engine.reader.driver
# COMPARE_FIELDS plus relevance) - two different vocabularies, so they are named separately
# rather than pretending the checker answered for fields it was never asked about.
READER_FIELDS = ("relevant", "polarity", "who_was_letting", "duration_of_occupancy",
                 "characterization", "under_thirty_days", "owner_freedom_characterization",
                 "restriction_nature")
CHECKER_FIELDS = ("relevant", "polarity", "characterization")
DEFAULT_STEM = "reports/review-round-1-cards"


def write_text(path: Path, text: str) -> None:
    """LF, UTF-8 without BOM, one trailing newline (same contract as make_map_review.write_text)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def courtlistener_url(cite: str | None) -> str:
    """The same search link the review page's own `clq` builds client-side
    (tools/make_map_review.py's CONTENT_TMPL, function `clq`): a quoted-citation search,
    percent-encoded like JS `encodeURIComponent` - so a card's link here is the link the
    page would have shown for the same case."""
    return 'https://www.courtlistener.com/?q=%22' + quote(cite or "", safe="!'()*~") + '%22'


def cards_from_queue(queue_doc: Mapping, checker: Mapping) -> list[dict]:
    """One object per card - section order (A-F), then queue order within a section - built
    from the queue manifest's own values plus the checker's, exactly as the page would show
    them. A case the checker was never asked about (or the checker file wasn't loaded)
    carries `checker: null`, not a dict of nulls indistinguishable from "asked and null"."""
    checker = {str(k): v for k, v in (checker or {}).items()}
    titles = queue_doc.get("titles") or {}
    out = []
    for sec, _key, default_title in SECTIONS:
        for c in (queue_doc.get("sections") or {}).get(sec) or ():
            values = c.get("values") or {}
            key = str(c["case_id"])
            chk_entry = checker.get(key)
            chk_values = (chk_entry or {}).get("values") or {}
            out.append({
                "case_id": c["case_id"],
                "section": sec,
                "section_title": titles.get(sec, default_title),
                "name": c.get("name"),
                "cite": c.get("cite"),
                "court": c.get("court"),
                "jurisdiction": c.get("jur"),
                "year": c.get("year"),
                "decide_field": c["decide_field"],
                "reader": {f: values.get(f) for f in READER_FIELDS},
                "checker": ({f: chk_values.get(f) for f in CHECKER_FIELDS}
                           if chk_entry is not None else None),
                "holding_summary": c.get("holding_summary"),
                "quotes": [{"text": q.get("text"), "supports": list(q.get("supports") or ())}
                          for q in (c.get("quotes") or ())],
                "fuzzy": [{"text": q.get("text"), "source": q.get("source"),
                          "classification": q.get("classification"),
                          "quote_coverage": q.get("quote_coverage"),
                          "auto_accepted": q.get("auto_accepted")}
                         for q in (c.get("fuzzy") or ())],
                "nulled_fields": list(c.get("nulled_fields") or ()),
                "other_reasons": list(c.get("other_reasons") or ()),
                "courtlistener_url": courtlistener_url(c.get("cite")),
                "conflict": c.get("conflict"),
            })
    return out


def _fmt(v) -> str:
    return "null" if v is None else str(v)


def markdown_for(cards: Sequence[dict], run_id: str, *, part: tuple[int, int] | None = None) -> str:
    """One readable card per record, headed by section - the markdown twin of the JSON
    export, for a model (or a human) reading files rather than parsing JSON by hand.

    `part`, when given, is `(k, n)` - this is file k of n from `markdown_parts` - and adds
    only a title suffix; `part=None` (every direct call, and `markdown_parts` with `n <= 1`)
    is byte-identical to what this function has always written."""
    title = f"# Cycle-004 map review round 1 - cards ({run_id})"
    if part is not None:
        title += f" - part {part[0]} of {part[1]}"
    lines = [title, "",
            f"{len(cards)} cards, one per record, grouped by section in the round's priority "
            "order. Written by tools/export_review_cards.py from the queue manifest and the "
            "checker file - read-only, the same values the review page itself shows.", ""]
    current_section = None
    for c in cards:
        if c["section"] != current_section:
            current_section = c["section"]
            lines.append(f"\n## {c['section']}. {c['section_title']}\n")
        lines.append(f"### {c.get('cite') or c['case_id']} - {c.get('name') or ''} "
                     f"[{c['case_id']}]")
        lines.append(f"- Court: {c.get('court') or '?'} - {c.get('jurisdiction') or '?'} - "
                     f"{c.get('year') or '?'}")
        lines.append(f"- Decide: **{c['decide_field']}**")
        lines.append(f"- Other reasons: {', '.join(c['other_reasons']) or '-'}")
        reader = " ".join(f"{f}={_fmt(v)}" for f, v in c["reader"].items())
        lines.append(f"- Reader: {reader}")
        if c["checker"] is not None:
            checker = " ".join(f"{f}={_fmt(v)}" for f, v in c["checker"].items())
            lines.append(f"- Checker: {checker}")
        else:
            lines.append("- Checker: not asked")
        if c["section"] == "C" and c["checker"] is not None:
            # Section C decides whichever field the reader and checker disagreed on - make
            # that disagreement the first thing a reviewer sees, not something they have to
            # cross-reference from the two lines above.
            rv, cv = c["reader"].get(c["decide_field"]), c["checker"].get(c["decide_field"])
            lines.append(f"- **Reader says {_fmt(rv)}; checker says {_fmt(cv)}**")
        if c["nulled_fields"]:
            lines.append(f"- Nulled by the quote gate: {', '.join(c['nulled_fields'])}")
        if c.get("conflict"):
            cf = c["conflict"]
            lines.append(f"- **Your earlier decision: {cf['field']} = {_fmt(cf['human_value'])}**"
                         f" ({(cf.get('human_basis') or {}).get('reviewer') or 'reviewer'}, run "
                         f"{(cf.get('human_basis') or {}).get('run_id') or '?'}, seq "
                         f"{cf.get('human_at')})")
            lines.append(f"- **The mapper-v3 re-read reads it as: {_fmt(cf['reread_value'])}**"
                         + (" (and reads the case as NOT a letting case at all)"
                            if cf.get("kind") == "relevant_false" else ""))
            lines.append("- Decide: keep (your value stands - the default), set (you revise "
                         "your own earlier decision), or unsure.")
        if "erased_value" in c:                 # section E only, see attach_erased_values
            lines.append(f"- Erased value for {c['decide_field']} (the reader's answer before "
                         f"the quote gate nulled it): {_fmt(c['erased_value'])}")
        if c["holding_summary"]:
            lines.append(f"- Holding: {c['holding_summary']}")
        lines.append(f"- CourtListener: {c['courtlistener_url']}")
        if c["quotes"]:
            lines.append("- Quotes:")
            for q in c["quotes"]:
                supports = ", ".join(q["supports"]) or "-"
                lines.append(f"  > {q['text']}")
                lines.append(f"  > (supports: {supports})")
        if c.get("fuzzy"):
            lines.append("- Fuzzy quote match(es) - reader's quote vs. the closest passage "
                         "found in the opinion:")
            for q in c["fuzzy"]:
                lines.append(f"  > quote: {q['text']}")
                lines.append(f"  > opinion passage: {q.get('source') or ''}")
                lines.append(f"  > classification: {q.get('classification')} - coverage: "
                             f"{q.get('quote_coverage')} - auto-accepted: "
                             f"{q.get('auto_accepted')}")
        if "opinion_text" in c:                 # --full-text only; absent otherwise
            lines.append("")
            lines.append("#### Opinion text")
            lines.append("")
            lines.append(c["opinion_text"] or "")
        lines.append("")
    return "\n".join(lines)


def _card_weight(c: Mapping) -> int:
    """A rough size estimate for balancing `--chunks` parts. `opinion_text` (mean ~15k chars,
    max ~55k) dominates every other field on a card once `--full-text` is set, so counting it
    plus a fixed overhead for the rest of the card is close enough to "roughly equal" without
    rendering every card twice just to measure it. With no `opinion_text` every card weighs
    the same, so `--chunks` alone (no `--full-text`) splits by card count."""
    return 400 + len(c.get("opinion_text") or "")


def markdown_parts(cards: Sequence[dict], run_id: str, n: int = 1) -> list[str]:
    """`markdown_for`'s text, split into `n` roughly-equal files by `_card_weight` - never
    splitting a card across two files, and never reordering them. `n <= 1` (the default) hands
    back a single part, byte-identical to `markdown_for(cards, run_id)`."""
    if not cards or n <= 1:
        return [markdown_for(cards, run_id)]
    n = min(int(n), len(cards))
    weights = [_card_weight(c) for c in cards]
    target = sum(weights) / n
    groups: list[list[dict]] = []
    current: list[dict] = []
    cum = 0
    for c, w in zip(cards, weights):
        current.append(c)
        cum += w
        if len(groups) < n - 1 and cum >= target * (len(groups) + 1):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [markdown_for(g, run_id, part=(k + 1, len(groups))) for k, g in enumerate(groups)]


def only_unsure_ids(decisions_path: str | Path) -> set[int]:
    """The case ids a `--decisions`-schema file (`tools/apply_map_review.py`'s
    `{case_id, field, decision, value, note}` list) marks `"decision": "unsure"` - the round
    that needs a second look with the full opinion text, not every card the first round
    queued."""
    raw = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
    return {int(d["case_id"]) for d in raw if d.get("decision") == "unsure"}


def attach_opinion_text(cards: Sequence[dict], source) -> list[dict]:
    """`cards` with `opinion_text` added - the store's `norm_text` for every card, fetched in
    one batched call through `source.fetch` (the `StoreCaseSource` interface - real for
    `main()`, a fake with the same shape in tests) rather than one round trip per card. A
    card the source has no text for (should not happen for an admitted case, but `fetch`
    itself is what enforces that) is left to raise there rather than silently writing `""`."""
    cards = list(cards)
    if not cards:
        return cards
    texts = {t.case_id: t.norm_text for t in source.fetch([c["case_id"] for c in cards])}
    for c in cards:
        c["opinion_text"] = texts[c["case_id"]]
    return cards


def unit_cache_keys(manifest: Mapping) -> dict[str, list[str]]:
    """unit_id -> cache keys, flattened across every cell in a map manifest
    (`runs/<run-id>/map-manifest.json`). Unit ids are unique across the whole run - each cell
    only ever names the units it read - so one flat dict answers for the run regardless of
    which cell a case's unit belongs to."""
    out: dict[str, list[str]] = {}
    for cell in (manifest.get("cells") or {}).values():
        for unit_id, keys in (cell.get("cache_keys") or {}).items():
            out[str(unit_id)] = list(keys)
    return out


def case_unit_index(batches: Sequence[Mapping]) -> dict[int, str]:
    """case_id -> the batch (unit) id that read it, from the map's own pool batch files
    (`corpus_engine.mapper.cells.load_batches`) - `batch_id` doubles as the reader's `unit.id`
    for a map read, so this is the same identifier `unit_cache_keys` is keyed by. A case is
    read by exactly one pool batch."""
    out: dict[int, str] = {}
    for b in batches:
        bid = b.get("batch_id")
        if bid is None:
            continue
        for c in b.get("cases") or ():
            cid = c.get("case_id")
            if cid is not None:
                out[int(cid)] = str(bid)
    return out


def erased_value(case_id: int, field: str, *, unit_of: Mapping[int, str],
                 cache_keys: Mapping[str, Sequence[str]], cache_dir) -> object:
    """The value the reader gave `field` on `case_id` BEFORE the quote gate erased it -
    section E's whole reason for existing (`corpus_engine.mapper.queue.reasons_for`: a judged
    field the reader answered but no verbatim quote backed, so a mechanical check nulled it).
    The card's own `values` only carry what SURVIVED the gate (null, for this field) - this
    reads the RAW answer, from the unit's own cached response, the same way
    `tools/measure_reader.py`'s offline re-derivation does: `corpus_engine.reader.parse` on
    the cached text, never the gated record.

    `None` when it cannot be recovered - the case's unit is not known, none of the unit's
    cache keys are on disk, the cached response will not parse, or the field is missing from
    the parsed record - because a section-E card must never be blocked on this, only enriched
    by it when it is there."""
    unit_id = unit_of.get(int(case_id))
    if unit_id is None:
        return None
    cache_dir = Path(cache_dir)
    for key in cache_keys.get(unit_id) or ():
        p = cache_dir / f"{key}.json"
        if not p.exists():
            continue
        try:
            text = json.loads(p.read_text(encoding="utf-8"))["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        recs = parse_records(text, [case_id])
        if not recs:
            continue
        for r in recs:
            if _as_case_id(r.get("case_id")) == int(case_id) and field in r:
                return r[field]
    return None


def attach_erased_values(cards: Sequence[dict], *, manifest: Mapping, batches: Sequence[Mapping],
                         cache_dir) -> list[dict]:
    """`cards` with `erased_value` added to every section-E card (see `erased_value`, above);
    every other card is returned untouched. `manifest`/`batches` are only consulted when at
    least one section-E card is present, so an export with none (this round's own, D5.2)
    never has to read the run's ~thousands of pool batch files for nothing."""
    cards = list(cards)
    e_cards = [c for c in cards if c.get("section") == "E"]
    if not e_cards:
        return cards
    unit_of = case_unit_index(batches)
    keys_by_unit = unit_cache_keys(manifest)
    for c in e_cards:
        c["erased_value"] = erased_value(c["case_id"], c["decide_field"], unit_of=unit_of,
                                         cache_keys=keys_by_unit, cache_dir=cache_dir)
    return cards


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", default="runs/cycle-004-shard-01/review-round-1.json",
                    help="the round's queue manifest (Queue.to_json())")
    ap.add_argument("--checker", default=None,
                    help="check_queue output; defaults to <queue>-checker.json")
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    ap.add_argument("--only-unsure", default=None,
                    help="a decisions file (tools/apply_map_review.py's --decisions schema); "
                         "restrict the export to the case ids it marks unsure")
    ap.add_argument("--full-text", action="store_true",
                    help="add opinion_text (the store's norm_text) to every exported card, "
                         "via corpus_engine.reader.sources.StoreCaseSource - read-only")
    ap.add_argument("--full-text-sections", default=None,
                    help="comma-separated section letters (e.g. C,D); add opinion_text only "
                         "to cards in these sections, instead of every card. Takes priority "
                         "over --full-text when both are given; --full-text alone still means "
                         "every card, unchanged from before this option existed")
    ap.add_argument("--chunks", type=int, default=1,
                    help="split the markdown export into N roughly-equal <out-stem>-partK.md "
                         "files, whole cards only (default 1: the single <out-stem>.md this "
                         "tool has always written)")
    ap.add_argument("--map-manifest", default="runs/cycle-004-shard-01/map-manifest.json",
                    help="the run's map manifest (runs/<run-id>/map-manifest.json); read only "
                         "when the export includes a section-E card, for erased_value's "
                         "cache-key lookup")
    ap.add_argument("--batches-dir", default="runs/cycle-004-shard-01/batches",
                    help="the run's pool batch directory; read only when the export includes "
                         "a section-E card, for erased_value's case -> unit lookup")
    ap.add_argument("--reader-cache", default="data/reader/cache",
                    help="the reader response cache directory (relative to the repo root "
                         "unless absolute); read only when the export includes a section-E "
                         "card, for erased_value's cached response lookup")
    a = ap.parse_args(argv)

    queue_path = Path(a.queue)
    doc = json.loads(queue_path.read_text(encoding="utf-8"))
    checker_path = (Path(a.checker) if a.checker
                    else queue_path.with_name(queue_path.stem + "-checker.json"))
    checker = json.loads(checker_path.read_text(encoding="utf-8")) if checker_path.exists() else {}

    cards = cards_from_queue(doc, checker)
    if a.only_unsure:
        ids = only_unsure_ids(a.only_unsure)
        cards = [c for c in cards if c["case_id"] in ids]
    if a.full_text_sections:
        wanted = {s.strip().upper() for s in a.full_text_sections.split(",") if s.strip()}
        attach_opinion_text([c for c in cards if c["section"] in wanted],
                            StoreCaseSource(store.connect()))
    elif a.full_text:
        cards = attach_opinion_text(cards, StoreCaseSource(store.connect()))
    if any(c["section"] == "E" for c in cards):
        manifest = json.loads(Path(a.map_manifest).read_text(encoding="utf-8"))
        batches = load_batches(Path(a.batches_dir))
        cache_dir = Path(a.reader_cache)
        cache_dir = cache_dir if cache_dir.is_absolute() else ROOT / cache_dir
        attach_erased_values(cards, manifest=manifest, batches=batches, cache_dir=cache_dir)

    json_path = Path(str(a.out_stem) + ".json")
    write_text(json_path, json.dumps(cards, indent=1))

    parts = markdown_parts(cards, doc.get("run_id", ""), a.chunks)
    if len(parts) == 1:
        md_paths = [Path(str(a.out_stem) + ".md")]
    else:
        md_paths = [Path(str(a.out_stem) + f"-part{k}.md") for k in range(1, len(parts) + 1)]
    for path, text in zip(md_paths, parts):
        write_text(path, text)
    print(f"{len(cards)} cards -> {json_path.as_posix()}, "
         + ", ".join(p.as_posix() for p in md_paths), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
