"""Resolve the reranker's revision to a commit sha and write it into domain.yaml (never 'main')."""
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from huggingface_hub import HfApi                                       # noqa: E402
from corpus_engine.domain import load_domain                            # noqa: E402
if __name__ == "__main__":
    dom = load_domain(); r = dom.ranking.reranker
    sha = HfApi().model_info(r["model"], revision=r.get("revision") if r.get("revision") not in (None, "main") else None).sha
    p = ROOT / "domains" / dom.name / "domain.yaml"; s = p.read_text(encoding="utf-8")
    s2 = re.sub(r"(reranker:\n(?:.*\n)*?\s+revision:\s*)\S+", lambda m: m.group(1) + sha, s, count=1)
    assert s2 != s or sha in s, "revision line not found"
    p.write_text(s2, encoding="utf-8", newline="\n"); print("pinned", r["model"], "->", sha)
