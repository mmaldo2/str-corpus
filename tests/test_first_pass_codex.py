"""tools/first_pass_codex.py: the external first pass over a review queue through the Codex CLI,
one call per card, written in the decisions schema `tools/apply_map_review.py` reads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import first_pass_codex as fp  # noqa: E402
from corpus_engine.reader.model import Response  # noqa: E402


def _card(cid, section, field, **over):
    """A card in tools/export_review_cards.py's JSON shape, with the opinion text attached."""
    c = {"case_id": cid, "section": section, "section_title": "T", "decide_field": field,
         "cite": f"{cid} N.Y. 1", "name": "A v. B", "court": "Ct.", "jurisdiction": "N.Y.", "year": 1890,
         "reader": {"relevant": True, "polarity": "favorable", "who_was_letting": "householder",
                    "characterization": "lodging", "under_thirty_days": None,
                    "owner_freedom_characterization": None, "restriction_nature": None,
                    "duration_of_occupancy": "weeks"},
         "checker": {"relevant": True, "polarity": "adverse", "characterization": "lodging"},
         "quotes": [{"text": "she let the room by the week", "supports": ["polarity"]}],
         "fuzzy": [], "nulled_fields": [], "other_reasons": [], "conflict": None,
         "holding_summary": "h", "courtlistener_url": "https://www.courtlistener.com/?q=x",
         "opinion_text": "The plaintiff let the room by the week. Judgment for the plaintiff."}
    c.update(over)
    return c


class _Scripted:
    """A provider whose reply is looked up by the case id found in the prompt."""
    def __init__(self, replies):
        self.replies, self.prompts = replies, []

    def complete(self, req):
        self.prompts.append(req.user)
        for cid, text in self.replies.items():
            if f"[{cid}]" in req.user:
                if isinstance(text, Exception):
                    raise text
                return Response(text, 10, 5, None, {"provider": "codex-cli", "cli_model": "gpt-6-astra"}, "stop", "0.153.4")
        raise AssertionError("no scripted reply for this prompt")

    def version(self):
        return "0.153.4"


def _decision(cid, field, decision, value=None, note="because"):
    d = {"case_id": cid, "field": field, "decision": decision, "note": note}
    if value is not None:
        d["value"] = value
    return json.dumps(d)


def test_one_call_per_card_writes_the_decisions_file_in_the_apply_schema(tmp_path):
    cards = [_card(700, "A", "polarity"), _card(701, "E", "under_thirty_days"),
             _card(702, "F", "quotes")]
    prov = _Scripted({700: _decision(700, "polarity", "keep"),
                      701: _decision(701, "under_thirty_days", "set", "no"),
                      702: _decision(702, "quotes", "keep")})
    out = tmp_path / "decisions-astra.json"
    man = fp.run_first_pass(cards, brief="BRIEF TEXT", handoff="HANDOFF TEXT", provider=prov,
                            out_path=out, log=lambda *_: None)
    got = json.loads(out.read_text(encoding="utf-8"))
    assert [(d["case_id"], d["field"], d["decision"], d.get("value")) for d in got] == [
        (700, "polarity", "keep", None), (701, "under_thirty_days", "set", "no"), (702, "quotes", "keep", None)]
    assert all("note" in d for d in got)
    assert man["decided"] == 3 and man["failed"] == [] and man["model"] == "gpt-6-astra"
    assert len(prov.prompts) == 3 and "BRIEF TEXT" in prov.prompts[0] and "HANDOFF TEXT" in prov.prompts[0]
    assert "she let the room by the week" in prov.prompts[0]          # the card's full text is in the prompt
    assert out.read_bytes().endswith(b"\n") and b"\r" not in out.read_bytes()


def test_a_value_outside_the_vocabulary_is_a_failed_card_not_a_written_decision(tmp_path):
    cards = [_card(700, "A", "polarity"), _card(701, "D", "polarity")]
    prov = _Scripted({700: _decision(700, "polarity", "set", "sideways"),
                      701: _decision(701, "polarity", "set", "adverse")})
    out = tmp_path / "d.json"
    man = fp.run_first_pass(cards, brief="b", handoff="h", provider=prov, out_path=out, log=lambda *_: None)
    got = json.loads(out.read_text(encoding="utf-8"))
    assert [d["case_id"] for d in got] == [701]
    assert man["failed"] == [{"case_id": 700, "error": "polarity: 'sideways' is not in the vocabulary"}]


def test_adopt_is_resolved_to_the_checkers_value_and_withdrawal_is_spelled_as_relevant_false(tmp_path):
    cards = [_card(700, "C", "polarity"), _card(701, "E", "owner_freedom_characterization")]
    prov = _Scripted({700: _decision(700, "polarity", "adopt"),
                      701: _decision(701, "relevant", "set", False, note="not a letting case")})
    out = tmp_path / "d.json"
    fp.run_first_pass(cards, brief="b", handoff="h", provider=prov, out_path=out, log=lambda *_: None)
    got = {d["case_id"]: d for d in json.loads(out.read_text(encoding="utf-8"))}
    assert got[700]["decision"] == "set" and got[700]["value"] == "adverse"      # the checker's polarity
    assert got[701] == {"case_id": 701, "field": "relevant", "decision": "set", "value": False,
                        "note": "not a letting case"}


def test_a_rerun_resumes_from_the_cards_already_decided(tmp_path):
    from corpus_engine.reader.model import ReaderError
    cards = [_card(700, "A", "polarity"), _card(701, "A", "polarity")]
    out = tmp_path / "d.json"
    prov = _Scripted({700: _decision(700, "polarity", "keep"), 701: ReaderError("codex exited 1")})
    man = fp.run_first_pass(cards, brief="b", handoff="h", provider=prov, out_path=out, log=lambda *_: None)
    assert man["decided"] == 1 and [f["case_id"] for f in man["failed"]] == [701]
    prov2 = _Scripted({700: _decision(700, "polarity", "set", "adverse"),        # must NOT be re-asked
                       701: _decision(701, "polarity", "keep")})
    man2 = fp.run_first_pass(cards, brief="b", handoff="h", provider=prov2, out_path=out, log=lambda *_: None)
    got = {d["case_id"]: d for d in json.loads(out.read_text(encoding="utf-8"))}
    assert got[700]["decision"] == "keep" and got[701]["decision"] == "keep"
    assert len(prov2.prompts) == 1 and man2["decided"] == 2 and man2["failed"] == []


def test_the_reply_may_wrap_the_json_in_prose_or_a_fence():
    card = _card(700, "A", "polarity")
    text = "Here is my decision:\n```json\n" + _decision(700, "polarity", "keep") + "\n```\nDone."
    assert fp.parse_decision(text, card)["decision"] == "keep"
    with pytest.raises(ValueError, match="no JSON object"):
        fp.parse_decision("I cannot decide.", card)
    with pytest.raises(ValueError, match="case_id"):
        fp.parse_decision(_decision(999, "polarity", "keep"), card)
    with pytest.raises(ValueError, match="field"):
        fp.parse_decision(_decision(700, "who_was_letting", "keep"), card)   # not the card's field, not relevant


def test_the_parser_carries_the_flags():
    ap = fp.build_parser()
    a = ap.parse_args(["--cards", "c.json", "--handoff", "h.md", "--out", "o.json"])
    assert a.model == "gpt-6-astra" and a.brief.endswith("review-first-pass-brief.md")
