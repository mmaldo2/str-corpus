"""tools/explainer_snapshot.py: the explainer's figures at one pinned ledger seq, refused when
the inputs describe different ledger states (spec 2026-09-29 lawyer explainer, section 8)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import explainer_snapshot as es  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.ledger import Basis, Patch, open_ledger  # noqa: E402

AT = "2026-09-12T08:55:22"


def _rec(cid, year, *, relevant=True, pol="favorable", who="householder", jur="N.Y.", dur="nights"):
    return {"case_id": cid, "cite": f"{cid} X", "year": year, "jurisdiction": jur,
            "relevant": relevant, "polarity": pol, "who_was_letting": who,
            "duration_of_occupancy": dur, "characterization": "lodging",
            "holding_summary": "h", "quotes": [{"text": "q", "supports": "polarity"}],
            "extraction_status": "ok"}


def _ledger(tmp_path):
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    reader = Basis(model="m", prompt_version="mapper-v1", run_id="r")
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", reader, cycle="cycle-001"),
               Patch(2, "admit", "", _rec(2, 1900, who="non_resident_owner"), "v", reader, cycle="cycle-001"),
               Patch(3, "admit", "", _rec(3, 1900, relevant=False), "v", reader, cycle="cycle-001")],
              note="seed", at=AT)
    led.apply([Patch(1, "set", "review.status", "human-adjudicated", "confirmed", Basis(reviewer="u"))],
              note="review", at=AT)
    return led


def _library(tmp_path):
    path = tmp_path / "lib.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cases (case_id INTEGER, jurisdiction TEXT, decision_year INTEGER, "
                 "is_duplicate_of INTEGER)")
    conn.executemany("INSERT INTO cases VALUES (?,?,?,?)", [
        (1, "N.Y.", 1799, None), (2, "Cal.", 2019, None), (3, "U.S.", 1900, None), (4, "N.Y.", 1650, 1)])
    conn.execute("CREATE TABLE signals (case_id INTEGER)")
    conn.executemany("INSERT INTO signals VALUES (?)", [(1,), (1,), (2,), (3,), (4,)])
    conn.commit()
    return path, conn


def _evaluation(seq, rel=(1, 1), fav=(1, 1), hh=(1, 0)):
    c = lambda t: {"human_reviewed": t[0], "machine_only": t[1]}  # noqa: E731
    return {"ledger": {"reporting_seq": seq, "content_sha256": "ab" * 32,
                       "counts": {"relevant": c(rel), "favorable": c(fav), "favorable_householder": c(hh)}},
            "gold_recovery": {
                "union": {"entries": 65, "resolved": 36, "read": 28, "relevant": 10, "relevant_human": 8},
                "misses": ([{"lost_at": "unsignaled"}] * 8 + [{"lost_at": "reader-negative"}] * 17
                           + [{"lost_at": "withdrawn"}]),
                "unresolved": [{"cite": "x"}] * 29},
            "coverage": {"bands": [{"unread_cases": 14000}, {"unread_cases": 255}],
                         "scenarios": [{"estimated_relevant": 817}, {"estimated_relevant": 409},
                                       {"estimated_relevant": 1568}]}}


def _sample(seq, frame=(2,), picks=(2,)):
    """The fixture ledger's audit frame (relevant, not reviewed) is [2] at its head and [1, 2] before the
    review patch; `frame` must match the ledger at `seq` wherever the snapshot tool recomputes it."""
    import hashlib
    return {"drawn_at": "2026-09-12T17:09:26+00:00", "ledger_head_seq": seq, "frame_size": len(frame),
            "frame_sha256": hashlib.sha256(chr(10).join(map(str, frame)).encode("utf-8")).hexdigest(),
            "seed": 20260912, "n": len(picks), "records": [{"case_id": c} for c in picks]}


def test_ledger_figures_counts_reads_and_tiers_at_the_pinned_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    assert f["as_of"] == head and f["date"] == "2026-09-12"
    assert f["opinions_read"] == 3                       # every admitted case, relevant or not
    assert f["relevant"] == {"human_reviewed": 1, "machine_only": 1, "total": 2}
    assert f["favorable"] == {"human_reviewed": 1, "machine_only": 1, "total": 2}
    assert f["favorable_householder"] == {"human_reviewed": 1, "machine_only": 0, "total": 1}


def test_ledger_figures_refuses_a_seq_beyond_the_ledger_head(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="head"):
        es.ledger_figures(led.view(as_of=head + 10), head + 10)


def test_library_figures_separate_the_searched_jurisdictions_from_the_rest(tmp_path):
    _, conn = _library(tmp_path)
    f = es.library_figures(conn, ("N.Y.", "Cal."))
    assert (f["canonical_total"], f["in_scope"], f["outside_scope"]) == (3, 2, 1)   # duplicate excluded
    assert f["jurisdictions"] == 2
    assert (f["first_year"], f["last_year"]) == ("1799", "2019")                    # strings, not counts


def test_display_helpers():
    assert es.millions(1_795_165) == "about 1.8 million"
    assert es.long_date("2026-09-12") == "September 12, 2026"


def test_benchmark_figures_break_down_every_loss():
    f = es.benchmark_figures(_evaluation(4))
    assert (f["entries"], f["resolved"], f["read"], f["kept"], f["kept_human"], f["unresolved"]) == (65, 36, 28, 10, 8, 29)
    assert f["lost"] == {"unsignaled": 8, "reader_negative": 17, "withdrawn": 1, "other": 0, "total": 26}


def test_benchmark_figures_refuse_losses_that_do_not_add_up():
    ev = _evaluation(4)
    ev["gold_recovery"]["misses"].pop()
    with pytest.raises(es.SnapshotError, match="26"):
        es.benchmark_figures(ev)


def test_tail_figures_sum_unread_and_span_the_scenarios():
    assert es.tail_figures(_evaluation(4)) == {"unread": 14255, "low": 409, "high": 1568}


def test_audit_figures_report_the_frozen_draw_with_the_seed_as_text():
    f = es.audit_figures(_sample(83531), as_of=83531)
    assert f == {"n": 1, "frame_size": 1, "seed": "20260912", "drawn_seq": 83531,
                 "drawn_date": "2026-09-12", "status": "drawn, not yet read"}


def test_consistency_refuses_an_evaluation_from_another_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    with pytest.raises(es.SnapshotError, match="evaluation"):
        es.check_consistency(head, f, _evaluation(head - 1), _sample(head))


def test_consistency_refuses_counts_that_disagree_with_the_evaluation(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    with pytest.raises(es.SnapshotError, match="relevant"):
        es.check_consistency(head, f, _evaluation(head, rel=(2, 0)), _sample(head))


def test_consistency_accepts_an_earlier_sample_and_refuses_a_later_one(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    es.check_consistency(head, f, _evaluation(head), _sample(head - 2))     # Checkpoint 2 shape
    with pytest.raises(es.SnapshotError, match="sample"):
        es.check_consistency(head, f, _evaluation(head), _sample(head + 1))


def test_cli_snapshot_writes_utf8_lf_json(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head)), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head)), encoding="utf-8")
    out = tmp_path / "explainer" / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head), "--label", "Checkpoint 1", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db),
                  "--out", str(out)])
    assert rc == 0
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    snap = json.loads(raw.decode("utf-8"))
    assert snap["snapshot"]["label"] == "Checkpoint 1" and snap["snapshot"]["as_of"] == head
    assert snap["snapshot"]["date_display"] == "September 12, 2026"
    assert snap["ledger"]["relevant"]["total"] == 2 and snap["tail"]["unread"] == 14255
    assert snap["inputs"]["ledger_content_sha256"] == "ab" * 32
    assert len(snap["inputs"]["evaluation_sha256"]) == 64


def test_cli_snapshot_refuses_and_writes_nothing_on_a_mismatch(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head - 1)), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head)), encoding="utf-8")
    out = tmp_path / "explainer" / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head), "--label", "Checkpoint 1", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db),
                  "--out", str(out)])
    assert rc == 2 and not out.exists()


SNAP = {"ledger": {"relevant": {"total": 4351, "human_reviewed": 1509}, "opinions_read": 24643},
        "library": {"first_year": "1671", "in_scope_display": "about 1.8 million"},
        "audit": {"seed": "20260912"}, "tail": {"ratio": 0.5}, "flag": {"on": True}}


def test_render_substitutes_counts_grouped_and_text_verbatim():
    out = es.render("At least {{snap:ledger.relevant.total}} cases since {{snap:library.first_year}}, "
                    "seed {{snap:audit.seed}}, {{snap:library.in_scope_display}}.", SNAP)
    assert out == "At least 4,351 cases since 1671, seed 20260912, about 1.8 million."


def test_render_fails_listing_every_unknown_key():
    with pytest.raises(es.SnapshotError) as e:
        es.render("{{snap:ledger.relevent.total}} and {{snap:nope}} and {{snap:nope}}", SNAP)
    assert str(e.value) == "unknown snapshot keys: ledger.relevent.total, nope"


def test_render_refuses_floats_booleans_and_whole_blocks():
    for path in ("tail.ratio", "flag.on", "ledger.relevant"):
        with pytest.raises(es.SnapshotError, match=path):
            es.render("{{snap:%s}}" % path, SNAP)


def test_lint_flags_dollar_amounts_but_honours_the_historical_price_marker():
    assert es.lint("It cost $0.02 per million.", template=False) == ["line 1: dollar amount"]
    assert es.lint("rooms at $ 8.50 a week", template=False) == ["line 1: dollar amount"]
    assert es.lint('"$8.50 a week" <!-- lint-allow: historical price -->', template=False) == []


def test_lint_flags_retired_pages_in_any_case():
    probs = es.lint("See reports/right-to-let-guide.html\nand the ATTORNEY-REPORT page", template=False)
    assert probs == ["line 1: reference to retired page 'right-to-let-guide'",
                     "line 2: reference to retired page 'attorney-report'"]


def test_lint_template_flags_literal_grouped_numbers_outside_placeholders():
    assert es.lint("We read 24,643 opinions.", template=True) == [
        "line 1: literal grouped number '24,643' (use a {{snap:...}} placeholder)"]
    assert es.lint("We read {{snap:ledger.opinions_read}} opinions in 1860.", template=True) == []


def test_lint_rendered_flags_leftover_placeholders():
    assert es.lint("x {{snap:a}} y", template=False) == ["line 1: unrendered placeholder"]


def test_cli_render_lints_both_sides_and_refuses_without_writing(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text("Read {{snap:ledger.opinions_read}} — ok\n", encoding="utf-8")
    bad.write_text("Read 24,643 opinions\n", encoding="utf-8")
    out = tmp_path / "out.md"
    assert es.main(["render", "--template", str(good), "--snapshot", str(snap), "--out", str(out)]) == 0
    assert out.read_bytes().decode("utf-8") == "Read 24,643 — ok\n"
    out2 = tmp_path / "out2.md"
    assert es.main(["render", "--template", str(bad), "--snapshot", str(snap), "--out", str(out2)]) == 1
    assert not out2.exists()
    assert es.main(["lint", "--in", str(out)]) == 0
    assert es.main(["lint", "--in", str(bad), "--template"]) == 1


def test_ledger_figures_count_adverse_and_mixed_opinions(tmp_path):
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    reader = Basis(model="m", prompt_version="mapper-v1", run_id="r")
    led.apply([Patch(1, "admit", "", _rec(1, 1850, pol="adverse"), "v", reader, cycle="cycle-001"),
               Patch(2, "admit", "", _rec(2, 1900, pol="mixed"), "v", reader, cycle="cycle-001"),
               Patch(3, "admit", "", _rec(3, 1900, pol="adverse", relevant=False), "v", reader, cycle="cycle-001")],
              note="seed", at=AT)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    assert f["adverse"] == {"human_reviewed": 0, "machine_only": 1, "total": 1}   # the irrelevant read is not counted
    assert f["mixed"] == {"human_reviewed": 0, "machine_only": 1, "total": 1}


def test_lint_template_ignores_commas_inside_markup_but_not_in_text():
    assert es.lint('<link href="css2?family=X:ital,wght@0,400;1,400">', template=True) == []
    assert es.lint('<polygon points="44,154 36,150 40,160"></polygon>', template=True) == []
    assert es.lint('<p class="n">We read 24,643 opinions</p>', template=True) == [
        "line 1: literal grouped number '24,643' (use a {{snap:...}} placeholder)"]



def test_lint_template_flags_grouped_numbers_followed_by_commas():
    assert es.lint("We found 4,351, and then more.", template=True) == [
        "line 1: literal grouped number '4,351' (use a {{snap:...}} placeholder)"]
    probs = es.lint("Counts were 4,351, 2,000, and 1,200.", template=True)
    assert [p.split("'")[1] for p in probs] == ["4,351", "2,000", "1,200"]
    assert es.lint("Decided Sept 12, 2026; odd tokens 1,2345 and 1,234,5678 stay quiet.", template=True) == []


def test_audit_status_is_only_asserted_at_the_seq_the_sample_was_drawn():
    assert es.audit_figures(_sample(83531), as_of=83531)["status"] == "drawn, not yet read"
    later = es.audit_figures(_sample(83531), as_of=90000)
    assert "status" not in later and later["drawn_seq"] == 83531     # a template asking for it fails loudly


def test_cli_snapshot_at_an_earlier_seq_reproduces_that_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of                              # the review patch is the head
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head - 1, rel=(0, 2), fav=(0, 2), hh=(0, 1))), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head - 1, frame=(1, 2), picks=(2,))), encoding="utf-8")
    out = tmp_path / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head - 1), "--label", "Checkpoint 1", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db), "--out", str(out)])
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0 and snap["snapshot"]["as_of"] == head - 1
    assert snap["ledger"]["relevant"] == {"human_reviewed": 0, "machine_only": 2, "total": 2}   # before the review


def test_cli_snapshot_refuses_a_later_sample_and_a_seq_beyond_the_head(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    for as_of, sample_seq in ((head, head + 1), (head + 5, head + 5)):
        ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
        ev.write_text(json.dumps(_evaluation(as_of)), encoding="utf-8")
        sm.write_text(json.dumps(_sample(sample_seq)), encoding="utf-8")
        out = tmp_path / f"snapshot-{as_of}-{sample_seq}.json"
        rc = es.main(["snapshot", "--as-of", str(as_of), "--label", "Checkpoint 1", "--evaluation", str(ev),
                      "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db), "--out", str(out)])
        assert rc == 2 and not out.exists()


def test_cli_render_refuses_an_unknown_placeholder_without_writing(tmp_path):
    snap, tpl, out = tmp_path / "snapshot.json", tmp_path / "t.md", tmp_path / "out.md"
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    tpl.write_text("At least {{snap:ledger.relevent.total}} cases", encoding="utf-8")
    assert es.main(["render", "--template", str(tpl), "--snapshot", str(snap), "--out", str(out)]) == 1
    assert not out.exists()



def test_library_figures_count_the_opinions_the_searches_flagged(tmp_path):
    _, conn = _library(tmp_path)
    assert es.library_figures(conn, ("N.Y.", "Cal."))["flagged"] == 2     # distinct, canonical, in scope


def test_ledger_figures_include_the_tradition_grid_without_the_unsearched_region(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    m = es.ledger_figures(led.view(as_of=head), head)["matrix"]
    assert m["eras"][0] == "pre-1860" and m["durations"] == ["nights", "weeks", "months", "unclear"]
    assert [r["name"] for r in m["regions"]] == ["northeast", "mid-atlantic", "midwest", "south", "west"]
    assert m["regions"][0]["jurisdictions"] == ["Conn.", "Mass.", "N.J.", "N.Y.", "Pa."]
    assert m["tiers"] == ["householder", "owner", "commercial", "unclear"]
    cells = {tuple(c[:4]): c[4:] for c in m["cells"]}
    assert cells[("pre-1860", "northeast", "householder", "nights")] == [1, 0]     # case 1 (1850), reviewed
    assert cells[("1900-1930", "northeast", "owner", "nights")] == [0, 1]           # case 2 (1900), machine-only
    assert cells[("pre-1860", "west", "householder", "weeks")] == [0, 0]            # zero-filled
    assert not any(c[1] == "federal" for c in m["cells"])


def test_audit_positions_place_each_pick_in_the_recomputed_frame(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    assert es.audit_positions(led.view(as_of=head - 1), _sample(head - 1, frame=(1, 2), picks=(2,))) == [1]
    assert es.audit_positions(led.view(as_of=head), _sample(head)) == [0]


def test_audit_positions_refuse_a_frame_that_does_not_match_the_manifest(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="frame"):
        es.audit_positions(led.view(as_of=head), _sample(head, frame=(1, 2), picks=(2,)))   # head frame is [2]
    with pytest.raises(es.SnapshotError, match="not in the frame"):
        es.audit_positions(led.view(as_of=head), _sample(head, frame=(2,), picks=(1,)))


def test_render_inlines_json_from_the_snapshot_and_named_data_safely():
    data = {"examples": {"map": {"items": [{"t": "a </script> b"}]}}}
    out = es.render("{{json:snap.ledger.relevant}}|{{json:examples.map}}", SNAP, data=data)
    assert out.startswith('{"total":4351,"human_reviewed":1509}|')
    assert r"<\/script>" in out and "</script> b" not in out


def test_render_json_fails_on_an_unknown_source_or_key():
    with pytest.raises(es.SnapshotError, match="examples.nope"):
        es.render("{{json:examples.nope}}", SNAP, data={"examples": {}})
    with pytest.raises(es.SnapshotError, match="other.x"):
        es.render("{{json:other.x}}", SNAP)


def test_cli_render_takes_named_data_files(tmp_path):
    snap, ex, tpl, out = (tmp_path / n for n in ("snapshot.json", "examples.json", "t.html", "out.html"))
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    ex.write_text(json.dumps({"map": {"n": 18}}), encoding="utf-8")
    tpl.write_text('<script type="application/json">{{json:examples.map}}</script>', encoding="utf-8")
    assert es.main(["render", "--template", str(tpl), "--snapshot", str(snap), "--data", f"examples={ex}",
                    "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == '<script type="application/json">{"n":18}</script>'



def _one_record_ledger(tmp_path, rec):
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    led.apply([Patch(rec["case_id"], "admit", "", rec, "v", Basis(model="m", prompt_version="mapper-v1", run_id="r"),
                     cycle="cycle-001")], note="seed", at=AT)
    return led


def test_the_grid_refuses_to_drop_a_favorable_opinion_outside_the_searched_regions(tmp_path):
    led = _one_record_ledger(tmp_path, _rec(9, 1850, jur="U.S."))          # federal: mapped, never searched
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="grid"):
        es.ledger_figures(led.view(as_of=head), head)


def test_the_grid_refuses_a_cell_outside_its_declared_axes(tmp_path):
    led = _one_record_ledger(tmp_path, _rec(9, 1850, dur="years"))          # a duration no filter offers
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="axes"):
        es.ledger_figures(led.view(as_of=head), head)


def test_cli_snapshot_at_checkpoint_2_places_an_earlier_draw_and_asserts_no_status(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head)), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head - 1, frame=(1, 2), picks=(2,))), encoding="utf-8")   # drawn before the review
    out = tmp_path / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head), "--label", "Checkpoint 2", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db), "--out", str(out)])
    audit = json.loads(out.read_text(encoding="utf-8"))["audit"]
    assert rc == 0 and audit["positions"] == [1] and "status" not in audit


def test_audit_positions_refuse_a_same_size_frame_with_other_members(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="frame"):
        es.audit_positions(led.view(as_of=head), _sample(head, frame=(1,), picks=(2,)))   # real frame [2]


def test_audit_positions_refuse_a_view_at_another_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="needs the ledger"):
        es.audit_positions(led.view(as_of=head), _sample(head - 1, frame=(1, 2), picks=(2,)))
