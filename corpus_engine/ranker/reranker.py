from __future__ import annotations
import hashlib
import re
from typing import Sequence
from corpus_engine.ranker.features import signal_summary
from corpus_engine.ranker.ports import round6


def gpu_has_resident_model(threshold_bytes: int = 6 << 30) -> bool:
    try:
        import torch
        return torch.cuda.is_available() and torch.cuda.memory_allocated() > threshold_bytes
    except Exception:            # noqa: BLE001 — no torch/cuda means nothing resident
        return False


class QwenReranker:
    def __init__(self, model: str, revision: str, query: str, *, batch: int = 8, encoder=None):
        if not re.fullmatch(r"[0-9a-f]{7,40}", revision or ""):
            raise ValueError(
                f"reranker revision must be a pinned commit sha (7-40 hex chars), not {revision!r} "
                "(run tools/pin_reranker.py)")
        self.model, self.revision, self.query, self.batch = model, revision, query, int(batch)
        self._encoder = encoder
        self.ranker_id = f"qwen3-reranker-4b:{revision[:7]}"

    @classmethod
    def from_domain(cls, domain):
        r = domain.ranking.reranker
        return cls(r["model"], str(r.get("revision", "")), r["query"], batch=int(r.get("batch", 8)))

    def digest(self) -> str:
        return hashlib.sha256(f"{self.model}@{self.revision}|{self.query}".encode()).hexdigest()[:16]

    def _enc(self):
        if self._encoder is None:
            if gpu_has_resident_model():
                raise RuntimeError("another model is resident on the GPU; run the reranker in its own process")
            from sentence_transformers import CrossEncoder
            self._encoder = CrossEncoder(self.model, revision=self.revision, device="cuda", max_length=1024)
        return self._encoder

    def _chunk_text(self, conn, case_id: int, chunk_id: int | None) -> str:
        row = conn.execute("SELECT char_start, char_end FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone() if chunk_id is not None else None
        if row is None:
            row = conn.execute("SELECT char_start, char_end FROM chunks WHERE case_id=? ORDER BY seq LIMIT 1", (case_id,)).fetchone()
        if row is None:
            return conn.execute("SELECT substr(norm_text, 1, 2000) FROM cases WHERE case_id=?", (case_id,)).fetchone()[0] or ""
        return conn.execute("SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?", (row[0] + 1, row[1] - row[0], case_id)).fetchone()[0] or ""

    def score(self, conn, run_id: str, case_ids: Sequence[int]) -> dict[int, float]:
        ids = [int(c) for c in case_ids]
        summ = signal_summary(conn, ids)
        pairs = [(self.query, self._chunk_text(conn, cid, summ[cid].best_chunk_id)) for cid in ids]
        logits = self._enc().predict(pairs, batch_size=self.batch)
        return {cid: round6(float(l)) for cid, l in zip(ids, logits)}
