from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from corpus_engine.reader.model import ModelPin, ReaderError, Response, Unit


class ResponseCache:
    def __init__(self, dir: Path):
        self.dir = Path(dir); self.dir.mkdir(parents=True, exist_ok=True)
    @staticmethod
    def key(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str, *, schema_sha: str = "",
            max_tokens: int = 0, effort: str = "") -> str:
        """What a cached response is allowed to answer for (spec section 4).

        3A hashed only `codebook_sha|pin.label|unit.id|case ids|prompt`, so two runs that
        differed only in reasoning effort, max_tokens or the attached schema collided - the
        limitation recorded in the measurement-v1 manifest. Slice 1 re-buys every read, so
        the key is widened now; measurement-v1's cache stays on disk for provenance and is
        addressed only by `key_v1`."""
        ids = ",".join(map(str, sorted(unit.case_ids)))
        parts = f"{codebook_sha}|{pin.label}|{unit.id}|{ids}|{prompt}|{schema_sha}|{max_tokens}|{effort}"
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()

    @staticmethod
    def key_v1(codebook_sha: str, pin: ModelPin, unit: Unit, prompt: str) -> str:
        """The frozen Stage 3A composition. Offline tools (manifest annotation, the
        who-was-letting consensus) address the purchased measurement-v1 cache with it.
        Never used for a new read."""
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
