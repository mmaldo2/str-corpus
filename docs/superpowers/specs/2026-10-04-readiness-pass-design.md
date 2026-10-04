# Readiness pass before the Gluck run — design

Date: 2026-10-04. Status: approved in brainstorm (user), section by section. This is part 0 of
the work driven by Cam's thirteen "Gluck" questions (`Downloads/Gluck Prompts.md`, outside the
repo); parts 1-4 (ledger answers, codebook v4, cycle 005, non-case sources) get their own specs.

## 1. Goal

Put the system in a state where the Gluck work can run without tripping over the
environment, the repository or the corpus: the remote holds the work, the Python environment
cannot vanish under a long run, the patch log stays inside GitHub's file limits, and a
decision printed in two reporters is one case, not two.

Health check that motivated it (2026-10-04): suite 812 passed + 1 xfail; the reader's stripped
`claude -p` call works on CLI 2.1.289 with `claude-opus-5`; Codex 0.153.4 answers on
`gpt-5.6-terra` (checker) and `gpt-6-astra` (first pass); 303 GB free.

## 2. Non-goals and standing rules

- No reading, no codebook change, no reader-model change (Opus 5 stays pinned; Opus 5.5 is a
  part-2/3 question).
- The 150-record audit stays pending and untouched. Nothing here may change `relevant`,
  `polarity` or `who_was_letting` on a sampled record (the `--audit` drift check reads those
  three).
- Moved out of this pass by decision: the `keep` provenance gap (part 2, where re-reads make it
  bite); the KWIC jurisdiction filter and proximity search (part 1).
- Published counts change only through ledger patches; the evaluation is republished after the
  audit, not here.
- Never push `.env`, `data/db/`, `data/raw/`, `reports/explainer/` (all ignored today).

## 3. Repository: push and housekeeping

1. Push the 36 local commits (Stage 4 evaluation, audit kit, explainer tool) before any
   restructuring. Push again at the end of the pass.
2. Commit: `reports/gold-codebook-review-2026-09-29.md`;
   `runs/cycle-004-shard-01/shard-manifest.json` (its shard-02 twin is tracked); the two empty
   audit trails `runs/cycle-001-shard-02/fuzzy-auto-accepted.json` and
   `runs/cycle-002-shard-01/fuzzy-auto-accepted.json`.
3. Ignore (no deletion): `reports/right-to-let-guide.html` and
   `reports/right-to-let-guide-sources.md` (the retired Sept 14 guide stays off the public
   repo), `cl.html`, `.tmp/`, `.playwright-mcp/`, `runs/*.err`, `tests/fixtures/*.db-shm`,
   `tests/fixtures/*.db-wal`.
4. Tests: find the test that leaves `corpus-tiny.db` in WAL with `-wal`/`-shm` behind
   (`store.connect` sets `journal_mode=WAL`) and close its connection;
   `tests/test_verification_char.py` opens the live corpus with `mode=ro`.

## 4. Python environment

The project `.venv` was created from the Hermes agent's bundled interpreter
(`pyvenv.cfg` home = `...\hermes-agent\.hermes-runtime\python\generation-1786712544-...`). A
Hermes update can remove that generation folder and break a multi-hour run.

1. `pip freeze` the current `.venv` into `requirements-lock.txt` (52 packages, including
   `torch==2.11.0+cu128`, installed with `--extra-index-url https://download.pytorch.org/whl/cu128`).
2. Move `.venv` to `.venv-hermes` (fallback; delete after the first successful run in part 1 or 3).
3. Create `.venv` from uv's standalone CPython 3.11.15 (the same version) and install the lock.
4. Verify on the new environment: full suite; `torch.cuda.is_available()`; a selector dry run that
   loads the local Qwen query encoder; `pipeline/kwic.py freq lodger` on the live corpus.
5. README setup section names the lock file and the uv interpreter.

## 5. Patch-log split

### 5.1 Layout

`data/ledger/patches.jsonl` (54,189,757 bytes, 83,531 patches) becomes a directory of segments:
`data/ledger/patches/0001.jsonl`, `0002.jsonl`, ... Each segment holds a contiguous seq range;
segment *n+1* starts at the seq after segment *n* ends. Only the last segment is ever appended
to. Concatenated in name order, the segments are byte for byte the old single file.

