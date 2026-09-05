from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ReaderError, Request, Response


class CassetteProvider:
    name = "cassette"
    def __init__(self, dir: Path, *, fallback=None):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True); self.fallback = fallback
    @staticmethod
    def key(req: Request) -> str:
        schema = json.dumps(req.json_schema, sort_keys=True) if req.json_schema else ""
        parts = f"{req.pin.label}|{req.system or ''}|{req.user}|{schema}|{req.max_tokens}|{req.temperature}"
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()
    def complete(self, req: Request) -> Response:
        p = self.dir / f"{self.key(req)}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8")); return Response(**d)
        if self.fallback is None:
            raise ReaderError(f"cassette miss for {req.pin.label} ({self.key(req)[:12]})")
        r = self.fallback.complete(req)
        p.write_bytes(json.dumps(asdict(r), sort_keys=True).encode("utf-8"))
        return r
