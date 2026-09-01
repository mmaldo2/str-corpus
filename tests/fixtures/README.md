# tests/fixtures

- `corpus-tiny.db` — built by `tools/build_fixture_corpus.py` from the live corpus:
  cycle-003 batches 001-005, all resolved gold cases, all human-reviewed ledger
  cases. Full text, page maps, both FTS tables, chunk vectors, embed_meta.
- `cycle-003-signals.db` — signals and coverage tables as of the end of cycle 003
  plus case metadata for every signalled case (`tools/capture_goldens.py`).
- `cycle-003-already-read.json` — the exclusion set in force when cycle 003 was sharded.
