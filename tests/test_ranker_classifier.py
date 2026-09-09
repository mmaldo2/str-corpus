import dataclasses, json, numpy as np, pytest
from types import SimpleNamespace
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import load_selectors
from corpus_engine.ranker.classifier import ClassifierRanker, train
from corpus_engine.ranker.evaluate import average_precision, evaluate_scores, precision_at, ships
from corpus_engine.ranker.features import feature_layout
from corpus_engine.ranker.labels import Label, sha256_file, write_heldout
from corpus_engine.ranker.ports import NullRanker
from corpus_engine.store import paths
from tests.helpers.ranker_fixture import make_ranker_db

def test_metrics():
    y = np.array([1, 0, 1, 0]); s = np.array([0.9, 0.8, 0.7, 0.1])
    assert abs(average_precision(y, s) - (1.0 + 2 / 3) / 2) < 1e-9 and precision_at(y, s, 2) == 0.5
    assert average_precision(np.zeros(3), np.arange(3)) == 0.0

def _synthetic_labels(conn):
    # positives: cases with >= 2 distinct selectors; negatives: the rest (a learnable rule)
    rows = conn.execute("SELECT c.case_id, c.era_partition, c.jurisdiction, count(DISTINCT s.selector_id) FROM cases c JOIN signals s ON s.case_id=c.case_id WHERE c.is_duplicate_of IS NULL GROUP BY 1").fetchall()
    return [Label(cid, int(n >= 2), 3.0 if n >= 3 else 1.0, n >= 3, era, jur) for cid, era, jur, n in rows]

def _training_inputs(tmp_path, fixture_db, repo_root):
    """(conn, domain, train_set, heldout) shared by every test in this module that trains: a
    fixture DB, a domain whose `.ranking` is a mutable SimpleNamespace copy of RankingSpec (so
    a test can pin `heldout_v2_sha256` without fighting the frozen dataclass), and a synthetic
    train/held-out split."""
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    real = load_domain()
    dom = dataclasses.replace(real, ranking=SimpleNamespace(**dataclasses.asdict(real.ranking)))
    labels = _synthetic_labels(conn); held = labels[::4]; train_set = [l for l in labels if l not in set(held)]
    return conn, dom, train_set, held

def test_train_beats_chance_scores_and_refuses_layout_drift(tmp_path, fixture_db, repo_root):
    conn, dom, train_set, held = _training_inputs(tmp_path, fixture_db, repo_root)
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


def test_train_writes_heldout_path_and_sha256_when_given(tmp_path, fixture_db, repo_root):
    # I-4: train() itself (not only the CLI) records the frozen held-out file's identity.
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    labels = _synthetic_labels(conn); held = labels[::4]; train_set = [l for l in labels if l not in set(held)]
    real_heldout = paths().root / dom.ranking.heldout
    out = tmp_path / "v9d"
    man = train(conn, dom, train_set, held, version="v9d", out_dir=out, commit="deadbeef", heldout_path=real_heldout)
    assert man["heldout"]["n"] == len(held)
    assert man["heldout"]["sha256"] == dom.ranking.heldout_sha256
    assert man["heldout"]["path"] == "data/eval/ranker-heldout-v1.jsonl"


def test_train_refuses_when_heldout_path_hash_does_not_match_the_pin(tmp_path, fixture_db, repo_root, monkeypatch):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root); dom = load_domain()
    labels = _synthetic_labels(conn); held = labels[::4]; train_set = [l for l in labels if l not in set(held)]
    bad_heldout = tmp_path / "tampered-heldout.jsonl"
    bad_heldout.write_text("not the frozen content\n", encoding="utf-8")
    assert sha256_file(bad_heldout) != dom.ranking.heldout_sha256

    def boom(*a, **k):                                          # pragma: no cover - must never run
        raise AssertionError("LogisticRegression must not be constructed when the held-out hash check fails")
    monkeypatch.setattr("sklearn.linear_model.LogisticRegression", boom)

    out = tmp_path / "v9e"
    with pytest.raises(ValueError, match="sha256"):
        train(conn, dom, train_set, held, version="v9e", out_dir=out, commit="x", heldout_path=bad_heldout)
    assert not (out / "model.npz").exists()


def test_the_ship_rule_needs_both_views_and_gives_no_margin():
    """D6 verbatim: strictly greater on ap_all AND on ap_reviewed. A tie does not ship."""
    better = {"ap_all": 0.51, "ap_reviewed": 0.41}
    fusion = {"ap_all": 0.50, "ap_reviewed": 0.40}
    assert ships(better, fusion) is True
    assert ships({"ap_all": 0.50, "ap_reviewed": 0.41}, fusion) is False   # tie on ap_all
    assert ships({"ap_all": 0.51, "ap_reviewed": 0.40}, fusion) is False   # tie on ap_reviewed
    assert ships({"ap_all": 0.51, "ap_reviewed": 0.39}, fusion) is False   # worse on one view


def test_train_refuses_to_overwrite_a_shipped_model_directory(tmp_path, fixture_db, repo_root):
    conn, dom, train_set, held = _training_inputs(tmp_path, fixture_db, repo_root)
    out = tmp_path / "v9f"
    train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x")
    with pytest.raises(ValueError, match="already holds a trained model"):
        train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x")
    train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x", overwrite=True)


def test_train_records_extra_rankers_and_the_pin_it_verified(tmp_path, fixture_db, repo_root):
    conn, dom, train_set, held = _training_inputs(tmp_path, fixture_db, repo_root)
    heldout = tmp_path / "v2.jsonl"
    write_heldout(heldout, held)
    dom.ranking.heldout_v2_sha256 = sha256_file(heldout)
    man = train(conn, dom, train_set, held, version="v9g", out_dir=tmp_path / "v9g", commit="x",
                heldout_path=heldout, heldout_pin="heldout_v2_sha256",
                extra_rankers={"classifier:v1": NullRanker()})
    assert man["heldout"]["pin"] == "heldout_v2_sha256"
    assert set(man["metrics"]) == {"classifier", "fusion", "classifier:v1"}
    assert man["metrics"]["classifier:v1"]["n_all"] == len(held)
