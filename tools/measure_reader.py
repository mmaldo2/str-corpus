"""Pre-registered reader-model measurement (spec section 6, ADR-0007).

One shared Budget across all candidates; every response is cached, so a re-run
resumes for free over completed units. Never edits the kit: the kit sha256 is
checked against domain.yaml before anything is spent.
"""
from __future__ import annotations
import argparse, json, math, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx                                                                                # noqa: E402
from corpus_engine import store                                                             # noqa: E402
from corpus_engine.domain import load_domain                                                # noqa: E402
from corpus_engine.ranker.labels import sha256_file                                         # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                        # noqa: E402
from corpus_engine.reader.codebook import load_codebook, stability_path                     # noqa: E402
from corpus_engine.reader.driver import Reader, plan_batch_extraction                       # noqa: E402
from corpus_engine.reader.measure import (load_kit, score_candidate, select_reader,         # noqa: E402
                                          stability_agreement)
from corpus_engine.reader.model import Budget, ModelPin, Request                            # noqa: E402
from corpus_engine.reader.providers.openrouter import OpenRouterProvider                    # noqa: E402

OPEN_PRECISIONS = ("bf16", "fp8")           # preference order for pinned open-weight models
STABILITY_BAR = 0.90
# ADR-0007 requires effort to be recorded. Left at each provider's default it is not a
# recorded quantity at all but a per-family accident: the 2026-09-04 first attempt saw
# 530 output tokens per case from one family and 3700 from another, which is a five-fold
# cost difference that measures provider defaults rather than models, and at 18 cases a
# batch. Every candidate is therefore pinned to the same effort, carried on ModelPin.extra.
REASONING = {"effort": "low"}


