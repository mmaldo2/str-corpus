"""Guards on tools/reread_records.py. The planner is pure (ids + a partition map in, batch
documents out) and the read path runs against a ScriptedProvider over the tiny fixture store,
exactly as tests/test_map_reader_tool.py does. Nothing here calls claude or codex."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from corpus_engine import store
from corpus_engine.reader.model import ModelPin
from corpus_engine.reader.providers.scripted import ScriptedProvider

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("reread_records", ROOT / "tools" / "reread_records.py")
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)

PIN = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-opus-5"})
# One cell of the tiny fixture store with more than 18 live cases, so a pool planned over it
# is two batches of ONE cell - which is what the read then walks.
CELL = ("1900-1930", "Tex.")


class _View:
    def __init__(self, records):
        class S:
            pass
        self.state = S()
        self.state.order = list(records)
        self.state.records = {c: {"relevant": rel} for c, (rel, _cy) in records.items()}
        self.state.in_file = {c: True for c in records}
        self.state.cycles = {c: cy for c, (_rel, cy) in records.items()}
        self.as_of = 42


def _fixture_conn(tmp_path, fixture_db):
    """The tiny fixture store where the tool looks for it: under `ROOT`, which every test
    here monkeypatches to `tmp_path`."""
    db = tmp_path / "data" / "db" / "corpus.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture_db, db)
    return store.connect(db)


def _answer(req):
    """One relevant record per batch, quoted verbatim out of the prompt so the gate keeps it.
    The same scripted reader tests/test_map_reader_tool.py uses."""
    bid = next(line.split()[2] for line in req.user.splitlines() if line.startswith("# Batch "))
    ids = [int(line.split()[2]) for line in req.user.splitlines() if line.startswith("## case_id ")]
    recs = []
    for j, cid in enumerate(ids):
        rel = j == 0
        quote = req.user.split(f"## case_id {cid}", 1)[1].split("### Opinion text\n", 1)[1][200:320]
        recs.append({"case_id": cid, "relevant": rel,
                     "polarity": "favorable" if rel else None,
                     "characterization": "lodging" if rel else None,
                     "quotes": ([{"text": quote, "supports": ["polarity", "characterization"]}]
                                if rel else []),
                     "worker": "reader", "batch_id": bid})
    return json.dumps({"records": recs})


class _FakeCodex(ScriptedProvider):
    """A checker with the one method the driver's preflight asks about."""
    name = "codex-cli"

    def is_available(self) -> bool:
        return True


@pytest.fixture
def wired_reread(tmp_path, fixture_db, monkeypatch):
    """A whole re-read installation under tmp_path: a planned pool, the store, and a scripted
    reader and checker. Mirrors `wired` in tests/test_map_reader_tool.py."""
    conn = _fixture_conn(tmp_path, fixture_db)
    ids = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL AND era_partition = ? "
        "AND jurisdiction = ? ORDER BY case_id LIMIT 20", CELL)]
    assert len(ids) == 20
    pool = tmp_path / "runs" / rr.RUN_ID / "batches"
    for n, b in enumerate(rr.plan_batches(ids, {c: CELL for c in ids}, run_id=rr.RUN_ID), 1):
        rr.write_json(pool / f"batch-{n:03d}.json", b)

    reader = ScriptedProvider(_answer)
    checker = _FakeCodex(_answer)
    monkeypatch.setattr(rr, "ROOT", tmp_path)
    monkeypatch.setattr(rr, "provider_for", lambda cand: (reader, PIN, "scripted, for the test"))
    monkeypatch.setattr(rr, "CodexCliProvider", lambda *a, **kw: checker)
    return {"root": tmp_path, "reader": reader, "checker": checker, "case_ids": ids,
            "manifest": tmp_path / "runs" / rr.RUN_ID / "map-manifest.json"}


def test_the_scope_is_the_relevant_records_of_cycles_one_to_three():
    view = _View({1: (True, "cycle-001"), 2: (False, "cycle-002"),
                  3: (True, "cycle-003"), 4: (True, "cycle-004")})
    assert rr.relevant_case_ids(view) == [1, 3]


def test_batches_are_eighteen_cases_in_case_id_order_within_a_cell():
    ids = list(range(1, 41))
    meta = {c: (("pre-1860", "N.Y.") if c <= 20 else ("1930-1970", "Pa.")) for c in ids}
    batches = rr.plan_batches(ids, meta, run_id="cycles-001-003-reread")
    assert [b["batch_id"] for b in batches] == [f"cycles-001-003-reread-batch-{n:03d}"
                                                for n in (1, 2, 3, 4)]
    assert [len(b["cases"]) for b in batches] == [18, 2, 18, 2]
    assert {(b["era_partition"], b["jurisdiction"]) for b in batches} == {
        ("1930-1970", "Pa."), ("pre-1860", "N.Y.")}
    for b in batches:                         # homogeneous, ordered, no signals to show
        assert all(c["era_partition"] == b["era_partition"] for c in b["cases"])
        assert [c["case_id"] for c in b["cases"]] == sorted(c["case_id"] for c in b["cases"])
        assert all(c["signals"] == [] for c in b["cases"])


