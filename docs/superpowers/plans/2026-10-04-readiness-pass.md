# Readiness Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the STR corpus pipeline in shape for the Gluck work: remote current, a Python environment that cannot vanish, a patch log inside GitHub's limits, and parallel reports merged so one decision is one case.

**Architecture:** Four independent fixes in the order the spec sets. The patch log becomes numbered segments whose concatenation is the old file byte for byte. Parallel reports are found by court, year, name and opinion-text containment (`corpus_engine/ingest/parallel.py`), calibrated by a blind read, recorded reversibly in a `parallel_reports` table, and reconciled into the ledger with a `duplicate_of` field that `tally._population` skips.

**Tech Stack:** Python 3.11.15, SQLite (corpus.db, 84 GB, WAL), pytest, uv (standalone CPython), git.

**Spec:** `docs/superpowers/specs/2026-10-04-readiness-pass-design.md`

## Global Constraints

- Work on branch `readiness/pre-gluck` in the main checkout, not a worktree: `data/db/corpus.db` and `.venv` are untracked and resolve from the checkout root. The user merges locally.
- Run Python as `.venv/Scripts/python` from the repo root; tests as `.venv/Scripts/python -m pytest -q -p no:cacheprovider` (pyproject sets `pythonpath = ["."]`).
- Files are UTF-8 with LF line endings.
- Never commit or push `.env`, `data/db/`, `data/raw/`, `reports/explainer/`.
- The audit stays pending: nothing may change `relevant`, `polarity` or `who_was_letting` on a record listed in `runs/audit-cycle-004/sample-manifest.json`.
- `SEGMENT_CAP_BYTES = 25_000_000`; segments are `data/ledger/patches/NNNN.jsonl`.
- The split must keep `ledger_content_sha256` at `b84796f05f9cfbc535f91a255c81d61ed44f623df34b51c6b6d0299483253932`.
- Merge method strings look like `parallel-v1:w5:0.55`; the ledger rule id is `parallel-report-merge-v1`.
- User gates: before the corpus `apply` (Task 8) and before the ledger `reconcile` apply (Task 9).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Tasks 1, 2, 8, 9 and 10 are controller tasks (pushes, the environment the agents run in, live data, user gates). Tasks 3-7 can go to implementer subagents.

## Review Focus

- A ledger directory that still holds the old single `patches.jsonl` must be refused with a message naming `tools/split_patch_log.py`, never opened as an empty log whose next apply restarts at seq 1. (Task 3, `test_an_unmigrated_ledger_is_refused_not_restarted`.)
- Re-running `apply` after a partial or complete run must skip losers already merged and report them, with no primary-key error. (Task 4, `test_apply_is_idempotent_and_skips_a_stale_winner`.)
- A winner that is no longer canonical by the time `apply` reaches it (marked earlier in the same run, or since `score`) must be skipped as stale, never chained. (Task 4, same test.)
- Empty or very short opinion texts must never merge, however alike. (Task 4, `test_score_group_measures_both_sizes_and_guards_short_and_empty_texts`.)
- A calibration pair labelled `unsure` must count against the threshold exactly like `different`. (Task 6, `test_threshold_is_the_lowest_bound_above_every_pair_not_labelled_same`.)

---

### Task 1: Push, branch, housekeeping (controller)

**Files:**
- Modify: `.gitignore`
- Modify: `tests/conftest.py:34-39` (`fixture_db`)
- Modify: `tests/test_verification_char.py:24`
- Modify: `tests/test_fixture_corpus.py` (one new test)
- Commit as-is: `reports/gold-codebook-review-2026-09-29.md`, `runs/cycle-004-shard-01/shard-manifest.json`, `runs/cycle-001-shard-02/fuzzy-auto-accepted.json`, `runs/cycle-002-shard-01/fuzzy-auto-accepted.json`

**Interfaces:**
- Produces: `fixture_db` now yields a per-session copy under pytest's tmp dir (same bytes as `tests/fixtures/corpus-tiny.db`).

- [ ] **Step 1: Check nothing secret is tracked, then push main**

```bash
git ls-files | grep -E '^\.env$|^data/db/|^data/raw/|^reports/explainer/' && echo "STOP: secret or data tracked" || echo ok
git push origin main
git rev-list --count origin/main..main
```
Expected: `ok`, a successful push (GitHub may warn that `data/ledger/patches.jsonl` is over 50 MB; that is the file Task 3 splits), then `0`.

- [ ] **Step 2: Branch**

```bash
git switch -c readiness/pre-gluck
```

- [ ] **Step 3: Write the failing test for the fixture copy**

Append to `tests/test_fixture_corpus.py`:

```python
def test_fixture_db_is_a_session_copy_not_the_tracked_file(fixture_db, repo_root):
    """Tests open the fixture with store.connect (WAL) and some write to it; the tracked file
    and its directory must never see a -wal/-shm or a write (spec 2026-10-04 section 3)."""
    tracked = repo_root / "tests" / "fixtures" / "corpus-tiny.db"
    assert fixture_db != tracked
    assert fixture_db.parent != tracked.parent
    assert fixture_db.stat().st_size == tracked.stat().st_size
```

- [ ] **Step 4: Run it to see it fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_fixture_corpus.py::test_fixture_db_is_a_session_copy_not_the_tracked_file`
Expected: FAIL on `assert fixture_db != tracked`.

- [ ] **Step 5: Make `fixture_db` a session copy**

In `tests/conftest.py` add `import shutil` to the imports and replace the `fixture_db` fixture with:

```python
@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory) -> Path:
    """A per-session copy of tests/fixtures/corpus-tiny.db. Tests open it with store.connect
    (WAL) and some write to it; the copy keeps the tracked file, and its directory, untouched."""
    src = REPO / "tests" / "fixtures" / "corpus-tiny.db"
    if not src.exists():
        pytest.skip("tests/fixtures/corpus-tiny.db not built yet (Task 3)")
    dst = tmp_path_factory.mktemp("fixture-db") / "corpus-tiny.db"
    shutil.copyfile(src, dst)
    return dst
```

- [ ] **Step 6: Open the live corpus read-only in the characterization test**

In `tests/test_verification_char.py`, `test_verified_files_reproduce_for_all_cycle_003`, replace `conn = sqlite3.connect(live_db)` with:

```python
    conn = sqlite3.connect(f"file:{live_db.as_posix()}?mode=ro", uri=True)
