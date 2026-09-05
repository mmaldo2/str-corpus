"""Guards on tools/measure_reader.py: the parts that decide how much may be spent and
how spend is attributed. Imported by path because tools/ is scripts, not a package."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("measure_reader", ROOT / "tools" / "measure_reader.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)


def test_prior_spend_defaults_to_the_manifest_so_a_resume_cannot_regrant_the_ceiling():
    """--max-usd is a ceiling on the measurement. A resume replays the cache for free, so
    its own counter starts at zero; if the flag defaulted to 0.0 a forgetful restart would
    be handed the whole ceiling a second time."""
    prior = {"total_task_spend_usd": 38.82, "spent_usd": 15.03,
             "spend_by_candidate": {"a": 20.0, "b": 16.82}}
    got, why = mr.resolve_prior_spend(None, prior)
    assert got == 38.82 and "total_task_spend_usd" in why

    # explicit always wins, including an explicit zero that deliberately re-grants it
    assert mr.resolve_prior_spend(5.0, prior) == (5.0, "explicit --prior-spend-usd")
    got, why = mr.resolve_prior_spend(0.0, prior)
    assert got == 0.0 and why == "explicit --prior-spend-usd"

    # credits-reconciled totals are preferred over the per-candidate sum, which under-counts
    got, why = mr.resolve_prior_spend(None, {"spent_usd": 15.03,
                                             "spend_by_candidate": {"a": 1.0}})
    assert got == 15.03 and "spent_usd" in why
    got, why = mr.resolve_prior_spend(None, {"spend_by_candidate": {"a": 1.5, "b": 2.5}})
    assert got == 4.0 and "under-counts" in why

    # no prior manifest at all is the only case that legitimately yields zero
    assert mr.resolve_prior_spend(None, {}) == (0.0, "no prior manifest; nothing spent yet")


def test_charged_keeps_a_real_zero_instead_of_falling_through():
    """`delta or tracked` reads the same and is not: it discards a true reading of
    exactly 0.0, which is what a fully cached re-read costs."""
    assert mr.charged(0.0, 5.0) == 0.0
    assert mr.charged(None, 5.0) == 5.0
    assert mr.charged(2.5, 5.0) == 2.5


def test_write_json_ends_with_a_newline(tmp_path):
    p = tmp_path / "m.json"
    mr.write_json(p, {"b": 1, "a": float("inf")}, indent=1, sort_keys=True)
    raw = p.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    assert json.loads(raw.decode("utf-8")) == {"a": None, "b": 1}   # non-finite -> null


def test_pin_label_round_trips_so_recomputed_cache_keys_match_what_was_hashed():
    """The cache key hashes pin.label; annotating an old manifest rebuilds pins from the
    labels it recorded, so the rebuild has to be exact."""
    fams = {"deepseek/deepseek-v4-pro": "deepseek", "anthropic/claude-opus-5": "anthropic"}
    open_pin = mr.pin_from_label("deepseek/deepseek-v4-pro@StreamLake:fp8", fams)
    assert (open_pin.model_id, open_pin.provider_name, open_pin.precision) == (
        "deepseek/deepseek-v4-pro", "StreamLake", "fp8")
    closed = mr.pin_from_label("anthropic/claude-opus-5@-:-", fams)
    assert closed.provider_name is None and closed.precision is None
    assert closed.label == "anthropic/claude-opus-5@-:-"
