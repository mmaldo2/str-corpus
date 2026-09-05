import json, shutil
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.model import Budget, CaseText, ModelPin, Plan, StopReason, Unit
from corpus_engine.reader.sources import InlinedCaseSource, StoreCaseSource

def test_pin_label_and_types():
    p = ModelPin("deepseek/deepseek-v4-flash", "deepseek", "DeepInfra", "fp8")
    assert p.label == "deepseek/deepseek-v4-flash@DeepInfra:fp8" and ModelPin("x", "y").label == "x@-:-"
    assert StopReason("budget:usd", "50.00").kind.startswith("budget")
    u = Unit("b-001", (3, 1, 2), {"batch_id": "b-001"}); assert u.case_ids == (3, 1, 2)
    pl = Plan("batch_extraction", (u,), "mapper-v1", p, Budget(max_usd=1.0), worker="claude")
    assert pl.checker_pin is None and pl.sample_pct == 10

def test_store_source_reads_fixture_and_inlined_source_round_trips(tmp_path, fixture_db):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p)
    ids = [r[0] for r in conn.execute("SELECT case_id FROM cases ORDER BY case_id LIMIT 3")]
    texts = StoreCaseSource(conn).fetch(ids)
    assert [t.case_id for t in texts] == ids and texts[0].raw_text and texts[0].norm_text and isinstance(texts[0].page_map, list)
    inl = InlinedCaseSource({t.case_id: t for t in texts})
    assert inl.fetch(ids[::-1])[0].case_id == ids[-1]
    import pytest
    from corpus_engine.reader.model import ReaderError
    with pytest.raises(ReaderError, match="999999999"):
        StoreCaseSource(conn).fetch([ids[0], 999999999])

def test_domain_reader_spec():
    r = load_domain().reader
    assert r.codebook == "mapper-v2" and r.codebooks_dir.endswith("codebooks") and r.checker_sample_pct == 10
    assert set(("characterization", "polarity", "holding_summary")) <= set(r.judged_fields)
    assert r.families["anthropic/claude-sonnet-5"] == "anthropic" and len(r.candidates) == 10
    assert r.kit_path == "data/reader/kit-v1/kit.json" and r.stability_sample.endswith("sample-50.json")
