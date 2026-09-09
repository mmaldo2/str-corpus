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
from corpus_engine.ledger import fold as ledger_fold
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

CONFLICT = {"case_id": 70, "field": "polarity", "human_value": "favorable",
            "human_basis": {"reviewer": "mmaldo2", "run_id": "map-cycle-004-round-1"},
            "human_at": 900, "reread_value": "adverse",
            "reread_basis": {"model": "claude-opus-5@claude-cli",
                             "prompt_version": "mapper-v3:f92016681314",
                             "run_id": "cycles-001-003-reread"},
            "kind": "value", "cell_key": "pre-1860|N.Y.", "batch_id": "b1"}


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


# ------------------------------------------------- section F: `set` on `quotes` drops a quote

def _fuzzy_rec(cid, **over):
    """A record carrying one quote flagged `verified-fuzzy` (the reader's fuzzy match) plus a
    clean `verified` quote that alone supports `polarity` - so a test can tell a dropped quote's
    cascade from a quote that was never touched."""
    r = _rec(cid, **over)
    r["quotes"] = [
        {"text": "she let the room by the week", "supports": ["characterization"],
         "status": "verified-fuzzy"},
        {"text": "the owner's liberty to let was unrestricted", "supports": ["polarity"],
         "status": "verified"},
    ]
    return r


def test_set_on_quotes_drops_the_named_fuzzy_quote_via_drop_quote_not_set():
    """The F-card decision: `set` on `quotes` never writes a `set` patch on the whole `quotes`
    field (that would replace the record's entire quote list with the raw value) - it writes a
    `drop_quote` patch naming the exact quote text to remove, the same op the Stage 1 bootstrap
    used for its own section B."""
    rec = _fuzzy_rec(830)
    ps = ap.patches_for(
        [{"case_id": 830, "field": "quotes", "decision": "set",
          "value": "she let the room by the week", "note": "OCR run of substitutions, not a "
          "real mismatch"}],
        {830: rec}, "mmaldo2")
    ops = [(p.op, p.field, p.new) for p in ps]
    assert ("drop_quote", "quotes", "she let the room by the week") in ops
    assert not any(op == "set" and f == "quotes" for op, f, _v in ops)
    assert any(op == "set" and f == "review.status" and v == "human-adjudicated"
              for op, f, v in ops)


def test_set_on_quotes_cascades_through_the_ledger_to_null_the_field_it_alone_supported():
    """End to end: applying the `drop_quote` patch `patches_for` emits through the ledger's own
    fold nulls `characterization` (supported only by the dropped quote) and leaves `polarity`
    (supported by the surviving quote) untouched - the cascade `fold.apply_patch` performs, not
    something this tool has to reimplement."""
    rec = _fuzzy_rec(831, characterization="lodging")
    ps = ap.patches_for(
        [{"case_id": 831, "field": "quotes", "decision": "set",
          "value": "she let the room by the week", "note": ""}],
        {831: rec}, "mmaldo2")
    state = ledger_fold.State(records={831: rec}, order=[831], cycles={831: "cycle-004"},
                              in_file={831: True}, prompts={831: "mapper-v3"})
    for p in ps:
        if p.op in ("set", "append", "drop_quote"):
            ledger_fold.apply_patch(state, p)
    after = state.records[831]
    assert after["characterization"] is None
    assert "characterization" in after["nulled_fields"]
    assert after["polarity"] == "adverse"                 # the surviving quote still supports it
    assert [q["text"] for q in after["quotes"]] == ["the owner's liberty to let was unrestricted"]


def test_set_on_quotes_accepts_a_list_of_texts_for_a_card_with_more_than_one_fuzzy_quote():
    rec = _fuzzy_rec(832)
    rec["quotes"].append({"text": "a third quote", "supports": ["under_thirty_days"],
                          "status": "verified-fuzzy"})
    ps = ap.patches_for(
        [{"case_id": 832, "field": "quotes", "decision": "set",
          "value": ["she let the room by the week", "a third quote"], "note": ""}],
        {832: rec}, "mmaldo2")
    dropped = [p.new for p in ps if p.op == "drop_quote"]
    assert dropped == ["she let the room by the week", "a third quote"]


