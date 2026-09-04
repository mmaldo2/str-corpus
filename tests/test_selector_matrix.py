"""Critical #1: the chunk matrix is memory-mapped, built once per run, and cleaned up.

At the live corpus size the int8 block is 14.1M x 1024 = 14.45 GB, and the pre-fix
per-scope cache held two of them at once (~26 GB) on a 32 GB host. These tests pin the
three properties the fix rests on:

  1. a union matrix produces the same signals as a per-selector-scope matrix;
  2. a request whose partitions are a subset of a cached matrix reuses it, with no query;
  3. close() removes the scratch files.
"""
import shutil

import numpy as np

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, load_selectors
from corpus_engine.selector.ports import EMBED_KINDS, FrozenSeedResolver, RecordedEmbedder
from corpus_engine.selector.runners import RUNNERS, EngineContext, _scope_partitions


def _conn(tmp_path, fixture_db):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "c.db"
    shutil.copy(fixture_db, p)
    conn = store.connect(p)
    store.migrate(conn)
    return conn


def _seeds(conn):
    """Real chunked fixture cases, offered under every seed-set name the selectors use."""
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT case_id FROM chunks ORDER BY case_id LIMIT 5")]
    return FrozenSeedResolver({n: ids for n in ("both", "ledger-favorable-reviewed", "treatise-anchors")})


def _ctx(conn, repo_root, scratch=None):
    return EngineContext(conn, load_domain(), RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz"),
                         _seeds(conn), scratch_dir=scratch)


def _live_partitions(conn):
    return [Partition(e, j) for e, j in conn.execute(
        "SELECT DISTINCT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL ORDER BY 1, 2")]


def _signals(ctx, sel, part):
    return [(g.case_id, g.chunk_id, g.cosine) for g in RUNNERS[sel.kind](ctx, sel, part)]


def _same_signals(a, b):
    """Identical selection and order; cosine equal to float32 precision.

    The cosines are not bit-identical between a union matrix and a per-scope one: sims()
    is a BLAS gemv over the whole block, and OpenBLAS picks its accumulation order from
    the matrix shape, so the same row scored in a 1,564-row block and a 1,159-row block
    can differ by one float32 ulp (measured max 1.5e-7, mean 9.1e-10 on the fixture, with
    provably identical input rows, scales and query vector). Which cases are selected, and
    in what order, is unchanged - that is the property that matters, and it is asserted
    exactly. `tests/test_selector_runners.py` already compares cosines at round(x, 6) for
    the same reason.
    """
    assert [(c, ch) for c, ch, _ in a] == [(c, ch) for c, ch, _ in b]
    assert all(abs(x[2] - y[2]) < 1e-6 for x, y in zip(a, b))
    return True


def test_union_matrix_yields_identical_signals_to_per_scope_matrices(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path / "db", fixture_db)
    dom = load_domain()
    vec_sels = [s for s in load_selectors(dom) if s.kind in EMBED_KINDS]
    assert vec_sels
    live = {p.key for p in _live_partitions(conn)}

    union_ctx = _ctx(conn, repo_root, tmp_path / "union")
    union = {p.key: p for s in vec_sels for p in _scope_partitions(s)}
    union_ctx.matrix_for(list(union.values()))              # one matrix for the whole run
    assert len(union_ctx.resources) == 1

    compared = 0
    try:
        for sel in vec_sels:
            scope_ctx = _ctx(conn, repo_root, tmp_path / f"scope-{sel.id}-{sel.version}")
            try:
                for part in _scope_partitions(sel):
                    if part.key not in live:
                        continue
                    assert _same_signals(_signals(union_ctx, sel, part),
                                         _signals(scope_ctx, sel, part)), f"{sel.label} x {part.key}"
                    compared += 1
                # the per-scope context built exactly its own scope, and no wider
                scope_matrix = scope_ctx.resources[("matrix", tuple(sorted(p.key for p in _scope_partitions(sel))))]
                assert set(scope_matrix.part_index) == {p.key for p in _scope_partitions(sel)}
            finally:
                scope_ctx.close()
        # every vector runner reused the single union matrix - no second matrix was built
        assert sum(1 for k in union_ctx.resources if k[0] == "matrix") == 1
    finally:
        union_ctx.close()
    assert compared >= len(vec_sels)


class _CountingConn:
    """Proxy that counts execute() calls; sqlite3.Connection cannot be monkeypatched."""

    def __init__(self, conn):
        self._conn = conn
        self.executes = 0

    def execute(self, *a, **k):
        self.executes += 1
        return self._conn.execute(*a, **k)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_matrix_for_reuses_a_superset_matrix_without_querying(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path / "db", fixture_db)
    ctx = _ctx(conn, repo_root, tmp_path / "scratch")
    try:
        parts = _live_partitions(conn)
        assert len(parts) >= 2
        p1, p2 = parts[0], parts[1]

        wide = ctx.matrix_for([p1, p2])
        counting = _CountingConn(ctx.conn)
        ctx.conn = counting

        narrow = ctx.matrix_for([p1])
        assert narrow is wide                                # same object, not a rebuild
        assert counting.executes == 0                        # and not a single query
        assert ctx.matrix_for([p2, p1]) is wide              # order-insensitive
        assert counting.executes == 0
        assert sum(1 for k in ctx.resources if k[0] == "matrix") == 1
    finally:
        ctx.conn = conn
        ctx.close()


def test_close_removes_the_memmapped_matrix_files(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path / "db", fixture_db)
    scratch = tmp_path / "scratch"
    ctx = _ctx(conn, repo_root, scratch)
    m = ctx.matrix_for(_live_partitions(conn))
    assert isinstance(m.M8, np.memmap)                       # on disk, not resident
    files = list(scratch.glob("matrix-*.i8"))
    assert len(files) == 1 and files[0].stat().st_size >= m.M8.shape[0] * m.M8.shape[1]

    del m                                                    # a live ChunkMatrix keeps the file mapped
    ctx.close()
    assert list(scratch.iterdir()) == []                     # caller-supplied dir kept, files gone
    ctx.close()                                              # idempotent


def test_close_removes_a_context_owned_scratch_dir(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path / "db", fixture_db)
    ctx = _ctx(conn, repo_root)                              # no scratch_dir: one is made lazily
    m = ctx.matrix_for(_live_partitions(conn))
    owned = ctx.scratch_dir
    assert owned is not None and owned.exists()
    del m
    ctx.close()
    assert not owned.exists() and ctx.scratch_dir is None
