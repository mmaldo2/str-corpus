# tests/golden

Snapshots captured by `tools/capture_goldens.py` at commit
`e9f6f48d0922ca81bc999bfed2bcad171fe47af3` before the Stage 1 refactor. They
are the characterization targets:

- `digests.json` — sha256 of every ledger, adjudication, verified, and batch
  file.
- `prompts/cycle-003-shard-01/batch-NNN.txt` — the exact reader prompt the old
  `run_map.build_payload` produced for the first ten cycle-003 batches.
- `cycle-003-batches.json` — the parameters under which
  `tests/fixtures/cycle-003-signals.db` reproduces the cycle-003 batches.

Never regenerate these without a logged reason; a change here is a change in
what the pipeline produces.

## Known non-reproductions

`runs/cycle-003-shard-01/batches/` (and `verified/`) contain two files that
`tools/capture_goldens.py`'s reproduction check deliberately excludes:
`batch-139-part1.json` and `batch-139-part2.json`. These are hand-derived,
post-sharding splits of `batch-139.json` (9 cases + 9 cases = the same 18
case_ids as `batch-139.json`), made after `cycle-003-shard-01` was sharded
so the batch could be mapped in two smaller LLM calls. `shard.emit_batches`
only ever writes `batch-NNN.json` files — it cannot and never did produce
`-part1`/`-part2` files — so they are not part of what the reproduction
check (`verify_batches_reproduce` in `tools/capture_goldens.py`) verifies;
it compares against the canonical `batch-[0-9][0-9][0-9].json` files only
(630 of them, matching `runs/shard-cycle003.log`'s own "630 batches" and
"excluding 3397 already-mapped cases" lines).

They are still real run artifacts, so `digests.json`'s `"batches"` and
`"verified"` sections continue to include their sha256 hashes alongside
everything else on disk under `runs/cycle-*/batches` and
`runs/cycle-*/verified` — only the reproduction check ignores them.
