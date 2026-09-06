"""Guards on tools/map_reader.py: the command that spends the cycle-004 map budget.

Every test here runs `main()` end to end over fakes - a ScriptedProvider for the reader, a
scripted stand-in for the Codex checker, a copy of the tiny fixture store, and a pool written
into a temporary run directory. Nothing in this file touches the `claude` CLI, OpenRouter, the
live store or data/reader/cache; that is the point of it. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
import json
import math
import shutil
from pathlib import Path

import pytest

from corpus_engine.domain import load_domain
from corpus_engine.mapper.cells import DEPTH_COLUMNS
from corpus_engine.mapper.runner import SCREEN_OFF
from corpus_engine.reader.model import ModelPin
from corpus_engine.reader.providers import openrouter as openrouter_mod
from corpus_engine.reader.providers.scripted import ScriptedProvider

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("map_reader", ROOT / "tools" / "map_reader.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)

RUN_ID = "cycle-004-shard-01"
PIN = ModelPin("claude-cli/claude-opus-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-opus-5"})


def _answer(req):
    """One relevant record per batch, quoted verbatim out of the prompt so the gate keeps it."""
    # `# Batch <id> (<era> x <jurisdiction>)`: index 2, because index 1 is the word "Batch".
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
def wired(tmp_path, fixture_db, repo_root, monkeypatch):
    """A whole map installation under tmp_path: pool, store, cache, and a scripted reader."""
    src = sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01").glob("batch-*.json"))
    pool = tmp_path / "runs" / RUN_ID / "batches"
    pool.mkdir(parents=True)
    for n, p in enumerate(src[:4], start=1):
        base = json.loads(p.read_text(encoding="utf-8"))
        era, jur = ("1930-1970", "N.Y.") if n <= 2 else ("pre-1860", "Pa.")
        cases = [{**c, "era_partition": era, "jurisdiction": jur,
                  "rank_score": round(1.0 - 0.01 * n, 4)} for c in base["cases"][:2]]
        (pool / f"batch-{n:03d}.json").write_bytes(json.dumps(
            {"batch_id": f"{RUN_ID}-batch-{n:03d}", "ranker_id": "classifier:v1",
             "era_partition": era, "jurisdiction": jur, "cases": cases}, indent=1).encode("utf-8"))
    db = tmp_path / "data" / "db" / "corpus.db"
    db.parent.mkdir(parents=True)
    shutil.copy(fixture_db, db)

    reader = ScriptedProvider(_answer)
    checker = _FakeCodex(_answer)
    monkeypatch.setattr(mr, "ROOT", tmp_path)
    monkeypatch.setattr(mr, "provider_for", lambda cand: (reader, PIN, "scripted, for the test"))
    monkeypatch.setattr(mr, "CodexCliProvider", lambda *a, **kw: checker)
    return {"root": tmp_path, "reader": reader, "checker": checker,
            "manifest": tmp_path / "runs" / RUN_ID / "map-manifest.json"}


def _manifest(wired) -> dict:
    return json.loads(Path(wired["manifest"]).read_text(encoding="utf-8"))


def test_the_parser_carries_every_flag_the_map_is_run_with():
    """The flags are the interface Task 8's run notes are written against; a rename here is
    a rename of the command a human is told to type."""
    ap = mr.build_parser()
    flags = {a for action in ap._actions for a in action.option_strings}
    assert {"--run-id", "--cells", "--dry-run-batches", "--max-units", "--max-wall-seconds",
            "--window", "--threshold", "--depth-column", "--sample-pct", "--screen",
            "--screen-max-usd"} <= flags
    a = ap.parse_args([])
    assert (a.run_id, a.window, a.threshold, a.depth_column) == ("cycle-004-shard-01", 3, 2, "0.25")
    assert a.max_wall_seconds == 21600 and a.max_units is None and a.screen is False


def test_a_full_run_reads_every_cell_and_writes_the_tracked_manifest(wired, capsys):
    assert mr.main(["--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["schema"] == "map-manifest-v1" and doc["run_id"] == RUN_ID
    assert doc["cycle"] == "cycle-004" and doc["stop"] == "done"
    assert doc["cell_order"] == ["1930-1970|N.Y.", "pre-1860|Pa."]
    assert doc["totals"]["units"] == 4 and doc["process"]["units"] == 4
    assert wired["reader"].calls == 4
    assert doc["totals"]["relevant_accepted"] == 4 and doc["totals"]["records"] == 8
    assert doc["reader_pin"] == PIN.label and doc["checker_pin"] == "codex-cli@-:-"
    assert doc["store_norm_version"] == mr.STORE_NORM_VERSION
    assert doc["read_timeout_seconds"] == 1500
    # extractions are derived and gitignored; the manifest is the tracked artefact
    stems = sorted(p.stem for p in (wired["root"] / "runs" / RUN_ID / "extractions").glob("*.json"))
    assert stems == [f"{RUN_ID}-batch-{n:03d}" for n in (1, 2, 3, 4)]
    assert "resume:" in capsys.readouterr().out


def test_the_default_unit_ceiling_is_the_selected_caps_plus_a_tenth(wired, capsys):
    """`--max-units` left off must not mean "unbounded": the default is computed from the
    cells actually selected and printed before anything is bought."""
    assert mr.main(["--cells", "pre-1860|Pa.", "--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["cell_order"] == ["pre-1860|Pa."]
    caps = sum(c["cap_batches"] for c in doc["cells"].values())
    assert caps and doc["flags"]["max_units"] == math.ceil(caps * 1.1)
    assert f"caps: {doc['flags']['max_units']} reader units" in capsys.readouterr().out


def test_a_resume_is_the_same_invocation_and_replays_the_cache_for_free(wired):
    argv = ["--cells", "1930-1970|N.Y.", "--sample-pct", "0"]
    assert mr.main(argv) == 0
    first = _manifest(wired)
    assert first["resume_command"] == (
        '.venv\\Scripts\\python tools\\map_reader.py --cells "1930-1970|N.Y." --sample-pct 0')
    assert wired["reader"].calls == 2
    assert mr.main(argv) == 0                      # the resume line, run again
    assert wired["reader"].calls == 2              # nothing re-bought
    again = _manifest(wired)
    # the process bought nothing; the manifest still says what the MAP cost
    assert again["process"]["units"] == 0 and again["totals"]["units"] == 2
    assert again["totals"]["batches_completed"] == 2


def test_the_dry_run_buys_n_batches_of_the_first_cell_and_prints_the_diagnostics(wired, capsys):
    assert mr.main(["--dry-run-batches", "1", "--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["cell_order"] == ["1930-1970|N.Y."] and doc["totals"]["units"] == 1
    assert doc["flags"]["dry_run_batches"] == 1
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "status_counts" in out and "dropped_quotes" in out
    assert f"{RUN_ID}-batch-001" in out
    # the same cache the full run replays: a later full run re-buys only what is missing
    assert mr.main(["--sample-pct", "0"]) == 0
    assert wired["reader"].calls == 4             # 1 dry-run unit + 3, not 1 + 4


def test_dry_run_batches_zero_is_refused_rather_than_buying_nothing_quietly(wired):
    with pytest.raises(SystemExit) as e:
        mr.main(["--dry-run-batches", "0"])
    assert "buys nothing" in str(e.value)


def test_an_unknown_cell_is_named_rather_than_silently_reading_everything(wired):
    with pytest.raises(SystemExit) as e:
        mr.main(["--cells", "1930-1970|Nowhere"])
    assert "no such cell" in str(e.value)


def test_the_checker_sample_is_counted_apart_from_the_reader_units(wired):
    """R11: `--max-units` is a reader ceiling. A checker call is part of what a map IS, so it
    is counted and reported but never competes with a batch for the same budget."""
    assert mr.main(["--sample-pct", "100", "--max-units", "2"]) == 0
    doc = _manifest(wired)
    assert doc["stop"] == "budget:units"
    assert doc["totals"]["units"] == 2 and doc["totals"]["checker_units"] == 2
    assert doc["sample_pct"] == 100
    assert wired["checker"].calls == 2
    cell = doc["cells"]["1930-1970|N.Y."]
    assert len(cell["checker_sampled"]) == 2 and set(cell["checker_status"].values()) == {"ok"}


def test_screen_is_accepted_but_constructs_no_provider(wired, monkeypatch):
    """Task 6 owns the screen. Until then `--screen` must be inert - and inert means it never
    reaches OpenRouter, which is the only thing on this path that could cost money outside
    the subscription (R1)."""
    def explode(*a, **kw):
        raise AssertionError("the map runner constructed an OpenRouterProvider")

    monkeypatch.setattr(openrouter_mod.OpenRouterProvider, "__init__", explode)
    assert mr.main(["--screen", "--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["flags"]["screen"] is True and doc["screen"] == SCREEN_OFF
    assert all(c["screen"] == {"state": "off"} for c in doc["cells"].values())


def test_checker_pin_is_built_from_the_domain_and_is_a_different_family(wired):
    """The driver refuses a checker of the reader's own family (`preflight:families`); the pin
    this tool builds is what that check is made against."""
    dom = load_domain()
    pin = mr.checker_pin(dom)
    assert pin.model_id == dom.reader.checker["model_id"] and pin.label == "codex-cli@-:-"
    fams = dom.reader.families
    assert fams[pin.model_id] != fams[dom.reader.model["model_id"]]


def test_a_missing_pool_is_reported_instead_of_mapping_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as e:
        mr.main([])
    assert "no batches to map" in str(e.value)


def test_two_cells_runs_leave_both_cells_keys_in_the_one_tracked_manifest(wired, capsys):
    """Review finding 3, at the command level. `runs/<run-id>/map-manifest.json` is the only
    tracked artefact of what the subscription window bought, and admission reads its cache
    keys; a second `--cells` run that wrote over it would delete the first cell's."""
    assert mr.main(["--cells", "1930-1970|N.Y.", "--sample-pct", "0"]) == 0
    first = _manifest(wired)["cells"]["1930-1970|N.Y."]["cache_keys"]
    assert first

    assert mr.main(["--cells", "pre-1860|Pa.", "--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["cell_order"] == ["1930-1970|N.Y.", "pre-1860|Pa."]
    assert doc["cells"]["1930-1970|N.Y."]["cache_keys"] == first
    assert doc["cells"]["pre-1860|Pa."]["cache_keys"]
    assert doc["totals"]["batches_completed"] == 4 and doc["totals"]["units"] == 4
    assert doc["process"]["units"] == 2                  # this process bought only its own cell
    assert "MERGED into" in capsys.readouterr().out


def test_a_dry_run_after_a_full_map_does_not_shrink_what_the_map_recorded(wired):
    """The dry run reads one batch of one cell. Its walk is the lesser one, so the full map's
    survives it - and the dry run's (cached, identical) unit row is still folded in."""
    assert mr.main(["--sample-pct", "0"]) == 0
    before = _manifest(wired)
    assert mr.main(["--dry-run-batches", "1", "--sample-pct", "0"]) == 0
    after = _manifest(wired)
    assert set(after["cells"]) == set(before["cells"])
    assert after["cells"]["1930-1970|N.Y."]["batches_completed"] == 2
    assert after["totals"]["batches_completed"] == before["totals"]["batches_completed"]
    assert after["process"]["units"] == 0                # the dry run replayed the cache


def test_the_manifest_records_the_depth_table_the_caps_came_from(wired):
    """Review finding 4. `flags.depth_column` plus the code makes the table derivable; a
    manifest read on its own could not show what the cell caps were computed against."""
    assert mr.main(["--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["depth_column"] == "0.25"
    assert doc["era_depth"] == DEPTH_COLUMNS["0.25"]
    assert doc["max_units_note"].startswith("--max-units is a ceiling on READER requests")


def test_the_help_does_not_promise_an_exact_unit_ceiling(wired):
    """Review finding 2. The overrun is bounded and one-shot, but it is real, and a run note
    written against a promise of exactness would be wrong about what was bought."""
    help_text = mr.build_parser().format_help()
    assert "NOT exact" in help_text and "two split halves" in help_text


def test_a_dry_run_reports_only_the_batches_it_actually_read(wired, capsys):
    """Re-review D. Since the manifest merges, `cell_order` after a full map is every cell the
    map has ever held; printing DRY RUN diagnostics for all of them would bury the N rows the
    dry run exists to show under hundreds it never read."""
    assert mr.main(["--sample-pct", "0"]) == 0
    capsys.readouterr()
    assert mr.main(["--dry-run-batches", "1", "--sample-pct", "0"]) == 0
    out = capsys.readouterr().out
    dry = [line for line in out.splitlines() if line.startswith("DRY RUN 1930-1970|N.Y.")]
    assert len(dry) == 1
    assert "DRY RUN pre-1860|Pa." not in out
    assert out.count(f"{RUN_ID}-batch-001") >= 1
    assert f"{RUN_ID}-batch-003" not in out      # the other cell's units are not dry-run rows
    # ...while the merged manifest still holds both cells
    assert set(_manifest(wired)["cells"]) == {"1930-1970|N.Y.", "pre-1860|Pa."}
