"""Guards on tools/measure_reader.py: the parts that decide how much may be spent and
how spend is attributed. Imported by path because tools/ is scripts, not a package."""
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from corpus_engine.reader.model import Plan, ReadingOutcome, StopReason

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


# --- Stage 3B slice 1: two transports, one tool -------------------------------------


def test_a_subscription_candidate_gets_a_cli_pin_and_a_unit_budget():
    """D1/D5: the subscription has no dollar price, so its ceilings are units and
    wall-clock. A usd budget over it is not a budget - `spend` would stay 0.0 for every
    request - and pre-flight refuses one (test_reader_claude_cli.py)."""
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    assert mr.is_subscription(cand) and not mr.is_subscription({"model_id": "z-ai/glm-5.3", "family": "zai"})
    pin = mr.cli_pin(cand)
    assert pin.label == "claude-cli/claude-sonnet-5@claude-cli:-" and pin.family == "anthropic"
    assert pin.extra == {"effort": "low", "cli_model": "claude-sonnet-5"}
    b = mr.budget_for(cand, 15.0)
    assert b.max_usd is None and b.max_units == mr.SUBSCRIPTION_MAX_UNITS
    assert b.max_wall_seconds == mr.SUBSCRIPTION_MAX_WALL_SECONDS
    b2 = mr.budget_for({"model_id": "z-ai/glm-5.3", "family": "zai"}, 12.5)
    assert b2.max_usd == 12.5 and b2.max_units is None and b2.max_wall_seconds is None
    assert mr.budget_for({"model_id": "x/y", "family": "f"}, -3.0).max_usd == 0.0


def test_the_openrouter_ceiling_for_this_slice_is_fifteen_dollars():
    assert mr.OPENROUTER_CEILING == 15.0
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "exceeds this slice's approved OpenRouter ceiling" in src
    assert "measurement-v2" in src and "record_schema(cb)" in src


def test_provider_for_returns_the_cli_transport_for_a_subscription_candidate(monkeypatch):
    cand = {"model_id": "claude-cli/claude-opus-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-opus-5"}
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    provider, pin, why = mr.provider_for(cand, None)
    assert provider.name == "claude-cli" and provider.cli_model == "claude-opus-5"
    assert pin.model_id == "claude-cli/claude-opus-5" and "2.1.258" in why
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: None)
    provider2, pin2, why2 = mr.provider_for(cand, None)
    assert provider2 is None and pin2 is None and "not available" in why2


def test_a_subscription_only_invocation_needs_no_openrouter_key():
    """If OPENROUTER_API_KEY is absent and only subscription candidates are selected the
    tool still runs: the key check and the /credits pre-read are conditioned on there
    being something to buy there, not on the flags."""
    sub = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
           "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    openr = {"model_id": "z-ai/glm-5.3", "family": "zai", "pin_open": True}
    assert mr.needs_openrouter([sub, openr]) and mr.needs_openrouter([openr])
    assert not mr.needs_openrouter([sub]) and not mr.needs_openrouter([])
    # and an OpenRouter candidate with no provider is skipped with a reason, never crashed on
    provider, pin, why = mr.provider_for(openr, None)
    assert provider is None and pin is None and "OPENROUTER_API_KEY" in why
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "if needs_openrouter(cands):" in src

    dom = SimpleNamespace(reader=SimpleNamespace(candidates=(sub, openr)))
    assert mr.selected_candidates(dom) == [sub, openr]
    assert mr.selected_candidates(dom, only="z-ai/glm-5.3") == [openr]
    assert mr.selected_candidates(dom, only="z-ai/glm-5.3", dry_run=sub["model_id"]) == [sub]


def test_the_subscription_unit_cap_scales_with_the_batch_list_it_is_given():
    """One request per batch plus the two split halves a parse failure falls back to. The
    winner's 5-case pair is four times as many units as the kit, so a fixed cap would stop
    it on `budget:units` and call that a result."""
    assert mr.subscription_unit_cap(23) == 3 * 23 + 3      # the 23-batch kit, halves included
    assert mr.subscription_unit_cap(92) == 3 * 92 + 3      # the 5-case pair over the same kit
    assert mr.subscription_unit_cap(1) == mr.SUBSCRIPTION_MAX_UNITS       # the floor binds below it
    assert mr.subscription_unit_cap(0) == mr.SUBSCRIPTION_MAX_UNITS


