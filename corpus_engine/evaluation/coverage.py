"""Measure 5: what the unread tail of shard 02 plausibly holds, as scenarios, never a bound."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Mapping
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance

METHOD_VERSION = "coverage-1"
BAND_WIDTH = 0.05
MIN_BAND_CASES = 200
OBSERVED_TAIL_YIELD = 0.11          # reports/map-cycle-004-shard-02.md §10: 11% below score 0.3


@dataclass(frozen=True)
class Band:
    lo: float
    hi: float
    read_cases: int
    relevant: int
    unread_cases: int


@dataclass(frozen=True)
class Scenario:
    name: str
    assumption: str
    estimated_relevant: int


@dataclass(frozen=True)
class Coverage:
    envelope: Envelope
    bands: tuple[Band, ...]
    scenarios: tuple[Scenario, ...]


def _band_of(score: float) -> tuple[float, float]:
    # score / BAND_WIDTH can land a hair under an exact multiple in binary floating
    # point (e.g. 0.15 / 0.05 == 2.9999999999999996), which would floor a boundary
    # score into the band below it; a small epsilon before floor keeps band edges
    # (0.05, 0.10, 0.15, ...) in the band they name.
    lo = round(math.floor(score / BAND_WIDTH + 1e-9) * BAND_WIDTH, 2)
    return (lo, round(lo + BAND_WIDTH, 2))


def tail_coverage(table: Mapping) -> Coverage:
    acc: dict[tuple[float, float], list[int]] = {}
    for b in table["batches"]:
        key = _band_of(float(b["score"]))
        row = acc.setdefault(key, [0, 0, 0])
        if b["read"]:
            row[0] += int(b["cases"]); row[1] += int(b["relevant"] or 0)
        else:
            row[2] += int(b["cases"])
    bands = tuple(Band(lo, hi, r, k, u) for (lo, hi), (r, k, u) in sorted(acc.items()))
    unread = sum(b.unread_cases for b in bands)
    prov = Provenance(inputs=(("bands-table", str(table.get("map_manifest_sha256")), "map-manifest"),),
                      run_ids=(str(table.get("run_id")),))
    limitations = (
        "Batches were read in a rule-driven, adaptively stopped order, so read-band yields are "
        "not a random sample of the tail.",
        "Unsignaled cases and reader false negatives are unmeasured; the estimate covers "
        "shard-02 candidates only.",
    )
    eligible = [b for b in bands if b.read_cases >= MIN_BAND_CASES]
    if not eligible:
        return Coverage(Envelope(METHOD_VERSION, "unread shard-02 candidate cases by ranker band",
                                 ("no read batches with at least 200 cases in a band; no scenario computed",),
                                 Uncertainty("assumption", None, "scenarios"), limitations, prov),
                        bands, ())
    lowest = min(eligible, key=lambda b: b.lo)
    rate = lowest.relevant / lowest.read_cases
    scenarios = (
        Scenario("lowest-read-band", f"the tail yields at the rate of band {lowest.lo:.2f}-{lowest.hi:.2f} "
                 f"({lowest.relevant}/{lowest.read_cases} = {rate:.3f})", round(unread * rate)),
        Scenario("half-lowest-read-band", "half that rate", round(unread * rate / 2)),
        Scenario("observed-11pct", "the 11% observed below score 0.3 in the third budget", round(unread * OBSERVED_TAIL_YIELD)),
    )
    env = Envelope(METHOD_VERSION, f"{unread} unread shard-02 candidate cases, by ranker-score band",
                   (), Uncertainty("assumption", None, "scenarios"), limitations, prov)
    return Coverage(env, bands, scenarios)
