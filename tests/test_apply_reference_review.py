"""The saved review page IS the record (same mechanism as pipeline/make_review.py), so this
tool has one job: turn the decision state embedded in that page into ledger patches with the
user as basis, and refuse anything it cannot read. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTESTED = ROOT / "tests" / "fixtures" / "reference-contested-tiny.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arr = _load("apply_reference_review")
mrr = _load("make_reference_review")


def saved_page(tmp_path, decisions) -> str:
    """A page in exactly the state the artifact capability republishes it in: the empty
    state array replaced by the decisions, everything else byte-identical."""
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    html = html_path.read_text(encoding="utf-8")
    payload = json.dumps(decisions).replace("<", "\\u003c")
    return html.replace('id="review-state">[]<', f'id="review-state">{payload}<')


def _d(case_id, field, decision, value=None, note=""):
    return {"case_id": case_id, "field": field, "decision": decision, "value": value, "note": note}


def test_read_state_returns_the_decisions_a_saved_page_carries(tmp_path):
    decisions = [_d(65116, "polarity", "adopt", "favorable"), _d(65116, "who_was_letting", "keep", "unclear")]
    got = arr.read_state(saved_page(tmp_path, decisions))
    assert [(d["case_id"], d["field"], d["decision"], d["value"]) for d in got] == [
        (65116, "polarity", "adopt", "favorable"), (65116, "who_was_letting", "keep", "unclear")]


def test_read_state_refuses_an_unsaved_page_and_a_bad_decision(tmp_path):
    html_path, _md, _n = mrr.build_pages(CONTESTED, tmp_path / "page")
    with pytest.raises(ValueError, match="no decisions"):
        arr.read_state(html_path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no review-state"):
        arr.read_state("<html>nothing here</html>")
    with pytest.raises(ValueError, match="decision"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "maybe", "favorable")]))
    with pytest.raises(ValueError, match="value"):
        arr.read_state(saved_page(tmp_path, [_d(1, "polarity", "set", "pro-tenant")]))
    with pytest.raises(ValueError, match="field"):
        arr.read_state(saved_page(tmp_path, [_d(1, "duration_of_occupancy", "keep", "weeks")]))
    bad = _d(1, "polarity", "keep", "favorable")
    bad.pop("case_id")
    with pytest.raises(ValueError, match="case_id"):     # not a KeyError: every malformed
        arr.read_state(saved_page(tmp_path, [bad]))      # decision fails the same way


def test_a_field_with_no_closed_vocabulary_opts_out_of_the_value_check_and_only_it(tmp_path):
    """tools/apply_map_review.py decides fields this tool has no frozenset for (`quotes`, and
    whatever a later codebook adds), so `values[field] is None` means "no vocabulary here".
    The opt-out is per field and explicit: the reference page passes neither, and its own two
    fields are validated exactly as before."""
    page = saved_page(tmp_path, [_d(65116, "polarity", "set", "whatever-the-codebook-says")])
    got = arr.read_state(page, fields=("polarity",), values={"polarity": None})
    assert got[0]["value"] == "whatever-the-codebook-says"
    with pytest.raises(ValueError, match="value"):        # the same page, default vocabulary
        arr.read_state(page)
    with pytest.raises(ValueError, match="value"):        # ...and an opt-out for another field
        arr.read_state(page, fields=("polarity", "who_was_letting"),
                       values={"polarity": arr.VALUES["polarity"], "who_was_letting": None})


def test_a_note_containing_a_closing_script_tag_survives_the_page(tmp_path):
    """The state block is read out of the HTML with a regex, so an unescaped `</script>` in a
    reviewer note would end it early and truncate the decisions. The page escapes `<`."""
    note = "the court cites </script> in the syllabus"
    got = arr.read_state(saved_page(tmp_path, [_d(65116, "polarity", "adopt", "favorable", note=note)]))
    assert len(got) == 1 and got[0]["note"] == note


def test_the_vocabulary_comes_from_the_reader_schema_and_the_fields_from_the_domain():
    """A frozen literal here is what let `non_resident_owner` diverge from the domain
    unnoticed; a page that splits a category must work once the schema carries the value."""
    from corpus_engine.domain import load_domain
    from corpus_engine.reader.schema import POLARITY_VALUES, WHO_VALUES
    assert arr.VALUES["polarity"] == frozenset(POLARITY_VALUES) | {arr.IRRELEVANT, None}
    assert arr.VALUES["who_was_letting"] == frozenset(WHO_VALUES) | {None}
    assert arr.fields_for(load_domain("str-right-to-let")) == ("polarity", "who_was_letting")


def test_the_run_id_rides_in_the_basis_and_the_why():
    """patch_id hashes `why` and `basis`, so a second page run under its own id can never be
    content-deduped against this one's patches."""
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    dec = [_d(1, "polarity", "adopt", "adverse")]
    v2 = arr.patches_for(dec, records, "u")
    v3 = arr.patches_for(dec, records, "u", run_id="reference-v3")
    assert all(p.basis.run_id == "reference-v2" and p.why.startswith("reference v2") for p in v2)
    assert all(p.basis.run_id == "reference-v3" and p.why.startswith("reference v3") for p in v3)
    assert {p.why for p in v2}.isdisjoint({p.why for p in v3})