def _outcome(spend=0.0, wall=2.0):
    """A minimal real ReadingOutcome - the dataclasses, not a mock - so score_candidate
    and the dry-run payload run over the shapes they will see in the field."""
    pin = mr.ModelPin("m/x", "fam")
    plan = Plan("batch_extraction", (), "cb", pin, mr.Budget(), "reader")
    return ReadingOutcome(plan, [], [], spend, 0, 0, wall, StopReason("done"),
                          {"provider_reported": []}, "")


def _strict_fake_run(calls):
    """A stand-in for run_candidate with the v2 signature and an assertion on every
    position, so a call site left on the 3A ordering (pin, batches, source, dom, prov,
    budget, cache, log) fails here instead of at $15 a run."""
    def fake(pin, provider, budget, kit_batches, source, dom, cb, cache, log, budget_state):
        assert isinstance(pin, mr.ModelPin), pin
        assert hasattr(provider, "name"), provider
        assert isinstance(budget, mr.Budget), budget
        assert isinstance(kit_batches, list) and all("batch_id" in b for b in kit_batches)
        assert hasattr(source, "fetch") and hasattr(dom, "reader") and hasattr(cb, "sha")
        assert isinstance(cache, mr.ResponseCache) and callable(log) and isinstance(budget_state, dict)
        calls.append({"pin": pin.label, "provider": provider.name, "budget": budget,
                      "batches": [b["batch_id"] for b in kit_batches]})
        return _outcome()
    return fake


def _ctx(tmp_path, *, prov=None, before=None, logs=None):
    cases = [{"case_id": i} for i in range(1, 19)]
    batches = [{"batch_id": "b1", "era_partition": "1900s", "jurisdiction": "NY", "cases": cases}]
    reference = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable",
                  "who_was_letting": "householder"}]
    dom = SimpleNamespace(reader=SimpleNamespace(stability_sample="data/reader/kit-v1/sample-50.json",
                                                 families={}, candidates=()))
    cb = SimpleNamespace(id="mapper-v3", sha="deadbeef", judged_fields=("polarity",))
    source = SimpleNamespace(fetch=lambda ids: {})
    return mr.Ctx(batches=batches, reference=reference, source=source, dom=dom, cb=cb,
                  cache=mr.ResponseCache(tmp_path / "cache"), schema={"records": {}}, excl={},
                  budget={"remaining": 15.0, "spent": 0.0, "real_spent": 0.0},
                  prior_spend={}, spend_by={}, tracked_by={}, list_cost_by={},
                  ids50=set(range(1, 19)), prov=prov, before=before, ceiling=15.0,
                  log=(logs.append if logs is not None else (lambda *_a, **_k: None)))


def test_run_candidate_has_the_v2_signature_everywhere():
    """R10: the pin/provider/budget signature is applied at ALL call sites - the kit run,
    the batch-size pair and both stability reads - so no 3A ordering survives."""
    assert list(inspect.signature(mr.run_candidate).parameters) == [
        "pin", "provider", "budget", "kit_batches", "source", "dom", "cb", "cache", "log",
        "budget_state"]


def test_the_winners_checks_drive_the_subscription_transport_and_never_touch_credits(tmp_path, monkeypatch):
    """A subscription winner is checked on its own transport and its own budget kind: no
    /credits read (there is no balance to reconcile and possibly no key at all), no dollar
    ceiling, and a unit cap sized to the batch list each check actually reads."""
    calls, logs = [], []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr, "reconcile", lambda *a, **k: pytest.fail("a subscription run reconciled credits"))
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    ctx = _ctx(tmp_path, logs=logs)
    sp = tmp_path / "stability" / "mapper-v3.json"
    m = mr.winner_checks(ctx, cand["model_id"], mr.cli_pin(cand),
                         SimpleNamespace(name="claude-cli"), cand, _score(0.86, 0.0, 200),
                         sp, "2026-09-05T00:00:00")

    assert [c["batches"] for c in calls] == [["b1-s1", "b1-s2", "b1-s3", "b1-s4"],
                                             ["b1-st1"], ["b1-st2"]]
    assert {c["pin"] for c in calls} == {"claude-cli/claude-sonnet-5@claude-cli:-"}
    for c, n in zip(calls, (4, 1, 1)):
        assert c["budget"].max_usd is None                       # never a dollar ceiling
        assert c["budget"].max_units == mr.subscription_unit_cap(n)
        assert c["budget"].max_wall_seconds == mr.SUBSCRIPTION_MAX_WALL_SECONDS
    assert m["batch_size_pair"]["b5"] is not None and m["batch_size_pair"]["b18"]["macro"] == 0.86
    assert set(m["stability"]) == {"relevant", "polarity", "who_was_letting"}
    assert m["stable"] is False and m["stability_stops"] == ["done", "done"]
    rec = json.loads(sp.read_text(encoding="utf-8"))
    assert rec["model_pin"] == "claude-cli/claude-sonnet-5@claude-cli:-" and rec["bar"] == 0.90
    assert ctx.spend_by[cand["model_id"] + ":stab1"] == 0.0      # unpriced, not cheap


