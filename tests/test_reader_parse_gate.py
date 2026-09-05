import shutil
from corpus_engine import store
from corpus_engine.reader.gate import gate_record, gate_unit
from corpus_engine.reader.model import Unit
from corpus_engine.reader.parse import parse_records, split_unit, strip_fences
from corpus_engine.reader.sources import StoreCaseSource

J = ("characterization", "polarity", "holding_summary")

def test_parse_accepts_clean_and_fenced_rejects_partial():
    recs = '[{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    assert len(parse_records(recs, [1, 2])) == 2
    assert len(parse_records("```json\n" + recs + "\n```", [1, 2])) == 2 and strip_fences("```\n[1]\n```") == "[1]"
    assert parse_records(recs, [1, 2, 3]) is None                         # case 3 unaccounted
    assert parse_records('[{"case_id": 1, "relevant": true}]', [1]) is None  # missing required keys
    assert parse_records(recs[:-10], [1, 2]) is None                       # truncated
    a, b = split_unit(Unit("u", (1, 2, 3, 4, 5), {"batch_id": "u"}))
    assert a.id == "u-a" and a.case_ids == (1, 2, 3) and b.case_ids == (4, 5) and b.meta["batch_id"] == "u"

def test_gate_drops_paraphrase_nulls_field_keeps_exact_and_stubs_missing(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    cid = conn.execute("SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1").fetchone()[0]
    t = StoreCaseSource(conn).fetch([cid])[0]
    exact = t.raw_text[500:620]
    rec = {"case_id": cid, "relevant": True, "polarity": "favorable", "characterization": "license", "holding_summary": "x",
           "quotes": [{"text": exact, "supports": "polarity"}, {"text": "The court plainly held something it never said here.", "supports": "characterization"}]}
    r = gate_record(dict(rec), t, J)
    assert r.dropped_quotes == 1 and r.nulled_fields == ("characterization", "holding_summary") and r.record["polarity"] == "favorable"
    assert r.record["characterization"] is None and r.record["quotes"][0]["status"] == "verified" and r.gate_status == "partial"
    irr = gate_record({"case_id": cid, "relevant": False, "polarity": "irrelevant", "quotes": [{"text": "zzz"}]}, t, J)
    assert irr.record["quotes"] == [] and irr.gate_status == "ok"
    out = gate_unit([rec], [t], (cid, 424242), J, "u")
    assert [x.case_id for x in out] == [cid, 424242] and out[1].gate_status == "missing" and out[1].record["relevant"] is None
