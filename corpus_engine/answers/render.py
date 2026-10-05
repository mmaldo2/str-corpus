"""HTML, CSV and JSON for a ledger answer (spec 2026-10-04-ledger-answers-running-log, section 6)."""
from __future__ import annotations
import csv
import dataclasses
import hashlib
import html
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Sequence

CAVEATS = ("Counts are lower bounds.",
           "Machine-only precision is unmeasured until the audit is applied.",
           "Nothing here is citable before a citator check and a page-image pin-cite check.")
COUNT_COLUMNS = ("term", "era", "jurisdiction", "matches", "opinions", "rate_per_1000")
REVIEW_LIST_LABEL = "Candidates for review, not a finding."
STYLE = ("<style>body{font-family:Georgia,serif;max-width:60em;margin:2em auto;line-height:1.4}"
         "table{border-collapse:collapse;margin:.5em 0 1.5em}td,th{border:1px solid #999;padding:.2em .5em;"
         "text-align:left}.stamp{color:#555}</style>")


def write_text(path, text: str) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_csv(path, rows: Iterable[Mapping], columns: Sequence[str]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columns), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: "" if r.get(c) is None else r.get(c) for c in columns})


def append_log(path, line: str) -> None:
    path = Path(path)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# Running log\n\n")
        f.write(line + "\n")


def stamp(view, questions_path, *, repo, date: str) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                                text=True, timeout=30).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    return {"ledger_seq": view.as_of, "date": date, "code_commit": commit,
            "questions_sha256": hashlib.sha256(Path(questions_path).read_bytes()).hexdigest()[:12]}


def question_json(q) -> dict:
    return dataclasses.asdict(q)


def _cond(field: str, values: Sequence) -> str:
    return f"{field.replace('_', ' ')} is {' or '.join(str(v) for v in values)}"


def method_line(q) -> str:
    parts = [_cond(f, v) for f, v in q.population.items()]
    if q.any_of:
        parts.append("(" + " or ".join(" and ".join(_cond(f, v) for f, v in m.items())
                                       for m in q.any_of) + ")")
    if q.text_match:
        parts.append(f"the text of {', '.join(q.text_match['in'])} matches any of: "
                     f"{', '.join(q.text_match['terms'])}")
    base = "Counted ledger records (relevant, not a merged parallel copy)"
    return base + (" where " + "; ".join(parts) if parts else "") + "."


def _table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    h = html.escape
    head = "".join(f"<th>{h(str(x))}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{h('' if v is None else str(v))}</td>" for v in r) + "</tr>"
                   for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def answer_html(q, stamp: Mapping, *, n_rows: int, reading: str | None = None,
                summary: Mapping | None = None, earliest: Sequence[Mapping] | None = None,
                concordance: Sequence[Mapping] | None = None) -> str:
    h = html.escape
    out = ["<!doctype html><html><head><meta charset='utf-8'>",
           f"<title>{h(q.id.upper())} · {h(q.title)}</title>", STYLE, "</head><body>",
           f"<h1>{h(q.id.upper())} · {h(q.title)}</h1>",
           f"<p class='stamp'>Ledger seq {stamp['ledger_seq']} · {h(stamp['date'])} · code "
           f"{h(stamp['code_commit'])} · questions {h(stamp['questions_sha256'])}</p>"]
    if q.review_list:
        out.append(f"<p><strong>{REVIEW_LIST_LABEL}</strong></p>")
    if q.kind == "records":
        out.append(f"<p><strong>Method.</strong> {h(method_line(q))}</p>")
    if reading:
        out.append("<h2>Reading</h2>" + "".join(f"<p>{h(p.strip())}</p>"
                                                for p in reading.split("\n\n") if p.strip()))
    if summary is not None:
        t = summary["total"]
        out.append("<h2>Counts</h2>" + _table(("human-reviewed", "machine-only"),
                                              [(t["human_reviewed"], t["machine_only"])]))
        keys = list(summary["by_group"][0]["key"]) if summary["by_group"] else []
        if keys:
            out.append("<h3>By " + h(", ".join(k.replace("_", " ") for k in keys)) + "</h3>" + _table(
                [k.replace("_", " ") for k in keys] + ["human-reviewed", "machine-only"],
                [[g["key"][k] for k in keys] + [g["human_reviewed"], g["machine_only"]]
                 for g in summary["by_group"]]))
        out.append("<h3>By jurisdiction and era</h3>" + _table(
            ("jurisdiction", "era", "human-reviewed", "machine-only"),
            [(c["jurisdiction"], c["era"], c["human_reviewed"], c["machine_only"])
             for c in summary["by_jurisdiction_era"]]))
        out.append(f"<p>Case table (the sheet): {t['human_reviewed']} human-reviewed and "
                   f"{t['machine_only']} machine-only records.</p>")
    if earliest:
        where = " and ".join(_cond(f, v) for f, v in (q.earliest_per_jurisdiction or {}).items())
        out.append(f"<h3>Earliest per jurisdiction{' where ' + h(where) if where else ''}</h3>" + _table(
            ("jurisdiction", "year", "case", "citations", "review"),
            [(e["jurisdiction"], e["year"], e.get("case_name", ""), e.get("citations", ""),
              e.get("review_tier", "")) for e in earliest]))
    for term in concordance or ():
        out.append(f"<h2>{h(term['label'])}</h2><p class='stamp'>FTS: {h(term['expr'])}"
                   f"{' (expression)' if term['fts_expression'] else ''}"
                   f"{' (stemmed)' if term['stem'] else ''}</p>")
        out.append(_table(("era", "opinions matching", "opinions", "per 1,000"),
                          [(e, r["matches"], r["opinions"], r["rate"]) for e, r in term["by_era"].items()]))
        out.append("<h3>Earliest uses</h3>" + _table(
            ("year", "cite", "case", "jurisdiction", "context"),
            [(u["year"], u["cite"], u["name"], u["jurisdiction"], u["context"]) for u in term["earliest"]]))
    out.append("<h2>Caveats</h2><ul>" + "".join(f"<li>{h(c)}</li>" for c in CAVEATS) + "</ul>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"
