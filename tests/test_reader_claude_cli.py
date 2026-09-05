"""The subscription transport. Every flag in the invocation is load-bearing: the probe on
2026-09-05 measured ~750 input tokens of overhead with them against ~137,000 for a bare
`claude -p`, so each one is asserted here and a silent removal fails the suite. The
environment must not carry ANTHROPIC_API_KEY: with a key present the call bills the API,
which is exactly the route ADR-0007's amendment moved away from."""
import json
import subprocess

import pytest

from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.driver import plan_batch_extraction, preflight
from corpus_engine.reader.model import Budget, ModelPin, ReaderError, Request
from corpus_engine.reader.providers import claude_cli as cc
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider

PIN = ModelPin("claude-cli/claude-sonnet-5", "anthropic", "claude-cli", None,
               {"effort": "low", "cli_model": "claude-sonnet-5"})
SCHEMA = {"type": "object", "properties": {"records": {"type": "array"}}}
VERSION = "2.1.258 (Claude Code)"


class P:
    """A fake CompletedProcess."""
    def __init__(self, stdout, code=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, code, stderr


def envelope(**kw) -> str:
    body = {"result": "[]", "is_error": False, "session_id": "sess-1", "num_turns": 1,
            "stop_reason": "end_turn", "total_cost_usd": 0.42,
            "usage": {"input_tokens": 700, "cache_creation_input_tokens": 40,
                      "cache_read_input_tokens": 14, "output_tokens": 120}}
    body.update(kw)
    return json.dumps(body)


def runner_for(responses, calls):
    def runner(cmd, **kw):
        if cmd[1] == "--version":
            return P(VERSION + "\n")
        calls.append((cmd, kw))
        out = responses.pop(0)
        return out if isinstance(out, P) else P(out)
    return runner


def test_every_flag_is_sent_and_the_api_key_is_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-be-passed")
    monkeypatch.setenv("STR_CORPUS_SENTINEL", "kept")
    calls = []
    p = ClaudeCliProvider("claude-sonnet-5", runner=runner_for([envelope()], calls), exe="claude")
    r = p.complete(Request(PIN, "the prompt", json_schema=SCHEMA))
    cmd, kw = calls[0]
    assert cmd[1:] == ["-p", "--model", "claude-sonnet-5", "--output-format", "json",
                       "--effort", "low", "--tools", "",
                       "--system-prompt", cc.DEFAULT_SYSTEM,
                       "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--setting-sources", "", "--exclude-dynamic-system-prompt-sections",
                       "--json-schema", json.dumps(SCHEMA, sort_keys=True)]
    assert kw["input"] == "the prompt" and kw["timeout"] == 1500 and kw["encoding"] == "utf-8"
    assert kw["capture_output"] is True and kw["text"] is True
    assert "ANTHROPIC_API_KEY" not in kw["env"] and kw["env"]["STR_CORPUS_SENTINEL"] == "kept"
    # usage is the sum of the three input counters; the subscription has no marginal price
    assert r.input_tokens == 754 and r.output_tokens == 120 and r.cost_usd is None
    assert r.raw["list_cost_usd"] == 0.42
    assert r.provider_reported == {"provider": "claude-cli", "cli_model": "claude-sonnet-5",
                                   "effort": "low", "claude_version": VERSION, "session_id": "sess-1"}
    assert r.tool_version == VERSION and r.finish_reason == "end_turn" and r.text == "[]"


def test_structured_output_is_the_response_text_when_present():
    so = {"records": [{"case_id": 1, "relevant": False, "polarity": None, "quotes": []}]}
    p = ClaudeCliProvider("claude-opus-5", runner=runner_for([envelope(structured_output=so, result="prose")], []))
    r = p.complete(Request(PIN, "u", json_schema=SCHEMA))
    assert r.text == json.dumps(so, sort_keys=True) and json.loads(r.text) == so


def test_request_system_overrides_the_default_and_no_schema_means_no_flag():
    calls = []
    p = ClaudeCliProvider("claude-sonnet-5", runner=runner_for([envelope()], calls))
    p.complete(Request(PIN, "u", system="CODEBOOK SYSTEM LINE"))
    cmd = calls[0][0]
    assert cmd[cmd.index("--system-prompt") + 1] == "CODEBOOK SYSTEM LINE"
    assert "--json-schema" not in cmd


def test_the_windows_cmd_shim_is_resolved_with_which(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda name: r"C:\npm\claude.cmd" if name == "claude" else None)
    calls = []
    ClaudeCliProvider("m", runner=runner_for([envelope()], calls), exe="claude").complete(Request(PIN, "u"))
    assert calls[0][0][0] == r"C:\npm\claude.cmd"
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    assert ClaudeCliProvider("m", exe="claude")._exe() == "claude"


def test_error_envelopes_and_unparseable_output_raise():
    p = ClaudeCliProvider("m", runner=runner_for([P(envelope(is_error=True, result="bad request",
                                                             api_error_status=400))], []))
    with pytest.raises(ReaderError, match="api_error_status=400"):
        p.complete(Request(PIN, "u"))
    p2 = ClaudeCliProvider("m", runner=runner_for([P("not json", 1, "exploded")], []))
    with pytest.raises(ReaderError, match="unparseable envelope"):
        p2.complete(Request(PIN, "u"))
    p3 = ClaudeCliProvider("m", runner=lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError("claude")))
    assert not p3.is_available()
    with pytest.raises(ReaderError, match="claude cli unavailable"):
        p3.complete(Request(PIN, "u"))
    def slow(cmd, **kw):
        if cmd[1] == "--version":
            return P(VERSION)
        raise subprocess.TimeoutExpired(cmd, 1500)
    with pytest.raises(ReaderError, match="timed out"):
        ClaudeCliProvider("m", runner=slow).complete(Request(PIN, "u"))


