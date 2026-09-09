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


def test_rerank_from_a_source_run_packs_only_its_unread_cases(tmp_path, fixture_db, repo_root):
    """The tail: the source run's pool minus what has been read. The manifest records the
    source, the ranker and the ids left out, so the shard is re-derivable from that file."""
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    runs = tmp_path / "runs"
    src = runs / "cycle-004-shard-01" / "batches"; src.mkdir(parents=True)
    all_ids = sorted({r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals")})
    pool, read = all_ids[:24], all_ids[:6]
    (src / "batch-001.json").write_text(json.dumps(
        {"batch_id": "cycle-004-shard-01-batch-001", "ranker_id": "classifier:v1",
         "era_partition": "1900-1930", "jurisdiction": "N.Y.",
         "cases": [{"case_id": c, "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                    "rank_score": 0.5, "signals": []} for c in pool]}), encoding="utf-8")
    ext = runs / "cycle-004-shard-01" / "extractions"; ext.mkdir(parents=True)
    (ext / "b.json").write_text(json.dumps([{"case_id": c} for c in read]), encoding="utf-8")
    dst = runs / "cycle-004-shard-02"; (dst / "batches").mkdir(parents=True)
    rep = rank_cli.rerank(conn, "cycle-004-shard-02", ranker_id="null", runs_dir=runs,
                          ledger_dir=tmp_path / "ledger", from_run="cycle-004-shard-01",
                          log=lambda *_: None)
    packed = {c["case_id"] for f in (dst / "batches").glob("batch-*.json")
              for c in json.loads(f.read_text(encoding="utf-8"))["cases"]}
    assert packed == set(pool) - set(read) and rep["cases"] == len(packed)
    m = json.loads((dst / "shard-manifest.json").read_text(encoding="utf-8"))
    assert m["source"] == {"run_id": "cycle-004-shard-01", "pool_cases": len(pool),
                           "excluded_read": len(read), "excluded_case_ids": sorted(read),
                           "packed_cases": len(packed)}
    assert m["ranker"]["ranker_id"] == "null"


def test_rerank_packs_batches_in_descending_score_order(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    runs = tmp_path / "runs"; (runs / "r3" / "batches").mkdir(parents=True)
    rank_cli.rerank(conn, "r3", ranker_id="fusion", runs_dir=runs,
                    ledger_dir=tmp_path / "ledger", log=lambda *_: None)
    means = []
    for f in sorted((runs / "r3" / "batches").glob("batch-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        means.append(sum(c["rank_score"] for c in b["cases"]) / len(b["cases"]))
        assert all(c["era_partition"] == b["era_partition"] for c in b["cases"])
        assert all(c["jurisdiction"] == b["jurisdiction"] for c in b["cases"])
    assert means == sorted(means, reverse=True)


def test_the_parser_carries_the_tail_flags():
    a = rank_cli.build_parser().parse_args(["--run-id", "cycle-004-shard-02",
                                            "--from-run", "cycle-004-shard-01",
                                            "--exclude-read"])
    assert a.from_run == "cycle-004-shard-01" and a.exclude_read is True
    assert rank_cli.build_parser().parse_args(["--run-id", "x"]).exclude_read is True
    assert rank_cli.build_parser().parse_args(["--run-id", "x",
                                               "--include-read"]).exclude_read is False
