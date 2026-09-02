"""Bridge until textnorm moves into the package (Stage 3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from textnorm import NORM_VERSION  # noqa: E402,F401
