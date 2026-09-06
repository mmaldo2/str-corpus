"""Guards on tools/measure_reader.py: the parts that decide how much may be spent and
how spend is attributed. Imported by path because tools/ is scripts, not a package."""
import importlib.util
import inspect
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from corpus_engine.domain import load_domain
from corpus_engine.reader.codebook import load_codebook
from corpus_engine.reader.model import (Plan, ReadingOutcome, RecordResult, Response,
                                        StopReason, Unit, UnitResult)
from corpus_engine.reader.providers import factory

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


def test_a_subscription_only_invocation_needs_no_openrouter_key(monkeypatch):
    """If OPENROUTER_API_KEY is absent and only subscription candidates are selected the
    tool still runs: the key check and the /credits pre-read are conditioned on there
    being something to buy there, not on the flags."""
    sub = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
           "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    openr = {"model_id": "z-ai/glm-5.3", "family": "zai", "pin_open": True}
    assert mr.needs_openrouter([sub, openr]) and mr.needs_openrouter([openr])
    assert not mr.needs_openrouter([sub]) and not mr.needs_openrouter([])
    # R1: an OpenRouter candidate called with no provider is a caller error, not a runtime
    # condition to report a reason for - `needs_openrouter` is what keeps main() from ever
    # making this call with prov=None for a real OpenRouter candidate.
    with pytest.raises(ValueError, match="z-ai/glm-5.3"):
        mr.provider_for(openr, None)
    # a subscription candidate needs no provider at all - the single-argument call resolves it
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: "2.1.258 (Claude Code)")
    assert mr.provider_for(sub)[1].model_id == sub["model_id"]
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "if needs_openrouter(cands):" in src

    dom = SimpleNamespace(reader=SimpleNamespace(candidates=(sub, openr)))
    assert mr.selected_candidates(dom) == [sub, openr]
    assert mr.selected_candidates(dom, only="z-ai/glm-5.3") == [openr]
    assert mr.selected_candidates(dom, only="z-ai/glm-5.3", dry_run=sub["model_id"]) == [sub]


def test_the_process_unit_cap_counts_every_subscription_read_the_process_will_make():
    """Review finding 1: the cap is a PROCESS budget, so it has to cover both subscription
    candidates over the kit AND the winner's checks - counted from the batches actually
    selected, not guessed."""
    cases = [{"case_id": i} for i in range(1, 19)]
    batches = [{"batch_id": f"b{n}", "era_partition": "e", "jurisdiction": "j", "cases": cases}
               for n in range(1, 24)]                       # the 23-batch kit
    plan = mr.process_unit_cap(2, batches, set(range(1, 19)))
    assert plan["kit"] == 2 * 23                            # one request per batch per candidate
    assert plan["batch_size_pair"] == 4 * 23                # 18 cases split into 5s is four units
    assert plan["stability"] == 2 * 23                      # two reads of the sampled batches
    assert plan["margin"] == mr.SUBSCRIPTION_UNIT_MARGIN
    assert plan["total"] == 46 + 92 + 46 + 10
    # no subscription candidate selected: nothing to budget for
    assert mr.process_unit_cap(0, batches, set(range(1, 19)))["total"] == 0


def _outcome(spend=0.0, wall=2.0, unpriced=0):
    """A minimal real ReadingOutcome - the dataclasses, not a mock - so score_candidate
    and the dry-run payload run over the shapes they will see in the field. `unpriced` is
    the driver's count of paid-but-unpriced requests, which is exactly how many CLI calls a
    subscription read made and what the process-wide unit counter draws on."""
    pin = mr.ModelPin("m/x", "fam")
    plan = Plan("batch_extraction", (), "cb", pin, mr.Budget(), "reader")
    return ReadingOutcome(plan, [], [], spend, 0, 0, wall, StopReason("done"),
                          {"provider_reported": [], "unpriced_requests": unpriced}, "")


def _ticking_clock(step=100.0):
    """A deterministic clock that advances `step` seconds on every read, so a shrinking
    wall-clock budget can be asserted exactly."""
    t = {"now": 0.0}

    def clock():
        t["now"] += step
        return t["now"]
    return clock


def _strict_fake_run(calls, *, unpriced=0):
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
        return _outcome(unpriced=unpriced)
    return fake


def _ctx(tmp_path, *, prov=None, before=None, logs=None, sub_units_cap=60,
         sub_max_wall=mr.SUBSCRIPTION_MAX_WALL_SECONDS, clock=time.time):
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
                  sub_units_cap=sub_units_cap, sub_max_wall=sub_max_wall, clock=clock,
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
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls, unpriced=5))
    monkeypatch.setattr(mr, "reconcile", lambda *a, **k: pytest.fail("a subscription run reconciled credits"))
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    ctx = _ctx(tmp_path, logs=logs, sub_units_cap=60, clock=_ticking_clock())
    sp = tmp_path / "stability" / "mapper-v3.json"
    m = mr.winner_checks(ctx, cand["model_id"], mr.cli_pin(cand),
                         SimpleNamespace(name="claude-cli"), cand, _score(0.86, 0.0, 200),
                         sp, "2026-09-05T00:00:00")

    assert [c["batches"] for c in calls] == [["b1-s1", "b1-s2", "b1-s3", "b1-s4"],
                                             ["b1-st1"], ["b1-st2"]]
    assert {c["pin"] for c in calls} == {"claude-cli/claude-sonnet-5@claude-cli:-"}
    # the three checks share ONE unit counter and ONE deadline, both shrinking as they run
    assert [c["budget"].max_units for c in calls] == [60, 55, 50]
    assert ctx.budget["sub_units"] == 15
    walls = [c["budget"].max_wall_seconds for c in calls]
    assert walls == sorted(walls, reverse=True) and len(set(walls)) == 3
    assert all(0 < wsec <= mr.SUBSCRIPTION_MAX_WALL_SECONDS for wsec in walls)
    for c in calls:
        assert c["budget"].max_usd is None                       # never a dollar ceiling
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
    assert payload["budget"] == {"max_usd": None, "max_units": 60,
                                 "max_wall_seconds": mr.SUBSCRIPTION_MAX_WALL_SECONDS}
    assert payload["effort"] == "low" and payload["read_timeout_seconds"] == 1500
    assert payload["spend_usd"] == 0.0 and payload["schema_sha"] and "status_counts" in payload
    assert set(payload["status_counts"]) == {"ok", "partial", "extraction-invalid", "missing"}
    # It selects nothing - no scores, no selection - but it does record what it spent, so
    # the field run can find it (see the dedicated dry-run-spend test below).
    m = json.loads((tmp_path / "measurement-v2" / "manifest.json").read_text(encoding="utf-8"))
    assert "selection" not in payload and "selection" not in m and not m.get("scores")
    assert m["dry_runs"]["claude-cli/claude-sonnet-5"]["batches"] == ["b1"]


