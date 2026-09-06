"""Cells and caps (spec section 4, D2).

The cap column comes from reports/ranking-cycle-004.md section 5 (batches whose mean
rank_score clears 0.25, per era) and is split across an era's jurisdictions in proportion to
each cell's pool size, rounded UP with a floor of one - so no cell in the six unvalidated
jurisdictions is silently budgeted to zero. Order is by the mean rank_score of a cell's own
capped head, because the window may end before every cell is reached and the cells most
likely to yield have to be the ones that were read."""
import json
import math
from pathlib import Path

import pytest

from corpus_engine.mapper.cells import (DEPTH_COLUMNS, ERA_DEPTH_025, ERA_DEPTH_050, BatchSource,
                                        Cell, batch_mean_rank_score, build_cells, load_batches,
                                        select_cells)

# The real per-era batch counts, verified 2026-09-06 over runs/cycle-004-shard-01/batches.
ERA_BATCHES = {"pre-1860": 244, "1860-1900": 233, "1900-1930": 316, "1930-1970": 519,
               "1970-2020": 533}


def _batch(bid, era, jur, scores):
    return {"batch_id": bid, "ranker_id": "classifier:v1", "era_partition": era,
            "jurisdiction": jur,
            "cases": [{"case_id": 1000 + i, "era_partition": era, "jurisdiction": jur,
                       "signals": [], "rank_score": s} for i, s in enumerate(scores)]}


def _fixture(tmp_path, spec):
    """spec: {(era, jur): [ [scores of batch 1], [scores of batch 2], ... ]}"""
    d = tmp_path / "batches"
    d.mkdir()
    n = 0
    for (era, jur), batches in spec.items():
        for scores in batches:
            n += 1
            b = _batch(f"cycle-004-shard-01-batch-{n:03d}", era, jur, scores)
            (d / f"batch-{n:03d}.json").write_bytes(
                json.dumps(b, indent=1).encode("utf-8"))
    return d


def test_the_depth_columns_are_the_section_five_table():
    assert ERA_DEPTH_025 == {"pre-1860": 32, "1860-1900": 32, "1900-1930": 59,
                             "1930-1970": 139, "1970-2020": 111}
    assert sum(ERA_DEPTH_025.values()) == 373
    assert ERA_DEPTH_050 == {"pre-1860": 13, "1860-1900": 16, "1900-1930": 27,
                             "1930-1970": 74, "1970-2020": 55}
    assert sum(ERA_DEPTH_050.values()) == 185
    assert DEPTH_COLUMNS == {"0.25": ERA_DEPTH_025, "0.5": ERA_DEPTH_050}


def test_load_batches_reads_every_file_and_scores_it(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.4, 0.6], [0.1, 0.1]]})
    batches = load_batches(d)
    assert [b["batch_id"] for b in batches] == ["cycle-004-shard-01-batch-001",
                                                "cycle-004-shard-01-batch-002"]
    assert batch_mean_rank_score(batches[0]) == pytest.approx(0.5)
    assert batch_mean_rank_score(batches[1]) == pytest.approx(0.1)
    assert batch_mean_rank_score({"cases": []}) == 0.0


def test_the_cap_is_the_eras_depth_split_by_pool_size_rounded_up_with_a_floor_of_one(tmp_path):
    """1900-1930 depth 59 over an era pool of 316 batches (61 Tex., 1 D.C., 254 padding in a
    third jurisdiction so the fixture's own total matches the denominator this test hand-computes
    against). A cell of 61 batches (Tex.) gets ceil(59 * 61 / 316) = 12; a cell of one batch
    gets ceil(59 * 1 / 316) = 1, never 0 - both computed by hand from this fixture's own counts,
    not the real corpus."""
    d = _fixture(tmp_path, {("1900-1930", "Tex."): [[0.9]] * 61,
                            ("1900-1930", "D.C."): [[0.2]] * 1,
                            ("1900-1930", "Ala."): [[0.5]] * 254})
    cells = {c.key: c for c in build_cells(load_batches(d), era_depth={"1900-1930": 59})}
    assert cells["1900-1930|Tex."].cap_batches == 12
    assert cells["1900-1930|D.C."].cap_batches == 1
    assert len(cells["1900-1930|Tex."].batch_ids) == 61


