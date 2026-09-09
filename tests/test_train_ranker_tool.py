"""Guards on tools/train_ranker.py. Nothing here trains against the live store: the parser,
the two-slice exclusion and the report renderer are the units under test, and each is a pure
function over data the test supplies."""
import importlib.util
from pathlib import Path

from corpus_engine.ranker.labels import Label

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("train_ranker", ROOT / "tools" / "train_ranker.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)


def test_the_parser_carries_the_v2_flags():
    a = tr.build_parser().parse_args(["--heldout", "v2", "--tag", "v2"])
    assert a.heldout == "v2" and a.tag == "v2" and a.force is False
    assert tr.build_parser().parse_args(["--version", "v3"]).tag == "v3"   # the old spelling
    assert tr.build_parser().parse_args([]).heldout == "v1"


def test_the_training_set_excludes_both_frozen_slices():
    labels = [Label(i, i % 2, 1.0, False, "pre-1860", "N.Y.") for i in range(1, 11)]
    v1, v2 = labels[:2], labels[2:4]
    train_set, evaluated = tr.split_labels(labels, v1, v2, evaluate_on="v2")
    assert {l.case_id for l in train_set} == {5, 6, 7, 8, 9, 10}
    assert {l.case_id for l in evaluated} == {3, 4}
    train_set, evaluated = tr.split_labels(labels, v1, v2, evaluate_on="v1")
    assert {l.case_id for l in train_set} == {5, 6, 7, 8, 9, 10}
    assert {l.case_id for l in evaluated} == {1, 2}


def test_the_report_states_the_rule_the_numbers_and_the_outcome(tmp_path):
    metrics = {"classifier": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.71,
                              "ap_reviewed": 0.71, "p50_all": 0.9, "p200_all": 0.6,
                              "per_cell": {"pre-1860|N.Y.": {"n": 10, "ap": 0.5, "p50": 0.4}}},
               "classifier:v1": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.64,
                                 "ap_reviewed": 0.64, "p50_all": 0.8, "p200_all": 0.5,
                                 "per_cell": {}},
               "fusion": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.40, "ap_reviewed": 0.40,
                          "p50_all": 0.6, "p200_all": 0.3, "per_cell": {}}}
    out = tmp_path / "ranking-v2.md"
    tr.write_report(out, metrics=metrics, tag="v2",
                    heldout={"path": "data/eval/x.jsonl", "sha256": "abcdef123456789",
                             "n": 300, "pin": "heldout_v2_sha256"},
                    strata={"pre-1860|N.Y.|1": 10}, shipped=True, commit="deadbeef",
                    cv={"cv_C": 0.3, "cv_ap": 0.8}, train={"n_pos": 5, "n_neg": 5})
    text = out.read_text(encoding="utf-8")
    assert "classifier:v2" in text and "fusion:v1" in text and "classifier:v1" in text
    assert "0.7100" in text and "0.4000" in text
    assert "SHIPS" in text and "ap_reviewed equals ap_all" in text
    assert out.read_bytes().endswith(b"\n") and b"\r" not in out.read_bytes()


def test_the_report_says_what_happens_when_it_does_not_ship(tmp_path):
    metrics = {"classifier": {"n_all": 9, "n_reviewed": 9, "ap_all": 0.30, "ap_reviewed": 0.30,
                              "p50_all": 0.1, "p200_all": 0.1, "per_cell": {}},
               "fusion": {"n_all": 9, "n_reviewed": 9, "ap_all": 0.40, "ap_reviewed": 0.40,
                          "p50_all": 0.2, "p200_all": 0.2, "per_cell": {}}}
    out = tmp_path / "r.md"
    tr.write_report(out, metrics=metrics, tag="v2",
                    heldout={"path": "p", "sha256": "abcdef123456789", "n": 9,
                             "pin": "heldout_v2_sha256"},
                    strata={}, shipped=False, commit="c", cv={"cv_C": 1.0, "cv_ap": 0.5},
                    train={"n_pos": 1, "n_neg": 1})
    text = out.read_text(encoding="utf-8")
    assert "DOES NOT SHIP" in text and "classifier v1 ordering" in text