def test_an_openrouter_dry_run_is_capped_far_below_the_slice_ceiling(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr, "reconcile", lambda *a, **k: 0.4)
    monkeypatch.setattr(factory, "pin_for", lambda cand, prov: (mr.ModelPin(cand["model_id"], cand["family"],
                                                                      extra={"reasoning": mr.REASONING}),
                                                           "closed-weight model"))
    cand = {"model_id": "google/gemini-3.7-flash", "family": "google"}
    ctx = _ctx(tmp_path, prov=SimpleNamespace(name="openrouter"), before=100.0)
    assert mr.dry_run([cand], 2, ctx, tmp_path / "measurement-v2") == 0
    assert calls[0]["budget"].max_usd == mr.DRY_RUN_MAX_USD == 2.0
    assert calls[0]["batches"] == ["b1"]                          # the kit here is one batch long


# --- fix round 1: the money and window paths the review flagged ---------------------


def test_a_second_subscription_candidate_draws_on_the_same_process_ceilings(tmp_path):
    """Review finding 1. The units and the deadline belong to the PROCESS, not to a read:
    five subscription reads each handed a fresh 6 h window is a 30 h window nobody typed."""
    c1 = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
          "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    c2 = {"model_id": "claude-cli/claude-opus-5", "family": "anthropic",
          "provider": "claude-cli", "cli_model": "claude-opus-5"}
    ctx = _ctx(tmp_path, sub_units_cap=25, clock=_ticking_clock(10.0))

    b1 = ctx.budget_for_run(c1, ctx.batches)
    assert b1.max_units == 25 and b1.max_usd is None
    ctx.settle(c1, _outcome(unpriced=20))                    # the first candidate used 20
    b2 = ctx.budget_for_run(c2, ctx.batches)
    assert b2.max_units == 5                                 # the second gets what is left
    assert b2.max_wall_seconds < b1.max_wall_seconds         # off one shared deadline
    ctx.settle(c2, _outcome(unpriced=9))                     # it ran over by four
    assert ctx.budget["sub_units"] == 29
    # clamped at zero, never negative: max_units 0 trips check_budget before the next request
    assert ctx.budget_for_run(c2, ctx.batches).max_units == 0

    # and the window closes the same way
    past = _ctx(tmp_path, sub_units_cap=25, sub_max_wall=5.0, clock=_ticking_clock(100.0))
    assert past.budget_for_run(c1, past.batches).max_wall_seconds == 0.0


def test_dry_run_batches_requires_a_named_candidate_and_refuses_zero(monkeypatch):
    """Review finding 2. Two sharp edges on a money flag: a batch count alone used to
    dry-run every candidate, and `0` - the natural spelling of "buy nothing" - was falsy and
    fell through to the paid five-candidate field run. Both are refused at parse time, before
    the domain is even loaded."""
    monkeypatch.setattr(mr, "load_domain", lambda: pytest.fail("main got past the flag guards"))
    with pytest.raises(SystemExit) as alone:
        mr.main(["--dry-run-batches", "3"])
    assert "names no candidate" in str(alone.value)
    with pytest.raises(SystemExit) as zero:
        mr.main(["--dry-run-batches", "0", "--dry-run", "claude-cli/claude-sonnet-5"])
    assert "buys nothing" in str(zero.value)
    with pytest.raises(SystemExit) as over:
        mr.main(["--max-usd", "20"])
    assert "exceeds this slice's approved OpenRouter ceiling" in str(over.value)


def _outcome_scored(spend=0.5, *, cost=None, case_id=1, unpriced=0, cache_hit=False):
    """One accepted, fully-judged record, so `score_candidate` returns a real v2 score and
    the candidate is not thrown out as "no accepted records". `cost=None` on the response is
    what makes a run unpriced, which is how a subscription read is recognised."""
    pin = mr.ModelPin("m/x", "fam")
    unit = Unit("b1", (case_id,), {})
    plan = Plan("batch_extraction", (unit,), "cb", pin, mr.Budget(), "reader")
    rec = {"case_id": case_id, "relevant": True, "polarity": "favorable",
           "who_was_letting": "householder", "extraction_status": "ok",
           "quotes": [{"text": "q", "supports": ["relevant"]}]}
    resp = Response("{}", 10, 10, cost, {"provider": "p"}, "stop")
    ur = UnitResult("b1", "ok", (RecordResult(case_id, rec, "ok", 0, ()),), resp, cache_hit)
    return ReadingOutcome(plan, [ur], [], spend, 10, 10, 3.0, StopReason("done"),
                          {"provider_reported": ["p"], "unpriced_requests": unpriced}, "")


