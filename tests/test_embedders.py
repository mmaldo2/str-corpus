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

def test_hosted_embedder_reorders_out_of_order_response(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp(200, {"data": [{"index": 1, "embedding": [0.2] * 4},
                                     {"index": 0, "embedding": [0.1] * 4}], "usage": {}})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    v = HostedEmbedder("openrouter", "m", 4, api_key="k", concurrency=1).encode(["a", "b"])
    assert np.allclose(v[0], 0.1) and np.allclose(v[1], 0.2)

def test_hosted_embedder_raises_on_short_vectors(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp(200, {"data": [{"embedding": [0.5] * 512} for _ in json["input"]], "usage": {}})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    with pytest.raises(EmbedError):
        HostedEmbedder("openrouter", "m", 1024, api_key="k").encode(["a"])

def test_hosted_embedder_raises_on_missing_item(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp(200, {"data": [{"embedding": [0.5] * 4}], "usage": {}})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    with pytest.raises(EmbedError):
        HostedEmbedder("openrouter", "m", 4, api_key="k").encode(["a", "b"])


def test_hosted_embedder_retries_transport_errors_then_gives_up(monkeypatch):
    import httpx
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        return _Resp(200, {"data": [{"embedding": [0.5] * 1024} for _ in json["input"]]})
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", fake_post)
    monkeypatch.setattr("corpus_engine.indexer.embedders.time.sleep", lambda s: None)
    e = HostedEmbedder("openrouter", "qwen/qwen3-embedding-4b", 1024, api_key="k", batch=4, concurrency=1)
    assert e.encode(["a", "b"]).shape == (2, 1024) and len(calls) == 2

    def always_timeout(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectTimeout("connect timed out")
    monkeypatch.setattr("corpus_engine.indexer.embedders.httpx.post", always_timeout)
    with pytest.raises(EmbedError, match="transport error after 4 attempts"):
        e.encode(["a"])
