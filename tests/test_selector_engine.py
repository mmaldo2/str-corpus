import json, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.engine import attribution, plan, shard
from corpus_engine.selector.model import Selector
from corpus_engine.selector.ports import FrozenSeedResolver, RecordedEmbedder
from corpus_engine.selector.runners import EngineContext

class Stamp:
    run_id = "t-01"; ts = "2026-01-01T00:00:00"

def _conn(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn); return conn

def test_plan_skips_empty_partitions_and_covers_after_shard(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    pl = plan(conn, dom, seeds=seeds, embedder=emb)
    assert any(s.reason == "partition_empty" for s in pl.skips)          # Mass. etc. have no cases in the fixture
    assert pl.units and all(u.partition.jurisdiction in {"Tex.", "Pa.", "La.", "N.Y."} for u in pl.units)
    rep = shard(conn, dom, "t-01", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
                ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "b", log=lambda *_: None)
    assert sum(rep.signals_written.values()) > 0 and rep.batches_written > 0
    assert (tmp_path / "b" / "batch-001.json").exists() and rep.manifest["engine_version"] == "v2"
    pl2 = plan(conn, dom, seeds=seeds, embedder=emb)
    assert pl2.units == ()                                                 # everything covered now
    rep2 = shard(conn, dom, "t-02", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
                 ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "b2", dry_run=True, log=lambda *_: None)
    assert sum(rep2.signals_written.values()) == 0 and not (tmp_path / "b2").exists()

def test_attribution_reads_signals_only(tmp_path, fixture_db, repo_root):
    conn = _conn(tmp_path, fixture_db)
    conn.execute("INSERT INTO signals (case_id, selector_id, selector_version, matched_text, char_span_start, char_span_end, chunk_id, cosine, era_partition, jurisdiction, run_id, ts) VALUES (7,'a',1,'m',0,1,NULL,NULL,'e','j','r1','t')")
    conn.commit()
    a = attribution(conn, [7, 8])
    assert a[7][0].selector_id == "a" and a[8] == ()