def test_set_on_quotes_refuses_a_value_that_matches_no_quote_on_the_record():
    rec = _fuzzy_rec(833)
    with pytest.raises(ValueError, match="833.*does not match any quote text"):
        ap.patches_for(
            [{"case_id": 833, "field": "quotes", "decision": "set",
              "value": "this text is not on the record", "note": ""}],
            {833: rec}, "mmaldo2")


def test_keep_on_quotes_still_takes_the_generic_path_and_writes_no_drop_quote():
    """`keep` (the quote stands as verified) and `unsure` (send for a full read) are unaffected
    by the `set`/drop special case - only `set` on `quotes` reaches it."""
    rec = _fuzzy_rec(834)
    ps = ap.patches_for(
        [{"case_id": 834, "field": "quotes", "decision": "keep", "value": None, "note": ""}],
        {834: rec}, "mmaldo2")
    assert not any(p.op == "drop_quote" for p in ps)
    assert not any(p.op == "set" and p.field == "quotes" for p in ps)


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


def _fuzzy_queue_doc():
    """A one-card section-F queue manifest, shaped exactly as `QueueCard.to_json()` writes
    it (`corpus_engine/mapper/queue.py`), for testing `cards_from_queue`'s export of the
    `fuzzy` block without going through `select_queue`'s own fuzzy classification."""
    card = {"case_id": 900, "section": "F", "reason": "fuzzy_quote", "other_reasons": [],
            "decide_field": "quotes", "cite": "900 N.Y. 1", "name": None, "court": "Ct. App.",
            "jur": "N.Y.", "year": 1900,
            "values": {f: None for f in ("relevant", "polarity", "who_was_letting",
                                         "duration_of_occupancy", "characterization",
                                         "under_thirty_days", "owner_freedom_characterization",
                                         "restriction_nature")},
            "holding_summary": None, "quotes": [], "nulled_fields": [],
            "extraction_status": "ok", "disagreements": [],
            "fuzzy": [{"text": "she let the room by the week", "supports": ["characterization"],
                      "status": "verified-fuzzy", "classification": "needs-human",
                      "quote_coverage": 0.8, "source": "she let ye roome by ye weeke",
                      "auto_accepted": False}]}
    return {"run_id": "test-run", "cap": 150, "titles": {}, "sections": {"F": [card]},
           "deferred": [], "fuzzy_auto_accepted": []}


def test_cards_from_queue_carries_the_fuzzy_block_for_a_section_f_card():
    cards = ec.cards_from_queue(_fuzzy_queue_doc(), {})
    assert cards[0]["fuzzy"] == [{"text": "she let the room by the week",
                                  "source": "she let ye roome by ye weeke",
                                  "classification": "needs-human", "quote_coverage": 0.8,
                                  "auto_accepted": False}]


def test_markdown_shows_the_fuzzy_quote_beside_the_opinion_passage():
    cards = ec.cards_from_queue(_fuzzy_queue_doc(), {})
    md = ec.markdown_for(cards, "test-run")
    assert "she let the room by the week" in md
    assert "she let ye roome by ye weeke" in md
    assert "needs-human" in md


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


# ----------------------------------------------------- round 3: section-E "unclear" and "keep"

def test_set_under_thirty_days_unclear_is_a_valid_value():
    """under_thirty_days's own vocabulary is yes|no|unclear|null - the parametrized vocabulary
    test above only exercises `yes`; `unclear` is the value round 3's E cards write when the
    surviving quotes and holding summary do not settle under-thirty-days either way."""
    ps = ap.patches_for([_d(873, "under_thirty_days", "set", "unclear")],
                        {873: _rec(873, under_thirty_days=None)}, "mmaldo2")
    assert ("set", "under_thirty_days", "unclear") in [(p.op, p.field, p.new) for p in ps]


