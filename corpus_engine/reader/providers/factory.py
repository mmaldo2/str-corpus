"""Which transport a reader candidate runs on, and what kind of budget that transport takes.

Moved out of tools/measure_reader.py (slice 2, spec section 6) because two callers now need
it: the measurement tool, which resolves five candidates against a shared OpenRouter ceiling,
and the cycle-004 map runner, which resolves exactly one - the pinned subscription reader -
and needs its units/wall-clock budget without inheriting the measurement's dollar accounting.
Nothing here changed in the move; tests/test_measure_reader_tool.py passes unedited."""
from __future__ import annotations
import time

import httpx

from corpus_engine.reader.model import Budget, ModelPin
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider
from corpus_engine.reader.providers.openrouter import OpenRouterProvider

OPEN_PRECISIONS = ("bf16", "fp8")           # preference order for pinned open-weight models
# ADR-0007 requires effort to be recorded. Left at each provider's default it is not a
# recorded quantity at all but a per-family accident: the 2026-09-04 first attempt saw
# 530 output tokens per case from one family and 3700 from another, which is a five-fold
# cost difference that measures provider defaults rather than models, and at 18 cases a
# batch. Every candidate is therefore pinned to the same effort - carried on ModelPin.extra
# as `reasoning.effort` for OpenRouter and as `effort` for the CLI, which `effort_of` reads
# either way and the widened cache key hashes.
EFFORT = "low"
REASONING = {"effort": EFFORT}
# Reasoning models generate for many minutes on an 18-case batch; anything shorter
# aborts a valid generation and the retry schedule re-buys it (see openrouter.py).
READ_TIMEOUT = 1500
SUBSCRIPTION_PROVIDER = "claude-cli"
# Both subscription ceilings are per PROCESS, not per read: one deadline and one shared
# unit counter across every subscription read the process makes (each candidate's kit run,
# the 5-case batch pair, both stability reads). A per-read ceiling multiplies by the number
# of reads - five subscription reads at 6 h each is a 30 h window nobody asked for.
# SUBSCRIPTION_MAX_UNITS is the fallback when no process cap has been computed;
# `process_unit_cap` computes the real one from the batches actually selected.
SUBSCRIPTION_MAX_UNITS = 60
SUBSCRIPTION_MAX_WALL_SECONDS = 6 * 3600
# Each parse failure costs two extra units (the split halves), so this is headroom for
# five of them across the whole process.
SUBSCRIPTION_UNIT_MARGIN = 10


def _auth(prov: OpenRouterProvider) -> dict:
    return {"Authorization": f"Bearer {prov.key}"}


def credits_remaining(prov: OpenRouterProvider) -> float:
    d = httpx.get(f"{prov.base}/credits", headers=_auth(prov), timeout=60).json()["data"]
    return float(d["total_credits"]) - float(d["total_usage"])


def endpoints(prov: OpenRouterProvider, model_id: str) -> list[dict]:
    r = httpx.get(f"{prov.base}/models/{model_id}/endpoints", headers=_auth(prov), timeout=60)
    return list(((r.json().get("data") or {}).get("endpoints")) or [])


def _probe(prov: OpenRouterProvider, model_id: str):
    """probe_model, retried once for transport reasons (controller ruling 7)."""
    try:
        return prov.probe_model(model_id), ""
    except Exception as exc:                                    # noqa: BLE001 - transport of any shape
        prov._models = None
        time.sleep(3)
        try:
            return prov.probe_model(model_id), ""
        except Exception as exc2:                               # noqa: BLE001
            return None, f"probe_model failed twice: {exc!r} / {exc2!r}"


def pin_for(cand: dict, prov: OpenRouterProvider) -> tuple[ModelPin | None, str]:
    """Resolve the pin actually served. Open-weight candidates are pinned to a named
    provider serving bf16 (preferred) or fp8; if neither is served the candidate is
    skipped rather than run at an unrecorded precision (ADR-0007)."""
    info, err = _probe(prov, cand["model_id"])
    if err:
        return None, err
    if info is None:
        return None, "not served by openrouter"
    if not cand.get("pin_open"):
        return (ModelPin(cand["model_id"], cand["family"], extra={"reasoning": REASONING}),
                "closed-weight model; provider chosen by openrouter")
    try:
        eps = endpoints(prov, cand["model_id"])
    except Exception as exc:                                    # noqa: BLE001
        return None, f"endpoints lookup failed: {exc!r}"
    served = sorted({(e.get("provider_name") or e.get("name") or "?", (e.get("quantization") or "?").lower())
                     for e in eps})
    for want in OPEN_PRECISIONS:
        for e in eps:
            if (e.get("quantization") or "").lower() == want:
                name = e.get("provider_name") or e.get("name")
                return (ModelPin(cand["model_id"], cand["family"], name, want, {"reasoning": REASONING}),
                        f"pinned to {name} at {want}; endpoints served: {served}")
    return None, f"no endpoint serving bf16 or fp8; endpoints served: {served}"


