# tools/capture_goldens.py
"""One-time golden capture at the pre-refactor commit. Run once:
    .venv\\Scripts\\python tools\\capture_goldens.py
Idempotent: re-running overwrites the same files with the same bytes.

Digests are computed over CRLF->LF-normalized bytes (git's stored, canonical
form) so they are stable regardless of the checkout platform's line-ending
translation (core.autocrlf). Any test hashing a file to compare against
digests.json must normalize the same way before hashing.

Use --digests-only to regenerate just tests/golden/digests.json (skips
prompts, the signals fixture, the already-read set, and the batch
reproduction check).
"""
import argparse, hashlib, json, shutil, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import run_map, shard  # noqa: E402  (old code, on purpose)

GOLDEN = ROOT / "tests" / "golden"
FIX = ROOT / "tests" / "fixtures"
RUN = "cycle-003-shard-01"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def digests() -> dict:
    out = {"ledger": {}, "adjudications": {}, "verified": {}, "batches": {}}
    for f in sorted((ROOT / "data" / "ledger").glob("cycle-*.jsonl")):
        out["ledger"][f.name] = sha(f)
    for f in sorted((ROOT / "data" / "adjudications").glob("cycle-*.json")):
        out["adjudications"][f.name] = sha(f)
    for run in sorted((ROOT / "runs").glob("cycle-*")):
        for f in sorted((run / "verified").glob("*.json")):
            out["verified"][f"{run.name}/{f.name}"] = sha(f)
        for f in sorted((run / "batches").glob("*.json")):
            out["batches"][f"{run.name}/{f.name}"] = sha(f)
    return out


def prompts(conn) -> None:
    d = GOLDEN / "prompts" / RUN
    d.mkdir(parents=True, exist_ok=True)
    for bf in sorted((ROOT / "runs" / RUN / "batches").glob("batch-*.json"))[:10]:
        batch = json.loads(bf.read_text(encoding="utf-8"))
        text = run_map.build_payload(conn, batch, "claude")
        (d / (bf.stem + ".txt")).write_text(text, encoding="utf-8", newline="\n")


def already_read_at_cycle_003() -> list[int]:
    """What shard.already_mapped_ids() returned when cycle 003 was sharded:
    every extraction in runs/ that existed before cycle-003-shard-01."""
    ids: set[int] = set()
    for f in (ROOT / "runs").glob("*/extractions*/*.json"):
        if f.parts[-3].startswith("cycle-003"):
            continue
        try:
            for r in json.loads(f.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("case_id"):
                    ids.add(r["case_id"])
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(ids)


def signals_fixture(conn) -> Path:
    FIX.mkdir(parents=True, exist_ok=True)
    dst = FIX / "cycle-003-signals.db"
    if dst.exists():
        dst.unlink()
    out = sqlite3.connect(dst)
    out.executescript(shard.SCHEMA)
    out.execute("""CREATE TABLE cases_meta (case_id INTEGER PRIMARY KEY, era_partition TEXT,
                   jurisdiction TEXT, decision_year INTEGER, is_duplicate_of INTEGER)""")
    cols = "case_id, selector_id, selector_version, matched_text, char_span_start, char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts"
    for row in conn.execute(f"SELECT signal_id, {cols} FROM signals ORDER BY signal_id"):
        out.execute(f"INSERT INTO signals (signal_id, {cols}) VALUES ({','.join('?' * 13)})", row)
    for row in conn.execute("SELECT selector_id, selector_version, era_partition, jurisdiction, run_id, ts, n_signals FROM coverage"):
        out.execute("INSERT INTO coverage VALUES (?,?,?,?,?,?,?)", row)
    ids = [r[0] for r in out.execute("SELECT DISTINCT case_id FROM signals")]
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        q = f"SELECT case_id, era_partition, jurisdiction, decision_year, is_duplicate_of FROM cases WHERE case_id IN ({','.join('?' * len(chunk))})"
        out.executemany("INSERT INTO cases_meta VALUES (?,?,?,?,?)", conn.execute(q, chunk).fetchall())
    out.commit(); out.close()
    return dst


def verify_batches_reproduce(fixture: Path, already: list[int]) -> dict:
    """Prove the fixture reproduces runs/cycle-003-shard-01/batches with the OLD code.

    Compares only the canonical batch-NNN.json files emit_batches can produce.
    runs/cycle-003-shard-01/batches/ also holds batch-139-part1.json and
    batch-139-part2.json, hand-derived post-sharding splits of batch-139.json
    (9+9 of the same 18 cases) made for mapping convenience — emit_batches
    never writes files in that shape, so they're outside what this check can
    or should reproduce. See tests/golden/README.md "Known non-reproductions".
    """
    CANONICAL = "batch-[0-9][0-9][0-9].json"
    want_dir = ROOT / "runs" / RUN / "batches"
    want = {f.name: sha(f) for f in sorted(want_dir.glob(CANONICAL))}
    for exclude in (True, False):
        tmp = Path(tempfile.mkdtemp(prefix="char-"))
        shard.RUNS = tmp                      # emit_batches writes under RUNS/<run_id>/batches
        shard.already_mapped_ids = lambda: set(already) if exclude else set()
        conn = sqlite3.connect(fixture)
        n = shard.emit_batches(conn, RUN, exclude_mapped=exclude)
        got = {f.name: sha(f) for f in sorted((tmp / RUN / "batches").glob(CANONICAL))}
        shutil.rmtree(tmp, ignore_errors=True)
        if got == want:
            return {"run_id": RUN, "exclude_mapped": exclude, "n_batches": n, "batch_size": shard.BATCH_SIZE}
    raise SystemExit("fixture does not reproduce cycle-003 batches under either exclusion mode; investigate before proceeding")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digests-only", action="store_true",
                     help="regenerate only tests/golden/digests.json; skip prompts, "
                          "the signals fixture, the already-read set, and the "
                          "reproduction check")
    args = ap.parse_args()
    GOLDEN.mkdir(parents=True, exist_ok=True)
    (GOLDEN / "digests.json").write_text(json.dumps(digests(), indent=1, sort_keys=True), encoding="utf-8")
    if args.digests_only:
        return 0
    conn = sqlite3.connect(ROOT / "data" / "db" / "corpus.db")
    conn.execute("PRAGMA busy_timeout=120000")
    prompts(conn)
    already = already_read_at_cycle_003()
    (FIX / "cycle-003-already-read.json").write_text(json.dumps(already), encoding="utf-8")
    fixture = signals_fixture(conn)
    params = verify_batches_reproduce(fixture, already)
    (GOLDEN / "cycle-003-batches.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    print(json.dumps(params))
    return 0


if __name__ == "__main__":
    sys.exit(main())
