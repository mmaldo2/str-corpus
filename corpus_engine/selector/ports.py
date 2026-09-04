from __future__ import annotations
import json
from pathlib import Path
from typing import Protocol
import numpy as np
from corpus_engine.indexer.embed import partition_runs
from corpus_engine.selector.model import ENGINE_VERSION, Partition, SeedSet, Selector, SelectorSpecError, Skip


class QueryEmbedder(Protocol):
    dim: int
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray: ...


class LocalQueryEmbedder:
    def __init__(self, conn):
        from corpus_engine.indexer.embedders import LocalEmbedder
        meta = dict(conn.execute("SELECT key, value FROM embed_meta"))
        if "model" not in meta:
            raise SelectorSpecError("embed_meta missing model key; index must be built with a pinned revision first")
        if "revision" not in meta:
            raise SelectorSpecError("embed_meta missing revision key; index must be built with a pinned revision first")
        if meta["revision"] == "main":
            raise SelectorSpecError("embed_meta has unpinned revision 'main'; index must be built with a pinned revision first")
        self.dim = int(meta.get("dim", "512"))
        self._local = LocalEmbedder(meta["model"], meta["revision"], self.dim)
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray:
        q = self._local.encode_query(text).astype(np.float32)
        return q / (np.linalg.norm(q) + 1e-12)


class RecordedEmbedder:
    def __init__(self, npz_path: Path):
        self._z = np.load(npz_path)
        self.dim = int(json.loads(str(self._z["__meta__"])).get("dim", "512"))
    def encode_query(self, text: str, *, label: str | None = None) -> np.ndarray:
        if label is None or label not in self._z.files:
            raise KeyError(f"no recorded vector for {label}")
        return self._z[label].astype(np.float32)


class SeedResolver(Protocol):
    def resolve(self, ref: str) -> SeedSet: ...


class FrozenSeedResolver:
    def __init__(self, mapping: dict[str, list[int]]):
        self.m = mapping
    def resolve(self, ref: str) -> SeedSet:
        if ref not in self.m:
            raise SelectorSpecError(f"unknown seed set {ref}")
        return SeedSet.build(ref, self.m[ref])


class LedgerSeedResolver:
    def __init__(self, domain):
        self.domain = domain
    def _ledger(self) -> list[int]:
        from corpus_engine.ledger import open_ledger
        return list(open_ledger(domain=self.domain).view().seed_set().case_ids)
    def _treatise(self) -> list[int]:
        out = []
        for line in Path(self.domain.gold_path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                g = json.loads(line)
                if g.get("tier") == "treatise" and g.get("case_id"):
                    out.append(int(g["case_id"]))
        return out
    def resolve(self, ref: str) -> SeedSet:
        if ref == "ledger-favorable-reviewed":
            return SeedSet.build(ref, self._ledger())
        if ref == "treatise-anchors":
            return SeedSet.build(ref, self._treatise())
        if ref == "both":
            return SeedSet.build(ref, self._ledger() + self._treatise())
        raise SelectorSpecError(f"unknown seed set {ref}")


EMBED_KINDS = {"embedding", "relevance_feedback"}
SEEDED_KINDS = {"citation_graph", "relevance_feedback"}


def fingerprint(conn, selector: Selector, partitions: list[Partition], *, seeds: SeedResolver, min_seeds: int) -> str | Skip:
    parts = tuple(partitions)
    seed_part = ""
    if selector.kind in SEEDED_KINDS:
        ss = seeds.resolve(selector.params["seed_set"])
        if len(ss.case_ids) < min_seeds:
            return Skip(selector.key, parts, "seed_unavailable")
        if selector.kind == "relevance_feedback":
            ids = list(ss.case_ids)
            chunked = 0
            for i in range(0, len(ids), 500):
                batch = ids[i:i + 500]
                ph = ",".join("?" * len(batch))
                chunked += conn.execute(
                    f"SELECT COUNT(DISTINCT case_id) FROM chunks WHERE case_id IN ({ph})", batch).fetchone()[0]
            if chunked < min_seeds:
                return Skip(selector.key, parts, "seed_unavailable")
        seed_part = f"|seed:{ss.hash}"
    if selector.kind in ("fts_phrase", "fts_near"):
        return "fts:v1"
    if selector.kind == "regex":
        return "regex:v1"
    if selector.kind == "citation_graph":
        return f"graph:v1{seed_part}"
    runs = partition_runs(conn)
    seen: set[str] = set()
    for p in parts:
        r = runs.get((p.era, p.jurisdiction), set())
        if not r:
            return Skip(selector.key, parts, "index_incomplete")
        seen |= r
    if len(seen) != 1:
        return Skip(selector.key, parts, "mixed_embedding_model")
    return f"embed:{next(iter(seen))}|engine:{ENGINE_VERSION}{seed_part}"
