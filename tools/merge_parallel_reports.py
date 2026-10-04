"""Merge parallel reports - one decision printed in two reporters (spec 2026-10-04 section 6).

  .venv/Scripts/python tools/merge_parallel_reports.py score                  # candidates.jsonl
  .venv/Scripts/python tools/merge_parallel_reports.py sample --per-band 25   # blind reader parts
  .venv/Scripts/python tools/merge_parallel_reports.py threshold              # calibration.json
  .venv/Scripts/python tools/merge_parallel_reports.py apply --dry-run        # counts only
  .venv/Scripts/python tools/merge_parallel_reports.py apply                  # corpus marks + merges.jsonl
  .venv/Scripts/python tools/merge_parallel_reports.py undo --method <method>
  .venv/Scripts/python tools/merge_parallel_reports.py reconcile --dry-run    # ledger counts before/after
  .venv/Scripts/python tools/merge_parallel_reports.py reconcile

Files live in --out-dir (default runs/parallel-reports). `score` and `sample` read the corpus
read-only; `apply` and `undo` write `cases.is_duplicate_of` and the `parallel_reports` table;
`reconcile` writes ledger patches. The user says go before `apply` and before `reconcile`."""
from __future__ import annotations
import argparse
import collections
import copy
import json
import random
import sqlite3
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import store                                      # noqa: E402
from corpus_engine.domain import load_domain                         # noqa: E402
from corpus_engine.ingest import parallel as par                     # noqa: E402
from corpus_engine.ledger import open_ledger                         # noqa: E402
from corpus_engine.ledger.duplicates import precedence, reconcile    # noqa: E402
from corpus_engine.ledger.fold import apply_patch                    # noqa: E402
from corpus_engine.ledger.ledger import LedgerView                   # noqa: E402
from corpus_engine.ledger.log import provisional_seqs                # noqa: E402

BOUNDS = tuple(round(0.20 + 0.05 * i, 2) for i in range(16))         # 0.20, 0.25 ... 0.95
SAMPLE_BANDS = tuple(round(0.2 + 0.1 * i, 1) for i in range(8))      # [0.2, 0.3) ... [0.9, 1.0]
MEASURES = ("c5", "c3")                                              # c5 first: it wins a tie
HEAD_CHARS, TAIL_CHARS = 2000, 1500
RUN_ID = "parallel-report-merge-2026-10"
LABELS = ("same", "different", "unsure")


def _ro(db) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write_text(path: Path, text: str) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def choose_threshold(labelled, *, measures=MEASURES, bounds=BOUNDS) -> dict | None:
    """Per measure, the lowest bound strictly above every pair not labelled `same` (`unsure`
    counts as not same); the measure kept is the one that merges more labelled-same pairs, c5
    on a tie. None when no bound clears every not-same pair."""
    best = None
    for m in measures:
        worst = max((r[m] for r in labelled if r["label"] != "same"), default=-1.0)
        t = next((b for b in bounds if b > worst), None)
        if t is None:
            continue
        merged = sum(1 for r in labelled if r["label"] == "same" and r[m] >= t)
        if best is None or merged > best["merged_same"]:
            best = {"measure": m, "threshold": t, "merged_same": merged,
                    "labelled_same": sum(1 for r in labelled if r["label"] == "same"),
                    "labelled_not_same": sum(1 for r in labelled if r["label"] != "same")}
    if best:
        best["method"] = f"parallel-v1:w{best['measure'][1]}:{best['threshold']}"
    return best


def calibration_sample(rows, *, per_band: int, seed: int, measure: str = "c5") -> list[dict]:
    rng = random.Random(seed)
    ok = [r for r in rows if par.passes_guards(r)]
    out = []
    for lo in SAMPLE_BANDS:
        hi = round(lo + 0.1, 1)
        band = [r for r in ok if lo <= r[measure] and (r[measure] < hi or hi >= 1.0)]
        out += rng.sample(band, min(per_band, len(band)))
    return out


def _excerpt(text: str) -> str:
    text = text or ""
    if len(text) > HEAD_CHARS + TAIL_CHARS:
        text = text[:HEAD_CHARS] + "\n[...]\n" + text[-TAIL_CHARS:]
    return "\n".join(textwrap.fill(p, 160) if p.strip() else "" for p in text.split("\n"))


