"""Append-only patch log: data/ledger/patches.jsonl."""
from __future__ import annotations
import hashlib, json, time
from dataclasses import replace
from pathlib import Path
from corpus_engine.ledger.types import Patch


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
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> list[Patch]:
        if not self.path.exists():
            return []
        out = [Patch.from_json(json.loads(l)) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return sorted(out, key=lambda p: p.seq)

    def head(self) -> int:
        ps = self.read()
        return ps[-1].seq if ps else 0

    def append(self, patches: list[Patch], *, at: str | None = None) -> list[Patch]:
        seq = self.head()
        stamp = at or time.strftime("%Y-%m-%dT%H:%M:%S")
        stamped = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            for p in patches:
                seq += 1
                q = replace(p, seq=seq, at=p.at or stamp, patch_id=patch_id(p))
                f.write(json.dumps(q.to_json(), ensure_ascii=True) + "\n")
                stamped.append(q)
        return stamped
