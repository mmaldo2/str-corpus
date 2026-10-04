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
