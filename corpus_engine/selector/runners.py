from __future__ import annotations
import atexit, gc, hashlib, re, shutil, tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import numpy as np
from corpus_engine.selector.model import Partition, SeedSet, Selector, SelectorSpecError, Signal


PENDING_SCRATCH: set[Path] = set()
"""Scratch matrix files a close() could not unlink (Windows: a lingering mapped-file
lock). Retried by every EngineContext.close() call and, once at interpreter exit, by
the atexit handler registered below."""

_pending_owned_dirs: set[Path] = set()
_atexit_registered = False


def _cleanup_pending_scratch() -> None:
    """Best-effort retry of PENDING_SCRATCH, run once at interpreter exit. Removes an
    owned scratch directory once its last pending file is gone."""
    for path in list(PENDING_SCRATCH):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
        PENDING_SCRATCH.discard(path)
    for d in list(_pending_owned_dirs):
        try:
            next(d.iterdir())
        except StopIteration:
            try:
                d.rmdir()
            except OSError:
                continue
            _pending_owned_dirs.discard(d)
        except OSError:
            continue


def _register_atexit_once() -> None:
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_cleanup_pending_scratch)
        _atexit_registered = True


_register_atexit_once()


def ctx_text(text: str, start: int, end: int, pad: int = 200) -> str:
    return text[max(0, start - pad): end + pad]


def _batched_in(ids: list[int], size: int = 500):
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


@dataclass
class ChunkMatrix:
    """embed_run identifies the embedding run; `keys` (tuple(sorted(part_index))) is this
    matrix's identity for caching - two ChunkMatrix instances can share a selector label
    (e.g. superset reuse) while covering different partitions, so EngineContext.sims()
    keys its cache by (selector label, matrix.keys), not by label alone.
    """
    M8: np.ndarray; scales: np.ndarray; chunk_ids: np.ndarray; case_ids: np.ndarray
    spans: np.ndarray; part_codes: np.ndarray; part_index: dict[str, int]
    embed_run: str | None = None
    keys: tuple[str, ...] = ()


