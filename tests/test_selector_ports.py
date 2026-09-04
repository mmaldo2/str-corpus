import numpy as np, pytest, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import Partition, Selector, Skip, SelectorSpecError
from corpus_engine.selector.ports import FrozenSeedResolver, LocalQueryEmbedder, RecordedEmbedder, fingerprint

def _sel(kind, **params):
    return Selector("s", 1, kind, "c", "p", ("pre-1860",), ("Tex.",), params)

def test_recorded_embedder_by_label(repo_root):
    e = RecordedEmbedder(repo_root / "tests/fixtures/query-vectors-v3.npz")
    v = e.encode_query("ignored", label="embed-householder-letting-21@v2")
    assert v.shape == (512,) and abs(np.linalg.norm(v) - 1) < 1e-4
    with pytest.raises(KeyError):
        e.encode_query("x", label="nope@v9")

def test_fingerprint_rules(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); store.migrate(conn)
    part = [Partition(*conn.execute("SELECT era_partition, jurisdiction FROM cases WHERE is_duplicate_of IS NULL LIMIT 1").fetchone())]
    seeds = FrozenSeedResolver({"few": [1, 2], "many": list(range(10))})
    assert fingerprint(conn, _sel("fts_phrase", pattern="x"), part, seeds=seeds, min_seeds=5) == "fts:v1"
    assert fingerprint(conn, _sel("regex", pattern="x"), part, seeds=seeds, min_seeds=5) == "regex:v1"
    assert fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5) == "embed:qwen3-0.6b-512-int8|engine:v2"
    fb = fingerprint(conn, _sel("relevance_feedback", seed_set="many"), part, seeds=seeds, min_seeds=5)
    assert fb.startswith("embed:qwen3-0.6b-512-int8|engine:v2|seed:") and len(fb.split("seed:")[1]) == 16
    g = fingerprint(conn, _sel("citation_graph", seed_set="many"), part, seeds=seeds, min_seeds=5)
    assert g.startswith("graph:v1|seed:")
    s = fingerprint(conn, _sel("citation_graph", seed_set="few"), part, seeds=seeds, min_seeds=5)
    assert isinstance(s, Skip) and s.reason == "seed_unavailable"
    # mixed model: retag one case's chunks
    cid = conn.execute("SELECT case_id FROM cases WHERE era_partition=? AND jurisdiction=? AND is_duplicate_of IS NULL LIMIT 1", (part[0].era, part[0].jurisdiction)).fetchone()[0]
    conn.execute("UPDATE chunks SET embed_run='other' WHERE case_id=?", (cid,)); conn.commit()
    m = fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5)
    assert isinstance(m, Skip) and m.reason == "mixed_embedding_model"
    conn.execute("DELETE FROM chunks"); conn.commit()
    assert fingerprint(conn, _sel("embedding", query_text="q"), part, seeds=seeds, min_seeds=5).reason == "index_incomplete"

def test_local_query_embedder_refuses_unpinned_meta(tmp_path):
    p = tmp_path / "m.db"; conn = store.connect(p); store.ensure_schema(conn)
    # Test case 1: revision == "main" should raise SelectorSpecError before model loads
    conn.execute("INSERT INTO embed_meta (key, value) VALUES (?, ?)", ("model", "sentence-transformers/all-MiniLM-L6-v2"))
    conn.execute("INSERT INTO embed_meta (key, value) VALUES (?, ?)", ("revision", "main"))
    conn.execute("INSERT INTO embed_meta (key, value) VALUES (?, ?)", ("dim", "384"))
    conn.commit()
    with pytest.raises(SelectorSpecError, match="revision"):
        LocalQueryEmbedder(conn)
    # Test case 2: missing revision should raise SelectorSpecError
    conn.execute("DELETE FROM embed_meta WHERE key='revision'")
    conn.commit()
    with pytest.raises(SelectorSpecError, match="revision"):
        LocalQueryEmbedder(conn)
    # Test case 3: missing model should raise SelectorSpecError
    conn.execute("DELETE FROM embed_meta")
    conn.execute("INSERT INTO embed_meta (key, value) VALUES (?, ?)", ("revision", "abc123"))
    conn.commit()
    with pytest.raises(SelectorSpecError, match="model"):
        LocalQueryEmbedder(conn)