def test_keep_on_a_section_e_card_leaves_the_null_field_null_and_still_adjudicates():
    """A section-E card's field is null on the record (the quote gate erased it) - `keep`
    writes no value patch at all (the field the reviewer is "keeping" is the record's current,
    already-null value, not the card's `erased_value`), but the case still moves into the
    human-reviewed tier: a `review.notes` patch records the (null) value as confirmed, any
    `needs-review:<field>` flag it superseded is cleared, and `review.status` is set to
    human-adjudicated, exactly as `keep` does for any other field. If leaving the field
    genuinely empty is not the reviewer's intent, `set` (to the erased value or to something
    else the quotes support) is the decision that writes a value - `keep` never does."""
    rec = _rec(874, characterization=None)
    ps = ap.patches_for([_d(874, "characterization", "keep")], {874: rec}, "mmaldo2")
    ops = [(p.op, p.field, p.new) for p in ps]
    assert not any(op == "set" and f == "characterization" for op, f, _v in ops)
    assert ("set", "review.status", "human-adjudicated") in ops
    notes = [v for op, f, v in ops if op == "append" and f == "review.notes"]
    assert any("characterization None confirmed by the reviewer" in n for n in notes)


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


# --------------------------------------------------------------- section G: re-read conflicts

def test_a_section_g_keep_confirms_the_human_value_against_the_reread():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "keep",
                               "value": None, "note": ""}],
                             {70: {"polarity": "favorable"}}, "mmaldo2",
                             run_id="reread-round-1", cards=cards)
    notes = [p.new for p in patches if p.field == "review.notes"]
    assert any("confirmed by the reviewer" in n and "adverse" in n for n in notes)
    assert not [p for p in patches if p.op == "set" and p.field == "polarity"]
    assert any(p.field == "review.status" and p.new == "human-adjudicated" for p in patches)


def test_a_section_g_set_records_that_the_reviewer_revised_their_own_decision():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "set",
                               "value": "adverse", "note": ""}],
                             {70: {"polarity": "favorable"}}, "mmaldo2",
                             run_id="reread-round-1", cards=cards)
    note = next(p.new for p in patches if p.field == "review.notes")
    assert "revises their own earlier decision" in note
    assert "map-cycle-004-round-1" in note and "seq 900" in note and "adverse" in note
    value = next(p for p in patches if p.op == "set" and p.field == "polarity")
    assert value.new == "adverse" and value.basis.reviewer == "mmaldo2"


def test_a_section_g_card_refuses_adopt():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    with pytest.raises(ValueError, match="no checker value to adopt"):
        ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "adopt",
                         "value": None, "note": ""}],
                       {70: {"polarity": "favorable"}}, "mmaldo2", cards=cards)


def test_a_section_g_unsure_leaves_the_record_machine_free_of_a_status_change():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "unsure",
                               "value": None, "note": ""}],
                             {70: {"polarity": "favorable"}}, "mmaldo2", cards=cards)
    assert any(p.field == "review.flags" and p.new == "needs-review:polarity" for p in patches)
    assert not [p for p in patches if p.field == "review.status"]


G_RELEVANT = {**CONFLICT, "field": "relevant", "kind": "relevant_false",
              "human_value": True, "reread_value": False}


def _g_relevant_records():
    return {70: {"relevant": True, "polarity": "favorable",
                 "who_was_letting": "householder",
                 "review": {"status": "human-adjudicated",
                            "flags": ["needs-review:relevant"], "notes": []}}}


