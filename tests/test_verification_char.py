import hashlib, json, sqlite3
import pytest
from corpus_engine.verification import verify_record

def _replay(conn, repo_root, run, batch_names):
    out = {}
    for name in batch_names:
        recs = json.loads((repo_root / "runs" / run / "extractions" / name).read_text(encoding="utf-8"))
        verified = [verify_record(conn, dict(r)) for r in recs]
        out[name] = hashlib.sha256(json.dumps(verified, indent=1).encode("utf-8")).hexdigest()
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