def _main_env(tmp_path, monkeypatch, candidates, *, prior=None):
    """Drive `main()` over a fake domain, kit and codebook rooted in tmp_path. Issues no
    request: `provider_for` and `run_candidate` are supplied by each test, and `keys_for` is
    stubbed because the fake codebook cannot render a prompt. Returns the manifest path."""
    monkeypatch.setattr(mr, "ROOT", tmp_path)
    batches = [{"batch_id": "b1", "era_partition": "e", "jurisdiction": "j",
                "cases": [{"case_id": 1}]}]
    reference = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable",
                  "who_was_letting": "householder"}]
    dom = SimpleNamespace(reader=SimpleNamespace(
        candidates=tuple(candidates), families={}, codebook="mapper-v3",
        kit_path="data/reader/kit-v2/kit.json", kit_sha256=None,
        stability_sample="data/reader/kit-v2/sample-50.json"))
    kit_dir = tmp_path / "data" / "reader" / "kit-v2"
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.json").write_text("{}", encoding="utf-8")
    (kit_dir / "sample-50.json").write_text("[1]", encoding="utf-8")
    cb = SimpleNamespace(id="mapper-v3", sha="deadbeef", judged_fields=("polarity",))
    monkeypatch.setattr(mr, "load_domain", lambda: dom)
    monkeypatch.setattr(mr, "load_kit", lambda p: (reference, batches,
                                                   SimpleNamespace(fetch=lambda ids: {})))
    monkeypatch.setattr(mr, "load_codebook", lambda d, name: cb)
    monkeypatch.setattr(mr, "stability_path", lambda d, c: tmp_path / "stability" / "mapper-v3.json")
    monkeypatch.setattr(mr, "keys_for", lambda *a, **k: {"b1": "cachekey"})
    monkeypatch.setattr(mr, "dry_run", lambda *a, **k: pytest.fail("entered the dry-run path"))
    out_dir = tmp_path / "data" / "reader" / "measurement-v2"
    if prior is not None:
        mr.write_json(out_dir / "manifest.json", prior, indent=1, sort_keys=True)
    return out_dir / "manifest.json"


def _openrouter_env(monkeypatch, credits):
    """A key, a provider and a credits series - so `reconcile` is the real one and the
    per-candidate deltas are real arithmetic over the numbers the series returns."""
    seq = iter(credits)
    last = {"v": credits[-1]}

    def remaining(prov):
        last["v"] = next(seq, last["v"])
        return last["v"]
    monkeypatch.setattr(mr.store, "env_value", lambda name: "test-key")
    monkeypatch.setattr(mr, "OpenRouterProvider", lambda key, **kw: SimpleNamespace(name="openrouter"))
    monkeypatch.setattr(mr, "credits_remaining", remaining)


def test_the_manifest_is_written_even_when_the_run_raises_after_a_paid_candidate(tmp_path, monkeypatch):
    """Review finding 3. The manifest was written once, at the very end, so anything raising
    after candidates 1..n were bought lost this process's spend - and the NEXT run's
    `resolve_prior_spend` then under-counts and re-grants a ceiling that was already spent.
    That is the one failure mode here that can end in real overspend."""
    cands = [{"model_id": f"m/{n}", "family": "f"} for n in (1, 2, 3)]
    manifest_path = _main_env(tmp_path, monkeypatch, cands)
    _openrouter_env(monkeypatch, [100.0, 99.5, 99.0, 98.5])
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.5, cost=0.5))
    seen = {"n": 0}

    def blow_up(*a, **k):
        seen["n"] += 1
        if seen["n"] == 3:
            raise RuntimeError("cache-key derivation blew up")
        return {"b1": "cachekey"}
    monkeypatch.setattr(mr, "keys_for", blow_up)

    with pytest.raises(RuntimeError):
        mr.main([])
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    # every candidate that was actually charged for is on record, the third included: its
    # money was spent before the derivation raised, so losing it is what must not happen
    assert sorted(m["scores"]) == ["m/1", "m/2", "m/3"]
    assert m["spend_by_candidate"] == {"m/1": 0.5, "m/2": 0.5, "m/3": 0.5}
    assert m["spent_usd"] == 1.5 and m["total_task_spend_usd"] == 1.5
    assert "raised before it finished" in m["incomplete"]
    assert m["selection"]["winner"] in ("m/1", "m/2", "m/3")          # and it still selected


def test_a_candidate_that_raises_while_being_resolved_is_recorded_not_fatal(tmp_path, monkeypatch):
    """Review finding 3, the other half: `provider_for` sat outside the per-candidate try, so
    a malformed candidate in domain.yaml (`provider: claude-cli` with no `cli_model`) took the
    whole measurement with it."""
    cands = [{"model_id": f"m/{n}", "family": "f"} for n in (1, 2, 3)]
    manifest_path = _main_env(tmp_path, monkeypatch, cands)
    _openrouter_env(monkeypatch, [100.0, 99.5, 99.0, 98.9, 98.8, 98.7, 98.6])

    def resolve(cand, prov):
        if cand["model_id"] == "m/3":
            raise KeyError("cli_model")
        return SimpleNamespace(name="openrouter"), mr.ModelPin(cand["model_id"], cand["family"]), "fake"
    monkeypatch.setattr(mr, "provider_for", resolve)
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.5, cost=0.5))

    assert mr.main([]) == 0                                          # the run still completes
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sorted(m["scores"]) == ["m/1", "m/2"]
    assert "KeyError" in m["failed"]["m/3"] and "incomplete" not in m
    assert m["selection"]["winner"] in ("m/1", "m/2")


