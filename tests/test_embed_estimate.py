import shutil
from corpus_engine import store
from corpus_engine.indexer.embed import EmbedRun, estimate_tokens
from corpus_engine.indexer.embedders import FakeEmbedder

def test_estimate_scales_sample_to_population(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    conn.execute("DELETE FROM chunks"); conn.commit()
    run = EmbedRun("fake-16", "fake", "r", 16, "int8", 60, 10, "{name}\n", "test")
    cases, tokens = estimate_tokens(conn, FakeEmbedder().tokenizer, run, sample=20)
    assert cases == conn.execute("SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL AND norm_text != ''").fetchone()[0]
    assert tokens > cases * 100
