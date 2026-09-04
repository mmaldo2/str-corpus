import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import rank as rank_cli
from tests.helpers.ranker_fixture import make_ranker_db

def test_rank_repacks_existing_run_without_touching_signals(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    run_dir = tmp_path / "runs" / "r"; (run_dir / "batches").mkdir(parents=True)
    (run_dir / "shard-manifest.json").write_text(json.dumps({"run_id": "r", "engine_version": "v2"}), encoding="utf-8")
    before = conn.execute("SELECT count(*) FROM signals").fetchone()[0]
    rep = rank_cli.rerank(conn, "r", ranker_id="null", runs_dir=tmp_path / "runs", ledger_dir=tmp_path / "ledger", log=lambda *_: None)
    assert rep["batches"] > 0 and (run_dir / "batches" / "batch-001.json").exists()
    m = json.loads((run_dir / "shard-manifest.json").read_text(encoding="utf-8"))
    assert m["ranker"]["ranker_id"] == "null" and m["engine_version"] == "v2"
    assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == before
