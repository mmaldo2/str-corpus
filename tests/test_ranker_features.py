import numpy as np
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.features import (FeatureLayout, best_cosine, case_features, feature_layout,
                                           lexical_density, signal_summary)
from tests.helpers.ranker_fixture import make_ranker_db

def _layout(dom):
    return feature_layout(dom, load_selectors(dom), 512)

def test_layout_names_and_roundtrip():
    dom = load_domain(); lay = _layout(dom)
    assert lay.size == len(lay.names) and lay.dim == 512
    assert lay.names[:1] == [f"sel:{lay.selector_labels[0]}"] and "n_selectors" in lay.names
    assert "pagerank_pct" in lay.names and "pagerank_missing" in lay.names and "ocr_missing" in lay.names
    assert lay.names[-1] == "vec:511" and sum(n.startswith("era:") for n in lay.names) == len(dom.eras)
    assert FeatureLayout.from_json(lay.to_json()) == lay

def test_signal_summary_unions_runs_and_picks_best_chunk(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    cid = conn.execute("SELECT case_id FROM signals WHERE cosine IS NOT NULL GROUP BY case_id ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
    s = signal_summary(conn, [cid])[cid]
    top = conn.execute("SELECT chunk_id, cosine FROM signals WHERE case_id=? AND cosine IS NOT NULL ORDER BY cosine DESC, chunk_id LIMIT 1", (cid,)).fetchone()
    assert s.best_chunk_id == top[0] and abs(best_cosine(s) - top[1]) < 1e-9
    assert len(s.selectors) == conn.execute("SELECT count(DISTINCT selector_id||'@v'||selector_version) FROM signals WHERE case_id=?", (cid,)).fetchone()[0]

def test_case_features_shape_missing_indicators_and_text_vector(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain(); lay = _layout(dom)
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 40")]
    X = case_features(conn, ids, lay)
    assert X.shape == (40, lay.size) and X.dtype == np.float32 and np.isfinite(X).all()
    vec = X[:, lay.names.index("vec:0"):lay.names.index("vec:0") + 512]
    assert (np.abs(vec).sum(axis=1) > 0).all()                       # every case has a chunk vector
    conn.execute("UPDATE cases SET pagerank_pct=NULL WHERE case_id=?", (ids[0],)); conn.commit()
    X2 = case_features(conn, ids[:1], lay)
    assert X2[0, lay.names.index("pagerank_missing")] == 1.0 and X2[0, lay.names.index("pagerank_pct")] == 0.0
    # a lexical-only case gets its first chunk's vector, not zeros
    lex = conn.execute("SELECT case_id FROM signals GROUP BY case_id HAVING max(cosine) IS NULL LIMIT 1").fetchone()[0]
    X3 = case_features(conn, [lex], lay); assert np.abs(X3[0, -512:]).sum() > 0
    # same inputs twice -> identical bytes
    assert np.array_equal(case_features(conn, ids, lay), X)
