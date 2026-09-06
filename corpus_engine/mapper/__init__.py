"""The map: one pass of the pinned reader over a cycle's ranked candidate pool under a
per-cell budget (CONTEXT.md glossary; spec sections 4-9)."""
from corpus_engine.mapper.cells import BatchSource, Cell, build_cells, load_batches, select_cells
from corpus_engine.mapper.yield_stop import CellProgress, CellStop

__all__ = ["BatchSource", "Cell", "build_cells", "load_batches", "select_cells",
           "CellProgress", "CellStop"]
