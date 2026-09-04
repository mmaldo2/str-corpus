from __future__ import annotations
import re
from dataclasses import dataclass, field
import numpy as np
from corpus_engine.selector.model import Partition, SeedSet, Selector, Signal


def ctx_text(text: str, start: int, end: int, pad: int = 200) -> str:
    return text[max(0, start - pad): end + pad]


@dataclass
class ChunkMatrix:
    M8: np.ndarray; scales: np.ndarray; chunk_ids: np.ndarray; case_ids: np.ndarray
    spans: np.ndarray; part_codes: np.ndarray; part_index: dict[str, int]


@dataclass
class EngineContext:
    conn: object
    domain: object
    embedder: object | None
    seeds: object
    resources: dict = field(default_factory=dict)

    def matrix_for(self, partitions: list[Partition]) -> ChunkMatrix:
        keys = tuple(sorted(p.key for p in partitions))
        if ("matrix", keys) in self.resources:
            return self.resources[("matrix", keys)]
        conn = self.conn
        dim = int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))
        where = " OR ".join("(c.era_partition=? AND c.jurisdiction=?)" for _ in partitions)
        params = [x for p in partitions for x in (p.era, p.jurisdiction)]
        n = conn.execute(f"SELECT count(*) FROM chunks ch JOIN cases c ON c.case_id=ch.case_id WHERE c.is_duplicate_of IS NULL AND ({where})", params).fetchone()[0]
        M8 = np.empty((n, dim), dtype=np.int8); scales = np.empty(n, np.float32); chunk_ids = np.empty(n, np.int64)
        case_ids = np.empty(n, np.int64); spans = np.empty((n, 2), np.int32); codes = np.empty(n, np.int16)
        index = {k: i for i, k in enumerate(keys)}
        i = 0
        for row in conn.execute(f"""SELECT ch.chunk_id, ch.case_id, ch.char_start, ch.char_end, ch.embedding, ch.embed_scale,
                                    c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id=ch.case_id
                                    WHERE c.is_duplicate_of IS NULL AND ({where}) ORDER BY ch.chunk_id""", params):
            vec = np.frombuffer(row[4], dtype=np.int8)
            M8[i, :len(vec)] = vec[:dim]; scales[i] = row[5]; chunk_ids[i] = row[0]; case_ids[i] = row[1]
            spans[i] = (row[2], row[3]); codes[i] = index[f"{row[6]}|{row[7]}"]; i += 1
        m = ChunkMatrix(M8[:i], scales[:i], chunk_ids[:i], case_ids[:i], spans[:i], codes[:i], index)
        self.resources[("matrix", keys)] = m
        return m

    def query_vec(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        key = ("query", sel.label)
        if key in self.resources:
            return self.resources[key]
        if sel.kind == "embedding":
            q = self.embedder.encode_query(sel.params["query_text"], label=sel.label)
        else:
            seeds = self.seeds.resolve(sel.params["seed_set"])
            mask = np.isin(matrix.case_ids, np.asarray(seeds.case_ids))
            if not mask.any():
                q = np.zeros(matrix.M8.shape[1], np.float32)
            else:
                vecs = matrix.M8[mask].astype(np.float32) * matrix.scales[mask][:, None]
                q = vecs.mean(axis=0)
        q = (q / (np.linalg.norm(q) + 1e-12)).astype(np.float32)
        self.resources[key] = q
        return q

    def sims(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        key = ("sims", sel.label)
        if key in self.resources:
            return self.resources[key]
        q = self.query_vec(sel, matrix)
        n = len(matrix.M8); out = np.empty(n, np.float32); block = 200_000
        for a in range(0, n, block):
            b = min(a + block, n)
            out[a:b] = (matrix.M8[a:b].astype(np.float32) @ q) * matrix.scales[a:b]
        self.resources[key] = out
        return out


def _scope_partitions(sel: Selector) -> list[Partition]:
    return [Partition(e, j) for e in sel.era_scope for j in sel.jurisdiction_scope]


def run_fts(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    table = "fts_raw" if s.params.get("index", "raw") == "raw" else "fts_porter"
    rows = ctx.conn.execute(
        f"""SELECT c.case_id, c.norm_text FROM {table} JOIN cases c ON c.case_id = {table}.rowid
            WHERE {table} MATCH ? AND c.era_partition = ? AND c.jurisdiction = ? AND c.is_duplicate_of IS NULL""",
        (s.params["pattern"], part.era, part.jurisdiction)).fetchall()
    phrases = [p.lower() for p in re.findall(r'"([^"]+)"', s.params["pattern"])]
    out = []
    for case_id, norm_text in rows:
        span, matched = (0, 0), ""
        for ph in phrases:
            i = norm_text.find(ph)
            if i >= 0:
                span = (i, i + len(ph)); matched = ctx_text(norm_text, *span); break
        if not matched:
            matched = norm_text[:400]
        out.append(Signal(case_id, s.id, s.version, matched, span, None, None, part))
    return out


def run_regex(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    pat = re.compile(s.params["pattern"], re.IGNORECASE)
    out = []
    for case_id, norm_text in ctx.conn.execute(
            "SELECT case_id, norm_text FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL",
            (part.era, part.jurisdiction)):
        m = pat.search(norm_text)
        if m:
            out.append(Signal(case_id, s.id, s.version, ctx_text(norm_text, m.start(), m.end()), (m.start(), m.end()), None, None, part))
    return out


def _vector_runner(ctx: EngineContext, s: Selector, part: Partition, exclude: set[int]) -> list[Signal]:
    matrix = ctx.matrix_for(_scope_partitions(s))
    sims = ctx.sims(s, matrix)
    code = matrix.part_index.get(part.key)
    if code is None:
        return []
    cand = np.flatnonzero(matrix.part_codes == code)
    if not len(cand):
        return []
    order = cand[np.lexsort((matrix.chunk_ids[cand], -sims[cand]))][: int(s.params.get("top_k", 50)) * 3]
    out, seen = [], set()
    min_cos, top_k = float(s.params.get("min_cosine", 0.5)), int(s.params.get("top_k", 50))
    for i in order:
        if sims[i] < min_cos or len(out) >= top_k:
            break
        case_id = int(matrix.case_ids[i])
        if case_id in seen or case_id in exclude:
            continue
        seen.add(case_id)
        cs, ce = int(matrix.spans[i][0]), int(matrix.spans[i][1])
        text = ctx.conn.execute("SELECT substr(norm_text, ?, ?) FROM cases WHERE case_id=?", (cs + 1, min(ce - cs, 400), case_id)).fetchone()[0]
        out.append(Signal(case_id, s.id, s.version, text, (cs, ce), int(matrix.chunk_ids[i]), float(sims[i]), part))
    return out


def run_embedding(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    return _vector_runner(ctx, s, part, set())


def run_relevance_feedback(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    seeds = ctx.seeds.resolve(s.params["seed_set"])
    return _vector_runner(ctx, s, part, set(seeds.case_ids))


def run_citation_graph(ctx: EngineContext, s: Selector, part: Partition) -> list[Signal]:
    seeds = ctx.seeds.resolve(s.params["seed_set"]); ids = list(seeds.case_ids)
    if not ids:
        return []
    ph = ",".join("?" * len(ids)); direction = s.params.get("direction", "both")
    out, seen = [], set(ids)
    if direction in ("both", "citing"):
        for cid, cite in ctx.conn.execute(
                f"""SELECT ct.citing_case_id, ct.cite FROM cites_to ct JOIN cases c ON c.case_id = ct.citing_case_id
                    WHERE ct.cited_case_id IN ({ph}) AND c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL
                    ORDER BY ct.citing_case_id, ct.cite""", ids + [part.era, part.jurisdiction]):
            if cid not in seen:
                seen.add(cid); out.append(Signal(cid, s.id, s.version, f"cites {cite}", (0, 0), None, None, part))
    if direction in ("both", "cited"):
        for cid, cite in ctx.conn.execute(
                f"""SELECT ct.cited_case_id, ct.cite FROM cites_to ct JOIN cases c ON c.case_id = ct.cited_case_id
                    WHERE ct.citing_case_id IN ({ph}) AND c.era_partition=? AND c.jurisdiction=? AND c.is_duplicate_of IS NULL
                    ORDER BY ct.cited_case_id, ct.cite""", ids + [part.era, part.jurisdiction]):
            if cid not in seen:
                seen.add(cid); out.append(Signal(cid, s.id, s.version, f"cited by {cite}", (0, 0), None, None, part))
    return out


RUNNERS = {"fts_phrase": run_fts, "fts_near": run_fts, "regex": run_regex, "embedding": run_embedding,
           "citation_graph": run_citation_graph, "relevance_feedback": run_relevance_feedback}
