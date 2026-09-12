"""Measures 2-3: precision and field accuracy from the frozen sample and the audit outcomes."""
from corpus_engine.evaluation.precision import precision_and_accuracy


def _manifest(n=4):
    recs = [{"case_id": i, "record": {"relevant": True, "polarity": "favorable", "who_was_letting": "householder"},
             "reader_run_id": "r", "prompt_version": "v", "rank_score": 0.5, "band": "0.50-0.55",
             "cell": "1900-1930|N.Y.", "opinion_sha256": "o"} for i in range(1, n + 1)]
    recs[1]["record"]["who_was_letting"] = "commercial_operator"
    return {"drawn_at": "t", "ledger_head_seq": 100, "ledger_content_sha256": "h", "frame_size": 2842,
            "frame_sha256": "f", "seed": 7, "method": "random.Random(seed).sample", "n": n,
            "tool_revision": "g", "brief_sha256": "b", "records": recs}


def _val(rel, pol=None, who=None):
    return {"relevant": rel, "polarity": pol, "who_was_letting": who}


def test_rates_confusions_subgroup_and_revisions():
    out = {"run_id": "audit-cycle-004", "applied_seq_range": [101, 140],
           "drift": {"checked": 4, "changed": [], "disposition": "none"},
           "records": {
               "1": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "householder"),
                     "revised_reason": None, "status": "decided"},
               "2": {"draw_time": _val(True, "favorable", "commercial_operator"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "adverse", "commercial_operator"), "user_final": _val(True, "adverse", "commercial_operator"),
                     "revised_reason": None, "status": "decided"},
               "3": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(False), "user_final": _val(False), "revised_reason": None, "status": "decided"},
               "4": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "unclear"),
                     "revised_reason": "the model note pointed to the lease", "status": "unresolved"}}}
    p = precision_and_accuracy(_manifest(), out)
    assert (p.n, p.decided, p.unresolved) == (4, 3, 1)
    assert p.precision.n == 3 and abs(p.precision.value - 2 / 3) < 1e-9
    assert p.field_accuracy["polarity"].n == 2 and p.field_accuracy["polarity"].value == 0.5
    assert p.field_accuracy["who_was_letting"].value == 1.0
    assert p.joint_correctness.n == 3 and abs(p.joint_correctness.value - 1 / 3) < 1e-9
    assert p.confusion["polarity"]["favorable"] == {"favorable": 1, "adverse": 1, "withdrawn": 1}
    assert p.subgroups["favorable_householder"]["n"] == 3         # draw-time favorable+householder: cases 1,3,4
    assert p.subgroups["favorable_householder"]["precision"].n == 2   # 4 is unresolved
    assert p.revisions == {"relevant": 0, "polarity": 0, "who_was_letting": 0}   # 4 revised but is unresolved -> not counted
    assert p.sampling_seq == 100 and p.frame_size == 2842 and p.drift["checked"] == 4
    assert any("unresolved" in s for s in p.envelope.limitations)


def test_without_outcomes_everything_is_unavailable():
    p = precision_and_accuracy(_manifest(), None)
    assert p.precision.status == "unavailable" and p.field_accuracy["polarity"].status == "unavailable"
    assert p.decided == 0 and "not yet" in p.envelope.exclusions[0]


def test_unknown_case_in_outcomes_is_refused():
    import pytest
    out = {"run_id": "a", "applied_seq_range": [1, 2], "drift": {}, "records": {"99": {"status": "decided",
           "draw_time": _val(True), "user_initial": _val(True), "user_final": _val(True), "claude": None, "astra": None,
           "checker": None, "revised_reason": None}}}
    with pytest.raises(ValueError, match="99 is not in the sample"):
        precision_and_accuracy(_manifest(), out)


def test_missing_case_in_outcomes_counted_as_unresolved():
    out = {"run_id": "audit-cycle-004", "applied_seq_range": [101, 140],
           "drift": {"checked": 3, "changed": [], "disposition": "none"},
           "records": {
               "1": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "householder"),
                     "revised_reason": None, "status": "decided"},
               "2": {"draw_time": _val(True, "favorable", "commercial_operator"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "adverse", "commercial_operator"), "user_final": _val(True, "adverse", "commercial_operator"),
                     "revised_reason": None, "status": "decided"},
               "3": {"draw_time": _val(True, "favorable", "householder"), "claude": None, "astra": None, "checker": None,
                     "user_initial": _val(True, "favorable", "householder"), "user_final": _val(True, "favorable", "householder"),
                     "revised_reason": None, "status": "decided"}}}
    p = precision_and_accuracy(_manifest(), out)
    assert (p.n, p.decided, p.unresolved) == (4, 3, 1)
    assert p.precision.n == 3 and abs(p.precision.value - 1.0) < 1e-9
    assert "case 4: missing" in p.envelope.exclusions
    assert any("missing" in s for s in p.envelope.limitations)
