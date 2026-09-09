"""Cells and caps (spec section 4).

A cell is an era x jurisdiction slice of the candidate pool - the unit the budget is set on.
Its cap is its share of the era's 0.25 rank-score depth from reports/ranking-cycle-004.md
section 5, in proportion to how many batches the cell actually holds, rounded UP with a floor
of one so a small cell in one of the six jurisdictions with no held-out AP still gets read.

Cells are read in descending order of the mean rank_score of their CAPPED HEAD, not of the
whole cell: the process may stop on its wall clock before every cell is reached, so the order
has to be about the batches that would actually be bought."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

# reports/ranking-cycle-004.md section 5: batches whose mean rank_score clears the cut.
ERA_DEPTH_025 = {"pre-1860": 32, "1860-1900": 32, "1900-1930": 59, "1930-1970": 139,
                 "1970-2020": 111}
ERA_DEPTH_050 = {"pre-1860": 13, "1860-1900": 16, "1900-1930": 27, "1930-1970": 74,
                 "1970-2020": 55}
DEPTH_COLUMNS = {"0.25": ERA_DEPTH_025, "0.5": ERA_DEPTH_050}
BATCH_GLOB = "batch-*.json"
# Units `--retry-lost` planned over the cases a completed unit dropped (I3). They live beside
# the pool's own batch files and are read like any other batch - `BatchSource` serves them, and
# admission needs to find them or the cases it recovered are re-derived from nothing - but they
# are NOT part of the pool the cells are built from: `load_batches` globs BATCH_GLOB only, so a
# retry can never add a batch to a cell, shift an era's proportional caps, or change what a
# resume of the original command would read.
RETRY_GLOB = "retry-*.json"


@dataclass(frozen=True)
class Cell:
    era: str
    jurisdiction: str
    batch_ids: tuple[str, ...]          # every batch in the cell, best rank_score first
    cap_batches: int
    mean_rank_score: float              # over `capped_ids`, which is what decides the order
    # D4: a budgeted run's cell. `cap_batches` is still the cell's own size (so `capped_ids` is
    # every batch it holds), but the cap governs nothing - the case budget stops the run and
    # the yield floor stops a cell - and `to_json` says so with `cap: "none"`. Last field,
    # defaulted, so every existing construction of `Cell` still works.
    uncapped: bool = False

    @property
    def key(self) -> str:
        return f"{self.era}|{self.jurisdiction}"

    @property
    def capped_ids(self) -> tuple[str, ...]:
        return self.batch_ids[:self.cap_batches]

    def to_json(self) -> dict:
        return {"era": self.era, "jurisdiction": self.jurisdiction,
                "n_batches": len(self.batch_ids), "cap_batches": self.cap_batches,
                "mean_rank_score": round(self.mean_rank_score, 6),
                # D4: a budgeted run has no per-cell cap - the budget stops the run and the
                # yield floor stops a cell - so the manifest says `none` rather than repeating
                # a `cap_batches` that is only the cell's own size and governs nothing.
                "cap": "none" if self.uncapped else "batches"}


def batch_mean_rank_score(batch: Mapping) -> float:
    cases = batch.get("cases") or []
    if not cases:
        return 0.0
    return sum(float(c.get("rank_score") or 0.0) for c in cases) / len(cases)


def load_batches(batches_dir: Path) -> list[dict]:
    """Every batch file in the shard, sorted by `batch_id` so the pool is the same list on
    every machine regardless of what order the filesystem hands them back."""
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(batches_dir).glob(BATCH_GLOB))]
    return sorted(out, key=lambda b: b["batch_id"])


def build_cells(batches: Sequence[Mapping], *, era_depth: Mapping[str, int] = ERA_DEPTH_025,
                jurisdictions_by_era: Mapping[str, Sequence[str]] | None = None) -> list[Cell]:
    """The cells of this pool, capped and ordered (D2).

    `jurisdictions_by_era` is optional: the pool's own batch files are the authority on which
    cells exist (ten jurisdictions on disk against the eleven the spec's prose names), so the
    map is derived from them unless a caller restricts it.

    `mean_rank_score` here is the mean over the cell's CAPPED HEAD - the batches this run will
    actually buy - because that is what the cell is worth at this depth. `build_budget_cells`
    (D4) uses a different mean, pooled over every case in the cell, and says why: an uncapped
    cell has no head to average."""
    by_cell: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for b in batches:
        era, jur = b["era_partition"], b["jurisdiction"]
        if jurisdictions_by_era is not None and jur not in (jurisdictions_by_era.get(era) or ()):
            continue
        by_cell.setdefault((era, jur), []).append((batch_mean_rank_score(b), b["batch_id"]))
    era_totals: dict[str, int] = {}
    for (era, _jur), rows in by_cell.items():
        era_totals[era] = era_totals.get(era, 0) + len(rows)
    cells: list[Cell] = []
    for (era, jur), rows in by_cell.items():
        if era not in era_depth:
            raise KeyError(f"no map depth recorded for era {era!r}; add it to a DEPTH_COLUMNS "
                           f"column rather than reading the era uncapped")
        rows.sort(key=lambda r: (-r[0], r[1]))          # best first, batch_id breaks ties
        ids = tuple(bid for _s, bid in rows)
        cap = max(1, math.ceil(era_depth[era] * len(rows) / era_totals[era]))
        head = [s for s, _bid in rows[:cap]]
        cells.append(Cell(era, jur, ids, cap, sum(head) / len(head) if head else 0.0))
    cells.sort(key=lambda c: (-c.mean_rank_score, c.era, c.jurisdiction))
    return cells


def build_budget_cells(batches: Sequence[Mapping]) -> list[Cell]:
    """The cells of a budgeted run (D4): every batch is walkable, so the cap is the cell's own
    size and `uncapped` says the number means nothing. The order is still by mean rank score -
    pooled over every CASE in the cell rather than averaged batch by batch, because an uncapped
    cell has no "head" the way `build_cells`' capped one does, and a batch-by-batch average
    would let a cell of many small batches outrank one whose cases actually score higher on
    average. This matters only for the manifest's `cell_order`: a budgeted run walks
    `global_batch_order`, not the cells."""
    by_cell: dict[tuple[str, str], list[tuple[float, str]]] = {}
    case_scores: dict[tuple[str, str], list[float]] = {}
    for b in batches:
        key = (b["era_partition"], b["jurisdiction"])
        by_cell.setdefault(key, []).append((batch_mean_rank_score(b), b["batch_id"]))
        case_scores.setdefault(key, []).extend(
            float(c.get("rank_score") or 0.0) for c in (b.get("cases") or []))
    cells = []
    for key, rows in by_cell.items():
        era, jur = key
        rows.sort(key=lambda r: (-r[0], r[1]))
        scores = case_scores[key]
        mean = sum(scores) / len(scores) if scores else 0.0
        cells.append(Cell(era, jur, tuple(bid for _s, bid in rows), len(rows), mean,
                          uncapped=True))
    cells.sort(key=lambda c: (-c.mean_rank_score, c.era, c.jurisdiction))
    return cells


def global_batch_order(batches: Sequence[Mapping]) -> tuple[tuple[str, str], ...]:
    """`(cell_key, batch_id)` for every batch in the pool, best mean rank score first, batch id
    breaking ties (D4). This is the order a budgeted run spends its cases in: top down across
    ALL cells, so the last batch bought is the worst one the budget could reach - which is the
    number the D5 test in the report is about."""
    rows = [(batch_mean_rank_score(b), b["batch_id"],
             f"{b['era_partition']}|{b['jurisdiction']}") for b in batches]
    rows.sort(key=lambda r: (-r[0], r[1]))
    return tuple((cell_key, bid) for _s, bid, cell_key in rows)


def select_cells(cells: Sequence[Cell], spec: str | None) -> list[Cell]:
    """`--cells era|jurisdiction[,...]`. The run order is the cells' own order, never the
    order they were typed in: a `--cells` run and a full run read the same cell first."""
    if not spec:
        return list(cells)
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    known = {c.key for c in cells}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise ValueError(f"no such cell: {', '.join(unknown)}; known cells are "
                         f"{', '.join(sorted(known))}")
    return [c for c in cells if c.key in set(wanted)]


class BatchSource:
    """One batch file at a time, by id. The runner reads 1,845 files' worth of metadata once
    through `load_batches` to build the cells, then pulls only the batches it actually plans.

    It serves the pool's batches AND the retry units `--retry-lost` wrote (RETRY_GLOB), because
    both were read and both have to be re-derivable offline by admission. `load_batches` does
    not - see RETRY_GLOB."""

    def __init__(self, batches_dir: Path):
        self.dir = Path(batches_dir)
        files = sorted(self.dir.glob(BATCH_GLOB)) + sorted(self.dir.glob(RETRY_GLOB))
        self._by_id = {p.stem: p for p in files}
        self._index: dict[str, Path] = {}
        for p in self._by_id.values():
            self._index[json.loads(p.read_text(encoding="utf-8"))["batch_id"]] = p

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._index))

    def __contains__(self, batch_id: str) -> bool:
        return batch_id in self._index

    def get(self, batch_id: str) -> dict:
        try:
            path = self._index[batch_id]
        except KeyError:
            raise KeyError(f"{batch_id} is not in {self.dir}") from None
        return json.loads(path.read_text(encoding="utf-8"))
