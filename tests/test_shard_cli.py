"""CLI guards on pipeline/shard.py.

These tests never touch data/db/corpus.db: the guard under test exits before any
domain load or store.connect(), and the test asserts that by making both explode.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import shard as shard_cli  # noqa: E402

BATCHES_ONLY_MSG = ("--batches-only is no longer supported under the selector engine; "
                    "re-run without it (batching always follows sharding)")


def test_batches_only_exits_before_touching_the_database(monkeypatch):
    def boom(*a, **k):                                    # pragma: no cover - must never run
        raise AssertionError("shard.py opened the store despite --batches-only")

    monkeypatch.setattr(shard_cli.store, "connect", boom)
    monkeypatch.setattr(shard_cli, "load_domain", boom)
    monkeypatch.setattr(sys, "argv", ["shard.py", "--run-id", "cycle-004-shard-01", "--batches-only"])

    with pytest.raises(SystemExit) as exc:
        shard_cli.main()
    assert str(exc.value) == BATCHES_ONLY_MSG