```

- [ ] **Step 7: Ignore local scratch and the retired guide**

Append to `.gitignore`:

```
# Local scratch, and the retired Sept 14 guide, kept off the public repo (2026-10-04)
.tmp/
.playwright-mcp/
cl.html
reports/right-to-let-guide.html
reports/right-to-let-guide-sources.md
runs/*.err
tests/fixtures/*.db-shm
tests/fixtures/*.db-wal
```

- [ ] **Step 8: Remove the stale fixture side files and run the suite**

```bash
rm -f tests/fixtures/corpus-tiny.db-shm tests/fixtures/corpus-tiny.db-wal
.venv/Scripts/python -m pytest -q -p no:cacheprovider
ls tests/fixtures | grep -E 'db-(shm|wal)$' || echo "no side files"
git status --short
```
Expected: `813 passed, 1 xfailed` (812 + the new test), `no side files`, and `git status` lists only the edited files plus the four files to commit.

- [ ] **Step 9: Commit**

```bash
git add .gitignore tests/conftest.py tests/test_verification_char.py tests/test_fixture_corpus.py \
  reports/gold-codebook-review-2026-09-29.md runs/cycle-004-shard-01/shard-manifest.json \
  runs/cycle-001-shard-02/fuzzy-auto-accepted.json runs/cycle-002-shard-01/fuzzy-auto-accepted.json
git commit -F - <<'EOF'
housekeeping: fixture_db is a session copy (no WAL files beside the tracked fixture); the live characterization test opens corpus.db read-only; ignore scratch and the retired guide; commit the gold codebook review and two run artifacts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Python environment off the Hermes runtime (controller)

**Files:**
- Create: `requirements-lock.txt`
- Modify: `.gitignore` (add `.venv-hermes/`)
- Modify: `README.md:9-15` (setup lines)

**Interfaces:**
- Produces: `.venv` built from uv's CPython 3.11.15; `.venv-hermes` kept as a fallback.

- [ ] **Step 1: Freeze the working environment**

```bash
.venv/Scripts/python -m pip freeze > .tmp/freeze.txt
grep -nE '@ file:|^-e ' .tmp/freeze.txt || echo "no local or editable installs"
wc -l .tmp/freeze.txt
```
Expected: `no local or editable installs`, 52 lines. If either check fails, stop and report the lines.

- [ ] **Step 2: Write the lock file**

```bash
{ printf '%s\n' "# Exact environment, frozen 2026-10-04 from the working .venv (CPython 3.11.15)." \
    "# Install: .venv\\Scripts\\python -m pip install -r requirements-lock.txt" \
    "--extra-index-url https://download.pytorch.org/whl/cu128"; cat .tmp/freeze.txt; } > requirements-lock.txt
head -5 requirements-lock.txt
```

- [ ] **Step 3: Confirm nothing is running from the venv**

Run (PowerShell): `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*Str-corpus*.venv*' } | Select-Object ProcessId, CommandLine`
Expected: no rows. If any, stop and ask the user.

- [ ] **Step 4: Move the old venv aside and build the new one**

```bash
mv .venv .venv-hermes
uv venv --seed --python "C:/Users/marcu/AppData/Roaming/uv/python/cpython-3.11.15-windows-x86_64-none/python.exe" .venv
cat .venv/pyvenv.cfg
```
Expected: `home = C:\Users\marcu\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none`, `version_info = 3.11.15`.

- [ ] **Step 5: Install the lock (torch is a large download; allow 20 minutes)**

```bash
.venv/Scripts/python -m pip install -r requirements-lock.txt
diff <(grep -vE '^(#|--)' requirements-lock.txt | sort) <(.venv/Scripts/python -m pip freeze | sort) && echo "freeze matches lock"
```
Expected: `freeze matches lock`.

- [ ] **Step 6: Verify the GPU, the query encoder, KWIC and the suite**

```bash
.venv/Scripts/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
.venv/Scripts/python -c "from corpus_engine import store; from corpus_engine.selector.ports import LocalQueryEmbedder; v = LocalQueryEmbedder(store.connect(wal=False)).encode_query('taking in lodgers'); print(v.shape, round(float((v * v).sum()), 3))"
.venv/Scripts/python pipeline/kwic.py freq lodger
.venv/Scripts/python -m pytest -q -p no:cacheprovider
```
Expected: `2.11.0+cu128 True`; a vector shape and `1.0`; one `lodger` row of per-era counts; `813 passed, 1 xfailed`.

- [ ] **Step 7: README and ignore**

In `README.md` replace the two install lines under "Reproduce from a clean machine" (`python -m venv .venv` through the `requirements-ranker.txt` line and its comment continuation) with:

```
uv venv --seed --python 3.11.15 .venv      # standalone CPython (not an app-bundled interpreter)
.venv\Scripts\python -m pip install -r requirements-lock.txt   # exact versions, incl. torch +cu128
# requirements.txt / requirements-ranker.txt list the direct dependencies the lock was built from
```

Append `.venv-hermes/` to `.gitignore` under the `.venv/` line.

- [ ] **Step 8: Commit**

```bash
git add requirements-lock.txt README.md .gitignore
git commit -F - <<'EOF'
env: rebuild .venv on uv's standalone CPython 3.11.15 from an exact lock (the old venv sat on the Hermes agent's bundled interpreter); .venv-hermes kept as a fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Patch-log segments and the live migration

**Files:**
- Modify: `corpus_engine/ledger/log.py` (whole file)
- Modify: `corpus_engine/ledger/ledger.py:7,141`
- Modify: `corpus_engine/evaluation/summary.py:38-46`
- Modify: `tools/bootstrap_ledger.py:10-11`
- Create: `tools/split_patch_log.py`
- Create: `tests/test_ledger_log_segments.py`, `tests/test_split_patch_log.py`
- Modify tests: `tests/test_ledger_fold.py:71-77`, `tests/test_ledger_apply.py:26`, `tests/test_mapper_admit.py:399,509`, `tests/test_evaluate_tool.py:121`, `tests/test_ledger_committed.py:30`
- Data: `data/ledger/patches.jsonl` -> `data/ledger/patches/0001.jsonl` ... (the controller runs Step 11)

**Interfaces:**
- Produces: `corpus_engine.ledger.log`: `SEGMENT_DIR = "patches"`, `LEGACY_FILE = "patches.jsonl"`, `SEGMENT_CAP_BYTES = 25_000_000`, `SEGMENT_GLOB`, `segment_name(n: int) -> str`, `log_files(ledger_dir: Path) -> list[Path]`, `PatchLog(dir: Path, *, cap_bytes: int = SEGMENT_CAP_BYTES)` with `segments() -> list[Path]`, `read()`, `head()`, `append()`.
- Produces: `corpus_engine.evaluation.summary.sha256_over(paths) -> str`; `ledger_content_sha256(ledger_dir)` unchanged in signature and value.
- Produces: `tools/split_patch_log.py`: `cut(data: bytes, cap: int) -> list[bytes]`, `split(ledger_dir: Path, *, cap: int = SEGMENT_CAP_BYTES, expect_sha: str | None = None) -> list[Path]`.

- [ ] **Step 1: Write the failing segment tests**

Create `tests/test_ledger_log_segments.py`:

```python
"""The patch log as numbered segments (spec 2026-10-04 section 5)."""
import json
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.evaluation.summary import ledger_content_sha256
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.log import PatchLog, log_files
from corpus_engine.ledger.types import Basis, LedgerError, Patch


def _p(i: int) -> Patch:
    return Patch(i, "set", "polarity", "adverse", f"why {i}", Basis(reviewer="m"))


def test_appends_rotate_at_the_cap_and_read_back_in_seq_order(tmp_path):
    log = PatchLog(tmp_path / "patches", cap_bytes=600)
    log.append([_p(1), _p(2)])
    assert [p.name for p in log.segments()] == ["0001.jsonl"]
    while log.segments()[-1].stat().st_size < 600:
        log.append([_p(9)])
    n_before = log.head()
    log.append([_p(3), _p(4)])
    assert [p.name for p in log.segments()] == ["0001.jsonl", "0002.jsonl"]
    assert [p.seq for p in log.read()] == list(range(1, n_before + 3))
    assert log.head() == n_before + 2
    first = json.loads((tmp_path / "patches" / "0002.jsonl").read_text().splitlines()[0])
    assert first["seq"] == n_before + 1          # segment 2 starts where segment 1 ended


def test_one_append_never_spans_two_segments(tmp_path):
    log = PatchLog(tmp_path / "patches", cap_bytes=300)
    log.append([_p(i) for i in range(1, 11)])    # far over the cap in one append
    assert [p.name for p in log.segments()] == ["0001.jsonl"]
    assert log.head() == 10


def test_an_empty_append_writes_nothing(tmp_path):
    log = PatchLog(tmp_path / "patches")
    assert log.append([]) == []
    assert not (tmp_path / "patches").exists()


def test_an_unmigrated_ledger_is_refused_not_restarted(tmp_path):
    """Review focus 1: a directory still holding the old single file must not open as an
    empty segmented log - the next apply would restart the seqs at 1."""
    (tmp_path / "patches.jsonl").write_text(json.dumps({"seq": 1}) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="split_patch_log"):
        PatchLog(tmp_path / "patches").read()
    with pytest.raises(LedgerError, match="split_patch_log"):
        PatchLog(tmp_path / "patches").append([_p(1)])
    with pytest.raises(LedgerError):
        open_ledger(tmp_path, domain=load_domain()).view()
    assert not (tmp_path / "patches").exists()


def test_both_layouts_in_one_directory_are_refused(tmp_path):
    (tmp_path / "patches.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "patches").mkdir()
    (tmp_path / "patches" / "0001.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="both"):
        log_files(tmp_path)


def test_the_content_hash_is_the_same_split_or_whole(tmp_path):
    whole, split = tmp_path / "whole", tmp_path / "split"
    for d in (whole, split):
        d.mkdir()
        (d / "cycle-001.jsonl").write_bytes(b'{"b":2}\n')
    (whole / "patches.jsonl").write_bytes(b'{"a":1}\n{"a":2}\n{"a":3}\n')
    (split / "patches").mkdir()
    (split / "patches" / "0001.jsonl").write_bytes(b'{"a":1}\n{"a":2}\n')
    (split / "patches" / "0002.jsonl").write_bytes(b'{"a":3}\n')
    assert ledger_content_sha256(whole) == ledger_content_sha256(split)


def test_a_ledger_applies_through_segments(tmp_path):
    led = open_ledger(tmp_path, domain=load_domain())
    rec = {"case_id": 1, "cite": "1 X", "year": 1850, "relevant": True, "polarity": "favorable",
           "who_was_letting": "householder", "duration_of_occupancy": "nights",
           "characterization": "lodging", "holding_summary": "h",
           "quotes": [{"text": "q", "supports": "polarity"}], "extraction_status": "ok"}
    res = led.apply([Patch(1, "admit", "", rec, "v",
                           Basis(model="m", prompt_version="v", run_id="r"), cycle="cycle-001")],
                    note="seed")
    assert res.replay_ok
    assert (tmp_path / "patches" / "0001.jsonl").exists()
    assert not (tmp_path / "patches.jsonl").exists()
    assert led.log.head() == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_ledger_log_segments.py`
Expected: FAIL at import (`cannot import name 'log_files'`).

- [ ] **Step 3: Rewrite `corpus_engine/ledger/log.py`**

Keep `patch_id` and `provisional_seqs` exactly as they are. Replace the module docstring, the imports and `class PatchLog`, and add the constants and two functions:

```python
"""Append-only patch log, stored as numbered segments: data/ledger/patches/NNNN.jsonl.

The log is one sequence of patches (seq 1..head). Each segment holds a contiguous seq range,
segment n+1 starting where segment n ended, so the segments concatenated in name order are
the log byte for byte - what `evaluation.summary.ledger_content_sha256` hashes. Only the last
segment is appended to; an append that finds it at or over `SEGMENT_CAP_BYTES` opens the next
one, and one append never spans two segments (spec 2026-10-04 section 5). The old single file
`patches.jsonl` is refused: `tools/split_patch_log.py` converts it."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import replace
from pathlib import Path
from corpus_engine.ledger.types import LedgerError, Patch

SEGMENT_DIR = "patches"
LEGACY_FILE = "patches.jsonl"
SEGMENT_CAP_BYTES = 25_000_000
SEGMENT_GLOB = "[0-9][0-9][0-9][0-9].jsonl"


def segment_name(n: int) -> str:
    return f"{n:04d}.jsonl"


def log_files(ledger_dir: Path) -> list[Path]:
    """The files holding a ledger directory's patch log, in log order: the segments, or the
    old single file on its own (so the migration can hash it before it splits it). A
    directory holding both layouts is refused, never merged."""
    legacy = ledger_dir / LEGACY_FILE
    segdir = ledger_dir / SEGMENT_DIR
    segs = sorted(segdir.glob(SEGMENT_GLOB)) if segdir.is_dir() else []
    if legacy.exists() and segs:
        raise LedgerError(f"{ledger_dir} holds both {LEGACY_FILE} and {SEGMENT_DIR}/; "
                          "one layout only (tools/split_patch_log.py)")
    return [legacy] if legacy.exists() else segs
```

and, after `provisional_seqs`:

```python
class PatchLog:
    """The log of one ledger. `dir` is its segment directory, `<ledger>/patches`."""

    def __init__(self, dir: Path, *, cap_bytes: int = SEGMENT_CAP_BYTES):
        self.dir = dir
        self.cap_bytes = cap_bytes

    def segments(self) -> list[Path]:
        legacy = self.dir.parent / LEGACY_FILE
        if legacy.exists():
            raise LedgerError(f"{legacy} is the old single-file log; run "
                              "tools/split_patch_log.py before opening this ledger")
        return sorted(self.dir.glob(SEGMENT_GLOB)) if self.dir.is_dir() else []

    def read(self) -> list[Patch]:
        out = []
        for seg in self.segments():
            out += [Patch.from_json(json.loads(l))
                    for l in seg.read_text(encoding="utf-8").splitlines() if l.strip()]
        return sorted(out, key=lambda p: p.seq)

    def head(self) -> int:
        ps = self.read()
        return ps[-1].seq if ps else 0

    def _target(self) -> Path:
        segs = self.segments()
        if not segs:
            return self.dir / segment_name(1)
        if segs[-1].stat().st_size >= self.cap_bytes:
            return self.dir / segment_name(int(segs[-1].stem) + 1)
        return segs[-1]

    def append(self, patches: list[Patch], *, at: str | None = None) -> list[Patch]:
        if not patches:
            return []
        seq = self.head()                       # refuses an unmigrated ledger before any write
        stamp = at or time.strftime("%Y-%m-%dT%H:%M:%S")
        stamped = []
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._target().open("a", encoding="utf-8", newline="\n") as f:
            for p in patches:
                seq += 1
                q = replace(p, seq=seq, at=p.at or stamp, patch_id=patch_id(p))
                f.write(json.dumps(q.to_json(), ensure_ascii=True) + "\n")
                stamped.append(q)
        return stamped
```

- [ ] **Step 4: Point the ledger at the segment directory**

In `corpus_engine/ledger/ledger.py` change the import line to
`from corpus_engine.ledger.log import SEGMENT_DIR, PatchLog, patch_id, provisional_seqs`
and in `Ledger.__init__` replace `self.log = PatchLog(self.dir / "patches.jsonl")` with
`self.log = PatchLog(self.dir / SEGMENT_DIR)`.

- [ ] **Step 5: Hash the segments in `corpus_engine/evaluation/summary.py`**

Add `from corpus_engine.ledger.log import log_files` to the imports and replace `ledger_content_sha256` with:

```python
def sha256_over(paths) -> str:
    """sha256 over the files' bytes in the given order, CRLF and CR folded to LF per file."""
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
    return h.hexdigest()


def ledger_content_sha256(ledger_dir: Path) -> str:
    """The patch log (its segments in order, or the old single file) and then the cycle files.
    The segments concatenate to the old file, so the split leaves this value unchanged."""
    return sha256_over(log_files(ledger_dir) + sorted(ledger_dir.glob("cycle-*.jsonl")))
```

- [ ] **Step 6: Run the segment tests**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_ledger_log_segments.py`
Expected: 7 passed.

- [ ] **Step 7: Write the failing migration tests**

Create `tests/test_split_patch_log.py`:

```python
"""tools/split_patch_log.py: the one-time cut of the single-file log into segments."""
import importlib.util
from pathlib import Path
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.evaluation.summary import ledger_content_sha256
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("split_patch_log", ROOT / "tools" / "split_patch_log.py")
spl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spl)
READER = Basis(model="m", prompt_version="v", run_id="r")


def _rec(cid):
    return {"case_id": cid, "cite": f"{cid} X", "year": 1850, "relevant": True,
            "polarity": "favorable", "who_was_letting": "householder",
            "duration_of_occupancy": "nights", "characterization": "lodging",
            "holding_summary": "h", "quotes": [{"text": "q", "supports": "polarity"}],
            "extraction_status": "ok"}


def _legacy_ledger(root: Path, n: int = 6) -> Path:
    """A ledger written through segments, then folded back into the old single file - the
    shape the live ledger has before the migration."""
    led = open_ledger(root, domain=load_domain())
    for i in range(1, n + 1):
        led.apply([Patch(i, "admit", "", _rec(i), "v", READER, cycle="cycle-001")], note=f"seed {i}")
    (root / "patches" / "0001.jsonl").replace(root / "patches.jsonl")
    (root / "patches").rmdir()
    return root


def test_cut_keeps_lines_whole_and_closes_a_piece_at_the_cap():
    data = b"".join(b"%03d" % i + b"x" * 26 + b"\n" for i in range(10))   # ten 30-byte lines
    pieces = spl.cut(data, 100)
    assert b"".join(pieces) == data
    assert [len(p) for p in pieces] == [120, 120, 60]     # a piece takes lines until it reaches 100
    assert all(p.endswith(b"\n") for p in pieces)


def test_split_keeps_the_bytes_the_hash_and_the_replay(tmp_path):
    root = _legacy_ledger(tmp_path)
    old = (root / "patches.jsonl").read_bytes()
    before = ledger_content_sha256(root)
    segs = spl.split(root, cap=len(old) // 3, expect_sha=before)
    assert len(segs) >= 2 and not (root / "patches.jsonl").exists()
    assert b"".join(p.read_bytes() for p in segs) == old
    assert ledger_content_sha256(root) == before
    led = open_ledger(root, domain=load_domain())
    assert led.log.head() == 6 and led.view().counts().total.machine_only == 6
    led.apply([Patch(99, "admit", "", _rec(99), "v", READER, cycle="cycle-001")], note="after")
    assert led.log.head() == 7                             # the seq carries on, not restarts


def test_split_refuses_a_wrong_hash_and_a_second_run(tmp_path):
    root = _legacy_ledger(tmp_path)
    with pytest.raises(SystemExit, match="expected"):
        spl.split(root, expect_sha="0" * 64)
    assert (root / "patches.jsonl").exists() and not (root / "patches").exists()
    assert not (root / ".lock").exists()
    spl.split(root)
    with pytest.raises(SystemExit, match="already split"):
        spl.split(root)
```

- [ ] **Step 8: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_split_patch_log.py`
Expected: FAIL (`tools/split_patch_log.py` does not exist).

- [ ] **Step 9: Write `tools/split_patch_log.py`**

```python
"""One-time: split data/ledger/patches.jsonl into data/ledger/patches/NNNN.jsonl segments
(spec 2026-10-04 section 5.4). Writes the segments beside the old file, checks that they
concatenate to its bytes and that the ledger content hash is unchanged, and only then swaps
them in and removes the old file. Holds the ledger lock throughout.

  .venv/Scripts/python tools/split_patch_log.py --expect-sha <published content_sha256>"""
from __future__ import annotations
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine.evaluation.summary import ledger_content_sha256, sha256_over     # noqa: E402
from corpus_engine.ledger.log import (LEGACY_FILE, SEGMENT_CAP_BYTES, SEGMENT_DIR,  # noqa: E402
                                      segment_name)


def cut(data: bytes, cap: int) -> list[bytes]:
    """Line-boundary pieces. A piece takes no more lines once it has reached `cap` bytes -
    the same rule `PatchLog.append` applies to the active segment."""
    pieces, cur, size = [], [], 0
    for line in data.splitlines(keepends=True):
        if cur and size >= cap:
            pieces.append(b"".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        pieces.append(b"".join(cur))
    return pieces


def split(ledger_dir: Path, *, cap: int = SEGMENT_CAP_BYTES,
          expect_sha: str | None = None) -> list[Path]:
    legacy, segdir = ledger_dir / LEGACY_FILE, ledger_dir / SEGMENT_DIR
    if segdir.exists():
        raise SystemExit(f"{segdir} exists; the log is already split")
    if not legacy.exists():
        raise SystemExit(f"no {legacy} to split")
    lock = ledger_dir / ".lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # FileExistsError: a writer is active
    try:
        data = legacy.read_bytes()
        if not data.endswith(b"\n"):
            raise SystemExit(f"{legacy} does not end in a newline; refusing to cut it")
        before = ledger_content_sha256(ledger_dir)
        if expect_sha and before != expect_sha:
            raise SystemExit(f"content hash {before} is not the expected {expect_sha}; "
                             "nothing written")
        tmp = ledger_dir / f"{SEGMENT_DIR}.split-tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        paths = []
        for i, piece in enumerate(cut(data, cap), 1):
            p = tmp / segment_name(i)
            p.write_bytes(piece)
            paths.append(p)
        if b"".join(p.read_bytes() for p in paths) != data:
            shutil.rmtree(tmp)
            raise SystemExit("the segments do not concatenate to the original bytes; nothing changed")
        if sha256_over(paths + sorted(ledger_dir.glob("cycle-*.jsonl"))) != before:
            shutil.rmtree(tmp)
            raise SystemExit("the content hash would move; nothing changed")
        tmp.rename(segdir)
        legacy.unlink()
        after = ledger_content_sha256(ledger_dir)
        if after != before:
            raise SystemExit(f"content hash moved after the swap: {before} -> {after}")
        return sorted(segdir.glob("*.jsonl"))
    finally:
        os.close(fd)
        lock.unlink()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=str(ROOT / "data" / "ledger"))
    ap.add_argument("--expect-sha")
    a = ap.parse_args(argv)
    for p in split(Path(a.ledger), expect_sha=a.expect_sha):
        print(f"{p.name}: {p.stat().st_size} bytes")
    print(f"content sha256 {ledger_content_sha256(Path(a.ledger))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10: Bring the remaining tests and the bootstrap guard to the new layout**

- `tests/test_ledger_fold.py`, `test_patch_log_stamps_and_round_trips`: `log = PatchLog(tmp_path / "patches")` and the last line reads `(tmp_path / "patches" / "0001.jsonl").read_text()`.
- `tests/test_ledger_apply.py:26`: `assert (tmp_path / "patches" / "0001.jsonl").exists()`.
- `tests/test_mapper_admit.py:399`: `assert not (tmp_path / "ledger" / "patches").exists()`; line 509: `assert (tmp_path / "ledger" / "patches" / "0001.jsonl").exists()`.
- `tests/test_evaluate_tool.py:121`: the skip condition becomes `not (ROOT / "data" / "ledger" / "patches").exists()`.
- `tests/test_ledger_committed.py`: add `from corpus_engine.ledger.log import log_files` and replace line 30 with
  `log = "".join(p.read_text(encoding="utf-8") for p in log_files(repo_root / "data" / "ledger"))`.
- `tools/bootstrap_ledger.py` lines 10-11 become:

```python
_LEDGER = ROOT / "data" / "ledger"
if (_LEDGER / "patches.jsonl").exists() or (_LEDGER / "patches").exists():
    raise SystemExit("the patch log exists; refusing to bootstrap twice")
```

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_split_patch_log.py tests/test_ledger_log_segments.py tests/test_ledger_fold.py tests/test_ledger_apply.py tests/test_mapper_admit.py tests/test_evaluation_summary.py`
Expected: all pass. (`tests/test_ledger_committed.py` and other live-ledger tests fail until Step 11: the live ledger is not split yet and is now refused.)

- [ ] **Step 11: Split the live log (controller)**

```bash
.venv/Scripts/python tools/split_patch_log.py --expect-sha b84796f05f9cfbc535f91a255c81d61ed44f623df34b51c6b6d0299483253932
```
Expected: three segments (`0001.jsonl` and `0002.jsonl` just over 25,000,000 bytes, `0003.jsonl` about 4.2 MB) and `content sha256 b84796f05f9cfbc535f91a255c81d61ed44f623df34b51c6b6d0299483253932`.

- [ ] **Step 12: Full suite**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider`
Expected: `823 passed, 1 xfailed` (813 + 7 + 3).

- [ ] **Step 13: Commit (code and data together, so every commit replays)**

```bash
git add -A corpus_engine/ledger/log.py corpus_engine/ledger/ledger.py corpus_engine/evaluation/summary.py \
  tools/bootstrap_ledger.py tools/split_patch_log.py tests/ data/ledger/
git status --short data/ledger
git commit -F - <<'EOF'
ledger: the patch log is numbered 25 MB segments (data/ledger/patches/NNNN.jsonl) that concatenate to the old file; one-time split tool; content hash unchanged (b84796f0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Expected `git status` before the commit: `D data/ledger/patches.jsonl` and `A` for the three segments.

---

### Task 4: Parallel-report detection, apply and undo (`corpus_engine/ingest/parallel.py`)

**Files:**
- Create: `corpus_engine/ingest/parallel.py`
- Create: `tests/test_parallel_reports.py`

**Interfaces:**
- Produces: `MIN_NAME_CHARS = 6`, `MIN_SHINGLES = 50`, `SIZE_RATIO = (0.5, 2.0)`, `TABLE` (DDL);
  `normalize_name(name) -> str`; `dates_compatible(a, b) -> bool`; `shingles(text, n) -> frozenset[str]`;
  `containment(a, b) -> float`; `size_ratio_ok(a, b) -> bool`;
  `Member(case_id: int, cite: str, reporter: str, decision_date: str, official: bool)` (frozen dataclass);
  `Group(jurisdiction: str, court: str, year: int | None, name: str, era: str, members: tuple[Member, ...])`;
  `candidate_groups(conn) -> list[Group]`; `corpus_precedence(m) -> tuple`;
  `pick_winner(members, precedence=corpus_precedence) -> Member`;
  `score_group(conn, group, winner) -> list[dict]` (keys: winner, loser, winner_cite, loser_cite, jurisdiction, court, year, era, name, c3, c5, date_ok, size_ok, long_enough);
  `passes_guards(row) -> bool`; `ensure_table(conn)`;
  `apply_merges(conn, pairs: Iterable[tuple[int, int, float]], *, method, run_id, ts) -> dict` (keys applied, already, stale);
  `undo_merges(conn, method) -> int`; `winner_map(conn) -> dict[int, int]`; `losers_among(conn, case_ids) -> set[int]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parallel_reports.py`:

```python
"""Parallel reports: detection, scoring, apply and undo (spec 2026-10-04 section 6)."""
import pytest
from corpus_engine import store
from corpus_engine.ingest import parallel as par

BODY = " ".join(f"word{i}" for i in range(400))


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "c.db")
    store.ensure_schema(c)
    yield c
    c.close()


def _case(conn, cid, *, name="Smith v. Jones", court="New York Supreme Court", jur="N.Y.",
          date="1908-04-24", year=1908, reporter="nys", text=BODY, official=False, dup=None):
    cite = f"{cid} {reporter} 1"
    conn.execute("""INSERT INTO cases (case_id, name_abbreviation, cite, court, jurisdiction,
                    decision_date, decision_year, era_partition, reporter, norm_text, raw_text,
                    is_duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, name, cite, court, jur, date, year, "1900-1930", reporter, text, text, dup))
    conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                 (cid, cite, cite.lower(), "official" if official else "parallel"))
    conn.commit()


def test_names_dates_and_shingles():
    assert par.normalize_name("Smith v. Jones, Inc.") == "smith v jones inc"
    assert par.dates_compatible("1908-04", "1908-04-24")
    assert not par.dates_compatible("1908-04-23", "1908-04-24")
    assert not par.dates_compatible("", "1908")
    assert par.shingles("A b c d e f", 5) == frozenset({"a b c d e", "b c d e f"})
    assert par.containment(frozenset(), frozenset({"x"})) == 0.0


def test_candidate_groups_need_the_same_court_year_name_and_two_reporters(conn):
    _case(conn, 1, reporter="nys")
    _case(conn, 2, reporter="misc", date="1908-04")
    _case(conn, 3, reporter="misc", court="New York Court of Appeals")      # other court
    _case(conn, 4, reporter="misc", year=1909, date="1909-01")              # other year
    _case(conn, 5, reporter="ad", name="Brown v. Green")                    # one reporter only
    _case(conn, 6, reporter="ad", name="Brown v. Green")
    _case(conn, 7, reporter="misc", dup=1)                                  # already a duplicate
    _case(conn, 8, reporter="misc", name="In re")                           # name too short
    _case(conn, 9, reporter="nys", name="In re")
    groups = par.candidate_groups(conn)
    assert [[m.case_id for m in g.members] for g in groups] == [[1, 2]]
    assert (groups[0].jurisdiction, groups[0].year, groups[0].era) == ("N.Y.", 1908, "1900-1930")


def test_score_group_measures_both_sizes_and_guards_short_and_empty_texts(conn):
    _case(conn, 1, reporter="nys", official=True)
    _case(conn, 2, reporter="misc", text="Syllabus by the reporter. " + BODY)
    _case(conn, 3, reporter="ad", text=" ".join(f"other{i}" for i in range(400)))
    _case(conn, 4, reporter="hun", text="Judgment affirmed, with costs.")
    _case(conn, 5, reporter="barb", text="")
    [g] = par.candidate_groups(conn)
    winner = par.pick_winner(g.members)
    assert winner.case_id == 1                                   # the official copy
    rows = {r["loser"]: r for r in par.score_group(conn, g, winner)}
    assert rows[2]["c5"] == 1.0 and rows[2]["c3"] == 1.0 and par.passes_guards(rows[2])
    assert rows[3]["c5"] == 0.0
    assert not rows[4]["long_enough"] and not par.passes_guards(rows[4])
    assert rows[5]["c5"] == 0.0 and not rows[5]["size_ok"] and not par.passes_guards(rows[5])


def test_pick_winner_prefers_official_then_lowest_id():
    ms = [par.Member(5, "", "a", "", False), par.Member(9, "", "b", "", True),
          par.Member(2, "", "c", "", False)]
    assert par.pick_winner(ms).case_id == 9
    assert par.pick_winner([m for m in ms if not m.official]).case_id == 2


def test_apply_is_idempotent_and_skips_a_stale_winner(conn):
    for cid, rep in ((1, "nys"), (2, "misc"), (3, "nys"), (4, "misc"), (5, "ad")):
        _case(conn, cid, reporter=rep)
    res = par.apply_merges(conn, [(1, 2, 0.9), (3, 4, 0.8), (4, 5, 0.7)], method="m", run_id="r", ts="t")
    assert res == {"applied": 2, "already": 0, "stale": 1}       # 4 became a loser first: no chain
    marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases"))
    assert marks == {1: None, 2: 1, 3: None, 4: 3, 5: None}
    again = par.apply_merges(conn, [(1, 2, 0.9), (3, 4, 0.8)], method="m", run_id="r", ts="t")
    assert again == {"applied": 0, "already": 2, "stale": 0}


def test_undo_restores_exactly_and_leaves_citation_based_marks(conn):
    _case(conn, 1, reporter="nys")
    _case(conn, 2, reporter="misc")
    _case(conn, 8, reporter="nys", name="Other v. Case")
    _case(conn, 9, reporter="nys", name="Other v. Case", dup=8)        # dedupe.py's mark
    par.apply_merges(conn, [(1, 2, 0.9)], method="m1", run_id="r", ts="t")
    assert par.winner_map(conn) == {2: 1}
    assert par.losers_among(conn, [1, 2, 8, 9]) == {2, 9}
    assert par.undo_merges(conn, "m1") == 1
    marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases"))
    assert marks == {1: None, 2: None, 8: None, 9: 8}
    assert par.winner_map(conn) == {}


def test_winner_map_without_the_table_is_empty(conn):
    assert par.winner_map(conn) == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_parallel_reports.py`
Expected: FAIL at import (`cannot import name 'parallel'`).

- [ ] **Step 3: Write `corpus_engine/ingest/parallel.py`**

```python
"""Parallel reports: one decision printed in two reporters, kept as two cases because CAP's
metadata for neither copy cites the other (spec 2026-10-04 section 6). Candidates share
jurisdiction, court, decision year and normalized case name across at least two reporters;
opinion-text containment decides. Merges are recorded in `parallel_reports` so `undo` clears
exactly them and never the citation-based marks `dedupe.py` made."""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

MIN_NAME_CHARS = 6        # shorter normalized names ("in re", initials) group unrelated cases
MIN_SHINGLES = 50         # word 5-grams; below this two memorandum decisions match on boilerplate
SIZE_RATIO = (0.5, 2.0)
TABLE = """CREATE TABLE IF NOT EXISTS parallel_reports (
    loser INTEGER PRIMARY KEY REFERENCES cases(case_id),
    winner INTEGER NOT NULL REFERENCES cases(case_id),
    score REAL, method TEXT NOT NULL, run_id TEXT, ts TEXT)"""
_WORD = re.compile(r"[a-z0-9]+")


def normalize_name(name: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split())


def dates_compatible(a: str | None, b: str | None) -> bool:
    """CAP dates come at year, month or day precision ("1908", "1908-04", "1908-04-24"); two
    are compatible when the less precise one is a prefix of the other."""
    a, b = a or "", b or ""
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def shingles(text: str | None, n: int) -> frozenset[str]:
    w = _WORD.findall((text or "").lower())
    return frozenset(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))


def containment(a: frozenset, b: frozenset) -> float:
    small = min(len(a), len(b))
    return len(a & b) / small if small else 0.0


def size_ratio_ok(a: frozenset, b: frozenset) -> bool:
    return bool(a and b) and SIZE_RATIO[0] <= len(a) / len(b) <= SIZE_RATIO[1]


@dataclass(frozen=True)
class Member:
    case_id: int
    cite: str
    reporter: str
    decision_date: str
    official: bool


@dataclass(frozen=True)
class Group:
    jurisdiction: str
    court: str
    year: int | None
    name: str
    era: str
    members: tuple[Member, ...]


def candidate_groups(conn) -> list[Group]:
    acc: dict[tuple, list[Member]] = defaultdict(list)
    era: dict[tuple, str] = {}
    for cid, name, cite, court, jur, date, year, ep, reporter, official in conn.execute(
            """SELECT c.case_id, c.name_abbreviation, c.cite, c.court, c.jurisdiction,
                      c.decision_date, c.decision_year, c.era_partition, c.reporter,
                      EXISTS(SELECT 1 FROM citations t WHERE t.case_id = c.case_id
                             AND t.cite = c.cite AND t.type = 'official')
               FROM cases c WHERE c.is_duplicate_of IS NULL"""):
        key = normalize_name(name)
        if len(key) < MIN_NAME_CHARS:
            continue
        k = (jur or "", court or "", year, key)
        acc[k].append(Member(int(cid), cite or "", reporter or "", date or "", bool(official)))
        era[k] = ep or ""
    out = []
    for k in sorted(acc, key=lambda k: (k[0], k[1], k[2] or 0, k[3])):
        ms = acc[k]
        if len({m.reporter for m in ms}) > 1:
            out.append(Group(k[0], k[1], k[2], k[3], era[k],
                             tuple(sorted(ms, key=lambda m: m.case_id))))
    return out


def corpus_precedence(m: Member) -> tuple:
    return (not m.official, m.case_id)


def pick_winner(members: Sequence[Member],
                precedence: Callable[[Member], tuple] = corpus_precedence) -> Member:
    return min(members, key=precedence)


def _texts(conn, ids: Sequence[int]) -> dict[int, str]:
    ph = ",".join("?" * len(ids))
    return {int(c): t or "" for c, t in conn.execute(
        f"SELECT case_id, norm_text FROM cases WHERE case_id IN ({ph})", list(ids))}


def score_group(conn, group: Group, winner: Member) -> list[dict]:
    """Every other member against the winner: word 3- and 5-gram containment and the guards."""
    others = [m for m in group.members if m.case_id != winner.case_id]
    texts = _texts(conn, [winner.case_id] + [m.case_id for m in others])
    w3, w5 = shingles(texts.get(winner.case_id), 3), shingles(texts.get(winner.case_id), 5)
    rows = []
    for m in others:
        o3, o5 = shingles(texts.get(m.case_id), 3), shingles(texts.get(m.case_id), 5)
        rows.append({"winner": winner.case_id, "loser": m.case_id,
                     "winner_cite": winner.cite, "loser_cite": m.cite,
                     "jurisdiction": group.jurisdiction, "court": group.court,
                     "year": group.year, "era": group.era, "name": group.name,
                     "c3": round(containment(w3, o3), 4), "c5": round(containment(w5, o5), 4),
                     "date_ok": dates_compatible(winner.decision_date, m.decision_date),
                     "size_ok": size_ratio_ok(w5, o5),
                     "long_enough": min(len(w5), len(o5)) >= MIN_SHINGLES})
    return rows


def passes_guards(row: Mapping) -> bool:
    return bool(row["date_ok"] and row["size_ok"] and row["long_enough"])


def ensure_table(conn) -> None:
    conn.execute(TABLE)
    conn.commit()


def apply_merges(conn, pairs: Iterable[tuple[int, int, float]], *, method: str, run_id: str,
                 ts: str) -> dict:
    """Mark each loser `is_duplicate_of` its winner and record the merge. A loser already
    recorded is skipped (a re-run); a pair whose winner or loser is no longer canonical is
    skipped as stale, which also stops a chain inside one run. Commits every 5,000 merges."""
    ensure_table(conn)
    n = {"applied": 0, "already": 0, "stale": 0}
    for winner, loser, score in pairs:
        if conn.execute("SELECT 1 FROM parallel_reports WHERE loser=?", (loser,)).fetchone():
            n["already"] += 1
            continue
        marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases WHERE case_id IN (?, ?)",
                                  (winner, loser)))
        if winner not in marks or loser not in marks or marks[winner] is not None \
                or marks[loser] is not None:
            n["stale"] += 1
            continue
        conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=? AND is_duplicate_of IS NULL",
                     (winner, loser))
        conn.execute("INSERT INTO parallel_reports (loser, winner, score, method, run_id, ts) "
                     "VALUES (?,?,?,?,?,?)", (loser, winner, score, method, run_id, ts))
        n["applied"] += 1
        if n["applied"] % 5000 == 0:
            conn.commit()
    conn.commit()
    return n


def undo_merges(conn, method: str) -> int:
    ensure_table(conn)
    rows = conn.execute("SELECT loser, winner FROM parallel_reports WHERE method=?",
                        (method,)).fetchall()
    for loser, winner in rows:
        conn.execute("UPDATE cases SET is_duplicate_of=NULL WHERE case_id=? AND is_duplicate_of=?",
                     (loser, winner))
    conn.execute("DELETE FROM parallel_reports WHERE method=?", (method,))
    conn.commit()
    return len(rows)


def winner_map(conn) -> dict[int, int]:
    """loser -> winner for every recorded merge; empty before any merge (no table yet)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='parallel_reports'").fetchone():
        return {}
    return {int(l): int(w) for l, w in conn.execute("SELECT loser, winner FROM parallel_reports")}


def losers_among(conn, case_ids: Iterable[int]) -> set[int]:
    """The ids among `case_ids` marked a duplicate of another case, by any rule."""
    ids = sorted({int(c) for c in case_ids})
    out: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        out |= {int(r[0]) for r in conn.execute(
            f"SELECT case_id FROM cases WHERE case_id IN ({ph}) AND is_duplicate_of IS NOT NULL",
            chunk)}
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_parallel_reports.py`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/ingest/parallel.py tests/test_parallel_reports.py
git commit -F - <<'EOF'
parallel reports: candidate groups by court, year and name across reporters; word 3/5-gram containment with date, size and length guards; reversible apply/undo in a parallel_reports table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Ledger side - `duplicate_of`, keeper precedence, reconcile

**Files:**
- Create: `corpus_engine/ledger/duplicates.py`
- Modify: `corpus_engine/ledger/tally.py` (`_population`)
- Modify: `corpus_engine/ledger/ledger.py` (add `LedgerView.reviewed_ids` after `reviewed`)
- Modify: `corpus_engine/mapper/queue.py:157` (`reasons_for`) and the G-card loop (`if rec.get("relevant") is False:` line)
- Modify: `tools/draw_audit_sample.py` (`_in_frame`)
- Create: `tests/test_ledger_duplicates.py`

**Interfaces:**
- Consumes: nothing from Task 4 (members are duck-typed: `.case_id`, `.official`).
- Produces: `corpus_engine.ledger.duplicates`: `DUPLICATE_FIELD = "duplicate_of"`, `RULE_ID = "parallel-report-merge-v1"`, `precedence(view, reviewed: set[int]) -> Callable[[member], tuple]`, `Reconciled(patches: list[Patch], for_user: list[dict])`, `reconcile(view, merges: Mapping[int, int], *, run_id: str, judged: Sequence[str]) -> Reconciled`; `LedgerView.reviewed_ids() -> set[int]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger_duplicates.py`:

```python
"""Ledger side of the parallel-report merge (spec 2026-10-04 section 6.6)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.duplicates import DUPLICATE_FIELD, RULE_ID, precedence, reconcile
from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.mapper.queue import reasons_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import apply_map_review as amr      # noqa: E402
import draw_audit_sample as das     # noqa: E402

READER = Basis(model="m", prompt_version="v", run_id="r")
USER = Basis(reviewer="marcus", run_id="round-x")
MERGE = Basis(rule_id=RULE_ID, run_id="merge-x")


def _rec(cid, *, relevant=True, polarity="favorable", quotes=1):
    return {"case_id": cid, "cite": f"{cid} X", "year": 1900, "jurisdiction": "N.Y.",
            "relevant": relevant, "polarity": polarity if relevant else None,
            "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "holding_summary": "h",
            "quotes": [{"text": f"q{i}", "supports": ["polarity"], "status": "verified"}
                       for i in range(quotes)],
            "extraction_status": "ok"}


def _ledger(tmp_path, recs):
    led = open_ledger(tmp_path, domain=load_domain())
    led.apply([Patch(r["case_id"], "admit", "", r, "v", READER, cycle="cycle-004") for r in recs],
              note="seed")
    return led


def _judged():
    return tuple(load_domain().judged_fields)


def test_a_duplicate_copy_renders_and_leaves_every_count(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2), _rec(3, polarity="adverse")])
    res = led.apply([Patch(2, "set", DUPLICATE_FIELD, 1, "parallel report of 1", MERGE,
                           cycle="cycle-004")], note="merge")
    assert res.replay_ok and not res.rejected
    v = led.view()
    assert list(v.record(2))[-1] == DUPLICATE_FIELD and v.record(2)[DUPLICATE_FIELD] == 1
    t = v.counts().total
    assert t.human_reviewed + t.machine_only == 2
    fav = v.counts(polarity="favorable").total
    assert fav.human_reviewed + fav.machine_only == 1
    assert sum(c.human_reviewed + c.machine_only for c in v.matrix().cells.values()) == 1
    assert 2 in {r["case_id"] for r in v.records()}       # still in the ledger, out of the counts


def test_reviewed_ids_is_reviewed_for_every_case(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2)])
    led.apply([Patch(2, "set", "polarity", "adverse", "user", USER)], note="review")
    v = led.view()
    assert v.reviewed_ids() == {c for c in v.state.order if v.reviewed(c)} == {2}


def test_precedence_orders_relevant_then_reviewed_then_quotes_then_official(tmp_path):
    led = _ledger(tmp_path, [_rec(1, quotes=1), _rec(2, quotes=3), _rec(3, relevant=False),
                             _rec(4, quotes=1)])
    led.apply([Patch(4, "set", "polarity", "favorable", "user", USER)], note="review")
    v = led.view()
    key = precedence(v, v.reviewed_ids())
    m = lambda cid, official=False: SimpleNamespace(case_id=cid, official=official)   # noqa: E731
    order = sorted([m(9, official=True), m(3), m(1), m(2), m(4), m(8)], key=key)
    assert [x.case_id for x in order] == [4, 2, 1, 3, 9, 8]


def test_reconcile_patches_a_machine_copy_and_lists_disagreements_for_the_user(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2),                    # plain pair: patch 2
                             _rec(4), _rec(5, relevant=False),    # relevance disagreement
                             _rec(6), _rec(7),                    # human value differs
                             _rec(8)])                            # only the winner is in the ledger
    led.apply([Patch(7, "set", "polarity", "adverse", "user", USER)], note="review")
    merges = {2: 1, 5: 4, 7: 6, 99: 8}
    res = reconcile(led.view(), merges, run_id="merge-x", judged=_judged())
    assert [(p.case_id, p.field, p.new, p.basis.rule_id) for p in res.patches] == \
        [(2, DUPLICATE_FIELD, 1, RULE_ID)]
    assert [(u["winner"], u["reason"]) for u in res.for_user] == [(4, "relevant"), (6, "human-value")]
    assert res.for_user[1]["detail"] == {"7": {"polarity": ["adverse", "favorable"]}}
    led.apply(res.patches, note="merge")
    assert reconcile(led.view(), merges, run_id="merge-x", judged=_judged()).patches == []


def test_the_queue_the_audit_frame_and_the_drift_check_treat_a_copy_right(tmp_path):
    led = _ledger(tmp_path, [_rec(1), _rec(2)])
    led.apply([Patch(2, "set", DUPLICATE_FIELD, 1, "copy", MERGE, cycle="cycle-004")], note="merge")
    v = led.view()
    kw = {"disagreements": (), "fuzzy_needs_human": False}
    assert reasons_for(dict(v.record(2), under_thirty_days="yes"), **kw) == ()
    assert reasons_for(dict(v.record(1), under_thirty_days="yes"), **kw) != ()
    assert das._in_frame(v, 1) and not das._in_frame(v, 2)
    manifest = {"records": [{"case_id": 2, "record": {k: _rec(2)[k] for k in
                                                       ("relevant", "polarity", "who_was_letting")}}]}
    assert amr.drift_check(manifest, v.state.records) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_ledger_duplicates.py`
Expected: FAIL at import (`No module named 'corpus_engine.ledger.duplicates'`).

- [ ] **Step 3: Write `corpus_engine/ledger/duplicates.py`**

```python
"""Ledger side of the parallel-report merge (spec 2026-10-04 section 6.6): which copy of a
decision the ledger keeps, and the `duplicate_of` patches that take the other copies out of
every count. A copy's record stays in its cycle file with its fields as they were."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence
from corpus_engine.ledger.types import Basis, Patch

DUPLICATE_FIELD = "duplicate_of"
RULE_ID = "parallel-report-merge-v1"


def precedence(view, reviewed: set[int]) -> Callable:
    """Sort key for the members of a parallel-report group, best first: a relevant ledger
    record, then any ledger record, then none; within that, human-reviewed, then more
    verified quotes, then the official reporter, then the lowest case id. `reviewed` is
    `view.reviewed_ids()`, computed once by the caller."""
    def key(m) -> tuple:
        rec = view.state.records.get(m.case_id)
        tier = 2 if rec is None else (0 if rec.get("relevant") is True else 1)
        verified = sum(1 for q in (rec or {}).get("quotes") or () if q.get("status") == "verified")
        return (tier, m.case_id not in reviewed, -verified, not m.official, m.case_id)
    return key


@dataclass
class Reconciled:
    patches: list[Patch] = field(default_factory=list)
    for_user: list[dict] = field(default_factory=list)


def reconcile(view, merges: Mapping[int, int], *, run_id: str,
              judged: Sequence[str]) -> Reconciled:
    """`merges` is loser -> winner from the corpus. For each group with two or more ledger
    records: a `relevant` disagreement, or a human-set judged value on another relevant copy
    that differs from the winner's, puts the group on the user's list and patches nothing;
    otherwise every other relevant copy gets `duplicate_of = winner`. Idempotent."""
    groups: dict[int, list[int]] = defaultdict(list)
    for loser, winner in merges.items():
        groups[int(winner)].append(int(loser))
    out = Reconciled()
    recs = view.state.records
    for winner in sorted(groups):
        in_ledger = [c for c in [winner] + sorted(groups[winner]) if c in recs]
        if len(in_ledger) < 2:
            continue
        readings = {c: recs[c].get("relevant") for c in in_ledger
                    if recs[c].get("relevant") is not None}
        if True in readings.values() and False in readings.values():
            out.for_user.append({"winner": winner, "members": in_ledger, "reason": "relevant",
                                 "detail": {str(c): v for c, v in readings.items()}})
            continue
        counted = [c for c in in_ledger if readings.get(c) is True]
        if len(counted) < 2:
            continue
        if winner not in counted:
            out.for_user.append({"winner": winner, "members": in_ledger,
                                 "reason": "winner-not-counted", "detail": {}})
            continue
        others = [c for c in counted if c != winner]
        diffs = {}
        for c in others:
            prov = view.provenance(c)
            fields = [f for f in judged
                      if prov.get(f) == "human" and recs[c].get(f) != recs[winner].get(f)]
            if fields:
                diffs[str(c)] = {f: [recs[c].get(f), recs[winner].get(f)] for f in fields}
        if diffs:
            out.for_user.append({"winner": winner, "members": in_ledger,
                                 "reason": "human-value", "detail": diffs})
            continue
        for c in others:
            if recs[c].get(DUPLICATE_FIELD) == winner:
                continue
            out.patches.append(Patch(c, "set", DUPLICATE_FIELD, winner,
                                     f"parallel report of {winner}: one decision, counted once",
                                     Basis(rule_id=RULE_ID, run_id=run_id),
                                     cycle=view.state.cycles.get(c)))
    return out
```

- [ ] **Step 4: Skip copies in counts, the queue and the audit frame; add `reviewed_ids`**

`corpus_engine/ledger/tally.py`: add `from corpus_engine.ledger.duplicates import DUPLICATE_FIELD` and in `_population` replace `if not r.get("relevant"):` with `if not r.get("relevant") or r.get(DUPLICATE_FIELD):`.

`corpus_engine/ledger/ledger.py`, in `LedgerView` right after `reviewed`:

```python
    def reviewed_ids(self) -> set[int]:
        """Every case `reviewed()` is true for, in one pass (`reviewed` scans the log per call)."""
        judged = set(self.domain.judged_fields) | {"review.status"}
        return {p.case_id for p in self.patches
                if p.basis.reviewer and p.op in ("set", "append") and p.field in judged}
```

`corpus_engine/mapper/queue.py`: add `from corpus_engine.ledger.duplicates import DUPLICATE_FIELD`; in `reasons_for` replace `if not record.get("relevant"):` with `if not record.get("relevant") or record.get(DUPLICATE_FIELD):`; in the G-card loop replace `if rec.get("relevant") is False:` with `if rec.get("relevant") is False or rec.get(DUPLICATE_FIELD):` and extend its comment to `# a withdrawn record, or a parallel copy, asks nothing`.

`tools/draw_audit_sample.py`, `_in_frame` body:

```python
    rec = view.state.records[cid]
    return rec.get("relevant") is True and not rec.get("duplicate_of") and not view.reviewed(cid)
```

- [ ] **Step 5: Run the new tests, then the suite**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_ledger_duplicates.py` then the full suite.
Expected: 5 passed; full suite `835 passed, 1 xfailed` (823 + 7 + 5).

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/ledger/duplicates.py corpus_engine/ledger/tally.py corpus_engine/ledger/ledger.py \
  corpus_engine/mapper/queue.py tools/draw_audit_sample.py tests/test_ledger_duplicates.py
git commit -F - <<'EOF'
ledger: duplicate_of takes a parallel copy out of every count, the review queue and future audit frames; keeper precedence and reconcile (disagreements go to the user's list); LedgerView.reviewed_ids

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: The tool - `tools/merge_parallel_reports.py`

**Files:**
- Create: `tools/merge_parallel_reports.py`
- Create: `tests/test_merge_parallel_reports_tool.py`

**Interfaces:**
- Consumes: Task 4 (`par.candidate_groups`, `pick_winner`, `score_group`, `passes_guards`, `apply_merges`, `undo_merges`, `winner_map`); Task 5 (`precedence`, `reconcile`, `LedgerView.reviewed_ids`).
- Produces: CLI `--db --ledger --out-dir {score | sample [--per-band --seed --parts] | threshold | apply [--dry-run --run-id] | undo --method | reconcile [--dry-run --run-id --user-list]}`; functions `choose_threshold(labelled, *, measures=("c5","c3"), bounds=BOUNDS) -> dict | None`, `calibration_sample(rows, *, per_band, seed, measure="c5") -> list[dict]`. Files in `--out-dir`: `candidates.jsonl`, `calibration-sample.json`, `calibration-pairs-partN.md` (blind, for the readers), `calibration-labels-partN.json` (the readers' output: `[{"pair_id", "label", "note"}]`), `calibration.json`, `merges.jsonl`, `reconcile-for-user.json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merge_parallel_reports_tool.py`:

```python
"""tools/merge_parallel_reports.py over a temporary store and ledger."""
import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("merge_parallel_reports",
                                               ROOT / "tools" / "merge_parallel_reports.py")
mpr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mpr)
BODY = " ".join(f"word{i}" for i in range(400))


def _row(c5, label, c3=None, **kw):
    return {"c5": c5, "c3": c5 if c3 is None else c3, "label": label,
            "date_ok": True, "size_ok": True, "long_enough": True, **kw}


def test_threshold_is_the_lowest_bound_above_every_pair_not_labelled_same():
    rows = [_row(0.95, "same"), _row(0.81, "same"), _row(0.66, "same"),
            _row(0.52, "different"), _row(0.31, "different"), _row(0.58, "unsure")]
    ch = mpr.choose_threshold(rows)
    assert ch["measure"] == "c5" and ch["threshold"] == 0.6      # the 0.58 unsure counts against
    assert ch["merged_same"] == 3 and ch["method"] == "parallel-v1:w5:0.6"


def test_no_threshold_when_a_different_pair_scores_at_the_top():
    assert mpr.choose_threshold([_row(0.97, "different"), _row(0.99, "same")]) is None


def test_the_other_measure_wins_when_it_separates_more_same_pairs():
    rows = [_row(0.9, "same", c3=0.9), _row(0.7, "same", c3=0.85), _row(0.75, "different", c3=0.4)]
    ch = mpr.choose_threshold(rows)
    assert (ch["measure"], ch["threshold"], ch["merged_same"]) == ("c3", 0.45, 2)


def test_the_calibration_sample_takes_only_guarded_pairs_per_band():
    rows = [_row(0.25 + 0.1 * (i % 8), None, loser=i) for i in range(80)]
    rows.append(_row(0.95, None, loser=999, date_ok=False))
    s = mpr.calibration_sample(rows, per_band=3, seed=1)
    assert len(s) == 24 and 999 not in {r["loser"] for r in s}
    assert s == mpr.calibration_sample(rows, per_band=3, seed=1)


def test_threshold_joins_blind_labels_back_to_scores_and_refuses_gaps(tmp_path):
    out = tmp_path / "pr"
    out.mkdir()
    sample = [_row(s, None, pair_id=i, winner=10 + i, loser=20 + i)
              for i, s in enumerate((0.9, 0.7, 0.4))]
    (out / "calibration-sample.json").write_text(json.dumps(sample), encoding="utf-8")
    labels = [{"pair_id": 0, "label": "same"}, {"pair_id": 1, "label": "same"},
              {"pair_id": 2, "label": None}]
    (out / "calibration-labels-part1.json").write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(SystemExit, match="carry no label"):
        mpr.main(["--out-dir", str(out), "threshold"])
    labels[2]["label"] = "different"
    (out / "calibration-labels-part1.json").write_text(json.dumps(labels), encoding="utf-8")
    assert mpr.main(["--out-dir", str(out), "threshold"]) == 0
    ch = json.loads((out / "calibration.json").read_text(encoding="utf-8"))["choice"]
    assert (ch["measure"], ch["threshold"], ch["merged_same"]) == ("c5", 0.45, 2)


def _store(tmp_path) -> Path:
    db = tmp_path / "c.db"
    conn = store.connect(db)
    store.ensure_schema(conn)

    def case(cid, reporter, *, official=False, text=BODY, name="Smith v. Jones"):
        cite = f"{cid} {reporter} 1"
        conn.execute("""INSERT INTO cases (case_id, name_abbreviation, cite, court, jurisdiction,
                        decision_date, decision_year, era_partition, reporter, norm_text, raw_text)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (cid, name, cite, "New York Supreme Court", "N.Y.", "1908-04", 1908,
                      "1900-1930", reporter, text, text))
        conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                     (cid, cite, cite.lower(), "official" if official else "parallel"))
    case(1, "misc", official=True)
    case(2, "nys", text="Syllabus by the reporter. " + BODY)
    case(3, "misc", official=True, name="Brown v. Green")
    case(4, "nys", name="Brown v. Green")
    conn.commit()
    conn.close()
    return db


def _rec(cid):
    return {"case_id": cid, "cite": f"{cid} X", "year": 1908, "jurisdiction": "N.Y.",
            "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
            "duration_of_occupancy": "nights", "characterization": "lodging",
            "holding_summary": "h", "extraction_status": "ok",
            "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified"}]}


def _duplicates(db) -> dict:
    c = sqlite3.connect(db)
    try:
        return dict(c.execute("SELECT case_id, is_duplicate_of FROM cases "
                              "WHERE is_duplicate_of IS NOT NULL"))
    finally:
        c.close()


def test_score_sample_apply_reconcile_undo_end_to_end(tmp_path, capsys):
    db, ledger, out = _store(tmp_path), tmp_path / "ledger", tmp_path / "pr"
    open_ledger(ledger, domain=load_domain()).apply(
        [Patch(c, "admit", "", _rec(c), "v", Basis(model="m", prompt_version="v", run_id="r"),
               cycle="cycle-004") for c in (2, 3, 4)], note="seed")
    common = ["--db", str(db), "--ledger", str(ledger), "--out-dir", str(out)]

    assert mpr.main(common + ["score"]) == 0
    rows = [json.loads(l) for l in (out / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(r["winner"], r["loser"]) for r in rows} == {(2, 1), (3, 4)}   # a ledger copy beats official

    assert mpr.main(common + ["sample", "--per-band", "1", "--parts", "2"]) == 0
    md = (out / "calibration-pairs-part1.md").read_text(encoding="utf-8")
    assert "## pair 0" in md and "c5" not in md                           # the readers are blind to scores

    (out / "calibration.json").write_text(json.dumps(
        {"choice": {"measure": "c5", "threshold": 0.6, "method": "parallel-v1:w5:0.6"}}), encoding="utf-8")
    capsys.readouterr()
    assert mpr.main(common + ["apply", "--dry-run"]) == 0
    assert "2 merges" in capsys.readouterr().out and _duplicates(db) == {}
    assert mpr.main(common + ["apply"]) == 0
    assert _duplicates(db) == {1: 2, 4: 3}
    merges = [json.loads(l) for l in (out / "merges.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [m["loser"] for m in merges] == [1, 4]

    capsys.readouterr()
    assert mpr.main(common + ["reconcile", "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "relevant: 0+3 -> 0+2" in text and "1 duplicate_of patches" in text
    assert open_ledger(ledger, domain=load_domain()).view().record(4).get("duplicate_of") is None
    assert mpr.main(common + ["reconcile"]) == 0
    v = open_ledger(ledger, domain=load_domain()).view()
    assert v.record(4)["duplicate_of"] == 3 and v.counts().total.machine_only == 2

    assert mpr.main(common + ["undo", "--method", "parallel-v1:w5:0.6"]) == 0
    assert _duplicates(db) == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_merge_parallel_reports_tool.py`
Expected: FAIL (`tools/merge_parallel_reports.py` does not exist).

- [ ] **Step 3: Write `tools/merge_parallel_reports.py`**

```python
"""Merge parallel reports - one decision printed in two reporters (spec 2026-10-04 section 6).

  .venv/Scripts/python tools/merge_parallel_reports.py score                  # candidates.jsonl
  .venv/Scripts/python tools/merge_parallel_reports.py sample --per-band 25   # blind reader parts
  .venv/Scripts/python tools/merge_parallel_reports.py threshold              # calibration.json
  .venv/Scripts/python tools/merge_parallel_reports.py apply --dry-run        # counts only
  .venv/Scripts/python tools/merge_parallel_reports.py apply                  # corpus marks + merges.jsonl
  .venv/Scripts/python tools/merge_parallel_reports.py undo --method <method>
  .venv/Scripts/python tools/merge_parallel_reports.py reconcile --dry-run    # ledger counts before/after
  .venv/Scripts/python tools/merge_parallel_reports.py reconcile

Files live in --out-dir (default runs/parallel-reports). `score` and `sample` read the corpus
read-only; `apply` and `undo` write `cases.is_duplicate_of` and the `parallel_reports` table;
`reconcile` writes ledger patches. The user says go before `apply` and before `reconcile`."""
from __future__ import annotations
import argparse
import collections
import copy
import json
import random
import sqlite3
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import store                                      # noqa: E402
from corpus_engine.domain import load_domain                         # noqa: E402
from corpus_engine.ingest import parallel as par                     # noqa: E402
from corpus_engine.ledger import open_ledger                         # noqa: E402
from corpus_engine.ledger.duplicates import precedence, reconcile    # noqa: E402
from corpus_engine.ledger.fold import apply_patch                    # noqa: E402
from corpus_engine.ledger.ledger import LedgerView                   # noqa: E402
from corpus_engine.ledger.log import provisional_seqs                # noqa: E402

BOUNDS = tuple(round(0.20 + 0.05 * i, 2) for i in range(16))         # 0.20, 0.25 ... 0.95
SAMPLE_BANDS = tuple(round(0.2 + 0.1 * i, 1) for i in range(8))      # [0.2, 0.3) ... [0.9, 1.0]
MEASURES = ("c5", "c3")                                              # c5 first: it wins a tie
HEAD_CHARS, TAIL_CHARS = 2000, 1500
RUN_ID = "parallel-report-merge-2026-10"
LABELS = ("same", "different", "unsure")


def _ro(db) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def choose_threshold(labelled, *, measures=MEASURES, bounds=BOUNDS) -> dict | None:
    """Per measure, the lowest bound strictly above every pair not labelled `same` (`unsure`
    counts as not same); the measure kept is the one that merges more labelled-same pairs, c5
    on a tie. None when no bound clears every not-same pair."""
    best = None
    for m in measures:
        worst = max((r[m] for r in labelled if r["label"] != "same"), default=-1.0)
        t = next((b for b in bounds if b > worst), None)
        if t is None:
            continue
        merged = sum(1 for r in labelled if r["label"] == "same" and r[m] >= t)
        if best is None or merged > best["merged_same"]:
            best = {"measure": m, "threshold": t, "merged_same": merged,
                    "labelled_same": sum(1 for r in labelled if r["label"] == "same"),
                    "labelled_not_same": sum(1 for r in labelled if r["label"] != "same")}
    if best:
        best["method"] = f"parallel-v1:w{best['measure'][1]}:{best['threshold']}"
    return best


def calibration_sample(rows, *, per_band: int, seed: int, measure: str = "c5") -> list[dict]:
    rng = random.Random(seed)
    ok = [r for r in rows if par.passes_guards(r)]
    out = []
    for lo in SAMPLE_BANDS:
        hi = round(lo + 0.1, 1)
        band = [r for r in ok if lo <= r[measure] and (r[measure] < hi or hi >= 1.0)]
        out += rng.sample(band, min(per_band, len(band)))
    return out


def _excerpt(text: str) -> str:
    text = text or ""
    if len(text) > HEAD_CHARS + TAIL_CHARS:
        text = text[:HEAD_CHARS] + "\n[...]\n" + text[-TAIL_CHARS:]
    return "\n".join(textwrap.fill(p, 160) if p.strip() else "" for p in text.split("\n"))


def cmd_score(a) -> int:
    view = open_ledger(Path(a.ledger), domain=load_domain()).view()
    key = precedence(view, view.reviewed_ids())
    conn = _ro(a.db)
    groups = par.candidate_groups(conn)
    out = Path(a.out_dir) / "candidates.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for i, g in enumerate(groups, 1):
            for row in par.score_group(conn, g, par.pick_winner(g.members, key)):
                f.write(json.dumps(row, sort_keys=True) + "\n")
                n += 1
            if i % 5000 == 0:
                print(f"{i}/{len(groups)} groups, {n} pairs", flush=True)
    print(f"{len(groups)} groups, {n} pairs -> {out}")
    return 0


def cmd_sample(a) -> int:
    out = Path(a.out_dir)
    picked = calibration_sample(_jsonl(out / "candidates.jsonl"), per_band=a.per_band, seed=a.seed)
    random.Random(a.seed).shuffle(picked)          # every reader gets every band
    for i, r in enumerate(picked):
        r["pair_id"] = i
    (out / "calibration-sample.json").write_text(json.dumps(picked, indent=1) + "\n", encoding="utf-8")
    conn = _ro(a.db)
    size = -(-len(picked) // a.parts) if picked else 0
    for k in range(a.parts):
        lines = [f"# Calibration pairs, part {k + 1}", ""]
        for r in picked[k * size:(k + 1) * size]:
            texts = dict(conn.execute("SELECT case_id, norm_text FROM cases WHERE case_id IN (?, ?)",
                                      (r["winner"], r["loser"])))
            lines += [f"## pair {r['pair_id']}", f"{r['court']}, {r['year']}: {r['name']}", "",
                      f"### A ({r['winner_cite']})", _excerpt(texts.get(r["winner"], "")), "",
                      f"### B ({r['loser_cite']})", _excerpt(texts.get(r["loser"], "")), ""]
        (out / f"calibration-pairs-part{k + 1}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(picked)} pairs in {a.parts} parts -> {out}")
    return 0


def cmd_threshold(a) -> int:
    out = Path(a.out_dir)
    sample = {r["pair_id"]: r for r in
              json.loads((out / "calibration-sample.json").read_text(encoding="utf-8"))}
    labels = {}
    for p in sorted(out.glob("calibration-labels-part*.json")):
        for r in json.loads(p.read_text(encoding="utf-8")):
            labels[r["pair_id"]] = (r.get("label"), r.get("note", ""))
    missing = [i for i in sorted(sample) if labels.get(i, (None,))[0] not in LABELS]
    if missing:
        sys.exit(f"{len(missing)} pairs carry no label ({'/'.join(LABELS)}): {missing[:10]}")
    labelled = [dict(sample[i], label=labels[i][0], note=labels[i][1]) for i in sorted(sample)]
    choice = choose_threshold(labelled)
    bands = collections.Counter((f"{min(int(r['c5'] * 10), 9) / 10:.1f}", r["label"]) for r in labelled)
    for b in SAMPLE_BANDS:
        print(f"c5 {b:.1f}: " + ", ".join(f"{lab} {bands[(f'{b:.1f}', lab)]}" for lab in LABELS))
    print(f"choice: {choice}")
    (out / "calibration.json").write_text(json.dumps(
        {"bounds": BOUNDS, "choice": choice, "labels": labelled}, indent=1) + "\n", encoding="utf-8")
    return 0


def _choice(out: Path) -> dict:
    cal = json.loads((out / "calibration.json").read_text(encoding="utf-8"))
    if not cal.get("choice"):
        sys.exit("calibration.json holds no threshold: no bound clears every not-same pair")
    return cal["choice"]


def cmd_apply(a) -> int:
    out = Path(a.out_dir)
    ch = _choice(out)
    m, t = ch["measure"], ch["threshold"]
    rows = [r for r in _jsonl(out / "candidates.jsonl") if par.passes_guards(r) and r[m] >= t]
    print(f"{len(rows)} merges at {m} >= {t} ({ch['method']})")
    for label in ("jurisdiction", "era"):
        c = collections.Counter(r[label] for r in rows)
        print(f"  by {label}: " + ", ".join(f"{v} {n}" for v, n in c.most_common()))
    if a.dry_run:
        return 0
    conn = store.connect(Path(a.db))
    res = par.apply_merges(conn, [(r["winner"], r["loser"], r[m]) for r in rows],
                           method=ch["method"], run_id=a.run_id,
                           ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
    print(f"applied {res['applied']}, already merged {res['already']}, stale {res['stale']}")
    with (out / "merges.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for loser, winner, score, method in conn.execute(
                "SELECT loser, winner, score, method FROM parallel_reports WHERE method=? "
                "ORDER BY loser", (ch["method"],)):
            f.write(json.dumps({"loser": loser, "winner": winner, "score": score,
                                "method": method}) + "\n")
    return 0


def cmd_undo(a) -> int:
    n = par.undo_merges(store.connect(Path(a.db)), a.method)
    print(f"undid {n} merges of {a.method}; ledger duplicate_of patches, if any, still stand")
    return 0


def cmd_reconcile(a) -> int:
    dom = load_domain()
    led = open_ledger(Path(a.ledger), domain=dom)
    view = led.view()
    judged = tuple(dom.judged_fields)
    res = reconcile(view, par.winner_map(_ro(a.db)), run_id=a.run_id, judged=judged)
    trial = copy.deepcopy(view.state)
    for p in provisional_seqs(res.patches, view.as_of):
        apply_patch(trial, p, judged=judged, cascade=p.cascade)
    after = LedgerView(view.name, view.as_of + len(res.patches), trial, view.patches, view.domain)
    for label, flt in (("relevant", {}), ("favorable", {"polarity": "favorable"}),
                       ("favorable householder", {"polarity": "favorable",
                                                  "who_was_letting": "householder"})):
        b, c = view.counts(**flt).total, after.counts(**flt).total
        print(f"{label}: {b.human_reviewed}+{b.machine_only} -> {c.human_reviewed}+{c.machine_only}")
    Path(a.user_list).parent.mkdir(parents=True, exist_ok=True)
    Path(a.user_list).write_text(json.dumps(res.for_user, indent=1) + "\n", encoding="utf-8")
    print(f"{len(res.patches)} duplicate_of patches; {len(res.for_user)} groups for the user "
          f"-> {a.user_list}")
    if a.dry_run:
        return 0
    r = led.apply(res.patches, note="parallel-report merge: one decision, counted once")
    if r.rejected or not r.replay_ok:
        sys.exit(f"apply refused {len(r.rejected)} writes or the replay failed "
                 f"(replay_ok={r.replay_ok})")
    print(f"{len(r.applied)} applied, {len(r.skipped)} already present; replay_ok={r.replay_ok}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "db" / "corpus.db"))
    ap.add_argument("--ledger", default=str(ROOT / "data" / "ledger"))
    ap.add_argument("--out-dir", default=str(ROOT / "runs" / "parallel-reports"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("score")
    s = sub.add_parser("sample")
    s.add_argument("--per-band", type=int, default=25)
    s.add_argument("--seed", type=int, default=20261004)
    s.add_argument("--parts", type=int, default=4)
    sub.add_parser("threshold")
    p = sub.add_parser("apply")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--run-id", default=RUN_ID)
    u = sub.add_parser("undo")
    u.add_argument("--method", required=True)
    r = sub.add_parser("reconcile")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--run-id", default=RUN_ID)
    r.add_argument("--user-list")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "reconcile" and not a.user_list:
        a.user_list = str(Path(a.out_dir) / "reconcile-for-user.json")
    return {"score": cmd_score, "sample": cmd_sample, "threshold": cmd_threshold,
            "apply": cmd_apply, "undo": cmd_undo, "reconcile": cmd_reconcile}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_merge_parallel_reports_tool.py` then the full suite.
Expected: 6 passed; full suite `841 passed, 1 xfailed`.

- [ ] **Step 5: Commit**

```bash
git add tools/merge_parallel_reports.py tests/test_merge_parallel_reports_tool.py
git commit -F - <<'EOF'
tool: merge_parallel_reports (score, blind calibration sample, threshold, apply/undo with merges.jsonl, ledger reconcile with before/after counts)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Follow-on rules - batch building, the map reader guard, gold

**Files:**
- Modify: `corpus_engine/selector/packing.py:20-24` (`build_batches` query)
- Modify: `tools/map_reader.py` (import, helper, guard after `conn = store.connect(...)` at line 225)
- Modify: `corpus_engine/evaluation/gold.py` (add `follow_merges`)
- Modify: `tools/evaluate.py:22,125-132` (`compute`)
- Tests: `tests/test_ranker_packing.py`, `tests/test_map_reader_tool.py`, `tests/test_evaluation_gold.py` (one new test each)

**Interfaces:**
- Consumes: Task 4 `par.losers_among`, `par.winner_map`.
- Produces: `corpus_engine.evaluation.gold.follow_merges(rows, winner_of: Mapping[int, int]) -> list[dict]`.

- [ ] **Step 1: Write the three failing tests**

Append to `tests/test_ranker_packing.py` (add `from corpus_engine import store` and `from corpus_engine.selector.packing import build_batches` if not already imported):

```python
def test_build_batches_leaves_out_a_case_marked_duplicate(tmp_path):
    conn = store.connect(tmp_path / "c.db")
    store.ensure_schema(conn)
    for cid in (1, 2, 3):
        conn.execute("INSERT INTO cases (case_id, era_partition, jurisdiction, is_duplicate_of) "
                     "VALUES (?,?,?,?)", (cid, "1900-1930", "N.Y.", 1 if cid == 2 else None))
        conn.execute("INSERT INTO signals (case_id, selector_id, selector_version, era_partition, "
                     "jurisdiction, run_id) VALUES (?,?,?,?,?,?)",
                     (cid, "s", 1, "1900-1930", "N.Y.", "r"))
    conn.commit()
    batches = build_batches(conn, "r", gold_ids=set(), exclude_ids=set())
    assert [c["case_id"] for b in batches for c in b["cases"]] == [1, 3]
```

Append to `tests/test_map_reader_tool.py`:

```python
def test_a_pool_holding_a_merged_duplicate_is_refused_before_any_read(wired):
    import sqlite3
    pool = wired["root"] / "runs" / RUN_ID / "batches"
    cases = json.loads((pool / "batch-001.json").read_text(encoding="utf-8"))["cases"]
    loser, winner = int(cases[0]["case_id"]), int(cases[1]["case_id"])
    conn = sqlite3.connect(wired["root"] / "data" / "db" / "corpus.db")
    conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=?", (winner, loser))
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit) as exc:
        mr.main(["--sample-pct", "0"])
    assert "marked duplicates" in str(exc.value) and str(loser) in str(exc.value)
    assert not Path(wired["manifest"]).exists()
```

Append to `tests/test_evaluation_gold.py`:

```python
def test_follow_merges_scores_a_gold_case_at_its_winner():
    from corpus_engine.evaluation.gold import follow_merges
    rows = [{"case_id": 2, "tier": "treatise"}, {"case_id": 1, "tier": "treatise"},
            {"cite_norm": "x"}]
    out = follow_merges(rows, {2: 1})
    assert out[0] == {"case_id": 1, "tier": "treatise", "merged_from": 2}
    assert out[1] == {"case_id": 1, "tier": "treatise"} and out[2] == {"cite_norm": "x"}
    assert rows[0]["case_id"] == 2                       # the caller's rows are not edited
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_ranker_packing.py::test_build_batches_leaves_out_a_case_marked_duplicate tests/test_map_reader_tool.py::test_a_pool_holding_a_merged_duplicate_is_refused_before_any_read tests/test_evaluation_gold.py::test_follow_merges_scores_a_gold_case_at_its_winner`
Expected: three FAILs (`[1, 2, 3]`, no SystemExit, ImportError).

- [ ] **Step 3: Filter duplicates out of batch building**

In `corpus_engine/selector/packing.py`, `build_batches`, replace the query with:

```python
    rows = conn.execute(
        """SELECT s.case_id, s.era_partition, s.jurisdiction,
                  s.selector_id, s.selector_version, s.matched_text,
                  s.char_span_start, s.char_span_end, s.chunk_id, s.cosine, s.run_id
           FROM signals s JOIN cases c ON c.case_id = s.case_id
           WHERE c.is_duplicate_of IS NULL
           ORDER BY s.era_partition, s.jurisdiction, s.case_id, s.rowid"""
    ).fetchall()
```

- [ ] **Step 4: Guard the map reader**

In `tools/map_reader.py`: add `BATCH_GLOB` to the `from corpus_engine.mapper.cells import (...)` list, add `from corpus_engine.ingest.parallel import losers_among  # noqa: E402` beside the other `corpus_engine` imports, add this function above `main`:

```python
def _marked_duplicates(conn, batches_dir: Path) -> list[int]:
    """Cases in the run's packed batches that are now marked duplicates (spec 2026-10-04
    section 6.7). Admission re-derives every batch from its file, so they are not filtered
    out at read time; the run is re-packed instead."""
    ids = {int(c["case_id"]) for p in sorted(batches_dir.glob(BATCH_GLOB))
           for c in json.loads(p.read_text(encoding="utf-8")).get("cases") or ()}
    return sorted(losers_among(conn, ids))
```

and directly after `conn = store.connect(ROOT / "data" / "db" / "corpus.db")`:

```python
    stale = _marked_duplicates(conn, batches_dir)
    if stale:
        sys.exit(f"{len(stale)} cases in {batches_dir} are now marked duplicates of another case "
                 f"(first {stale[:5]}); re-pack the run with pipeline/rank.py (README: cycle map) "
                 "before reading it")
```

- [ ] **Step 5: Gold follows the merge**

In `corpus_engine/evaluation/gold.py`, after `_dedupe`:

```python
def follow_merges(rows: Sequence[Mapping], winner_of: Mapping[int, int]) -> list[dict]:
    """A gold row whose case was merged into a parallel report is scored at the winner
    (spec 2026-10-04 section 6.7); `merged_from` keeps the id the gold file names. `_dedupe`
    then collapses two gold rows that name two copies of one decision."""
    out = []
    for r in rows:
        d = dict(r)
        cid = d.get("case_id")
        if cid is not None and int(cid) in winner_of:
            d["merged_from"] = int(cid)
            d["case_id"] = winner_of[int(cid)]
        out.append(d)
    return out
```

In `tools/evaluate.py` change line 22 to
`from corpus_engine.evaluation.gold import follow_merges, gold_recovery, READ_FAILED  # noqa: E402`
and replace the lines from `gold_rows = ...` through the `signaled = ... attribution(...)` line in `compute` with:

```python
    gold_rows = [json.loads(l) for l in (ROOT / "data" / "gold" / "gold.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if not a.no_store:
        from corpus_engine import store
        from corpus_engine.ingest.parallel import winner_map
        conn = store.connect()
        gold_rows = follow_merges(gold_rows, winner_map(conn))
    ids = [int(g["case_id"]) for g in gold_rows if g.get("case_id")]
    if a.no_store:
        signaled = {cid: True for cid in ids}
    else:
        from corpus_engine.selector.engine import attribution
        signaled = {cid: bool(refs) for cid, refs in attribution(conn, ids).items()}
```

- [ ] **Step 6: Run the three tests, then the suite**

Expected: 3 passed; full suite `844 passed, 1 xfailed`.

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/selector/packing.py tools/map_reader.py corpus_engine/evaluation/gold.py tools/evaluate.py \
  tests/test_ranker_packing.py tests/test_map_reader_tool.py tests/test_evaluation_gold.py
git commit -F - <<'EOF'
merge follow-ons: batch building skips duplicate-marked cases; map_reader refuses a pool holding one (re-pack first); gold recovery scores a merged gold case at its winner

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Live corpus merge - score, calibrate, user gate, apply (controller)

**Files:**
- Modify: `.gitignore` (add `runs/parallel-reports/candidates.jsonl`)
- Data: `runs/parallel-reports/` (commit `calibration-sample.json`, `calibration-pairs-part*.md`, `calibration-labels-part*.json`, `calibration.json`, `merges.jsonl`); `data/db/corpus.db` (untracked)

- [ ] **Step 1: Score the corpus (read-only; about an hour)**

```bash
mkdir -p runs/parallel-reports
.venv/Scripts/python -u tools/merge_parallel_reports.py score > runs/parallel-reports/score.log 2>&1
tail -2 runs/parallel-reports/score.log
```
Run it in the background and wait for the notification. Expected: about 75,000 groups and roughly 96,000 pairs (the 2026-10-04 measurement).

- [ ] **Step 2: Draw the blind calibration sample**

```bash
.venv/Scripts/python tools/merge_parallel_reports.py sample --per-band 25 --parts 4
```
Expected: about 200 pairs in 4 parts (a thin band yields fewer).

- [ ] **Step 3: Label the pairs (four agents in parallel, most capable model)**

Dispatch four general-purpose agents, one per part, each with this prompt (N = 1..4):

> You are labelling pairs of court-opinion texts for a deduplication calibration. Read `runs/parallel-reports/calibration-pairs-partN.md` in full. Each `## pair <id>` section holds two texts, A and B: excerpts (the first 2,000 and last 1,500 characters) of two cases with the same court, year and case name, printed in different law reporters. For each pair decide:
> - `same`: A and B report the same judicial decision. Different headnotes, syllabi, counsel lists, reporter's notes, running heads, OCR errors, or one copy abridged are all expected and still `same`.
> - `different`: two different decisions - for example the trial court's and the appellate court's decision in one dispute, a motion and the merits, a reargument, or companion cases with different facts.
> - `unsure`: the excerpts do not settle it.
> Write `runs/parallel-reports/calibration-labels-partN.json`, a JSON list with one object per pair in the file: `{"pair_id": <int>, "label": "same" | "different" | "unsure", "note": "<one short sentence; required for different and unsure>"}`. Read no other file and change no other file. Reply with the count of each label.

- [ ] **Step 4: Choose the threshold**

```bash
.venv/Scripts/python tools/merge_parallel_reports.py threshold
.venv/Scripts/python tools/merge_parallel_reports.py apply --dry-run
```
Expected: a per-band table of labels, the choice (measure, threshold, method, merged_same of labelled_same), then the merge count by jurisdiction and era. If the choice is `None`, stop and report to the user: no bound is safe.

- [ ] **Step 5: USER GATE**

Show the user the per-band label table, every `different`/`unsure` pair with its note and score, the chosen measure and threshold, and the dry-run counts by jurisdiction and era. Note that zero not-same pairs above the threshold in about 25 per band bounds the false-merge rate only loosely (rule of three: under about 3/n per band). Wait for an explicit go. If the user changes the threshold, edit `choice` in `runs/parallel-reports/calibration.json` (measure, threshold, method) and re-run the dry run.

- [ ] **Step 6: Apply**

```bash
.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('file:data/db/corpus.db?mode=ro', uri=True); print(c.execute('SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL').fetchone()[0])"
.venv/Scripts/python tools/merge_parallel_reports.py apply
.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('file:data/db/corpus.db?mode=ro', uri=True); print(c.execute('SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL').fetchone()[0], c.execute('SELECT count(*) FROM parallel_reports').fetchone()[0])"
wc -l runs/parallel-reports/merges.jsonl
```
Expected: canonical count before (1,874,141) minus `applied` equals the count after; `parallel_reports` rows equal `applied` equal the lines in `merges.jsonl`; `stale` 0. Spot-check three merged pairs by reading both texts' first 500 characters.

- [ ] **Step 7: Commit the calibration record and the merge list**

Append `runs/parallel-reports/candidates.jsonl` to `.gitignore` (the score log is already ignored by `*.log`).

```bash
git add .gitignore runs/parallel-reports/
git status --short runs/parallel-reports
git commit -F - <<'EOF'
corpus: parallel reports merged (method and counts in runs/parallel-reports/calibration.json and merges.jsonl); blind calibration sample and labels committed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Put the method, the threshold and the applied count in the commit subject when you run it.

---

### Task 9: Live ledger reconcile - dry run, user gate, apply, re-pin counts (controller)

**Files:**
- Data: `data/ledger/patches/*.jsonl`, `data/ledger/cycle-*.jsonl`, `data/ledger/manifest/*` (via the tool)
- Create: `runs/parallel-reports/reconcile-for-user.json`
- Modify: `tests/test_ledger_committed.py` (the pinned counts)

- [ ] **Step 1: Dry run**

```bash
.venv/Scripts/python tools/merge_parallel_reports.py reconcile --dry-run
```
Expected: three `before -> after` lines (relevant from 1509+2842 down by about 129), the number of `duplicate_of` patches, and the number of groups for the user.

- [ ] **Step 2: Check the audit sample is untouched**

```bash
.venv/Scripts/python - <<'EOF'
import json
from pathlib import Path
from corpus_engine.ingest import parallel as par
import sqlite3
ids = {int(r["case_id"]) for r in json.loads(Path("runs/audit-cycle-004/sample-manifest.json").read_text())["records"]}
m = par.winner_map(sqlite3.connect("file:data/db/corpus.db?mode=ro", uri=True))
print("audit records that are merge losers:", sorted(ids & set(m)))
EOF
```
The reconcile writes only `duplicate_of`, never the three audit fields; list any audit records that will be marked so the user knows they drop out of counts while still being audited.

- [ ] **Step 3: USER GATE**

Show the user the count deltas, the patch count, every group in `runs/parallel-reports/reconcile-for-user.json` (cites, case names, reason, the differing values), and the audit-record list from Step 2. The user-list groups are left for a later review round (spec section 9). Wait for an explicit go.

- [ ] **Step 4: Apply**

```bash
.venv/Scripts/python tools/merge_parallel_reports.py reconcile
```
Expected: `N applied, 0 already present; replay_ok=True` and the same after-counts as the dry run.

- [ ] **Step 5: Re-pin the live counts**

In `tests/test_ledger_committed.py`, in `test_the_rename_leaves_the_committed_counts_and_the_replay_untouched` and `test_the_protection_rule_leaves_the_published_counts_untouched`, replace the pinned 4351, 1954, 397 and 1509 with the after-values Step 4 printed, keeping the old value in the trailing comment in the file's style, e.g. `== 4222   # 4351 before the parallel-report merge (2026-10-xx)`. Leave `flagged == 34` unless the suite shows it moved.

- [ ] **Step 6: Full suite and commit**

```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider
git add data/ledger tests/test_ledger_committed.py runs/parallel-reports/reconcile-for-user.json
git commit -F - <<'EOF'
ledger: parallel copies take duplicate_of and leave the counts (rule parallel-report-merge-v1); user-list groups kept for a review round

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Expected: `844 passed, 1 xfailed`. Put the before and after relevant counts in the commit subject when you run it.

---

### Task 10: Documentation, final check, finish (controller)

**Files:**
- Modify: `README.md:164` (patch log), plus a short "Parallel reports" block after the cycle-map section
- Modify: `CONTEXT.md` (a **Parallel report** entry under "The record")
- Modify: `reports/handoff-cycle-004.md` (append a "Readiness pass" section)
- Modify: `docs/superpowers/specs/2026-10-04-readiness-pass-design.md` (append "## 10. As built")

- [ ] **Step 1: README**

Replace `` `data/ledger/patches.jsonl` the append-only log`` on line 164 with
`` `data/ledger/patches/NNNN.jsonl` the append-only log (25 MB segments; concatenated in order they are the log)``.
After the cycle-map section add:

```
## Parallel reports (one decision printed in two reporters)

.venv\Scripts\python tools\merge_parallel_reports.py score | sample | threshold | apply [--dry-run] | undo --method <m> | reconcile [--dry-run]
# Merges live in corpus.db's parallel_reports table (undo clears exactly them) and in
# runs/parallel-reports/merges.jsonl; the ledger keeps one copy per decision (duplicate_of).
# A run packed before a merge must be re-packed (pipeline/rank.py) before map_reader reads it.
```

- [ ] **Step 2: CONTEXT entry (after **Two-tier count**)**

```
**Parallel report**:
One decision printed in more than one reporter. The corpus keeps one copy canonical and marks
the others `is_duplicate_of` it; in the ledger a second copy's record carries `duplicate_of`
and is left out of every count. Copies found by opinion text rather than by CAP's citations
are listed in `parallel_reports` and can be undone.
_Avoid_: duplicate case (a duplicate can also be one volume ingested twice)
```

- [ ] **Step 3: Handoff section**

Append to `reports/handoff-cycle-004.md` a `## Readiness pass (2026-10-xx)` section with: the venv now on uv CPython 3.11.15 from `requirements-lock.txt` (`.venv-hermes` to delete after the first successful run); the patch log as segments (content hash unchanged at the split); the merge (method, threshold, applied count, canonical count after); the reconcile (count deltas, the user-list path and its size); carry-forwards: re-pack `cycle-004-shard-02` before reading its tail, `build_gold.py` must follow `is_duplicate_of` before any gold rebuild, the `keep` gap (part 2), KWIC proximity and per-jurisdiction frequency (part 1), the explainer's library figure changes at Checkpoint 2.

- [ ] **Step 4: Spec as-built**

Append `## 10. As built` to the spec with the same numbers, the final test count, and the plan's three amendments (minimum-length guard, map-reader refusal instead of a read-time skip, `build_gold` parked).

- [ ] **Step 5: Final check and commit**

```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider
git add README.md CONTEXT.md reports/handoff-cycle-004.md docs/superpowers/specs/2026-10-04-readiness-pass-design.md
git commit -F - <<'EOF'
docs: readiness pass as built (README patch log and parallel reports, CONTEXT parallel report, handoff, spec section 10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 6: Finish the branch**

Use superpowers:finishing-a-development-branch (the user merges locally), then `git push origin main` and confirm `git rev-list --count origin/main..main` is 0. Update the project memory: state, the Checkpoint 2 caution (library figure), and the `.venv-hermes` deletion still to do.
