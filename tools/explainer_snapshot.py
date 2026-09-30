"""The lawyer explainer's figures (spec: docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md).

snapshot  every figure the explainer shows, read at ONE pinned ledger seq from the ledger API,
          corpus.db, the published evaluation JSON and the audit sample manifest; refused (exit 2,
          nothing written) when those inputs describe different ledger states.
render    substitutes {{snap:dotted.path}} placeholders from snapshot.json (ints grouped, text
          verbatim); an unknown key fails the whole render.
lint      the guardrails a text must pass before the team sees it: no dollar amounts, no retired
          pages, nothing left unrendered, and (templates) no literal grouped numbers.

Counts are ints; years and identifiers are strings, so a later render never groups them."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from export_review_cards import write_text                     # noqa: E402
from corpus_engine import store                                # noqa: E402
from corpus_engine.domain import load_domain                   # noqa: E402
from corpus_engine.ledger import open_ledger                   # noqa: E402
from draw_audit_sample import _in_frame, _sha                  # noqa: E402  the audit frame's own definition

AUDIT_STATUS = "drawn, not yet read"
LOSS_KEYS = {"unsignaled": "unsignaled", "reader-negative": "reader_negative", "withdrawn": "withdrawn"}
TIERS = ("relevant", "favorable", "favorable_householder")


class SnapshotError(Exception):
    """The inputs disagree about which ledger state they describe, or a figure cannot be derived."""


def tier(t) -> dict:
    return {"human_reviewed": t.human_reviewed, "machine_only": t.machine_only,
            "total": t.human_reviewed + t.machine_only}


def millions(n: int) -> str:
    return f"about {n / 1_000_000:.1f} million"


def long_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d:%B} {d.day}, {d.year}"


def ledger_figures(view, as_of: int) -> dict:
    if view.as_of != as_of:
        raise SnapshotError(f"ledger head is seq {view.as_of}, not the requested snapshot seq {as_of}")
    return {"as_of": as_of, "date": view.patches[-1].at[:10],
            "opinions_read": len(view.state.order),
            "relevant": tier(view.counts().total),
            "favorable": tier(view.counts(polarity="favorable").total),
            "adverse": tier(view.counts(polarity="adverse").total),
            "mixed": tier(view.counts(polarity="mixed").total),
            "favorable_householder": tier(view.counts(polarity="favorable",
                                                      who_was_letting="householder").total),
            "matrix": matrix_figures(view)}


def matrix_figures(view) -> dict:
    """The tradition grid (favorable opinions by era x region x letting tier x duration), limited to the
    regions that hold at least one searched jurisdiction; cells are [era, region, tier, duration, human, machine]."""
    d = view.domain
    names = list(dict.fromkeys(d.regions.values()))
    regions = [{"name": n, "jurisdictions": sorted(j for j in d.jurisdictions if d.regions.get(j) == n)} for n in names]
    regions = [r for r in regions if r["jurisdictions"]]
    kept = {r["name"] for r in regions}
    eras, tiers, durations = list(d.eras), list(dict.fromkeys(d.letting_tiers.values())), ["nights", "weeks", "months", "unclear"]
    all_cells = view.matrix().cells
    stray = sorted({k for k, t in all_cells.items() if (t.human_reviewed or t.machine_only) and k[1] in kept
                    and (k[0] not in eras or k[2] not in tiers or k[3] not in durations)})
    if stray:
        raise SnapshotError(f"favorable opinions fall outside the grid's axes: {stray[:3]}")
    cells = [[k[0], k[1], k[2], k[3], t.human_reviewed, t.machine_only]
             for k, t in sorted(all_cells.items()) if k[1] in kept]
    fav = view.counts(polarity="favorable").total
    got = (sum(c[4] for c in cells), sum(c[5] for c in cells))
    if got != (fav.human_reviewed, fav.machine_only):
        dropped = sorted({k[1] for k, t in all_cells.items() if k[1] not in kept and (t.human_reviewed or t.machine_only)})
        raise SnapshotError(f"the grid holds {got[0]}/{got[1]} favorable opinions but the ledger has "
                            f"{fav.human_reviewed}/{fav.machine_only}; outside the searched regions: {dropped}")
    return {"eras": eras, "regions": regions, "tiers": tiers, "durations": durations, "cells": cells}


def library_figures(conn, jurisdictions: Sequence[str]) -> dict:
    marks = ",".join("?" * len(jurisdictions))
    total = conn.execute("SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL").fetchone()[0]
    n, lo, hi = conn.execute(
        f"SELECT count(*), min(decision_year), max(decision_year) FROM cases "
        f"WHERE is_duplicate_of IS NULL AND jurisdiction IN ({marks})", tuple(jurisdictions)).fetchone()
    flagged = conn.execute(
        f"SELECT count(DISTINCT s.case_id) FROM signals s JOIN cases c ON c.case_id = s.case_id "
        f"WHERE c.is_duplicate_of IS NULL AND c.jurisdiction IN ({marks})", tuple(jurisdictions)).fetchone()[0]
    return {"canonical_total": total, "in_scope": n, "outside_scope": total - n, "flagged": flagged,
            "jurisdictions": len(jurisdictions), "first_year": str(lo), "last_year": str(hi),
            "in_scope_display": millions(n),
            "outside_scope_display": f"about {round((total - n) / 1000):,} thousand"}


def benchmark_figures(evaluation: Mapping) -> dict:
    g = evaluation["gold_recovery"]
    u = g["union"]
    counted = Counter(m["lost_at"] for m in g["misses"])
    lost = {key: counted.get(raw, 0) for raw, key in LOSS_KEYS.items()}
    lost["other"] = sum(n for raw, n in counted.items() if raw not in LOSS_KEYS)
    lost["total"] = sum(counted.values())
    expected = u["resolved"] - u["relevant"]
    if lost["total"] != expected:
        raise SnapshotError(f"benchmark misses list {lost['total']} losses but resolved - kept = {expected}")
    return {"entries": u["entries"], "resolved": u["resolved"], "read": u["read"], "kept": u["relevant"],
            "kept_human": u["relevant_human"], "unresolved": len(g["unresolved"]), "lost": lost}


def tail_figures(evaluation: Mapping) -> dict:
    c = evaluation["coverage"]
    est = [s["estimated_relevant"] for s in c["scenarios"]]
    return {"unread": sum(b["unread_cases"] for b in c["bands"]), "low": min(est), "high": max(est)}


def audit_figures(sample: Mapping, as_of: int) -> dict:
    """`status` is asserted only at the seq the sample was drawn; at a later snapshot the audit may
    have been read, and this tool has no input that says so, so a template asking for it fails."""
    out = {"n": sample["n"], "frame_size": sample["frame_size"], "seed": str(sample["seed"]),
           "drawn_seq": sample["ledger_head_seq"], "drawn_date": sample["drawn_at"][:10]}
    if sample["ledger_head_seq"] == as_of:
        out["status"] = AUDIT_STATUS
    return out


def audit_positions(view, sample: Mapping) -> list[int]:
    """Where each audit pick sits in its frame, recomputed from the ledger at the draw's own seq and checked
    against the manifest's frame size and hash, so the page's dot grid shows the real draw."""
    seq = sample["ledger_head_seq"]
    if view.as_of != seq:
        raise SnapshotError(f"audit frame needs the ledger at seq {seq}; the view is at {view.as_of}")
    frame = sorted(cid for cid in view.state.order if _in_frame(view, cid))
    if len(frame) != sample["frame_size"] or _sha("\n".join(map(str, frame))) != sample.get("frame_sha256"):
        raise SnapshotError(f"audit frame at seq {seq} has {len(frame)} records and does not match the manifest "
                            f"({sample['frame_size']} records, sha {str(sample.get('frame_sha256'))[:12]})")
    index = {cid: i for i, cid in enumerate(frame)}
    missing = [r["case_id"] for r in sample["records"] if r["case_id"] not in index]
    if missing:
        raise SnapshotError(f"audit pick(s) {missing[:5]} not in the frame")
    return sorted(index[r["case_id"]] for r in sample["records"])


def check_consistency(as_of: int, ledger: Mapping, evaluation: Mapping, sample: Mapping) -> None:
    seq = evaluation["ledger"]["reporting_seq"]
    if seq != as_of:
        raise SnapshotError(f"evaluation reports ledger seq {seq}, not the snapshot seq {as_of}")
    for name in TIERS:
        want = evaluation["ledger"]["counts"][name]
        got = ledger[name]
        if (got["human_reviewed"], got["machine_only"]) != (want["human_reviewed"], want["machine_only"]):
            raise SnapshotError(f"{name}: ledger {got['human_reviewed']}/{got['machine_only']} at seq "
                                f"{as_of} but the evaluation says {want['human_reviewed']}/{want['machine_only']}")
    if sample["ledger_head_seq"] > as_of:
        raise SnapshotError(f"audit sample drawn at seq {sample['ledger_head_seq']}, after the snapshot seq {as_of}")


def build_snapshot(*, label: str, as_of: int, view, conn, jurisdictions: Sequence[str],
                   evaluation: Mapping, sample: Mapping, git_revision: str, inputs: Mapping, draw_view=None) -> dict:
    led = ledger_figures(view, as_of)
    check_consistency(as_of, led, evaluation, sample)
    audit = audit_figures(sample, as_of)
    audit["positions"] = audit_positions(draw_view if draw_view is not None else view, sample)
    return {"snapshot": {"label": label, "as_of": as_of, "date": led["date"],
                         "date_display": long_date(led["date"]), "git_revision": git_revision,
                         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "library": library_figures(conn, jurisdictions),
            "ledger": led,
            "benchmark": benchmark_figures(evaluation),
            "tail": tail_figures(evaluation),
            "audit": audit,
            "inputs": dict(inputs)}


PLACEHOLDER = re.compile(r"\{\{snap:([A-Za-z0-9_.]+)\}\}")
JSON_PLACEHOLDER = re.compile(r"\{\{json:([A-Za-z0-9_]+)((?:\.[A-Za-z0-9_]+)*)\}\}")
DOLLAR = re.compile(r"\$\s?\d")
GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?!\d|,\d)")   # "4,351, and" still counts
TAG = re.compile(r"<[^>]*>")
ALLOW_PRICE = "lint-allow: historical price"
RETIRED = ("right-to-let-guide", "attorney-report", "the right-to-let record", "right-to-let corpus engine")


def resolve(snapshot: Mapping, path: str):
    cur = snapshot
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def format_value(value, path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SnapshotError(f"{{{{snap:{path}}}}} is a {type(value).__name__}; only counts and text render")
    return f"{value:,}" if isinstance(value, int) else value


def render(text: str, snapshot: Mapping, data: Mapping | None = None) -> str:
    """Fill {{snap:path}} with a formatted value, then {{json:source.path}} with compact JSON for a page's
    <script type="application/json"> block (source "snap" or a named data file; "</" is escaped)."""
    missing: list[str] = []
    sources = {"snap": snapshot, **(data or {})}

    def sub(m: re.Match) -> str:
        try:
            return format_value(resolve(snapshot, m.group(1)), m.group(1))
        except KeyError:
            missing.append(m.group(1))
            return m.group(0)

    def sub_json(m: re.Match) -> str:
        source, path = m.group(1), m.group(2).lstrip(".")
        try:
            value = resolve(sources[source], path) if path else sources[source]
        except KeyError:
            missing.append(f"{source}.{path}" if path else source)
            return m.group(0)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    out = JSON_PLACEHOLDER.sub(sub_json, PLACEHOLDER.sub(sub, text))
    if missing:
        raise SnapshotError("unknown snapshot keys: " + ", ".join(sorted(set(missing))))
    return out


def lint(text: str, *, template: bool) -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if DOLLAR.search(line) and ALLOW_PRICE not in line:
            problems.append(f"line {i}: dollar amount")
        low = line.lower()
        for name in RETIRED:
            if name in low:
                problems.append(f"line {i}: reference to retired page {name!r}")
        if template:   # figures live in text; commas inside tags (font axes, SVG points) are markup
            for m in GROUPED.finditer(TAG.sub(" ", JSON_PLACEHOLDER.sub("", PLACEHOLDER.sub("", line)))):
                problems.append(f"line {i}: literal grouped number {m.group(0)!r} (use a {{{{snap:...}}}} placeholder)")
        elif "{{" in line:
            problems.append(f"line {i}: unrendered placeholder")
    return problems


def _report(problems: list[str], label: str) -> None:
    for p in problems:
        print(f"{label}: {p}", file=sys.stderr)


def cmd_render(a) -> int:
    src = Path(a.template).read_text(encoding="utf-8")
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    data = {}
    for spec in a.data:
        name, _, path = spec.partition("=")
        if not re.fullmatch(r"[A-Za-z0-9_]+", name) or name == "snap" or not path:
            print(f"refused: --data takes NAME=FILE with a name other than 'snap' (got {spec!r})", file=sys.stderr)
            return 1
        data[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = lint(src, template=True)
    if problems:
        _report(problems, a.template)
        return 1
    try:
        out = render(src, snap, data)
    except SnapshotError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    problems = lint(out, template=False)
    if problems:
        _report(problems, "rendered output")
        return 1
    write_text(Path(a.out), out)
    print(f"{Path(a.template).as_posix()} -> {Path(a.out).as_posix()}")
    return 0


def cmd_lint(a) -> int:
    problems = lint(Path(a.input).read_text(encoding="utf-8"), template=a.template)
    _report(problems, a.input)
    return 1 if problems else 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_snapshot(a) -> int:
    ev_path, sample_path = Path(a.evaluation), Path(a.sample)
    evaluation = json.loads(ev_path.read_text(encoding="utf-8"))
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    domain = load_domain()
    ledger = open_ledger(Path(a.ledger_dir) if a.ledger_dir else None, domain=domain)
    view = ledger.view(as_of=a.as_of)
    draw_view = ledger.view(as_of=min(sample["ledger_head_seq"], a.as_of))
    conn = store.connect(Path(a.db) if a.db else None, wal=False)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    try:
        snap = build_snapshot(label=a.label, as_of=a.as_of, view=view, conn=conn,
                              jurisdictions=domain.jurisdictions, evaluation=evaluation, sample=sample,
                              git_revision=rev, draw_view=draw_view,
                              inputs={"evaluation_sha256": _sha256(ev_path), "sample_sha256": _sha256(sample_path),
                                      "ledger_content_sha256": evaluation["ledger"]["content_sha256"]})
    except SnapshotError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    write_text(Path(a.out), json.dumps(snap, indent=1, ensure_ascii=False))
    print(f"{a.label} at seq {a.as_of} -> {Path(a.out).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="read every explainer figure at one pinned ledger seq")
    s.add_argument("--as-of", type=int, required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--evaluation", required=True)
    s.add_argument("--sample", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--ledger-dir", default=None, help="default: the project ledger")
    s.add_argument("--db", default=None, help="default: data/db/corpus.db")
    r = sub.add_parser("render", help="fill {{snap:...}} placeholders; lint before and after")
    r.add_argument("--template", required=True)
    r.add_argument("--snapshot", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--data", action="append", default=[], metavar="NAME=FILE",
                   help="a JSON file the template reads as {{json:NAME.path}}")
    li = sub.add_parser("lint", help="check a file against the explainer guardrails")
    li.add_argument("--in", dest="input", required=True)
    li.add_argument("--template", action="store_true")
    a = ap.parse_args(argv)
    return {"snapshot": cmd_snapshot, "render": cmd_render, "lint": cmd_lint}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