def test_a_subscription_only_run_does_not_erase_an_earlier_openrouter_run_s_money(tmp_path, monkeypatch):
    """Review finding 6. A run that charged nothing must not write its zero over what an
    earlier OpenRouter process recorded in the same manifest."""
    cand = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
            "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    prior = {"spent_usd": 12.5, "credits_before": 100.0, "credits_after": 87.5,
             "total_task_spend_usd": 12.5, "scores": {}, "pins": {}}
    manifest_path = _main_env(tmp_path, monkeypatch, [cand], prior=prior)
    monkeypatch.setattr(mr.store, "env_value", lambda name: pytest.fail("read the OpenRouter key"))
    monkeypatch.setattr(mr, "credits_remaining", lambda p: pytest.fail("called /credits"))
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="claude-cli"), mr.cli_pin(c), "fake cli"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.0, cost=None, unpriced=1))

    assert mr.main([]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["spent_usd"] == 12.5 and m["credits_before"] == 100.0 and m["credits_after"] == 87.5
    assert m["total_task_spend_usd"] == 12.5                 # nothing new was charged
    assert m["priced_by_candidate"] == {"claude-cli/claude-sonnet-5": False}
    assert m["spend_by_candidate"]["claude-cli/claude-sonnet-5"] == 0.0
    assert m["subscription_budget"]["units_used"] >= 1       # the shared counter did move


def test_priced_by_candidate_survives_an_only_rerun():
    """Review finding 4: it was built from this process's scores alone and left out of the
    merge, so an `--only` re-run left a one-candidate map beside a five-candidate `scores` -
    the exact class of bug merge_manifest exists to prevent."""
    assert "priced_by_candidate" in mr.MERGE_BY_CANDIDATE
    merged = mr.merge_manifest({"priced_by_candidate": {"a/one": True, "b/two": False}},
                               {"priced_by_candidate": {"b/two": True}})
    assert merged["priced_by_candidate"] == {"a/one": True, "b/two": True}


def test_a_dry_run_records_an_unavailable_candidate_and_still_runs_the_rest(tmp_path, monkeypatch):
    """Review finding 7: `sys.exit` mid-loop killed the process after earlier candidates had
    already been bought. The gate now finishes and reports non-zero."""
    calls = []
    monkeypatch.setattr(mr, "run_candidate", _strict_fake_run(calls))
    monkeypatch.setattr(mr.ClaudeCliProvider, "version", lambda self: None)      # cli not on PATH
    monkeypatch.setattr(mr, "reconcile", lambda *a, **k: 0.0)
    monkeypatch.setattr(factory, "pin_for",
                        lambda c, p: (mr.ModelPin(c["model_id"], c["family"],
                                                  extra={"reasoning": mr.REASONING}), "closed-weight"))
    bad = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
           "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    good = {"model_id": "google/gemini-3.7-flash", "family": "google"}
    ctx = _ctx(tmp_path, prov=SimpleNamespace(name="openrouter"), before=100.0)
    out_dir = tmp_path / "measurement-v2"

    assert mr.dry_run([bad, good], 1, ctx, out_dir) == 1              # non-zero: one failed
    assert [c["pin"] for c in calls] == ["google/gemini-3.7-flash@-:-"]
    assert (out_dir / "dry-run-google_gemini-3.7-flash.json").exists()
    assert not (out_dir / "dry-run-claude-cli_claude-sonnet-5.json").exists()


def test_the_v1_inputs_can_only_be_named_for_the_offline_annotation(monkeypatch):
    """domain.yaml now names mapper-v3 and kit v2, so re-deriving measurement-v1's records
    means naming v1's codebook, kit and sample. Those overrides skip the kit sha256 check,
    so a run that spends must never accept them."""
    monkeypatch.setattr(mr, "load_domain", lambda: pytest.fail("main got past the override guard"))
    for flag, value in (("--codebook", "mapper-v2"),
                        ("--kit-path", "data/reader/kit-v1/kit.json"),
                        ("--stability-sample", "data/reader/kit-v1/sample-50.json")):
        with pytest.raises(SystemExit) as exc:
            mr.main([flag, value])
        assert "may only be passed with --annotate-only" in str(exc.value)
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "sha256 not verified" in src              # and the annotation says so out loud


# --- fix round 2: the selection defects the 2026-09-05 field run exposed --------------


def test_the_tool_hands_select_reader_pin_labels_for_the_subscription_tie_break():
    """Defect 1. The tie-break is keyed on pin labels (`measure.subscription_keys`), so the
    tool has to pass labels: the pins it built this process, the subscription labels a prior
    manifest recorded, and the label `cli_pin` builds for a candidate that never got a pin."""
    sub = {"model_id": "claude-cli/claude-sonnet-5", "family": "anthropic",
           "provider": "claude-cli", "cli_model": "claude-sonnet-5"}
    openr = {"model_id": "google/gemini-3.7-flash", "family": "google"}
    dom = SimpleNamespace(reader=SimpleNamespace(candidates=(sub, openr), families={}))

    assert mr.subscription_labels(dom) == {"claude-cli/claude-sonnet-5@claude-cli:-"}
    # a subscription pin only a prior manifest knows about is recognised from its label
    prior = {"pins": {"claude-cli/claude-opus-5": "claude-cli/claude-opus-5@claude-cli:-",
                      "google/gemini-3.7-flash": "google/gemini-3.7-flash@-:-"}}
    assert mr.subscription_labels(dom, {}, prior) == {
        "claude-cli/claude-sonnet-5@claude-cli:-", "claude-cli/claude-opus-5@claude-cli:-"}
    assert mr.label_provider("google/gemini-3.7-flash@-:-") is None
    assert mr.label_provider("z-ai/glm-5.3@AkashML:fp8") == "AkashML"

    # a malformed subscription candidate (no cli_model) is skipped, never a KeyError that
    # would take the whole selection with it
    bad = SimpleNamespace(reader=SimpleNamespace(candidates=({"model_id": "x/y", "family": "f",
                                                              "provider": "claude-cli"},),
                                                 families={}))
    assert mr.subscription_labels(bad) == set()
    src = (ROOT / "tools" / "measure_reader.py").read_text(encoding="utf-8")
    assert "subscription=subscription_labels(dom, pins, prior)" in src


def test_a_cache_hit_covered_by_recorded_spend_is_priced_rather_than_written_off():
    """Defect 2b. The 2026-09-05 field run scored gemini [UNPRICED] with cost_per_accepted
    inf against $0.94 of real, reconciled spend, because its first kit batch replayed from
    the dry run's cache. A cache hit is a unit an earlier process PAID for, not the absence
    of a price: the figure is the credits delta plus what that earlier process recorded."""
    ref = [{"case_id": 1, "source": "human", "relevant": True, "polarity": "favorable",
            "who_was_letting": "householder"}]
    spend_by, tracked_by = {}, {}
    s = mr.score(_outcome_scored(0.60, cost=0.60, cache_hit=True), ref, "google/gemini-3.7-flash",
                 {"google/gemini-3.7-flash": 0.34}, spend_by, tracked_by, 0.60)
    assert s["priced"] is True and math.isfinite(s["cost_per_accepted"])
    assert abs(s["spend_usd"] - 0.94) < 1e-9            # real_delta 0.60 + recorded 0.34
    assert spend_by["google/gemini-3.7-flash"] == 0.94
    assert tracked_by["google/gemini-3.7-flash"] == 0.6
    assert "[UNPRICED]" not in mr.line(s)

    # a credits reading alone is enough: one cached unit no longer condemns the candidate
    s2 = mr.score(_outcome_scored(0.60, cost=0.60, cache_hit=True), ref, "g", {}, {}, {}, 0.60)
    assert s2["priced"] is True and abs(s2["spend_usd"] - 0.60) < 1e-9

    # and the one case that really has no figure to quote is still unpriced, never cheap
    s3 = mr.score(_outcome_scored(0.0, cost=0.60, cache_hit=True), ref, "g", {}, {}, {}, None)
    assert s3["priced"] is False and s3["cost_per_accepted"] == math.inf
    assert "[UNPRICED]" in mr.line(s3)


def test_a_dry_run_records_its_spend_so_the_field_run_can_price_the_units_it_replays(
        tmp_path, monkeypatch):
    """Defect 2a. The dry-run dispatch sits outside main's try/finally, so its money was
    recorded nowhere: the next run's `resolve_prior_spend` could not see it, and `score`
    found no recorded figure for the units the field run then replayed from its cache."""
    cand = {"model_id": "g/one", "family": "google"}
    real_dry_run = mr.dry_run
    manifest_path = _main_env(tmp_path, monkeypatch, [cand])
    monkeypatch.setattr(mr, "dry_run", real_dry_run)          # this test IS the dry-run path
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.6, cost=0.6))

    _openrouter_env(monkeypatch, [100.0, 99.4])
    assert mr.main(["--dry-run", "g/one"]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["spend_by_candidate"] == {"g/one": 0.6} and m["total_task_spend_usd"] == 0.6
    assert m["tracked_spend_by_candidate"] == {"g/one": 0.6}
    assert m["pins"] == {"g/one": "g/one@-:-"} and m["dry_runs"]["g/one"]["batches"] == ["b1"]
    assert not m.get("scores") and "selection" not in m    # a one-batch read is not a measurement

    # the field run now replays that batch from cache and still prices the candidate
    monkeypatch.setattr(mr, "run_candidate",
                        lambda *a, **k: _outcome_scored(0.0, cost=0.6, cache_hit=True))
    _openrouter_env(monkeypatch, [99.4, 99.0, 99.0])
    assert mr.main([]) == 0
    m2 = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m2["scores"]["g/one"]["priced"] is True
    assert m2["priced_by_candidate"] == {"g/one": True}
    assert abs(m2["scores"]["g/one"]["spend_usd"] - 1.0) < 1e-9    # 0.4 charged now + 0.6 then
    assert m2["spend_by_candidate"]["g/one"] == 1.0
    assert m2["prior_spend_usd"] == 0.6 and m2["total_task_spend_usd"] == 1.0


def _pinned_scores(by_key):
    """Wrap the real `score` so a `main()` test can pin the macro and the decided rates a
    candidate is credited with, while the spend arithmetic underneath stays real."""
    real = mr.score

    def fake(out, reference, key, *a, **k):
        s = real(out, reference, key, *a, **k)
        spec = by_key.get(key)
        if spec:
            s["macro"] = spec.get("macro", s["macro"])
            for f, rate in (spec.get("decided") or {}).items():
                s["fields"][f]["decided_rate"] = rate
        return s
    return fake


def _prior_with_another_candidates_checks():
    """A manifest whose stability and batch-size pair were earned by b/two, while a/one is
    the candidate a recomputed selection now crowns."""
    return {
        "pins": {"a/one": "a/one@-:-", "b/two": "b/two@-:-"},
        "scores": {"a/one": _score(0.95, 0.05, 190), "b/two": _score(0.60, 0.02, 180)},
        "spend_by_candidate": {"a/one": 1.0, "b/two": 1.0},
        "tracked_spend_by_candidate": {"a/one": 1.0, "b/two": 1.0},
        "total_task_spend_usd": 2.0, "selection": {"winner": "b/two"}, "winner_pin": "b/two@-:-",
        "stability": {"polarity": {"agreement_decided": 0.99, "decided_rate_b": 1.0}},
        "stable": True, "stability_stops": ["done", "done"],
        "batch_size_pair": {"b18": _score(0.60, 0.02, 180), "b5": _score(0.61, 0.02, 180)},
    }


def test_a_recomputed_winner_never_inherits_another_candidates_stability(tmp_path, monkeypatch):
    """3A N5 / defect 3. Selection is recomputed over every candidate on record, so the
    winner can be one this process did not run - and the stability and batch-size pair
    already in the manifest may belong to somebody else. `merge_manifest` keeps
    whole-manifest fields, so saying nothing republished b/two's stability as a/one's."""
    prior = _prior_with_another_candidates_checks()
    cands = [{"model_id": m, "family": "f"} for m in ("a/one", "b/two", "c/three")]
    manifest_path = _main_env(tmp_path, monkeypatch, cands, prior=prior)
    _openrouter_env(monkeypatch, [100.0] + [99.5] * 8)
    pins_run = []

    def resolve(cand, prov):
        pins_run.append(cand["model_id"])
        return SimpleNamespace(name="openrouter"), mr.ModelPin(cand["model_id"], cand["family"]), "fake"
    monkeypatch.setattr(mr, "provider_for", resolve)
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.1, cost=0.1))
    monkeypatch.setattr(mr, "score", _pinned_scores({"c/three": {"macro": 0.50}}))

    assert mr.main(["--only", "c/three"]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["selection"]["winner"] == "a/one"                  # not run here, and not b/two
    assert m["winner_pin"] == "a/one@-:-"
    assert m["stability"] != prior["stability"]                 # b/two's numbers are gone
    assert m["batch_size_pair"] != prior["batch_size_pair"]
    assert "a/one" in m["winner_checks_source"] and "recomputed winner" in m["winner_checks_source"]
    assert set(m["stability"]) == {"relevant", "polarity", "who_was_letting"}
    assert pins_run.count("a/one") == 1                        # resolved once, for the checks


def test_checks_that_cannot_be_run_for_the_new_winner_are_marked_missing(tmp_path, monkeypatch):
    """The other half of defect 3: when the recomputed winner's checks cannot be run - it is
    not a candidate in domain.yaml, or the budget is gone - every field they would have
    written is recorded as null with the reason, rather than left showing another
    candidate's numbers."""
    prior = _prior_with_another_candidates_checks()
    prior["scores"]["d/four"] = _score(0.99, 0.01, 200)         # gone from domain.yaml
    prior["pins"]["d/four"] = "d/four@-:-"
    cands = [{"model_id": m, "family": "f"} for m in ("a/one", "b/two", "c/three")]
    manifest_path = _main_env(tmp_path, monkeypatch, cands, prior=prior)
    _openrouter_env(monkeypatch, [100.0, 99.5, 99.5])
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.1, cost=0.1))
    monkeypatch.setattr(mr, "score", _pinned_scores({"c/three": {"macro": 0.50}}))

    assert mr.main(["--only", "c/three"]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["selection"]["winner"] == "d/four" and m["winner_pin"] == "d/four@-:-"
    assert all(m[f] is None for f in mr.WINNER_CHECK_FIELDS)
    assert m["winner_checks_missing"]["recorded_checks_belong_to"] == "b/two"
    assert "not a candidate in domain.yaml" in m["winner_checks_missing"]["reason"]
    assert m["winner_checks_source"].startswith("missing:")
    assert mr.prior_checks_owner(prior) == "b/two"
    assert mr.prior_checks_owner({}) is None


def test_a_winners_own_recorded_checks_are_still_carried_forward(tmp_path, monkeypatch):
    """The carry-forward is not removed, only narrowed to the case it was always meant for:
    the manifest says these checks were recorded FOR this winner, so nothing is re-bought."""
    prior = _prior_with_another_candidates_checks()
    prior["scores"]["b/two"] = _score(0.95, 0.02, 180)          # b/two owns the checks AND wins
    prior["scores"]["a/one"] = _score(0.60, 0.05, 190)
    cands = [{"model_id": m, "family": "f"} for m in ("a/one", "b/two", "c/three")]
    manifest_path = _main_env(tmp_path, monkeypatch, cands, prior=prior)
    _openrouter_env(monkeypatch, [100.0, 99.5, 99.5])
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.1, cost=0.1))
    monkeypatch.setattr(mr, "score", _pinned_scores({"c/three": {"macro": 0.50}}))

    assert mr.main(["--only", "c/three"]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["selection"]["winner"] == "b/two"
    assert m["stability"] == prior["stability"] and m["stable"] is True
    assert "carried forward" in m["winner_checks_source"] and "b/two" in m["winner_checks_source"]


def test_the_manifest_records_why_each_eliminated_candidate_went_out(tmp_path, monkeypatch):
    """Defect 4. `select_reader` already returns the reason and the number it failed on;
    the manifest has to carry it per candidate so the report can say that glm went out on a
    polarity decided rate of 0.8970 < 0.90 rather than leaving a reader to guess."""
    cands = [{"model_id": m, "family": "f"} for m in ("z-ai/glm-5.3", "google/gemini-3.7-flash")]
    manifest_path = _main_env(tmp_path, monkeypatch, cands)
    _openrouter_env(monkeypatch, [100.0] + [99.5] * 8)
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.1, cost=0.1))

    monkeypatch.setattr(mr, "score", _pinned_scores(
        {"z-ai/glm-5.3": {"macro": 0.8512, "decided": {"polarity": 0.8970}},
         "google/gemini-3.7-flash": {"macro": 0.8363}}))

    assert mr.main([]) == 0
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["eliminated_by_candidate"] == {
        "z-ai/glm-5.3": "decided rate below the 0.90 floor: polarity 0.8970 < 0.90"}
    assert m["selection"]["winner"] == "google/gemini-3.7-flash"
    # recomputed every run, never merged per candidate: a stale reason must not survive
    assert "eliminated_by_candidate" not in mr.MERGE_BY_CANDIDATE


