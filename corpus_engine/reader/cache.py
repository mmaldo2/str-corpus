from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ModelPin, ReaderError, Response, Unit


class ResponseCache:
    def __init__(self, dir: Path):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True)
    @staticmethod
    def key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str:
        ids = ",".join(map(str, sorted(unit.case_ids)))
        return hashlib.sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}".encode("utf-8")).hexdigest()
    def get(self, key: str) -> Response | None:
        """A truncated or schema-drifted entry raises ReaderError, not the TypeError /
        JSONDecodeError that `Response(**json.loads(...))` raises on its own: those escaped
        the driver's per-unit handler and ended the whole read (I1)."""
        p = self.dir / f"{key}.json"
        if not p.exists():
            return None
        try:
            return Response(**json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as exc:
            raise ReaderError(f"malformed cache entry {p.name}: {type(exc).__name__}: {exc}") from exc
    def put(self, key: str, r: Response) -> None:
        (self.dir / f"{key}.json").write_bytes(json.dumps(asdict(r), sort_keys=True).encode("utf-8"))
