import shutil
from corpus_engine import store
from corpus_engine.domain import load_domain

def test_rankings_table_and_ranking_spec(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); actions = store.migrate(conn)
    assert "created rankings" in actions
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rankings)")]
    assert cols == ["run_id", "ranker_id", "case_id", "score", "ts"]
    assert store.migrate(conn) == []
    dom = load_domain()
    assert dom.ranking.default in {"null", "fusion", "classifier", "reranker"}
    assert dom.ranking.classifier_version == "v1" and dom.ranking.bar_ap_delta == 0.05
    assert dom.ranking.fusion == {"lexical_weight": 0.5, "cosine_weight": 0.5}
    assert dom.ranking.reranker["model"] == "Qwen/Qwen3-Reranker-4B" and dom.ranking.reranker["query"]
    assert dom.ranking.heldout == "data/eval/ranker-heldout-v1.jsonl"
