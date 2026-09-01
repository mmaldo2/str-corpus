import hashlib, json, re, sqlite3
from corpus_engine.selector.packing import pack_batches

def _gold_ids(repo_root):
    ids = set()
    for line in (repo_root / "data/gold/gold.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("case_id"):
            ids.add(json.loads(line)["case_id"])
    return ids

def test_pack_batches_reproduces_cycle_003_byte_for_byte(repo_root, golden_dir, tmp_path):
    params = json.loads((golden_dir / "cycle-003-batches.json").read_text(encoding="utf-8"))
    digests = json.loads((golden_dir / "digests.json").read_text(encoding="utf-8"))["batches"]
    # Two manual post-sharding split files (batch-139-part1.json, batch-139-part2.json)
    # live in this run's batches dir but were never produced by the packer — exclude
    # anything that doesn't match the canonical batch-NNN.json pattern.
    want = {
        k.split("/")[1]: v
        for k, v in digests.items()
        if k.startswith(params["run_id"] + "/")
        and re.fullmatch(r"batch-\d{3}\.json", k.split("/")[1])
    }
    conn = sqlite3.connect(repo_root / "tests/fixtures/cycle-003-signals.db")
    exclude = set(json.loads((repo_root / "tests/fixtures/cycle-003-already-read.json").read_text())) if params["exclude_mapped"] else set()
    n = pack_batches(conn, params["run_id"], tmp_path, gold_ids=_gold_ids(repo_root),
                     exclude_ids=exclude, batch_size=params["batch_size"])
    assert n == params["n_batches"] == len(want)
    got = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in tmp_path.glob("batch-*.json")}
    assert got == want
