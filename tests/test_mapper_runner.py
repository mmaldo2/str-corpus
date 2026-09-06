"""The map runner (spec section 6, D6, D9) over a ScriptedProvider - no network, no CLI.

What is being pinned: cells are read in order; a cell stops on the yield rule and the runner
moves to the next one; the per-process caps end the run cleanly with the manifest written; a
resume replays the cache for free; a failed unit costs one batch and never a cell; and the
manifest carries what Task 7 needs to re-derive every record offline."""
import json
import shutil
from pathlib import Path

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.mapper.cells import BatchSource, build_cells, load_batches, select_cells
from corpus_engine.mapper.runner import (MANIFEST_SCHEMA, MAP_RESUME_TOOL, SCREEN_OFF, MapRunner,
                                         NullScreen, RunnerCaps, default_max_units,
                                         relevant_accepted, unit_completed)
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader
from corpus_engine.reader.model import ModelPin
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.sources import StoreCaseSource

PIN = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-opus-5"})
CHECKER = ModelPin("codex-cli", "openai", extra={"cli_model": "gpt-5.6-terra"})


def _pool(tmp_path, repo_root, spec):
    """Rewrite the committed cycle-003 fixture batches as a cycle-004-shaped pool.

    spec: {(era, jurisdiction): n_batches}. Real case ids come from the fixture batches so
    StoreCaseSource can fetch their text out of tests/fixtures/corpus-tiny.db."""
    src = sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json"))
    pool = tmp_path / "batches"
    pool.mkdir()
    n, i = 0, 0
    for (era, jur), count in spec.items():
        for _k in range(count):
            base = json.loads(src[i % len(src)].read_text(encoding="utf-8"))
            i += 1
            n += 1
            cases = [{**c, "era_partition": era, "jurisdiction": jur,
                      "rank_score": round(1.0 - 0.01 * n, 4)} for c in base["cases"][:2]]
            b = {"batch_id": f"cycle-004-shard-01-batch-{n:03d}", "ranker_id": "classifier:v1",
                 "era_partition": era, "jurisdiction": jur, "cases": cases}
            (pool / f"batch-{n:03d}.json").write_bytes(json.dumps(b, indent=1).encode("utf-8"))
    return pool


def _answer(relevant_per_batch):
    """A provider whose relevance verdict is chosen per batch_id, so a cell's yield curve is
    scripted exactly. Every relevant record carries a verbatim quote so the gate keeps it."""
    def f(req):
        bid = next(line.split()[1] for line in req.user.splitlines() if line.startswith("# Batch "))
        want = relevant_per_batch(bid)
        ids = [int(line.split()[2]) for line in req.user.splitlines()
               if line.startswith("## case_id ")]
        recs = []
        for j, cid in enumerate(ids):
            rel = j < want
            body = req.user.split(f"## case_id {cid}", 1)[1]
            quote = body.split("### Opinion text\n", 1)[1][200:320]
            recs.append({"case_id": cid, "relevant": rel,
                         "polarity": "favorable" if rel else None,
                         "characterization": "lodging" if rel else None,
                         "under_thirty_days": "yes" if rel else None,
                         "quotes": ([{"text": quote,
                                      "supports": ["polarity", "characterization",
                                                   "under_thirty_days"]}] if rel else []),
                         "worker": "reader", "batch_id": bid})
        return json.dumps({"records": recs})
    return f


def _runner(tmp_path, fixture_db, pool, *, answer, caps, cells=None, sample_pct=0,
            checker=None, calls=None, **kw):
    db = tmp_path / "c.db"
    if not db.exists():
        shutil.copy(fixture_db, db)
    conn = store.connect(db)
    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    cache = ResponseCache(tmp_path / "cache")
    provider = ScriptedProvider(answer)
    if calls is not None:
        calls.append(provider)
    source = StoreCaseSource(conn)

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=lambda *_: None,
                      domain=dom, store_norm_version="v1")

    built = cells if cells is not None else build_cells(load_batches(pool),
                                                        era_depth={"pre-1860": 8, "1930-1970": 8})
    return MapRunner(factory, built, batch_source=BatchSource(pool), cache=cache,
                     manifest_path=tmp_path / "map-manifest.json", caps=caps,
                     log=lambda *_: None, codebook=cb, pin=PIN,
                     checker_pin=(CHECKER if checker is not None else None),
                     sample_pct=sample_pct, run_id="cycle-004-shard-01",
                     extractions_dir=tmp_path / "extractions", **kw)


