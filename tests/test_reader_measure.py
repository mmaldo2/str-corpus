"""Scoring v2 (spec section 6). Two numbers per field, not one: `decided_rate` says how
often the reader gave no usable answer at all after the gate, `agreement_decided` how often
it agreed when both sides answered. 3A blended them, so a model that left polarity null
scored the same as one that got polarity wrong. Polarity and who_was_letting are judged only
where both sides call the case relevant, so a relevance miss is scored once, as relevance."""
import math

import pytest

from corpus_engine.reader.measure import (BAR_FIELDS, excluded_fields, field_scores,
                                          score_candidate, select_reader, stability,
                                          subscription_keys)
from corpus_engine.reader.model import (Budget, ModelPin, Plan, ReadingOutcome, RecordResult,
                                        Response, StopReason, Unit, UnitResult)

REF = [
    {"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
    {"case_id": 2, "source": "human", "relevant": True, "polarity": "adverse", "who_was_letting": "commercial_operator"},
    {"case_id": 3, "source": "human", "relevant": True, "polarity": "mixed", "who_was_letting": "unclear"},
    {"case_id": 4, "source": "human", "relevant": False, "polarity": None, "who_was_letting": None},
    {"case_id": 5, "source": "machine", "relevant": False, "polarity": None, "who_was_letting": None},
]
PRED = [
    {"case_id": 1, "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
     "quotes": [1, 2], "extraction_status": "ok"},
    {"case_id": 2, "relevant": True, "polarity": None, "who_was_letting": "non_resident_owner",
     "quotes": [1], "extraction_status": "partial"},
    {"case_id": 3, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
    {"case_id": 4, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
    {"case_id": 5, "relevant": False, "polarity": None, "who_was_letting": None,
     "quotes": [], "extraction_status": "ok"},
]


_UNSET = object()   # distinguishes "cost_usd not supplied" (default to spend) from an
                    # explicit cost_usd=None (a real subscription response, no charge)


def _out(recs, dropped, spend, *, cache_hit=False, cost_usd=_UNSET, list_cost=None):
    rr = tuple(RecordResult(r["case_id"], r, r.get("extraction_status", "ok"), d, ())
               for r, d in zip(recs, dropped))
    resp = Response("", 1, 1, spend if cost_usd is _UNSET else cost_usd, {"provider": "P"}, "stop",
                    None, {"list_cost_usd": list_cost} if list_cost is not None else {})
    u = UnitResult("u", "ok", rr, resp, cache_hit)
    plan = Plan("k", (Unit("u", tuple(r["case_id"] for r in recs)),), "cb", ModelPin("m", "f"), Budget(), "w")
    return ReadingOutcome(plan, [u], [], spend, 1, 1, 2.0, StopReason("done"), {}, "")


def test_field_scores_separates_undecided_from_disagreeing():
    s = field_scores(PRED, REF)
    # relevant: every reference row is decided; case 3 is the one miss
    assert s["relevant"]["n_reference_decided"] == 5 and s["relevant"]["n_both_decided"] == 5
    assert s["relevant"]["decided_rate"] == 1.0 and s["relevant"]["agreement_decided"] == 4 / 5
    # polarity: reference-decided on 1, 2, 3; case 3 drops out because the prediction says
    # irrelevant (that miss is already counted once, as relevance); case 2 answered null
    assert s["polarity"]["n_reference_decided"] == 2 and s["polarity"]["n_both_decided"] == 1
    assert s["polarity"]["decided_rate"] == 0.5 and s["polarity"]["agreement_decided"] == 1.0
    assert s["polarity"]["n_prediction_irrelevant"] == 1
    # who_was_letting: both answered on 1 and 2, and disagreed on 2
    assert s["who_was_letting"]["decided_rate"] == 1.0 and s["who_was_letting"]["agreement_decided"] == 0.5
    assert abs(s["macro"] - (4 / 5 + 1.0 + 0.5) / 3) < 1e-9


def test_a_reference_field_marked_unsure_is_excluded_for_that_field_only():
    s = field_scores(PRED, REF, excluded={2: {"who_was_letting"}})
    assert s["who_was_letting"]["n_reference_decided"] == 1 and s["who_was_letting"]["agreement_decided"] == 1.0
    assert s["polarity"]["n_reference_decided"] == 2          # the case stays in for the other fields
    assert excluded_fields([{"case_id": 2, "excluded_fields": ["who_was_letting"]},
                            {"case_id": 3, "excluded_fields": []}]) == {2: {"who_was_letting"}}


def test_excluded_fields_reads_review_flags_too_and_unions_with_the_explicit_list():
    """R7: exclusions come from `needs-review:<field>` flags at
    `record["review"]["flags"]`, unioned with any explicit `excluded_fields` list a kit
    case row may already carry (Task 7 writes that list at kit-build time)."""
    rows = [
        {"case_id": 4, "review": {"flags": ["needs-review:polarity", "citator-checked"]}},
        {"case_id": 5, "excluded_fields": ["who_was_letting"],
         "review": {"flags": ["needs-review:polarity"]}},
        {"case_id": 6, "review": {"flags": []}},
    ]
    ex = excluded_fields(rows)
    assert ex[4] == {"polarity"}                       # flag-only source
    assert ex[5] == {"who_was_letting", "polarity"}     # union of both sources
    assert 6 not in ex                                  # nothing to exclude, not an empty-set entry


def test_a_reference_polarity_of_irrelevant_is_not_a_decided_value():
    ref = [dict(REF[0], polarity="irrelevant")]
    s = field_scores([PRED[0]], ref)
    assert s["polarity"]["n_reference_decided"] == 0 and s["polarity"]["agreement_decided"] == 0.0


def test_score_candidate_reports_both_accepted_counts_and_prices_only_a_paid_run():
    s = score_candidate(_out(PRED, [0, 1, 0, 0, 0], 0.30), REF)
    assert s["fidelity"] == 3 / 4                       # one dropped quote among relevant records
    assert s["accepted"] == 5 and s["accepted_full"] == 4      # case 2 is partial
    assert s["priced"] is True and abs(s["cost_per_accepted"] - 0.06) < 1e-9
    assert s["agreement_machine_irrelevant"] == 1.0 and s["schema_compliance"] == 1.0
    # R5: agreement is over HUMAN reference rows only (cases 1-4), as measurement v1 did -
    # the machine row (case 5) is not part of the field bar, so "relevant" is 3/4 (case 3
    # miscalled), not 4/5 (which would silently credit the machine row's correct null read).
    assert abs(s["macro"] - (3 / 4 + 1.0 + 0.5) / 3) < 1e-9 and set(s["fields"]) == set(BAR_FIELDS)


def test_a_subscription_candidate_is_unpriced_and_records_the_list_cost():
    s = score_candidate(_out(PRED, [0, 0, 0, 0, 0], 0.0, cost_usd=None, list_cost=0.42), REF)
    assert s["priced"] is False and s["cost_per_accepted"] == math.inf
    assert s["list_cost_usd"] == 0.42 and s["spend_usd"] == 0.0


def test_a_real_cost_alongside_a_list_cost_still_counts_as_priced():
    """R6: `priced` is decided from `cost_usd` alone, never from `list_cost_usd`'s mere
    presence - a response can carry both a genuine charge and a list-price annotation."""
    s = score_candidate(_out(PRED, [0, 0, 0, 0, 0], 0.30, cost_usd=0.30, list_cost=0.10), REF)
    assert s["priced"] is True and abs(s["cost_per_accepted"] - 0.06) < 1e-9
    assert s["list_cost_usd"] == 0.10 and s["spend_usd"] == 0.30


def test_score_candidate_spend_override_prices_a_cache_only_rerun():
    s = score_candidate(_out(PRED, [0, 0, 0, 0, 0], 0.0, cache_hit=True), REF, spend_usd_override=0.5)
    assert s["priced"] is True and abs(s["cost_per_accepted"] - 0.1) < 1e-9
    assert score_candidate(_out(PRED, [0] * 5, 0.0, cache_hit=True), REF)["priced"] is False


def _s(macro, *, fidelity=0.99, decided=0.95):
    fields = {f: {"decided_rate": decided, "agreement_decided": macro,
                  "n_reference_decided": 100, "n_both_decided": 95, "n_prediction_irrelevant": 0}
              for f in BAR_FIELDS}
    return {"fidelity": fidelity, "fields": fields, "macro": macro}


def test_select_reader_applies_both_floors():
    r = select_reader({"a": _s(0.99, fidelity=0.90), "b": _s(0.88)})
    assert r["winner"] == "b" and "a" in r["eliminated"] and "fidelity" in r["eliminated"]["a"]
    r2 = select_reader({"a": _s(0.99, decided=0.80)})
    assert r2["winner"] is None and "decided rate" in r2["eliminated"]["a"] and r2["shortfall"] is True


def test_a_subscription_candidate_wins_within_two_points_of_the_best():
    subs = {"claude-cli/claude-sonnet-5"}
    r = select_reader({"openai/gpt-5.6-terra": _s(0.88), "claude-cli/claude-sonnet-5": _s(0.87)},
                      subscription=subs)
    assert r["winner"] == "claude-cli/claude-sonnet-5" and r["shortfall"] is False
    assert "within 0.02" in r["rule"] and abs(r["best_macro"] - 0.88) < 1e-9
    r2 = select_reader({"openai/gpt-5.6-terra": _s(0.90), "claude-cli/claude-sonnet-5": _s(0.87)},
                       subscription=subs)
    assert r2["winner"] == "openai/gpt-5.6-terra" and "highest macro" in r2["rule"]


def test_the_tie_break_also_applies_when_nobody_reaches_the_bar():
    """D4's tie-break is stated over survivors, and the reason for it - the subscription
    read costs nothing - does not change when the bar is missed. The shortfall is disclosed
    either way, and the rule string says which branch fired."""
    r = select_reader({"openai/gpt-5.6-terra": _s(0.80), "claude-cli/claude-opus-5": _s(0.79)},
                      subscription={"claude-cli/claude-opus-5"})
    assert r["winner"] == "claude-cli/claude-opus-5" and r["shortfall"] is True
    assert "no survivor reached 0.85" in r["rule"]


SUB_LABEL = "claude-cli/claude-sonnet-5@claude-cli:-"


def test_the_subscription_tie_break_is_keyed_on_pin_labels():
    """The tie-break matches D4's subscription set against the keys of `scores`, and a
    caller working from pins keys those by LABEL. So the set is labels: a subscription
    label within 0.02 of the best surviving macro wins, exactly as the model-id spelling
    was always meant to."""
    scores = {"google/gemini-3.7-flash@-:-": _s(0.8900), SUB_LABEL: _s(0.8750)}
    r = select_reader(scores, subscription={SUB_LABEL})
    assert r["winner"] == SUB_LABEL and r["shortfall"] is False
    assert "within 0.02" in r["rule"] and abs(r["best_macro"] - 0.8900) < 1e-9


def test_the_model_id_form_alone_matches_nothing_when_the_scores_are_keyed_by_label():
    """Regression for the dead tie-break: the tool passed `{c["model_id"] ...}` while the
    keys being tested were pin labels, so `k in subscription` was never true and the
    subscription branch could not fire. A label carries its own model id, so the label
    form matches BOTH spellings; the bare model id matches only one."""
    scores = {"google/gemini-3.7-flash@-:-": _s(0.8900), SUB_LABEL: _s(0.8750)}
    dead = select_reader(scores, subscription={"claude-cli/claude-sonnet-5"})
    assert dead["winner"] == "google/gemini-3.7-flash@-:-" and "highest macro" in dead["rule"]

    # the same labels still win over the manifest's own model-id-keyed scores
    by_id = {"google/gemini-3.7-flash": _s(0.8900), "claude-cli/claude-sonnet-5": _s(0.8750)}
    assert select_reader(by_id, subscription={SUB_LABEL})["winner"] == "claude-cli/claude-sonnet-5"
    assert subscription_keys(by_id, {SUB_LABEL}) == {"claude-cli/claude-sonnet-5"}
    assert subscription_keys(scores, {SUB_LABEL}) == {SUB_LABEL}
    assert subscription_keys(scores, {"claude-cli/claude-sonnet-5"}) == set()


def test_the_decided_rate_floor_is_compared_unrounded_and_says_which_number_failed():
    """The floor is applied to the rate as computed. 0.8974 rounds to 0.90 and is still
    below the floor; 0.9000 is not below it and passes. The reason records the exact
    number, so the manifest can say glm went out on a polarity decided rate of 0.8970
    rather than leaving a reader to guess."""
    assert select_reader({"a": _s(0.95, decided=0.8974)})["winner"] is None
    assert select_reader({"a": _s(0.95, decided=0.9000)})["winner"] == "a"

    glm = _s(0.8512)
    glm["fields"]["polarity"]["decided_rate"] = 0.8970          # the live 2026-09-05 number
    r = select_reader({"z-ai/glm-5.3": glm, "google/gemini-3.7-flash": _s(0.8363)})
    assert r["eliminated"]["z-ai/glm-5.3"] == ("decided rate below the 0.90 floor: "
                                               "polarity 0.8970 < 0.90")
    assert r["winner"] == "google/gemini-3.7-flash" and r["survivors"] == ["google/gemini-3.7-flash"]


def test_selection_is_deterministic_on_an_exact_tie():
    r = select_reader({"b/two": _s(0.90), "a/one": _s(0.90)})
    assert r["winner"] == "a/one" and r["survivors"] == ["a/one", "b/two"]


def test_stability_reports_agreement_over_both_decided_plus_second_reads_decided_rate():
    """R12: a case where the second read went null is not instability - it is scored
    against the second read's own decided rate, not folded into the agreement number."""
    read_a = [{"case_id": 1, "polarity": "favorable"}, {"case_id": 2, "polarity": "adverse"},
              {"case_id": 3, "polarity": "mixed"}]
    read_b = [{"case_id": 1, "polarity": "favorable"}, {"case_id": 2, "polarity": None},
              {"case_id": 3, "polarity": "adverse"}]
    s = stability(read_a, read_b, fields=("polarity",))
    assert s["polarity"]["agreement_decided"] == 0.5             # case 2 drops out; 1 of 2 remaining agree
    assert abs(s["polarity"]["decided_rate_b"] - 2 / 3) < 1e-9
