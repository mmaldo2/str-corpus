from __future__ import annotations
import time
import httpx
from corpus_engine.indexer.embedders import RETRY_DELAYS
from corpus_engine.reader.model import ReaderError, Request, Response


def _httpx_transport(url, json_body, headers, timeout):
    r = httpx.post(url, json=json_body, headers=headers, timeout=timeout)
    try:
        body = r.json()
    except ValueError:
        body = {"error": r.text[:300]}
    return r.status_code, body


class OpenRouterProvider:
    name = "openrouter"
    def __init__(self, api_key: str, *, transport=None, timeout: int = 300, base: str = "https://openrouter.ai/api/v1"):
        self.key, self.transport, self.timeout, self.base = api_key, transport or _httpx_transport, timeout, base
        self._models: dict | None = None

    def _body(self, req: Request) -> dict:
        body = {"model": req.pin.model_id, "messages": ([{"role": "system", "content": req.system}] if req.system else [])
                + [{"role": "user", "content": req.user}], "temperature": req.temperature, "max_tokens": req.max_tokens,
                "usage": {"include": True}}
        if req.pin.provider_name:
            prov = {"order": [req.pin.provider_name], "allow_fallbacks": False}
            if req.pin.precision:
                prov["quantizations"] = [req.pin.precision]
            body["provider"] = prov
        if req.json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "records", "schema": req.json_schema}}
        return body

    def complete(self, req: Request) -> Response:
        last = ""
        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                status, body = self.transport(f"{self.base}/chat/completions", self._body(req),
                                              {"Authorization": f"Bearer {self.key}"}, self.timeout)
            except (httpx.TransportError, OSError) as exc:
                last = f"transport error: {exc!r}"
                if delay == 0:
                    raise ReaderError(f"{last} after {attempt + 1} attempts") from exc
                time.sleep(delay); continue
            if status == 200 and body.get("choices"):
                ch = body["choices"][0]; u = body.get("usage") or {}
                content = ch.get("message", {}).get("content") or ""
                finish_reason = ch.get("finish_reason") or ""
                if not content:
                    raise ReaderError(f"empty completion from {req.pin.model_id} (finish_reason={finish_reason})")
                return Response(content, int(u.get("prompt_tokens") or 0),
                                int(u.get("completion_tokens") or 0), (float(u["cost"]) if u.get("cost") is not None else None),
                                {"provider": body.get("provider"), "model": body.get("model"), "id": body.get("id")},
                                finish_reason)
            last = f"{status}: {str(body)[:200]}"
            if status == 429 or status >= 500:
                if delay == 0:
                    break
                time.sleep(delay); continue
            raise ReaderError(last)
        raise ReaderError(f"openrouter failed after {len(RETRY_DELAYS)} attempts; last {last}")

    def probe_model(self, model_id: str) -> dict | None:
        if self._models is None:
            r = httpx.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"}, timeout=60)
            self._models = {m["id"]: m for m in r.json().get("data", [])}
        return self._models.get(model_id)