def test_default_max_units_is_the_capped_batches_plus_a_tenth(tmp_path, repo_root):
    pool = _pool(tmp_path, repo_root, {("pre-1860", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"pre-1860": 4})
    assert sum(c.cap_batches for c in cells) == 4
    assert default_max_units(cells) == 5          # ceil(4 * 1.1)


def test_a_cell_stops_on_the_yield_rule_and_the_runner_moves_to_the_next(tmp_path, fixture_db,
                                                                         repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6, ("pre-1860", "Pa."): 3})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 0),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    ny = out.manifest["cells"]["1930-1970|N.Y."]
    assert ny["batches_completed"] == 3 and ny["stop"]["kind"] == "yield_floor"
    assert [e["relevant_accepted"] for e in ny["yield_series"]] == [0, 0, 0]
    pa = out.manifest["cells"]["pre-1860|Pa."]
    assert pa["batches_completed"] == 3 and pa["stop"]["kind"] in ("yield_floor", "cap_reached")
    assert out.manifest["cell_order"] == list(out.manifest["cells"])
    assert out.manifest["totals"]["relevant_accepted"] == 0


def test_a_paying_cell_is_read_to_its_cap(tmp_path, fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"1930-1970": 4})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), cells=cells)
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["cap_batches"] == 4 and cell["batches_completed"] == 4
    assert cell["stop"]["kind"] == "cap_reached"
    assert cell["relevant_accepted"] == 8 and cell["irrelevant_accepted"] == 0


def test_the_unit_cap_ends_the_run_cleanly_and_the_manifest_is_still_written(tmp_path,
                                                                            fixture_db,
                                                                            repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=2, max_wall_seconds=1e6))
    out = r.run()
    assert out.stop == "budget:units" and out.units == 2
    doc = json.loads(Path(out.manifest_path).read_text(encoding="utf-8"))
    assert doc["schema"] == MANIFEST_SCHEMA and doc["stop"] == "budget:units"
    assert doc["resume_command"] == f".venv\\Scripts\\python {MAP_RESUME_TOOL}"
    assert doc["totals"]["units"] == 2


def test_a_resume_replays_the_cache_for_free_and_finishes_the_cell(tmp_path, fixture_db,
                                                                   repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    cells = build_cells(load_batches(pool), era_depth={"1930-1970": 4})
    calls = []
    first = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                    caps=RunnerCaps(max_units=2, max_wall_seconds=1e6), cells=cells, calls=calls)
    first.run()
    assert calls[0].calls == 2
    second = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                     caps=RunnerCaps(max_units=10, max_wall_seconds=1e6), cells=cells, calls=calls)
    out = second.run()
    assert calls[1].calls == 2                       # only the two units not already bought
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["batches_completed"] == 4 and cell["stop"]["kind"] == "cap_reached"


