"""The schema every Request now carries, the two response shapes parse accepts, and the
cache key that decides what a new read may reuse. The key is widened here, while every
read is being re-bought anyway: the 3A key hashed only the pin label, so two runs that
differed in effort, max_tokens or schema collided (measurement-v1 manifest, LIMITATION)."""
import hashlib, json, shutil

from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.reader.cache import ResponseCache
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import Reader, plan_batch_extraction
from corpus_engine.reader.model import Budget, ModelPin, Response, Unit, effort_of
from corpus_engine.reader.parse import parse_records
from corpus_engine.reader.providers.scripted import ScriptedProvider
from corpus_engine.reader.schema import record_schema, schema_sha
from corpus_engine.reader.sources import StoreCaseSource

CLI_PIN = ModelPin("claude-cli/claude-sonnet-5", "anthropic", "claude-cli", None,
                   {"effort": "low", "cli_model": "claude-sonnet-5"})


def test_record_schema_pins_the_vocabularies_and_the_supports_rule():
    cb = load_codebook(load_domain(), "mapper-v2")
    s = record_schema(cb)
    assert s["required"] == ["records"] and s["properties"]["records"]["type"] == "array"
    rec = s["properties"]["records"]["items"]
    assert rec["required"] == ["case_id", "relevant", "polarity", "quotes"]
    assert rec["properties"]["polarity"]["enum"] == ["favorable", "adverse", "mixed", None]
    assert "irrelevant" not in rec["properties"]["polarity"]["enum"]          # D2: not a polarity value
    assert rec["properties"]["who_was_letting"]["enum"] == [
        "householder", "commercial_operator", "non_resident_owner", "unclear", None]
    q = rec["properties"]["quotes"]["items"]
    assert q["required"] == ["text", "supports"]
    assert q["properties"]["supports"]["type"] == "array"
    assert set(q["properties"]["supports"]["items"]["enum"]) == set(cb.judged_fields) | {"relevant"}
    # a relevant record must carry at least one quote; an irrelevant one need not
    assert rec["if"] == {"properties": {"relevant": {"const": True}}, "required": ["relevant"]}
    assert rec["then"] == {"properties": {"quotes": {"minItems": 1}}}
    assert schema_sha(s) == hashlib.sha256(json.dumps(s, sort_keys=True).encode("utf-8")).hexdigest()
    assert schema_sha(None) == ""


def test_parse_accepts_the_wrapped_object_and_the_bare_array():
    recs = [{"case_id": 1, "relevant": True, "polarity": "favorable", "quotes": []}]
    assert parse_records(json.dumps({"records": recs}), [1]) == recs
    assert parse_records(json.dumps(recs), [1]) == recs
    assert parse_records("```json\n" + json.dumps({"records": recs}) + "\n```", [1]) == recs
    assert parse_records("here you go: " + json.dumps({"records": recs}), [1]) == recs
    assert parse_records(json.dumps({"records": recs}), [1, 2]) is None       # coverage still required
    assert parse_records(json.dumps({"other": recs}), [1]) is None


def test_cache_key_composition_is_pinned():
    unit = Unit("u1", (2, 1), {})
    sha = schema_sha({"type": "object"})
    got = ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=64000, effort="low")
    want = hashlib.sha256(
        f"CB|claude-cli/claude-sonnet-5@claude-cli:-|u1|1,2|PROMPT|{sha}|64000|low".encode("utf-8")).hexdigest()
    assert got == want
    for other in (ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=64000, effort="high"),
                  ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha="", max_tokens=64000, effort="low"),
                  ResponseCache.key("CB", CLI_PIN, unit, "PROMPT", schema_sha=sha, max_tokens=16000, effort="low")):
        assert other != got
    # the 3A composition is kept verbatim so the purchased v1 cache stays addressable,
    # and a v2 key never collides with it
    v1 = ResponseCache.key_v1("CB", CLI_PIN, unit, "PROMPT")
    assert v1 == hashlib.sha256(
        "CB|claude-cli/claude-sonnet-5@claude-cli:-|u1|1,2|PROMPT".encode("utf-8")).hexdigest()
    assert v1 != got


def test_effort_of_reads_both_pin_shapes():
    assert effort_of(ModelPin("m", "f", extra={"reasoning": {"effort": "low"}})) == "low"
    assert effort_of(CLI_PIN) == "low"
    assert effort_of(ModelPin("m", "f")) == ""


def test_response_carries_a_raw_envelope_slot_and_defaults_it_empty():
    r = Response("t", 1, 2, None, {}, "stop")
    assert r.raw == {}
    assert Response("t", 1, 2, None, {}, "stop", None, {"list_cost_usd": 0.42}).raw["list_cost_usd"] == 0.42


def test_the_plan_carries_the_schema_and_every_request_sends_it(tmp_path, fixture_db, repo_root):
    p = tmp_path / "c.db"; shutil.copy(fixture_db, p); conn = store.connect(p); dom = load_domain()
    cb = load_codebook(dom, "mapper-v1")
    batch = json.loads(sorted((repo_root / "tests/fixtures/batches/cycle-003-shard-01")
                              .glob("batch-*.json"))[0].read_text(encoding="utf-8"))
    schema = record_schema(cb)
    plan = plan_batch_extraction([batch], "mapper-v1", ModelPin("m", "f"), Budget(max_usd=1.0),
                                 worker="claude", json_schema=schema)
    assert plan.json_schema is schema and plan.resume_tool == ""
    seen = []

    def answer(req):
        seen.append(req.json_schema)
        return json.dumps({"records": [{"case_id": c, "relevant": False, "polarity": None, "quotes": []}
                                       for c in plan.units[0].case_ids]})

    out = Reader(ScriptedProvider(answer), StoreCaseSource(conn), log=lambda *_: None, domain=dom,
                 store_norm_version="v1").read(plan)
    assert seen == [schema] and out.stop.kind == "done"