def test_a_case_with_no_store_row_is_left_out_of_the_plan():
    batches = rr.plan_batches([1, 2], {1: ("pre-1860", "N.Y.")}, run_id="r")
    assert [c["case_id"] for b in batches for c in b["cases"]] == [1]


def test_the_cells_are_uncapped_and_the_yield_floor_never_fires():
    batches = rr.plan_batches(list(range(1, 41)),
                              {c: ("pre-1860", "N.Y.") for c in range(1, 41)}, run_id="r")
    cells = rr.reread_cells(batches)
    assert len(cells) == 1 and cells[0].uncapped is True
    assert cells[0].cap_batches == len(cells[0].batch_ids) == 3
    # NO_YIELD_STOP is what the runner is given: a relevant-accepted count is never negative,
    # so `got <= threshold` can never be true. Every one of the 693 records is read.
    assert rr.NO_YIELD_STOP == -1


def test_plan_writes_the_case_id_list_and_the_batches_and_buys_nothing(tmp_path, monkeypatch,
                                                                      fixture_db, repo_root):
    """--plan is offline: the ledger view and one SELECT, no provider constructed at all."""
    conn = _fixture_conn(tmp_path, fixture_db)
    # All five out of ONE cell, so the pool is the single unit this asserts. Grouping by cell
    # is the planner's own rule (test_batches_are_eighteen_cases_in_case_id_order_within_a_cell);
    # what this test is about is that `--plan` wrote the pool and the id list at all.
    ids = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL AND era_partition = ? "
        "AND jurisdiction = ? ORDER BY case_id LIMIT 5", CELL)]
    view = _View({c: (True, "cycle-001") for c in ids})
    monkeypatch.setattr(rr, "ROOT", tmp_path)
    monkeypatch.setattr(rr, "open_ledger", lambda **kw: type("L", (), {"view": lambda s: view})())
    monkeypatch.setattr(rr.store, "connect", lambda *a, **kw: conn)
    monkeypatch.setattr(rr, "provider_for", lambda cand: pytest.fail("--plan bought something"))
    assert rr.main(["--plan"]) == 0
    doc = json.loads((tmp_path / "runs" / rr.RUN_ID / "case-ids.json").read_text(encoding="utf-8"))
    assert doc["case_ids"] == sorted(ids) and doc["run_id"] == rr.RUN_ID
    assert doc["cycles"] == ["cycle-001", "cycle-002", "cycle-003"] and doc["as_of"] == 42
    assert len(list((tmp_path / "runs" / rr.RUN_ID / "batches").glob("batch-*.json"))) == 1


def test_the_read_walks_every_planned_batch_and_writes_the_manifest(wired_reread):
    assert rr.main([]) == 0
    doc = json.loads(wired_reread["manifest"].read_text(encoding="utf-8"))
    assert doc["run_id"] == rr.RUN_ID and doc["stop"] == "done"
    assert doc["flags"]["threshold"] == rr.NO_YIELD_STOP
    assert all(c["cap"] == "none" for c in doc["cells"].values())
    assert doc["totals"]["batches_completed"] == doc["totals"]["batches_attempted"]
    assert doc["codebook_id"] == "mapper-v3"


def test_the_resume_line_names_this_tool_and_a_resume_buys_nothing(wired_reread):
    """`MapRunner.resume_command` spells the MAP's tool by default; a re-read that printed
    `tools\\map_reader.py` would hand the operator a line that reads the wrong pool."""
    assert rr.main(["--sample-pct", "0"]) == 0
    doc = json.loads(wired_reread["manifest"].read_text(encoding="utf-8"))
    assert doc["resume_command"] == (
        ".venv\\Scripts\\python tools\\reread_records.py --sample-pct 0")
    assert doc["tool"] == "tools/reread_records.py"
    assert doc["flags"]["order"] == "cell" and doc["flags"]["reread"] is True
    calls = wired_reread["reader"].calls
    assert rr.main(["--sample-pct", "0"]) == 0          # the resume line, run again
    assert wired_reread["reader"].calls == calls        # nothing re-bought


def test_a_read_with_no_planned_pool_says_to_plan_first(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        rr.main([])
    assert "run --plan first" in str(exc.value)
