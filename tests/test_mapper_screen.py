"""The optional relevance screen (spec section 7, D10). Built, tested, NOT run this slice.

Four things are pinned: it triggers only where D10 says - a `CellStop` the RUNNER computed
(never one the screen re-derives) that is `yield_floor` with cap remaining, never
`cap_reached` (R2/R9); the cases it marks relevant are re-batched at `SCREEN_BATCH_SIZE` into
`pinned_units()`, ready for the PINNED reader to read through the same driver machinery the
map itself uses, because only the pinned reader's records are ever admitted (R10); its dollar
ceiling is checked BEFORE every paid request, not after - a ceiling checked afterwards is a
receipt, not a ceiling; and `Screen.off()` reproduces the runner's old `NullScreen` shape
exactly, because it is now what `MapRunner` builds in `NullScreen`'s place (R2/R3)."""
import json
import shutil

import pytest

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.mapper.cells import Cell
from corpus_engine.mapper.runner import SCREEN_OFF
from corpus_engine.mapper.screen import (SCREEN_BATCH_SIZE, SCREEN_MAX_USD, Screen,
                                         ScreenBudgetExceeded, rebatch, remaining_batches)
from corpus_engine.mapper.yield_stop import CellProgress, CellStop
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import plan_batch_extraction
from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.sources import StoreCaseSource

CELL = Cell("1930-1970", "N.Y.", tuple(f"b{i}" for i in range(1, 9)), 6, 0.42)


def _progress(n_read, *, yields=0):
    p = CellProgress(CELL.key, CELL.cap_batches)
    for i in range(1, n_read + 1):
        p.add(f"b{i}", yields, True)
    return p


def test_the_defaults_are_the_recorded_ones():
    assert SCREEN_MAX_USD == 5.0 and SCREEN_BATCH_SIZE == 18


def test_the_remainder_is_what_the_cap_allowed_minus_what_was_read():
    p = _progress(3)
    assert remaining_batches(CELL, p) == ("b4", "b5", "b6")
    assert remaining_batches(CELL, _progress(6)) == ()


def test_off_matches_the_runners_null_screen_shape():
    """R2/R3: `Screen.off()` is what `MapRunner` now builds instead of `NullScreen`, and it
    has to answer exactly the same way - a manifest reader must never be able to tell which
    one produced a given run's off block."""
    s = Screen.off()
    assert s.to_json() == SCREEN_OFF
    assert set(SCREEN_OFF) == {"state", "enabled", "max_usd", "screened_units", "hits"}
    assert s.maybe_run(CELL, CellStop("yield_floor", "x"), batch_source=None,
                       progress=_progress(3, yields=0)) is None


def test_it_triggers_only_on_a_yield_floor_stop_with_cap_remaining():
    """R2: the screen is handed the runner's own `CellStop` and never calls
    `progress.should_stop()` itself. R9: the trigger is asserted directly, with a real fake
    `batch_source` behind the one case that should actually read."""
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": []}]}
            for i in range(1, 9)}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _Reader:
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": False, "quotes": []} for cid in unit.case_ids]
            return type("O", (), {"records": recs, "spend_usd": 0.1,
                                  "units": [type("U", (), {"unit_id": unit.id, "cache_hit": False,
                                                           "response": 1})()]})()

    s = Screen(lambda: _Reader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None)

    # yield_floor with cap remaining: the trigger fires and the screen actually reads.
    doc = s.maybe_run(CELL, CellStop("yield_floor", "..."), batch_source=_Src(),
                      progress=_progress(3, yields=0))
    assert doc["state"] == "ran"

    # a cell still paying has no stop at all
    assert s.maybe_run(CELL, None, batch_source=_Src(),
                       progress=_progress(2, yields=5))["state"] == "not_triggered"

    # cap_reached never triggers it, even with a remainder left to screen
    assert s.maybe_run(CELL, CellStop("cap_reached", "..."), batch_source=_Src(),
                       progress=_progress(3, yields=0))["state"] == "not_triggered"

    # a cell at its cap has no remainder
    assert s.maybe_run(CELL, CellStop("yield_floor", "..."), batch_source=_Src(),
                       progress=_progress(6, yields=0))["state"] == "not_triggered"


