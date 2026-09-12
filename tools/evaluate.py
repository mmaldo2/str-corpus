"""Publish the Stage 4 evaluation (tools/evaluate.py). This task: --build-bands.

--build-bands derives runs/evaluation/shard-02-bands.json from the gitignored batches and
the map manifest so measure 5 can be recomputed from tracked data."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from export_review_cards import write_text                     # noqa: E402
from corpus_engine.domain import load_domain                   # noqa: E402
from corpus_engine.ledger import open_ledger                   # noqa: E402
from corpus_engine.evaluation import contract, render, summary  # noqa: E402
from corpus_engine.evaluation.gold import gold_recovery, READ_FAILED  # noqa: E402
from corpus_engine.evaluation.precision import precision_and_accuracy  # noqa: E402
from corpus_engine.evaluation.agreement import agreement       # noqa: E402
from corpus_engine.evaluation.coverage import tail_coverage    # noqa: E402
import apply_map_review as ap                                  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bands(manifest: Mapping, batches: Sequence[Mapping], *, manifest_sha: str,
                batch_shas: Mapping[str, str]) -> dict:
    read: dict[str, dict] = {}
    for cell in (manifest.get("cells") or {}).values():
        for u in cell.get("units") or ():
            if u.get("status") == "ok" and not u.get("failed"):
                read[u["unit_id"]] = u
    rows = []
    for b in batches:
        cases = b.get("cases") or []
        score = round(sum(float(c.get("rank_score") or 0) for c in cases) / len(cases), 6) if cases else 0.0
        u = read.get(b["batch_id"])
        rows.append({"batch_id": b["batch_id"], "cell": f"{b['era_partition']}|{b['jurisdiction']}",
                     "score": score, "cases": len(cases), "read": u is not None,
                     "relevant": int(u["relevant_accepted"]) if u else None,
                     "sha256": batch_shas.get(b["batch_id"])})
    rows.sort(key=lambda r: r["batch_id"])
    return {"run_id": manifest.get("run_id"), "map_manifest_sha256": manifest_sha, "batches": rows}


def cmd_build_bands(a) -> int:
    run = ROOT / "runs" / a.run_id
    mpath = run / "map-manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    paths = sorted((run / "batches").glob("batch-*.json"))
    batches = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    shas = {b["batch_id"]: sha256_file(p) for b, p in zip(batches, paths)}
    table = build_bands(manifest, batches, manifest_sha=sha256_file(mpath), batch_shas=shas)
    out = Path(a.out)
    write_text(out, json.dumps(table, indent=1))
    print(f"{len(table['batches'])} batches ({sum(1 for r in table['batches'] if r['read'])} read) -> {out.as_posix()}")
    return 0


def load_registry_files(registry: dict, root: Path) -> dict:
    files = {}
    fields = tuple(load_domain().judged_fields) + ap.EXTRA_FIELDS
    for e in registry.get("rounds") or ():
        for key in ("queue", "checker", "claude", "astra", "user"):
            p = e.get(key)
            if not p or p in files:
                continue
            path = root / p
            if not path.exists():
                raise SystemExit(f"registry names {p} for round {e['round_id']} but it does not exist")
            if p.endswith(".html"):
                files[p] = ap.read_page(path.read_text(encoding="utf-8"), fields)
            else:
                files[p] = json.loads(path.read_text(encoding="utf-8"))
    return files


def read_units(root: Path, view) -> dict[int, str]:
    out: dict[int, str] = {}
    for mpath in sorted((root / "runs").glob("*/map-manifest.json")):
        m = json.loads(mpath.read_text(encoding="utf-8")); run = m.get("run_id") or mpath.parent.name
        bdir = mpath.parent / "batches"
        cases_of = {}
        if bdir.exists():
            for b in bdir.glob("batch-*.json"):
                d = json.loads(b.read_text(encoding="utf-8")); cases_of[d["batch_id"]] = [int(c["case_id"]) for c in d.get("cases") or ()]
        for cell in (m.get("cells") or {}).values():
            for u in cell.get("units") or ():
                for cid in cases_of.get(u["unit_id"], ()):
                    ok = u.get("status") == "ok" and not u.get("failed")
                    if cid not in out or out[cid] == READ_FAILED and ok:
                        out[cid] = run if ok else READ_FAILED
    for p in view.patches:                                  # fallback: a record the ledger carries was read by its admit run
        if p.op == "admit" and p.case_id not in out:
            out[p.case_id] = p.basis.run_id or "unknown-run"
    return out


def compute(a) -> dict:
    dom = load_domain(); led = open_ledger(domain=dom); view = led.view()
    reporting_seq = led.log.head(); content = summary.ledger_content_sha256(led.dir)
    gold_rows = [json.loads(l) for l in (ROOT / "data" / "gold" / "gold.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [int(g["case_id"]) for g in gold_rows if g.get("case_id")]
    if a.no_store:
        signaled = {cid: True for cid in ids}
    else:
        from corpus_engine import store
        from corpus_engine.selector.engine import attribution
        signaled = {cid: bool(refs) for cid, refs in attribution(store.connect(), ids).items()}
    gold = gold_recovery(gold_rows, view, signaled=signaled, read_units=read_units(ROOT, view))
    audit = Path(a.audit)
    manifest = json.loads((audit / "sample-manifest.json").read_text(encoding="utf-8")) if (audit / "sample-manifest.json").exists() else None
    outcomes = json.loads((audit / "outcomes.json").read_text(encoding="utf-8")) if (audit / "outcomes.json").exists() else None
    prec = precision_and_accuracy(manifest, outcomes) if manifest else precision_and_accuracy(
        {"ledger_head_seq": 0, "frame_size": 0, "seed": None, "records": []}, None)
    registry = json.loads(Path(a.rounds).read_text(encoding="utf-8"))
    files = load_registry_files(registry, ROOT)
    ledger_run_ids = sorted({p.basis.run_id for p in view.patches if p.basis.reviewer and p.basis.run_id})
    agr = agreement(registry, files, ledger_run_ids=ledger_run_ids)
    if agr.unregistered_run_ids:
        raise SystemExit(f"unregistered reviewer run ids: {', '.join(agr.unregistered_run_ids)}; add a disposition to {a.rounds}")
    cov = tail_coverage(json.loads(Path(a.bands).read_text(encoding="utf-8")))
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    code = {"git_revision": rev, "command": " ".join(sys.argv), "python": platform.python_version(), "packages": {}}
    ev = summary.evaluate(view, summary.Inputs(gold, prec, agr, cov), cycle=a.cycle, reporting_seq=reporting_seq,
                          content_sha256=content, code=code)
    return summary.to_json(ev)


def cmd_publish(a) -> int:
    doc = compute(a)
    problems = contract.validate(doc)
    if problems:
        print("contract violations: " + ", ".join(problems), file=sys.stderr); return 1
    jp, mp = Path(a.out + ".json"), Path(a.out + ".md")
    if jp.exists():
        if not a.force:
            print(f"{jp} exists; pass --force to supersede (the old pair is kept as -revN)", file=sys.stderr); return 1
        n = 1
        while Path(f"{a.out}-rev{n}.json").exists():
            n += 1
        jp.rename(f"{a.out}-rev{n}.json")
        if mp.exists():
            mp.rename(f"{a.out}-rev{n}.md")
    md = render.markdown(doc)
    write_text(jp, json.dumps(doc, indent=1, ensure_ascii=False)); write_text(mp, md)
    print(f"{doc['evaluation_id']} -> {jp.as_posix()}, {mp.as_posix()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap_ = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap_.add_subparsers(dest="cmd", required=True)
    bb = sub.add_parser("build-bands", help="derive the bands table from a run's batches")
    bb.add_argument("--run-id", default="cycle-004-shard-02")
    bb.add_argument("--out", default="runs/evaluation/shard-02-bands.json")
    bb.set_defaults(func=cmd_build_bands)
    pub = sub.add_parser("publish", help="compute the five measures, validate, and write the json+md pair")
    pub.add_argument("--cycle", default="004")
    pub.add_argument("--audit", default="runs/audit-cycle-004")
    pub.add_argument("--rounds", default="runs/evaluation/rounds.json")
    pub.add_argument("--bands", default="runs/evaluation/shard-02-bands.json")
    pub.add_argument("--out", default="reports/evaluation-cycle-004")
    pub.add_argument("--force", action="store_true")
    pub.add_argument("--no-store", action="store_true",
                     help="skip the sqlite attribution; every resolved gold case counts as signaled "
                          "(for tests and machines without the store)")
    pub.set_defaults(func=cmd_publish)
    return ap_


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