def test_patches_for_covers_the_four_decisions():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True},
               2: {"polarity": "mixed", "who_was_letting": "unclear", "relevant": True},
               3: {"polarity": "adverse", "who_was_letting": "householder", "relevant": True},
               4: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "polarity", "keep", "favorable"),
                 _d(2, "polarity", "adopt", "adverse", note="clearly a tenant-protection holding"),
                 _d(3, "who_was_letting", "set", "non_resident_owner"),
                 _d(4, "polarity", "unsure")]
    ps = arr.patches_for(decisions, records, "mmaldo2")
    by_case = {}
    for p in ps:
        by_case.setdefault(p.case_id, []).append((p.op, p.field, p.new))
    assert 1 not in by_case                                        # keep -> no patch at all
    assert ("set", "polarity", "adverse") in by_case[2]
    assert ("append", "review.notes", "user note: clearly a tenant-protection holding") in by_case[2]
    assert ("set", "review.status", "human-adjudicated") in by_case[2]
    assert ("set", "who_was_letting", "non_resident_owner") in by_case[3]
    assert ("append", "review.flags", "needs-review:polarity") in by_case[4]
    assert not any(op == "set" and f == "polarity" for op, f, _v in by_case[4])
    assert all(p.basis.reviewer == "mmaldo2" and p.basis.run_id == "reference-v2" for p in ps)
    assert all(p.basis.kind() == "human" for p in ps)


def test_adopting_irrelevant_on_polarity_clears_the_whole_record():
    records = {9: {"polarity": "mixed", "who_was_letting": "commercial_operator", "relevant": True}}
    ps = arr.patches_for([_d(9, "polarity", "adopt", "irrelevant")], records, "mmaldo2")
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert ("relevant", False) in sets and ("polarity", None) in sets and ("who_was_letting", None) in sets
    assert ("review.status", "human-adjudicated") in sets


def test_irrelevant_wins_over_a_value_decision_on_the_same_case():
    """A case the reviewer put out of the corpus carries no who_was_letting, even where the
    same page also carries a who_was_letting value for it (5 of the 71 real cases do). Without
    this the later field would re-set what `irrelevant` just nulled."""
    records = {9: {"polarity": "mixed", "who_was_letting": "unclear", "relevant": True}}
    ps = arr.patches_for([_d(9, "polarity", "adopt", "irrelevant"),
                          _d(9, "who_was_letting", "adopt", "non_resident_owner")], records, "u")
    sets = [(p.field, p.new) for p in ps if p.op == "set"]
    assert ("who_was_letting", None) in sets
    assert ("who_was_letting", "non_resident_owner") not in sets
    assert any(p.op == "append" and p.field == "review.notes" and "irrelevant" in p.new for p in ps)


def test_a_decided_field_clears_the_stale_flag_standing_on_it():
    """A reviewer value supersedes an older `needs-review:<field>` flag - one an earlier page
    left, or one the retraction cascade wrote when the supporting quote was dropped. Without
    this the case stays out of agreement for a field the user has actually adjudicated. Only
    the flag for the decided field goes: the one naming a field this page did not decide,
    and the flags of any other kind, stay."""
    records = {1: {"polarity": None, "who_was_letting": "unclear", "relevant": True,
                   "review": {"status": "machine", "flags": ["needs-review:polarity",
                                                             "needs-review:characterization",
                                                             "abrogation-risk: see citator"],
                              "notes": []}}}
    ps = arr.patches_for([_d(1, "polarity", "adopt", "adverse")], records, "u")
    cleared = [p.new for p in ps if p.op == "set" and p.field == "review.flags"]
    assert cleared == [["needs-review:characterization", "abrogation-risk: see citator"]]
    assert any(p.op == "append" and p.field == "review.notes" and "flag cleared" in p.new for p in ps)
    assert ("polarity", "adverse") in [(p.field, p.new) for p in ps if p.op == "set"]


def test_a_flagless_case_and_an_unsure_decision_write_no_clearing_patch():
    """The clearing patch exists only where there is something to clear, so re-running a page
    over a clean ledger is a no-op; and `unsure` still ADDS the flag rather than removing it."""
    records = {1: {"polarity": "mixed", "relevant": True, "review": {"flags": [], "notes": []}},
               2: {"polarity": "mixed", "relevant": True}}                      # no review block
    ps = arr.patches_for([_d(1, "polarity", "set", "adverse"), _d(2, "polarity", "unsure")],
                         records, "u")
    assert not [p for p in ps if p.op == "set" and p.field == "review.flags"]
    assert ("append", "review.flags", "needs-review:polarity") in [(p.op, p.field, p.new) for p in ps]


