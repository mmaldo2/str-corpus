from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ModelPin, Response, Unit


class ResponseCache:
    def __init__(self, dir: Path):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True)
    @staticmethod
    def key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str:
        ids = ",".join(map(str, sorted(unit.case_ids)))
        return hashlib.sha256(f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}".encode("utf-8")).hexdigest()
    def get(self, key: str) -> Response | None:
        p = self.dir / f"{key}.json"
        return Response(**json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None
    def put(self, key: str, r: Response) -> None:
        (self.dir / f"{key}.json").write_bytes(json.dumps(asdict(r), sort_keys=True).encode("utf-8"))