Rejected: one file per cycle (cycle 004 alone is most of the log, and re-read patches interleave
across cycles, so concatenation would no longer be the log); Git LFS (every version of a growing
file is stored whole, exhausting the free quota).

### 5.2 Rotation

Before an append, if the active segment is at or above `SEGMENT_CAP_BYTES = 25_000_000`, the
append opens the next segment. One append never spans two segments. The largest single append
so far is 10.2 MB (cycle-004 shard-01 admission, 23,567 patches), so a segment stays below
about 35 MB, under GitHub's 50 MB warning and far under its 100 MB rejection.

### 5.3 Code

- `corpus_engine/ledger/log.py`: `PatchLog(dir)` reads every segment in name order and appends
  to the last, applying 5.2. `head()` is the last segment's last seq. Seq, `patch_id` and the
  write lock are unchanged.
- `ledger.py`: `Ledger` builds `PatchLog(self.dir / "patches")`.
- `corpus_engine/evaluation/summary.py`: `ledger_content_sha256` hashes the segments in name
  order, then the cycle files, exactly as before. Because the segments concatenate to the old
  file, the hash is unchanged.
- `tools/bootstrap_ledger.py`: refuses if either the old file or the segment directory exists.
- Tests that open `patches.jsonl` directly (`test_ledger_committed.py`, `test_ledger_apply.py`,
  `test_mapper_admit.py`, `test_evaluation_summary.py`, `test_evaluate_tool.py`) go through the
  new layout. A grep found no other direct reader.
- A ledger directory holding both layouts is an error (`LedgerError`), never a silent merge.

### 5.4 Migration

One-time `tools/split_patch_log.py`, under the ledger lock: cut the file at line boundaries into
segments of at most 25 MB; verify that the concatenation equals the original bytes and that
`ledger_content_sha256` still returns
`b84796f05f9cfbc535f91a255c81d61ed44f623df34b51c6b6d0299483253932` (the value published in
`reports/evaluation-cycle-004.json`, and the live value on 2026-10-04); only then remove
`patches.jsonl`. Refuses if the segment directory exists. Runs before section 6 writes any patch.

## 6. Merging parallel reports

### 6.1 The problem, measured (2026-10-04, read-only)

Ingest dedupe (`corpus_engine/ingest/dedupe.py`) merges cases that share a normalized citation
in CAP's metadata. Copies whose metadata does not cite each other stay separate, e.g. *Jacobs*
as 98 N.Y. 98 (case 558002) and 2 N.Y. Crim. 539 (case 1167707).

- Canonical cases sharing jurisdiction, court, decision year and full normalized name, in
  different reporters: 75,260 groups, 96,125 cases beyond the first.
- Text of 300 random pairs (word 5-gram containment): at least 0.8 for 109 pairs, 0.5-0.8 for
  156, 0.2-0.5 for 9, below 0.2 for 26. Pairs in the 0.5-0.8 band read as the same opinion
  (headnotes, syllabi and OCR noise lower the score). Estimate: about 80,000 canonical cases are
  second copies, mostly N.Y. (*Misc.* / *A.D.* vs *N.Y.S.* vs *N.Y. St. Rep.*), then Tex. and Ohio.
- Ledger: 117 groups carry two or more relevant records (the 129 extra records found for the
  explainer); 171 more groups carry one.

### 6.2 Detection

`corpus_engine/ingest/parallel.py` (pure functions plus one corpus runner):

- Candidate groups: canonical cases (`is_duplicate_of IS NULL`) with equal jurisdiction, court
  and decision year, equal normalized `name_abbreviation`, and at least two reporters.
- Guards on every pair: decision dates prefix-compatible ("1908-04" is compatible with
  "1908-04-24"; two different full dates are not); shingle-set size ratio within 0.5-2.0;
  both texts at least 50 word 5-grams long (two different memorandum decisions in one case,
  "Judgment affirmed, with costs", would otherwise match on boilerplate). Normalized names
  shorter than 6 characters never group.
- Score: word-shingle containment, |A ∩ B| / min(|A|, |B|), on `norm_text`. Shingle size (3 or 5)
  and the threshold are set by calibration (6.3) and recorded in the method version string
  (e.g. `parallel-v1:w5:0.55`).
- Within a group, each member is scored against the group's winner (6.4) and merges only if it
  passes; a member that fails stays canonical.

