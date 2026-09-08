"""The map review round's two tools (spec section 9): the page the user decides in, and the
path from the page they saved back to the ledger.

The page is the record - there is no separate decision file - so the guards here are the two
that make that true: the save markers must be replaced by real values (an unreplaced marker
is a page that silently loses every decision), and the state block the page writes must be
exactly what `apply_reference_review.read_state` parses. Imported by path because tools/ is
scripts, not a package."""
import importlib.util
import json
from pathlib import Path

import pytest

from corpus_engine.domain import load_domain
from corpus_engine.mapper.queue import SECTIONS, select_queue

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mk = _load("make_map_review")
ap = _load("apply_map_review")
arr = _load("apply_reference_review")
ec = _load("export_review_cards")


def _rec(cid, **over):
    r = {"case_id": cid, "relevant": True, "polarity": "adverse", "who_was_letting": "unclear",
         "duration_of_occupancy": "months", "characterization": "lease",
         "under_thirty_days": "no", "owner_freedom_characterization": "regulable_privilege",
         "restriction_nature": "zoning", "holding_summary": "the lodger has the use only",
         "cite": f"{cid} N.Y. 1", "name": "A v. B", "court": "Ct. App.",
         "jurisdiction": "N.Y.", "year": 1890,
         "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified"}],
         "nulled_fields": [], "extraction_status": "ok",
         "review": {"status": "machine", "flags": [], "notes": []}}
    r.update(over)
    return r


class _View:
    def __init__(self, records):
        self.state = type("S", (), {"order": [r["case_id"] for r in records],
                                    "records": {r["case_id"]: r for r in records}})()
        self.patches = []

    def reviewed(self, cid):
        return False


class _Cases:
    def fetch(self, ids):
        from corpus_engine.reader.model import CaseText
        return [CaseText(int(c), "", "", "", "", 1890, "text", "text", []) for c in ids]


def _manifest(disagreements=()):
    return {"run_id": "cycle-004-shard-01",
            "cells": {"1860-1900|N.Y.": {"checker_disagreements": list(disagreements),
                                         "checker_status": {}}}}


def _queue_doc(records=None, disagreements=()):
    records = records or [_rec(700, polarity="favorable", under_thirty_days="yes"),
                          _rec(701, who_was_letting="householder",
                               duration_of_occupancy="nights"),
                          _rec(702, polarity="mixed"),
                          _rec(703, nulled_fields=["characterization"])]
    return select_queue(_View(records), "cycle-004-shard-01",
                        manifest=_manifest(disagreements), cases=_Cases()).to_json()


CHECKER = {700: {"values": {"polarity": "adverse"}, "status": "ok"}}


def _page_data(html: str) -> dict:
    """The DOC literal the page carries, which is what every card is rendered from."""
    return json.loads(html.split("const DOC = ")[1].split(";\nconst DATA")[0])


# --------------------------------------------------------------------------- the page

def test_the_page_renders_six_sections_and_a_decision_schema(tmp_path):
    doc = _queue_doc()
    html_path, md_path, tb64_len = mk.build_pages(doc, tmp_path / "page", checker=CHECKER)
    html = html_path.read_bytes().decode("utf-8")
    assert html.endswith("\n") and "\r" not in html
    for _s, _k, title in SECTIONS:
        assert title in html, title
    assert '<script type="application/json" id="review-state">' in html
    assert "__TEMPLATE_B64__" not in html and tb64_len > 0
    assert "Adopt checker value" in html and "Unsure" in html and "Keep reader value" in html
    assert "courtlistener.com" in html
    md = md_path.read_bytes().decode("utf-8")
    assert md.endswith("\n") and "cycle-004-shard-01" in md


def test_the_save_markers_are_replaced_so_the_page_can_republish_itself(tmp_path):
    html_path, _md, _n = mk.build_pages(_queue_doc(), tmp_path / "page", checker=CHECKER)
    html = html_path.read_text(encoding="utf-8")
    # the literals may only survive inside JS string concatenation (the page rebuilds them
    # at save time); the *marker* forms must be gone.
    assert '"__REVIEW_STATE__"' not in html
    assert '"__TEMPLATE_B64__"' not in html
    assert 'id="review-state">[]<' in html
    assert 'const TB64 = "' in html and len(html.split('const TB64 = "')[1]) > 1000
    assert "claude.use('artifact')" in html and "art.publish(" in html


def test_the_file_is_content_only_and_committable(tmp_path):
    html_path, _md, _n = mk.build_pages(_queue_doc(), tmp_path / "page", checker=CHECKER)
    raw = html_path.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    low = raw.decode("utf-8").lower()
    for tag in ("<!doctype", "<html", "<head", "<body"):
        assert tag not in low, tag          # the Artifact tool supplies the skeleton