def test_a_non_numeric_usage_field_raises_readererror_not_valueerror():
    """task-2-review finding 1. A syntactically valid envelope whose `usage.*` field is not
    numeric used to escape `complete()` as a bare ValueError; every other malformed-response
    case here raises ReaderError, so this one must too."""
    p = ClaudeCliProvider("m", runner=runner_for([envelope(usage={"input_tokens": "lots",
                                                                  "cache_creation_input_tokens": 0,
                                                                  "cache_read_input_tokens": 0,
                                                                  "output_tokens": 1})], []))
    with pytest.raises(ReaderError, match="malformed usage block"):
        p.complete(Request(PIN, "u"))


def test_throttling_waits_the_pinned_schedule_and_then_gives_up():
    slept, calls = [], []
    responses = [P(envelope(is_error=True, api_error_status=429, result="usage limit reached")) for _ in range(6)]
    p = ClaudeCliProvider("m", runner=runner_for(responses, calls), sleep=slept.append)
    with pytest.raises(ReaderError, match="subscription window exhausted"):
        p.complete(Request(PIN, "u"))
    assert slept == [60, 300, 900, 1800, 3600] and len(calls) == 6


def test_a_throttled_call_that_later_succeeds_returns_its_response():
    slept, calls = [], []
    responses = [P(envelope(is_error=True, api_error_status=529, result="overloaded, please retry")), P(envelope())]
    p = ClaudeCliProvider("m", runner=runner_for(responses, calls), sleep=slept.append)
    assert p.complete(Request(PIN, "u")).text == "[]"
    assert slept == [60] and len(calls) == 2
    # throttling is also recognised from the message when no status is set
    slept2, calls2 = [], []
    p2 = ClaudeCliProvider("m", runner=runner_for([P(envelope(is_error=True, result="5-hour usage limit reached")),
                                                   P(envelope())], calls2), sleep=slept2.append)
    assert p2.complete(Request(PIN, "u")).text == "[]" and slept2 == [60]


def test_a_prompt_over_the_stdin_cap_raises_before_any_call():
    calls = []
    p = ClaudeCliProvider("m", runner=runner_for([], calls))
    with pytest.raises(ReaderError, match="stdin cap"):
        p.complete(Request(PIN, "x" * (cc.PROMPT_LIMIT_BYTES + 1)))
    assert calls == []


def test_preflight_refuses_a_dollar_budget_on_the_unpriced_subscription_provider():
    dom = load_domain(); cb = load_codebook(dom, "mapper-v1")
    plan = plan_batch_extraction([], "mapper-v1", PIN, Budget(max_usd=5.0), worker="reader")
    stop = preflight(plan, cb, None, ClaudeCliProvider("claude-sonnet-5"), None,
                     store_norm_version="v1", families={})
    assert stop.kind == "preflight:budget_unpriced" and "claude-cli" in stop.detail
