import hashlib, json, sqlite3, tempfile
from pathlib import Path
import pytest
from corpus_engine.verification import verify_record

def _replay(conn, repo_root, run, batch_names):
    # Hash the bytes verify_quotes.py's own write_text(..., encoding="utf-8") would
    # produce, not an in-memory json.dumps() string: on Windows, write_text with no
    # newline= applies universal-newline translation (\n -> \r\n), and that is what
    # tools/capture_goldens.py hashed from the real runs/*/verified/*.json files. A
    # bare json.dumps(...).encode("utf-8") is LF-only and would never match those
    # goldens on this platform, for every file, regardless of verify_record's output.
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for name in batch_names:
            recs = json.loads((repo_root / "runs" / run / "extractions" / name).read_text(encoding="utf-8"))
            verified = [verify_record(conn, dict(r)) for r in recs]
            p = Path(td) / name
            p.write_text(json.dumps(verified, indent=1), encoding="utf-8")
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def test_verified_files_reproduce_on_fixture_subset(fixture_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    run = "cycle-003-shard-01"
    names = [f"batch-{n:03d}.json" for n in range(1, 6)]
    got = _replay(sqlite3.connect(fixture_db), repo_root, run, names)
    assert got == {n: digests[f"{run}/{n}"] for n in names}

@pytest.mark.live_db
def test_verified_files_reproduce_for_all_cycle_003(live_db, repo_root, golden_dir):
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["verified"]
    conn = sqlite3.connect(live_db)
    for run in ("cycle-003-shard-01", "cycle-003-remap"):
        names = sorted(p.name for p in (repo_root / "runs" / run / "extractions").glob("*.json"))
        got = _replay(conn, repo_root, run, names)
        assert got == {n: digests[f"{run}/{n}"] for n in names}, run
