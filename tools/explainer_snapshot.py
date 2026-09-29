"""The lawyer explainer's figures (spec: docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md).

snapshot  every figure the explainer shows, read at ONE pinned ledger seq from the ledger API,
          corpus.db, the published evaluation JSON and the audit sample manifest; refused (exit 2,
          nothing written) when those inputs describe different ledger states.

Counts are ints; years and identifiers are strings, so a later render never groups them."""
from __future__ import annotations
import argparse
import hashlib
import json
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
            "favorable_householder": tier(view.counts(polarity="favorable",
                                                      who_was_letting="householder").total)}


def library_figures(conn, jurisdictions: Sequence[str]) -> dict:
    marks = ",".join("?" * len(jurisdictions))
    total = conn.execute("SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL").fetchone()[0]
    n, lo, hi = conn.execute(
        f"SELECT count(*), min(decision_year), max(decision_year) FROM cases "
        f"WHERE is_duplicate_of IS NULL AND jurisdiction IN ({marks})", tuple(jurisdictions)).fetchone()
    return {"canonical_total": total, "in_scope": n, "outside_scope": total - n,
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


def audit_figures(sample: Mapping) -> dict:
    return {"n": sample["n"], "frame_size": sample["frame_size"], "seed": str(sample["seed"]),
            "drawn_seq": sample["ledger_head_seq"], "drawn_date": sample["drawn_at"][:10],
            "status": AUDIT_STATUS}


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
                   evaluation: Mapping, sample: Mapping, git_revision: str, inputs: Mapping) -> dict:
    led = ledger_figures(view, as_of)
    check_consistency(as_of, led, evaluation, sample)
    return {"snapshot": {"label": label, "as_of": as_of, "date": led["date"],
                         "date_display": long_date(led["date"]), "git_revision": git_revision,
                         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "library": library_figures(conn, jurisdictions),
            "ledger": led,
            "benchmark": benchmark_figures(evaluation),
            "tail": tail_figures(evaluation),
            "audit": audit_figures(sample),
            "inputs": dict(inputs)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_snapshot(a) -> int:
    ev_path, sample_path = Path(a.evaluation), Path(a.sample)
    evaluation = json.loads(ev_path.read_text(encoding="utf-8"))
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    domain = load_domain()
    view = open_ledger(Path(a.ledger_dir) if a.ledger_dir else None, domain=domain).view(as_of=a.as_of)
    conn = store.connect(Path(a.db) if a.db else None, wal=False)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    try:
        snap = build_snapshot(label=a.label, as_of=a.as_of, view=view, conn=conn,
                              jurisdictions=domain.jurisdictions, evaluation=evaluation, sample=sample,
                              git_revision=rev,
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
    a = ap.parse_args(argv)
    return {"snapshot": cmd_snapshot}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