def test_every_queued_case_reaches_the_page_with_the_field_its_card_decides(tmp_path):
    doc = _queue_doc()
    html_path, md_path, _n = mk.build_pages(doc, tmp_path / "page", checker=CHECKER)
    data = _page_data(html_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    on_page = {c["case_id"]: c["decide_field"]
               for cards in data["sections"].values() for c in cards}
    assert on_page == {700: "polarity", 701: "who_was_letting", 702: "polarity",
                       703: "characterization"}
    for cid in on_page:
        assert f"[{cid}]" in md, cid
    assert data["checker"]["700"]["values"]["polarity"] == "adverse"


def test_a_card_with_no_checker_value_offers_no_adopt(tmp_path):
    """Adopt means "the checker's answer". A card the checker never answered for has none,
    and an adopt radio there would write null over the reader's value."""
    html_path, _md, _n = mk.build_pages(_queue_doc(), tmp_path / "page", checker={})
    html = html_path.read_text(encoding="utf-8")
    assert "Adopt checker value" in html          # the branch exists in the template
    assert _page_data(html)["checker"] == {}      # ...and no card has a value to adopt


def test_an_empty_round_still_renders(tmp_path):
    doc = _queue_doc(records=[_rec(900, relevant=False, polarity=None)])
    html_path, md_path, _n = mk.build_pages(doc, tmp_path / "page", checker={})
    md = md_path.read_text(encoding="utf-8")
    assert "0 cards this round" in md
    assert _page_data(html_path.read_text(encoding="utf-8"))["sections"]["A"] == []


# ------------------------------------------------------------------- the checker pass

def test_check_mode_runs_the_checker_over_the_queue_and_records_the_path(tmp_path):
    """R7/R10. Scripted, never codex: `--check` is a live step and this test is not it."""
    from corpus_engine.reader.model import Budget, ModelPin

    asked = []

    class _Reader:
        def read(self, plan):
            asked.extend(u.id for u in plan.units)
            return type("O", (), {"units": [], "stop": None, "records": [
                {"case_id": int(u.case_ids[0]), "relevant": True, "polarity": "mixed",
                 "characterization": "lodging"} for u in plan.units]})()

    doc = _queue_doc()
    manifest_path = tmp_path / "review-round-1.json"
    out_path = tmp_path / "review-round-1-checker.json"
    results = mk.run_check(doc, out_path, reader_factory=_Reader, codebook=None,
                           checker_pin=ModelPin("codex-cli", "openai", "codex-cli"),
                           budget=Budget(max_units=4), manifest_path=manifest_path)
    assert sorted(results) == [700, 701, 702, 703]          # 100%, not a sample
    assert sorted(asked) == ["reread-700", "reread-701", "reread-702", "reread-703"]
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["700"]["values"]["polarity"] == "mixed" and written["700"]["status"] == "ok"
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["checker_path"] == {"plan": "reread", "worker": "checker",
                                     "pin": "codex-cli@codex-cli:-", "cases_per_unit": 1,
                                     "unit_cap": 4, "sample_pct": 100}
    assert saved["checker_results"] == out_path.as_posix()


def test_check_mode_loads_the_domains_own_codebook_not_a_hardcoded_version(tmp_path, monkeypatch):
    """task-8-review finding 1: `main()`'s `--check` branch hardcoded
    `load_codebook(domain, "mapper-v3")` instead of reading `domain.reader.codebook`, unlike
    `tools/map_reader.py`'s `load_codebook(dom, dom.reader.codebook)` - a latent drift risk
    if the codebook id ever changes. It must load whatever `domain.reader.codebook` names."""
    import corpus_engine.reader.codebook as codebook_mod
    from corpus_engine.domain import load_domain
    from corpus_engine.reader.model import ModelPin

    domain = load_domain()
    seen = []
    real_load_codebook = codebook_mod.load_codebook

    def _spy(dom, version):
        seen.append(version)
        return real_load_codebook(dom, version)

    monkeypatch.setattr(codebook_mod, "load_codebook", _spy)
    monkeypatch.setattr(mk, "default_checker",
                        lambda dom: ((lambda: None), ModelPin("codex-cli", "openai", "codex-cli"),
                                    "stub"))
    monkeypatch.setattr(mk, "run_check", lambda *a, **kw: {})

    doc = _queue_doc()
    queue_path = tmp_path / "review-round-1.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")

    assert mk.main(["--check", "--queue", str(queue_path)]) == 0
    # The point is not that this differs from "mapper-v3" today (it doesn't) - it is that the
    # call reads it from the domain rather than a hardcoded literal.
    assert seen == [domain.reader.codebook]


def test_the_queue_manifest_reads_back_as_the_round_that_was_written():
    doc = _queue_doc(disagreements=[{"unit_id": "b1", "case_id": 702, "field": "polarity",
                                     "reader_value": "mixed", "checker_value": "adverse"}])
    q = mk.cards_from_doc(doc)
    assert [c.case_id for c in q.cards] == [700, 701, 702, 703]
    assert [c.section for c in q.cards] == ["A", "B", "C", "E"]
    assert all(c.record["jurisdiction"] == "N.Y." for c in q.cards)
    assert q.cards[2].decide_field == "polarity"
    assert q.cards[3].decide_field == "characterization"


# --------------------------------------------------------- the page back to the ledger

def _saved_page(tmp_path, decisions, *, doc=None):
    """A page in exactly the state the artifact capability republishes it in: the empty
    state array replaced by the decisions, everything else byte-identical."""
    html_path, _md, _n = mk.build_pages(doc or _queue_doc(), tmp_path / "page", checker=CHECKER)
    html = html_path.read_text(encoding="utf-8")
    payload = json.dumps(decisions).replace("<", "\\u003c")
    saved = html.replace('id="review-state">[]<', f'id="review-state">{payload}<')
    path = tmp_path / "saved.html"
    path.write_text(saved, encoding="utf-8")
    return path


def _d(case_id, field, decision, value=None, note=""):
    return {"case_id": case_id, "field": field, "decision": decision, "value": value,
            "note": note}


def test_the_saved_page_parses_back_through_the_reference_tools_state_reader(tmp_path):
    """One state reader for both pages. Section F decides `quotes`, which has no closed
    vocabulary - the reader has to accept the field without inventing values for it."""
    fields = ("polarity", "who_was_letting", "characterization", "quotes")
    page = _saved_page(tmp_path, [_d(700, "polarity", "adopt", "adverse"),
                                  _d(701, "who_was_letting", "keep", "unclear"),
                                  _d(702, "polarity", "set", "favorable", note="both ways"),
                                  _d(703, "quotes", "unsure")])
    got = ap.read_page(page.read_text(encoding="utf-8"), fields)
    assert [(d["case_id"], d["field"], d["decision"], d["value"]) for d in got] == [
        (700, "polarity", "adopt", "adverse"), (701, "who_was_letting", "keep", "unclear"),
        (702, "polarity", "set", "favorable"), (703, "quotes", "unsure", None)]
    assert got[2]["note"] == "both ways"


def test_a_note_containing_a_closing_script_tag_survives_the_page(tmp_path):
    note = "the court cites </script> in the syllabus"
    page = _saved_page(tmp_path, [_d(700, "polarity", "keep", "favorable", note=note)])
    got = ap.read_page(page.read_text(encoding="utf-8"), ("polarity",))
    assert len(got) == 1 and got[0]["note"] == note


def test_a_tampered_saved_page_is_refused_by_the_vocabulary_check(tmp_path):
    """I1. `read_state` was called with `values={f: None for f in fields}`, which is the
    "this field has no closed vocabulary" opt-out - passed for EVERY field, it turned the
    check off everywhere, and the ledger performs no value validation of its own. A page
    carrying `FAVORABEL` on the field the published favorable count slices on has to be
    refused, by name, before a single patch is built."""
    fields = ("polarity", "who_was_letting", "characterization", "quotes")
    page = _saved_page(tmp_path, [_d(700, "polarity", "keep", "adverse"),
                                  _d(701, "polarity", "set", "FAVORABEL")])
    with pytest.raises(ValueError, match="FAVORABEL"):
        ap.read_page(page.read_text(encoding="utf-8"), fields)


def test_the_vocabulary_is_the_readers_schema_and_only_free_text_opts_out():
    """Read from `corpus_engine.reader.schema`, never re-declared here, so a codebook that
    adds a value works without editing the tool. Only `holding_summary` (free text) and
    `quotes` (kept, or sent for a full read) have no closed vocabulary."""
    from corpus_engine.reader.schema import CHARACTERIZATION_VALUES, POLARITY_VALUES
    dom = load_domain()
    fields = tuple(dom.judged_fields) + ap.EXTRA_FIELDS
    values = ap.values_for(fields)
    assert set(values) == set(fields)
    assert [f for f, v in values.items() if v is None] == ["holding_summary", "quotes"]
    assert values["polarity"] == frozenset(POLARITY_VALUES) | {None}
    assert values["characterization"] == frozenset(CHARACTERIZATION_VALUES) | {None}
    with pytest.raises(ValueError, match="citator_status"):
        ap.values_for(("polarity", "citator_status"))


