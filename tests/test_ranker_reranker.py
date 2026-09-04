import pytest
from corpus_engine.ranker.reranker import QwenReranker
from tests.helpers.ranker_fixture import make_ranker_db

class _Fake:
    def __init__(self): self.calls = []
    def predict(self, pairs, batch_size=8):
        self.calls.append((len(pairs), batch_size)); return [len(t) / 1000.0 for _, t in pairs]

def test_reranker_pairs_best_chunk_text_and_scores_by_case(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 12")]
    fake = _Fake(); r = QwenReranker("Qwen/Qwen3-Reranker-4B", "0123456789abcdef", "letting query", batch=4, encoder=fake)
    s = r.score(conn, "run", ids)
    assert set(s) == set(ids) and fake.calls == [(12, 4)] and r.ranker_id == "qwen3-reranker-4b:0123456" and len(r.digest()) == 16
    assert all(v > 0 for v in s.values()) and s == r.score(conn, "run", ids)
    with pytest.raises(ValueError, match="main"):
        QwenReranker("Qwen/Qwen3-Reranker-4B", "main", "q", encoder=fake)


@pytest.mark.parametrize("revision", ["main", "v1.0", ""])
def test_reranker_rejects_non_sha_revisions(revision):
    with pytest.raises(ValueError):
        QwenReranker("Qwen/Qwen3-Reranker-4B", revision, "q", encoder=_Fake())


@pytest.mark.parametrize("revision", ["0123456789abcdef0123456789abcdef01234567", "abc1234"])
def test_reranker_accepts_hex_sha_revisions(revision):
    r = QwenReranker("Qwen/Qwen3-Reranker-4B", revision, "q", encoder=_Fake())
    assert r.revision == revision
