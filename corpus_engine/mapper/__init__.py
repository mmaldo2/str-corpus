"""The map: one pass of the pinned reader over a cycle's ranked candidate pool under a
per-cell budget (CONTEXT.md glossary; spec sections 4-9)."""
from corpus_engine.mapper.admit import (IDENTITY_FIELDS, MAPPER_FIELDS, AdmittedRecord, basis_for,
                                        checker_notes, counts_by_cell, patches_for, prompt_version,
                                        records_from_manifest)
from corpus_engine.mapper.cells import BatchSource, Cell, build_cells, load_batches, select_cells
from corpus_engine.mapper.runner import (MapOutcome, MapRunner, RunnerCaps, default_max_units,
                                          merge_manifest)
from corpus_engine.mapper.screen import Screen
from corpus_engine.mapper.yield_stop import CellProgress, CellStop

__all__ = ["BatchSource", "Cell", "build_cells", "load_batches", "select_cells",
           "CellProgress", "CellStop",
           "MapOutcome", "MapRunner", "RunnerCaps", "Screen", "default_max_units",
           "merge_manifest",
           "IDENTITY_FIELDS", "MAPPER_FIELDS", "AdmittedRecord", "basis_for", "checker_notes",
           "counts_by_cell", "patches_for", "prompt_version", "records_from_manifest"]