def test_rebatch_packs_the_hits_at_eighteen_and_keeps_the_cell_metadata():
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i + j, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}
                                for j in range(20)]}
            for i in range(1, 4)}
    ids = [100 * i + j for i in range(1, 4) for j in range(20)][:25]
    out = rebatch(ids, pool, era="1930-1970", jurisdiction="N.Y.", prefix="screen-1930-1970-N.Y.")
    assert [len(b["cases"]) for b in out] == [18, 7]
    assert [b["batch_id"] for b in out] == ["screen-1930-1970-N.Y.-001",
                                            "screen-1930-1970-N.Y.-002"]
    assert all(b["era_partition"] == "1930-1970" and b["jurisdiction"] == "N.Y." for b in out)
    assert [c["case_id"] for b in out for c in b["cases"]] == ids
    assert rebatch([], pool, era="e", jurisdiction="j", prefix="p") == []


def test_the_ceiling_is_checked_before_every_request_and_stops_the_screen(monkeypatch):
    """The measurement tool's rule, kept: a request is refused while the ceiling is already
    reached, rather than issued and then regretted."""
    spend = {"usd": 0.0}
    asked = []

    class _FakeReader:
        def read(self, plan):
            asked.append(plan.units[0].id)
            spend["usd"] += 3.0
            raise AssertionError("the screen must check its ceiling before it reads")

    s = Screen(lambda: _FakeReader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None, spend_probe=lambda: spend["usd"])
    spend["usd"] = 5.0
    with pytest.raises(ScreenBudgetExceeded):
        s._check_budget()
    spend["usd"] = 4.99
    s._check_budget()                     # under the ceiling: allowed
    assert asked == []


def test_a_screen_run_reads_the_remainder_records_the_hits_and_rebatches_them():
    """End to end with a scripted reader: no OpenRouter, no network. Only `relevant` is
    consumed - the screen's polarity and characterization are thrown away, because only the
    pinned reader's records are ever admitted (D10)."""
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i + j, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}
                                for j in range(4)]}
            for i in range(1, 9)}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _Reader:
        """Marks the first case of every screened batch relevant and the rest not."""
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": (k == 0), "polarity": "adverse", "quotes": []}
                    for k, cid in enumerate(unit.case_ids)]
            return _Outcome(unit.id, recs)

    class _Outcome:
        def __init__(self, uid, recs):
            self.records = recs
            self.spend_usd = 0.25
            self.units = [type("U", (), {"unit_id": uid, "cache_hit": False, "response": 1})()]

    s = Screen(lambda: _Reader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None)
    doc = s.maybe_run(CELL, CellStop("yield_floor", "..."), batch_source=_Src(),
                      progress=_progress(3, yields=0))
    assert doc["state"] == "ran"
    assert doc["screened_batches"] == 3 and doc["screened_cases"] == 12
    assert doc["hits"] == 3 and doc["hit_case_ids"] == [400, 500, 600]
    assert doc["rebatched"] == ["screen-1930-1970-N.Y.-001"]
    assert doc["units"] == 3 and doc["spend_usd"] == pytest.approx(0.75)
    assert s.to_json() == {"state": "on", "enabled": True, "max_usd": 5.0, "screened_units": 3,
                           "hits": 3, "spend_usd": pytest.approx(0.75),
                           "hit_case_ids": [400, 500, 600]}
    # the hits are what pinned_units() hands the pinned reader - the same case rows, packed
    # at SCREEN_BATCH_SIZE, ready for plan_batch_extraction.
    units = s.pinned_units()
    assert [u["batch_id"] for u in units] == doc["rebatched"]
    assert [c["case_id"] for c in units[0]["cases"]] == [400, 500, 600]


def test_the_screen_stops_at_its_ceiling_and_says_so():
    pool = {f"b{i}": {"batch_id": f"b{i}", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                      "cases": [{"case_id": 100 * i, "era_partition": "1930-1970",
                                 "jurisdiction": "N.Y.", "signals": [], "rank_score": 0.3}]}
            for i in range(1, 9)}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _Reader:
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": True, "quotes": []} for cid in unit.case_ids]
            return type("O", (), {"records": recs, "spend_usd": 2.6,
                                  "units": [type("U", (), {"unit_id": unit.id, "cache_hit": False,
                                                           "response": 1})()]})()

    s = Screen(lambda: _Reader(), fallback_pin=None, codebook=None, max_usd=5.0,
               log=lambda *_: None)
    doc = s.maybe_run(CELL, CellStop("yield_floor", "..."), batch_source=_Src(),
                      progress=_progress(3, yields=0))
    assert doc["state"] == "ceiling"
    assert doc["units"] == 2 and doc["spend_usd"] == pytest.approx(5.2)
    assert doc["hits"] == 2                       # what it bought is kept