@dataclass
class EngineContext:
    """Per-run resources shared by the runners: the connection, the chunk matrix (or
    matrices), and the cached query vectors and similarity arrays.

    The int8 chunk block is memory-mapped, not resident: at the live corpus size it is
    14.1M x 1024 = 14.45 GB, which does not fit beside SQLite and Python on a 32 GB host.
    sims() streams it in 200k-row blocks (819 MB per block as float32), so the resident
    set is one block plus the small per-chunk arrays; the OS page cache absorbs the rest.
    scratch_dir is where those files live - when None, one temp dir is created lazily and
    removed by close(). Always call close() (engine.shard / engine.probe do, in a finally)
    or the scratch files outlive the run.
    """
    conn: object
    domain: object
    embedder: object | None
    seeds: object
    resources: dict = field(default_factory=dict)
    scratch_dir: Path | None = None
    log: Callable = field(default=print, repr=False)
    _owns_scratch: bool = field(default=False, init=False, repr=False)
    _matrix_files: list = field(default_factory=list, init=False, repr=False)
    _own_pending: set = field(default_factory=set, init=False, repr=False)

    def _scratch(self) -> Path:
        if self.scratch_dir is None:
            self.scratch_dir = Path(tempfile.mkdtemp(prefix="selector-matrix-"))
            self._owns_scratch = True
        else:
            self.scratch_dir = Path(self.scratch_dir)
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
        return self.scratch_dir

    def _cached_matrix(self, keys: tuple[str, ...]) -> ChunkMatrix | None:
        """An exact hit, else any cached matrix whose partitions are a superset of keys.

        A wider matrix is correct for a narrower request: every caller selects its own
        partition through part_index / part_codes before doing anything else, and the rows
        of a partition keep their chunk_id order however wide the scan was. This is what
        lets shard() build one union matrix for the whole run and scan chunks once.
        """
        exact = self.resources.get(("matrix", keys))
        if exact is not None:
            return exact
        want = set(keys)
        for k, v in self.resources.items():
            if isinstance(k, tuple) and k and k[0] == "matrix" and want.issubset(v.part_index.keys()):
                return v
        return None

    def matrix_for(self, partitions: list[Partition]) -> ChunkMatrix:
        keys = tuple(sorted(p.key for p in partitions))
        hit = self._cached_matrix(keys)
        if hit is not None:
            return hit
        conn = self.conn
        dim = int(dict(conn.execute("SELECT key, value FROM embed_meta")).get("dim", "512"))
        where = " OR ".join("(c.era_partition=? AND c.jurisdiction=?)" for _ in partitions)
        params = [x for p in partitions for x in (p.era, p.jurisdiction)]
        n = conn.execute(f"SELECT count(*) FROM chunks ch JOIN cases c ON c.case_id=ch.case_id WHERE c.is_duplicate_of IS NULL AND ({where})", params).fetchone()[0]
        M8 = self._alloc_block(keys, n, dim)
        scales = np.empty(n, np.float32); chunk_ids = np.empty(n, np.int64)
        case_ids = np.empty(n, np.int64); spans = np.empty((n, 2), np.int32); codes = np.empty(n, np.int16)
        index = {k: i for i, k in enumerate(keys)}
        i = 0
        runs_seen: set[str] = set()
        for row in conn.execute(f"""SELECT ch.chunk_id, ch.case_id, ch.char_start, ch.char_end, ch.embedding, ch.embed_scale,
                                    c.era_partition, c.jurisdiction, ch.embed_run FROM chunks ch JOIN cases c ON c.case_id=ch.case_id
                                    WHERE c.is_duplicate_of IS NULL AND ({where}) ORDER BY ch.chunk_id""", params):
            vec = np.frombuffer(row[4], dtype=np.int8)
            M8[i, :len(vec)] = vec[:dim]; scales[i] = row[5]; chunk_ids[i] = row[0]; case_ids[i] = row[1]
            spans[i] = (row[2], row[3]); codes[i] = index[f"{row[6]}|{row[7]}"]; runs_seen.add(row[8]); i += 1
        if hasattr(M8, "flush"):
            M8.flush()
        if len(runs_seen) > 1:
            raise ValueError(f"mixed embedding runs in matrix: {sorted(runs_seen)}")
        m = ChunkMatrix(M8[:i], scales[:i], chunk_ids[:i], case_ids[:i], spans[:i], codes[:i], index,
                        next(iter(runs_seen)) if runs_seen else None, keys=keys)
        self.resources[("matrix", keys)] = m
        return m

    def _alloc_block(self, keys: tuple[str, ...], n: int, dim: int):
        """The (n, dim) int8 block, on disk. Zero rows cannot be mmapped, so stay in RAM."""
        if n == 0:
            return np.zeros((0, dim), dtype=np.int8)
        digest = hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()[:16]
        path = self._scratch() / f"matrix-{digest}.i8"
        block = np.memmap(path, dtype=np.int8, mode="w+", shape=(n, dim))
        self._matrix_files.append((path, block))
        return block

    def close(self) -> None:
        """Drop the caches and delete the scratch matrix files. Idempotent, and safe to
        call again later to retry anything left over from a first call.

        Windows will not unlink a mapped file, and mmap.close() refuses while numpy still
        exports the buffer, so the mapping is released by dropping every reference to it
        (the cached ChunkMatrix and the base memmap) and letting the collector run - but
        gc.collect() is a backstop, not the primary mechanism: an exception's traceback
        keeps its raising frame (and that frame's locals) alive for as long as the
        exception propagates, so a runner that built a matrix and then raised must drop
        its own `matrix`/`sims` locals before this runs (see `_vector_runner`'s except
        clause) or the unlink below can still find the file mapped.

        A file that still can't be unlinked (a lingering Windows lock, or a caller still
        holding a ChunkMatrix from this context) is kept in the module-level
        PENDING_SCRATCH set rather than silently dropped, a warning naming the path is
        logged via `self.log`, and - for a scratch dir this context owns - scratch_dir /
        _owns_scratch are NOT reset, so the path is not forgotten and a later close() (or
        the atexit handler at interpreter exit) can retry it.
        """
        self.resources.clear()
        pending, self._matrix_files = self._matrix_files, []
        paths = [path for path, _block in pending]
        del pending
        gc.collect()                                          # backstop, not primary
        # Retry anything left pending from an earlier close() on this context first, so
        # a second call finishes the job even though _matrix_files no longer names it.
        for path in list(self._own_pending):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                continue
            PENDING_SCRATCH.discard(path)
            self._own_pending.discard(path)
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                PENDING_SCRATCH.add(path)
                self._own_pending.add(path)
                self.log(f"WARN EngineContext.close: could not remove scratch matrix "
                         f"{path} ({type(e).__name__}: {e}); will retry")
        if self._owns_scratch and self.scratch_dir is not None:
            if self._own_pending:
                _pending_owned_dirs.add(self.scratch_dir)
                return                                         # keep the path; something is still out there
            shutil.rmtree(self.scratch_dir, ignore_errors=True)
            self.scratch_dir = None
            self._owns_scratch = False

    def query_vec(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        key = ("query", sel.label)
        if key in self.resources:
            return self.resources[key]
        if sel.kind == "embedding":
            q = self.embedder.encode_query(sel.params["query_text"], label=sel.label)
        else:
            seeds = self.seeds.resolve(sel.params["seed_set"])
            rows = []
            for batch in _batched_in(list(seeds.case_ids)):
                ph = ",".join("?" * len(batch))
                rows.extend(self.conn.execute(
                    f"SELECT embedding, embed_scale, embed_run FROM chunks WHERE case_id IN ({ph})", batch))
            if not rows:
                raise SelectorSpecError(
                    f"relevance_feedback seed_set {sel.params['seed_set']!r} has no chunked seed cases "
                    "(plan() should have skipped this selector as seed_unavailable)")
            runs = {r[2] for r in rows}
            if matrix.embed_run is not None:
                runs.add(matrix.embed_run)
            if len(runs) > 1:
                raise ValueError(f"mixed embedding runs for relevance_feedback centroid: {sorted(runs)}")
            dim = matrix.M8.shape[1]
            vecs = np.zeros((len(rows), dim), np.float32)
            scales = np.empty(len(rows), np.float32)
            for i, (blob, scale, _run) in enumerate(rows):
                vec = np.frombuffer(blob, dtype=np.int8)
                vecs[i, :len(vec)] = vec[:dim]; scales[i] = scale
            q = (vecs * scales[:, None]).mean(axis=0)
        q = (q / (np.linalg.norm(q) + 1e-12)).astype(np.float32)
        self.resources[key] = q
        return q

    def sims(self, sel: Selector, matrix: ChunkMatrix) -> np.ndarray:
        # Keyed by matrix identity, not just the selector label: with superset reuse, a
        # label-keyed entry would be wrong if a different (e.g. narrower) matrix were
        # ever scored for the same selector.
        key = ("sims", sel.label, matrix.keys)
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
    try:
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
    except BaseException:
        # This frame's `matrix`/`sims` locals are what a live traceback would otherwise
        # keep pinned for as long as the exception propagates (see EngineContext.close);
        # drop them here so close(), called from the caller's finally, can unlink the
        # scratch file without a lingering Windows mapped-file lock.
        del matrix, sims
        raise


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