def _clean(o):
    """math.inf / nan have no JSON spelling; Python writes the non-standard
    `Infinity`, which strict parsers reject. Map every non-finite float to null."""
    if isinstance(o, bool) or o is None or isinstance(o, (int, str)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def dumps(obj, **kw) -> str:
    return json.dumps(_clean(obj), **kw)


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


def run_candidate(pin: ModelPin, kit_batches, source, dom, prov, budget_state, cache, log):
    plan = plan_batch_extraction(kit_batches, dom.reader.codebook, pin,
                                 Budget(max_usd=max(budget_state["remaining"], 0.0)), worker="reader")
    out = Reader(prov, source, cache=cache, log=log, domain=dom).read(plan)
    budget_state["remaining"] -= out.spend_usd
    budget_state["spent"] += out.spend_usd
    return out


def reconcile(prov, before: float, ceiling: float, budget: dict, log) -> float | None:
    """Enforce the ceiling on what OpenRouter ACTUALLY charged, not on driver-tracked
    spend. A response that is billed but unusable (200 with empty content) raises out of
    `complete()` before `_ReadState.record_paid` sees it, so the driver's own total
    under-counts. Re-read /credits after every run and reset the remaining budget from
    the real delta; returns the real spend of the run just finished."""
    try:
        now = credits_remaining(prov)
    except Exception as exc:                                    # noqa: BLE001
        log(f"   credits reconcile failed ({exc!r}); falling back to driver-tracked spend")
        return None
    real = before - now
    prev = budget.get("real_spent", 0.0)
    budget["real_spent"] = real
    budget["remaining"] = ceiling - real
    log(f"   real spend so far ${real:.4f} (driver-tracked ${budget['spent']:.4f}); "
        f"remaining ${budget['remaining']:.2f}")
    return real - prev


def score(out, reference, key: str, prior_spend: dict, spend_by: dict, tracked_by: dict,
          real_delta: float | None) -> dict:
    """Cost per accepted record is priced from the real charge for this run when the
    credits endpoint answered, else from driver-tracked spend. Controller ruling 2: a
    cache hit makes either number an under-count, so add the first run's recorded spend
    (manifest) and, if there is none to add, leave the score unpriced rather than cheap."""
    cached = any(u.cache_hit for u in out.units)
    recorded = prior_spend.get(key)
    base = out.spend_usd if real_delta is None else real_delta
    priced = real_delta is not None or not cached
    if cached:
        if recorded is None:
            priced = False
        else:
            base += recorded
    tracked_by[key] = round(out.spend_usd, 6)
    spend_by[key] = round(base, 6)
    return score_candidate(out, reference, spend_usd_override=(base if priced else None))


def line(s: dict) -> str:
    cpa = s["cost_per_accepted"]
    cpa_txt = "inf" if not math.isfinite(cpa) else f"${cpa:.4f}"
    return (f"   fidelity={s['fidelity']:.4f} macro={s['agreement_human']['macro']:.4f} "
            f"cpa={cpa_txt} spend=${s['spend_usd']:.2f} "
            f"accepted={s['accepted']} schema={s['schema_compliance']:.3f} "
            f"wall={s['wall_seconds']:.0f}s stop={s['stop']}"
            + ("" if s.get("priced", True) else "  [UNPRICED]"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, default=50.0)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()

    dom = load_domain()
    kit_path = ROOT / dom.reader.kit_path
    if dom.reader.kit_sha256 and sha256_file(kit_path) != dom.reader.kit_sha256:
        sys.exit("kit sha256 does not match domain.yaml; never edit the kit")
    reference, batches, source = load_kit(kit_path)
    key = store.env_value("OPENROUTER_API_KEY")
    if not key:
        sys.exit("no OPENROUTER_API_KEY")
    prov = OpenRouterProvider(key)

    before = credits_remaining(prov)
    print(f"openrouter credits remaining before the run: ${before:.2f} (ceiling ${a.max_usd:.2f})", flush=True)
    if before < a.max_usd:
        sys.exit(f"remaining credits ${before:.2f} < ceiling ${a.max_usd:.2f}; top up or lower --max-usd")

    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    n_cached = len(list(cache.dir.glob("*.json")))
    print(f"response cache: {cache.dir} ({n_cached} entries)", flush=True)
    out_dir = ROOT / "data" / "reader" / "measurement-v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    prior_path = out_dir / "manifest.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
    prior_spend = dict(prior.get("spend_by_candidate") or {})
    spend_by: dict[str, float] = {}
    tracked_by: dict[str, float] = {}

    cb = load_codebook(dom, dom.reader.codebook)
    print(f"codebook {cb.id} sha {cb.sha}", flush=True)
    sp = stability_path(dom, cb)
    if not sp.exists():
        # the measurement itself is the stability run for v2: grant a provisional
        # record so pre-flight lets the reads start, replaced with the real one below
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_bytes(dumps({"codebook": cb.id, "codebook_sha": cb.sha, "provisional": True,
                              "note": "measurement in progress"}, indent=1).encode("utf-8"))
        print(f"wrote provisional stability record {sp.name}", flush=True)

    budget = {"remaining": a.max_usd, "spent": 0.0, "real_spent": 0.0}
    scores: dict[str, dict] = {}
    pins: dict[str, str] = {}
    pin_objs: dict[str, ModelPin] = {}
    skipped: dict[str, str] = {}
    failed: dict[str, str] = {}
    not_run: dict[str, str] = {}

    for cand in dom.reader.candidates:
        mid = cand["model_id"]
        if a.only and mid != a.only:
            continue
        if budget["remaining"] <= 0:
            not_run[mid] = "budget exhausted before this candidate ran"
            print(f"NOT RUN {mid}: budget exhausted", flush=True)
            continue
        pin, why = pin_for(cand, prov)
        print(f"PIN {mid} -> {pin.label if pin else 'SKIP'}  ({why})", flush=True)
        if pin is None:
            skipped[mid] = why
            continue
        print(f"== {pin.label}  (remaining ${budget['remaining']:.2f})", flush=True)
        try:
            out = run_candidate(pin, batches, source, dom, prov, budget, cache, print)
        except Exception as exc:                                # noqa: BLE001 - one candidate never aborts the run
            failed[mid] = f"run raised {type(exc).__name__}: {str(exc)[:300]}"
            print(f"   FAILED {failed[mid]}", flush=True)
            reconcile(prov, before, a.max_usd, budget, print)
            continue
        real_delta = reconcile(prov, before, a.max_usd, budget, print)
        if out.stop.kind.startswith("preflight:"):
            failed[mid] = f"pre-flight refusal {out.stop.kind}: {out.stop.detail}"
            print(f"   FAILED {failed[mid]}", flush=True)
            continue
        s = score(out, reference, mid, prior_spend, spend_by, tracked_by, real_delta)
        if s["accepted"] == 0:
            errs = sorted({u.error for u in out.units if u.error})[:2]
            failed[mid] = (f"no accepted records ({len(out.units)} units, stop={out.stop.kind}"
                           + ("; " + "; ".join(errs) if errs else "") + ")")
            print(f"   FAILED {failed[mid]}", flush=True)
            print(line(s), flush=True)
            continue
        scores[mid] = s
        pins[mid] = pin.label
        pin_objs[mid] = pin
        print(line(s), flush=True)
        if budget["remaining"] <= 0:
            print("budget exhausted", flush=True)

    sel = select_reader(scores)
    manifest = {"kit_sha256": dom.reader.kit_sha256, "kit_path": dom.reader.kit_path,
                "codebook": cb.id, "codebook_sha": cb.sha, "budget_usd": a.max_usd,
                "reasoning": REASONING, "max_tokens": Request.max_tokens,
                "credits_before": round(before, 4), "spent_usd": round(budget["real_spent"], 4),
                "tracked_spend_usd": round(budget["spent"], 4),
                "pins": pins, "skipped": skipped, "failed": failed, "not_run": not_run,
                "scores": scores, "selection": sel, "spend_by_candidate": spend_by,
                "tracked_spend_by_candidate": tracked_by,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if sel["winner"]:
        w = sel["winner"]
        wpin = pin_objs[w]
        manifest["winner_pin"] = wpin.label
        manifest["winner_model"] = {"model_id": wpin.model_id, "family": wpin.family,
                                    "provider_name": wpin.provider_name, "precision": wpin.precision}
        print(f"\n== winner {wpin.label}: batch-size pair (5-case batches over the same kit)", flush=True)
        small = []
        for b in batches:
            for j in range(0, len(b["cases"]), 5):
                small.append({**b, "batch_id": f"{b['batch_id']}-s{j // 5 + 1}", "cases": b["cases"][j:j + 5]})
        try:
            out5 = run_candidate(wpin, small, source, dom, prov, budget, cache, print)
            d5 = reconcile(prov, before, a.max_usd, budget, print)
            s5 = score(out5, reference, f"{w}:b5", prior_spend, spend_by, tracked_by, d5)
            manifest["batch_size_pair"] = {"b18": scores[w], "b5": s5}
            print(line(s5), flush=True)
        except Exception as exc:                                # noqa: BLE001
            manifest["batch_size_pair"] = {"b18": scores[w], "b5": None,
                                           "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            print(f"   batch-size pair FAILED {exc}", flush=True)

        print(f"\n== winner {wpin.label}: stability, two reads of the fifty-case sample", flush=True)
        ids50 = set(json.loads((ROOT / dom.reader.stability_sample).read_text(encoding="utf-8")))

        def sub(tag: str):
            units = []
            for b in batches:
                cs = [c for c in b["cases"] if int(c["case_id"]) in ids50]
                if cs:
                    units.append({**b, "batch_id": f"{b['batch_id']}-{tag}", "cases": cs})
            return units

        try:
            o1 = run_candidate(wpin, sub("st1"), source, dom, prov, budget, cache, print)
            spend_by[f"{w}:stab1"] = reconcile(prov, before, a.max_usd, budget, print) or o1.spend_usd
            o2 = run_candidate(wpin, sub("st2"), source, dom, prov, budget, cache, print)
            spend_by[f"{w}:stab2"] = reconcile(prov, before, a.max_usd, budget, print) or o2.spend_usd
            stab = stability_agreement(o1, o2)
            stable = bool(stab) and all(v >= STABILITY_BAR for v in stab.values())
            manifest["stability"] = stab
            manifest["stable"] = stable
            manifest["stability_stops"] = [o1.stop.kind, o2.stop.kind]
            sp.write_bytes(dumps({"codebook": cb.id, "codebook_sha": cb.sha, "model_pin": wpin.label,
                                  "sample": dom.reader.stability_sample, "agreement": stab, "stable": stable,
                                  "bar": STABILITY_BAR, "ts": manifest["ts"]}, indent=1).encode("utf-8"))
            print(f"   stability {stab} stable={stable}", flush=True)
        except Exception as exc:                                # noqa: BLE001
            manifest["stability"] = None
            manifest["stability_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            print(f"   stability FAILED {exc}", flush=True)

    manifest["tracked_spend_usd"] = round(budget["spent"], 4)
    manifest["spend_by_candidate"] = spend_by
    manifest["tracked_spend_by_candidate"] = tracked_by
    try:
        after = credits_remaining(prov)
        manifest["credits_after"] = round(after, 4)
        manifest["spent_usd"] = round(before - after, 4)
    except Exception as exc:                                    # noqa: BLE001
        manifest["credits_after"] = None
        manifest["spent_usd"] = round(budget["real_spent"], 4)
        print(f"credits lookup after the run failed: {exc}", flush=True)
    prior_path.write_bytes(dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    print(dumps(sel, indent=1), flush=True)
    print(f"total charged ${manifest['spent_usd']} of ${a.max_usd:.2f} "
          f"(driver-tracked ${budget['spent']:.2f}); credits after {manifest['credits_after']}", flush=True)
    print("set reader.model in domain.yaml to:", dumps(manifest.get("winner_model")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
