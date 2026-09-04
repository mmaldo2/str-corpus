"""Critical #1: the chunk matrix is memory-mapped, built once per run, and cleaned up.

At the live corpus size the int8 block is 14.1M x 1024 = 14.45 GB, and the pre-fix
per-scope cache held two of them at once (~26 GB) on a 32 GB host. These tests pin the
three properties the fix rests on:

  1. a union matrix produces the same signals as a per-selector-scope matrix;
  2. a request whose partitions are a subset of a cached matrix reuses it, with no query;
  3. close() removes the scratch files.
"""
import shutil
from pathlib import Path

import numpy as np

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, load_selectors
from corpus_engine.selector.ports import EMBED_KINDS, FrozenSeedResolver, RecordedEmbedder
import corpus_engine.selector.runners as runners_mod
from corpus_engine.selector.runners import RUNNERS, EngineContext, _scope_partitions, scope_partitions, union_scope


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


def _ctx(conn, repo_root, scratch=None, log=print):
    return EngineContext(conn, load_domain(), RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz"),
                         _seeds(conn), scratch_dir=scratch, log=log)


def _live_partitions(conn):
    return [Partition(e, j) for e, j in conn.execute(
        "SELECT DISTINCT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL ORDER BY 1, 2")]


def _live_chunked_partitions(conn):
    """Partitions that actually contribute rows to a chunk matrix (a live partition can
    have cases with no chunks)."""
    return [Partition(e, j) for e, j in conn.execute(
        """SELECT DISTINCT c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id = ch.case_id
           WHERE c.is_duplicate_of IS NULL ORDER BY 1, 2""")]


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
    union_ctx.matrix_for(union_scope(vec_sels))              # one matrix for the whole run
    assert len(union_ctx.resources) == 1

    compared = 0
    try:
        for sel in vec_sels:
            scope_ctx = _ctx(conn, repo_root, tmp_path / f"scope-{sel.id}-{sel.version}")
            try:
                for part in scope_partitions(sel):
                    if part.key not in live:
                        continue
                    assert _same_signals(_signals(union_ctx, sel, part),
                                         _signals(scope_ctx, sel, part)), f"{sel.label} x {part.key}"
                    compared += 1
                # the per-scope context built exactly its own scope, and no wider
                scope_matrix = scope_ctx.resources[("matrix", tuple(sorted(p.key for p in scope_partitions(sel))))]
                assert set(scope_matrix.part_index) == {p.key for p in scope_partitions(sel)}
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


# --- R1: scratch matrix orphaned when a run fails ---

def test_close_normal_path_leaves_pending_scratch_untouched(tmp_path, fixture_db, repo_root):
    """(a) the ordinary close() path adds nothing to the module-level pending set."""
    before = set(runners_mod.PENDING_SCRATCH)
    conn = _conn(tmp_path / "db", fixture_db)
    ctx = _ctx(conn, repo_root, tmp_path / "scratch")
    m = ctx.matrix_for(_live_partitions(conn))
    del m
    ctx.close()
    assert list((tmp_path / "scratch").iterdir()) == []
    assert runners_mod.PENDING_SCRATCH == before


def test_close_defers_a_windows_style_unlink_failure_to_pending_scratch(tmp_path, fixture_db, repo_root, monkeypatch):
    """(b) simulate the Windows failure: Path.unlink raises PermissionError once. The
    file is kept in PENDING_SCRATCH, a warning naming the path is logged through the
    context's `log` callable, scratch_dir / _owns_scratch are NOT reset while it is
    pending, and a second close() (with unlink restored) clears it.
    """
    conn = _conn(tmp_path / "db", fixture_db)
    logs = []
    ctx = _ctx(conn, repo_root, log=logs.append)              # no scratch_dir: context-owned
    m = ctx.matrix_for(_live_partitions(conn))
    owned = ctx.scratch_dir
    files = list(owned.glob("matrix-*.i8"))
    assert len(files) == 1
    target = files[0]
    del m                                                     # drop the live ChunkMatrix reference

    real_unlink = Path.unlink
    raised = {"n": 0}

    def flaky_unlink(self, *a, **k):
        if self == target and raised["n"] == 0:
            raised["n"] += 1
            raise PermissionError("simulated Windows mapped-file lock")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    ctx.close()

    assert target in runners_mod.PENDING_SCRATCH
    assert any(str(target) in msg for msg in logs)             # warning names the path
    assert ctx.scratch_dir == owned and ctx._owns_scratch is True   # not reset while pending
    assert owned.exists()

    monkeypatch.undo()                                         # restore the real Path.unlink
    ctx.close()                                                # second call retries and clears it

    assert target not in runners_mod.PENDING_SCRATCH
    assert not target.exists()
    assert ctx.scratch_dir is None and ctx._owns_scratch is False
    assert not owned.exists()