`tools/merge_parallel_reports.py score` writes every candidate pair with its score and guards to
`runs/parallel-reports/candidates.jsonl` (read-only on the corpus; ignored by git, tens of MB).
`apply` writes the merges it made to `runs/parallel-reports/merges.jsonl`, which is committed.

### 6.3 Calibration

A stratified sample from `candidates.jsonl`, about 25 pairs per score band across 0.2-1.0, is
read by a Claude agent that sees both opinions side by side and labels each pair *same opinion*
or *different*. The threshold is the lowest band boundary above which the sample holds no
*different* pair. A wrong merge hides a case from all future reading; a missed merge costs one
extra read, so ties go to the higher threshold. The labelled sample and the chosen threshold are
committed as `runs/parallel-reports/calibration.json` and summarized for the user before 6.5.

### 6.4 Winner

1. If any member has a relevant ledger record, the winner is the ledger keeper among them
   (6.6). This keeps every group with one relevant ledger record exactly as it is in the ledger.
2. Otherwise, if any member has a ledger record (read and found not relevant), that one, so the
   unread copy is not read again.
3. Otherwise the official-reporter copy (the rule `dedupe.py` already uses).
4. Otherwise the lowest `case_id`.

### 6.5 Apply and undo (corpus)

New table `parallel_reports(loser INTEGER PRIMARY KEY, winner INTEGER, score REAL, method TEXT,
run_id TEXT, ts TEXT)`. `tools/merge_parallel_reports.py apply --method <version>` writes the
rows and sets `cases.is_duplicate_of = winner` only where it is NULL; the citation-based marks
are never touched. `undo --method <version>` clears `is_duplicate_of` for exactly the losers it
recorded and deletes those rows. `--dry-run` prints counts per jurisdiction and per era.
Gate: the user sees the calibration summary and the dry-run counts and says go before apply.

### 6.6 Ledger reconcile

In each merged group with two or more ledger records, one record is kept: the human-reviewed
one (`view.reviewed`) first, then the one with more verified quotes, then the official cite,
then the lowest `case_id`.

- Every other ledger record in the group gets one patch: `set duplicate_of = <keeper case_id>`,
  basis `rule_id = parallel-report-merge-v1` plus the run id. The record stays in its cycle
  file with its fields as they were (history is kept).
- `tally._population` skips records carrying `duplicate_of`, so `counts()`, the tradition matrix
  and everything built on them (the evaluation, the explainer snapshot) follow. Relevant falls by
  about 129.
- Not changed: `seed_set` (a duplicate copy is still a genuine reviewed opinion, and changing the
  seed hash would invalidate coverage of the two seeded selectors); ranker labels.
- The review queue skips records carrying `duplicate_of`; a future audit draw excludes them from
  its frame.
- The group is not patched, and goes on a short list for the user to decide, when the copies'
  ledger records disagree on `relevant` (one read relevant, another read or withdrawn as not
  relevant: two readings of one opinion), or when the non-keeper holds a human-set value on a
  judged field that differs from the keeper's.