# --- final review: the fixes C1, I1, I2, I3, I5 and M3 --------------------------------


def _tiny_v2_kit(tmp_path):
    """A one-case, one-batch kit in the shape `load_kit` reads, so a cache-key derivation can
    be exercised against the real codebook and the real prompt renderer without touching the
    6 MB kit the measurement was bought over."""
    raw = "The defendant let the premises to travellers for short periods. " * 8
    kit = {"reference": [{"case_id": 1, "source": "human", "relevant": True,
                          "polarity": "favorable", "who_was_letting": "householder"}],
           "batches": [{"batch_id": "kit-tiny-001", "era_partition": "e", "jurisdiction": "j",
                        "cases": [{"case_id": 1, "signals": []}]}],
           "texts": {"1": {"cite": "1 Rep 1", "name": "Rex v. Tiny", "court": "KB",
                           "jurisdiction": "j", "year": 1900, "raw_text": raw,
                           "norm_text": raw, "page_map": [[0, 1]]}}}
    p = tmp_path / "kit-tiny.json"
    p.write_text(json.dumps(kit), encoding="utf-8")
    return mr.load_kit(p)


def _cached_response(cache, key, *, model, provider, cost, case_ids=(1,)):
    """A response file in the shape the cache writes, for a key the test chose."""
    recs = [{"case_id": c, "relevant": True, "polarity": "favorable", "who_was_letting":
             "householder", "characterization": "license", "holding_summary": None,
             "quotes": [{"text": "let the premises to travellers", "supports": "polarity"}],
             "worker": "reader", "batch_id": "kit-tiny-001"} for c in case_ids]
    (cache.dir / f"{key}.json").write_text(json.dumps(
        {"text": json.dumps({"records": recs}), "input_tokens": 10, "output_tokens": 5,
         "cost_usd": cost, "provider_reported": {"model": model, "provider": provider},
         "finish_reason": "stop", "tool_version": None, "raw": {}}), encoding="utf-8")


