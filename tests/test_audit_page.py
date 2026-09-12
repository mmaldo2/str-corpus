"""The audit page: blind until locked, reveal after, revisions keep the initial answer."""
import json
import re
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_map_review as mmr


def _queue():
    return {"run_id": "audit-cycle-004", "cap": 2, "titles": {"H": "Audit sample"}, "deferred": [],
            "sections": {"H": [{"case_id": 9, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9",
                                "name": "A v. B", "court": "Ct.", "jur": "N.Y.", "year": 1900},
                               {"case_id": 10, "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "10 A. 10",
                                "name": "C v. D", "court": "Ct.", "jur": "N.Y.", "year": 1901}]}}


def _readers():
    e = lambda cid, f, v, n: {"case_id": cid, "field": f, "decision": "set", "value": v, "note": n}
    claude = [e(9, "relevant", True, "cn1"), e(9, "polarity", "adverse", "cn2"), e(9, "who_was_letting", "householder", "cn3"),
              e(10, "relevant", False, "cn4")]
    astra = [e(9, "relevant", True, "an1"), e(9, "polarity", "favorable", "an2"), e(9, "who_was_letting", "householder", "an3"),
             e(10, "relevant", False, "an4")]
    return claude, astra


def test_page_carries_opinions_and_reader_answers_but_no_draw_time_values(tmp_path):
    claude, astra = _readers()
    html_path, _ = mmr.build_audit_page(_queue(), tmp_path / "audit", opinions={9: "she let the room", 10: "a store lease"},
                                        claude=claude, astra=astra, checker={"9": {"values": {"polarity": "adverse"}}})
    html = html_path.read_text(encoding="utf-8")
    doc = json.loads(re.search(r"const DOC = (.*?);\n", html).group(1))
    assert [c["case_id"] for c in doc["cards"]] == [9, 10] and doc["cards"][0]["opinion"] == "she let the room"
    assert doc["readers"]["9"]["claude"][1]["value"] == "adverse" and doc["readers"]["9"]["checker"]["polarity"] == "adverse"
    assert "draw_time" not in html and "record" not in doc
    for s in ("name=\"rel-", "name=\"pol-", "name=\"who-", "Lock", "Cannot read this opinion", "Revise", "class=\"reveal\""):
        assert s in html
    assert 'id="review-state">[]</script>' in html


def test_read_audit_state_returns_locked_entries_and_refuses_unlocked_ones(tmp_path):
    claude, astra = _readers()
    html_path, _ = mmr.build_audit_page(_queue(), tmp_path / "audit", opinions={9: "x", 10: "y"}, claude=claude, astra=astra, checker={})
    html = html_path.read_text(encoding="utf-8")
    state = [{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "initial_value": True, "locked_at": "t", "revised_reason": None, "note": ""},
             {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "initial_value": "favorable", "locked_at": "t", "revised_reason": "the note", "note": ""},
             {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "householder", "initial_value": "householder", "locked_at": "t", "revised_reason": None, "note": ""}]
    saved = html.replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps(state) + '</script>')
    got = mmr.read_audit_state(saved)
    assert [(d["field"], d["value"], d["initial_value"]) for d in got] == [("relevant", True, True), ("polarity", "adverse", "favorable"), ("who_was_letting", "householder", "householder")]
    bad = html.replace('id="review-state">[]</script>', 'id="review-state">' + json.dumps([dict(state[0], locked_at=None)]) + '</script>')
    with pytest.raises(ValueError, match="not locked"):
        mmr.read_audit_state(bad)


def test_main_audit_builds_the_page_from_the_queue_dir_opinions(tmp_path):
    claude, astra = _readers()
    queue_path = tmp_path / "audit-queue.json"
    queue_path.write_text(json.dumps(_queue()), encoding="utf-8")
    opinions_dir = tmp_path / "opinions"
    opinions_dir.mkdir()
    (opinions_dir / "9.txt").write_text("she let the room", encoding="utf-8")
    (opinions_dir / "10.txt").write_text("a store lease", encoding="utf-8")
    claude_path = tmp_path / "claude.json"
    claude_path.write_text(json.dumps(claude), encoding="utf-8")
    astra_path = tmp_path / "astra.json"
    astra_path.write_text(json.dumps(astra), encoding="utf-8")
    out_stem = tmp_path / "page"

    assert mmr.main(["--audit", "--queue", str(queue_path), "--claude", str(claude_path),
                     "--astra", str(astra_path), "--out-stem", str(out_stem)]) == 0
    html_path = Path(str(out_stem) + ".html")
    assert html_path.exists()
    doc = json.loads(re.search(r"const DOC = (.*?);\n",
                               html_path.read_text(encoding="utf-8")).group(1))
    assert {c["case_id"]: c["opinion"] for c in doc["cards"]} == {
        9: "she let the room", 10: "a store lease"}

    with pytest.raises(SystemExit):
        mmr.main(["--audit", "--queue", str(queue_path), "--astra", str(astra_path),
                 "--out-stem", str(out_stem)])
