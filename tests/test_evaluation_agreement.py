"""Measure 4: agreement per round and pair on substantive labels; the registry reconciliation."""
from corpus_engine.evaluation.agreement import agreement, effective_label, WITHDRAWN


def _queue():
    return {"run_id": "r1", "sections": {"A": [
        {"case_id": 1, "decide_field": "polarity", "values": {"polarity": "favorable"}},
        {"case_id": 2, "decide_field": "polarity", "values": {"polarity": "favorable"}},
        {"case_id": 3, "decide_field": "polarity", "values": {"polarity": "mixed"}},
        {"case_id": 4, "decide_field": "polarity", "values": {"polarity": "favorable"}}]}}


def _dec(cid, field, decision, value=None):
    d = {"case_id": cid, "field": field, "decision": decision, "note": ""}
    if value is not None:
        d["value"] = value
    return d


def test_effective_label_resolves_keep_set_adopt_withdraw_unsure():
    card = {"decide_field": "polarity", "values": {"polarity": "favorable"}}
    assert effective_label(_dec(1, "polarity", "keep"), card, None) == "favorable"
    assert effective_label(_dec(1, "polarity", "set", "adverse"), card, None) == "adverse"
    assert effective_label(_dec(1, "polarity", "adopt"), card, {"polarity": "adverse"}) == "adverse"
    assert effective_label(_dec(1, "relevant", "set", False), card, None) == "WITHDRAWN"
    assert effective_label(_dec(1, "polarity", "unsure"), card, None) == "UNSURE"


