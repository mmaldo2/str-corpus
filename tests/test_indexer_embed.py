import shutil, sqlite3
from corpus_engine import store
from corpus_engine.indexer.embed import EmbedRun, build_embeddings, partition_runs, quantize
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
    build_embeddings(conn, e, e.tokenizer, RUN_B, limit=5, log=lambda *_: None)                # re-embeds 5 cases under B
    runs = conn.execute("SELECT embed_run, count(DISTINCT case_id) FROM chunks GROUP BY 1").fetchall()
    assert dict(runs)["fake-b-16-int8"] == 5 and dict(runs)["fake-a-16-int8"] == len(cases_a) - 5
    pr = partition_runs(conn)
    assert any(len(v) == 2 for v in pr.values()) or len(pr) > 1          # a mixed partition exists now
    dup = conn.execute("SELECT case_id FROM chunks GROUP BY case_id, seq HAVING count(*) > 1").fetchall()
    assert dup == []                                                        # never two runs for one (case, seq)

def test_partitions_filter_limits_scope(tmp_path, fixture_db):
    conn = _db(tmp_path, fixture_db); e = FakeEmbedder(dim=16)
    part = conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone()
    build_embeddings(conn, e, e.tokenizer, RUN_A, partitions=[tuple(part)], log=lambda *_: None)
    got = conn.execute("""SELECT DISTINCT c.era_partition, c.jurisdiction FROM chunks ch JOIN cases c ON c.case_id=ch.case_id""").fetchall()
    assert got == [tuple(part)]
