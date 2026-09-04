# tests/golden

## Byte convention

`digests.json` hashes are computed over CRLF->LF-normalized bytes (git's stored,
canonical form for these text files) — `tools/capture_goldens.py`'s `sha()` does
`p.read_bytes().replace(b"\r\n", b"\n")` before hashing. This makes digests stable
regardless of the checkout platform's line-ending translation (`core.autocrlf`
turns the LF blobs stored in git into CRLF on a Windows working-tree checkout, and
back on commit). Any test that hashes a file — or an in-memory reproduction of one
— to compare against `digests.json` must normalize `\r\n` -> `\n` the same way
before hashing, whether it's hashing bytes read from disk or a freshly-serialized
`json.dumps(...)` string.

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

## Selector goldens

Captured by `tools/capture_selector_goldens.py`, commit
`goldens: cycle-003 recall report and recorded query vectors for the embedding
selectors` (Stage 2B Task 1), against the live database as it stood at cycle
003 (`signals` table unchanged since then; no cycle-004 rows were present):

- `recall-cycle-003.json` — the pre-refactor `pipeline/eval_recall.py:evaluate(None)`
  report, slimmed to `tiers`, `hits` (`{case_id, selectors}`, sorted), and
  `misses` (sorted `case_id`s). Tiers: brief-letting 6/9, treatise 22/29,
  brief-all 17/63.
- `tests/fixtures/query-vectors-v3.npz` — one normalized 512-d float32 query
  vector per active embedding selector from `pipeline/shard.py:load_selectors()`
  (key `f"{id}@v{version}"`), plus `__meta__` (the JSON string of `embed_meta`).
  **These vectors are for the 0.6B index that `tests/fixtures/corpus-tiny.db`
  and the rest of this plan's fixtures characterize** — `embed_meta` was read
  from that fixture DB (`Qwen/Qwen3-Embedding-0.6B`, revision
  `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`, dim 512), not from the live
  database, which has since been re-embedded with Qwen3-Embedding-4B (1024-d).
  When the 4B index lands, these vectors are replaced as a logged golden
  change, not amended in place.

Only four embedding selectors were active at capture time —
`embed-short-letting-23@v1`, `adverse-embed-regulation-29@v1`,
`embed-zoning-paying-occupants-22@v2`, `embed-householder-letting-21@v2` —
not six; two more (`embed-householder-letting-21@v1`,
`embed-zoning-paying-occupants-22@v1`) exist in `selectors/selectors.yaml`
but are `status: retired`, so `load_selectors()` excludes them.

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

## Unexplained drift (bootstrap)

`corpus_engine/ledger/bootstrap.py`'s `patches_from_artifacts` derives the
patch log purely from the run artifacts the old scripts consumed
(`decisions-final.json`, `verified/*.json`, the polarity-review and
relevance-recheck run directories). Two case_ids in `data/ledger/cycle-001.jsonl`
do not come from any such artifact: they were corrected directly by hand in
commit `2ca53b9` ("Resolve final two adjudications: Hancock v. Rand -> mixed;
Hardin v. State kept (mixed, low weight). Cycle 001 fully adjudicated; no open
questions."), which edited `data/ledger/cycle-001.jsonl` in place with no
run/decisions artifact recording why. `bootstrap.py`'s `_drift_patches`
reproduces that commit's diff explicitly, with
`why="bootstrap: unexplained drift, see tests/golden/README.md"`.

**case_id 4453395** — "24 N.Y. Sup. Ct. 279" (Hancock v. Rand, per the commit
message):
```diff
- "polarity": "irrelevant"
+ "polarity": "mixed"
- "review": {"status": "human-adjudicated", "flags": ["open-question:polarity"],
-            "notes": ["relevant adjudicated -> True",
-                      "user note: I agree it's relevant, but why is this favorable? ",
-                      "characterization adjudicated -> innkeeping"]}
+ "review": {"status": "human-adjudicated", "flags": [],
+            "notes": ["relevant adjudicated -> True",
+                      "user note: I agree it's relevant, but why is this favorable? ",
+                      "characterization adjudicated -> innkeeping",
+                      "polarity resolved -> mixed per user: value is classificatory
+                       (fixed price/duration does not alter guest status),
+                       not rights-protective"]}
```

**case_id 4539230** — "47 Tex. Crim. 493" (Hardin v. State, per the commit
message):
```diff
- "relevance_score": 0.55
+ "relevance_score": 0.35
- "review": {"status": "pending-user-question", "flags": ["open-question:polarity"],
-            "notes": ["user note: Is this relevant?"]}
+ "review": {"status": "human-adjudicated", "flags": [],
+            "notes": ["user note: Is this relevant?",
+                      "relevance resolved -> keep (mixed, low weight) per user:
+                       incidental civil holding distinguishing householder
+                       room-letting from boarding-house business (Cady/Howth line)"]}
```

## Resolved: `LedgerView.reviewed()` semantics (159-vs-150 finding)

The Task 9 bootstrap originally found `sum(1 for r in relevant if
v.reviewed(r["case_id"]))` returning 159 against a published figure of 150 in
the task brief. Investigation (see the bootstrap task report) found
`LedgerView.reviewed()` counted any `drop_quote` patch with a human
`basis.reviewer` as "reviewed" *regardless of the record's `field` or final
`review.status`* — so a Section B fuzzy-quote "mismatch" call alone (drop a
quote, append a note, never touch `review.status` — faithful to
`apply_adjudications.py`) counted as human review. There are 13 such
human-confirmed mismatch drops across the three cycles (1 in cycle-001, 7 in
cycle-002, 5 in cycle-003, verified against each run's `decisions-final.json`);
9 of the affected records were otherwise untouched, so they contributed the
full 159-vs-150 gap.

Controller ruling: per `CONTEXT.md`, "human-reviewed" means a human confirmed
the record's *judgments* — a fuzzy-quote mismatch call alone does not qualify.
The rule in `LedgerView.reviewed()` was wrong, not the published 150 figure.
Fixed in `corpus_engine/ledger/ledger.py`: `reviewed()` now requires a patch
with `basis.reviewer` and `op in ("set", "append")` whose `field` is in the
domain's judged fields or equals `"review.status"`; `drop_quote` no longer
qualifies on its own (a human must also make a judged-field or status decision
on that case for it to count). `tests/test_ledger_apply.py` covers this
directly: after an admit, a human `drop_quote` alone leaves `reviewed()`
`False`, and a subsequent human `set review.status "human-adjudicated"` makes
it `True`. With the fixed rule, `test_bootstrap_counts_match_published_figures`
passes unchanged — the bootstrapped `reviewed()` count is 150, matching the
published figure.
