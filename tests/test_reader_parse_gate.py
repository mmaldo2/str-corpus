import shutil
from corpus_engine import store
from corpus_engine.reader.gate import DUPLICATE_NOTE, gate_record, gate_unit
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

def test_parse_robust_brackets():
    # (a) prose before the array containing [1]
    before_text = 'See [1] for details. [{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    result = parse_records(before_text, [1, 2])
    assert result is not None and len(result) == 2
    # (b) prose after the array containing [42]
    after_text = '[{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}] See case [42] for more.'
    result = parse_records(after_text, [1, 2])
    assert result is not None and len(result) == 2
    # (c) record whose `notes` field contains brackets
    notes_text = '[{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": [], "notes": "See [1] for details [test]"}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    result = parse_records(notes_text, [1, 2])
    assert result is not None and len(result) == 2 and result[0]["notes"] == "See [1] for details [test]"
    # (d) truncated JSON still returns None
    truncated = '[{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []'
    result = parse_records(truncated, [1])
    assert result is None

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


def test_gate_accepts_a_quote_supporting_several_fields(tmp_path, fixture_db):
    """One passage can carry two findings and models say so with a list. Before this
    was handled the gate raised `unhashable type: 'list'` and killed the whole read."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    cid = conn.execute("SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1").fetchone()[0]
    t = StoreCaseSource(conn).fetch([cid])[0]
    exact = t.raw_text[500:620]
    r = gate_record({"case_id": cid, "relevant": True, "polarity": "favorable", "characterization": "license",
                     "holding_summary": "x",
                     "quotes": [{"text": exact, "supports": ["polarity", "characterization"]}]}, t, J)
    assert r.record["polarity"] == "favorable" and r.record["characterization"] == "license"
    assert r.nulled_fields == ("holding_summary",) and r.dropped_quotes == 0
    # a malformed value supports nothing, so every judged field is voided rather than trusted
    bad = gate_record({"case_id": cid, "relevant": True, "polarity": "favorable",
                       "quotes": [{"text": exact, "supports": [None, 7]}]}, t, J)
    assert bad.record["polarity"] is None


def test_gate_supports_is_the_one_shared_helper():
    """task-2-review finding 5: `gate._supports` duplicated the ledger's `quote_supports`
    verbatim. It is now an alias for the same function object, so the gate's quote-support
    parsing and the ledger's drop_quote cascade can never silently drift apart. M4 moved the
    definition to `corpus_engine.quotes` - upstream of both - and `fold` re-exports it, so
    all three names are still the one function."""
    from corpus_engine.reader import gate
    from corpus_engine.quotes import quote_supports
    from corpus_engine.ledger.fold import quote_supports as folded
    from corpus_engine.verification import quote_supports as verified
    assert gate._supports is quote_supports is folded is verified


def test_parse_bare_array_survives_a_stray_brace_in_prose():
    """task-1-review finding 1. The dispatch used to pick object-vs-array by comparing the
    *position* of the first `{`/`[`, so prose containing a stray, non-JSON `{` before the
    real answer made the parser commit to the object branch and fail outright - even though
    the real answer is a bare array. Deciding by what actually decodes at the top of the
    text, not by bracket position, fixes it."""
    text = 'Cf. {id.} below for context: [{"case_id": 1, "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    result = parse_records(text, [1, 2])
    assert result is not None and len(result) == 2


def test_parse_accepts_a_case_id_the_model_wrote_as_a_string():
    """m3. Coverage was checked against the raw values, so `"case_id": "1"` read as an
    unaccounted case: the unit was declared unparseable and burned a paid split retry
    before being written off, over a record that had in fact come back."""
    recs = '[{"case_id": "1", "relevant": true, "polarity": "favorable", "quotes": []}, {"case_id": 2, "relevant": false, "polarity": "irrelevant", "quotes": []}]'
    got = parse_records(recs, [1, 2])
    assert got is not None and len(got) == 2
    # a value that is not an integer spelling is still not a case id
    assert parse_records('[{"case_id": "one", "relevant": true, "polarity": "x", "quotes": []}]', [1]) is None


def test_gate_notes_a_duplicated_case_id_instead_of_dropping_it_silently(tmp_path, fixture_db):
    """m4. Two records for one case id: the last still wins, but the response is no longer
    reported as if only one had arrived."""
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    cid = conn.execute("SELECT case_id FROM cases WHERE length(norm_text) > 2000 ORDER BY case_id LIMIT 1").fetchone()[0]
    t = StoreCaseSource(conn).fetch([cid])[0]
    exact = t.raw_text[500:620]
    first = {"case_id": cid, "relevant": True, "polarity": "favorable", "quotes": [{"text": exact, "supports": "polarity"}]}
    second = {**first, "polarity": "adverse"}
    out = gate_unit([first, second], [t], (cid,), J, "u")
    assert len(out) == 1 and out[0].record["polarity"] == "adverse"          # last wins, as before
    assert DUPLICATE_NOTE in out[0].record["gate_notes"]
    clean = gate_unit([first], [t], (cid,), J, "u")
    assert "gate_notes" not in clean[0].record or DUPLICATE_NOTE not in (clean[0].record.get("gate_notes") or "")