def test_the_winners_checks_reconcile_credits_for_an_openrouter_winner(tmp_path, monkeypatch):
    calls, settled = [], []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr, "reconcile", lambda prov, before, ceiling, budget, log: settled.append(1) or 0.25)
    cand = {"model_id": "z-ai/glm-5.3", "family": "zai", "pin_open": True}
    ctx = _ctx(tmp_path, prov=SimpleNamespace(name="openrouter"), before=100.0)
    wpin = mr.ModelPin("z-ai/glm-5.3", "zai", "Fireworks", "bf16", {"reasoning": mr.REASONING})
    m = mr.winner_checks(ctx, cand["model_id"], wpin, SimpleNamespace(name="openrouter"), cand,
                         _score(0.80, 0.01, 190), tmp_path / "st.json", "2026-09-05T00:00:00")
    assert len(settled) == 3                                     # after every paid run, as in 3A
    for c in calls:
        assert c["budget"].max_usd == 15.0 and c["budget"].max_units is None
    assert m["batch_size_pair"]["b5"]["priced"] is True
    assert ctx.spend_by["z-ai/glm-5.3:stab1"] == 0.25            # the credits delta, not the tracker


def test_a_dry_run_buys_one_batch_writes_the_diagnostics_and_selects_nothing(tmp_path, monkeypatch):
    """The gate before any field run. It writes into the SAME cache and measurement
    directory, so the field run replays the batch for free rather than re-buying it."""
    calls = []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    ctx = _ctx(tmp_path)
    assert mr.dry_run([cand], 1, ctx, tmp_path / "measurement-v2") == 0
    assert [c["batches"] for c in calls] == [["b1"]]
    p = tmp_path / "measurement-v2" / "dry-run-claude-cli_claude-sonnet-5.json"
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["provider"] == "claude-cli" and payload["pin"].endswith("@claude-cli:-")
    assert payload["budget"] == {"max_usd": None, "max_units": mr.subscription_unit_cap(1),
                                 "max_wall_seconds": mr.SUBSCRIPTION_MAX_WALL_SECONDS}
    assert payload["effort"] == "low" and payload["read_timeout_seconds"] == 1500
    assert payload["spend_usd"] == 0.0 and payload["schema_sha"] and "status_counts" in payload
    assert set(payload["status_counts"]) == {"ok", "partial", "extraction-invalid", "missing"}
    assert "selection" not in payload and not (tmp_path / "measurement-v2" / "manifest.json").exists()


def test_an_openrouter_dry_run_is_capped_far_below_the_slice_ceiling(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr, "reconcile", lambda *a, **k: 0.4)
    monkeypatch.setattr(mr, "pin_for", lambda cand, prov: (mr.ModelPin(cand["model_id"], cand["family"],
                                                                      extra={"reasoning": mr.REASONING}),
                                                           "closed-weight model"))
    cand = {"model_id": "google/gemini-3.7-flash", "family": "google"}
    ctx = _ctx(tmp_path, prov=SimpleNamespace(name="openrouter"), before=100.0)
    assert mr.dry_run([cand], 2, ctx, tmp_path / "measurement-v2") == 0
    assert calls[0]["budget"].max_usd == mr.DRY_RUN_MAX_USD == 2.0
    assert calls[0]["batches"] == ["b1"]                          # the kit here is one batch long