def test_a_section_g_relevant_card_takes_the_g_branch_not_the_relevance_overturn():
    """Final review, finding 2. `relevant` is the field of the most serious G card there is
    (the `relevant_false` kind), and the only meaningful decision on it is `set` False. It has
    to clear the `needs-review:relevant` flag the re-read raised - the overturn branch clears
    nothing, so this card would be re-queued for ever - and its note has to name the decision
    it supersedes. The overturn's own cascade still applies: a case out of the corpus carries
    no polarity or who_was_letting."""
    cards = {(70, "relevant"): {"case_id": 70, "section": "G", "decide_field": "relevant",
                                "conflict": G_RELEVANT}}
    patches = ap.patches_for([{"case_id": 70, "field": "relevant", "decision": "set",
                               "value": "false", "note": ""}],
                             _g_relevant_records(), "mmaldo2", run_id="reread-round-1",
                             cards=cards)
    sets = [(p.field, p.new) for p in patches if p.op == "set"]
    assert ("relevant", False) in sets and ("polarity", None) in sets
    assert ("who_was_letting", None) in sets
    assert ("review.flags", []) in sets                     # the re-read's flag is cleared
    assert ("review.status", "human-adjudicated") in sets
    notes = " ".join(p.new for p in patches if p.field == "review.notes")
    assert "revises their own earlier decision" in notes and "seq 900" in notes
    assert "supersedes the needs-review:relevant flag" in notes


def test_a_section_g_relevant_card_refuses_adopt_like_every_other_g_card():
    cards = {(70, "relevant"): {"case_id": 70, "section": "G", "decide_field": "relevant",
                                "conflict": G_RELEVANT}}
    with pytest.raises(ValueError, match="no checker value to adopt"):
        ap.patches_for([{"case_id": 70, "field": "relevant", "decision": "adopt",
                         "value": None, "note": ""}],
                       _g_relevant_records(), "mmaldo2", cards=cards,
                       checker={70: {"values": {"relevant": False}, "status": "ok"}})


def test_a_section_g_relevant_card_refuses_a_set_to_true():
    cards = {(70, "relevant"): {"case_id": 70, "section": "G", "decide_field": "relevant",
                                "conflict": G_RELEVANT}}
    with pytest.raises(ValueError, match="only be set to False"):
        ap.patches_for([{"case_id": 70, "field": "relevant", "decision": "set",
                         "value": "true", "note": ""}],
                       _g_relevant_records(), "mmaldo2", cards=cards)


def test_a_section_g_keep_clears_the_flag_the_reread_raised():
    """The other half of finding 1: nothing retires a G card except this flag going away."""
    records = {70: {"polarity": "favorable",
                    "review": {"status": "human-adjudicated",
                               "flags": ["needs-review:polarity"], "notes": []}}}
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "keep",
                               "value": None, "note": ""}], records, "mmaldo2", cards=cards)
    assert ("review.flags", []) in [(p.field, p.new) for p in patches if p.op == "set"]


def test_a_section_g_unsure_leaves_the_flag_standing():
    records = {70: {"polarity": "favorable",
                    "review": {"status": "human-adjudicated",
                               "flags": ["needs-review:polarity"], "notes": []}}}
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "unsure",
                               "value": None, "note": ""}], records, "mmaldo2", cards=cards)
    assert not [p for p in patches if p.op == "set" and p.field == "review.flags"]
    assert any(p.field == "review.flags" and p.op == "append" for p in patches)


def test_an_adopt_the_checker_never_answered_is_refused_not_written_as_a_null():
    """Finding 3. `.get(field)` on a missing checker entry becomes `set <field> None` - a real
    value patch nulling a field nobody decided."""
    with pytest.raises(ValueError, match="no entry for the case"):
        ap.patches_for([{"case_id": 704, "field": "polarity", "decision": "adopt",
                         "value": None, "note": ""}],
                       {704: {"polarity": "mixed"}}, "mmaldo2", checker={})
    with pytest.raises(ValueError, match="answered no polarity"):
        ap.patches_for([{"case_id": 704, "field": "polarity", "decision": "adopt",
                         "value": None, "note": ""}],
                       {704: {"polarity": "mixed"}}, "mmaldo2",
                       checker={704: {"values": {}, "status": "missing"}})


def test_the_queue_manifest_is_required_in_both_modes(tmp_path, monkeypatch):
    """Since section G the queue is what tells a G decision apart from an ordinary one, and it
    derives the --checker default; a saved page applied without it loses both silently."""
    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["apply_map_review.py", "--saved", str(tmp_path / "p.html")])
    with pytest.raises(SystemExit):
        ap.main()


