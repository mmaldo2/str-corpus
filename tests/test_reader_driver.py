import json, shutil, time
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader, agreement, plan_batch_extraction, preflight
from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.sources import StoreCaseSource

PIN = ModelPin("anthropic/claude-haiku-4.5", "anthropic")

def _batches(repo_root, n=3):
    files = sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json"))[:n]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]

def _answer(conn):
    def f(req):
        ids = [int(l.split()[2]) for l in req.user.splitlines() if l.startswith("## case_id ")]
        recs = []
        for cid in ids:
            raw = conn.execute("SELECT raw_text FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
            recs.append({"case_id": cid, "relevant": True, "polarity": "favorable", "characterization": "license", "holding_summary": "h",
                         "quotes": [{"text": raw[300:420], "supports": "polarity"}, {"text": raw[300:420], "supports": "characterization"},
                                    {"text": "not in the opinion at all, a paraphrase", "supports": "holding_summary"}],
                         "worker": "claude", "batch_id": "x"})
        return json.dumps(recs)
    return f

def test_read_gates_caches_budgets_and_reports(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    prov = ScriptedProvider(_answer(conn), cost_per_call=0.5); cache = ResponseCache(tmp_path / "cache")
    plan = plan_batch_extraction(_batches(repo_root), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude")
    (tmp_path / "stab").mkdir()
    out = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom).read(plan)
    assert out.stop.kind == "budget:usd" and len(out.units) == 2 and prov.calls == 2 and out.spend_usd == 1.0
    recs = out.records
    assert recs and all(r["holding_summary"] is None for r in recs) and all(r["polarity"] == "favorable" for r in recs)
    assert all(r["extraction_status"] == "partial" for r in recs) and out.resume_command.endswith("--resume")
    assert out.manifest["codebook_sha"] and out.manifest["model_pin"] == PIN.label
    out2 = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom).read(plan)   # resume: cached units are free
    assert prov.calls == 3 and out2.stop.kind == "done" and len(out2.units) == 3 and sum(u.cache_hit for u in out2.units) == 2

def test_checker_sampling_and_disagreements(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    reader = ScriptedProvider(_answer(conn))
    def flip(req):
        recs = json.loads(_answer(conn)(req))
        for r in recs: r["polarity"] = "adverse"
        return json.dumps(recs)
    checker = ScriptedProvider(flip)
    batches10 = _batches(repo_root, 10)
    plan = plan_batch_extraction(batches10, "mapper-v1", PIN, Budget(), worker="claude",
                                 checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=100)
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom).read(plan)
    assert checker.calls == len(batches10) and out.disagreements and all(d.field == "polarity" for d in out.disagreements)
    plan10 = plan_batch_extraction(batches10, "mapper-v1", PIN, Budget(), worker="claude",
                                   checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=10)
    c2 = ScriptedProvider(flip)
    Reader(ScriptedProvider(_answer(conn)), StoreCaseSource(conn), checker=c2, log=lambda *_: None, domain=dom).read(plan10)
    assert 0 <= c2.calls <= len(batches10)

def test_preflight_refuses_same_family_and_missing_checker(tmp_path, fixture_db, repo_root):
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude", checker_pin=ModelPin("x", "anthropic"))
    s = preflight(plan, cb, None, ScriptedProvider(["[]"]), ScriptedProvider(["[]"]), store_norm_version=None, families={})
    assert s is not None and s.kind == "preflight:families"
    plan2 = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude", checker_pin=ModelPin("codex-cli", "openai"))
    missing = CodexCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    assert preflight(plan2, cb, None, ScriptedProvider(["[]"]), missing, store_norm_version=None, families={}).kind == "preflight:checker_available"

def test_agreement():
    a = [{"case_id": 1, "polarity": "favorable", "relevant": True}, {"case_id": 2, "polarity": None, "relevant": False}]
    b = [{"case_id": 1, "polarity": "adverse", "relevant": True}, {"case_id": 2, "polarity": None, "relevant": False}, {"case_id": 3}]
    assert agreement(a, b, ("polarity", "relevant")) == {"polarity": 0.5, "relevant": 1.0}
