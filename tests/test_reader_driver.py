import inspect, json, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import (Reader, agreement, plan_batch_extraction, plan_judgment, plan_reread,
                                         preflight, resume_command, resume_note)
from corpus_engine.reader.model import Budget, ModelPin, ReaderError, Unit
from corpus_engine.reader.parse import split_unit
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
    out = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:usd" and len(out.units) == 2 and prov.calls == 2 and out.spend_usd == 1.0
    recs = out.records
    assert recs and all(r["holding_summary"] is None for r in recs) and all(r["polarity"] == "favorable" for r in recs)
    assert all(r["extraction_status"] == "partial" for r in recs)
    assert out.resume_command == ""          # this plan names no tool; the manifest note says why
    assert out.manifest["codebook_sha"] and out.manifest["model_pin"] == PIN.label
    out2 = Reader(prov, StoreCaseSource(conn), cache=cache, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)   # resume: cached units are free
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
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert checker.calls == len(batches10) and out.disagreements and all(d.field == "polarity" for d in out.disagreements)
    plan10 = plan_batch_extraction(batches10, "mapper-v1", PIN, Budget(), worker="claude",
                                   checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=10)
    c2 = ScriptedProvider(flip)
    Reader(ScriptedProvider(_answer(conn)), StoreCaseSource(conn), checker=c2, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan10)
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


