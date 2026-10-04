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
