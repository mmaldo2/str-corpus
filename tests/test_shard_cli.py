"""CLI guards on pipeline/shard.py.

These tests never touch data/db/corpus.db: the guard under test exits before any
domain load or store.connect(), and the test asserts that by making both explode.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import shard as shard_cli  # noqa: E402
from corpus_engine.ranker.ports import NullRanker  # noqa: E402

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


def _isolate_heavy_calls(monkeypatch, *, engine_shard, load_ranker):
    """Stub every module opening the DB or doing real selector/plan/rank work, so main()
    runs to completion with no store.connect() and no live-DB access (I-5, --ranker/--no-rank
    wiring). Mirrors how test_batches_only_exits_before_touching_the_database isolates itself.
    """
    monkeypatch.setattr(shard_cli.store, "connect", lambda: object())
    monkeypatch.setattr(shard_cli.store, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(shard_cli.store, "migrate", lambda conn: None)
    monkeypatch.setattr(shard_cli, "load_domain", lambda: object())
    monkeypatch.setattr(shard_cli, "migrate_coverage", lambda conn, sels: None)
    monkeypatch.setattr(shard_cli, "load_selectors", lambda *a, **k: [])
    monkeypatch.setattr(shard_cli, "partition_runs", lambda conn: {})
    monkeypatch.setattr(shard_cli, "plan", lambda *a, **k: SimpleNamespace(units=(), skips=()))
    monkeypatch.setattr(shard_cli, "LedgerSeedResolver", lambda domain: object())
    monkeypatch.setattr(shard_cli, "LocalQueryEmbedder", lambda conn: object())
    monkeypatch.setattr(shard_cli, "load_ranker", load_ranker)
    monkeypatch.setattr(shard_cli, "shard", engine_shard)


def test_no_rank_flag_calls_engine_shard_with_ranker_none(monkeypatch):
    calls = {}

    def fake_shard(conn, domain, run_id, **kwargs):
        calls["ranker"] = kwargs.get("ranker")
        return SimpleNamespace(signals_written={"a": 1}, batches_written=1, batch_dir=Path("b"),
                               cases_batched=0, excluded_already_read=0, manifest={"ranker": None})

    def boom_load_ranker(*a, **k):                          # pragma: no cover - must never run
        raise AssertionError("load_ranker must not be called under --no-rank")

    _isolate_heavy_calls(monkeypatch, engine_shard=fake_shard, load_ranker=boom_load_ranker)
    monkeypatch.setattr(sys, "argv", ["shard.py", "--run-id", "r-no-rank", "--no-rank"])

    assert shard_cli.main() == 0
    assert calls["ranker"] is None


def test_ranker_null_flag_calls_engine_shard_with_a_null_ranker(monkeypatch):
    calls = {}

    def fake_shard(conn, domain, run_id, **kwargs):
        calls["ranker"] = kwargs.get("ranker")
        return SimpleNamespace(signals_written={"a": 1}, batches_written=1, batch_dir=Path("b"),
                               cases_batched=0, excluded_already_read=0, manifest={"ranker": None})

    def fake_load_ranker(domain, conn, ranker_id):
        calls["load_ranker_id"] = ranker_id
        return NullRanker()

    _isolate_heavy_calls(monkeypatch, engine_shard=fake_shard, load_ranker=fake_load_ranker)
    monkeypatch.setattr(sys, "argv", ["shard.py", "--run-id", "r-ranker-null", "--ranker", "null"])

    assert shard_cli.main() == 0
    assert calls["load_ranker_id"] == "null"
    assert isinstance(calls["ranker"], NullRanker)