def test_an_invalid_checker_value_is_refused_naming_the_case_and_the_field():
    """`adopt` writes the CHECKER's value, which never passes through `read_state` at all -
    so the tool checks again on the value that will actually be written."""
    with pytest.raises(ValueError, match="801.*lodgingg.*characterization"):
        ap.patches_for([_d(801, "characterization", "adopt")], {801: _rec(801)}, "mmaldo2",
                       checker={801: {"values": {"characterization": "lodgingg"},
                                      "status": "ok"}})
    with pytest.raises(ValueError, match="802.*polarity"):
        ap.patches_for([_d(802, "polarity", "set", "favourable")], {802: _rec(802)}, "mmaldo2")


def test_a_relevance_decision_writes_a_boolean_and_not_the_pages_string():
    """The page spells `relevant` as a radio's string; the record, the checker and `counts`
    all carry a real boolean, and `"false"` is truthy. Section C can decide this field: the
    checker disputed relevance on 46 of round 1's 150 cards."""
    ps = ap.patches_for([_d(830, "relevant", "set", "false")], {830: _rec(830)}, "mmaldo2")
    assert [p.new for p in ps if p.op == "set" and p.field == "relevant"] == [False]
    ps = ap.patches_for([_d(831, "relevant", "adopt")], {831: _rec(831)}, "mmaldo2",
                        checker={831: {"values": {"relevant": False}, "status": "ok"}})
    assert [p.new for p in ps if p.op == "set" and p.field == "relevant"] == [False]


# --------------------------------------------------- round-1b: relevance-overturn decisions

def test_a_relevance_overturn_is_accepted_on_a_card_whose_decide_field_is_polarity():
    """The round-1b addendum: every card in the round decides polarity or who_was_letting, so
    the reviewer needs a way to say the case is not a letting case at all even though that is
    not the field the card queued. `relevant`/`set`/`false` on a polarity card writes the
    relevant/polarity/who_was_letting cascade plus a note and human-adjudicated status - four
    patches, nothing else, no generic `polarity` patch since polarity was never decided."""
    rec = _rec(850, polarity="favorable", who_was_letting="householder")
    ps = ap.patches_for([_d(850, "relevant", "set", False, note="not a letting case at all")],
                        {850: rec}, "mmaldo2")
    ops = [(p.op, p.field, p.new) for p in ps]
    assert ("set", "relevant", False) in ops
    assert ("set", "polarity", None) in ops
    assert ("set", "who_was_letting", None) in ops
    assert ("set", "review.status", "human-adjudicated") in ops
    notes = [p.new for p in ps if p.op == "append" and p.field == "review.notes"]
    assert any("relevance overturned by the reviewer: not a letting case at all" in n
               for n in notes)
    assert len(ps) == 5          # note + 3 sets + status - no generic patches on top


def test_a_relevance_overturn_accepts_both_letter_cases_of_the_string():
    for cid, spelling in ((851, "false"), (852, "False")):
        ps = ap.patches_for([_d(cid, "relevant", "set", spelling)], {cid: _rec(cid)}, "mmaldo2")
        assert ("set", "relevant", False) in [(p.op, p.field, p.new) for p in ps]


def test_a_relevance_overturn_rejects_relevant_true():
    with pytest.raises(ValueError, match="853.*not accepted"):
        ap.patches_for([_d(853, "relevant", "set", True)], {853: _rec(853)}, "mmaldo2")


def test_a_relevance_overturn_rejects_a_case_already_relevant_false():
    rec = _rec(854, relevant=False, polarity=None, who_was_letting=None)
    with pytest.raises(ValueError, match="854.*already relevant false"):
        ap.patches_for([_d(854, "relevant", "set", False)], {854: rec}, "mmaldo2")


def test_check_against_queue_accepts_relevant_on_any_card():
    """`field == "relevant"` is the one exception to "deciding exactly that card's
    decide_field" - it is waved through no matter what the card's own decide_field is."""
    doc = _queue_doc()          # 700's decide_field is polarity, 701's is who_was_letting
    ap.check_against_queue([{"case_id": 700, "field": "relevant"},
                            {"case_id": 701, "field": "relevant"}], doc)   # does not raise


def test_check_against_queue_still_rejects_a_field_that_is_neither_relevant_nor_the_decide_field():
    doc = _queue_doc()
    with pytest.raises(ValueError, match=r"700.*decides 'polarity'.*'characterization'"):
        ap.check_against_queue([{"case_id": 700, "field": "characterization"}], doc)