- `tools/merge_parallel_reports.py reconcile` runs dry first (patch list, count deltas, the
  user's list), then applies with the user's go.

### 6.7 Follow-on rules

- No future read of a loser: batch building (`selector.packing.build_batches`, used by
  `pipeline/shard.py` and `pipeline/rank.py`) drops cases with `is_duplicate_of` set, and
  `tools/map_reader.py` refuses to start on a batch directory that holds one (the shard-02
  tail was packed before the merge), naming the re-pack. Planning amendment: the design said
  the case source would skip such a case at read time; admission re-derives every batch
  offline from the batch files, so a read-time filter would make admission disagree with what
  was read. Refusing and re-packing keeps the two in step.
- Gold recovery follows the merge: `tools/evaluate.py` loads loser-to-winner from
  `parallel_reports` and the gold measure scores a gold case at its winner. `gold.jsonl` and its
  pinned sha are unchanged.
- Cell sizes, partition counts and the explainer's "canonical cases" figure fall by the merged
  count. Checkpoint 2 must restate the library figure; re-running Checkpoint 1's snapshot would
  now give a different number (added to the Checkpoint 2 cautions).

### 6.8 Known limits

Copies whose court or name is written differently between reporters, and copies in different
decision years, are not candidates in this version. Scores near the threshold are decided by the
calibration sample, not by reading every pair.

## 7. Testing

- Patch log: segment rotation at the cap; one append never splits; read order across segments;
  both-layouts error; content hash of a split log equals the hash of the same bytes as one file;
  migration refuses a second run and refuses on a byte mismatch.
- Parallel reports: candidate grouping and guards on the fixture corpus; containment scoring;
  winner rule order; apply sets only NULL marks; undo restores exactly; dry run writes nothing.
- Ledger: a `duplicate_of` set patch round-trips through fold and render; `counts()` and
  `matrix()` exclude the record; the queue skips it; the drift check ignores the new field; a
  `relevant` disagreement and a human-value disagreement each go to the user's list instead of
  a patch; the winner rule prefers a relevant ledger copy over an irrelevant one.
- Follow-ons: batch building drops a loser; the case source skips one in a packed batch; gold
  scoring maps a loser to its winner.
- Environment: full suite on the rebuilt `.venv`, plus the GPU, encoder and KWIC checks in 4.4.

## 8. Sequencing

1. Push the 36 commits.
2. Housekeeping commits and the two test fixes.
3. Rebuild the environment; everything after runs on it.
4. Patch-log split (code, then the migration, hash checked).
5. Parallel reports: code; `score` over the corpus; calibration read; user gate; corpus `apply`.
6. Ledger reconcile: dry run; user's list; user gate; apply.
7. Follow-on rules (batch filter, read-time skip, gold mapping); README, CONTEXT ("parallel
   report"), the cycle-004 handoff, the Checkpoint 2 cautions.
8. Full suite, push.

## 9. Parked

- The `keep` provenance gap (part 2).
- KWIC proximity and a per-jurisdiction frequency filter (part 1).
- Parallel reports across name variants, courts or years (6.8).
- `pipeline/build_gold.py` resolves a gold cite only to a canonical case; after the merge a
  cite that names a losing copy would not resolve. `gold.jsonl` is frozen and not rebuilt
  here; make the lookup follow `is_duplicate_of` before any gold rebuild.
- The groups on the reconcile's user list are decided in a later review round (a `relevant`
  disagreement does not double-count; a human-value disagreement does until decided).
- Deleting `.venv-hermes` (after the first successful run).

## 10. As built (2026-10-04)

Branch `readiness/pre-gluck`; suite 847 passed + 1 xfail (812 + 1 at the start).

- Environment: `.venv` on uv CPython 3.11.15 (`home` = uv's 3.11 minor link), installed from
  `requirements-lock.txt` (52 packages, freeze == lock); GPU, Qwen query encoder and KWIC
  verified. `.venv-hermes` kept as the fallback.
- Patch log: three segments (25,000,344 / 25,000,123 / 4,189,290 bytes at the split); content
  hash b84796f0 unchanged; the reconcile's 92 patches went to `0003.jsonl`.
- Parallel reports: 96,125 candidate pairs in 75,260 groups; 74,627 pass the guards (date
  16,826, size 12,302, length 1,538 fail). Blind calibration: 200 stratified pairs plus 50 from
  the 0.5-0.6 band at the user's request (25 Tex. Crim. App., 25 other courts): 236 same, 14
  different (9 Texas companion appeals, the rest New York motion/reargument pairs), 0 unsure;
  the highest different scored c5 0.484. Threshold c5 >= 0.5 (user's choice), method
  `parallel-v1:w5:0.5`: 68,962 applied, 2,911 skipped as targets, 0 stale. Canonical cases
  1,874,141 -> 1,805,179.
- Ledger: 92 `duplicate_of` patches (seq 83,532-83,623); relevant 4,351 -> 4,259 (1,477 / 2,782),
  favorable 1,954 -> 1,906, favorable householder 397 -> 379; 35 groups on the user's list.

Amendments made while building: the minimum-length guard (6.2); `map_reader` refuses a pool
holding a merged copy instead of skipping at read time (6.7); `build_gold` parked (9);
`apply` skips a loser other cases already point at, counted as `target`, so no chain forms;
the target set is read once per run (the first live apply, with a per-pair lookup, was stopped
at the one-hour limit having committed nothing); `apply` merges only pairs inside the
sampled c5 region (c5 >= 0.2) whatever measure the calibration picks; output files are
written LF.
