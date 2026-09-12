"""corpus_engine.evaluation.stats: Wilson intervals and Cohen's kappa against known values."""
import math
import pytest
from corpus_engine.evaluation import stats
from corpus_engine.evaluation.types import Estimate


def test_wilson_interval_matches_published_values():
    lo, hi = stats.wilson_interval(0, 10)                 # zero successes: lower bound is 0
    assert lo == 0.0 and abs(hi - 0.2775) < 0.001
    lo, hi = stats.wilson_interval(10, 10)
    assert abs(lo - 0.7225) < 0.001 and hi == 1.0
    lo, hi = stats.wilson_interval(75, 100)               # Wilson 95%: 0.657 .. 0.825
    assert abs(lo - 0.6573) < 0.001 and abs(hi - 0.8250) < 0.001


def test_wilson_interval_refuses_n_zero():
    with pytest.raises(ValueError, match="n must be positive"):
        stats.wilson_interval(0, 0)


def test_cohens_kappa_textbook_example():
    # 50 items: both say A on 20, both say B on 15, rater1 A / rater2 B on 5, B/A on 10.
    pairs = [("A", "A")] * 20 + [("B", "B")] * 15 + [("A", "B")] * 5 + [("B", "A")] * 10
    # po = 35/50 = 0.70; pe = (25/50)(30/50) + (25/50)(20/50) = 0.30 + 0.20 = 0.50; k = 0.40
    assert abs(stats.cohens_kappa(pairs) - 0.40) < 1e-9


def test_cohens_kappa_is_undefined_with_one_category_or_no_pairs():
    assert stats.cohens_kappa([("A", "A")] * 7) is None
    assert stats.cohens_kappa([]) is None


def test_estimate_carries_the_interval_and_status():
    e = stats.estimate(75, 100)
    assert isinstance(e, Estimate) and e.value == 0.75 and e.n == 100 and e.status == "ok"
    assert abs(e.lo - 0.6573) < 0.001
    z = stats.estimate(0, 0)
    assert z.status == "undefined" and z.value is None and z.n == 0
