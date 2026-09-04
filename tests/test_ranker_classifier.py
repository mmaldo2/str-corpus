import json, numpy as np, pytest
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.classifier import ClassifierRanker, train
from corpus_engine.ranker.evaluate import average_precision, evaluate_scores, precision_at
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.labels import Label
from tests.helpers.ranker_fixture import make_ranker_db

def test_metrics():
    y = np.array([1, 0, 1, 0]); s = np.array([0.9, 0.8, 0.7, 0.1])
    assert abs(average_precision(y, s) - (1.0 + 2 / 3) / 2) < 1e-9 and precision_at(y, s, 2) == 0.5
    assert average_precision(np.zeros(3), np.arange(3)) == 0.0

def _synthetic_labels(conn):
    # positives: cases with >= 2 distinct selectors; negatives: the rest (a learnable rule)
    rows = conn.execute("SELECT c.case_id, c.era_partition, c.jurisdiction, count(DISTINCT s.selector_id) FROM cases c JOIN signals s ON s.case_id=c.case_id WHERE c.is_duplicate_of IS NULL GROUP BY 1").fetchall()
    return [Label(cid, int(n >= 2), 3.0 if n >= 3 else 1.0, n >= 3, era, jur) for cid, era, jur, n in rows]

def test_train_beats_chance_scores_and_refuses_layout_drift(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    labels = _synthetic_labels(conn); held = labels[::4]; train_set = [l for l in labels if l not in set(held)]
    out = tmp_path / "v9"
    man = train(conn, dom, train_set, held, version="v9", out_dir=out, commit="deadbeef")
    assert (out / "model.npz").exists() and man["ranker_id"] == "classifier:v9" and man["cv_C"] in (0.01, 0.03, 0.1, 0.3, 1, 3)
    base = sum(l.label for l in held) / len(held)
    assert man["metrics"]["classifier"]["ap_all"] > base + 0.1
    r = ClassifierRanker(out); s = r.score(conn, "run", [l.case_id for l in held])
    ev = evaluate_scores(held, s); assert abs(ev["ap_all"] - man["metrics"]["classifier"]["ap_all"]) < 1e-6
    assert s == r.score(conn, "run", [l.case_id for l in held]) and len(r.digest()) == 16
    with pytest.raises(ValueError, match="overlap"):
        train(conn, dom, train_set + held[:1], held, version="v9b", out_dir=tmp_path / "v9b", commit="x")
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8")); m["layout"]["selector_labels"][0] = "ghost-1@v1"
    (out / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="ghost-1@v1"):
        ClassifierRanker(out).check_layout(feature_layout(dom, load_selectors(dom), 512))
