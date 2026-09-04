import json, shutil
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
import corpus_engine.selector.engine as engine_mod
from corpus_engine.selector.engine import _already_read_ids_with_skips, already_read_ids, attribution, plan, shard
from corpus_engine.selector.model import Selector, load_selectors
from corpus_engine.selector.ports import EMBED_KINDS, FrozenSeedResolver, RecordedEmbedder
import corpus_engine.selector.runners as runners_mod
from corpus_engine.selector.runners import RUNNERS, EngineContext

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


# --- Fix Round 1 ---

def test_shard_calls_partition_runs_once(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    real = engine_mod.partition_runs
    calls = {"n": 0}
    def counting(c):
        calls["n"] += 1
        return real(c)
    monkeypatch.setattr(engine_mod, "partition_runs", counting)

    shard(conn, dom, "t-pr1", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
          ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "bpr", dry_run=True, log=lambda *_: None)
    assert calls["n"] == 1                                                 # one scan for the whole shard() call

    calls["n"] = 0
    precomputed = real(conn)
    shard(conn, dom, "t-pr2", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
          ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "bpr2", dry_run=True, log=lambda *_: None,
          runs=precomputed)
    assert calls["n"] == 0                                                 # supplied runs short-circuits the scan


def test_already_read_ids_skips_malformed_input(tmp_path):
    runs_dir = tmp_path / "runs"; ledger_dir = tmp_path / "ledger"
    ext_dir = runs_dir / "cycle-x" / "extractions"
    ext_dir.mkdir(parents=True)
    (ext_dir / "bad.json").write_text(json.dumps({"a": 1}), encoding="utf-8")             # not a list
    (ext_dir / "good.json").write_text(json.dumps([{"case_id": 42}, {"case_id": 43}]), encoding="utf-8")
    manifest_dir = ledger_dir / "manifest"; manifest_dir.mkdir(parents=True)
    (manifest_dir / "cycle-x.jsonl").write_text(
        "not json\n" + json.dumps({"case_id": 44}) + "\n" + json.dumps({"no_case_id": True}) + "\n",
        encoding="utf-8")

    ids, skipped = _already_read_ids_with_skips(runs_dir, ledger_dir, log=lambda *_: None)
    assert ids == {42, 43, 44}
    assert skipped == 3                                                    # bad.json + bad line + missing case_id
    assert already_read_ids(runs_dir, ledger_dir) == {42, 43, 44}          # public wrapper: same ids, no crash


def test_shard_rolls_back_on_runner_exception(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    pl = plan(conn, dom, seeds=seeds, embedder=emb)
    assert len(pl.units) >= 2
    first, second = pl.units[0], pl.units[1]
    sels = load_selectors(dom); by_key = {s.key: s for s in sels}
    second_kind = by_key[second.key].kind
    real_runner = RUNNERS[second_kind]

    def flaky(ctx, s, part):
        if s.key == second.key and part.key == second.partition.key:
            raise RuntimeError("boom")
        return real_runner(ctx, s, part)
    monkeypatch.setitem(RUNNERS, second_kind, flaky)

    with pytest.raises(RuntimeError):
        shard(conn, dom, "t-fail", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
              ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "bfail", log=lambda *_: None)

    assert conn.in_transaction is False
    cov_first = conn.execute(
        "SELECT 1 FROM coverage_v2 WHERE selector_id=? AND selector_version=? AND partition_key=?",
        (first.key[0], first.key[1], first.partition.key)).fetchone()
    assert cov_first is not None
    cov_second = conn.execute(
        "SELECT 1 FROM coverage_v2 WHERE selector_id=? AND selector_version=? AND partition_key=?",
        (second.key[0], second.key[1], second.partition.key)).fetchone()
    assert cov_second is None
    sig_second = conn.execute(
        "SELECT count(*) FROM signals WHERE selector_id=? AND selector_version=? AND era_partition=? AND jurisdiction=?",
        (second.key[0], second.key[1], second.partition.era, second.partition.jurisdiction)).fetchone()[0]
    assert sig_second == 0
def test_shard_cleans_up_scratch_matrix_when_a_vector_runner_raises(tmp_path, fixture_db, repo_root, monkeypatch):
    """R1: a runner exception must not orphan the scratch chunk matrix. On this platform
    close() should succeed outright and leave no file behind; if it genuinely cannot (a
    Windows mapped-file lock that outlives the run), the leftover file must be tracked in
    runners.PENDING_SCRATCH with a warning logged - never silently forgotten. Either
    outcome is acceptable here; silently losing the file is not.
    """
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    pl = plan(conn, dom, seeds=seeds, embedder=emb)
    sels = load_selectors(dom); by_key = {s.key: s for s in sels}
    vec_unit = next(u for u in pl.units if by_key[u.key].kind in EMBED_KINDS)
    vec_kind = by_key[vec_unit.key].kind
    real_runner = RUNNERS[vec_kind]

    def flaky(ctx, s, part):
        if s.key == vec_unit.key and part.key == vec_unit.partition.key:
            raise RuntimeError("boom")
        return real_runner(ctx, s, part)
    monkeypatch.setitem(RUNNERS, vec_kind, flaky)

    scratch = tmp_path / "scratch"
    logs = []
    before_pending = set(runners_mod.PENDING_SCRATCH)
    with pytest.raises(RuntimeError):
        shard(conn, dom, "t-r1c", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
              ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "br1c", log=logs.append, scratch_dir=scratch)

    new_pending = set(runners_mod.PENDING_SCRATCH) - before_pending
    leftover = list(scratch.glob("matrix-*.i8")) if scratch.exists() else []
    assert not leftover or (set(leftover) <= new_pending and any("could not remove" in m for m in logs))


def test_shard_accepts_a_precomputed_plan_and_does_not_replan(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = _conn(tmp_path, fixture_db); dom = load_domain()
    seeds = FrozenSeedResolver({"both": list(range(10)), "ledger-favorable-reviewed": list(range(10))})
    emb = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    pre = plan(conn, dom, seeds=seeds, embedder=emb)

    def boom(*a, **k):                                    # pragma: no cover - must never run
        raise AssertionError("shard() re-planned despite plan_=")
    monkeypatch.setattr(engine_mod, "plan", boom)

    rep = shard(conn, dom, "t-plan", seeds=seeds, embedder=emb, stamp=Stamp(), runs_dir=tmp_path / "runs",
                ledger_dir=tmp_path / "ledger", out_dir=tmp_path / "bplan", log=lambda *_: None, plan_=pre)
    assert rep.plan.units == pre.units and rep.plan.skips == pre.skips
    assert rep.plan.run_id == "t-plan"                     # run_id stamped onto the supplied plan
    assert sum(rep.signals_written.values()) > 0