def test_card_index_keys_on_case_and_field_so_two_g_cards_do_not_collide():
    doc = {"sections": {"G": [{"case_id": 70, "decide_field": "polarity", "section": "G"},
                              {"case_id": 70, "decide_field": "who_was_letting",
                               "section": "G"}]}}
    idx = ap.card_index(doc)
    assert set(idx) == {(70, "polarity"), (70, "who_was_letting")}


def test_the_page_and_the_export_show_the_conflict(tmp_path):
    queue = {"run_id": "cycles-001-003-reread", "cap": 250,
             "titles": {s: t for s, _k, t in SECTIONS},
             "sections": {s: [] for s, _k, _t in SECTIONS},
             "deferred": [], "fuzzy_auto_accepted": []}
    queue["sections"]["G"] = [{"case_id": 70, "section": "G", "reason": "reread_conflict",
                               "other_reasons": [], "decide_field": "polarity",
                               "cite": "1 X 1", "name": "A v B", "court": "c", "jur": "N.Y.",
                               "year": 1880, "values": {"polarity": "favorable"},
                               "holding_summary": "h", "quotes": [], "nulled_fields": [],
                               "extraction_status": "ok", "disagreements": [], "fuzzy": [],
                               "conflict": CONFLICT}]
    html, md, _n = mk.build_pages(queue, tmp_path / "page")
    text = html.read_text(encoding="utf-8")
    assert "Re-read conflicts with a human decision" in text and "reread_value" not in text
    # spec section 7: both bases on the card, not only the human one.
    assert "mmaldo2" in text and "map-cycle-004-round-1" in text        # human basis
    assert "claude-opus-5@claude-cli" in text                            # re-read basis: model
    assert "mapper-v3:f92016681314" in text        # re-read basis: prompt_version
    assert "cycles-001-003-reread" in text          # re-read basis: run_id
    cards = ec.cards_from_queue(queue, {})
    assert cards[0]["conflict"] == CONFLICT
    body = ec.markdown_for(cards, "cycles-001-003-reread")
    assert "Your earlier decision: polarity = favorable" in body
    assert "The mapper-v3 re-read reads it as: adverse" in body
    # spec section 7: the export shows the re-read's own basis beside the human basis.
    assert "mmaldo2" in body and "map-cycle-004-round-1" in body
    assert "claude-opus-5@claude-cli" in body
    assert "mapper-v3:f92016681314" in body
    assert "cycles-001-003-reread" in body


def test_every_queue_section_appears_in_both_the_html_and_the_js_sections_array(tmp_path):
    """The past defect this task was told to guard against: a section present in
    `corpus_engine.mapper.queue.SECTIONS` but absent from the page's own hardcoded JS
    `const SECTIONS = [...]` array renders nothing for that section, silently, with every
    other test in this file still green - because those other tests only check the section's
    TITLE text, which lives in the static HTML markup regardless of what the JS array lists.
    This walks the built page and asserts every section id shows up in both places, so a
    future section (H, say) cannot vanish the way section G almost did."""
    doc = _queue_doc()
    html_path, _md, _n = mk.build_pages(doc, tmp_path / "page", checker=CHECKER)
    html = html_path.read_text(encoding="utf-8")
    js_sections = html.split("const SECTIONS = [", 1)[1].split("];", 1)[0]
    for sec, key, _title in SECTIONS:
        assert f'id="sec-{sec}"' in html, f"no HTML section block for {sec!r}"
        assert f'id="cards-{sec}"' in html, f"no card container for {sec!r}"
        assert f"'{sec}'" in js_sections, f"{sec!r} missing from the JS SECTIONS array"
        assert f"'{key}'" in js_sections, f"{key!r} missing from the JS SECTIONS array"



# ------------------------------------------------- the T6 -> T7 -> apply seam (finding 11) ---

