import json, math, shutil
from types import SimpleNamespace
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.ports import FusionRanker, NullRanker, _load_classifier, load_ranker, round6
from tests.helpers.ranker_fixture import make_ranker_db

def test_round6_is_float32_then_six_places():
    assert round6(0.12345678901) == 0.123457 and isinstance(round6(1), float)
    assert round6(0.1 + 1e-9) == round6(0.1)

def test_null_and_fusion_score_every_id_deterministically(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    ids = [r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals ORDER BY case_id LIMIT 30")] + [999999999]
    lay = feature_layout(dom, load_selectors(dom), 512)
    for r in (NullRanker(), FusionRanker(lay, 0.5, 0.5)):
        s = r.score(conn, "r", ids)
        assert set(s) == set(ids) and all(isinstance(v, float) and math.isfinite(v) for v in s.values())
        assert s == r.score(conn, "r", ids) and s[999999999] == 0.0
    n = NullRanker().score(conn, "r", ids)
    dens = {cid: len({x[0] for x in conn.execute("SELECT selector_id FROM signals WHERE case_id=?", (cid,))}) for cid in ids}
    assert all(n[c] == float(dens[c]) for c in ids)
    f = FusionRanker(lay, 1.0, 0.0).score(conn, "r", ids)
    assert 0.0 <= max(f.values()) <= 1.0 and NullRanker().digest() == "" and len(FusionRanker(lay, .5, .5).digest()) == 16

def test_load_ranker_resolves_null_and_fusion(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    assert load_ranker(dom, conn, "null").ranker_id == "null"
    assert load_ranker(dom, conn, "fusion").ranker_id == "fusion:v1"

def test_load_ranker_classifier_raises_not_implemented_or_refuses_layout_drift(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    try:
        import corpus_engine.ranker.classifier
    except ModuleNotFoundError:
        with pytest.raises(NotImplementedError, match="classifier ranker is not available yet"):
            load_ranker(dom, conn, "classifier")
        return
    # module exists: the fixture DB's embed_meta dim (512) legitimately differs from the trained
    # v1 model's dim (1024), so load_ranker's check_layout call correctly refuses rather than
    # silently misaligning features against coef - see test_load_classifier_loads_real_v1_cleanly
    # for the matching-dim positive path.
    with pytest.raises(ValueError, match="retrain"):
        load_ranker(dom, conn, "classifier")

def test_load_ranker_unknown_id_raises_value_error_without_db_access(monkeypatch, tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    monkeypatch.setattr("corpus_engine.ranker.ports._dim", lambda conn: (_ for _ in ()).throw(RuntimeError("_dim must not be called")))
    monkeypatch.setattr("corpus_engine.ranker.features.feature_layout", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("feature_layout must not be called")))
    with pytest.raises(ValueError, match="unknown ranker"):
        load_ranker(dom, conn, "bogus")


def test_load_classifier_refuses_layout_drift(tmp_path, monkeypatch, repo_root):
    src = repo_root / "data" / "ranker" / "v1"
    if not (src / "model.npz").exists():
        pytest.skip("data/ranker/v1 not trained")
    dst = tmp_path / "data" / "ranker" / "v1"
    shutil.copytree(src, dst)
    manifest_path = dst / "manifest.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m["layout"]["selector_labels"][0] = "ghost-1@v1"
    manifest_path.write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr("corpus_engine.store.paths", lambda root=None: SimpleNamespace(root=tmp_path))
    dom = load_domain()
    layout = feature_layout(dom, load_selectors(dom), 1024)
    with pytest.raises(ValueError, match="ghost-1@v1"):
        _load_classifier(dom, layout)

def test_load_classifier_loads_real_v1_cleanly(repo_root):
    if not (repo_root / "data" / "ranker" / "v1" / "model.npz").exists():
        pytest.skip("data/ranker/v1 not trained")
    dom = load_domain()
    layout = feature_layout(dom, load_selectors(dom), 1024)          # v1's real training dim; the fixture DB's
                                                                       # embed_meta dim is 512 and would legitimately fail
    r = _load_classifier(dom, layout)
    assert r.ranker_id == "classifier:v1"
