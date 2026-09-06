"""The review round (spec section 9, D4/D5).

Six sections in a fixed priority order, each record in exactly one of them with its other
reasons listed on the card, 150 cards a round and the rest carried forward. The decisions the
user saves into the page become HUMAN-basis patches - that is the only route from machine-only
to human-reviewed (D3)."""
import pytest

from corpus_engine.mapper.queue import (QUEUE_CAP, SECTIONS, Queue, QueueCard, check_queue,
                                        checker_path, classify_fuzzy, fuzzy_quotes, reasons_for,
                                        select_queue)


def _rec(cid, **over):
    r = {"case_id": cid, "relevant": True, "polarity": "adverse", "who_was_letting": "unclear",
         "duration_of_occupancy": "months", "characterization": "lease",
         "under_thirty_days": "no", "owner_freedom_characterization": "regulable_privilege",
         "restriction_nature": "zoning", "holding_summary": "h", "cite": f"{cid} X. 1",
         "name": "A v. B", "court": "Ct.", "jurisdiction": "N.Y.", "year": 1890,
         "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified"}],
         "nulled_fields": [], "extraction_status": "ok",
         "review": {"status": "machine", "flags": [], "notes": []}}
    r.update(over)
    return r


class _View:
    """The slice of LedgerView select_queue actually uses."""

    def __init__(self, records, run_id, *, reviewed=()):
        self.state = type("S", (), {"order": [r["case_id"] for r in records],
                                    "records": {r["case_id"]: r for r in records},
                                    "in_file": {r["case_id"]: bool(r.get("relevant"))
                                                for r in records}})()
        self._run = run_id
        self._reviewed = set(reviewed)
        self.patches = []

    def reviewed(self, cid):
        return cid in self._reviewed


class _Cases:
    def __init__(self, text=""):
        self.text = text
        self.asked = []

    def fetch(self, ids):
        from corpus_engine.reader.model import CaseText
        self.asked.append(list(ids))
        return [CaseText(int(c), "", "", "", "", 1890, self.text, self.text, []) for c in ids]


def _manifest(cases, disagreements=()):
    return {"run_id": "cycle-004-shard-01", "cycle": "cycle-004",
            "checker_pin": "codex-cli@-:-", "cell_order": ["1860-1900|N.Y."],
            "cells": {"1860-1900|N.Y.": {
                "cache_keys": {"b1": "K"}, "checker_disagreements": list(disagreements),
                "checker_status": {}}},
            "_case_ids": list(cases)}


def test_the_sections_are_the_D4_order_and_the_cap_is_one_fifty():
    assert QUEUE_CAP == 150
    assert [k for _s, k, _t in SECTIONS] == ["favorable_under_thirty", "householder_nights",
                                             "checker_disagreement", "polarity_mixed",
                                             "gate_erased", "fuzzy_quote"]
    assert [s for s, _k, _t in SECTIONS] == ["A", "B", "C", "D", "E", "F"]


def test_each_criterion_fires_on_exactly_what_D4_says():
    assert reasons_for(_rec(1, polarity="favorable", under_thirty_days="yes"),
                       disagreements=(), fuzzy_needs_human=False)[0] == "favorable_under_thirty"
    assert reasons_for(_rec(2, polarity="favorable", under_thirty_days="no"),
                       disagreements=(), fuzzy_needs_human=False) == ()
    assert reasons_for(_rec(3, who_was_letting="householder", duration_of_occupancy="nights"),
                       disagreements=(), fuzzy_needs_human=False) == ("householder_nights",)
    assert reasons_for(_rec(4), disagreements=({"field": "polarity"},),
                       fuzzy_needs_human=False) == ("checker_disagreement",)
    assert reasons_for(_rec(5, polarity="mixed"), disagreements=(),
                       fuzzy_needs_human=False) == ("polarity_mixed",)
    assert reasons_for(_rec(6, nulled_fields=["characterization"]), disagreements=(),
                       fuzzy_needs_human=False) == ("gate_erased",)
    assert reasons_for(_rec(7), disagreements=(), fuzzy_needs_human=True) == ("fuzzy_quote",)
    # an irrelevant record has nothing to adjudicate
    assert reasons_for(_rec(8, relevant=False, polarity=None),
                       disagreements=({"field": "relevant"},), fuzzy_needs_human=True) == ()


