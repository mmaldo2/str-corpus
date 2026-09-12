"""The external first pass over a review round, through the Codex CLI: one call per card.

Until now the GPT Astra pass on every round went by hand - the user pasted the handoff and the
card files into a chat and brought the decisions file back. This tool runs the same pass on
the Codex subscription (`corpus_engine.reader.providers.codex_cli.CodexCliProvider`, the
provider the 100% checker already uses), one prompt per card, and writes the decisions file
`tools/apply_map_review.py --decisions` reads.

Inputs:
  --cards    the round's card export with full opinion text
             (`tools/export_review_cards.py --full-text`, the `.json` twin)
  --brief    the standing first-pass brief (default reports/review-first-pass-brief.md)
  --handoff  the round's handoff addendum (composition, settled rules, what to expect)
  --model    the Codex model (default gpt-6-astra - the reader the user has used by hand)
  --out      the decisions file; a sidecar `<out-stem>-manifest.json` records the model, the
             codex version, and each card's status

Per card the prompt is: the brief, the handoff, a short single-card instruction, then the
card exactly as the markdown export renders it (reader values, checker block, quotes, erased
value, full opinion). The reply is parsed for one JSON object and validated the way the apply
tool validates a decisions file: the field is the card's decide field (or `relevant` for a
withdrawal), the decision is keep|set|unsure, a `set` value is in the field's vocabulary.
`adopt` is resolved here to the checker's value so the written decision is a real value.

Resumable: a card already in `--out` is not re-asked, so a rerun after a failed call finishes
the round from where it stopped. A card whose call fails or whose reply cannot be validated
is listed in the manifest's `failed` and left out of the decisions file - never guessed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from corpus_engine.reader.model import ReaderError, Request           # noqa: E402
from corpus_engine.reader.providers.codex_cli import CodexCliProvider  # noqa: E402
from apply_map_review import VALUES, BOOLS, NULLS                       # noqa: E402
from export_review_cards import markdown_for, write_text               # noqa: E402

DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_BRIEF = "reports/review-first-pass-brief.md"

SINGLE_CARD = """## This call

You are given ONE card, with the full opinion text, not a chunk. Decide it under the brief
and the handoff above and reply with exactly one JSON object (no list, no file), of the shape
the brief's Output section gives:

{"case_id": <the card's id>, "field": "<the card's decide field, or 'relevant' for a withdrawal>",
 "decision": "keep|set|unsure", "value": <only on set>, "note": "<one line>",
 "checker_disagrees": <true only when it does>}

Read the opinion and decide before you look at the card's Checker line. Do not use `adopt`.
Nothing but the JSON object is needed in the reply.
"""


def build_prompt(card: dict, *, brief: str, handoff: str) -> str:
    card_md = markdown_for([card], "", part=None)
    # drop the export's file title and its two-line preamble; the section heading stays
    body = card_md.split("\n## ", 1)[1] if "\n## " in card_md else card_md
    return "\n\n".join([brief.strip(), handoff.strip(), SINGLE_CARD.strip(),
                        "## The card\n\n## " + body.strip()]) + "\n"


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _json_objects(text: str) -> list[dict]:
    """Every JSON object (or single-object list) the reply carries, fenced or bare."""
    found = []
    candidates = _FENCE.findall(text) or []
    candidates.append(text)
    dec = json.JSONDecoder()
    for cand in candidates:
        i = 0
        while True:
            j = min([k for k in (cand.find("{", i), cand.find("[", i)) if k >= 0], default=-1)
            if j < 0:
                break
            try:
                obj, end = dec.raw_decode(cand, j)
            except ValueError:
                i = j + 1
                continue
            if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict):
                obj = obj[0]
            if isinstance(obj, dict) and "decision" in obj:
                found.append(obj)
            i = end
        if found:
            break
    return found


def parse_decision(text: str, card: dict) -> dict:
    """The one validated decision entry a reply carries for `card`, in the apply schema.

    Raises ValueError with the reason when the reply carries no JSON object, names another
    case, decides a field that is neither the card's nor `relevant`, uses a decision outside
    keep|adopt|set|unsure, or sets a value outside the field's vocabulary."""
    objs = _json_objects(text)
    if not objs:
        raise ValueError("no JSON object with a decision in the reply")
    d = objs[-1]
    cid = d.get("case_id")
    if str(cid) != str(card["case_id"]):
        raise ValueError(f"case_id {cid!r} is not the card's ({card['case_id']})")
    field = d.get("field")
    if field not in (card["decide_field"], "relevant"):
        raise ValueError(f"field {field!r} is neither the card's decide field "
                         f"({card['decide_field']}) nor relevant")
    decision = d.get("decision")
    if decision not in ("keep", "adopt", "set", "unsure"):
        raise ValueError(f"decision {decision!r} is not keep|set|unsure")
    out = {"case_id": card["case_id"], "field": field, "decision": decision,
           "note": str(d.get("note") or "").strip()}
    if decision == "adopt":
        chk = card.get("checker") or {}
        if field not in chk:
            raise ValueError(f"adopt on {field}, but the checker gave no value for it")
        out["decision"], out["value"] = "set", chk[field]
    elif decision == "set":
        if "value" not in d:
            raise ValueError("set without a value")
        out["value"] = d["value"]
    if out["decision"] == "set":
        out["value"] = _checked_value(field, out["value"])
    if d.get("checker_disagrees") is True:
        out["checker_disagrees"] = True
    return out