def test_the_four_decisions_become_the_right_human_basis_patches():
    assert ap.DECISIONS == ("keep", "adopt", "set", "unsure")
    records = {800: _rec(800, polarity="favorable"), 801: _rec(801, polarity="favorable"),
               802: _rec(802, polarity="favorable"), 803: _rec(803, polarity="favorable")}
    decisions = [
        {"case_id": 800, "field": "polarity", "decision": "keep", "value": "favorable",
         "note": ""},
        {"case_id": 801, "field": "polarity", "decision": "adopt", "value": "adverse",
         "note": ""},
        {"case_id": 802, "field": "polarity", "decision": "set", "value": "mixed",
         "note": "both"},
        {"case_id": 803, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
    ]
    ps = ap.patches_for(decisions, records, "mmaldo2", run_id="map-cycle-004-round-1",
                        checker={801: {"values": {"polarity": "adverse"}, "status": "ok"}})
    by = {}
    for p in ps:
        by.setdefault(p.case_id, []).append((p.op, p.field, p.new))
    assert all(p.basis.reviewer == "mmaldo2" for p in ps)
    assert all(p.basis.run_id == "map-cycle-004-round-1" for p in ps)
    assert all(p.basis.kind() == "human" for p in ps)
    assert ("set", "polarity", "adverse") in by[801]
    assert ("set", "polarity", "mixed") in by[802]
    assert ("append", "review.flags", "needs-review:polarity") in by[803]
    assert ("set", "review.status", "human-adjudicated") in by[800]
    assert not any(op == "set" and f == "polarity" for op, f, _v in by[800])   # keep writes none
    assert not any(op == "set" and f == "polarity" for op, f, _v in by[803])   # nor does unsure
    assert any(op == "append" and f == "review.notes" and "user note: both" in str(v)
               for op, f, v in by[802])


def test_adopt_takes_the_checkers_value_and_not_the_pages_own():
    """The page writes the checker's value into the decision when the radio is clicked, but
    the tool re-derives it: a checker file the round was NOT built with must not be able to
    launder a stale value through the page."""
    records = {801: _rec(801, polarity="favorable")}
    d = [{"case_id": 801, "field": "polarity", "decision": "adopt", "value": "mixed",
          "note": ""}]
    ps = ap.patches_for(d, records, "mmaldo2",
                        checker={801: {"values": {"polarity": "adverse"}, "status": "ok"}})
    assert [p.new for p in ps if p.op == "set" and p.field == "polarity"] == ["adverse"]


def test_adopting_a_field_clears_the_needs_review_flag_it_supersedes():
    """The same rule apply_reference_review enforces, through the same function: a field the
    reviewer has decided is not unsure any more."""
    rec = _rec(810, polarity="favorable")
    rec["review"]["flags"] = ["needs-review:polarity", "needs-review:characterization"]
    ps = ap.patches_for([{"case_id": 810, "field": "polarity", "decision": "set",
                          "value": "mixed", "note": ""}], {810: rec}, "mmaldo2")
    flags = [p.new for p in ps if p.op == "set" and p.field == "review.flags"]
    assert flags == [["needs-review:characterization"]]


def test_unsure_leaves_the_readers_value_standing_and_flags_the_field():
    rec = _rec(820, polarity="favorable")
    ps = ap.patches_for([{"case_id": 820, "field": "quotes", "decision": "unsure",
                          "value": None, "note": ""}], {820: rec}, "mmaldo2")
    ops = [(p.op, p.field, p.new) for p in ps]
    assert ("append", "review.flags", "needs-review:quotes") in ops
    assert not any(op == "set" and f == "quotes" for op, f, _v in ops)
    assert any(op == "append" and f == "review.notes" and "waits for a full read" in str(v)
               for op, f, v in ops)


def test_the_patch_order_is_deterministic():
    records = {1: _rec(1), 2: _rec(2)}
    d = [{"case_id": 2, "field": "polarity", "decision": "keep", "value": "adverse", "note": ""},
         {"case_id": 1, "field": "who_was_letting", "decision": "set", "value": "householder",
          "note": ""},
         {"case_id": 1, "field": "polarity", "decision": "keep", "value": "adverse", "note": ""}]
    ps = ap.patches_for(d, records, "mmaldo2")
    assert [(p.case_id, p.field) for p in ps
            if p.op == "set" and p.field != "review.status"] == [(1, "who_was_letting")]
    assert [p.case_id for p in ps] == sorted(p.case_id for p in ps)


def test_an_unknown_decision_is_refused_rather_than_silently_dropped():
    with pytest.raises(ValueError, match="maybe"):
        ap.patches_for([{"case_id": 1, "field": "polarity", "decision": "maybe",
                         "value": "adverse", "note": ""}], {1: _rec(1)}, "mmaldo2")


# ------------------------------------------------------------ the --decisions file path

FIELDS = ("polarity", "who_was_letting", "characterization", "quotes")


def test_a_decisions_file_reads_the_same_way_a_saved_page_does(tmp_path):
    """`ap.read_decisions` and `ap.read_page` both funnel through
    `apply_reference_review._decisions_from_list` - the same schema the page embeds,
    validated by the same rules, whether it arrives wrapped in a page or as a bare list."""
    raw = [_d(700, "polarity", "adopt", "adverse"),
          _d(701, "who_was_letting", "keep", "unclear"),
          _d(702, "polarity", "set", "favorable", note="both ways"),
          _d(703, "quotes", "unsure")]
    got = ap.read_decisions(raw, FIELDS)
    page = _saved_page(tmp_path, raw)
    from_page = ap.read_page(page.read_text(encoding="utf-8"), FIELDS)
    assert got == from_page


def test_the_decisions_file_path_checks_every_case_against_the_queue_and_applies_each_kind(
        tmp_path, monkeypatch):
    """Round-trip through `ap.main`: keep, set, adopt and unsure, each on the card the queue
    actually asked about, with --assisted-by recording the first pass."""
    import sys as _sys

    from corpus_engine.domain import load_domain
    from corpus_engine.ledger import open_ledger as real_open_ledger
    from corpus_engine.ledger.types import Basis, Patch

    doc = _queue_doc()
    queue_path = tmp_path / "review-round-1.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    checker = {700: {"values": {"polarity": "adverse"}, "status": "ok"},
              702: {"values": {"polarity": "adverse"}, "status": "ok"}}
    checker_path = tmp_path / "review-round-1-checker.json"
    checker_path.write_text(json.dumps(checker), encoding="utf-8")

    decisions = [
        _d(700, "polarity", "keep", "favorable"),
        _d(701, "who_was_letting", "set", "commercial_operator", note="reassessed"),
        _d(702, "polarity", "adopt"),
        _d(703, "characterization", "unsure"),
    ]
    dec_path = tmp_path / "decisions.json"
    dec_path.write_text(json.dumps(decisions), encoding="utf-8")

    dom = load_domain()
    ledger_dir = tmp_path / "ledger"
    led = real_open_ledger(ledger_dir, domain=dom)
    seed_basis = Basis(model="m", prompt_version="v", run_id="seed")
    admits = [Patch(r["case_id"], "admit", "", r, "seed", seed_basis, cycle="cycle-001")
             for r in [_rec(700, polarity="favorable", under_thirty_days="yes"),
                       _rec(701, who_was_letting="householder", duration_of_occupancy="nights"),
                       _rec(702, polarity="mixed"),
                       _rec(703, nulled_fields=["characterization"])]]
    led.apply(admits, note="seed")

    monkeypatch.setattr(ap, "open_ledger", lambda *a, **kw: real_open_ledger(
        ledger_dir, domain=kw.get("domain") or dom))
    monkeypatch.setattr(_sys, "argv",
                        ["apply_map_review.py", "--decisions", str(dec_path),
                         "--queue", str(queue_path), "--checker", str(checker_path),
                         "--run-id", "map-cycle-004-round-1", "--assisted-by", "GPT Astra",
                         "--dry-run"])
    assert ap.main() == 0

    monkeypatch.setattr(_sys, "argv",
                        ["apply_map_review.py", "--decisions", str(dec_path),
                         "--queue", str(queue_path), "--checker", str(checker_path),
                         "--run-id", "map-cycle-004-round-1", "--assisted-by", "GPT Astra"])
    assert ap.main() == 0

    # `led`'s own `.view()` is cached from the seed apply() above and would not see writes
    # made through the fresh Ledger instances `ap.main()` opens on every call - a new
    # instance over the same directory reads the log as it stands now.
    after = real_open_ledger(ledger_dir, domain=dom).view()
    assert after.state.records[701]["who_was_letting"] == "commercial_operator"
    assert after.state.records[702]["polarity"] == "adverse"          # adopt took the checker
    assert after.state.records[700]["polarity"] == "favorable"        # keep left it standing
    notes = "\n".join(after.state.records[701]["review"]["notes"])
    assert "first pass drafted by GPT Astra; confirmed by the reviewer" in notes
    flags = after.state.records[703]["review"]["flags"]
    assert "needs-review:characterization" in flags


