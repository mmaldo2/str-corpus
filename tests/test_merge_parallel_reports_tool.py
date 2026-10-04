"""tools/merge_parallel_reports.py over a temporary store and ledger."""
import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("merge_parallel_reports",
                                               ROOT / "tools" / "merge_parallel_reports.py")
mpr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mpr)
BODY = " ".join(f"word{i}" for i in range(400))


def _row(c5, label, c3=None, **kw):
    return {"c5": c5, "c3": c5 if c3 is None else c3, "label": label,
            "date_ok": True, "size_ok": True, "long_enough": True, **kw}


def test_threshold_is_the_lowest_bound_above_every_pair_not_labelled_same():
    rows = [_row(0.95, "same"), _row(0.81, "same"), _row(0.66, "same"),
            _row(0.52, "different"), _row(0.31, "different"), _row(0.58, "unsure")]
    ch = mpr.choose_threshold(rows)
    assert ch["measure"] == "c5" and ch["threshold"] == 0.6      # the 0.58 unsure counts against
    assert ch["merged_same"] == 3 and ch["method"] == "parallel-v1:w5:0.6"


def test_no_threshold_when_a_different_pair_scores_at_the_top():
    assert mpr.choose_threshold([_row(0.97, "different"), _row(0.99, "same")]) is None


def test_the_other_measure_wins_when_it_separates_more_same_pairs():
    rows = [_row(0.9, "same", c3=0.9), _row(0.7, "same", c3=0.85), _row(0.75, "different", c3=0.4)]
    ch = mpr.choose_threshold(rows)
    assert (ch["measure"], ch["threshold"], ch["merged_same"]) == ("c3", 0.45, 2)


def test_the_calibration_sample_takes_only_guarded_pairs_per_band():
    rows = [_row(0.25 + 0.1 * (i % 8), None, loser=i) for i in range(80)]
    rows.append(_row(0.95, None, loser=999, date_ok=False))
    s = mpr.calibration_sample(rows, per_band=3, seed=1)
    assert len(s) == 24 and 999 not in {r["loser"] for r in s}
    assert s == mpr.calibration_sample(rows, per_band=3, seed=1)


def test_threshold_joins_blind_labels_back_to_scores_and_refuses_gaps(tmp_path):
    out = tmp_path / "pr"
    out.mkdir()
    sample = [_row(s, None, pair_id=i, winner=10 + i, loser=20 + i)
              for i, s in enumerate((0.9, 0.7, 0.4))]
    (out / "calibration-sample.json").write_text(json.dumps(sample), encoding="utf-8")
    labels = [{"pair_id": 0, "label": "same"}, {"pair_id": 1, "label": "same"},
              {"pair_id": 2, "label": None}]
    (out / "calibration-labels-part1.json").write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(SystemExit, match="carry no label"):
        mpr.main(["--out-dir", str(out), "threshold"])
    labels[2]["label"] = "different"
    (out / "calibration-labels-part1.json").write_text(json.dumps(labels), encoding="utf-8")
    assert mpr.main(["--out-dir", str(out), "threshold"]) == 0
    ch = json.loads((out / "calibration.json").read_text(encoding="utf-8"))["choice"]
    assert (ch["measure"], ch["threshold"], ch["merged_same"]) == ("c5", 0.45, 2)


