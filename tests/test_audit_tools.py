"""The audit draw, the blind card export, and the first-pass tool's audit mode."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import draw_audit_sample as das
import export_review_cards as erc
import first_pass_codex as fp
from corpus_engine.reader.model import Response


class _View:
    def __init__(self, records, reviewed=()):
        self.state = type("S", (), {})(); self.state.records = records; self.state.order = sorted(records)
        self._r = set(reviewed)
    def reviewed(self, cid): return cid in self._r


def _rec(cid, **o):
    r = {"case_id": cid, "relevant": True, "polarity": "favorable", "who_was_letting": "householder",
         "characterization": "lodging", "under_thirty_days": None, "owner_freedom_characterization": None,
         "restriction_nature": None, "duration_of_occupancy": "weeks", "quotes": [], "holding_summary": "h",
         "cite": f"{cid} A. 1", "name": "A v. B", "court": "Ct.", "jurisdiction": "N.Y.", "year": 1900,
         "review": {"basis": {"run_id": "run-a", "prompt_version": "mapper-v3"}}}
    r.update(o); return r


def _draw(seed=7, n=3):
    records = {i: _rec(i) for i in range(1, 11)}
    records[5]["relevant"] = False
    view = _View(records, reviewed={6})
    texts = {i: f"opinion {i}" for i in records}
    return das.draw(view, seed=seed, n=n, texts=texts, scores={i: 0.5 for i in records},
                    cells={i: "1900-1930|N.Y." for i in records}, head_seq=100, content_sha256="c" * 64,
                    tool_revision="g", brief_sha256="b", drawn_at="2026-09-12T00:00:00Z")


def test_draw_is_deterministic_and_excludes_irrelevant_and_reviewed_records():
    m1, q1 = _draw(); m2, _ = _draw()
    assert m1["records"] == m2["records"] and m1["frame_size"] == 8          # 10 minus 5 (irrelevant) minus 6 (reviewed)
    ids = [r["case_id"] for r in m1["records"]]
    assert len(ids) == 3 and 5 not in ids and 6 not in ids
    assert m1["seed"] == 7 and m1["method"] == "random.Random(seed).sample" and len(m1["frame_sha256"]) == 64
    r0 = m1["records"][0]
    assert r0["record"]["polarity"] == "favorable" and r0["reader_run_id"] == "run-a" and r0["prompt_version"] == "mapper-v3"
    assert r0["band"] == "0.50-0.55" and len(r0["opinion_sha256"]) == 64
    card = q1["sections"]["H"][0]
    assert q1["run_id"] == "audit-cycle-004" and card["decide_fields"] == ["relevant", "polarity", "who_was_letting"]
    assert "values" not in card and "quotes" not in card and "holding_summary" not in card and card["cite"]


def test_draw_refuses_n_larger_than_the_frame():
    with pytest.raises(ValueError, match="frame has 8"):
        _draw(n=9)


def test_blind_markdown_carries_only_identity_and_opinion():
    card = {"case_id": 1, "section": "H", "section_title": "Audit sample", "cite": "1 A. 1", "name": "A v. B",
            "court": "Ct.", "jurisdiction": "N.Y.", "year": 1900, "decide_fields": ["relevant", "polarity", "who_was_letting"],
            "courtlistener_url": "https://www.courtlistener.com/?q=x", "opinion_text": "she let the room",
            "reader": {"polarity": "favorable"}, "checker": {"polarity": "adverse"}, "quotes": [{"text": "q"}],
            "holding_summary": "SECRET", "decide_field": "polarity"}
    md = erc.markdown_for([card], "audit-cycle-004", audit=True)
    assert "1 A. 1" in md and "she let the room" in md and "Decide: **relevant, polarity, who_was_letting**" in md
    for leak in ("favorable", "adverse", "SECRET", "Reader:", "Checker:", "Quotes"):
        assert leak not in md


def _card():
    return {"case_id": 9, "section": "H", "decide_fields": ["relevant", "polarity", "who_was_letting"], "cite": "9 A. 9",
            "name": "n", "court": "c", "jurisdiction": "j", "year": 1, "courtlistener_url": "u", "opinion_text": "t", "section_title": "H"}


def test_audit_parse_requires_three_entries_or_one_withdrawal_or_one_unresolved():
    ok = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": "a"},
                     {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "note": "b"},
                     {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "unclear", "note": "c"}])
    got = fp.parse_decisions_audit(ok, _card())
    assert [(d["field"], d["value"]) for d in got] == [("relevant", True), ("polarity", "adverse"), ("who_was_letting", "unclear")]
    wd = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": False, "note": "not letting"}])
    assert fp.parse_decisions_audit(wd, _card()) == [{"case_id": 9, "field": "relevant", "decision": "set", "value": False, "note": "not letting"}]
    un = json.dumps([{"case_id": 9, "field": "relevant", "decision": "unresolved", "note": "garbled"}])
    assert fp.parse_decisions_audit(un, _card())[0]["decision"] == "unresolved"
    with pytest.raises(ValueError, match="three entries"):
        fp.parse_decisions_audit(json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": ""}]), _card())
    with pytest.raises(ValueError, match="duplicate"):
        fp.parse_decisions_audit(json.dumps(json.loads(ok)[:2] + [json.loads(ok)[1]]), _card())
    with pytest.raises(ValueError, match="keep"):
        fp.parse_decisions_audit(json.dumps([dict(json.loads(ok)[0], decision="keep")] + json.loads(ok)[1:]), _card())
    with pytest.raises(ValueError, match="vocabulary"):
        fp.parse_decisions_audit(json.dumps(json.loads(ok)[:2] + [dict(json.loads(ok)[2], value="lodger")]), _card())
    mixed = json.dumps([json.loads(ok)[0],
                        {"case_id": 9, "field": "relevant", "decision": "unresolved", "note": "garbled"}])
    with pytest.raises(ValueError, match="unresolved reply is exactly one entry"):
        fp.parse_decisions_audit(mixed, _card())


class _Scripted:
    def __init__(self, reply): self.reply, self.prompts = reply, []
    def complete(self, req):
        self.prompts.append(req.user)
        return Response(self.reply, 1, 1, None, {"provider": "codex-cli"}, "stop", "0")
    def version(self): return "0"


def test_audit_run_writes_three_entries_per_card_and_resumes_by_brief_hash(tmp_path):
    reply = json.dumps([{"case_id": 9, "field": "relevant", "decision": "set", "value": True, "note": "a"},
                        {"case_id": 9, "field": "polarity", "decision": "set", "value": "adverse", "note": "b"},
                        {"case_id": 9, "field": "who_was_letting", "decision": "set", "value": "unclear", "note": "c"}])
    out = tmp_path / "d.json"
    man = fp.run_first_pass([_card()], brief="B1", handoff="", provider=_Scripted(reply), out_path=out, log=lambda *_: None, audit=True)
    assert man["decided"] == 1 and len(json.loads(out.read_text(encoding="utf-8"))) == 3
    assert len(man["brief_sha256"]) == 64
    p2 = _Scripted(reply)
    fp.run_first_pass([_card()], brief="B1", handoff="", provider=p2, out_path=out, log=lambda *_: None, audit=True)
    assert p2.prompts == []                                   # same brief: not re-asked
    p3 = _Scripted(reply)
    fp.run_first_pass([_card()], brief="B2", handoff="", provider=p3, out_path=out, log=lambda *_: None, audit=True)
    assert len(p3.prompts) == 1                               # changed brief: re-asked


def test_codex_provider_passes_cwd_to_the_runner():
    from corpus_engine.reader.providers.codex_cli import CodexCliProvider
    from corpus_engine.reader.model import Request
    seen = {}
    def runner(argv, **kw):
        seen.update(kw)
        class P: returncode = 0; stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}\n'; stderr = ""
        return P()
    prov = CodexCliProvider("m", runner=runner, cwd="/iso")
    prov.complete(Request(pin={}, user="hi"))
    assert seen.get("cwd") == "/iso"
