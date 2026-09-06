"""Checker transport: the Codex command-line tool via subprocess, as in cycles 1-3 (user decision, ADR-0007 amendment)."""
from __future__ import annotations
import json, shutil, subprocess
from corpus_engine.reader.model import ReaderError, Request, Response


class CodexCliProvider:
    name = "codex-cli"
    def __init__(self, cli_model: str, *, runner=subprocess.run, timeout: int = 900, exe: str = "codex"):
        # Resolve the executable the way ClaudeCliProvider does: on Windows the npm shim is
        # `codex.CMD`, which subprocess cannot find under the bare name without a shell.
        self.cli_model, self.runner, self.timeout = cli_model, runner, timeout
        self.exe = shutil.which(exe) or exe
        self._version: str | None = None

    def version(self) -> str | None:
        if self._version is None:
            try:
                p = self.runner([self.exe, "--version"], capture_output=True, text=True, timeout=60)
                self._version = (p.stdout or "").strip() or None
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                self._version = None
        return self._version

    def is_available(self) -> bool:
        return self.version() is not None

    def complete(self, req: Request) -> Response:
        cmd = [self.exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--model", self.cli_model, "--json", "-"]
        try:
            p = self.runner(cmd, input=req.user, capture_output=True, text=True, timeout=self.timeout, encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise ReaderError(f"codex cli unavailable: {exc!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ReaderError("codex cli timed out") from exc
        if p.returncode != 0:
            raise ReaderError(f"codex exited {p.returncode}: {(p.stderr or '')[:300]}")
        text, usage = "", {}
        for line in (p.stdout or "").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                text = item["text"]
            for k in ("usage", "token_usage"):
                if isinstance(ev.get(k), dict):
                    usage = ev[k]
        if not text:
            raise ReaderError("codex cli produced no agent_message")
        return Response(text, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), None,
                        {"provider": "codex-cli", "cli_model": self.cli_model}, "stop", self.version())
