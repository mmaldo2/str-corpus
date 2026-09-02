import shutil, sys
from pathlib import Path

from corpus_engine import store

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from shard import mixed_embed_runs  # noqa: E402


def test_mixed_embed_runs_flags_partial_reembed(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p)
    conn = store.connect(p); store.migrate(conn)
    conn.execute("UPDATE chunks SET embed_run='other' WHERE case_id = (SELECT case_id FROM chunks LIMIT 1)")
    conn.commit()
    assert len(mixed_embed_runs(conn)) > 1