def test_a_decisions_file_rejects_an_unknown_case_id():
    doc = _queue_doc()
    with pytest.raises(ValueError, match="9999.*not a card"):
        ap.check_against_queue([{"case_id": 9999, "field": "polarity"}], doc)


def test_a_decisions_file_rejects_a_wrong_field():
    doc = _queue_doc()
    with pytest.raises(ValueError, match=r"700.*decides 'polarity'.*'characterization'"):
        ap.check_against_queue([{"case_id": 700, "field": "characterization"}], doc)


def test_a_decisions_file_rejects_an_invalid_value():
    with pytest.raises(ValueError, match="FAVORABEL"):
        ap.read_decisions([_d(700, "polarity", "set", "FAVORABEL")], FIELDS)


def test_assisted_by_adds_a_note_and_marks_the_why_string():
    ps = ap.patches_for([_d(810, "polarity", "set", "mixed")], {810: _rec(810)}, "mmaldo2",
                        assisted_by="GPT Astra")
    notes = [p.new for p in ps if p.op == "append" and p.field == "review.notes"]
    assert any("first pass drafted by GPT Astra; confirmed by the reviewer" in n for n in notes)
    assert all("assisted by GPT Astra" in p.why for p in ps)


def test_assisted_by_is_absent_by_default():
    ps = ap.patches_for([_d(811, "polarity", "keep", "adverse")], {811: _rec(811)}, "mmaldo2")
    notes = [p.new for p in ps if p.op == "append" and p.field == "review.notes"]
    assert not any("drafted by" in n for n in notes)
    assert not any("assisted by" in p.why for p in ps)


def test_saved_and_decisions_are_mutually_exclusive():
    with pytest.raises(SystemExit):        # neither given: the mutually exclusive group is required
        ap.main([])
    with pytest.raises(SystemExit):        # both given: argparse refuses the pair
        ap.main(["--saved", "x", "--decisions", "y"])


# ------------------------------------------------------------------- export_review_cards

def test_cards_from_queue_carries_every_field_the_page_shows(tmp_path):
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, CHECKER)
    assert [c["case_id"] for c in cards] == [700, 701, 702, 703]
    assert [c["section"] for c in cards] == ["A", "B", "D", "E"]
    c700 = cards[0]
    assert c700["section_title"] == "Favorable and under thirty days"
    assert c700["decide_field"] == "polarity"
    assert c700["reader"]["polarity"] == "favorable"
    assert c700["reader"]["under_thirty_days"] == "yes"
    assert c700["checker"] == {"relevant": None, "polarity": "adverse", "characterization": None}
    assert c700["holding_summary"] == "the lodger has the use only"
    assert c700["quotes"] == [{"text": "q", "supports": ["polarity"]}]
    assert c700["nulled_fields"] == []
    assert c700["other_reasons"] == []
    assert "courtlistener.com" in c700["courtlistener_url"] and "700" in c700["courtlistener_url"]


def test_a_card_with_no_checker_answer_carries_none_not_a_dict_of_nulls():
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, {})
    assert all(c["checker"] is None for c in cards)


def test_cards_from_queue_respects_nulled_fields_and_other_reasons(tmp_path):
    doc = _queue_doc(disagreements=[{"unit_id": "b1", "case_id": 702, "field": "polarity",
                                     "reader_value": "mixed", "checker_value": "adverse"}])
    cards = ec.cards_from_queue(doc, {})
    by_id = {c["case_id"]: c for c in cards}
    assert by_id[703]["nulled_fields"] == ["characterization"]
    assert by_id[703]["decide_field"] == "characterization"


def test_markdown_has_one_heading_per_section_and_every_card(tmp_path):
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, CHECKER)
    md = ec.markdown_for(cards, doc["run_id"])
    assert md.endswith("\n")
    assert "## A. Favorable and under thirty days" in md
    assert "## B. Householder letting by the night" in md
    assert "## D. Polarity mixed" in md
    assert "## E. Judged fields erased by the quote gate" in md
    for cid in (700, 701, 702, 703):
        assert f"[{cid}]" in md
    assert "not asked" in md          # 701/702/703 have no checker entry in CHECKER


def test_main_writes_deterministic_json_and_markdown(tmp_path):
    doc = _queue_doc()
    queue_path = tmp_path / "review-round-1.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    checker_path = tmp_path / "review-round-1-checker.json"
    checker_path.write_text(json.dumps(CHECKER), encoding="utf-8")
    out_stem = tmp_path / "cards"

    assert ec.main(["--queue", str(queue_path), "--checker", str(checker_path),
                    "--out-stem", str(out_stem)]) == 0
    json_path = Path(str(out_stem) + ".json")
    md_path = Path(str(out_stem) + ".md")
    raw = json_path.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    cards = json.loads(raw.decode("utf-8"))
    assert len(cards) == 4
    md_raw = md_path.read_bytes()
    assert md_raw.endswith(b"\n") and b"\r\n" not in md_raw

    # a second run over the same inputs writes byte-identical files
    out_stem2 = tmp_path / "cards2"
    ec.main(["--queue", str(queue_path), "--checker", str(checker_path),
            "--out-stem", str(out_stem2)])
    assert json_path.read_bytes() == Path(str(out_stem2) + ".json").read_bytes()


def test_courtlistener_url_matches_the_pages_own_encoding():
    """The same %22-quoted-cite search the review page's client-side `clq` builds."""
    url = ec.courtlistener_url("119 N.J.L. 61")
    assert url == "https://www.courtlistener.com/?q=%22119%20N.J.L.%2061%22"


# ------------------------------------------------------- round-1b: unsure, full text, chunks

class _FakeTextSource:
    """The `StoreCaseSource` interface (`fetch(ids) -> [CaseText, ...]`), backed by a plain
    dict of short texts instead of a real corpus.db connection."""
    def __init__(self, texts: dict):
        self.texts = texts

    def fetch(self, ids):
        from corpus_engine.reader.model import CaseText
        return [CaseText(int(i), "", "", "", "", 1890, "", self.texts[int(i)], [])
               for i in ids]