# --- R3: key the sims cache by matrix identity ---

def test_sims_cache_is_keyed_by_matrix_identity_not_selector_label_alone(tmp_path, fixture_db, repo_root):
    """With superset reuse, a sims() entry keyed only by selector label would be wrong if
    a different matrix were ever scored under that label. Score the same selector against
    two distinct matrices - built in two separate contexts, so neither's matrix_for() can
    satisfy the other's request via superset reuse - and confirm two distinct sims cache
    entries, with arrays whose lengths reflect their own matrix, not each other's.
    """
    conn = _conn(tmp_path / "db", fixture_db)
    dom = load_domain()
    sel = next(s for s in load_selectors(dom) if s.kind in EMBED_KINDS)
    chunked = _live_chunked_partitions(conn)
    assert len(chunked) >= 2
    p1, p2 = chunked[0], chunked[1]

    narrow_ctx = _ctx(conn, repo_root, tmp_path / "narrow")
    wide_ctx = _ctx(conn, repo_root, tmp_path / "wide")
    try:
        narrow = narrow_ctx.matrix_for([p1])
        wide = wide_ctx.matrix_for([p1, p2])
        assert narrow.keys == (p1.key,)
        assert wide.keys == tuple(sorted((p1.key, p2.key)))
        assert len(narrow.M8) < len(wide.M8)                  # p2 contributes at least one row

        sims_narrow = narrow_ctx.sims(sel, narrow)
        sims_wide = wide_ctx.sims(sel, wide)

        assert len(sims_narrow) == len(narrow.M8)
        assert len(sims_wide) == len(wide.M8)
        assert len(sims_narrow) != len(sims_wide)

        assert ("sims", sel.label, narrow.keys) in narrow_ctx.resources
        assert ("sims", sel.label, wide.keys) in wide_ctx.resources
        # re-fetching returns the cached array, not a recompute under a colliding key
        assert narrow_ctx.sims(sel, narrow) is sims_narrow
        assert wide_ctx.sims(sel, wide) is sims_wide
    finally:
        narrow_ctx.close()
        wide_ctx.close()


# --- R4: make the scope helper public / move the union rule next to the matrix ---

def test_scope_partitions_is_public_with_a_deprecated_alias():
    assert _scope_partitions is scope_partitions


def test_union_scope_matches_the_original_dict_union_formula_in_order(tmp_path, fixture_db, repo_root):
    """union_scope() must preserve the exact insertion order of the formula it replaces
    in engine.shard() - {p.key: p for s in selectors for p in scope_partitions(s)} - so
    the union matrix's row order (and its last-ulp cosines) is unchanged.
    """
    conn = _conn(tmp_path / "db", fixture_db)
    dom = load_domain()
    vec_sels = [s for s in load_selectors(dom) if s.kind in EMBED_KINDS]
    assert len(vec_sels) >= 2

    original = {p.key: p for s in vec_sels for p in scope_partitions(s)}
    assert union_scope(vec_sels) == list(original.values())

    # Duplicate selectors and a reordering both prove it is first-seen order, not sorted.
    doubled = vec_sels + vec_sels
    assert union_scope(doubled) == list(original.values())
    reordered = {p.key: p for s in reversed(vec_sels) for p in scope_partitions(s)}
    assert union_scope(list(reversed(vec_sels))) == list(reordered.values())