def test_annotating_a_v2_manifest_uses_the_key_the_run_used_not_the_v1_one(tmp_path):
    """C1. `--annotate-only` addressed the cache with `ResponseCache.key_v1` while
    `--measurement-dir` defaulted to measurement-v2, so the command three documents offered
    as the safe offline one found 0 of v2's keys and overwrote the recorded map with empty
    objects. The composition is now read off the manifest, and for a v2 manifest it is the
    widened key - including the openai-strict schema dialect an openai-family pin was
    actually sent, which is why gpt's unit map came back empty even in the paid run (I2)."""
    from corpus_engine.reader.cache import ResponseCache
    from corpus_engine.reader.driver import plan_batch_extraction, schema_for
    from corpus_engine.reader.model import Budget
    from corpus_engine.reader.render import render_unit
    from corpus_engine.reader.schema import record_schema, schema_sha

    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    reference, batches, source = _tiny_v2_kit(tmp_path)
    cache = mr.ResponseCache(tmp_path / "cache")
    families = dom.reader.families
    schema = record_schema(cb)

    gpt = mr.pin_from_label("openai/gpt-5.6-terra@-:-", families)
    glm = mr.pin_from_label("z-ai/glm-5.3@AkashML:fp8", families)
    unit = plan_batch_extraction(batches, cb.id, gpt, Budget(), worker="reader").units[0]
    prompt = render_unit(cb, unit, source.fetch(unit.case_ids), "reader")

    # the key the RUN computed for an openai-family pin: the strict dialect, max_tokens and
    # effort all hashed in
    strict = schema_sha(schema_for(schema, cb, gpt, families))
    assert strict != schema_sha(schema)                      # the two dialects differ, as v2 records
    gpt_key = ResponseCache.key(cb.sha, gpt, unit, prompt, schema_sha=strict,
                                max_tokens=64000, effort="low")
    glm_key = ResponseCache.key(cb.sha, glm, unit, prompt, schema_sha=schema_sha(schema),
                                max_tokens=64000, effort="low")
    _cached_response(cache, gpt_key, model="openai/gpt-5.6-terra", provider="OpenAI", cost=0.5)
    _cached_response(cache, glm_key, model="z-ai/glm-5.3", provider="AkashML", cost=0.25)
    # what the frozen v1 composition would have addressed: a key that is not on disk at all,
    # which is exactly why the old annotator recorded `units: {}` and said nothing
    assert not (cache.dir / f"{ResponseCache.key_v1(cb.sha, gpt, unit, prompt)}.json").exists()

    # I1: a purchase of the SAME model id under another provider, bought by some OTHER
    # measurement (its key is not derivable from this manifest's codebook, kit and key
    # composition). Its money must not appear in this manifest's superseded figures.
    _cached_response(cache, "0" * 64, model="z-ai/glm-5.3", provider="Reka", cost=9.99)

    prior = {"schema_sha": schema_sha(schema), "max_tokens": 64000,
             "effort_by_candidate": {"openai/gpt-5.6-terra": "low", "z-ai/glm-5.3": "low"},
             "read_timeout_by_candidate": {"openai/gpt-5.6-terra": 1500, "z-ai/glm-5.3": 1500},
             "pins": {"openai/gpt-5.6-terra": "openai/gpt-5.6-terra@-:-",
                      "z-ai/glm-5.3": "z-ai/glm-5.3@AkashML:fp8"},
             "scores": {"openai/gpt-5.6-terra": {"accepted": 1}, "z-ai/glm-5.3": {"accepted": 1}},
             "spend_by_candidate": {"openai/gpt-5.6-terra": 0.5, "z-ai/glm-5.3": 0.25},
             "total_task_spend_usd": 0.75}
    assert mr.cache_key_version(prior) == "v2"
    assert mr.cache_key_version({"pins": {}}) == "v1"        # measurement-v1 carries no schema_sha

    path = tmp_path / "manifest.json"
    assert mr.annotate(prior, path, cb, batches, source, dom, cache,
                       stability_sample="data/reader/kit-v1/sample-50.json") == 0
    m = json.loads(path.read_text(encoding="utf-8"))

    assert m["cache_key_version"] == "v2"
    assert m["cache_keys"]["openai/gpt-5.6-terra"]["units"] == {"kit-tiny-001": gpt_key}
    assert m["cache_keys"]["z-ai/glm-5.3"]["units"] == {"kit-tiny-001": glm_key}
    # the control that the whole annotation exists to be: what the run scored, re-derived
    assert m["accepted_by_candidate"]["openai/gpt-5.6-terra"]["matches_the_run"] is True
    assert m["accepted_by_candidate"]["z-ai/glm-5.3"]["matches_the_run"] is True
    # I1: the other measurement's $9.99 is not imported, and no superseded entry invents itself
    assert m["discarded_spend_by_candidate"] == {}
    assert m["superseded_cache_keys"] == {}
    assert m["spend_attribution"]["superseded_purchases_usd"] == 0
    # scoped coverage: this measurement's own two files, not the three in the shared directory
    assert m["cache_key_coverage"] == {"keys_recorded": 2, "superseded_keys_recorded": 0,
                                       "cache_files": 2, "unaccounted": 0}
    # a measured setting is never overwritten by an offline re-derivation, and v1's
    # provenance constants are not stamped onto a later measurement
    assert m["read_timeout_by_candidate"] == {"openai/gpt-5.6-terra": 1500, "z-ai/glm-5.3": 1500}
    assert "approved_ceiling_usd" not in m and "discarded_attempts_usd" not in m
    assert "LIMITATION" not in m["note"] and "cache_key_version v2" in m["note"]


