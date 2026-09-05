"""D3: the who-was-letting reference for the kit cases nobody ever reviewed on that field is
the value at least 4 of the 5 finalists returned under mapper-v2; the rest go to the user on a
second page. The counting rule, who is *excluded* from that rule, and the shape of that second
page are what this file pins - the cached reads it counts over are provenance, not a fixture.
"""
import importlib.util
import json
from pathlib import Path

from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cr = _load("consensus_reference")
mrr = _load("make_reference_review")

C = list(cr.CANDIDATES)


def test_four_of_five_agree_is_consensus_and_three_is_not():
    four = dict(zip(C, ["householder", "householder", "householder", "householder", "commercial_operator"]))
    assert cr.consensus(four) == ("householder", 4, 5)
    three = dict(zip(C, ["householder", "householder", "householder", "unclear", "commercial_operator"]))
    assert cr.consensus(three) == (None, 3, 5)
    unanimous = dict(zip(C, ["unclear"] * 5))
    assert cr.consensus(unanimous) == ("unclear", 5, 5)


def test_nulls_do_not_count_toward_the_four():
    values = dict(zip(C, ["householder", "householder", "householder", "householder", None]))
    assert cr.consensus(values) == ("householder", 4, 4)
    thin = dict(zip(C, ["householder", "householder", None, None, None]))
    assert cr.consensus(thin) == (None, 2, 2)
    assert cr.consensus(dict(zip(C, [None] * 5))) == (None, 0, 0)


def test_the_agreed_value_must_be_in_the_readers_vocabulary():
    """The consensus copies a value into the reference; it never invents one. A value the
    reader's schema does not carry is not a reference label, however many candidates
    returned it."""
    assert set(cr.CONSENSUS_VOCABULARY) == set(cr.WHO_VALUES)
    assert "non_resident_owner" in cr.CONSENSUS_VOCABULARY          # canonical spelling
    off = dict(zip(C, ["nonresident owner"] * 5))
    assert cr.consensus(off) == (None, 5, 5)


def test_consensus_patches_carry_a_machine_basis_that_can_judge():
    ps = cr.patches_for({77: ("householder", 4, 5)}, {77: {"who_was_letting": None}})
    assert [(p.field, p.new) for p in ps if p.op == "set"] == [("who_was_letting", "householder")]
    p = ps[0]
    assert p.basis.kind() == "reader" and p.basis.can_judge()
    assert p.basis.model == "model-consensus:mapper-v2:4of5" and p.basis.prompt_version == "mapper-v2"
    assert p.basis.run_id == "reference-v2-consensus"
    assert all(p.basis.reviewer is None for p in ps)              # never a human basis
    assert all(p.case_id == 77 for p in ps)


def test_a_reviewers_adjudication_and_a_reviewers_irrelevance_both_beat_the_consensus(tmp_path):
    """R8 and Task-5 finding 4. The user's Task-5 page already decided some of these cases -
    directly (a reviewer-basis who_was_letting patch) or by being asked about them at all
    (the reference-v1 contested queue). And a case the user ruled out of the corpus carries
    no labels: it gets no consensus value and is not put back in front of them."""
    led = open_ledger(tmp_path, domain=load_domain())
    reader = Basis(model="m", prompt_version="mapper-v2", run_id="r1")

    def rec(cid, relevant=True):
        return {"case_id": cid, "cite": f"{cid} X", "year": 1900, "relevant": relevant,
                "polarity": "favorable", "who_was_letting": "householder",
                "quotes": [], "extraction_status": "ok"}

    led.apply([Patch(c, "admit", "", rec(c), "seed", reader, cycle="cycle-001") for c in (1, 2, 3, 4, 5)],
              note="seed")
    led.apply([Patch(1, "set", "who_was_letting", "commercial_operator", "adjudicated", Basis(reviewer="u")),
               Patch(3, "set", "relevant", False, "out of scope", Basis(reviewer="u"))], note="task 5")
    v1 = {"contested": [{"case_id": 2, "contested_fields": ["who_was_letting"]},
                        {"case_id": 4, "contested_fields": ["polarity"]}]}

    assert cr.adjudicated_who(v1) == {2}
    eligible, reviewed, irrelevant = cr.partition([1, 2, 3, 4, 5], led.view(), cr.adjudicated_who(v1))
    assert reviewed == [1, 2] and irrelevant == [3] and eligible == [4, 5]
    assert not (set(reviewed) | set(irrelevant)) & set(eligible)   # the three are disjoint

    # a machine consensus over the eligible cases only still applies cleanly on top of Task 5
    agreed = {cid: ("commercial_operator", 5, 5) for cid in eligible}
    res = led.apply(cr.patches_for(agreed, led.view().state.records), note="v2", dry_run=True)
    assert {p.case_id for p in res.applied} == {4, 5}
    assert led.view().record(1)["who_was_letting"] == "commercial_operator"   # reviewer's, untouched
    assert led.view().record(3)["relevant"] is False


def test_the_split_document_builds_a_second_review_page(tmp_path):
    class T:
        def __init__(self, cid):
            self.case_id, self.name, self.cite = cid, f"Case {cid}", f"{cid} N.Y. 1"
            self.court, self.jurisdiction, self.year = "N.Y. Ct. App.", "N.Y.", 1899
    splits = {5: (None, 3, 5), 6: (None, 2, 4)}
    per_candidate = {5: dict(zip(C, ["householder", "householder", "householder", "unclear", "commercial_operator"])),
                     6: dict(zip(C, ["unclear", "unclear", "commercial_operator", "commercial_operator", None]))}
    doc = cr.contested_doc(splits, {5: T(5), 6: T(6)},
                           {5: {"who_was_letting": None, "relevant": True, "polarity": "favorable"},
                            6: {"who_was_letting": None, "relevant": True, "polarity": "adverse"}},
                           per_candidate, holdings={5: {C[0]: "a lodger sued the householder"}})
    assert [c["case_id"] for c in doc["contested"]] == [5, 6]
    assert all(c["contested_fields"] == ["who_was_letting"] for c in doc["contested"])
    assert doc["counts"]["splits"] == 2
    data = mrr.build_items(doc)                                   # the page builder accepts it
    assert data["A"] == [] and [i["case_id"] for i in data["B"]] == [5, 6]
    assert [c["label"] for c in data["B"][0]["cands"]] == [lab for _full, lab in mrr.CANDIDATES]
    assert data["B"][0]["maj"] == "householder" and data["B"][0]["maj_n"] == 3
    assert data["B"][0]["ev_maj"] == [{"cand": "opus-5", "quote": "",
                                       "holding": "a lodger sued the householder"}]
    out = tmp_path / "contested-who.json"
    out.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    html, md, _n = mrr.build_pages(out, tmp_path / "review-queue-reference-v2")
    text = html.read_text(encoding="utf-8")
    assert "(2 cases)" in text                                    # the rendered who-was-letting count
    assert "<title>Reference adjudication v2" in text             # the page names its own queue
    assert 'id="cards-B"' in text and md.exists()
    assert "Case 5" in text and "Case 6" in text


def test_records_from_cache_is_the_basis_of_the_accepted_counts():
    """The consensus reads the same cached records the accepted counts are derived from, so
    the two can never disagree about what a candidate said."""
    mr = _load("measure_reader")
    assert callable(mr.records_from_cache)
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "records_from_cache(" in src.split("def accepted_from_cache", 1)[1]
    assert "ResponseCache.key_v1" in src                          # the v1 cache, addressed the v1 way