def test_the_real_pool_caps_reproduce_the_recorded_totals():
    """The numbers the runner's default --max-units is computed from. If the batch files or
    the depth table move, this is the test that says so."""
    per_cell = {("1930-1970", "N.Y."): 75, ("1930-1970", "D.C."): 8, ("1970-2020", "N.Y."): 82,
                ("pre-1860", "Cal."): 17, ("1860-1900", "La."): 13}
    expected = {("1930-1970", "N.Y."): 21, ("1930-1970", "D.C."): 3, ("1970-2020", "N.Y."): 18,
                ("pre-1860", "Cal."): 3, ("1860-1900", "La."): 2}
    for (era, jur), n in per_cell.items():
        cap = max(1, math.ceil(ERA_DEPTH_025[era] * n / ERA_BATCHES[era]))
        assert cap == expected[(era, jur)], (era, jur, cap)


def test_batches_inside_a_cell_are_ranked_and_cells_are_ordered_by_their_capped_head(tmp_path):
    """The head, not the whole cell: a cell whose cap is 2 is judged on the two batches it
    will actually read, so a long tail of weak batches cannot demote a strong short head."""
    d = _fixture(tmp_path, {
        ("pre-1860", "N.Y."): [[0.10], [0.90], [0.80]],     # head (0.90, 0.80) -> 0.85
        ("pre-1860", "Pa."): [[0.60], [0.60], [0.60]],      # head (0.60, 0.60) -> 0.60
    })
    cells = build_cells(load_batches(d), era_depth={"pre-1860": 4})
    assert [c.key for c in cells] == ["pre-1860|N.Y.", "pre-1860|Pa."]
    ny = cells[0]
    assert ny.cap_batches == 2
    assert ny.batch_ids == ("cycle-004-shard-01-batch-002", "cycle-004-shard-01-batch-003",
                            "cycle-004-shard-01-batch-001")
    assert ny.capped_ids == ("cycle-004-shard-01-batch-002", "cycle-004-shard-01-batch-003")
    assert ny.mean_rank_score == pytest.approx(0.85)
    assert isinstance(ny, Cell) and ny.era == "pre-1860" and ny.jurisdiction == "N.Y."


def test_ties_break_deterministically_on_era_then_jurisdiction(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "Pa."): [[0.5]], ("pre-1860", "Cal."): [[0.5]],
                            ("1860-1900", "N.Y."): [[0.5]]})
    keys = [c.key for c in build_cells(load_batches(d),
                                       era_depth={"pre-1860": 2, "1860-1900": 1})]
    assert keys == ["1860-1900|N.Y.", "pre-1860|Cal.", "pre-1860|Pa."]


def test_jurisdictions_by_era_is_derived_from_the_batches_when_not_given(tmp_path):
    """Spec section 1 says eleven jurisdictions; the batches on disk carry ten. The cell set
    is whatever the batch files say it is - passing the map in only restricts it."""
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5]], ("pre-1860", "Utah"): [[0.9]]})
    batches = load_batches(d)
    assert {c.jurisdiction for c in build_cells(batches, era_depth={"pre-1860": 2})} == {"N.Y.", "Utah"}
    restricted = build_cells(batches, era_depth={"pre-1860": 2},
                             jurisdictions_by_era={"pre-1860": ["N.Y."]})
    assert [c.key for c in restricted] == ["pre-1860|N.Y."]


def test_an_era_with_no_depth_entry_is_refused_rather_than_read_uncapped(tmp_path):
    d = _fixture(tmp_path, {("2020-", "N.Y."): [[0.5]]})
    with pytest.raises(KeyError, match="2020-"):
        build_cells(load_batches(d), era_depth=ERA_DEPTH_025)


def test_batch_source_serves_batches_by_id_without_reloading_the_pool(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5], [0.6]]})
    src = BatchSource(d)
    assert src.ids() == ("cycle-004-shard-01-batch-001", "cycle-004-shard-01-batch-002")
    assert "cycle-004-shard-01-batch-001" in src
    b = src.get("cycle-004-shard-01-batch-002")
    assert b["jurisdiction"] == "N.Y." and len(b["cases"]) == 1
    with pytest.raises(KeyError):
        src.get("cycle-004-shard-01-batch-999")


def test_select_cells_filters_by_key_and_refuses_an_unknown_one(tmp_path):
    d = _fixture(tmp_path, {("pre-1860", "N.Y."): [[0.5]], ("pre-1860", "Pa."): [[0.9]]})
    cells = build_cells(load_batches(d), era_depth={"pre-1860": 2})
    assert [c.key for c in select_cells(cells, None)] == [c.key for c in cells]
    assert [c.key for c in select_cells(cells, "pre-1860|N.Y.")] == ["pre-1860|N.Y."]
    assert [c.key for c in select_cells(cells, "pre-1860|Pa.,pre-1860|N.Y.")] == [
        "pre-1860|Pa.", "pre-1860|N.Y."]        # the run order stays the cells' own order
    with pytest.raises(ValueError, match="1930-1970"):
        select_cells(cells, "1930-1970|N.Y.")
