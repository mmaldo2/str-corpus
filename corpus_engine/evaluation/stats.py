"""Wilson score interval and Cohen's kappa, stdlib only, tested against known values."""
from __future__ import annotations
import math
from collections import Counter
from typing import Sequence
from corpus_engine.evaluation.types import Estimate


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohens_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """None when kappa is undefined: no pairs, or expected agreement is 1 (one category)."""
    n = len(pairs)
    if n == 0:
        return None
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    pe = sum(a[c] * b[c] for c in set(a) | set(b)) / (n * n)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def estimate(k: int, n: int) -> Estimate:
    if n <= 0:
        return Estimate(None, 0, None, None, "undefined")
    lo, hi = wilson_interval(k, n)
    return Estimate(k / n, n, lo, hi, "ok")
