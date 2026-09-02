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

## Known discrepancy: `LedgerView.reviewed()` count in `test_ledger_bootstrap.py`

`test_bootstrap_counts_match_published_figures` (added in the Task 9 bootstrap)
asserts `sum(1 for r in relevant if v.reviewed(r["case_id"])) == 150`, a figure
carried over from the task brief. The actual bootstrapped count is **159**, and
this is not a derivation bug: `LedgerView.reviewed()` (Task 8, `ledger.py`)
counts any `drop_quote` patch with a human `basis.reviewer` as "reviewed"
*regardless of the record's `field` or final `review.status`*
(`p.field in judged or p.op == "drop_quote"`). Section B of the old scripts
(`apply_adjudications.py`'s fuzzy-quote "mismatch" resolution) drops a quote and
appends a note, but — faithfully to the original script — never touches
`review.status`. There are 13 such human-confirmed mismatch drops across the
three cycles (1 in cycle-001, 7 in cycle-002, 5 in cycle-003, verified against
each run's `decisions-final.json`); 9 of the affected records were never
otherwise touched by a status-setting adjudication, so their `review.status`
stays `"machine"` even though `reviewed()` correctly reports them as reviewed.
150 is exactly the count of `relevant` records whose `review.status !=
"machine"` (`138 + 11 + 1`, the same three non-machine buckets asserted two
lines earlier in the same test) — a different, narrower question than "was this
record ever touched by a human reviewer," which is what `reviewed()` answers.
150 appears to be a miscount in the task-9 brief that conflated the two
quantities (mirroring the brief's own "8 passed" vs. actual-9 miscount noted in
`task-8-report.md`), not a defect in the bootstrap or in `reviewed()`. The
byte-for-byte reproduction test — the actual gate — passes cleanly; this
count-only assertion is left exactly as specified in the brief rather than
weakened, and is flagged here per that finding.