def _checked_value(field: str, raw):
    vocab = VALUES.get(field)
    if vocab is None:                       # quotes / holding_summary: free text
        return raw
    val = raw
    if field == "relevant" and isinstance(raw, str):
        val = BOOLS.get(raw.lower(), raw)
    elif raw in NULLS:
        val = None
    if val not in vocab or (field == "relevant" and val not in (True, False)):
        raise ValueError(f"{field}: {raw!r} is not in the vocabulary")
    return val


def _load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _dump(path: Path, obj) -> None:
    write_text(path, json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def manifest_path_for(out_path: Path) -> Path:
    return out_path.with_name(out_path.stem + "-manifest.json")


def run_first_pass(cards: Sequence[dict], *, brief: str, handoff: str, provider,
                   out_path: Path, log: Callable[..., None] = print,
                   model: str = DEFAULT_MODEL) -> dict:
    """Ask `provider` about every card not yet in `out_path`; write the decisions file after
    each answer (so a crash loses nothing) and the sidecar manifest at the end. Returns the
    manifest: model, codex version, `decided`, `asked`, `failed` [{case_id, error}], tokens."""
    out_path = Path(out_path)
    decided = _load_json(out_path, [])
    done = {str(d["case_id"]) for d in decided}
    failed, asked, in_tok, out_tok = [], 0, 0, 0
    for n, card in enumerate(cards, 1):
        cid = card["case_id"]
        if str(cid) in done:
            continue
        asked += 1
        log(f"[{n}/{len(cards)}] {cid} {card.get('cite') or ''} ({card['section']}/{card['decide_field']})")
        try:
            resp = provider.complete(Request(pin={"model": model}, user=build_prompt(card, brief=brief, handoff=handoff)))
            in_tok += resp.input_tokens or 0
            out_tok += resp.output_tokens or 0
            entry = parse_decision(resp.text, card)
        except (ReaderError, ValueError) as exc:
            failed.append({"case_id": cid, "error": str(exc)})
            log(f"    FAILED: {exc}")
            continue
        decided.append(entry)
        done.add(str(cid))
        _dump(out_path, decided)
        log(f"    {entry['field']} {entry['decision']}"
            + (f" {entry['value']!r}" if "value" in entry else "") + f" - {entry['note'][:90]}")
    order = {str(c["case_id"]): i for i, c in enumerate(cards)}
    decided.sort(key=lambda d: order.get(str(d["case_id"]), len(order)))
    _dump(out_path, decided)
    version = provider.version() if hasattr(provider, "version") else None
    man = {"model": model, "codex_version": version, "cards": len(cards), "decided": len(decided),
           "asked": asked, "failed": failed, "input_tokens": in_tok, "output_tokens": out_tok,
           "decisions": str(out_path).replace("\\", "/")}
    _dump(manifest_path_for(out_path), man)
    return man


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cards", required=True, help="the round's card export .json (with --full-text)")
    ap.add_argument("--brief", default=DEFAULT_BRIEF)
    ap.add_argument("--handoff", required=True, help="the round's handoff addendum .md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", required=True, help="the decisions file to write (resumable)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per call")
    ap.add_argument("--limit", type=int, default=None, help="ask at most N cards this run")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    cards = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    missing = [c["case_id"] for c in cards if "opinion_text" not in c]
    if missing:
        print(f"{len(missing)} cards carry no opinion_text; export with --full-text", file=sys.stderr)
        return 2
    if a.limit:
        cards = cards[:a.limit]
    brief = Path(a.brief).read_text(encoding="utf-8")
    handoff = Path(a.handoff).read_text(encoding="utf-8")
    provider = CodexCliProvider(a.model, timeout=a.timeout)
    man = run_first_pass(cards, brief=brief, handoff=handoff, provider=provider,
                         out_path=Path(a.out), model=a.model, log=lambda *x: print(*x, flush=True))
    print(f"decided {man['decided']}/{man['cards']} (asked {man['asked']}, failed {len(man['failed'])}) "
          f"-> {man['decisions']}; manifest {manifest_path_for(Path(a.out)).as_posix()}", flush=True)
    return 1 if man["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
