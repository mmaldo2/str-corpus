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
import hashlib
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


AUDIT_FIELDS = ("relevant", "polarity", "who_was_letting")
AUDIT_CARD = """## This call

You are given ONE card with the full opinion text and nothing else about the case. From the
opinion alone, decide `relevant` (true|false) and, if true, `polarity` and `who_was_letting`.
Reply with exactly one JSON list: three entries {"case_id", "field", "decision": "set", "value",
"note"} (relevant, polarity, who_was_letting) when relevant is true; exactly one entry with
"field": "relevant", "value": false when it is not a letting case; or exactly one entry
{"case_id", "field": "relevant", "decision": "unresolved", "note"} if the text is unreadable.
No keep, adopt or unsure. Nothing but the JSON list is needed in the reply.
"""


def build_prompt_audit(card: dict, *, brief: str) -> str:
    card_md = markdown_for([card], "", audit=True)
    return "\n\n".join([brief.strip(), AUDIT_CARD.strip(), card_md.strip()]) + "\n"


def parse_decisions_audit(text: str, card: dict) -> list[dict]:
    # A bare JSON list, fenced or not - read directly rather than through _json_objects, which
    # only ever surfaces single-object lists (a dict with "decision") and would drop this one.
    lst = None
    for cand in (_FENCE.findall(text) or []) + [text]:
        i = cand.find("[")
        while i >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(cand, i); lst = obj; break
            except ValueError:
                i = cand.find("[", i + 1)
        if lst is not None:
            break
    if not isinstance(lst, list) or not lst:
        raise ValueError("no JSON list of decisions in the reply")
    entries = []
    for d in lst:
        if str(d.get("case_id")) != str(card["case_id"]):
            raise ValueError(f"case_id {d.get('case_id')!r} is not the card's ({card['case_id']})")
        if d.get("decision") == "unresolved":
            if len(lst) != 1:
                raise ValueError("an unresolved reply is exactly one entry")
            return [{"case_id": card["case_id"], "field": "relevant", "decision": "unresolved",
                     "note": str(d.get("note") or "").strip()}]
        if d.get("decision") != "set":
            raise ValueError(f"decision {d.get('decision')!r}: audit entries are set only, never keep/adopt/unsure")
        if d.get("field") not in AUDIT_FIELDS:
            raise ValueError(f"field {d.get('field')!r} is not one of {AUDIT_FIELDS}")
        entries.append({"case_id": card["case_id"], "field": d["field"], "decision": "set",
                        "value": _checked_value(d["field"], d.get("value")), "note": str(d.get("note") or "").strip()})
    fields = [e["field"] for e in entries]
    if len(set(fields)) != len(fields):
        raise ValueError("duplicate field in the reply")
    rel = next((e for e in entries if e["field"] == "relevant"), None)
    if rel is None:
        raise ValueError("no relevant entry")
    if rel["value"] is False:
        if len(entries) != 1:
            raise ValueError("a withdrawal is exactly one entry")
        return entries
    if sorted(fields) != sorted(AUDIT_FIELDS):
        raise ValueError("a relevant card needs exactly three entries: relevant, polarity, who_was_letting")
    return sorted(entries, key=lambda e: AUDIT_FIELDS.index(e["field"]))


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


