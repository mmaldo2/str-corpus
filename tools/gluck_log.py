"""Ledger answers into the running log (spec docs/superpowers/specs/2026-10-04-ledger-answers-running-log-design.md).

  .venv/Scripts/python tools/gluck_log.py run --all
  .venv/Scripts/python tools/gluck_log.py run --question q1 --question q3
  .venv/Scripts/python tools/gluck_log.py list

Reads reports/gluck/questions.yaml (gitignored); writes reports/gluck/out/<date>-<id>-<slug>/
(answer.html, cases.csv or counts.csv, summary.json) and appends to reports/gluck/log.md. The
ledger and the corpus are read only. Publishing to Drive is a separate, agent-run step."""
from __future__ import annotations
import argparse
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import concordance as cc                                # noqa: E402
from corpus_engine.answers import records as ar                            # noqa: E402
from corpus_engine.answers import render as rd                             # noqa: E402
from corpus_engine.answers.citations import citation_sets                  # noqa: E402
from corpus_engine.answers.questions import QuestionError, load_questions  # noqa: E402
from corpus_engine.domain import load_domain                               # noqa: E402
from corpus_engine.ledger import open_ledger                               # noqa: E402


def _ro(db) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-") or "answer"


def _folder(out: Path, name: str) -> Path:
    path, k = out / name, 2
    while path.exists():
        path, k = out / f"{name}-{k}", k + 1
    return path


def build_records(q, *, view, domain, conn, reviewed):
    recs = ar.select(view, domain, q, conn=conn)
    ids = [int(r["case_id"]) for r in recs]
    cites = citation_sets(conn, ids, jurisdiction_of={int(r["case_id"]): r.get("jurisdiction") for r in recs},
                          preference=domain.citation_preference)
    names = ar.names_and_courts(conn, ids)
    rows = ar.case_rows(recs, domain=domain, reviewed=reviewed, names=names, citations=cites)
    earliest = []
    if q.earliest_per_jurisdiction:
        for e in ar.earliest_per_jurisdiction(recs, q.earliest_per_jurisdiction, domain=domain):
            e["case_name"] = names.get(e["case_id"], ("", ""))[0]
            e["citations"] = "; ".join(cites.get(e["case_id"]) or [])
            earliest.append(e)
    return rows, {"summary": ar.summary(recs, domain=domain, reviewed=reviewed, group_by=q.group_by),
                  "earliest": earliest}


def build_concordance(q, *, conn, dens, domain):
    order = {e: i for i, e in enumerate(domain.eras)}
    rows, terms = [], []
    for t in q.terms:
        try:
            cells = cc.cell_counts(conn, t.expr, expr=t.is_expr, stem=t.stem)
            first = cc.earliest(conn, t.expr, expr=t.is_expr, stem=t.stem, n=5)
        except sqlite3.OperationalError as exc:
            raise SystemExit(f"{q.id}: term {t.label!r}: {exc}")
        for (e, j), d in sorted(dens.items(), key=lambda kv: (order.get(kv[0][0], 99), str(kv[0][1]))):
            m = cells.get((e, j), 0)
            rows.append({"term": t.label, "era": e, "jurisdiction": j, "matches": m, "opinions": d,
                         "rate_per_1000": cc.rate(m, d)})
        terms.append({"label": t.label, "expr": t.expr, "fts_expression": t.is_expr, "stem": t.stem,
                      "by_era": cc.era_table(cells, dens, eras=domain.eras), "earliest": first})
    return rows, {"concordance": terms}


def cmd_run(a) -> int:
    root = Path(a.root)
    domain = load_domain()
    try:
        questions = load_questions(root / "questions.yaml", domain)
    except QuestionError as exc:
        raise SystemExit(f"questions.yaml: {exc}")
    missing = sorted(set(a.question) - {q.id for q in questions})
    if missing:
        raise SystemExit(f"no such question: {', '.join(missing)}")
    wanted = [q for q in questions if a.all or q.id in a.question]
    if not wanted:
        raise SystemExit("nothing to run: pass --all or --question <id>")
    view = open_ledger(Path(a.ledger), domain=domain).view()
    reviewed = view.reviewed_ids()
    conn = _ro(a.db)
    st = rd.stamp(view, root / "questions.yaml", repo=ROOT, date=a.date)
    dens = cc.denominators(conn) if any(q.kind == "concordance" for q in wanted) else {}
    built = []                                   # everything is built before anything is written
    for q in wanted:
        if q.kind == "concordance":
            rows, extra = build_concordance(q, conn=conn, dens=dens, domain=domain)
            name, cols = "counts.csv", rd.COUNT_COLUMNS
        else:
            rows, extra = build_records(q, view=view, domain=domain, conn=conn, reviewed=reviewed)
            name, cols = "cases.csv", ar.COLUMNS
        reading_path = root / "readings" / f"{q.id}.md"
        reading = reading_path.read_text(encoding="utf-8") if reading_path.exists() else None
        built.append((q, rows, name, cols, extra, reading))
    out = root / "out"
    for q, rows, name, cols, extra, reading in built:
        folder = _folder(out, f"{a.date}-{q.id}-{slug(q.title)}")
        folder.mkdir(parents=True)
        rd.write_csv(folder / name, rows, cols)
        rd.write_text(folder / "answer.html", rd.answer_html(q, st, n_rows=len(rows), reading=reading, **extra))
        rd.write_text(folder / "summary.json", json.dumps(
            {"question": rd.question_json(q), "stamp": st, **extra}, indent=1, default=str) + "\n")
        rd.append_log(root / "log.md", f"- {a.date} · {q.id} · {q.title} · seq {st['ledger_seq']} · "
                                       f"out/{folder.name} · Drive: unpublished")
        print(f"{q.id}: {len(rows)} rows -> {folder}")
    return 0


def cmd_list(a) -> int:
    root = Path(a.root)
    for q in load_questions(root / "questions.yaml", load_domain()):
        print(f"{q.id}  {q.kind:12} {q.title}")
    log = root / "log.md"
    if log.exists():
        print(log.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT / "reports" / "gluck"))
    ap.add_argument("--db", default=str(ROOT / "data" / "db" / "corpus.db"))
    ap.add_argument("--ledger", default=str(ROOT / "data" / "ledger"))
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--question", action="append", default=[])
    r.add_argument("--all", action="store_true")
    sub.add_parser("list")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return {"run": cmd_run, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