def test_pinned_units_are_read_by_the_pinned_reader_through_the_real_driver(tmp_path, fixture_db,
                                                                            repo_root):
    """R10: `pinned_units()`'s output is not a private shape - it is a normal batch pool that
    `plan_batch_extraction` and `Reader` read exactly as the map itself does. `ScriptedProvider`
    stands in for the pinned subscription model; no network, no CLI. Only what this second,
    pinned read returns is ever admitted - the fallback screen's own `polarity` guess above
    never reaches here at all, because `maybe_run` never carried it past `relevant`."""
    src = json.loads((repo_root / "tests/fixtures/batches/cycle-003-shard-01/batch-001.json")
                     .read_text(encoding="utf-8"))
    cases = [{**c, "era_partition": "1930-1970", "jurisdiction": "N.Y.", "rank_score": 0.5}
             for c in src["cases"][:4]]
    ids = [c["case_id"] for c in cases]
    pool = {"b1": {"batch_id": "b1", "era_partition": "1930-1970", "jurisdiction": "N.Y.",
                  "cases": cases}}

    class _Src:
        def get(self, bid):
            return pool[bid]

    class _FallbackReader:
        """The cheap screen: relevant on the first two cases, irrelevant on the rest."""
        def read(self, plan):
            unit = plan.units[0]
            recs = [{"case_id": cid, "relevant": (k < 2), "polarity": "adverse", "quotes": []}
                    for k, cid in enumerate(unit.case_ids)]
            return type("O", (), {"records": recs, "spend_usd": 0.1,
                                  "units": [type("U", (), {"unit_id": unit.id,
                                                           "cache_hit": False,
                                                           "response": 1})()]})()

    cell = Cell("1930-1970", "N.Y.", ("b1",), 1, 0.5)
    prog = CellProgress(cell.key, cell.cap_batches)
    screen = Screen(lambda: _FallbackReader(), fallback_pin=None, codebook=None, max_usd=5.0,
                    log=lambda *_: None)
    doc = screen.maybe_run(cell, CellStop("yield_floor", "..."), batch_source=_Src(),
                           progress=prog)
    assert doc["hit_case_ids"] == ids[:2]
    units = screen.pinned_units()
    assert [c["case_id"] for c in units[0]["cases"]] == ids[:2]

    db = tmp_path / "c.db"
    shutil.copy(fixture_db, db)
    conn = store.connect(db)
    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    source = StoreCaseSource(conn)

    def pinned_answer(req):
        cids = [int(line.split()[2]) for line in req.user.splitlines()
               if line.startswith("## case_id ")]
        recs = []
        for cid in cids:
            body = req.user.split(f"## case_id {cid}", 1)[1]
            quote = body.split("### Opinion text\n", 1)[1][200:320]
            recs.append({"case_id": cid, "relevant": True, "polarity": "favorable",
                        "characterization": "lodging", "worker": "reader", "batch_id": "pinned",
                        "quotes": [{"text": quote, "supports": ["polarity", "characterization"]}]})
        return json.dumps({"records": recs})

    from corpus_engine.reader.driver import Reader
    pinned_reader = Reader(ScriptedProvider(pinned_answer), source, cache=None,
                           log=lambda *_: None, domain=dom, store_norm_version="v1")
    pin = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
                  {"effort": "low", "cli_model": "claude-opus-5"})
    plan = plan_batch_extraction(units, cb.id, pin, Budget(max_usd=None, max_units=5),
                                 worker="reader")
    out = pinned_reader.read(plan)
    assert out.stop.kind == "done"
    assert sorted(r["case_id"] for r in out.records) == sorted(ids[:2])
    # only the PINNED reader's verdict survives - "favorable", never the screen's "adverse".
    assert all(r["relevant"] is True and r["polarity"] == "favorable" for r in out.records)


def test_the_module_never_imports_a_live_transport_at_call_time():
    """The screen is off this slice. Nothing in it may reach the network when it is not run."""
    src = (__import__("pathlib").Path("corpus_engine/mapper/screen.py")).read_text(encoding="utf-8")
    assert "httpx.get" not in src and "httpx.post" not in src
    assert "def maybe_run" in src and "if self.reader_factory is None" in src
