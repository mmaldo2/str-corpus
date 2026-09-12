"""Publish the Stage 4 evaluation (tools/evaluate.py). This task: --build-bands.

--build-bands derives runs/evaluation/shard-02-bands.json from the gitignored batches and
the map manifest so measure 5 can be recomputed from tracked data."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from export_review_cards import write_text                     # noqa: E402


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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    bb = sub.add_parser("build-bands", help="derive the bands table from a run's batches")
    bb.add_argument("--run-id", default="cycle-004-shard-02")
    bb.add_argument("--out", default="runs/evaluation/shard-02-bands.json")
    bb.set_defaults(func=cmd_build_bands)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
