import sys
from pathlib import Path

from corpus_engine import store

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from shard import missing_jurisdictions  # noqa: E402


def test_missing_jurisdictions(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.ensure_schema(conn)
    conn.executemany(
        "INSERT INTO cases (case_id, jurisdiction, is_duplicate_of) VALUES (?, ?, NULL)",
        [(1, "Tex."), (2, "Pa.")],
    )
    conn.commit()

    assert missing_jurisdictions(conn, ["Tex.", "Pa.", "Mass."]) == ["Mass."]
    assert missing_jurisdictions(conn, ["Tex."]) == []
