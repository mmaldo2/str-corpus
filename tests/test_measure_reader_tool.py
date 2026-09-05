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


def _score(macro, cpa, accepted, *, fidelity=0.99, decided=0.95):
    """A v2-shaped score (measure.score_candidate): two numbers per field, macro alongside."""
    return {"fidelity": fidelity, "macro": macro, "cost_per_accepted": cpa, "priced": True,
            "accepted": accepted, "accepted_full": accepted,
            "fields": {f: {"decided_rate": decided, "agreement_decided": macro,
                           "n_reference_decided": 155, "n_both_decided": 150,
                           "n_prediction_irrelevant": 0}
                       for f in ("relevant", "polarity", "who_was_letting")}}


def test_merge_manifest_never_drops_a_candidate_a_rerun_did_not_run():
    """I8. `--only <one model>` used to write a one-candidate document over the
    ten-candidate measurement: `selection.winner` was that candidate by construction and
    `spend_by_candidate` had lost the other nine, which also degrades the next run's
    ceiling guard (resolve_prior_spend). Git was the only thing preventing the loss."""
    prior = {
        "kit_sha256": "abc", "codebook": "mapper-v2", "total_task_spend_usd": 38.82,
        "pins": {"a/one": "a/one@-:-", "b/two": "b/two@-:-"},
        "scores": {"a/one": _score(0.70, 0.05, 195), "b/two": _score(0.60, 0.01, 190)},
        "spend_by_candidate": {"a/one": 9.71, "b/two": 1.90},
        "tracked_spend_by_candidate": {"a/one": 9.80, "b/two": 1.92},
        "failed": {"c/three": "no accepted records"}, "skipped": {}, "not_run": {},
        "selection": {"winner": "a/one"}, "winner_pin": "a/one@-:-", "stability": {"polarity": 0.82},
    }
    rerun = {                                   # what a `--only b/two` process builds on its own
        "kit_sha256": "abc", "codebook": "mapper-v2", "total_task_spend_usd": 40.0,
        "pins": {"b/two": "b/two@prov:fp8"},
        "scores": {"b/two": _score(0.62, 0.02, 193)},
        "spend_by_candidate": {"b/two": 2.10}, "tracked_spend_by_candidate": {"b/two": 2.11},
        "failed": {}, "skipped": {}, "not_run": {}, "selection": {"winner": "b/two"},
    }
    merged = mr.merge_manifest(prior, rerun)
    assert sorted(merged["scores"]) == ["a/one", "b/two"]                     # nothing dropped
    assert sorted(merged["spend_by_candidate"]) == ["a/one", "b/two"]
    assert merged["spend_by_candidate"] == {"a/one": 9.71, "b/two": 2.10}     # the re-run wins its own
    assert merged["pins"]["b/two"] == "b/two@prov:fp8" and merged["pins"]["a/one"] == "a/one@-:-"
    assert merged["failed"] == {"c/three": "no accepted records"}             # an old failure is still on record
    assert merged["stability"] == {"polarity": 0.82}                          # untouched whole-manifest fields survive
    assert merged["total_task_spend_usd"] == 40.0                             # the fresher process owns these
    # and the winner is decided over every candidate on record, not over the one re-run
    assert mr.select_reader(merged["scores"])["winner"] == "a/one"
    assert sorted(mr.select_reader(merged["scores"])["survivors"]) == ["a/one", "b/two"]


def test_the_tool_arms_the_norm_version_preflight():
    """I10. `Reader(prov, source, cache=cache, log=log, domain=dom)` omitted
    store_norm_version, so pre-flight check (1) was None and short-circuited - and 3B's
    live-store read, where the check is the whole point, would have copied that call."""
    from corpus_engine.domain import load_domain
    from corpus_engine.reader.codebook import load_codebook
    from corpus_engine.textnorm_version import NORM_VERSION

    assert mr.STORE_NORM_VERSION == f"v{NORM_VERSION}"
    dom = load_domain()
    cb = load_codebook(dom, dom.reader.codebook)
    assert cb.validated_norm_version == mr.STORE_NORM_VERSION      # the check passes, rather than being inert
    assert "store_norm_version=STORE_NORM_VERSION" in (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