def test_keys_for_hashes_the_dialect_each_family_was_actually_sent(tmp_path):
    """I2. The cache key hashes the schema that went out, and `driver.schema_for` sends the
    openai-strict dialect to an openai-family pin. `keys_for` hashed the plan's schema for
    every pin, so it looked for a key that was never written and recorded nothing - the
    manifest's `cache_keys[\"openai/gpt-5.6-terra\"].units` was `{}` for a candidate that had
    run all 23 units."""
    from corpus_engine.reader.cache import ResponseCache
    from corpus_engine.reader.driver import plan_batch_extraction, schema_for
    from corpus_engine.reader.model import Budget
    from corpus_engine.reader.render import render_unit
    from corpus_engine.reader.schema import record_schema, schema_sha

    dom = load_domain()
    cb = load_codebook(dom, "mapper-v3")
    reference, batches, source = _tiny_v2_kit(tmp_path)
    cache = mr.ResponseCache(tmp_path / "cache")
    families = dom.reader.families
    schema = record_schema(cb)
    gpt = mr.pin_from_label("openai/gpt-5.6-terra@-:-", families)
    units = plan_batch_extraction(batches, cb.id, gpt, Budget(), worker="reader").units
    prompt = render_unit(cb, units[0], source.fetch(units[0].case_ids), "reader")

    strict_key = ResponseCache.key(cb.sha, gpt, units[0], prompt,
                                   schema_sha=schema_sha(schema_for(schema, cb, gpt, families)),
                                   max_tokens=mr.Request.max_tokens, effort="low")
    default_key = ResponseCache.key(cb.sha, gpt, units[0], prompt, schema_sha=schema_sha(schema),
                                    max_tokens=mr.Request.max_tokens, effort="low")
    assert strict_key != default_key
    _cached_response(cache, strict_key, model="openai/gpt-5.6-terra", provider="OpenAI", cost=0.1)

    assert mr.keys_for(units, cb, gpt, source, cache, schema, families) == {"kit-tiny-001": strict_key}
    # and a family that is not openai still gets the plan's own dialect
    gem = mr.pin_from_label("google/gemini-3.7-flash@-:-", families)
    gem_prompt = render_unit(cb, units[0], source.fetch(units[0].case_ids), "reader")
    gem_key = ResponseCache.key(cb.sha, gem, units[0], prompt, schema_sha=schema_sha(schema),
                                max_tokens=mr.Request.max_tokens, effort="low")
    _cached_response(cache, gem_key, model="google/gemini-3.7-flash", provider="Google", cost=0.1)
    assert gem_prompt == prompt
    assert mr.keys_for(units, cb, gem, source, cache, schema, families) == {"kit-tiny-001": gem_key}


