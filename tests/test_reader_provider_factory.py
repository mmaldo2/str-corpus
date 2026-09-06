"""The transport / budget helpers now live in the engine, not in the measurement script.

They are the same functions: the map runner (slice 2) and the measurement tool both have to
resolve a candidate to a provider and a pin, and both have to express the subscription's
budget as units and wall clock rather than dollars. Importing them out of tools/ would drag
the measurement's OpenRouter ceiling and manifest merging into every map run."""
import importlib.util
from pathlib import Path

from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers import factory as F
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("measure_reader", ROOT / "tools" / "measure_reader.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)

SUB = {"model_id": "claude-cli/claude-opus-5", "family": "anthropic",
       "provider": "claude-cli", "cli_model": "claude-opus-5"}
OPENR = {"model_id": "z-ai/glm-5.3", "family": "zai", "pin_open": True}


def test_the_factory_owns_the_constants_the_pin_is_built_from():
    assert F.EFFORT == "low" and F.REASONING == {"effort": "low"}
    assert F.READ_TIMEOUT == 1500 and F.OPEN_PRECISIONS == ("bf16", "fp8")
    assert F.SUBSCRIPTION_PROVIDER == "claude-cli"
    assert F.SUBSCRIPTION_MAX_UNITS == 60 and F.SUBSCRIPTION_MAX_WALL_SECONDS == 6 * 3600
    assert F.SUBSCRIPTION_UNIT_MARGIN == 10


def test_cli_pin_is_the_label_the_cache_key_hashes():
    pin = F.cli_pin(SUB)
    assert isinstance(pin, ModelPin)
    assert pin.label == "claude-cli/claude-opus-5@claude-cli:-"
    assert pin.extra == {"effort": "low", "cli_model": "claude-opus-5"}
    assert F.is_subscription(SUB) and not F.is_subscription(OPENR)


def test_needs_openrouter_is_false_for_an_all_subscription_run():
    """A transport-selection question, same shape as `is_subscription`: whether this
    invocation must authenticate to OpenRouter at all."""
    assert F.needs_openrouter([SUB, OPENR]) and F.needs_openrouter([OPENR])
    assert not F.needs_openrouter([SUB]) and not F.needs_openrouter([])


def test_provider_for_picks_the_cli_transport_and_reports_why(monkeypatch):
    monkeypatch.setattr(ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    provider, pin, why = F.provider_for(SUB, None)
    assert provider.name == "claude-cli" and provider.cli_model == "claude-opus-5"
    assert provider.timeout == F.READ_TIMEOUT and pin.model_id == "claude-cli/claude-opus-5"
    assert "2.1.258" in why
    monkeypatch.setattr(ClaudeCliProvider, "version", lambda self: None)
    assert F.provider_for(SUB, None) == (None, None,
                                         "claude cli not available on PATH (shutil.which found nothing)")
    # an OpenRouter candidate with no provider configured is skipped with a reason, never crashed on
    provider2, pin2, why2 = F.provider_for(OPENR, None)
    assert provider2 is None and pin2 is None and "OPENROUTER_API_KEY" in why2


def test_budget_for_never_puts_a_dollar_ceiling_on_the_subscription():
    b = F.budget_for(SUB, 15.0)
    assert b == Budget(max_usd=None, max_units=60, max_wall_seconds=21600.0)
    b2 = F.budget_for(SUB, 15.0, max_units=439, max_wall_seconds=3600)
    assert b2.max_usd is None and b2.max_units == 439 and b2.max_wall_seconds == 3600.0
    assert F.budget_for(OPENR, 12.5) == Budget(max_usd=12.5)
    assert F.budget_for(OPENR, -3.0).max_usd == 0.0


def test_process_unit_cap_still_counts_the_measurement_reads():
    cases = [{"case_id": i} for i in range(1, 19)]
    batches = [{"batch_id": f"b{n}", "era_partition": "e", "jurisdiction": "j", "cases": cases}
               for n in range(1, 24)]
    plan = F.process_unit_cap(2, batches, set(range(1, 19)))
    assert plan == {"kit": 46, "batch_size_pair": 92, "stability": 46, "margin": 10, "total": 194}
    assert F.process_unit_cap(0, batches, set(range(1, 19)))["total"] == 0


def test_the_measurement_tool_still_exposes_every_moved_name():
    """The relocation is behaviour-preserving: tests/test_measure_reader_tool.py calls all of
    these through `mr.` and must keep passing without being edited."""
    for name in ("EFFORT", "REASONING", "READ_TIMEOUT", "OPEN_PRECISIONS", "SUBSCRIPTION_PROVIDER",
                 "SUBSCRIPTION_MAX_UNITS", "SUBSCRIPTION_MAX_WALL_SECONDS", "SUBSCRIPTION_UNIT_MARGIN",
                 "credits_remaining", "endpoints", "pin_for", "is_subscription", "needs_openrouter",
                 "cli_pin", "provider_for", "small_batches", "sample_batches", "process_unit_cap",
                 "budget_for", "ClaudeCliProvider", "OpenRouterProvider"):
        assert hasattr(mr, name), name
        if name in ("cli_pin", "provider_for", "budget_for", "process_unit_cap", "needs_openrouter"):
            assert getattr(mr, name) is getattr(F, name), f"{name} is a copy, not the moved function"
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "from corpus_engine.reader.providers.factory import" in src
    assert "def provider_for(" not in src and "def budget_for(" not in src