def test_a_disagreement_on_a_field_the_checker_never_compared_is_not_a_reason():
    """The checker compares three fields (driver.COMPARE_FIELDS). A manifest row naming any
    other field is not a reader/checker disagreement this round can show."""
    assert reasons_for(_rec(20), disagreements=({"field": "restriction_nature"},),
                       fuzzy_needs_human=False) == ()
    assert reasons_for(_rec(21), disagreements=({"field": "characterization"},),
                       fuzzy_needs_human=False) == ("checker_disagreement",)


def test_a_record_with_several_reasons_appears_once_in_its_highest_section():
    rec = _rec(9, polarity="favorable", under_thirty_days="yes",
               who_was_letting="householder", duration_of_occupancy="nights",
               nulled_fields=["restriction_nature"])
    got = reasons_for(rec, disagreements=({"field": "polarity"},), fuzzy_needs_human=True)
    assert got == ("favorable_under_thirty", "householder_nights", "checker_disagreement",
                   "gate_erased", "fuzzy_quote")


def test_the_mechanical_fuzzy_rule_is_stage_ones():
    """coverage >= 0.92 and no mismatched run longer than 4 characters."""
    src = "the lodger has not the possession, but the use only, of the apartment"
    assert classify_fuzzy("the lodger has not the possession, but the use only",
                          src)["classification"] == "trivial-ocr"
    assert classify_fuzzy("the lodger keeps possession of the whole apartment",
                          src)["classification"] == "needs-human"
    out = classify_fuzzy("the lodger has not the possession", src)
    assert 0.0 <= out["quote_coverage"] <= 1.0 and isinstance(out["miss_runs"], list)


def test_a_trivial_fuzzy_quote_on_a_clean_record_is_auto_accepted():
    """Stage 1 paired the mechanical rule with a reader `ocr-ok` pass. This slice runs no such
    pass, so the second signal is the reader's own gate outcome: nothing dropped, nothing
    nulled. A record the gate had to touch does NOT get the benefit of the doubt."""
    text = ("the lodger has not the possession, but the use only, of the apartment " * 4)
    clean = _rec(10, quotes=[{"text": "the lodger has not the possession, but the use only",
                              "supports": ["polarity"], "status": "verified-fuzzy",
                              "fuzzy_score": 97.0}])
    assert [q["classification"] for q in fuzzy_quotes(clean, text)] == ["trivial-ocr"]
    assert all(q["auto_accepted"] for q in fuzzy_quotes(clean, text))
    dirty = _rec(11, extraction_status="partial", nulled_fields=["characterization"],
                 quotes=clean["quotes"])
    assert not any(q["auto_accepted"] for q in fuzzy_quotes(dirty, text))
    # a quote the gate matched exactly is not a fuzzy quote at all
    assert fuzzy_quotes(_rec(12), text) == ()


def test_an_auto_accepted_quote_keeps_the_record_out_of_section_F_and_into_the_audit_trail():
    text = ("the lodger has not the possession, but the use only, of the apartment " * 4)
    quote = [{"text": "the lodger has not the possession, but the use only",
              "supports": ["polarity"], "status": "verified-fuzzy", "fuzzy_score": 97.0}]
    clean, dirty = _rec(30, quotes=quote), _rec(31, quotes=[
        {"text": "the lodger keeps possession of the whole apartment",
         "supports": ["polarity"], "status": "verified-fuzzy", "fuzzy_score": 93.0}])
    q = select_queue(_View([clean, dirty], "r"), "r", manifest=_manifest([30, 31]),
                     cases=_Cases(text))
    assert [c.case_id for c in q.cards] == [31]          # 30's quote never reaches a human
    assert [f["case_id"] for f in q.auto_accepted] == [30]
    assert q.to_json()["fuzzy_auto_accepted"][0]["classification"] == "trivial-ocr"