def test_a_paid_run_refuses_a_measurement_dir_it_was_not_pointed_at(monkeypatch):
    """I3. `resolve_prior_spend` reads prior spend out of the manifest in the directory the
    run writes, and only that one, so a paid run pointed at a second directory is granted the
    whole --max-usd ceiling a second time. The slice spends against exactly one directory."""
    monkeypatch.setattr(mr, "load_domain", _raise("main got past the directory guard"))
    with pytest.raises(SystemExit) as exc:
        mr.main(["--measurement-dir", "data/reader/measurement-v3"])
    assert "granted the whole --max-usd ceiling a second time" in str(exc.value)
    # an operator who says the word out loud gets through the guard, and so does the offline
    # annotation - both reach load_domain, which this test has booby-trapped
    for extra in (["--allow-measurement-dir"], ["--annotate-only"]):
        with pytest.raises(RuntimeError, match="past the directory guard"):
            mr.main(["--measurement-dir", "data/reader/measurement-v3"] + extra)
    assert mr.DEFAULT_MEASUREMENT_DIR == "data/reader/measurement-v2"


def test_merging_a_manifest_keeps_the_subscription_units_an_earlier_process_used():
    """I5. `subscription_budget` is a whole-manifest field, so the 2026-09-05 merge pass -
    which made no subscription call, every unit having replayed from cache - wrote its zero
    over the field run's count. The manifest said 0 units used against a report that said 45."""
    prior = {"subscription_budget": {"max_units": 137, "units_used": 45, "units_planned": {}}}
    fresh = {"subscription_budget": {"max_units": 137, "units_used": 0, "units_planned": {}}}
    assert mr.merge_manifest(prior, fresh)["subscription_budget"]["units_used"] == 45
    # a process that really did make more calls owns the higher figure
    assert mr.merge_manifest(prior, {"subscription_budget": {"units_used": 60}}
                             )["subscription_budget"]["units_used"] == 60
    # and a manifest with no subscription block at all is left alone
    assert "subscription_budget" not in mr.merge_manifest({"pins": {}}, {"pins": {}})


def test_a_dry_run_records_its_spend_even_when_the_payload_assembly_raises(tmp_path, monkeypatch):
    """M3. `keys_for` and the payload assembly run after a paid candidate and outside the
    per-candidate try, so a raise there lost the dry run's spend record - the exact N1 failure
    `dry_run`'s docstring says it fixed. `main` writes from a finally; now so does this."""
    cand = {"model_id": "g/one", "family": "google"}
    real_dry_run = mr.dry_run
    manifest_path = _main_env(tmp_path, monkeypatch, [cand])
    monkeypatch.setattr(mr, "dry_run", real_dry_run)
    monkeypatch.setattr(mr, "provider_for",
                        lambda c, p: (SimpleNamespace(name="openrouter"),
                                      mr.ModelPin(c["model_id"], c["family"]), "fake"))
    monkeypatch.setattr(mr, "run_candidate", lambda *a, **k: _outcome_scored(0.6, cost=0.6))
    monkeypatch.setattr(mr, "keys_for", _raise("cache-key derivation blew up"))
    _openrouter_env(monkeypatch, [100.0, 99.4])

    with pytest.raises(RuntimeError):
        mr.main(["--dry-run", "g/one"])
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["spend_by_candidate"] == {"g/one": 0.6} and m["total_task_spend_usd"] == 0.6


def _raise(msg):
    def f(*a, **k):
        raise RuntimeError(msg)
    return f