def test_only_unsure_ids_reads_the_decisions_file_schema(tmp_path):
    dec_path = tmp_path / "decisions.json"
    dec_path.write_text(json.dumps([
        {"case_id": 700, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
        {"case_id": 701, "field": "who_was_letting", "decision": "set",
         "value": "householder", "note": ""},
        {"case_id": 702, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
    ]), encoding="utf-8")
    assert ec.only_unsure_ids(dec_path) == {700, 702}


def test_main_only_unsure_restricts_the_export_to_the_flagged_cases(tmp_path):
    doc = _queue_doc()
    queue_path = tmp_path / "review-round-1.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    dec_path = tmp_path / "decisions.json"
    dec_path.write_text(json.dumps([
        {"case_id": 700, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
        {"case_id": 702, "field": "polarity", "decision": "unsure", "value": None, "note": ""},
    ]), encoding="utf-8")
    out_stem = tmp_path / "unsure-cards"

    assert ec.main(["--queue", str(queue_path), "--checker", str(tmp_path / "none.json"),
                    "--only-unsure", str(dec_path), "--out-stem", str(out_stem)]) == 0
    cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    assert sorted(c["case_id"] for c in cards) == [700, 702]


def test_attach_opinion_text_adds_norm_text_via_the_injected_source():
    cards = ec.cards_from_queue(_queue_doc(), {})
    got = ec.attach_opinion_text(cards, _FakeTextSource({700: "op 700", 701: "op 701",
                                                          702: "op 702", 703: "op 703"}))
    assert {c["case_id"]: c["opinion_text"] for c in got} == {
        700: "op 700", 701: "op 701", 702: "op 702", 703: "op 703"}


def test_full_text_puts_opinion_text_after_the_card_fields_in_markdown():
    cards = ec.cards_from_queue(_queue_doc(), CHECKER)
    ec.attach_opinion_text(cards, _FakeTextSource({700: "the opinion text for 700",
                                                   701: "op 701", 702: "op 702", 703: "op 703"}))
    md = ec.markdown_for(cards, "cycle-004-shard-01")
    assert "#### Opinion text" in md
    assert "the opinion text for 700" in md
    court_at = md.index("- CourtListener:")
    heading_at = md.index("#### Opinion text")
    text_at = md.index("the opinion text for 700")
    assert court_at < heading_at < text_at        # opinion text follows the card fields


def test_markdown_for_without_full_text_has_no_opinion_heading():
    cards = ec.cards_from_queue(_queue_doc(), CHECKER)
    md = ec.markdown_for(cards, "cycle-004-shard-01")
    assert "#### Opinion text" not in md


def test_chunks_default_writes_the_single_file_unsuffixed(tmp_path):
    cards = ec.cards_from_queue(_queue_doc(), CHECKER)
    parts = ec.markdown_parts(cards, "cycle-004-shard-01", 1)
    assert len(parts) == 1
    assert parts[0] == ec.markdown_for(cards, "cycle-004-shard-01")   # byte-identical


def test_chunks_splits_into_n_files_without_splitting_a_card():
    cards = ec.cards_from_queue(_queue_doc(), CHECKER)
    for c in cards:
        c["opinion_text"] = "x" * 1000       # equal weights: an even split by card count
    parts = ec.markdown_parts(cards, "cycle-004-shard-01", 4)
    assert len(parts) == 4
    seen = []
    for p in parts:
        for cid in (700, 701, 702, 703):
            if f"[{cid}]" in p:
                seen.append(cid)
    assert sorted(seen) == [700, 701, 702, 703]        # every card appears exactly once
    assert all(p.endswith("\n") for p in parts)
    assert all("part " in p.split("\n", 1)[0] for p in parts)


def test_chunks_more_than_cards_caps_at_one_part_per_card():
    cards = ec.cards_from_queue(_queue_doc(), CHECKER)
    parts = ec.markdown_parts(cards, "cycle-004-shard-01", 99)
    assert len(parts) == len(cards)


def test_main_chunks_names_files_out_stem_partk(tmp_path, monkeypatch):
    doc = _queue_doc()
    queue_path = tmp_path / "review-round-1.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    checker_path = tmp_path / "review-round-1-checker.json"
    checker_path.write_text(json.dumps(CHECKER), encoding="utf-8")
    out_stem = tmp_path / "cards"

    monkeypatch.setattr(ec, "StoreCaseSource",
                        lambda conn: _FakeTextSource({700: "t700", 701: "t701",
                                                       702: "t702", 703: "t703"}))
    monkeypatch.setattr(ec.store, "connect", lambda *a, **kw: None)

    assert ec.main(["--queue", str(queue_path), "--checker", str(checker_path),
                    "--out-stem", str(out_stem), "--full-text", "--chunks", "2"]) == 0
    for k in (1, 2):
        p = Path(str(out_stem) + f"-part{k}.md")
        assert p.exists()
        raw = p.read_bytes()
        assert raw.endswith(b"\n") and b"\r\n" not in raw
    assert not Path(str(out_stem) + ".md").exists()
    json_cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    assert all("opinion_text" in c for c in json_cards)


# ------------------------------------------------------ round 2: adopt on relevant cascades
#
# Section C can now decide `relevant` itself (the checker disputed relevance directly, not
# some other field) - `adopt` there must write the same relevant/polarity/who_was_letting
# cascade the round-1b `set`-False relevance overturn writes, not a bare `relevant` patch that
# would leave stale polarity/who_was_letting values sitting on a record that is no longer
# relevant.

def test_adopting_the_checkers_relevant_false_on_its_own_decide_field_cascades():
    rec = _rec(860, polarity="favorable", who_was_letting="householder")
    ps = ap.patches_for([_d(860, "relevant", "adopt")], {860: rec}, "mmaldo2",
                        checker={860: {"values": {"relevant": False}, "status": "ok"}})
    ops = [(p.op, p.field, p.new) for p in ps]
    assert ("set", "relevant", False) in ops
    assert ("set", "polarity", None) in ops
    assert ("set", "who_was_letting", None) in ops
    assert ("set", "review.status", "human-adjudicated") in ops
    assert len(ps) == 5          # note + 3 sets + status, same shape as the set-False overturn


def test_keep_on_a_relevant_decide_field_does_not_cascade():
    """`keep` leaves the reader's already-True value standing - nothing about the case
    changed, so there is nothing to cascade."""
    rec = _rec(861, polarity="favorable", who_was_letting="householder")
    ps = ap.patches_for([_d(861, "relevant", "keep", True)], {861: rec}, "mmaldo2")
    ops = [(p.op, p.field, p.new) for p in ps]
    assert not any(op == "set" and f in ("polarity", "who_was_letting", "relevant")
                   for op, f, _v in ops)
    assert ("set", "review.status", "human-adjudicated") in ops


def test_adopting_relevant_true_is_still_rejected():
    """A queued record's relevant is already True, so in practice a checker can only ever
    disagree with False - but the rule holds regardless of decision kind."""
    with pytest.raises(ValueError, match="862.*not accepted"):
        ap.patches_for([_d(862, "relevant", "adopt")], {862: _rec(862)}, "mmaldo2",
                       checker={862: {"values": {"relevant": True}, "status": "ok"}})


def test_adopting_relevant_on_an_already_irrelevant_record_is_rejected():
    rec = _rec(863, relevant=False, polarity=None, who_was_letting=None)
    with pytest.raises(ValueError, match="863.*already relevant false"):
        ap.patches_for([_d(863, "relevant", "adopt")], {863: rec}, "mmaldo2",
                       checker={863: {"values": {"relevant": False}, "status": "ok"}})


# --------------------------------------------------- round 2: section-E field vocabularies

@pytest.mark.parametrize("field,good,bad", [
    ("under_thirty_days", "yes", "sometimes"),
    ("owner_freedom_characterization", "regulable_privilege", "bogus_freedom"),
    ("restriction_nature", "zoning", "bogus_restriction"),
    ("characterization", "lodging", "bogus_characterization"),
])
def test_set_on_a_section_e_field_validates_against_its_own_vocabulary(field, good, bad):
    ps = ap.patches_for([_d(870, field, "set", good)], {870: _rec(870, **{field: None})},
                        "mmaldo2")
    assert ("set", field, good) in [(p.op, p.field, p.new) for p in ps]
    with pytest.raises(ValueError, match=f"871.*{field}"):
        ap.patches_for([_d(871, field, "set", bad)], {871: _rec(871, **{field: None})},
                       "mmaldo2")


def test_set_on_holding_summary_accepts_free_text_with_no_vocabulary_check():
    """`holding_summary` (ap.VALUES['holding_summary'] is None) is one of the two free-text
    opt-outs - unlike the closed-vocabulary judged fields above, any string is accepted."""
    text = "the court held the lease terminable at will, no letting restriction at issue"
    ps = ap.patches_for([_d(872, "holding_summary", "set", text)], {872: _rec(872)}, "mmaldo2")
    assert ("set", "holding_summary", text) in [(p.op, p.field, p.new) for p in ps]


def test_an_unsure_decision_does_not_set_human_adjudicated_status():
    """D3: unsure flags the field for a human and leaves the record machine-only; only keep,
    adopt and set carry the record into the human-reviewed tier."""
    import tools.apply_map_review as ap
    unsure = ap.patches_for([_d(840, "polarity", "unsure")], {840: _rec(840)}, "mmaldo2",
                            assisted_by="GPT Astra")
    assert not [p for p in unsure if p.field == "review.status"]
    assert any("left unsure, not confirmed" in str(p.new) for p in unsure if p.field == "review.notes")
    kept = ap.patches_for([_d(841, "polarity", "keep")], {841: _rec(841)}, "mmaldo2",
                          assisted_by="GPT Astra")
    assert [p for p in kept if p.field == "review.status" and p.new == "human-adjudicated"]


# --------------------------------------------- round 2: --full-text-sections, section-C markdown

def test_markdown_shows_reader_vs_checker_prominently_for_section_c():
    doc = _queue_doc(disagreements=[{"unit_id": "b1", "case_id": 702, "field": "polarity",
                                     "reader_value": "mixed", "checker_value": "adverse"}])
    checker = {702: {"values": {"polarity": "adverse"}, "status": "ok"}}
    cards = ec.cards_from_queue(doc, checker)
    assert [c["section"] for c in cards] == ["A", "B", "C", "E"]     # 702 -> C, per queue.py
    md = ec.markdown_for(cards, doc["run_id"])
    assert "Reader says mixed; checker says adverse" in md


def test_markdown_says_not_available_when_section_c_has_no_checker_entry():
    """A section-C card without a checker value (missing/not asked) gets no "Reader says"
    line - there is nothing to contrast the reader's answer against."""
    doc = _queue_doc(disagreements=[{"unit_id": "b1", "case_id": 702, "field": "polarity",
                                     "reader_value": "mixed", "checker_value": "adverse"}])
    cards = ec.cards_from_queue(doc, {})               # no checker file loaded
    md = ec.markdown_for(cards, doc["run_id"])
    assert "Reader says" not in md


def test_full_text_sections_attaches_opinion_text_only_to_the_named_sections(tmp_path, monkeypatch):
    doc = _queue_doc()          # 700 A, 701 B, 702 D, 703 E
    queue_path = tmp_path / "review-round-2.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    checker_path = tmp_path / "review-round-2-checker.json"
    checker_path.write_text(json.dumps(CHECKER), encoding="utf-8")
    out_stem = tmp_path / "cards"

    monkeypatch.setattr(ec, "StoreCaseSource",
                        lambda conn: _FakeTextSource({700: "t700", 701: "t701",
                                                       702: "t702", 703: "t703"}))
    monkeypatch.setattr(ec.store, "connect", lambda *a, **kw: None)

    assert ec.main(["--queue", str(queue_path), "--checker", str(checker_path),
                    "--out-stem", str(out_stem), "--full-text-sections", "D"]) == 0
    cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    by_id = {c["case_id"]: c for c in cards}
    assert by_id[702]["opinion_text"] == "t702"        # section D: included
    assert "opinion_text" not in by_id[700]            # section A: excluded
    assert "opinion_text" not in by_id[701]            # section B: excluded


def test_full_text_sections_takes_priority_over_full_text_when_both_are_given(tmp_path, monkeypatch):
    doc = _queue_doc()
    queue_path = tmp_path / "review-round-2.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    out_stem = tmp_path / "cards"

    monkeypatch.setattr(ec, "StoreCaseSource",
                        lambda conn: _FakeTextSource({700: "t700", 701: "t701",
                                                       702: "t702", 703: "t703"}))
    monkeypatch.setattr(ec.store, "connect", lambda *a, **kw: None)

    assert ec.main(["--queue", str(queue_path), "--checker", str(tmp_path / "none.json"),
                    "--out-stem", str(out_stem), "--full-text-sections", "B",
                    "--full-text"]) == 0
    cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    by_id = {c["case_id"]: c for c in cards}
    assert by_id[701]["opinion_text"] == "t701"        # section B: included
    assert "opinion_text" not in by_id[700]            # --full-text alone did not win


# ------------------------------------------------------------- round 2: section-E erased_value

def test_unit_cache_keys_flattens_across_every_cell():
    manifest = {"cells": {"c1": {"cache_keys": {"batch-001": ["k1"]}},
                          "c2": {"cache_keys": {"batch-002": ["k2", "k3"]}}}}
    assert ec.unit_cache_keys(manifest) == {"batch-001": ["k1"], "batch-002": ["k2", "k3"]}


def test_unit_cache_keys_handles_a_manifest_with_no_cells():
    assert ec.unit_cache_keys({}) == {}


def test_case_unit_index_maps_case_id_to_the_batch_that_read_it():
    batches = [{"batch_id": "batch-001", "cases": [{"case_id": 700}, {"case_id": 701}]},
              {"batch_id": "batch-002", "cases": [{"case_id": 703}]}]
    assert ec.case_unit_index(batches) == {700: "batch-001", 701: "batch-001", 703: "batch-002"}


def test_erased_value_reads_the_raw_pre_gate_field_from_the_cached_response(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    raw_text = json.dumps([{"case_id": 703, "relevant": True, "polarity": "adverse",
                            "quotes": [], "characterization": "innkeeping"}])
    (cache_dir / "k1.json").write_text(json.dumps({"text": raw_text}), encoding="utf-8")

    got = ec.erased_value(703, "characterization", unit_of={703: "batch-002"},
                          cache_keys={"batch-002": ["k1"]}, cache_dir=cache_dir)
    assert got == "innkeeping"


def test_erased_value_is_none_when_the_case_has_no_known_unit(tmp_path):
    assert ec.erased_value(999, "characterization", unit_of={}, cache_keys={},
                           cache_dir=tmp_path) is None


def test_erased_value_is_none_when_no_cache_key_is_on_disk(tmp_path):
    got = ec.erased_value(703, "characterization", unit_of={703: "batch-002"},
                          cache_keys={"batch-002": ["missing-key"]}, cache_dir=tmp_path)
    assert got is None


def test_erased_value_is_none_when_the_cached_response_will_not_parse(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "k1.json").write_text(json.dumps({"text": "not json at all"}),
                                       encoding="utf-8")
    got = ec.erased_value(703, "characterization", unit_of={703: "batch-002"},
                          cache_keys={"batch-002": ["k1"]}, cache_dir=cache_dir)
    assert got is None


def test_erased_value_is_none_when_the_field_is_absent_from_the_raw_record(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    raw_text = json.dumps([{"case_id": 703, "relevant": True, "polarity": "adverse",
                            "quotes": []}])                    # no characterization key
    (cache_dir / "k1.json").write_text(json.dumps({"text": raw_text}), encoding="utf-8")
    got = ec.erased_value(703, "characterization", unit_of={703: "batch-002"},
                          cache_keys={"batch-002": ["k1"]}, cache_dir=cache_dir)
    assert got is None


def test_attach_erased_values_skips_io_entirely_when_no_section_e_card_is_present(tmp_path):
    doc = _queue_doc()
    cards = [c for c in ec.cards_from_queue(doc, {}) if c["section"] != "E"]

    class _ExplodingManifest(dict):
        def get(self, *a, **kw):
            raise AssertionError("manifest read despite no section-E card")

    out = ec.attach_erased_values(cards, manifest=_ExplodingManifest(), batches=[],
                                  cache_dir=tmp_path)
    assert all("erased_value" not in c for c in out)


def test_attach_erased_values_adds_it_only_to_section_e_cards(tmp_path):
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, {})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    raw_text = json.dumps([{"case_id": 703, "relevant": True, "polarity": "adverse",
                            "quotes": [], "characterization": "innkeeping"}])
    (cache_dir / "k1.json").write_text(json.dumps({"text": raw_text}), encoding="utf-8")
    manifest = {"cells": {"c1": {"cache_keys": {"batch-002": ["k1"]}}}}
    batches = [{"batch_id": "batch-002", "cases": [{"case_id": 703}]}]

    out = ec.attach_erased_values(cards, manifest=manifest, batches=batches,
                                  cache_dir=cache_dir)
    by_id = {c["case_id"]: c for c in out}
    assert by_id[703]["erased_value"] == "innkeeping"
    assert "erased_value" not in by_id[700]


def test_markdown_shows_erased_value_for_section_e_when_present():
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, {})
    for c in cards:
        if c["section"] == "E":
            c["erased_value"] = "innkeeping"
    md = ec.markdown_for(cards, doc["run_id"])
    assert "Erased value for characterization" in md and "innkeeping" in md


def test_markdown_has_no_erased_value_line_when_the_key_is_absent():
    doc = _queue_doc()
    cards = ec.cards_from_queue(doc, {})
    md = ec.markdown_for(cards, doc["run_id"])
    assert "Erased value" not in md


def test_main_computes_erased_value_for_section_e_cards_via_manifest_and_batches(tmp_path):
    doc = _queue_doc()
    queue_path = tmp_path / "review-round-2.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")

    manifest_path = tmp_path / "map-manifest.json"
    manifest_path.write_text(json.dumps(
        {"cells": {"c1": {"cache_keys": {"batch-002": ["k1"]}}}}), encoding="utf-8")

    batches_dir = tmp_path / "batches"
    batches_dir.mkdir()
    (batches_dir / "batch-002.json").write_text(json.dumps(
        {"batch_id": "batch-002", "cases": [{"case_id": 703}]}), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    raw_text = json.dumps([{"case_id": 703, "relevant": True, "polarity": "adverse",
                            "quotes": [], "characterization": "innkeeping"}])
    (cache_dir / "k1.json").write_text(json.dumps({"text": raw_text}), encoding="utf-8")

    out_stem = tmp_path / "cards"
    assert ec.main(["--queue", str(queue_path), "--checker", str(tmp_path / "none.json"),
                    "--out-stem", str(out_stem), "--map-manifest", str(manifest_path),
                    "--batches-dir", str(batches_dir), "--reader-cache", str(cache_dir)]) == 0
    cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    by_id = {c["case_id"]: c for c in cards}
    assert by_id[703]["erased_value"] == "innkeeping"
    assert "erased_value" not in by_id[700]


def test_main_never_reads_map_manifest_or_batches_when_no_section_e_card(tmp_path):
    """The default paths (the real run's manifest and ~1,846 pool batch files) must not be
    touched at all for a round with no section-E cards, like this round's own (B 1, C 100,
    D 149, no E) - passing nonexistent defaults must not raise."""
    doc = _queue_doc(records=[_rec(700, polarity="favorable", under_thirty_days="yes")])
    queue_path = tmp_path / "review-round-2.json"
    queue_path.write_text(json.dumps(doc), encoding="utf-8")
    out_stem = tmp_path / "cards"

    assert ec.main(["--queue", str(queue_path), "--checker", str(tmp_path / "none.json"),
                    "--out-stem", str(out_stem), "--map-manifest", str(tmp_path / "nope.json"),
                    "--batches-dir", str(tmp_path / "nope-dir"),
                    "--reader-cache", str(tmp_path / "nope-cache")]) == 0
    cards = json.loads(Path(str(out_stem) + ".json").read_bytes().decode("utf-8"))
    assert "erased_value" not in cards[0]


def test_an_adopt_with_a_null_value_passes_vocabulary_validation():
    """adopt takes the checker's value at apply time, so a null value on the entry is fine;
    a non-null value on an adopt or a set must still be in the field's vocabulary."""
    import tools.apply_reference_review as arr
    ok = arr._decisions_from_list([{"case_id": 1, "field": "relevant", "decision": "adopt",
                                    "value": None, "note": ""}], fields=("relevant",),
                                  values={"relevant": frozenset({False})})
    assert ok and ok[0]["decision"] == "adopt"
    import pytest
    with pytest.raises(ValueError):
        arr._decisions_from_list([{"case_id": 1, "field": "relevant", "decision": "set",
                                   "value": None, "note": ""}], fields=("relevant",),
                                 values={"relevant": frozenset({False})})

