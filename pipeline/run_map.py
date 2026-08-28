"""Map-stage driver (spec §8, amendments A6): headless CLI fleet.

For each batch file, materializes a self-contained payload (mapper prompt +
batch provenance + full opinion text per case), invokes a headless `claude`
CLI mapper (Sonnet), validates the returned JSON against the schema's hard
requirements, and writes runs/<run>/extractions/batch-NNN.json. Every 10th
batch is additionally sent to `codex exec` (read-only sandbox) as the
cross-model checker; disagreements on relevant/polarity/characterization go
to runs/<run>/disagreements.jsonl. Codex is checker only — its output is
never the record of relevance.

Per-batch token usage is logged to runs/<run>/map-usage.jsonl (cost-per-case
metric). On CLI failure the driver retries once, then marks the batch failed
and continues; it never degrades model tier.

Usage:
    python pipeline/run_map.py --run-id cycle-001 [--max-batches 40]
        [--parallel 2] [--cross-check-every 10] [--mapper-model sonnet]
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "db" / "corpus.db"
RUNS = ROOT / "runs"
MAPPER_PROMPT = ROOT / "prompts" / "mapper.md"

REQUIRED_FIELDS = {"case_id", "relevant", "polarity", "quotes", "worker", "batch_id"}


def build_payload(conn, batch: dict, worker_name: str) -> str:
    cases_meta = conn.execute(
        f"""SELECT case_id, cite, name_abbreviation, court, jurisdiction,
                   decision_year, raw_text
            FROM cases WHERE case_id IN
            ({",".join(str(c["case_id"]) for c in batch["cases"])})"""
    ).fetchall()
    texts = {r[0]: r for r in cases_meta}
    parts = [MAPPER_PROMPT.read_text(encoding="utf-8")]
    parts.append(
        f"\n\n# Batch {batch['batch_id']} "
        f"({batch['era_partition']} x {batch['jurisdiction']})\n"
        f'Set "worker": "{worker_name}" and "batch_id": "{batch["batch_id"]}" '
        "on every record.\n"
    )
    for c in batch["cases"]:
        r = texts.get(c["case_id"])
        if r is None:
            continue
        sig_lines = "\n".join(
            f"  - {s['selector_id']} v{s['selector_version']}: "
            f"...{s['matched_text'][:160]}..."
            for s in c["signals"]
        )
        parts.append(
            f"\n## case_id {r[0]} — {r[2]}, {r[1]} ({r[3]}, {r[4]} {r[5]})\n"
            f"Retrieval provenance:\n{sig_lines}\n\n"
            f"### Opinion text\n{r[6]}\n"
        )
    return "".join(parts)


def parse_records(raw: str, batch: dict) -> list[dict] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("["):]
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        records = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(records, list):
        return None
    want = {c["case_id"] for c in batch["cases"]}
    got = {r.get("case_id") for r in records if isinstance(r, dict)}
    if not want <= got:
        return None  # §8: every case accounted for
    for r in records:
        if not REQUIRED_FIELDS <= set(r):
            return None
    return records


def call_claude(payload: str, model: str, timeout: int = 900) -> tuple[str, dict]:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        timeout=timeout, shell=(sys.platform == "win32"),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:500]}")
    envelope = json.loads(proc.stdout)
    return envelope.get("result", ""), envelope.get("usage", {})


def call_codex(payload: str, timeout: int = 900) -> str:
    proc = subprocess.run(
        ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        timeout=timeout, shell=(sys.platform == "win32"),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"codex exited {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout


def process_batch(conn_str: str, batch_file: Path, run_dir: Path, model: str,
                  cross_check: bool) -> dict:
    conn = sqlite3.connect(conn_str)
    batch = json.loads(batch_file.read_text(encoding="utf-8"))
    out_file = run_dir / "extractions" / batch_file.name
    if out_file.exists():
        return {"batch": batch["batch_id"], "status": "cached"}
    payload = build_payload(conn, batch, "claude")
    records = None
    usage = {}
    for attempt in range(2):
        try:
            raw, usage = call_claude(payload, model)
            records = parse_records(raw, batch)
            if records:
                break
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            if attempt == 1:
                return {"batch": batch["batch_id"], "status": "failed", "error": str(e)[:300]}
            time.sleep(20)
    if not records:
        return {"batch": batch["batch_id"], "status": "failed", "error": "invalid JSON after retry"}
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(records, indent=1), encoding="utf-8")

    result = {"batch": batch["batch_id"], "status": "ok", "n": len(records),
              "usage": usage}
    if cross_check:
        try:
            codex_raw = call_codex(build_payload(conn, batch, "codex"))
            codex_records = parse_records(codex_raw, batch)
            if codex_records:
                by_id = {r["case_id"]: r for r in codex_records}
                disagreements = []
                for r in records:
                    o = by_id.get(r["case_id"])
                    if not o:
                        continue
                    for f in ("relevant", "polarity", "characterization"):
                        if r.get(f) != o.get(f):
                            disagreements.append(
                                {"case_id": r["case_id"], "field": f,
                                 "claude": r.get(f), "codex": o.get(f),
                                 "batch_id": batch["batch_id"]}
                            )
                with (run_dir / "disagreements.jsonl").open("a", encoding="utf-8") as f:
                    for d in disagreements:
                        f.write(json.dumps(d) + "\n")
                result["cross_check"] = {"cases": len(codex_records),
                                         "disagreements": len(disagreements)}
            else:
                result["cross_check"] = {"error": "codex output unparseable"}
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            result["cross_check"] = {"error": str(e)[:300]}
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--max-batches", type=int, default=40)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--cross-check-every", type=int, default=10)
    ap.add_argument("--mapper-model", default="sonnet")
    args = ap.parse_args()

    run_dir = RUNS / args.run_id
    batch_files = sorted((run_dir / "batches").glob("batch-*.json"))[: args.max_batches]
    print(f"{len(batch_files)} batches (cap {args.max_batches})")
    usage_log = (run_dir / "map-usage.jsonl").open("a", encoding="utf-8")
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(
                process_batch, str(DB), bf, run_dir, args.mapper_model,
                args.cross_check_every > 0 and i % args.cross_check_every == 0,
            ): bf
            for i, bf in enumerate(batch_files)
        }
        for fut in as_completed(futures):
            r = fut.result()
            usage_log.write(json.dumps({**r, "ts": time.strftime("%H:%M:%S")}) + "\n")
            usage_log.flush()
            if r["status"] == "failed":
                failed += 1
            else:
                ok += 1
            print(f"[{ok + failed}/{len(batch_files)}] {r['batch']}: {r['status']}"
                  + (f" ({r.get('n')} records)" if r.get("n") else ""), flush=True)
    print(f"done: {ok} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
