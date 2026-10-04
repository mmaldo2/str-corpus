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


def patch_id(p: Patch) -> str:
    """Content-addressed id from the patch's semantic fields (not `note`, which
    is batch-level provenance, not part of what the patch does).

    Known hazard: because the id is content-addressed, two legitimately
    distinct patches that happen to carry identical case_id/op/field/new/why/
    basis/cycle/cascade collide on the same id, and `apply()` treats the
    later one as a duplicate to skip. 175 such rows exist in the bootstrap
    log, all effect-idempotent status sets (e.g. two `set review.status
    human-adjudicated` patches for the same case and cycle) where the
    collision is harmless.
    """
    canon = json.dumps([p.case_id, p.op, p.field, p.new, p.why, p.basis.to_json(), p.cycle, p.cascade],
                       sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def provisional_seqs(patches, head_seq: int) -> list[Patch]:
    """`patches` stamped with the seqs `PatchLog.append` is about to assign them.

    A `Patch` carries `seq = 0` until it is appended, and D2's grandfather baseline
    (`fold.PROTECTION_FROM_SEQ`) reads the seq to tell a patch that is already in the log
    from one that is not - so an unstamped patch reads as history and a trial fold would let
    a machine read overwrite a human decision that the real append then refuses (review
    finding 1). Every fold of not-yet-appended patches - `Ledger.apply`'s validation, its
    `--dry-run`, a tool's projected view - stamps first, so the trial state is exactly the
    state the log will replay to. `patch_id` does not hash `seq`, so stamping changes no id
    and `append` re-stamps the same numbers under the write lock."""
    return [replace(p, seq=head_seq + i + 1) for i, p in enumerate(patches)]


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