def run_first_pass(cards: Sequence[dict], *, brief: str, handoff: str = "", provider,
                   out_path: Path, log: Callable[..., None] = print,
                   model: str = DEFAULT_MODEL, audit: bool = False) -> dict:
    """Ask `provider` about every card not yet in `out_path`; write the decisions file after
    each answer (so a crash loses nothing) and the sidecar manifest at the end. Returns the
    manifest: model, codex version, `decided`, `asked`, `failed` [{case_id, error}], tokens.

    One loop for both modes. Normal mode: the prompt is `build_prompt` (brief + handoff + the
    card), the reply is one `parse_decision` entry, and resume is keyed on `case_id` alone.

    `audit=True` runs the blind single-field-triple pass instead (section H): the prompt is
    `build_prompt_audit` (the brief and `AUDIT_CARD` only - no handoff, no checker), the reply
    is `parse_decisions_audit`'s list of up to three flat entries, `decided` counts CARDS
    (not entries - a card can leave up to three), and resume is keyed on `(case_id,
    brief_sha256)`: a rerun under the SAME brief text skips a card already in `out_path`; a
    rerun under a CHANGED brief moves the existing decisions file aside
    (`<out>-superseded-<oldhash8>.json`, done once, before the loop) and asks every card
    again, because a changed brief means the earlier answers were given under different
    instructions. The returned manifest carries `brief_sha256` only in audit mode."""
    out_path = Path(out_path)
    man_path = manifest_path_for(out_path)
    decided = _load_json(out_path, [])
    brief_sha256 = None
    if audit:
        brief_sha256 = hashlib.sha256(brief.encode("utf-8")).hexdigest()
        old_brief_sha256 = _load_json(man_path, {}).get("brief_sha256")
        if old_brief_sha256 and old_brief_sha256 != brief_sha256:
            # The brief changed since the earlier run: those answers were given under
            # different instructions, so they are moved aside (never discarded) and every
            # card is asked again, rather than silently mixing decisions from two briefs.
            if out_path.exists():
                out_path.rename(out_path.with_name(f"{out_path.stem}-superseded-{old_brief_sha256[:8]}.json"))
            decided = []
    done = {str(d["case_id"]) for d in decided}
    failed, asked, in_tok, out_tok = [], 0, 0, 0
    for n, card in enumerate(cards, 1):
        cid = card["case_id"]
        if str(cid) in done:
            continue
        asked += 1
        tag = "audit" if audit else f"{card['section']}/{card['decide_field']}"
        log(f"[{n}/{len(cards)}] {cid} {card.get('cite') or ''} ({tag})")
        try:
            if audit:
                resp = provider.complete(Request(pin={"model": model}, user=build_prompt_audit(card, brief=brief)))
            else:
                resp = provider.complete(Request(pin={"model": model},
                                                 user=build_prompt(card, brief=brief, handoff=handoff)))
            in_tok += resp.input_tokens or 0
            out_tok += resp.output_tokens or 0
            entries = parse_decisions_audit(resp.text, card) if audit else [parse_decision(resp.text, card)]
        except (ReaderError, ValueError) as exc:
            failed.append({"case_id": cid, "error": str(exc)})
            log(f"    FAILED: {exc}")
            continue
        decided.extend(entries)
        done.add(str(cid))
        _dump(out_path, decided)
        for entry in entries:
            log(f"    {entry['field']} {entry['decision']}"
                + (f" {entry['value']!r}" if "value" in entry else "") + f" - {entry['note'][:90]}")
    order = {str(c["case_id"]): i for i, c in enumerate(cards)}
    if audit:
        decided.sort(key=lambda d: (order.get(str(d["case_id"]), len(order)),
                                    AUDIT_FIELDS.index(d["field"]) if d["field"] in AUDIT_FIELDS else 0))
    else:
        decided.sort(key=lambda d: order.get(str(d["case_id"]), len(order)))
    _dump(out_path, decided)
    version = provider.version() if hasattr(provider, "version") else None
    decided_count = len({str(d["case_id"]) for d in decided}) if audit else len(decided)
    man = {"model": model, "codex_version": version, "cards": len(cards), "decided": decided_count,
           "asked": asked, "failed": failed, "input_tokens": in_tok, "output_tokens": out_tok,
           "decisions": str(out_path).replace("\\", "/")}
    if audit:
        man["brief_sha256"] = brief_sha256
    _dump(man_path, man)
    return man


class _ArgumentParser(argparse.ArgumentParser):
    """`--audit` requires `--workdir` (the isolated cwd `--workdir`'s own help text explains
    why); enforced here, at `parse_args`, rather than in `main`, so `build_parser` alone
    refuses the combination and every caller gets the same argparse-style usage error."""
    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args, namespace)
        if ns.audit and not ns.workdir:
            self.error("--audit requires --workdir")
        return ns


def build_parser() -> argparse.ArgumentParser:
    ap = _ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cards", required=True, help="the round's card export .json (with --full-text)")
    ap.add_argument("--brief", default=DEFAULT_BRIEF)
    ap.add_argument("--handoff", default=None, help="the round's handoff addendum .md; "
                    "required unless --audit")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", required=True, help="the decisions file to write (resumable)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per call")
    ap.add_argument("--limit", type=int, default=None, help="ask at most N cards this run")
    ap.add_argument("--audit", action="store_true",
                    help="the blind audit pass (section H): relevant/polarity/who_was_letting "
                         "only, no handoff, no checker; resume is keyed on the brief's hash")
    ap.add_argument("--workdir", default=None,
                    help="cwd for the codex cli subprocess (CodexCliProvider's cwd) - an "
                         "isolated directory, so the audit pass never runs in a git repo "
                         "checkout the model could read; required with --audit")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if not a.audit and not a.handoff:
        print("--handoff is required unless --audit", file=sys.stderr)
        return 2
    cards = json.loads(Path(a.cards).read_text(encoding="utf-8"))
    missing = [c["case_id"] for c in cards if "opinion_text" not in c]
    if missing:
        print(f"{len(missing)} cards carry no opinion_text; export with --full-text", file=sys.stderr)
        return 2
    if a.limit:
        cards = cards[:a.limit]
    brief = Path(a.brief).read_text(encoding="utf-8")
    handoff = Path(a.handoff).read_text(encoding="utf-8") if a.handoff else ""
    provider = CodexCliProvider(a.model, timeout=a.timeout, cwd=a.workdir)
    man = run_first_pass(cards, brief=brief, handoff=handoff, provider=provider,
                         out_path=Path(a.out), model=a.model, log=lambda *x: print(*x, flush=True),
                         audit=a.audit)
    print(f"decided {man['decided']}/{man['cards']} (asked {man['asked']}, failed {len(man['failed'])}) "
          f"-> {man['decisions']}; manifest {manifest_path_for(Path(a.out)).as_posix()}", flush=True)
    return 1 if man["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
