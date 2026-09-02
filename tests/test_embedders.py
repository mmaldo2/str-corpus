import json, numpy as np, pytest
from corpus_engine.indexer.embedders import FakeEmbedder, HostedEmbedder, EmbedError

def test_fake_embedder_is_deterministic_and_dim_correct():
    e = FakeEmbedder(dim=16)
    a = e.encode(["lodger", "boarder"]); b = e.encode(["lodger"])
    assert a.shape == (2, 16) and a.dtype == np.float32 and np.allclose(a[0], b[0]) and not np.allclose(a[0], a[1])

class _Resp:
    def __init__(self, status, payload): self.status_code = status; self._p = payload; self.text = json.dumps(payload)
    def json(self): return self._p

def test_hosted_embedder_truncates_retries_and_counts_tokens(monkeypatch):
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json["input"])
        if len(calls) == 1:
            return _Resp(429, {"error": "slow down"})
        return _Resp(200, {"data": [{"embedding": [0.5] * 2560} for _ in json["input"]], "usage": {"total_tokens": 7}})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    monkeypatch.setattr("corpus_engine.indexer.embedders.time.sleep", lambda s: None)
    e = HostedEmbedder("openrouter", "qwen/qwen3-embedding-4b", 1024, api_key="k", batch=2, concurrency=1)
    v = e.encode(["a", "b", "c"])
    assert v.shape == (3, 1024) and e.tokens_used == 14 and len(calls) == 3

def test_hosted_embedder_gives_up_after_four_failures(monkeypatch):
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", lambda *a, **k: _Resp(500, {"error": "x"}))
    monkeypatch.setattr("corpus_engine.indexer.embedders.time.sleep", lambda s: None)
    with pytest.raises(EmbedError):
        HostedEmbedder("deepinfra", "m", 8, api_key="k").encode(["a"])
