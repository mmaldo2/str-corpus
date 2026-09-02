import shutil, sqlite3
import pytest
from corpus_engine import store
from corpus_engine.indexer.embed import EmbedRun, build_embeddings, partition_runs, quantize, register_run
from corpus_engine.indexer.embedders import FakeEmbedder
import numpy as np

RUN_A = EmbedRun("fake-a-16-int8", "fake", "r", 16, "int8-symmetric-pervector", 60, 10, "{name}\n", "test")
RUN_B = EmbedRun("fake-b-16-int8", "fake", "r", 16, "int8-symmetric-pervector", 60, 10, "{name}\n", "test")

def _db(tmp_path, fixture_db):
    # fixture predates the embed_run column, so store.migrate legacy-tags its
    # chunks under LEGACY_EMBED_RUN and registers that run (store.migrate is
    # exercised on its own in test_store_migrate.py); clear that residue so
    # the run-tagging assertions below start from a clean slate.
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); store.migrate(conn)
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM embed_runs")
    conn.execute("DELETE FROM embed_meta")
    conn.commit()
    return conn

def test_quantize_round_trips_direction():
    v = np.random.default_rng(0).standard_normal((3, 16)).astype(np.float32)
    q8, s = quantize(v)
    back = q8.astype(np.float32) * s[:, None]
    vn = v / np.linalg.norm(v, axis=1, keepdims=True)
    assert np.all((back * vn).sum(axis=1) > 0.99)

def test_build_embeddings_tags_runs_resumes_and_replaces(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db); e = FakeEmbedder(dim=16)
    n = build_embeddings(conn, e, e.tokenizer, RUN_A, log=lambda *_: None)          # all cases, fake embedder is fast
    assert n > 0 and conn.execute("SELECT DISTINCT embed_run FROM chunks").fetchall() == [("fake-a-16-int8",)]
    assert conn.execute("SELECT run_key FROM embed_runs").fetchall() == [("fake-a-16-int8",)]
    assert build_embeddings(conn, e, e.tokenizer, RUN_A, log=lambda *_: None) == 0             # resume: nothing left under A
    cases_a = {r[0] for r in conn.execute("SELECT DISTINCT case_id FROM chunks")}
    # re-embed 5 cases under B, all drawn from one partition with >5 cases, so that
    # partition is guaranteed to end up holding both runs (a partition-agnostic limit=5
    # could land entirely inside a small partition and never exercise the mixed case)
    big_partition = conn.execute(
        """SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL
           GROUP BY 1, 2 HAVING count(*) > 5 ORDER BY count(*) DESC LIMIT 1"""
    ).fetchone()
    build_embeddings(conn, e, e.tokenizer, RUN_B, limit=5, partitions=[tuple(big_partition)], log=lambda *_: None)
    runs = conn.execute("SELECT embed_run, count(DISTINCT case_id) FROM chunks GROUP BY 1").fetchall()
    assert dict(runs)["fake-b-16-int8"] == 5 and dict(runs)["fake-a-16-int8"] == len(cases_a) - 5
    pr = partition_runs(conn)
    assert any(len(v) == 2 for v in pr.values())                           # a mixed partition exists now
    dup = conn.execute("SELECT case_id FROM chunks GROUP BY case_id, seq HAVING count(*) > 1").fetchall()
    assert dup == []                                                        # never two runs for one (case, seq)
    spans_both = conn.execute(
        "SELECT case_id FROM chunks GROUP BY case_id HAVING count(DISTINCT embed_run) > 1"
    ).fetchall()
    assert spans_both == []                                                 # no case appears under both runs

def test_partitions_filter_limits_scope(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db); e = FakeEmbedder(dim=16)
    part = conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone()
    build_embeddings(conn, e, e.tokenizer, RUN_A, partitions=[tuple(part)], log=lambda *_: None)
    got = conn.execute("""SELECT DISTINCT c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id=ch.case_id""").fetchall()
    assert got == [tuple(part)]

# --- I2: register_run must reject a run_key whose recorded parameters have drifted ---

def test_register_run_matching_row_is_a_noop(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db)
    register_run(conn, RUN_A)
    register_run(conn, RUN_A)  # identical params again: no raise, no duplicate row
    assert conn.execute("SELECT count(*) FROM embed_runs WHERE run_key=?", (RUN_A.run_key,)).fetchone()[0] == 1

def test_register_run_rejects_a_key_with_drifted_parameters(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db)
    register_run(conn, RUN_A)
    drifted = EmbedRun(RUN_A.run_key, RUN_A.model, "different-revision", RUN_A.dim, RUN_A.quant,
                       RUN_A.chunk_tokens, RUN_A.chunk_overlap, RUN_A.prefix_template, RUN_A.provider)
    with pytest.raises(ValueError, match=f"embed_run {RUN_A.run_key} already registered with different parameters"):
        register_run(conn, drifted)

def test_register_run_flags_provider_drift_specifically(tmp_path, fixture_db):
    # provider is the field the review called out as not part of the key at all.
    conn = _db(tmp_path, fixture_db)
    register_run(conn, RUN_A)
    drifted = EmbedRun(RUN_A.run_key, RUN_A.model, RUN_A.revision, RUN_A.dim, RUN_A.quant,
                       RUN_A.chunk_tokens, RUN_A.chunk_overlap, RUN_A.prefix_template, "other-provider")
    with pytest.raises(ValueError, match="provider: 'test' != 'other-provider'"):
        register_run(conn, drifted)
