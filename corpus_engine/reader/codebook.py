from __future__ import annotations
import hashlib, re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Codebook:
    id: str; path: Path; text: str; sha: str; judged_fields: tuple[str, ...]; validated_norm_version: str | None


def load_codebook(domain, codebook_id: str) -> Codebook:
    path = Path(domain.root) / domain.reader.codebooks_dir / f"{codebook_id}.md"
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    m = re.match(r"<!--\s*validated_norm_version:\s*(\S+)\s*-->\n?", text)
    return Codebook(codebook_id, path, text, hashlib.sha256(raw).hexdigest(), tuple(domain.reader.judged_fields),
                    m.group(1) if m else None)


def stability_path(domain, codebook: Codebook) -> Path:
    return Path(domain.root) / domain.reader.codebooks_dir / "stability" / f"{codebook.sha}.json"
