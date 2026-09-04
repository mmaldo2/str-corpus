import math
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.ports import FusionRanker, NullRanker, load_ranker, round6
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
