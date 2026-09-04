"""I1: pipeline/index.py's --legacy-0.6b comparison run must never record the literal
revision "main" under the already-claimed legacy run key. Imports the constants and
checks the EmbedRun pipeline/index.py would build; does not run the CLI or touch a
database (let alone the live one)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import index as pipeline_index  # noqa: E402
from corpus_engine import store  # noqa: E402
from corpus_engine.indexer.embed import EmbedRun  # noqa: E402


def test_legacy_revision_is_pinned_to_the_migrate_constant():
    assert pipeline_index.LEGACY_REVISION == store.LEGACY_EMBED_REVISION == "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
    assert pipeline_index.LEGACY_REVISION != "main"


def test_legacy_run_key_matches_what_migrate_registered():
    assert pipeline_index.LEGACY_RUN_KEY == store.LEGACY_EMBED_RUN


def test_legacy_embed_run_built_by_index_carries_pinned_non_main_revision():
    # Mirrors the EmbedRun construction in pipeline/index.py's `elif args.legacy:` branch.
    run = EmbedRun(pipeline_index.LEGACY_RUN_KEY, pipeline_index.LEGACY_MODEL, pipeline_index.LEGACY_REVISION,
                   pipeline_index.LEGACY_DIM, "int8-symmetric-pervector", pipeline_index.LEGACY_CHUNK_TOKENS,
                   pipeline_index.LEGACY_CHUNK_OVERLAP, "", "local")
    assert run.revision == store.LEGACY_EMBED_REVISION
    assert run.revision != "main"