def test_deciding_two_flagged_fields_on_one_case_clears_both():
    """`review.flags` is set as a whole list, so the second clearing patch has to build on the
    first rather than on the record - otherwise it reinstates the flag the first just removed."""
    records = {1: {"polarity": None, "who_was_letting": None, "relevant": True,
                   "review": {"flags": ["needs-review:polarity", "needs-review:who_was_letting"],
                              "notes": []}}}
    ps = arr.patches_for([_d(1, "polarity", "adopt", "adverse"),
                          _d(1, "who_was_letting", "adopt", "householder")], records, "u")
    cleared = [p.new for p in ps if p.op == "set" and p.field == "review.flags"]
    assert cleared == [["needs-review:who_was_letting"], []]


def test_patch_order_follows_the_field_order_flag():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    decisions = [_d(1, "who_was_letting", "set", "householder"), _d(1, "polarity", "set", "adverse")]
    fields = [p.field for p in arr.patches_for(decisions, records, "u") if p.op == "set"]
    assert fields.index("polarity") < fields.index("who_was_letting")
    fields2 = [p.field for p in arr.patches_for(decisions, records, "u",
                                                field_order=("who_was_letting", "polarity")) if p.op == "set"]
    assert fields2.index("who_was_letting") < fields2.index("polarity")


def test_null_spellings_become_none():
    records = {1: {"polarity": "favorable", "who_was_letting": "unclear", "relevant": True}}
    ps = arr.patches_for([_d(1, "polarity", "set", "null")], records, "u")
    assert ("polarity", None) in [(p.field, p.new) for p in ps if p.op == "set"]


def test_run_id_already_applied_reads_the_view_not_the_records():
    from corpus_engine.ledger.types import Basis, Patch
    p = Patch(1, "set", "polarity", "adverse", "why", Basis(reviewer="u", run_id="reference-v2"))

    class FakeView:
        patches = [p]
    assert arr.run_id_already_applied(FakeView(), "reference-v2") is True
    assert arr.run_id_already_applied(FakeView(), "reference-v3") is False


def test_main_refuses_to_reapply_an_existing_run_id_unless_forced(tmp_path, monkeypatch):
    """task-7-review finding 1. Re-running an applied page's run id re-emits a fresh
    review.notes patch for every decision it already made (each note interpolates the
    field's current value), so main() must refuse it by default."""
    from corpus_engine.domain import load_domain
    from corpus_engine.ledger import open_ledger as real_open_ledger
    from corpus_engine.ledger.types import Basis, Patch

    dom = load_domain()
    led = real_open_ledger(tmp_path, domain=dom)
    rec = {"case_id": 65116, "cite": "65116 X", "year": 1900, "relevant": True, "polarity": "favorable",
           "who_was_letting": "unclear", "quotes": [{"text": "q", "supports": "polarity"}]}
    admit = Patch(65116, "admit", "", rec, "seed", Basis(model="m", prompt_version="v", run_id="seed"),
                 cycle="cycle-001")
    seeded = Patch(65116, "set", "polarity", "favorable", "seed", Basis(reviewer="u", run_id="reference-v2"))
    led.apply([admit, seeded], note="seed")

    monkeypatch.setattr(arr, "open_ledger",
                        lambda *a, **kw: real_open_ledger(tmp_path, domain=kw.get("domain") or dom))
    saved = tmp_path / "saved.html"
    saved.write_text(saved_page(tmp_path, [_d(65116, "polarity", "adopt", "adverse")]), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["apply_reference_review.py", "--saved", str(saved), "--dry-run"])
    with pytest.raises(SystemExit, match="reference-v2"):
        arr.main()

    monkeypatch.setattr(sys, "argv",
                        ["apply_reference_review.py", "--saved", str(saved), "--dry-run", "--force"])
    assert arr.main() == 0


def test_the_users_saved_page_is_readable_and_maps_onto_the_ledger():
    """The real input, guarded so a later edit to either the page or the reader is caught."""
    saved = ROOT / "data" / "reader" / "review" / "reference-v1" / "saved-2026-09-05.html"
    if not saved.exists():
        pytest.skip("the user's saved page is not on disk")
    decisions = arr.read_state(saved.read_text(encoding="utf-8"))
    assert len(decisions) == 82
    tally = {}
    for d in decisions:
        tally[(d["field"], d["decision"])] = tally.get((d["field"], d["decision"]), 0) + 1
    assert tally == {("polarity", "adopt"): 37, ("polarity", "keep"): 4,
                     ("who_was_letting", "adopt"): 36, ("who_was_letting", "keep"): 2,
                     ("who_was_letting", "set"): 1, ("who_was_letting", "unsure"): 2}
