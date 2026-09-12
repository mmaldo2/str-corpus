# tools/threeway_sheet.py
"""Three-way sheet: Claude first pass vs GPT Astra vs the checker, per card (one-field rounds)
or per field (--per-field, the audit). One-field mode also writes the agreed set in the apply
schema; per-field mode never does (the audit applies only the user's decisions)."""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from corpus_engine.evaluation.agreement import effective_label, WITHDRAWN   # noqa: E402
from export_review_cards import write_text                                   # noqa: E402


def _cards(queue: Mapping) -> dict[int, dict]:
    out = {}
    for sec, lst in (queue.get("sections") or {}).items():
        for c in lst:
            out[int(c["case_id"])] = dict(c, section=sec)
    return out


def _by_case(decisions: Sequence[Mapping]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for d in decisions or ():
        out.setdefault(int(d["case_id"]), []).append(dict(d))
    return out


def _label_for(entries: list[dict], card: dict, field: str, checker_values) -> tuple[str, str]:
    """(label, note) for `field` on this card from one reader's entries."""
    for d in entries:
        if effective_label(d, card, checker_values) == WITHDRAWN:
            return WITHDRAWN, d.get("note", "")
    for d in entries:
        if d.get("field") == field:
            return effective_label(d, card, checker_values), d.get("note", "")
    return "MISSING", ""


def build(queue: Mapping, checker: Mapping, claude: Sequence[Mapping], astra: Sequence[Mapping], *,
          label: str, per_field: bool = False) -> tuple[str, list[dict]]:
    cards = _cards(queue)
    cl, asr = _by_case(claude), _by_case(astra)
    rows_dis, rows_agr, agreed, sec_tally = [], [], [], {}
    for cid in sorted(cards):
        card = cards[cid]
        chk = ((checker.get(str(cid)) or {}).get("values") or {})
        fields = card.get("decide_fields") or [card["decide_field"]]
        for f in fields:
            a, an = _label_for(cl.get(cid, []), card, f, chk)
            b, bn = _label_for(asr.get(cid, []), card, f, chk)
            if per_field:
                row = (f"| {cid} | {card.get('cite') or ''} | {f} | {a} | {b} | "
                       f"{an[:160].replace('|', '/')} | {bn[:160].replace('|', '/')} |")
            else:
                row = (f"| {cid} | {card.get('cite') or ''} | {card.get('section')} | {f} | "
                       f"{card.get('values', {}).get(f, '')} | {chk.get(f, '')} | {a} | {b} | "
                       f"{an[:160].replace('|', '/')} | {bn[:160].replace('|', '/')} |")
            t = sec_tally.setdefault(card.get("section"), Counter())
            if a == b and a != "MISSING":
                rows_agr.append(row); t["agree"] += 1
                if not per_field:
                    d = next((x for x in cl[cid] if x.get("field") == f or effective_label(x, card, chk) == WITHDRAWN), None)
                    if d:
                        d = dict(d)
                        if d.get("decision") == "adopt":
                            d["decision"], d["value"] = "set", chk.get(f)
                        agreed.append(d)
            else:
                rows_dis.append(row); t["disagree"] += 1
            if not per_field:
                break
    n_agree, n_dis = len(rows_agr), len(rows_dis)
    unit = "fields" if per_field else "cards"
    head = [f"# Three-way sheet: {label}", "",
            (f"{len(cards)} cards. {unit} agree {n_agree}; disagree {n_dis}." if per_field
             else f"{len(cards)} cards. Claude and Astra agree on {n_agree}; disagree on {n_dis}."),
            "", "| section | agree | disagree |", "|---|---|---|"]
    head += [f"| {s} | {t['agree']} | {t['disagree']} |" for s, t in sorted(sec_tally.items())]
    if per_field:
        hdr = ["| case | cite | field | Claude | Astra | Claude note | Astra note |",
               "|---|---|---|---|---|---|---|"]
    else:
        hdr = ["| case | cite | sec | field | current | checker | Claude | Astra | Claude note | Astra note |",
               "|---|---|---|---|---|---|---|---|---|---|"]
    md = "\n".join(head + ["", "## Disagreements", ""] + hdr + rows_dis + ["", "## Agreements", ""] + hdr + rows_agr) + "\n"
    agreed.sort(key=lambda d: (int(d["case_id"]), d["field"]))
    return md, ([] if per_field else agreed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", required=True); ap.add_argument("--checker", default=None)
    ap.add_argument("--claude", required=True); ap.add_argument("--astra", required=True)
    ap.add_argument("--out-md", required=True); ap.add_argument("--out-agreed", default=None)
    ap.add_argument("--per-field", action="store_true"); ap.add_argument("--label", required=True)
    a = ap.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    checker = load(a.checker) if a.checker and Path(a.checker).exists() else {}
    md, agreed = build(load(a.queue), checker, load(a.claude), load(a.astra), label=a.label, per_field=a.per_field)
    write_text(Path(a.out_md), md)
    if a.out_agreed and not a.per_field:
        write_text(Path(a.out_agreed), json.dumps(agreed, indent=1, ensure_ascii=False))
    print(md.splitlines()[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