def test_the_queue_is_priority_ordered_capped_and_carries_the_rest_forward():
    recs = ([_rec(100 + i, polarity="favorable", under_thirty_days="yes") for i in range(4)]
            + [_rec(200 + i, who_was_letting="householder", duration_of_occupancy="nights")
               for i in range(4)]
            + [_rec(300 + i, polarity="mixed") for i in range(4)])
    q = select_queue(_View(recs, "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([r["case_id"] for r in recs]), cases=_Cases(), cap=6)
    assert isinstance(q, Queue) and len(q.cards) == 6
    assert [c.section for c in q.cards] == ["A", "A", "A", "A", "B", "B"]
    assert q.deferred == (202, 203, 300, 301, 302, 303)
    assert all(isinstance(c, QueueCard) for c in q.cards)
    doc = q.to_json()
    assert doc["run_id"] == "cycle-004-shard-01" and doc["cap"] == 6
    assert set(doc["sections"]) == {s for s, _k, _t in SECTIONS}
    assert [c["case_id"] for c in doc["sections"]["A"]] == [100, 101, 102, 103]
    assert doc["sections"]["D"] == []
    assert len(doc["deferred"]) == 6


def test_a_record_the_user_has_already_adjudicated_is_not_queued_again():
    """The round exists to move machine-only records to human-reviewed; a card spent on a
    decision the user has already made is a card not spent on one they have not."""
    recs = [_rec(50, polarity="mixed"), _rec(51, polarity="mixed")]
    q = select_queue(_View(recs, "r", reviewed=[50]), "r", manifest=_manifest([50, 51]),
                     cases=_Cases())
    assert [c.case_id for c in q.cards] == [51]


def test_the_queue_is_the_run_that_admitted_the_record_not_the_whole_ledger():
    from corpus_engine.ledger.types import Basis, Patch
    recs = [_rec(60, polarity="mixed"), _rec(61, polarity="mixed")]
    view = _View(recs, "run-a")
    view.patches = [Patch(60, "admit", "", {}, "w", Basis(model="m", prompt_version="p",
                                                          run_id="run-a")),
                    Patch(61, "admit", "", {}, "w", Basis(model="m", prompt_version="p",
                                                          run_id="run-b"))]
    q = select_queue(view, "run-a", manifest=_manifest([60, 61]), cases=_Cases())
    assert [c.case_id for c in q.cards] == [60]


def test_a_records_other_reasons_are_carried_onto_its_card():
    rec = _rec(400, polarity="favorable", under_thirty_days="yes",
               who_was_letting="householder", duration_of_occupancy="nights")
    q = select_queue(_View([rec], "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([400]), cases=_Cases())
    card = q.cards[0]
    assert card.section == "A" and card.reason == "favorable_under_thirty"
    assert card.other_reasons == ("householder_nights",)


def test_the_disagreements_on_a_card_come_from_the_manifest():
    dis = [{"unit_id": "b1", "case_id": 500, "field": "polarity",
            "reader_value": "favorable", "checker_value": "adverse"}]
    q = select_queue(_View([_rec(500)], "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([500], dis), cases=_Cases())
    assert q.cards[0].section == "C"
    assert q.cards[0].disagreements == tuple(dis)


def test_the_card_names_the_one_field_its_decision_applies_to():
    """R4. Sections C and E cannot be guessed from the section letter: C decides whatever the
    checker contradicted, E whatever the gate erased."""
    def field(rec, dis=()):
        card = QueueCard(rec["case_id"], "?", reasons_for(rec, disagreements=dis,
                                                          fuzzy_needs_human=False)[0]
                         if reasons_for(rec, disagreements=dis, fuzzy_needs_human=False)
                         else "fuzzy_quote", (), rec, tuple(dis), ())
        return card.decide_field

    assert field(_rec(1, polarity="favorable", under_thirty_days="yes")) == "polarity"
    assert field(_rec(2, who_was_letting="householder",
                      duration_of_occupancy="nights")) == "who_was_letting"
    assert field(_rec(3), ({"field": "characterization"},)) == "characterization"
    assert field(_rec(4, polarity="mixed")) == "polarity"
    assert field(_rec(5, nulled_fields=["under_thirty_days"])) == "under_thirty_days"
    assert field(_rec(6)) == "quotes"
    card = QueueCard(7, "A", "favorable_under_thirty", (), _rec(7), (), ())
    assert card.to_json()["decide_field"] == "polarity"


def _plan_reader(asked, records_for, units=()):
    class _Reader:
        def read(self, plan):
            asked.extend(u.id for u in plan.units)
            recs = records_for(plan)
            return type("O", (), {"records": recs, "units": list(units),
                                  "stop": type("S", (), {"kind": "done", "detail": ""})()})()
    return _Reader


def test_check_queue_asks_the_checker_once_per_queued_case():
    """D5's 100% pass. Scripted, not codex: this task never invokes a CLI."""
    from corpus_engine.reader.model import Budget, ModelPin

    asked = []
    reader = _plan_reader(asked, lambda plan: [
        {"case_id": int(u.case_ids[0]), "relevant": True, "polarity": "adverse",
         "characterization": "license", "quotes": []} for u in plan.units])
    recs = [_rec(600), _rec(601, polarity="mixed")]
    q = select_queue(_View(recs, "cycle-004-shard-01"), "cycle-004-shard-01",
                     manifest=_manifest([600, 601], [{"unit_id": "b1", "case_id": 600,
                                                      "field": "polarity",
                                                      "reader_value": "adverse",
                                                      "checker_value": "favorable"}]),
                     cases=_Cases())
    got = check_queue(q, reader_factory=lambda: reader(), codebook=None,
                      checker_pin=ModelPin("codex-cli", "openai"), budget=Budget())
    assert sorted(got) == [600, 601]
    assert got[600]["values"]["polarity"] == "adverse" and got[600]["status"] == "ok"
    assert len(asked) == 2                       # one unit per queued record, 100%
    assert asked == ["reread-600", "reread-601"]     # a re-read plan, not a judgment


def test_check_queue_reports_the_four_statuses_it_documents():
    """ok | unparsed | failed:<msg> | missing (R4). A case the budget stopped short of is
    `missing`, not silence: the page has to be able to say the checker was never asked."""
    from corpus_engine.reader.model import Budget, ModelPin

    recs = [_rec(700, polarity="mixed"), _rec(701, polarity="mixed"),
            _rec(702, polarity="mixed"), _rec(703, polarity="mixed")]
    q = select_queue(_View(recs, "r"), "r", manifest=_manifest([700, 701, 702, 703]),
                     cases=_Cases())

    def _result(cid, status):
        return type("R", (), {"case_id": cid,
                              "record": {"case_id": cid, "extraction_status": status}})()

    units = [type("U", (), {"unit_id": "reread-700", "status": "ok", "error": "",
                            "records": [_result(700, "ok")]})(),
             type("U", (), {"unit_id": "reread-701", "status": "parse_failed", "error": "",
                            "records": [_result(701, "missing")]})(),
             type("U", (), {"unit_id": "reread-702", "status": "failed", "error": "codex boom",
                            "records": [_result(702, "missing")]})()]
    reader = _plan_reader([], lambda plan: [u.records[0].record for u in units], units)
    got = check_queue(q, reader_factory=lambda: reader(), codebook=None,
                      checker_pin=ModelPin("codex-cli", "openai"), budget=Budget())
    assert got[700]["status"] == "ok"
    assert got[701]["status"] == "unparsed"
    assert got[702]["status"].startswith("failed:") and "codex boom" in got[702]["status"]
    assert got[703] == {"values": {}, "status": "missing"}


def test_an_empty_queue_asks_the_checker_nothing():
    from corpus_engine.reader.model import Budget, ModelPin

    asked = []
    reader = _plan_reader(asked, lambda plan: [])
    empty = Queue("r", (), (), 150)
    assert check_queue(empty, reader_factory=lambda: reader(), codebook=None,
                       checker_pin=ModelPin("codex-cli", "openai"), budget=Budget()) == {}
    assert asked == []


def test_the_checker_path_the_manifest_records_names_the_plan_and_the_pin():
    """R10: a round whose second opinion came from some other plan or pin is not this round,
    and the manifest has to be able to say which one it was."""
    from corpus_engine.reader.model import ModelPin

    path = checker_path(ModelPin("codex-cli", "openai", "codex-cli"), unit_cap=42)
    assert path["plan"] == "reread" and path["worker"] == "checker"
    assert path["pin"] == "codex-cli@codex-cli:-"
    assert path["cases_per_unit"] == 1 and path["unit_cap"] == 42 and path["sample_pct"] == 100


def test_the_case_text_is_fetched_once_and_only_for_records_with_a_fuzzy_quote():
    fuzzy = [{"text": "q", "supports": ["polarity"], "status": "verified-fuzzy"}]
    recs = [_rec(800), _rec(801, quotes=fuzzy), _rec(802, quotes=fuzzy)]
    cases = _Cases("q text")
    select_queue(_View(recs, "r"), "r", manifest=_manifest([800, 801, 802]), cases=cases)
    assert cases.asked == [[801, 802]]


@pytest.mark.parametrize("cap", [0, 1, 3])
def test_nothing_is_dropped_at_any_cap(cap):
    recs = [_rec(900 + i, polarity="mixed") for i in range(3)]
    q = select_queue(_View(recs, "r"), "r", manifest=_manifest([900, 901, 902]),
                     cases=_Cases(), cap=cap)
    assert len(q.cards) == cap
    assert [c.case_id for c in q.cards] + list(q.deferred) == [900, 901, 902]
