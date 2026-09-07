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