def test_agreement_per_pair_with_bulk_rounds_excluded_and_unregistered_runs_listed():
    registry = {"rounds": [
        {"round_id": "r1", "kind": "historical", "queue": "q1.json", "checker": "c1.json",
         "claude": "cl1.json", "astra": "as1.json", "user": "u1.json",
         "selection_rule": "A: favorable + under thirty days", "user_mode": "card_by_card",
         "apply_run_ids": ["r1", "r1b"]},
        {"round_id": "r2", "kind": "historical", "queue": "q1.json", "checker": "c1.json",
         "claude": "cl1.json", "astra": "as1.json", "user": "u1.json",
         "selection_rule": "same", "user_mode": "bulk_adopted_astra", "apply_run_ids": ["r2"]}],
        "dispositions": {"seed": "the bootstrap, not a review round"}}
    files = {"q1.json": _queue(), "c1.json": {"1": {"values": {"polarity": "adverse"}}},
             "cl1.json": [_dec(1, "polarity", "keep"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "as1.json": [_dec(1, "polarity", "adopt"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "u1.json": [_dec(1, "polarity", "set", "adverse")]}
    a = agreement(registry, files, ledger_run_ids=["r1", "r1b", "r2", "seed", "orphan"])
    r1 = a.rounds[0]
    assert r1.round_id == "r1" and r1.exposure == "exposure-affected"
    ca = r1.pairs["claude-astra"]["polarity"]
    assert ca.n == 4 and ca.raw.value == 0.75                    # 1 disagrees (favorable vs adverse); withdrawals agree
    assert r1.pairs["claude-user"]["polarity"].n == 1 and r1.pairs["claude-user"]["polarity"].raw.value == 0.0
    assert r1.pairs["astra-user"]["polarity"].raw.value == 1.0
    assert r1.pairs["astra-user"]["polarity"].kappa.status == "undefined"   # one category
    assert [e["round_id"] for e in a.excluded] == ["r2"] and a.excluded[0]["cards"] == 4
    assert a.unregistered_run_ids == ("orphan",)
    assert "bulk" in a.envelope.exclusions[0]


def test_an_audit_round_is_reported_blind_with_per_field_pairs():
    registry = {"rounds": [{"round_id": "audit", "kind": "audit", "queue": "aq.json", "checker": None,
                            "claude": "ac.json", "astra": "aa.json", "user": "au.json",
                            "selection_rule": "simple random sample of machine-only relevant records",
                            "user_mode": "card_by_card", "apply_run_ids": ["audit-cycle-004"]}],
                "dispositions": {}}
    q = {"run_id": "audit", "sections": {"H": [{"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"]}]}}
    files = {"aq.json": q,
             "ac.json": [_dec(9, "relevant", "set", True), _dec(9, "polarity", "set", "adverse"), _dec(9, "who_was_letting", "set", "householder")],
             "aa.json": [_dec(9, "relevant", "set", True), _dec(9, "polarity", "set", "adverse"), _dec(9, "who_was_letting", "set", "unclear")],
             "au.json": [{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "initial_value": True},
                         {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "initial_value": "favorable"},
                         {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "householder", "initial_value": "householder"}]}
    a = agreement(registry, files, ledger_run_ids=["audit-cycle-004"])
    r = a.rounds[0]
    assert r.exposure == "blind" and r.pairs["claude-astra"]["who_was_letting"].raw.value == 0.0
    # the user pair uses the INITIAL (pre-reveal) value: claude said adverse, user initially favorable
    assert r.pairs["claude-user"]["polarity"].raw.value == 0.0


def test_effective_label_relevant_adopt_resolves_via_the_checker():
    card = {"decide_field": "relevant", "values": {"relevant": True}}
    assert effective_label(_dec(1, "relevant", "adopt"), card, {"relevant": False}) == WITHDRAWN
    assert effective_label(_dec(1, "relevant", "adopt"), card, {"relevant": True}) == "True"


def test_bulk_adopted_astra_round_keeps_claude_astra_pair_but_is_also_excluded():
    """The spec excludes a bulk_adopted_astra round from every USER pair only: claude-astra
    is still built and the round still appears in `rounds`, in addition to `excluded`."""
    registry = {"rounds": [
        {"round_id": "r2", "kind": "historical", "queue": "q1.json", "checker": "c1.json",
         "claude": "cl1.json", "astra": "as1.json", "user": "u1.json",
         "selection_rule": "same", "user_mode": "bulk_adopted_astra", "apply_run_ids": ["r2"]}],
        "dispositions": {}}
    files = {"q1.json": _queue(), "c1.json": {"1": {"values": {"polarity": "adverse"}}},
             "cl1.json": [_dec(1, "polarity", "keep"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "as1.json": [_dec(1, "polarity", "adopt"), _dec(2, "polarity", "set", "adverse"),
                          _dec(3, "polarity", "set", "adverse"), _dec(4, "relevant", "set", False)],
             "u1.json": [_dec(1, "polarity", "set", "adverse")]}
    a = agreement(registry, files, ledger_run_ids=["r2"])
    assert len(a.rounds) == 1
    r2 = a.rounds[0]
    assert r2.round_id == "r2"
    assert set(r2.pairs.keys()) == {"claude-astra"}
    assert r2.pairs["claude-astra"]["polarity"].n == 4
    assert [e["round_id"] for e in a.excluded] == ["r2"]
    assert "user pairs excluded" in a.excluded[0]["reason"]


def test_agreement_omits_pairs_when_a_reader_file_is_null():
    """Mirrors the real registry's reread-2 round: astra and user are null. The measure must
    build only the readers whose file is named and must not raise for the missing pairs."""
    registry = {"rounds": [
        {"round_id": "reread-2", "kind": "historical", "queue": "q2.json", "checker": "c2.json",
         "claude": "cl2.json", "astra": None, "user": None,
         "selection_rule": "E and F cards deferred from round 1", "user_mode": "none",
         "apply_run_ids": ["reread-round-2"]}],
        "dispositions": {}}
    queue = {"run_id": "r2", "sections": {"E": [
        {"case_id": 1, "decide_field": "polarity", "values": {"polarity": "favorable"}}]}}
    files = {"q2.json": queue, "c2.json": {"1": {"values": {"polarity": "adverse"}}},
             "cl2.json": [_dec(1, "polarity", "keep")]}
    a = agreement(registry, files, ledger_run_ids=["reread-round-2"])
    r = a.rounds[0]
    assert r.round_id == "reread-2" and r.exposure == "exposure-affected"
    assert r.pairs == {}
    assert a.unregistered_run_ids == ()