def test_a_failed_unit_costs_one_batch_and_never_the_cell(tmp_path, fixture_db, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})
    bad = "cycle-004-shard-01-batch-002"

    def answer(req):
        if f"# Batch {bad}" in req.user:
            raise RuntimeError("provider exploded")
        return _answer(lambda bid: 2)(req)

    r = _runner(tmp_path, fixture_db, pool, answer=answer,
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert cell["failed_units"] == [bad]
    assert bad not in [e["batch_id"] for e in cell["yield_series"]]
    assert cell["failures"][0]["status"] == "failed" and "exploded" in cell["failures"][0]["error"]
    assert out.manifest["totals"]["failed_units"] == 1
    # R11: a reader request that raised is a unit that was spent, not a free retry.
    assert out.units == cell["batches_attempted"]


def test_the_manifest_records_the_cache_key_of_every_unit_it_bought(tmp_path, fixture_db,
                                                                    repo_root):
    """Task 7 re-parses and re-gates from the cache rather than from an extraction file, so
    the key composition has to be recorded, not recomputed from today's constants."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 3})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    keys = out.manifest["cells"]["1930-1970|N.Y."]["cache_keys"]
    assert keys and all((Path(tmp_path / "cache") / f"{k}.json").exists() for k in keys.values())
    assert out.manifest["codebook_sha"] and out.manifest["schema_sha"]
    assert out.manifest["max_tokens"] == 64000 and out.manifest["effort"] == "low"
    assert out.manifest["reader_pin"] == PIN.label
    assert out.manifest["store_norm_version"] == "v1"


def test_extractions_are_written_per_batch_and_are_derived_not_authoritative(tmp_path,
                                                                             fixture_db,
                                                                             repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    files = sorted((tmp_path / "extractions").glob("*.json"))
    assert [p.stem for p in files] == ["cycle-004-shard-01-batch-001",
                                       "cycle-004-shard-01-batch-002"]
    recs = json.loads(files[0].read_text(encoding="utf-8"))["records"]
    assert recs and recs[0]["extraction_status"] in ("ok", "partial")
    assert out.manifest["cells"]["1930-1970|N.Y."]["records"] == 4


def test_the_checker_sample_and_its_disagreements_reach_the_manifest(tmp_path, fixture_db,
                                                                     repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})

    def flip(req):
        recs = json.loads(_answer(lambda bid: 2)(req))["records"]
        for rec in recs:
            rec["polarity"] = "adverse"
        return json.dumps({"records": recs})

    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 2),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), sample_pct=100,
                checker=ScriptedProvider(flip))
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert len(cell["checker_sampled"]) == cell["batches_attempted"]
    assert all(s == "ok" for s in cell["checker_status"].values())
    fields = {d["field"] for d in cell["checker_disagreements"]}
    assert fields == {"polarity"}
    assert out.manifest["sample_pct"] == 100
    assert out.manifest["totals"]["checker_disagreements"] == len(cell["checker_disagreements"])
    # R6: every unit carries its own checker block, and R11 counts checker calls apart from
    # the reader units the --max-units ceiling governs.
    assert all(u["checker"]["sampled"] and u["checker"]["status"] == "ok"
               for u in cell["units"])
    assert out.manifest["totals"]["checker_units"] == 2
    assert out.manifest["totals"]["units"] == 2


def test_an_unsampled_unit_says_so_rather_than_going_silent(tmp_path, fixture_db, repo_root):
    """"not sampled" and "sampled and agreed" are different facts about a unit; a manifest
    that recorded neither would let a run with a broken checker read as a clean one (R6)."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    cell = out.manifest["cells"]["1930-1970|N.Y."]
    assert [u["checker"] for u in cell["units"]] == [{"sampled": False, "status": "none",
                                                      "disagreements": []}] * 2
    assert cell["checker_sampled"] == [] and cell["checker_status"] == {}
    assert out.manifest["totals"]["checker_units"] == 0


def test_the_screen_is_off_by_default_and_says_so_in_the_shape_task_6_keeps(tmp_path,
                                                                            fixture_db,
                                                                            repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6))
    out = r.run()
    assert out.manifest["screen"] == SCREEN_OFF
    assert set(SCREEN_OFF) == {"state", "enabled", "max_usd", "screened_units", "hits"}
    assert out.manifest["cells"]["1930-1970|N.Y."]["screen"] == {"state": "off"}
    assert NullScreen().maybe_run(object(), None) is None