def test_budget_units_stop(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    prov = ScriptedProvider(_answer(conn))
    plan = plan_batch_extraction(_batches(repo_root, 3), "mapper-v1", PIN, Budget(max_units=1), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:units" and prov.calls == 1 and len(out.units) == 1


def test_budget_wall_stop(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    prov = ScriptedProvider(_answer(conn))
    plan = plan_batch_extraction(_batches(repo_root, 3), "mapper-v1", PIN, Budget(max_wall_seconds=5), worker="claude")
    seq = iter([0, 0, 10, 10])
    clock = lambda: next(seq, 10)
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, clock=clock, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:wall" and prov.calls == 1 and len(out.units) == 1


def test_split_retry_both_halves_parse(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    ans = _answer(conn); calls = {"n": 0}
    def f(req):
        calls["n"] += 1
        return "not json at all" if calls["n"] == 1 else ans(req)
    prov = ScriptedProvider(f)
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert prov.calls == 3
    u = out.units[0]
    assert u.status == "ok" and len(u.records) == len(plan.units[0].case_ids)
    assert all(r.gate_status != "missing" for r in u.records)
    assert u.retried and out.manifest["units_retried_after_split"] == 1   # "ok", but it took two asks (m5)


def test_split_retry_second_half_garbage(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    ans = _answer(conn); calls = {"n": 0}
    def f(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        if calls["n"] == 2:
            return ans(req)
        return "still not json"
    prov = ScriptedProvider(f)
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert prov.calls == 3
    u = out.units[0]
    assert u.status == "partial_parse" and len(u.records) == len(plan.units[0].case_ids)
    stubs = [r for r in u.records if r.gate_status == "missing"]
    assert stubs and all(r.record["gate_notes"] == "parse failed (split half)" for r in stubs)
    assert any(r.gate_status != "missing" for r in u.records)


def test_checker_reader_error_does_not_duplicate_unit(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    reader = ScriptedProvider(_answer(conn))
    class BrokenChecker:
        name = "broken-checker"
        def __init__(self):
            self.calls = 0
        def complete(self, req):
            self.calls += 1
            raise ReaderError("checker exploded")
    checker = BrokenChecker()
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude",
                                 checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=100)
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    ids = [u.unit_id for u in out.units]
    assert len(ids) == len(set(ids)) == 1
    u = out.units[0]
    assert u.status == "ok" and u.checker is not None and u.checker.startswith("failed:")
    assert out.failed_units == []


def test_checker_unparsed_response(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    reader = ScriptedProvider(_answer(conn))
    checker = ScriptedProvider(["not json"])
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude",
                                 checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=100)
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.units[0].checker == "unparsed"
    assert out.disagreements == []
    assert out.manifest["checker_unparsed"] == 1


def test_budget_rechecked_inside_split(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    prov = ScriptedProvider(lambda req: "still not json", cost_per_call=0.5)
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:usd"
    assert prov.calls == 2                       # primary + first half; second half's pre-check trips
    assert out.spend_usd <= 1.0 + 0.5             # never overspends by more than one request


def test_preflight_budget_unpriced_for_codex_cli_reader(repo_root):
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude")
    prov = CodexCliProvider("m")
    s = preflight(plan, cb, None, prov, None, store_norm_version=None, families={})
    assert s is not None and s.kind == "preflight:budget_unpriced"


def test_budget_stop_mid_split_keeps_parsed_half(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    ans = _answer(conn); calls = {"n": 0}
    def f(req):
        calls["n"] += 1
        return "not json at all" if calls["n"] == 1 else ans(req)   # primary garbage forces split; first half parses for real
    prov = ScriptedProvider(f, cost_per_call=0.5)
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude")
    unit = plan.units[0]; first_half, second_half = split_unit(unit)
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:usd" and prov.calls == 2         # primary + first half; second half's pre-check trips
    assert len(out.units) == 1
    u = out.units[0]
    assert u.status == "partial_parse"
    real = [r for r in u.records if r.case_id in set(first_half.case_ids)]
    stubs = [r for r in u.records if r.case_id in set(second_half.case_ids)]
    assert len(real) == len(first_half.case_ids)
    assert all(r.gate_status != "missing" and r.record.get("polarity") == "favorable" for r in real)
    assert len(stubs) == len(second_half.case_ids)
    assert all(r.gate_status == "missing" and r.record["gate_notes"] == "budget stop before split half" for r in stubs)


def test_budget_trips_exactly_at_checker_ask(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    reader = ScriptedProvider(_answer(conn), cost_per_call=1.0)
    checker = ScriptedProvider(_answer(conn))
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(max_usd=1.0), worker="claude",
                                 checker_pin=ModelPin("scripted-checker", "openai"), sample_pct=100)
    out = Reader(reader, StoreCaseSource(conn), checker=checker, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "budget:usd"
    ids = [u.unit_id for u in out.units]
    assert len(ids) == len(set(ids)) == 1
    u = out.units[0]
    assert u.status == "ok" and u.checker == "failed:budget"
    assert checker.calls == 0


def test_a_non_reader_exception_costs_one_unit_not_the_whole_read(tmp_path, fixture_db, repo_root):
    """I1. The unit loop caught only _BudgetStop and ReaderError, so any other exception
    escaped read() and took every paid response with it. That is how a TypeError in the
    gate killed a whole candidate mid-measurement and had it recorded as a failed model."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    ans = _answer(conn); calls = {"n": 0}
    def f(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("unhashable type: 'list'")      # not a ReaderError
        return ans(req)
    prov = ScriptedProvider(f)
    plan = plan_batch_extraction(_batches(repo_root, 3), "mapper-v1", PIN, Budget(), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "done" and len(out.units) == 3
    bad = out.units[0]
    assert bad.status == "failed" and bad.error.startswith("failed:TypeError: unhashable type")
    assert len(bad.records) == len(plan.units[0].case_ids)
    assert all(r.gate_status == "missing" and r.record["gate_notes"].startswith("unit failed: TypeError")
               for r in bad.records)
    assert [u.status for u in out.units[1:]] == ["ok", "ok"]          # the rest of the plan still ran


def test_a_malformed_cache_entry_costs_one_unit_not_the_whole_read(tmp_path, fixture_db, repo_root):
    """I1, the live instance of it: ResponseCache.get did Response(**json.loads(...)), so
    one truncated cache file raised TypeError/JSONDecodeError out of _ask and ended the run."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    cache = ResponseCache(tmp_path / "cache")
    plan = plan_batch_extraction(_batches(repo_root, 3), "mapper-v1", PIN, Budget(), worker="claude")
    src = StoreCaseSource(conn)
    Reader(ScriptedProvider(_answer(conn)), src, cache=cache, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    sorted(cache.dir.glob("*.json"))[0].write_text('{"text": "truncated', encoding="utf-8")
    prov = ScriptedProvider(_answer(conn))
    out = Reader(prov, src, cache=cache, log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "done" and len(out.units) == 3
    failed = [u for u in out.units if u.status == "failed"]
    assert len(failed) == 1 and "malformed cache entry" in failed[0].error
    assert sum(1 for u in out.units if u.cache_hit) == 2 and prov.calls == 0


def test_provider_error_on_a_split_half_keeps_the_half_already_paid_for(tmp_path, fixture_db, repo_root):
    """I2. The budget-stop path was fixed to preserve the first half's parsed records; the
    provider-error path still stubbed every case in the unit, discarding a bought response."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    ans = _answer(conn); calls = {"n": 0}
    def f(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"                        # forces the split
        if calls["n"] == 2:
            return ans(req)                                 # first half: bought, parsed, real
        raise ReaderError("provider gave up on the second half")
    prov = ScriptedProvider(f)
    plan = plan_batch_extraction(_batches(repo_root, 2), "mapper-v1", PIN, Budget(), worker="claude")
    unit = plan.units[0]; first_half, second_half = split_unit(unit)
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert out.stop.kind == "done" and len(out.units) == 2      # the read continues to the next unit
    u = out.units[0]
    assert u.status == "partial_parse" and u.retried and "gave up on the second half" in u.error
    real = [r for r in u.records if r.case_id in set(first_half.case_ids)]
    stubs = [r for r in u.records if r.case_id in set(second_half.case_ids)]
    assert len(real) == len(first_half.case_ids) and len(stubs) == len(second_half.case_ids)
    assert all(r.gate_status != "missing" and r.record.get("polarity") == "favorable" for r in real)
    assert all(r.record["gate_notes"] == "failed on split half (ReaderError)" for r in stubs)
    assert [r.case_id for r in u.records] == list(unit.case_ids)


def test_a_defect_in_one_split_half_keeps_the_half_already_paid_for(tmp_path, fixture_db, repo_root):
    """N6. The unit loop catches Exception (an engine defect costs one unit, not the run),
    but the split loop caught only ReaderError and _BudgetStop - so a TypeError raised while
    the second half was being fetched threw away the first half, which had been bought."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude")
    unit = plan.units[0]
    first, _second = split_unit(unit)
    answer = _answer(conn)
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return "this will not parse"
        if calls["n"] == 2:
            return answer(req)
        raise TypeError("engine defect on the second half")

    out = Reader(ScriptedProvider(flaky), StoreCaseSource(conn), log=lambda *_: None, domain=dom,
                 store_norm_version="v1").read(plan)
    u = out.units[0]
    assert u.status == "partial_parse" and u.retried is True and "TypeError" in u.error
    kept = [r for r in u.records if r.record.get("extraction_status") != "missing"]
    assert sorted(r.case_id for r in kept) == sorted(first.case_ids)
    assert out.stop.kind == "done"                       # the run continues


def test_a_one_case_unit_is_never_split_into_an_empty_half(tmp_path, fixture_db, repo_root):
    """I4. split_unit((1,)) yields ((1,), ()), and the driver then bought a request for the
    empty half: no cases rendered, and parse_records over no ids succeeds vacuously, so the
    nothing came back as a success. plan_reread and plan_judgment emit only one-case units."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    cid = conn.execute("SELECT case_id FROM cases ORDER BY case_id LIMIT 1").fetchone()[0]
    prov = ScriptedProvider(lambda req: "not json at all")
    plan = plan_reread([{"case_id": cid, "era_partition": "e", "jurisdiction": "j"}],
                       "mapper-v1", PIN, Budget(), worker="claude")
    out = Reader(prov, StoreCaseSource(conn), log=lambda *_: None, domain=dom, store_norm_version="v1").read(plan)
    assert prov.calls == 1                                   # the primary ask only; no empty half bought
    u = out.units[0]
    assert u.status == "parse_failed" and not u.retried and "never split" in u.error
    assert [r.case_id for r in u.records] == [cid] and u.records[0].gate_status == "missing"


def test_resume_command_names_a_program_that_exists(repo_root):
    """I9. Every outcome used to carry `pipeline\\read.py --plan <run>\\plan.json --resume`:
    no such script, no such flag, and nothing ever wrote that plan file."""
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v1", PIN, Budget(), worker="claude",
                                 resume_tool="tools\\measure_reader.py")
    cmd = resume_command(plan)
    program = cmd.split()[1]
    assert (repo_root / program.replace("\\", "/")).exists(), cmd
    assert f"--only {PIN.model_id}" in cmd
    assert "--only" in (repo_root / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    # a plan kind with no runner yet gets no line at all rather than one that cannot run
    judge = plan_judgment([1], "Did the court reach the merits?", "mapper-v1", PIN, Budget(), worker="claude")
    assert resume_command(judge) == ""


def test_resume_command_names_the_tool_that_built_the_plan():
    """I9 again, one step further: the line has to name a program that exists AND that
    actually built this plan. A plan nothing has a runner for gets no command at all."""
    plan = plan_batch_extraction([], "mapper-v1", PIN, Budget(), worker="reader",
                                 resume_tool="tools\\measure_reader.py")
    assert resume_command(plan) == f".venv\\Scripts\\python tools\\measure_reader.py --only {PIN.model_id}"
    bare = plan_batch_extraction([], "mapper-v1", PIN, Budget(), worker="reader")
    assert resume_command(bare) == ""
    assert "no runner" in resume_note(bare)
    assert plan_judgment([1], "q?", "mapper-v1", PIN, Budget(), worker="reader").resume_tool == ""


def test_cache_key_composition_is_pinned(tmp_path):
    """I11. Spec section 8 asks for a test that the key changes when the codebook changes;
    there was none, in either direction, which is how the omissions below went unnoticed."""
    sha_a, sha_b = "a" * 64, "b" * 64
    pin = ModelPin("m", "fam")
    unit = Unit("u1", (1, 2), {"batch_id": "u1"})
    key = ResponseCache.key(sha_a, pin, unit, "prompt")
    assert key != ResponseCache.key(sha_b, pin, unit, "prompt")                          # codebook sha
    assert key != ResponseCache.key(sha_a, ModelPin("m2", "fam"), unit, "prompt")        # model id
    assert key != ResponseCache.key(sha_a, ModelPin("m", "fam", "prov", "fp8"), unit, "prompt")   # pin label
    assert key != ResponseCache.key(sha_a, pin, Unit("u2", (1, 2), {}), "prompt")        # unit id
    assert key != ResponseCache.key(sha_a, pin, Unit("u1", (1, 3), {}), "prompt")        # case ids
    assert key != ResponseCache.key(sha_a, pin, unit, "other prompt")                    # rendered prompt
    assert key == ResponseCache.key(sha_a, pin, Unit("u1", (2, 1), {}), "prompt")        # ids are sorted
    # Stage 3B slice 1 closed both omissions from `key`'s signature - not from `pin.extra`
    # automatically, but by adding `schema_sha`/`max_tokens`/`effort` keyword arguments the
    # driver now fills from `schema_sha(plan.json_schema)` and `effort_of(pin)`. A caller
    # that omits them (as this test still does) gets the same key as before the widening,
    # which is why the assertion below is unchanged: `pin.extra` alone never touched the
    # key, in 3A or now.
    effort_high = ModelPin("m", "fam", extra={"reasoning": {"effort": "high"}})
    assert ResponseCache.key(sha_a, effort_high, unit, "prompt") == key
    assert list(inspect.signature(ResponseCache.key).parameters) == [
        "codebook_sha", "pin", "unit", "prompt", "schema_sha", "max_tokens", "effort"]


def test_store_norm_version_is_required_so_the_guard_cannot_be_left_inert(tmp_path, fixture_db):
    """I10. It defaulted to None, and None short-circuits pre-flight check (1) - the check
    that stops a read of texts the codebook was never validated against. A caller now has to
    say what the store holds, even if what it says is None."""
    import pytest
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    with pytest.raises(TypeError, match="store_norm_version"):
        Reader(ScriptedProvider(["[]"]), StoreCaseSource(conn))
    r = Reader(ScriptedProvider(["[]"]), StoreCaseSource(conn), store_norm_version="v1")
    assert r.norm == "v1"


def test_preflight_refuses_a_store_at_the_wrong_norm_version(repo_root):
    """The check exists but was never exercised, and its only real caller left it unarmed
    (I10). mapper-v2 is the codebook that carries the `validated_norm_version` header."""
    dom = load_domain(); cb = load_codebook(dom, "mapper-v2")
    plan = plan_batch_extraction(_batches(repo_root, 1), "mapper-v2", PIN, Budget(), worker="claude")
    prov = ScriptedProvider(["[]"])
    assert cb.validated_norm_version == "v1"
    s = preflight(plan, cb, None, prov, None, store_norm_version="v2", families={})
    assert s is not None and s.kind == "preflight:norm_version" and "v1 != v2" in s.detail
    assert preflight(plan, cb, None, prov, None, store_norm_version="v1", families={}) is None
    # unpassed, the check short-circuits - which is exactly what the tool used to do
    assert preflight(plan, cb, None, prov, None, store_norm_version=None, families={}) is None
