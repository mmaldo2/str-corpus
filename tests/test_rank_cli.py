import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import rank as rank_cli
from corpus_engine.ranker.labels import Label, write_heldout
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


def test_rerank_flags_pool_jurisdictions_missing_from_the_heldout_slice(tmp_path, fixture_db, repo_root):
    # I-1: the fixture pool spans {La., N.Y., Pa., Tex.} - freeze a synthetic held-out
    # file that only covers two of them, and assert the manifest names the other two.
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    run_dir = tmp_path / "runs" / "r2"; (run_dir / "batches").mkdir(parents=True)
    (run_dir / "shard-manifest.json").write_text(json.dumps({"run_id": "r2"}), encoding="utf-8")
    heldout = tmp_path / "heldout-fixture.jsonl"
    write_heldout(heldout, [Label(1, 1, 1.0, True, "1900-1930", "N.Y."),
                           Label(2, 0, 1.0, False, "1900-1930", "Pa.")])
    warnings = []
    rep = rank_cli.rerank(conn, "r2", ranker_id="null", runs_dir=tmp_path / "runs", ledger_dir=tmp_path / "ledger",
                          log=warnings.append, heldout_path=heldout)
    m = json.loads((run_dir / "shard-manifest.json").read_text(encoding="utf-8"))
    assert m["ranker"]["heldout_uncovered_jurisdictions"] == ["La.", "Tex."]
    assert any("La." in w and "Tex." in w for w in warnings)