def test_a_screen_is_handed_the_cells_own_stop_and_never_re_derives_it(tmp_path, fixture_db,
                                                                       repo_root):
    """R2/R3: `should_stop` is the yield module's to answer. The runner computes the CellStop
    and passes it in, so Task 6's screen cannot drift into a second copy of the rule."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})

    class Spy:
        def __init__(self):
            self.seen = []

        def maybe_run(self, cell, stop, **kw):
            self.seen.append((cell.key, None if stop is None else stop.kind))
            return {"state": "considered", "hits": 0}

        def to_json(self):
            return {"state": "considered", "enabled": True, "max_usd": 1.0,
                    "screened_units": 0, "hits": 0}

    spy = Spy()
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 0),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), screen=spy)
    out = r.run()
    assert spy.seen == [("1930-1970|N.Y.", "yield_floor")]
    assert out.manifest["cells"]["1930-1970|N.Y."]["screen"] == {"state": "considered", "hits": 0}
    assert out.manifest["screen"]["state"] == "considered"


def test_the_manifest_is_written_even_when_the_run_raises(tmp_path, fixture_db, repo_root):
    """The manifest is the record of what was BOUGHT. A defect that escapes the driver must
    not take the record of the units already paid for with it (spec section 11)."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 6})

    class Exploding:
        def maybe_run(self, cell, stop, **kw):
            raise RuntimeError("screen defect")

        def to_json(self):
            return dict(SCREEN_OFF)

    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 0),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6), screen=Exploding())
    try:
        r.run()
        raise AssertionError("the defect should have propagated")
    except RuntimeError as exc:
        assert "screen defect" in str(exc)
    doc = json.loads((tmp_path / "map-manifest.json").read_text(encoding="utf-8"))
    assert doc["cells"]["1930-1970|N.Y."]["batches_completed"] == 3
    assert doc["totals"]["units"] == 3


def test_helpers_agree_with_the_drivers_own_vocabulary(tmp_path, fixture_db, repo_root):
    from corpus_engine.reader.model import RecordResult, UnitResult
    ok = RecordResult(1, {"relevant": True, "extraction_status": "ok"}, "ok", 0, ())
    part = RecordResult(2, {"relevant": True, "extraction_status": "partial"}, "partial", 1, ())
    irr = RecordResult(3, {"relevant": False, "extraction_status": "ok"}, "ok", 0, ())
    miss = RecordResult(4, {"relevant": None, "extraction_status": "missing"}, "missing", 0, ())
    u = UnitResult("b1", "ok", (ok, part, irr, miss), None, False)
    assert relevant_accepted(u) == 2 and unit_completed(u) is True
    assert unit_completed(UnitResult("b2", "failed", (miss,), None, False)) is False
    assert unit_completed(UnitResult("b3", "partial_parse", (ok, miss), None, False)) is True
    assert unit_completed(UnitResult("b4", "partial_parse", (miss,), None, False)) is False


def test_the_cells_flag_limits_the_run_without_changing_the_order(tmp_path, repo_root):
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2, ("pre-1860", "Pa."): 2})
    cells = build_cells(load_batches(pool), era_depth={"pre-1860": 2, "1930-1970": 2})
    picked = select_cells(cells, "pre-1860|Pa.")
    assert [c.key for c in picked] == ["pre-1860|Pa."]


def test_the_resume_command_is_the_same_invocation(tmp_path, fixture_db, repo_root):
    """Resuming a map is re-running the command that started it (D9); a resume line that
    dropped the flags would read a different set of cells under different caps."""
    pool = _pool(tmp_path, repo_root, {("1930-1970", "N.Y."): 2})
    r = _runner(tmp_path, fixture_db, pool, answer=_answer(lambda bid: 1),
                caps=RunnerCaps(max_units=50, max_wall_seconds=1e6),
                resume_args=["--cells", "1930-1970|N.Y.", "--max-units", "40"])
    out = r.run()
    assert out.resume_command == (f'.venv\\Scripts\\python {MAP_RESUME_TOOL} '
                                  f'--cells "1930-1970|N.Y." --max-units 40')
