"""The Embedder port and its adapters: local pinned weights, hosted open weights, and a
deterministic fake for tests (ADR-0006)."""
from __future__ import annotations
import hashlib, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol
import httpx
import numpy as np


class EmbedError(RuntimeError): ...


class Embedder(Protocol):
    name: str
    dim: int
    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray: ...


class _WhitespaceTokenizer:
    """Stand-in with the HF fast-tokenizer call shape the chunker needs."""
    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=True, truncation=False, verbose=False):
        return {"offset_mapping": [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]}


class FakeEmbedder:
    def __init__(self, dim: int = 16):
        self.name, self.dim, self.tokenizer = f"fake-{dim}", dim, _WhitespaceTokenizer()
    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            out[i] = np.random.default_rng(seed).standard_normal(self.dim)
        return out


def tokenizer_for(model: str, revision: str):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model, revision=revision)


class LocalEmbedder:
    def __init__(self, model: str, revision: str, dim: int, device: str | None = None):
        import torch
        from sentence_transformers import SentenceTransformer
        dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_obj = SentenceTransformer(model, revision=revision, device=dev,
                                             model_kwargs={"torch_dtype": torch.float16} if dev == "cuda" else {},
                                             tokenizer_kwargs={"padding_side": "left"})
        self.tokenizer, self.name, self.dim = self.model_obj.tokenizer, f"local:{model}@{revision}", dim
    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        v = self.model_obj.encode(texts, batch_size=batch_size, convert_to_numpy=True, normalize_embeddings=False, show_progress_bar=False)
        return v[:, :self.dim].astype(np.float32)
    def encode_query(self, text: str) -> np.ndarray:
        return self.model_obj.encode([text], prompt_name="query", convert_to_numpy=True)[0][:self.dim].astype(np.float32)


BASES = {"openrouter": "https://openrouter.ai/api/v1", "deepinfra": "https://api.deepinfra.com/v1/openai"}


class HostedEmbedder:
    def __init__(self, provider: str, model_id: str, dim: int, api_key: str, *, batch: int = 64,
                 concurrency: int = 4, timeout: int = 120):
        self.base, self.model_id, self.dim, self.key = BASES[provider], model_id, dim, api_key
        self.batch, self.concurrency, self.timeout = batch, concurrency, timeout
        self.name, self.tokens_used = f"hosted:{provider}:{model_id}", 0
        self._tokens_lock = threading.Lock()

    def _one(self, texts: list[str]) -> np.ndarray:
        for attempt, delay in enumerate((2, 8, 30, 0)):
            r = httpx.post(f"{self.base}/embeddings", json={"model": self.model_id, "input": texts},
                           headers={"Authorization": f"Bearer {self.key}"}, timeout=self.timeout)
            if r.status_code == 200:
                p = r.json()
                # the OpenAI-shaped embeddings schema does not guarantee response
                # order matches request order — restore it by each item's `index`.
                ordered = sorted(enumerate(p["data"]), key=lambda pair: pair[1].get("index", pair[0]))
                items = [d for _, d in ordered]
                if len(items) != len(texts):
                    raise EmbedError(f"expected {len(texts)} embeddings, got {len(items)}")
                arr = np.asarray([d["embedding"][:self.dim] for d in items], dtype=np.float32)
                if arr.ndim != 2 or arr.shape[1] != self.dim:
                    got = arr.shape[1] if arr.ndim == 2 else 0
                    raise EmbedError(f"provider returned {got}-dim vectors, expected {self.dim}")
                with self._tokens_lock:
                    self.tokens_used += int((p.get("usage") or {}).get("total_tokens") or 0)
                return arr
            if r.status_code in (429,) or r.status_code >= 500:
                if attempt == 3:
                    break
                time.sleep(delay); continue
            raise EmbedError(f"{r.status_code}: {r.text[:200]}")
        raise EmbedError("embedding request failed after 4 attempts")

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        batches = [texts[i:i + self.batch] for i in range(0, len(texts), self.batch)]
        with ThreadPoolExecutor(self.concurrency) as ex:
            parts = list(ex.map(self._one, batches))
        return np.concatenate(parts) if parts else np.empty((0, self.dim), dtype=np.float32)
