import json, pytest
from corpus_engine.reader.model import ModelPin, Request, ReaderError
from corpus_engine.reader.providers.cassette import CassetteProvider
from corpus_engine.reader.providers.codex_cli import CodexCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider
from corpus_engine.reader.providers.scripted import ScriptedProvider

PIN = ModelPin("deepseek/deepseek-v4-flash", "deepseek", "DeepInfra", "fp8")

def test_scripted_and_cassette_record_and_replay(tmp_path):
    s = ScriptedProvider(["[1]", "[2]"]); req = Request(PIN, "hello")
    c = CassetteProvider(tmp_path, fallback=s)
    assert c.complete(req).text == "[1]" and s.calls == 1
    assert c.complete(req).text == "[1]" and s.calls == 1                       # replayed, not re-asked
    assert c.complete(Request(PIN, "other")).text == "[2]" and s.calls == 2
    with pytest.raises(ReaderError, match="cassette miss"):
        CassetteProvider(tmp_path).complete(Request(PIN, "never seen"))

def test_openrouter_sends_pin_and_schema_reads_cost_and_retries():
    sent = []; calls = {"n": 0}
    def transport(url, json_body, headers, timeout):
        calls["n"] += 1; sent.append(json_body)
        if calls["n"] == 1:
            return 429, {"error": "slow"}
        return 200, {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.00012}, "provider": "DeepInfra"}
    import corpus_engine.reader.providers.openrouter as m
    m.time.sleep = lambda s: None
    p = OpenRouterProvider("k", transport=transport)
    r = p.complete(Request(PIN, "u", json_schema={"type": "array"}))
    assert r.text == "[]" and r.cost_usd == 0.00012 and r.input_tokens == 10 and r.provider_reported["provider"] == "DeepInfra"
    body = sent[-1]
    assert body["model"] == PIN.model_id and body["provider"] == {"order": ["DeepInfra"], "allow_fallbacks": False, "quantizations": ["fp8"]}
    assert body["response_format"]["type"] == "json_schema" and body["temperature"] == 0.0 and calls["n"] == 2
    body2 = []; p2 = OpenRouterProvider("k", transport=lambda u, j, h, t: (body2.append(j) or (200, {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}})))
    p2.complete(Request(ModelPin("anthropic/claude-sonnet-5", "anthropic"), "u"))
    assert "provider" not in body2[0] and "response_format" not in body2[0]

def test_codex_cli_parses_events_and_records_version():
    class P:  # fake CompletedProcess
        def __init__(self, out, code=0): self.stdout = out; self.stderr = ""; self.returncode = code
    def runner(cmd, **kw):
        if cmd[1] == "--version":
            return P("codex-cli 9.9.9\n")
        assert cmd[:3] == ["codex", "exec", "--sandbox"] and "--model" in cmd and cmd[cmd.index("--model") + 1] == "gpt-5.6-terra"
        events = [{"type": "item.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "draft"}},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "[{\"case_id\": 1}]"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}]
        return P("\n".join(json.dumps(e) for e in events) + "\n")
    p = CodexCliProvider("gpt-5.6-terra", runner=runner)
    r = p.complete(Request(ModelPin("codex-cli", "openai"), "prompt"))
    assert r.text == '[{"case_id": 1}]' and r.input_tokens == 100 and r.tool_version == "codex-cli 9.9.9" and r.cost_usd is None
    assert p.is_available()
    bad = CodexCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("codex")))
    assert not bad.is_available()
