r"""Export the map review round's cards to files (spec section 9 handoff).

`tools/make_map_review.py` renders the queue as a self-saving page. This writes the same
information as plain files instead, for a first pass done by another model working from
files rather than the page: `reports/review-round-1-cards.json` (one object per card,
machine-readable) and its readable twin `reports/review-round-1-cards.md` (one card per
record, headed by section). Everything a card on the page shows, nothing more. Ordering is
deterministic - section in the round's own priority order (A-F), then queue order within a
section - so a diff between two exports of the same round is a diff of content, never order.

Input : runs/<run-id>/review-round-<n>.json          (Queue.to_json(), the round's manifest)
        runs/<run-id>/review-round-<n>-checker.json  (check_queue output)
Output: reports/review-round-1-cards.{json,md}

Read-only: no network, no reader, no ledger. Just reformats files already on disk.

  .venv\Scripts\python tools\export_review_cards.py \
      --queue runs\cycle-004-shard-01\review-round-1.json
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

from corpus_engine.mapper.queue import SECTIONS  # noqa: E402

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
                "nulled_fields": list(c.get("nulled_fields") or ()),
                "other_reasons": list(c.get("other_reasons") or ()),
                "courtlistener_url": courtlistener_url(c.get("cite")),
            })
    return out


def _fmt(v) -> str:
    return "null" if v is None else str(v)


def markdown_for(cards: Sequence[dict], run_id: str) -> str:
    """One readable card per record, headed by section - the markdown twin of the JSON
    export, for a model (or a human) reading files rather than parsing JSON by hand."""
    lines = [f"# Cycle-004 map review round 1 - cards ({run_id})", "",
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
        if c["nulled_fields"]:
            lines.append(f"- Nulled by the quote gate: {', '.join(c['nulled_fields'])}")
        if c["holding_summary"]:
            lines.append(f"- Holding: {c['holding_summary']}")
        lines.append(f"- CourtListener: {c['courtlistener_url']}")
        if c["quotes"]:
            lines.append("- Quotes:")
            for q in c["quotes"]:
                supports = ", ".join(q["supports"]) or "-"
                lines.append(f"  > {q['text']}")
                lines.append(f"  > (supports: {supports})")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", default="runs/cycle-004-shard-01/review-round-1.json",
                    help="the round's queue manifest (Queue.to_json())")
    ap.add_argument("--checker", default=None,
                    help="check_queue output; defaults to <queue>-checker.json")
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    a = ap.parse_args(argv)

    queue_path = Path(a.queue)
    doc = json.loads(queue_path.read_text(encoding="utf-8"))
    checker_path = (Path(a.checker) if a.checker
                    else queue_path.with_name(queue_path.stem + "-checker.json"))
    checker = json.loads(checker_path.read_text(encoding="utf-8")) if checker_path.exists() else {}

    cards = cards_from_queue(doc, checker)
    json_path = Path(str(a.out_stem) + ".json")
    md_path = Path(str(a.out_stem) + ".md")
    write_text(json_path, json.dumps(cards, indent=1))
    write_text(md_path, markdown_for(cards, doc.get("run_id", "")))
    print(f"{len(cards)} cards -> {json_path.as_posix()}, {md_path.as_posix()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