def cmd_score(a) -> int:
    view = open_ledger(Path(a.ledger), domain=load_domain()).view()
    key = precedence(view, view.reviewed_ids())
    conn = _ro(a.db)
    groups = par.candidate_groups(conn)
    out = Path(a.out_dir) / "candidates.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for i, g in enumerate(groups, 1):
            for row in par.score_group(conn, g, par.pick_winner(g.members, key)):
                f.write(json.dumps(row, sort_keys=True) + "\n")
                n += 1
            if i % 5000 == 0:
                print(f"{i}/{len(groups)} groups, {n} pairs", flush=True)
    print(f"{len(groups)} groups, {n} pairs -> {out}")
    return 0


def cmd_sample(a) -> int:
    out = Path(a.out_dir)
    picked = calibration_sample(_jsonl(out / "candidates.jsonl"), per_band=a.per_band, seed=a.seed)
    random.Random(a.seed).shuffle(picked)          # every reader gets every band
    for i, r in enumerate(picked):
        r["pair_id"] = i
    _write_text(out / "calibration-sample.json", json.dumps(picked, indent=1) + "\n")
    conn = _ro(a.db)
    size = -(-len(picked) // a.parts) if picked else 0
    for k in range(a.parts):
        lines = [f"# Calibration pairs, part {k + 1}", ""]
        for r in picked[k * size:(k + 1) * size]:
            texts = dict(conn.execute("SELECT case_id, norm_text FROM cases WHERE case_id IN (?, ?)",
                                      (r["winner"], r["loser"])))
            lines += [f"## pair {r['pair_id']}", f"{r['court']}, {r['year']}: {r['name']}", "",
                      f"### A ({r['winner_cite']})", _excerpt(texts.get(r["winner"], "")), "",
                      f"### B ({r['loser_cite']})", _excerpt(texts.get(r["loser"], "")), ""]
        _write_text(out / f"calibration-pairs-part{k + 1}.md", "\n".join(lines))
    print(f"{len(picked)} pairs in {a.parts} parts -> {out}")
    return 0


def cmd_threshold(a) -> int:
    out = Path(a.out_dir)
    sample = {r["pair_id"]: r for r in
              json.loads((out / "calibration-sample.json").read_text(encoding="utf-8"))}
    labels = {}
    for p in sorted(out.glob("calibration-labels-part*.json")):
        for r in json.loads(p.read_text(encoding="utf-8")):
            labels[r["pair_id"]] = (r.get("label"), r.get("note", ""))
    missing = [i for i in sorted(sample) if labels.get(i, (None,))[0] not in LABELS]
    if missing:
        sys.exit(f"{len(missing)} pairs carry no label ({'/'.join(LABELS)}): {missing[:10]}")
    labelled = [dict(sample[i], label=labels[i][0], note=labels[i][1]) for i in sorted(sample)]
    choice = choose_threshold(labelled)
    bands = collections.Counter((f"{min(int(r['c5'] * 10), 9) / 10:.1f}", r["label"]) for r in labelled)
    for b in SAMPLE_BANDS:
        print(f"c5 {b:.1f}: " + ", ".join(f"{lab} {bands[(f'{b:.1f}', lab)]}" for lab in LABELS))
    print(f"choice: {choice}")
    _write_text(out / "calibration.json", json.dumps(
        {"bounds": BOUNDS, "choice": choice, "labels": labelled}, indent=1) + "\n")
    return 0


def _choice(out: Path) -> dict:
    cal = json.loads((out / "calibration.json").read_text(encoding="utf-8"))
    if not cal.get("choice"):
        sys.exit("calibration.json holds no threshold: no bound clears every not-same pair")
    return cal["choice"]


def _write_merges(conn, out: Path) -> None:
    """merges.jsonl mirrors every row of `parallel_reports` (all methods), so it never goes stale."""
    with (out / "merges.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for loser, winner, score, method in conn.execute(
                "SELECT loser, winner, score, method FROM parallel_reports ORDER BY loser"):
            f.write(json.dumps({"loser": loser, "winner": winner, "score": score,
                                "method": method}) + "\n")


def cmd_apply(a) -> int:
    out = Path(a.out_dir)
    ch = _choice(out)
    m, t = ch["measure"], ch["threshold"]
    # only pairs inside the sampled region (c5 >= the lowest calibration band) can merge
    rows = [r for r in _jsonl(out / "candidates.jsonl")
            if par.passes_guards(r) and r[m] >= t and r["c5"] >= SAMPLE_BANDS[0]]
    print(f"{len(rows)} merges at {m} >= {t} ({ch['method']})")
    for label in ("jurisdiction", "era"):
        c = collections.Counter(r[label] for r in rows)
        print(f"  by {label}: " + ", ".join(f"{v} {n}" for v, n in c.most_common()))
    if a.dry_run:
        return 0
    conn = store.connect(Path(a.db))
    res = par.apply_merges(conn, [(r["winner"], r["loser"], r[m]) for r in rows],
                           method=ch["method"], run_id=a.run_id,
                           ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
                           log=lambda s: print(s, flush=True))
    print(f"applied {res['applied']}, already merged {res['already']}, stale {res['stale']}, "
          f"skipped (other cases point at the loser) {res['target']}")
    _write_merges(conn, out)
    return 0


def cmd_undo(a) -> int:
    conn = store.connect(Path(a.db))
    n = par.undo_merges(conn, a.method)
    _write_merges(conn, Path(a.out_dir))
    print(f"undid {n} merges of {a.method}; ledger duplicate_of patches, if any, still stand")
    return 0


def cmd_reconcile(a) -> int:
    dom = load_domain()
    led = open_ledger(Path(a.ledger), domain=dom)
    view = led.view()
    judged = tuple(dom.judged_fields)
    res = reconcile(view, par.winner_map(_ro(a.db)), run_id=a.run_id, judged=judged)
    trial = copy.deepcopy(view.state)
    for p in provisional_seqs(res.patches, view.as_of):
        apply_patch(trial, p, judged=judged, cascade=p.cascade)
    after = LedgerView(view.name, view.as_of + len(res.patches), trial, view.patches, view.domain)
    for label, flt in (("relevant", {}), ("favorable", {"polarity": "favorable"}),
                       ("favorable householder", {"polarity": "favorable",
                                                  "who_was_letting": "householder"})):
        b, c = view.counts(**flt).total, after.counts(**flt).total
        print(f"{label}: {b.human_reviewed}+{b.machine_only} -> {c.human_reviewed}+{c.machine_only}")
    Path(a.user_list).parent.mkdir(parents=True, exist_ok=True)
    _write_text(Path(a.user_list), json.dumps(res.for_user, indent=1) + "\n")
    print(f"{len(res.patches)} duplicate_of patches; {len(res.for_user)} groups for the user "
          f"-> {a.user_list}")
    if a.dry_run:
        return 0
    trial_run = led.apply(res.patches, note="parallel-report merge: one decision, counted once",
                          dry_run=True)
    if trial_run.rejected:
        sys.exit(f"reconcile: the ledger would refuse {len(trial_run.rejected)} writes; nothing "
                 f"applied: {trial_run.rejected}")
    r = led.apply(res.patches, note="parallel-report merge: one decision, counted once")
    if r.rejected or not r.replay_ok:
        sys.exit(f"apply refused {len(r.rejected)} writes or the replay failed "
                 f"(replay_ok={r.replay_ok})")
    print(f"{len(r.applied)} applied, {len(r.skipped)} already present; replay_ok={r.replay_ok}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "db" / "corpus.db"))
    ap.add_argument("--ledger", default=str(ROOT / "data" / "ledger"))
    ap.add_argument("--out-dir", default=str(ROOT / "runs" / "parallel-reports"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("score")
    s = sub.add_parser("sample")
    s.add_argument("--per-band", type=int, default=25)
    s.add_argument("--seed", type=int, default=20261004)
    s.add_argument("--parts", type=int, default=4)
    sub.add_parser("threshold")
    p = sub.add_parser("apply")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--run-id", default=RUN_ID)
    u = sub.add_parser("undo")
    u.add_argument("--method", required=True)
    r = sub.add_parser("reconcile")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--run-id", default=RUN_ID)
    r.add_argument("--user-list")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "reconcile" and not a.user_list:
        a.user_list = str(Path(a.out_dir) / "reconcile-for-user.json")
    return {"score": cmd_score, "sample": cmd_sample, "threshold": cmd_threshold,
            "apply": cmd_apply, "undo": cmd_undo, "reconcile": cmd_reconcile}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
