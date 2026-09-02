"""Bridge to pipeline/textnorm.py until textnorm moves into the package (Stage 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION, normalize, normalize_text, normalize_cite  # noqa: E402,F401