def is_subscription(cand: dict) -> bool:
    return cand.get("provider") == SUBSCRIPTION_PROVIDER


def needs_openrouter(cands) -> bool:
    """Whether this invocation has to authenticate to OpenRouter at all. A run of nothing
    but subscription candidates buys nothing there, so demanding a key (or reading
    /credits) would be a made-up precondition standing between the user and a read their
    subscription already pays for."""
    return any(not is_subscription(c) for c in cands)


def cli_pin(cand: dict) -> ModelPin:
    """Full model names, never aliases (`claude-sonnet-5`, not `sonnet`), so the pin label
    is reproducible and the cache key it feeds means one thing."""
    return ModelPin(cand["model_id"], cand["family"], SUBSCRIPTION_PROVIDER, None,
                    {"effort": EFFORT, "cli_model": cand["cli_model"]})


def provider_for(cand: dict, prov=None, *, timeout: int = READ_TIMEOUT):
    """(provider, pin, why) for one candidate. A subscription candidate is transported by the
    Claude CLI and never touches OpenRouter, so it needs no `prov` at all - the single-argument
    call `provider_for(cand)` is how a subscription-only caller (map_reader, R1) resolves one
    without ever configuring an OpenRouterProvider. An OpenRouter candidate resolves its pin
    exactly as in 3A (open weights pinned to a named bf16/fp8 endpoint or skipped), but it
    cannot be resolved at all without one: calling it with `prov=None` for an OpenRouter
    candidate is a caller error, not a runtime condition to report a reason for, so it raises
    rather than returning a `(None, None, why)` tuple."""
    if is_subscription(cand):
        cli = ClaudeCliProvider(cand["cli_model"], timeout=timeout, effort=EFFORT)
        version = cli.version()
        if version is None:
            return None, None, "claude cli not available on PATH (shutil.which found nothing)"
        return cli, cli_pin(cand), f"subscription via claude cli {version}"
    if prov is None:
        raise ValueError(f"{cand['model_id']} is not a subscription candidate and requires an "
                         f"OpenRouterProvider (prov=None)")
    pin, why = pin_for(cand, prov)
    return (prov if pin is not None else None), pin, why


def small_batches(batches):
    out = []
    for b in batches:
        for j in range(0, len(b["cases"]), 5):
            out.append({**b, "batch_id": f"{b['batch_id']}-s{j // 5 + 1}", "cases": b["cases"][j:j + 5]})
    return out


def sample_batches(batches, ids: set, tag: str):
    out = []
    for b in batches:
        cs = [c for c in b["cases"] if int(c["case_id"]) in ids]
        if cs:
            out.append({**b, "batch_id": f"{b['batch_id']}-{tag}", "cases": cs})
    return out


def process_unit_cap(n_subscription: int, batches, ids50, *, margin: int = SUBSCRIPTION_UNIT_MARGIN) -> dict:
    """The default `--sub-max-units`: every request the selected subscription candidates can
    make in THIS PROCESS, counted rather than guessed - one per kit batch per candidate, plus
    the winner's checks (the 5-case pair is about four times the kit's units, and the two
    stability reads one unit per sampled batch each) - plus a margin for split halves.

    Returned as its parts so the run can print what it budgeted and the manifest can record
    it; `["total"]` is the number the shared counter is measured against."""
    kit = int(n_subscription) * len(batches)
    pair = len(small_batches(batches))
    stab = 2 * len(sample_batches(batches, set(ids50), "st"))
    total = kit + pair + stab + int(margin) if n_subscription else 0
    return {"kit": kit, "batch_size_pair": pair, "stability": stab, "margin": int(margin),
            "total": total}


def budget_for(cand: dict, remaining_usd: float, *, max_units: int | None = None,
               max_wall_seconds: float | None = None) -> Budget:
    """D1/D5. The subscription has no marginal price, so a usd ceiling over it is not a
    ceiling: `_ReadState.spend` would stay 0.0 for every request and never trip. The driver
    refuses one outright (`preflight:budget_unpriced`), which is why this returns a units /
    wall-clock budget with `max_usd` left None."""
    if is_subscription(cand):
        return Budget(max_usd=None,
                      max_units=SUBSCRIPTION_MAX_UNITS if max_units is None else int(max_units),
                      max_wall_seconds=(SUBSCRIPTION_MAX_WALL_SECONDS if max_wall_seconds is None
                                        else float(max_wall_seconds)))
    return Budget(max_usd=max(remaining_usd, 0.0))