def _store(tmp_path) -> Path:
    db = tmp_path / "c.db"
    conn = store.connect(db)
    store.ensure_schema(conn)

    def case(cid, reporter, *, official=False, text=BODY, name="Smith v. Jones"):
        cite = f"{cid} {reporter} 1"
        conn.execute("""INSERT INTO cases (case_id, name_abbreviation, cite, court, jurisdiction,
                        decision_date, decision_year, era_partition, reporter, norm_text, raw_text)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (cid, name, cite, "New York Supreme Court", "N.Y.", "1908-04", 1908,
                      "1900-1930", reporter, text, text))
        conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                     (cid, cite, cite.lower(), "official" if official else "parallel"))
    case(1, "misc", official=True)
    case(2, "nys", text="Syllabus by the reporter. " + BODY)
    case(3, "misc", official=True, name="Brown v. Green")
    case(4, "nys", name="Brown v. Green")
    conn.commit()
    conn.close()
    return db


def _rec(cid):
    return {"case_id": cid, "cite": f"{cid} X", "year": 1908, "jurisdiction": "N.Y.",
            "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
            "duration_of_occupancy": "nights", "characterization": "lodging",
            "holding_summary": "h", "extraction_status": "ok",
            "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified"}]}


def _duplicates(db) -> dict:
    c = sqlite3.connect(db)
    try:
        return dict(c.execute("SELECT case_id, is_duplicate_of FROM cases "
                              "WHERE is_duplicate_of IS NOT NULL"))
    finally:
        c.close()


def test_score_sample_apply_reconcile_undo_end_to_end(tmp_path, capsys):
    db, ledger, out = _store(tmp_path), tmp_path / "ledger", tmp_path / "pr"
    open_ledger(ledger, domain=load_domain()).apply(
        [Patch(c, "admit", "", _rec(c), "v", Basis(model="m", prompt_version="v", run_id="r"),
               cycle="cycle-004") for c in (2, 3, 4)], note="seed")
    common = ["--db", str(db), "--ledger", str(ledger), "--out-dir", str(out)]

    assert mpr.main(common + ["score"]) == 0
    rows = [json.loads(l) for l in (out / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(r["winner"], r["loser"]) for r in rows} == {(2, 1), (3, 4)}   # a ledger copy beats official

    assert mpr.main(common + ["sample", "--per-band", "1", "--parts", "2"]) == 0
    md = (out / "calibration-pairs-part1.md").read_text(encoding="utf-8")
    assert "## pair 0" in md and "c5" not in md                           # the readers are blind to scores
    assert b"\r\n" not in (out / "calibration-pairs-part1.md").read_bytes()

    (out / "calibration.json").write_text(json.dumps(
        {"choice": {"measure": "c5", "threshold": 0.6, "method": "parallel-v1:w5:0.6"}}), encoding="utf-8")
    capsys.readouterr()
    assert mpr.main(common + ["apply", "--dry-run"]) == 0
    assert "2 merges" in capsys.readouterr().out and _duplicates(db) == {}
    assert mpr.main(common + ["apply"]) == 0
    assert _duplicates(db) == {1: 2, 4: 3}
    merges = [json.loads(l) for l in (out / "merges.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [m["loser"] for m in merges] == [1, 4]

    capsys.readouterr()
    assert mpr.main(common + ["reconcile", "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "relevant: 0+3 -> 0+2" in text and "1 duplicate_of patches" in text
    assert b"\r\n" not in (out / "reconcile-for-user.json").read_bytes()
    assert open_ledger(ledger, domain=load_domain()).view().record(4).get("duplicate_of") is None
    assert mpr.main(common + ["reconcile"]) == 0
    v = open_ledger(ledger, domain=load_domain()).view()
    assert v.record(4)["duplicate_of"] == 3 and v.counts().total.machine_only == 2

    assert mpr.main(common + ["undo", "--method", "parallel-v1:w5:0.6"]) == 0
    assert _duplicates(db) == {}


def test_apply_merges_nothing_outside_the_sampled_region(tmp_path, capsys):
    out = tmp_path / "pr"
    out.mkdir()
    rows = [dict(_row(0.9, None, c3=0.95), winner=1, loser=2, jurisdiction="N.Y.", era="1900-1930"),
            dict(_row(0.1, None, c3=0.95), winner=3, loser=4, jurisdiction="N.Y.", era="1900-1930")]
    (out / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (out / "calibration.json").write_text(json.dumps(
        {"choice": {"measure": "c3", "threshold": 0.5, "method": "parallel-v1:w3:0.5"}}), encoding="utf-8")
    assert mpr.main(["--out-dir", str(out), "apply", "--dry-run"]) == 0
    assert "1 merges at c3 >= 0.5" in capsys.readouterr().out