def test_a_reread_conflict_travels_from_the_reread_to_the_queue_to_the_ledger_and_retires(
        tmp_path):
    """Final review, finding 11. The one test that carries a real conflict the whole way:
    `reread_patches` raises it and flags the field, `select_queue` turns it into a section-G
    card, `patches_for` decides it and clears the flag, and the NEXT round - rebuilt from the
    same whole conflicts file, which is what Task 8 does - no longer asks it. The four
    task-scoped section-G tests all pass records with no review block at all, which is why
    findings 1 and 2 survived seven task reviews."""
    from corpus_engine.ledger import open_ledger as real_open_ledger
    from corpus_engine.ledger.types import Basis, Patch
    from corpus_engine.mapper.admit import AdmittedRecord, reread_patches

    manifest = json.loads((ROOT / "tests" / "fixtures" / "mapper-admit" /
                           "manifest.json").read_text(encoding="utf-8"))
    dom = load_domain()
    led = real_open_ledger(tmp_path / "ledger", domain=dom)
    seed = _rec(70, polarity="favorable")
    led.apply([Patch(70, "admit", "", seed, "seed",
                     Basis(model="m", prompt_version="mapper-v3:f92016681314", run_id="seed"),
                     cycle="cycle-001"),
               Patch(70, "set", "polarity", "favorable", "round 1",
                     Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1"))],
              note="seed")

    view = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    assert view.provenance(70)["polarity"] == "human"
    out = reread_patches([AdmittedRecord(70, "1860-1900|N.Y.", "b1", "key",
                                         {**seed, "polarity": "adverse"}, "")],
                         manifest=manifest, view=view)
    assert [c["field"] for c in out.conflicts] == ["polarity"]
    led2 = real_open_ledger(tmp_path / "ledger", domain=dom)
    led2.apply(out.patches, note="re-read")

    # ROUND 1: the conflict is a card, and the flag the re-read raised is what makes it one.
    view = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    assert "needs-review:polarity" in view.record(70)["review"]["flags"]
    queue = select_queue(view, "cycles-001-003-reread", manifest=_manifest(), cases=_Cases(),
                         conflicts=out.conflicts)
    assert [(c.section, c.case_id, c.decide_field) for c in queue.cards] == [("G", 70,
                                                                             "polarity")]

    patches = ap.patches_for([{"case_id": 70, "field": "polarity", "decision": "keep",
                               "value": None, "note": ""}],
                             view.state.records, dom.reviewer_default,
                             run_id="reread-round-1", cards=ap.card_index(queue.to_json()))
    real_open_ledger(tmp_path / "ledger", domain=dom).apply(patches, note="round 1")

    # ROUND 2: same conflicts file, and the decided card is gone.
    after = real_open_ledger(tmp_path / "ledger", domain=dom).view()
    assert after.record(70)["review"]["flags"] == []
    assert after.record(70)["polarity"] == "favorable"          # keep left it standing
    again = select_queue(after, "cycles-001-003-reread", manifest=_manifest(), cases=_Cases(),
                         conflicts=out.conflicts)
    assert again.cards == () and again.deferred == ()


def test_the_checker_unit_cap_counts_cases_not_cards(tmp_path):
    """Nit 13. `check_queue` plans one unit per DISTINCT case, and section G is the first round
    where one case can carry two cards - so a manifest field spelled `len(queue.cards)` is
    wrong for the first time."""
    from corpus_engine.mapper.queue import QueueCard, Queue
    from corpus_engine.reader.model import ModelPin

    rec = _rec(70)
    queue = Queue("cycles-001-003-reread",
                  (QueueCard(70, "G", "reread_conflict", (), rec, (), (),
                             conflict={**CONFLICT, "field": "polarity"}),
                   QueueCard(70, "G", "reread_conflict", (), rec, (), (),
                             conflict={**CONFLICT, "field": "who_was_letting"})), ())
    doc = queue.to_json()

    class _Reader:
        def read(self, plan):
            return type("O", (), {"records": [], "units": ()})()

    mk.run_check(doc, tmp_path / "checker.json", reader_factory=lambda: _Reader(),
                 codebook=None, checker_pin=ModelPin("codex-cli", "openai", "codex-cli"),
                 budget=None)
    assert doc["checker_path"]["unit_cap"] == 1                 # one case, two cards
