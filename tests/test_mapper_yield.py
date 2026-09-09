"""The per-cell stop rule (spec section 5, D2): three completed batches yielding two or fewer
relevant accepted records between them, or the cap.

Pure: no reader, no clock, no files. A failed unit is recorded but never enters the window -
a provider failure is not evidence that a cell has stopped paying, and letting it count would
close a cell on the strength of an outage."""
import pytest

from corpus_engine.mapper.yield_stop import THRESHOLD, WINDOW, CellProgress, CellStop


def _p(cap=10):
    return CellProgress("1930-1970|N.Y.", cap)


def test_the_window_and_threshold_are_the_recorded_defaults():
    assert WINDOW == 3 and THRESHOLD == 2


def test_a_cell_does_not_stop_before_the_window_is_full():
    p = _p()
    p.add("b1", 0, True)
    assert p.should_stop() is None
    p.add("b2", 0, True)
    assert p.should_stop() is None


def test_three_completed_batches_at_or_under_the_threshold_stop_the_cell():
    p = _p()
    for bid, n in (("b1", 1), ("b2", 1), ("b3", 0)):
        p.add(bid, n, True)
    stop = p.should_stop()
    assert isinstance(stop, CellStop) and stop.kind == "yield_floor"
    assert "2" in stop.detail and "b1" in stop.detail and "b3" in stop.detail
    assert p.relevant_accepted == 2 and p.completed_batches == 3


def test_three_above_the_threshold_do_not():
    p = _p()
    for bid, n in (("b1", 1), ("b2", 1), ("b3", 1)):
        p.add(bid, n, True)
    assert p.should_stop() is None


def test_the_window_is_the_LAST_three_not_the_first_three():
    p = _p()
    for bid, n in (("b1", 0), ("b2", 0), ("b3", 0)):
        p.add(bid, n, True)
    assert p.should_stop().kind == "yield_floor"
    p.add("b4", 9, True)                       # a rich batch re-opens the cell
    assert p.should_stop() is None
    p.add("b5", 0, True)
    p.add("b6", 0, True)
    assert p.should_stop() is None             # last three are 9, 0, 0 = 9
    p.add("b7", 0, True)
    assert p.should_stop().kind == "yield_floor"


def test_a_failed_unit_is_recorded_and_skipped_by_the_window():
    p = _p()
    p.add("b1", 0, True)
    p.add("b2", 0, False)                       # provider failure: not evidence about yield
    p.add("b3", 0, True)
    assert p.should_stop() is None
    assert p.failed == ("b2",)
    assert p.attempted_batches == 3 and p.completed_batches == 2
    p.add("b4", 0, True)
    assert p.should_stop().kind == "yield_floor"


def test_the_cap_stops_the_cell_even_while_it_is_still_paying():
    p = _p(cap=2)
    p.add("b1", 8, True)
    assert p.should_stop() is None
    p.add("b2", 8, True)
    stop = p.should_stop()
    assert stop.kind == "cap_reached" and stop.detail == "2 of 2 batches"


def test_the_cap_wins_when_both_rules_fire_so_the_screen_is_not_offered_a_finished_cell():
    """The screen (spec section 7) triggers on yield_floor WITH cap remaining. A cell that
    hit its cap on a dry window has no remainder, so it must not report yield_floor."""
    p = _p(cap=3)
    for bid in ("b1", "b2", "b3"):
        p.add(bid, 0, True)
    assert p.should_stop().kind == "cap_reached"


def test_a_failed_unit_does_not_consume_the_cap():
    p = _p(cap=2)
    p.add("b1", 5, False)
    p.add("b2", 5, True)
    assert p.should_stop() is None
    p.add("b3", 5, True)
    assert p.should_stop().kind == "cap_reached"


def test_the_parameters_are_overridable_and_recorded(caplog):
    p = _p()
    p.add("b1", 3, True)
    p.add("b2", 3, True)
    assert p.should_stop(window=2, threshold=6).kind == "yield_floor"
    assert p.should_stop(window=2, threshold=5) is None
    doc = p.to_json(window=2, threshold=6)
    assert doc["yield_series"] == [{"batch_id": "b1", "relevant_accepted": 3},
                                   {"batch_id": "b2", "relevant_accepted": 3}]
    assert doc["relevant_accepted"] == 6 and doc["batches_completed"] == 2
    assert doc["batches_attempted"] == 2 and doc["failed_units"] == []
    assert doc["stop"] == {"kind": "yield_floor", "detail": doc["stop"]["detail"]}
    assert p.to_json()["stop"] is None


def test_an_uncapped_cell_reports_exhaustion_rather_than_a_cap_it_does_not_have():
    """Nit 14. A budgeted run's cells carry `cap_batches = len(batch_ids)` and `uncapped=True`,
    and the manifest writes `cap: "none"` - so the same arithmetic means "ran out of batches",
    not "a depth decision stopped it"."""
    p = CellProgress("1930-1970|N.Y.", 2, uncapped=True)
    p.add("b1", 8, True)
    assert p.should_stop() is None
    p.add("b2", 8, True)
    stop = p.should_stop()
    assert stop.kind == "cell_exhausted" and stop.detail == "2 of 2 batches"
