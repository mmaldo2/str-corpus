"""Reader transport: the Claude Code CLI on the user's subscription (ADR-0007 amendment
2026-09-05, decision D1).

Never `shell=True` (the legacy pipeline/run_map.py call_claude used it on Windows and so
handed the prompt to cmd.exe's quoting rules); the executable is resolved with
`shutil.which` instead, which finds the `.cmd` shim npm installs on Windows.

Every flag is load-bearing. Measured 2026-09-05: this invocation costs ~750 input tokens
of overhead per call, against ~137,000 for a bare `claude -p` (tools, MCP config, dynamic
system-prompt sections and the user's settings all arrive as context otherwise). Each flag
is asserted in tests/test_reader_claude_cli.py, so removing one fails the suite."""
from __future__ import annotations
import json, os, re, shutil, subprocess, time
from corpus_engine.reader.model import ReaderError, Request, Response

DEFAULT_SYSTEM = ("You are an extraction worker in a legal-history pipeline. Follow the codebook "
                  "in the message exactly and return only the JSON it asks for.")
# The CLI reads the prompt from stdin and caps it at 10 MB. Refuse at 9 MB rather than let
# a unit be truncated mid-case: a truncated opinion still parses and still gates, so the
# damage would be silent.
STDIN_LIMIT_BYTES = 10 * 1024 * 1024
PROMPT_LIMIT_BYTES = 9 * 1024 * 1024
# The subscription's own refusal is a wait, not a failure: the window reopens. A unit that
# still cannot be bought after the last wait is failed and the driver moves on; the next
# run resumes it from the cache for free.
THROTTLE_DELAYS = (60, 300, 900, 1800, 3600)
THROTTLE_STATUS = ("429", "529")
THROTTLE_TEXT = re.compile(r"usage limit|rate.?limit|too many requests|overloaded|"
                           r"capacity|try again later", re.IGNORECASE)


def _throttled(status: str, blob: str) -> bool:
    return status in THROTTLE_STATUS or bool(THROTTLE_TEXT.search(blob or ""))


class ClaudeCliProvider:
    name = "claude-cli"

    def __init__(self, cli_model: str, *, runner=subprocess.run, timeout: int = 1500,
                 exe: str = "claude", effort: str = "low", system_default: str = DEFAULT_SYSTEM,
                 sleep=time.sleep, delays: tuple[int, ...] = THROTTLE_DELAYS):
        self.cli_model, self.runner, self.timeout, self.exe = cli_model, runner, timeout, exe
        self.effort, self.system_default = effort, system_default
        self.sleep, self.delays = sleep, tuple(delays)
        self._version: str | None = None

    def _exe(self) -> str:
        return shutil.which(self.exe) or self.exe

    def version(self) -> str | None:
        if self._version is None:
            try:
                p = self.runner([self._exe(), "--version"], capture_output=True, text=True, timeout=60)
                self._version = (p.stdout or "").strip() or None
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                self._version = None
        return self._version

    def is_available(self) -> bool:
        return self.version() is not None

    def argv(self, req: Request) -> list[str]:
        cmd = [self._exe(), "-p", "--model", self.cli_model, "--output-format", "json",
               "--effort", self.effort, "--tools", "",
               "--system-prompt", req.system or self.system_default,
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--setting-sources", "", "--exclude-dynamic-system-prompt-sections"]
        if req.json_schema:
            cmd += ["--json-schema", json.dumps(req.json_schema, sort_keys=True)]
        return cmd

    @staticmethod
    def env() -> dict:
        """The subscription pays for this call. With ANTHROPIC_API_KEY visible the CLI bills
        the API instead - the route ADR-0007's amendment deliberately left."""
        return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    def complete(self, req: Request) -> Response:
        size = len(req.user.encode("utf-8"))
        if size > PROMPT_LIMIT_BYTES:
            raise ReaderError(f"prompt is {size} bytes; the CLI stdin cap is {STDIN_LIMIT_BYTES} "
                              f"and this unit must be split before it is asked")
        last = ""
        for attempt in range(len(self.delays) + 1):
            resp, last, throttled = self._attempt(req)
            if resp is not None:
                return resp
            if not throttled:
                raise ReaderError(last)
            if attempt < len(self.delays):
                self.sleep(self.delays[attempt])
        raise ReaderError(f"subscription window exhausted after {len(self.delays)} waits; last {last}")

    def _attempt(self, req: Request) -> tuple[Response | None, str, bool]:
        try:
            p = self.runner(self.argv(req), input=req.user, capture_output=True, text=True,
                            timeout=self.timeout, encoding="utf-8", env=self.env())
        except (FileNotFoundError, OSError) as exc:
            return None, f"claude cli unavailable: {exc!r}", False
        except subprocess.TimeoutExpired:
            return None, f"claude cli timed out after {self.timeout}s", False
        out, err = p.stdout or "", p.stderr or ""
        try:
            env = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            env = None
        if not isinstance(env, dict):
            return (None, f"claude exited {p.returncode} with unparseable envelope: {(out or err)[:300]}",
                    _throttled("", f"{out} {err}"))
        status = str(env.get("api_error_status") or "")
        blob = f"{env.get('result') or ''} {err}"
        if p.returncode != 0 or env.get("is_error") or status:
            return (None, f"claude exited {p.returncode} (api_error_status={status or 'none'}): "
                          f"{str(env.get('result'))[:300]}", _throttled(status, blob))
        structured = env.get("structured_output")
        text = json.dumps(structured, sort_keys=True) if structured is not None else (env.get("result") or "")
        if not text:
            return None, "claude cli produced no result and no structured_output", False
        u = env.get("usage") or {}
        inp = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                               "cache_read_input_tokens"))
        reported = {"provider": self.name, "cli_model": self.cli_model, "effort": self.effort,
                    "claude_version": self.version(), "session_id": env.get("session_id")}
        # cost_usd stays None: `total_cost_usd` is what the same call would have cost on the
        # API, not a charge against anything. It is recorded so the report can say what the
        # subscription saved, and `score_candidate` marks the candidate unpriced.
        raw = {"list_cost_usd": env.get("total_cost_usd"), "num_turns": env.get("num_turns"),
               "session_id": env.get("session_id")}
        return (Response(text, inp, int(u.get("output_tokens") or 0), None, reported,
                         env.get("stop_reason") or "stop", self.version(), raw), "", False)
