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
from corpus_engine.reader.driver import RESUME_TOOL, Reader, plan_batch_extraction          # noqa: E402
from corpus_engine.reader.gate import gate_unit                                             # noqa: E402
from corpus_engine.reader.measure import (load_kit, score_candidate, select_reader,         # noqa: E402
                                          stability_agreement)
from corpus_engine.reader.model import Budget, ModelPin, Request                             # noqa: E402
from corpus_engine.reader.parse import parse_records, split_unit                             # noqa: E402
from corpus_engine.reader.render import render_unit                                          # noqa: E402
from corpus_engine.reader.providers.openrouter import OpenRouterProvider                     # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                                      # noqa: E402

OPEN_PRECISIONS = ("bf16", "fp8")           # preference order for pinned open-weight models
# Pre-flight check (1) compares the codebook's `validated_norm_version` header against the
# normalizer the texts were produced by. Left unpassed it is None and the check silently
# short-circuits, so the only real caller was disarming the guard that 3B's live-store read
# depends on (I10). The kit's texts were inlined from the store by tools/build_reader_kit.py
# under this same normalizer, and `corpus_engine.verification` spells it the same way.
STORE_NORM_VERSION = f"v{NORM_VERSION}"
STABILITY_BAR = 0.90
# ADR-0007 requires effort to be recorded. Left at each provider's default it is not a
# recorded quantity at all but a per-family accident: the 2026-09-04 first attempt saw
# 530 output tokens per case from one family and 3700 from another, which is a five-fold
# cost difference that measures provider defaults rather than models, and at 18 cases a
# batch. Every candidate is therefore pinned to the same effort, carried on ModelPin.extra.
REASONING = {"effort": "low"}
# Reasoning models generate for many minutes on an 18-case batch; anything shorter
# aborts a valid generation and the retry schedule re-buys it (see openrouter.py).
READ_TIMEOUT = 1500
# The user approved $50 for the whole measurement. --max-usd was set to 47 for the run
# proper because a first attempt had already been charged for and discarded (it truncated
# at max_tokens 16000 and was thrown away with its cache), so the flag value alone does
# not describe the envelope; both numbers are recorded in the manifest.
APPROVED_CEILING = 50.0
DISCARDED_ATTEMPTS = 2.85
# 546c1bf raised the read ceiling from a scalar 300 s to 1500 s. Responses cached before
# that commit were generated under the old ceiling; the manifest records which, per
# candidate, from the mtimes of that candidate's own cache files.
TIMEOUT_CHANGE_COMMIT = "546c1bf"
TIMEOUT_CHANGE_EPOCH = 1788605116          # git log -1 --format=%ct 546c1bf
TIMEOUT_BEFORE_CHANGE = 300


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


def write_json(path: Path, obj, **kw) -> None:
    """Every committed file ends with a newline; json.dumps does not add one."""
    path.write_bytes((dumps(obj, **kw) + "\n").encode("utf-8"))


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
                                 Budget(max_usd=max(budget_state["remaining"], 0.0)), worker="reader",
                                 resume_tool=RESUME_TOOL)
    out = Reader(prov, source, cache=cache, log=log, domain=dom,
                 store_norm_version=STORE_NORM_VERSION).read(plan)
    budget_state["remaining"] -= out.spend_usd
    budget_state["spent"] += out.spend_usd
    return out


def reconcile(prov, before: float, ceiling: float, budget: dict, log) -> float | None:
    """Enforce the ceiling on what OpenRouter ACTUALLY charged, not on driver-tracked
    spend, because the two disagree in both directions and neither is a safe proxy.

    Driver-tracked can come in LOW: a response that is billed but unusable (200 with
    empty content) raises out of `complete()` before `_ReadState.record_paid` sees it.
    It can equally come in HIGH: over the 2026-09-05 measurement the driver totalled
    $15.54 against $15.03 charged, essentially all of it on one run whose per-response
    `usage.cost` figures summed $0.50 above the credits delta. Why those two sources
    disagree there is unexplained.

    So re-read /credits after every run and reset the remaining budget from the real
    delta; returns the real spend of the run just finished, or None if /credits failed."""
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


def charged(delta: float | None, tracked: float) -> float:
    """What a run really cost: the credits delta when the endpoint answered, else the
    driver's own figure. `delta or tracked` looks equivalent and is not - it throws away
    a true reading of exactly 0.0, which is what a fully cached re-read costs, and
    substitutes a driver total that in that case is also 0.0 but need not be."""
    return tracked if delta is None else delta


def line(s: dict) -> str:
    cpa = s["cost_per_accepted"]
    cpa_txt = "inf" if not math.isfinite(cpa) else f"${cpa:.4f}"
    decided = " ".join(f"{f}={s['fields'][f]['decided_rate']:.2f}/{s['fields'][f]['agreement_decided']:.2f}"
                       for f in ("relevant", "polarity", "who_was_letting"))
    return (f"   fidelity={s['fidelity']:.4f} macro={s['macro']:.4f} [{decided}] "
            f"cpa={cpa_txt} spend=${s['spend_usd']:.2f} "
            f"accepted={s['accepted']} ({s['accepted_full']} full) schema={s['schema_compliance']:.3f} "
            f"wall={s['wall_seconds']:.0f}s stop={s['stop']}"
            + ("" if s.get("priced", True) else "  [UNPRICED]"))



def pin_from_label(label: str, families) -> ModelPin:
    """Rebuild a pin from the label the manifest recorded. Only `label` feeds the cache
    key, so this round-trips exactly what the run hashed."""
    model_id, _, tail = label.partition("@")
    prov, _, prec = tail.rpartition(":")
    pin = ModelPin(model_id, families.get(model_id, "?"),
                   None if prov in ("", "-") else prov,
                   None if prec in ("", "-") else prec,
                   {"reasoning": REASONING})
    if pin.label != label:
        raise ValueError(f"pin label did not round-trip: {label!r} -> {pin.label!r}")
    return pin


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


def keys_for(units, cb, pin: ModelPin, source, cache: ResponseCache) -> dict:
    """The cache key the driver would compute for each unit, and for the split halves a
    unit falls back to when its response will not parse. Only keys actually present in
    the cache are recorded, so the map is evidence rather than prediction."""
    found = {}
    for unit in units:
        for u in (unit, *split_unit(unit)):
            prompt = render_unit(cb, u, source.fetch(u.case_ids), "reader")
            k = ResponseCache.key_v1(cb.sha, pin, u, prompt)
            if (cache.dir / f"{k}.json").exists():
                found[u.id] = k
    return found


def records_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged) -> list[dict]:
    """One candidate's gated records, re-derived from its own cached responses. Offline:
    reads the response cache and the frozen kit, issues no request, spends nothing. Mirrors
    the driver exactly - parse, split-half fallback on a parse failure, then the quote gate.

    The measurement-v1 cache is addressed with `ResponseCache.key_v1`: slice 1 widened the
    live key with the schema, max_tokens and effort, and those responses were bought under
    the old composition.

    Kept separate from `accepted_from_cache` because two callers want the same derivation
    for different reasons - the manifest annotation counts these records, and the
    who-was-letting consensus (tools/consensus_reference.py) reads their field values. One
    derivation means the two can never disagree about what a candidate said."""
    def cached(u):
        texts = source.fetch(u.case_ids)
        p = cache.dir / f"{ResponseCache.key_v1(cb.sha, pin, u, render_unit(cb, u, texts, 'reader'))}.json"
        return texts, (json.loads(p.read_text(encoding="utf-8"))["text"] if p.exists() else None)

    records = []
    for unit in units:
        texts, text = cached(unit)
        if text is None:                                   # unit never bought, or bought under another pin
            continue
        recs, stubbed = parse_records(text, unit.case_ids), set()
        if recs is None:                                   # mirror the driver: fall back to the split halves
            recs = []
            for half in split_unit(unit):
                if not half.case_ids:
                    continue
                _t, htext = cached(half)
                part = parse_records(htext, half.case_ids) if htext is not None else None
                if part is None:
                    stubbed.update(half.case_ids)
                else:
                    recs.extend(part)
        ok_ids = [c for c in unit.case_ids if c not in stubbed]
        if ok_ids:
            records += [r.record for r in gate_unit(recs, texts, ok_ids, judged, unit.id)]
    return records


def accepted_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged) -> dict:
    """Re-derive one candidate's accepted counts from its own cached responses, over exactly
    the records `records_from_cache` yields.

    `accepted` (spec section 2 as amended) counts a record that parsed and came back from
    the gate with a decided `relevant` field - `extraction_status` "ok" OR "partial", and
    partial is precisely the status of a record that lost judged fields to the gate.
    `accepted_full` is the strict reading the spec used to carry. The gap between the two
    is why cost per accepted record is a lower bound on the cost of a fully judged record
    (I7). Recomputing `accepted` as well is the control: it has to reproduce what the paid
    run scored, and the annotation records whether it did."""
    live = [r for r in records_from_cache(cb, pin, units, source, cache, judged)
            if r.get("extraction_status") != "missing"]
    return {"accepted": sum(1 for r in live if r.get("extraction_status") in ("ok", "partial")
                            and r.get("relevant") is not None),
            "accepted_full": sum(1 for r in live if r.get("extraction_status") == "ok"
                                 and r.get("relevant") is not None)}


def annotate(prior: dict, prior_path: Path, cb, batches, source, dom, cache: ResponseCache) -> int:
    """Recompute the manifest's derived records offline. Issues no request of any kind:
    everything comes from the existing manifest, the frozen kit and the response cache,
    so it can be re-run at any time for nothing."""
    if not prior.get("pins"):
        sys.exit("no manifest with pins to annotate")
    m = dict(prior)
    families = dom.reader.families
    by_model = {}
    for f in cache.dir.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        pr = d.get("provider_reported") or {}
        by_model.setdefault(pr.get("model"), []).append((d, pr.get("provider")))

    cache_keys, timeouts = {}, {}
    ids50 = set(json.loads((ROOT / dom.reader.stability_sample).read_text(encoding="utf-8")))
    winner = (m.get("selection") or {}).get("winner")

    jobs = [(mid, label, batches) for mid, label in sorted(m["pins"].items())]
    if winner and winner in m["pins"]:
        wl = m["pins"][winner]
        jobs += [(f"{winner}:b5", wl, small_batches(batches)),
                 (f"{winner}:stab1", wl, sample_batches(batches, ids50, "st1")),
                 (f"{winner}:stab2", wl, sample_batches(batches, ids50, "st2"))]

    for name, label, bs in jobs:
        pin = pin_from_label(label, families)
        units = plan_batch_extraction(bs, cb.id, pin, Budget(), worker="reader").units
        found = keys_for(units, cb, pin, source, cache)
        cache_keys[name] = {"pin": label, "units": found}
        mtimes = [(cache.dir / f"{k}.json").stat().st_mtime for k in found.values()]
        old = sum(1 for t in mtimes if t < TIMEOUT_CHANGE_EPOCH)
        new = len(mtimes) - old
        timeouts[name] = {"units_under_300s": old, "units_under_1500s": new,
                          "read_timeout_seconds": (TIMEOUT_BEFORE_CHANGE if new == 0 else
                                                   READ_TIMEOUT if old == 0 else "mixed")}
        print(f"{name:<36} {len(found):>3} keys  300s={old:<3} 1500s={new:<3} "
              f"-> {timeouts[name]['read_timeout_seconds']}", flush=True)

    # How many accepted records were fully judged, re-derived from the cache (I7).
    accepted = {}
    for mid, label in sorted(m["pins"].items()):
        pin = pin_from_label(label, families)
        units = plan_batch_extraction(batches, cb.id, pin, Budget(), worker="reader").units
        counts = accepted_from_cache(cb, pin, units, source, cache, cb.judged_fields)
        counts["accepted_recorded_by_the_run"] = ((m.get("scores") or {}).get(mid) or {}).get("accepted")
        counts["matches_the_run"] = counts["accepted_recorded_by_the_run"] == counts["accepted"]
        accepted[mid] = counts
        print(f"{mid:<36} accepted={counts['accepted']:>4} (run recorded "
              f"{counts['accepted_recorded_by_the_run']}) fully judged={counts['accepted_full']:>4}", flush=True)
    m["accepted_by_candidate"] = accepted

    # Money spent on responses no score rests on: an open-weight candidate whose pin
    # resolved to a different provider on a later run re-bought its whole kit, and the
    # superseded purchase is charged to the measurement but attributed to no candidate.
    discarded, superseded_keys = {}, {}
    for mid, label in sorted(m["pins"].items()):
        scored = pin_from_label(label, families)
        if not scored.provider_name:
            continue
        others = {prov for d, prov in by_model.get(mid, []) if prov and prov != scored.provider_name}
        for prov in sorted(others):
            for d, p2 in by_model.get(mid, []):
                if p2 == prov:
                    k = f"{mid}@{prov}"
                    discarded[k] = round(discarded.get(k, 0.0) + (d.get("cost_usd") or 0.0), 6)
            # the superseded run's responses are still in the cache; key them too, so the
            # money recorded as discarded is tied to the same evidence as the money kept
            alt = ModelPin(mid, scored.family, prov, scored.precision, {"reasoning": REASONING})
            units = plan_batch_extraction(batches, cb.id, alt, Budget(), worker="reader").units
            superseded_keys[f"{mid}@{prov}"] = {"pin": alt.label,
                                                "units": keys_for(units, cb, alt, source, cache)}

    attributed = sum((m.get("spend_by_candidate") or {}).values())
    charged_total = m.get("total_task_spend_usd")           # not `charged`: that is a module function (m1)
    m["cache_keys"] = cache_keys
    m["superseded_cache_keys"] = superseded_keys
    kept = sum(len(v["units"]) for v in cache_keys.values())
    sup = sum(len(v["units"]) for v in superseded_keys.values())
    m["cache_key_coverage"] = {"keys_recorded": kept, "superseded_keys_recorded": sup,
                               "cache_files": len(list(cache.dir.glob("*.json"))),
                               "unaccounted": len(list(cache.dir.glob("*.json"))) - kept - sup}
    m["read_timeout_by_candidate"] = timeouts
    m.pop("read_timeout_seconds", None)
    m["discarded_spend_by_candidate"] = discarded
    m["approved_ceiling_usd"] = APPROVED_CEILING
    m["discarded_attempts_usd"] = DISCARDED_ATTEMPTS
    m["spend_attribution"] = {"attributed_to_candidates_usd": round(attributed, 4),
                              "charged_usd": charged_total,
                              "unattributed_usd": round((charged_total or 0.0) - attributed, 4),
                              "superseded_purchases_usd": round(sum(discarded.values()), 6)}
    m["note"] = (
        "Derived records recomputed offline by `tools/measure_reader.py --annotate-only` "
        "(no requests, no spend). cache_keys holds, per candidate and per unit, the key the "
        "driver computes as sha256(codebook_sha|pin.label|unit id|sorted case ids|rendered "
        "prompt); only keys present in data/reader/cache are recorded, and the split halves "
        "a unit falls back to on a parse failure appear as <unit>-a / <unit>-b. "
        "read_timeout_by_candidate is attributed from each candidate's own cache-file mtimes "
        "against the commit time of " + TIMEOUT_CHANGE_COMMIT + ", which raised the read "
        "ceiling from " + str(TIMEOUT_BEFORE_CHANGE) + "s to " + str(READ_TIMEOUT) + "s; a "
        "candidate with units on both sides is recorded as \"mixed\". "
        "accepted_by_candidate re-derives each candidate's accepted records from its own "
        "cached responses (parse, split-half fallback, quote gate - no request, no spend): "
        "`accepted` is the pre-registered denominator and reproduces what the paid run "
        "scored (`matches_the_run`), while `accepted_full` counts only the records whose "
        "judged fields all survived the gate, so `accepted` minus `accepted_full` is how "
        "many accepted records were partial. LIMITATION: the cache "
        "key hashes only the pin label, so it distinguishes neither reasoning effort nor "
        "max_tokens, and two runs differing only in those would collide. The key was left "
        "alone deliberately - changing it would orphan the whole purchased cache - and "
        "fixing it belongs to Stage 3B.")
    write_json(prior_path, m, indent=1, sort_keys=True)
    print("\ncoverage: " + dumps(m["cache_key_coverage"]), flush=True)
    print("superseded purchases:", dumps(discarded), flush=True)
    print("attribution:", dumps(m["spend_attribution"]), flush=True)
    return 0


MERGE_BY_CANDIDATE = ("pins", "scores", "spend_by_candidate", "tracked_spend_by_candidate",
                      "skipped", "failed", "not_run")


def merge_manifest(prior: dict, manifest: dict) -> dict:
    """Fold this process's results into the manifest already on disk.

    The manifest is the pre-registered record of a ten-candidate measurement, and a given
    process may have re-run one of them (`--only`) or none. Writing `manifest` straight over
    the file replaced that record with a one-candidate document whose `selection.winner` was
    that candidate by construction and whose `spend_by_candidate` had lost the other nine -
    which then also degrades `resolve_prior_spend`'s ceiling guard on the next run (I8). Git
    was the only thing standing between a `--only` re-run and the loss of the measurement.

    Per-candidate maps merge key by key, this process winning for the candidates it actually
    ran; every other field is whole-manifest and the fresher process owns it. `selection` is
    recomputed by the caller over the MERGED scores, so a re-run of one candidate is judged
    against all ten and never against itself alone."""
    merged = {**prior, **manifest}
    for k in MERGE_BY_CANDIDATE:
        merged[k] = {**(prior.get(k) or {}), **(manifest.get(k) or {})}
    return merged


def resolve_prior_spend(flag: float | None, prior: dict) -> tuple[float, str]:
    """How much of --max-usd an earlier process already spent.

    --max-usd is a ceiling on the MEASUREMENT, not on one process: a resume re-derives
    the cached units for free, so its own counter starts at zero and, left to itself,
    a forgetful restart would be handed the whole ceiling a second time. Defaulting the
    flag to 0.0 made that a matter of the operator typing the right number. It now fails
    closed - an omitted flag reads the prior manifest, and only an explicit
    `--prior-spend-usd 0` re-grants the full ceiling.

    total_task_spend_usd is preferred because it is reconciled against the credits
    endpoint and so counts money that no candidate was charged for; the per-candidate
    sum is the last resort precisely because it under-counts (5.2% of the 2026-09-05
    measurement was attributed to no candidate) and under-counting is what this guard
    exists to prevent.
    """
    if flag is not None:
        return float(flag), "explicit --prior-spend-usd"
    for field in ("total_task_spend_usd", "spent_usd"):
        v = prior.get(field)
        if isinstance(v, (int, float)):
            return float(v), f"derived from the prior manifest's {field}"
    by = prior.get("spend_by_candidate") or {}
    if by:
        return float(sum(by.values())), "derived from the prior manifest's spend_by_candidate (under-counts)"
    return 0.0, "no prior manifest; nothing spent yet"


# NOTE (Stage 3B slice 1): scores are the v2 shape from measure.score_candidate. The
# measurement-v1 manifest holds v1-shaped scores, which select_reader can no longer read;
# this tool is rewritten for measurement-v2 in Task 9 and must not be run in a paid mode
# before then.
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, default=50.0)
    ap.add_argument("--only", default=None)
    # Omitted, this is read off the prior manifest (see resolve_prior_spend); pass an
    # explicit 0 to deliberately re-grant the whole ceiling.
    ap.add_argument("--prior-spend-usd", type=float, default=None)
    ap.add_argument("--annotate-only", action="store_true",
                    help="recompute the manifest's derived records (cache keys, per-candidate "
                         "read timeout, budget envelope) from the existing manifest and the "
                         "response cache. Makes no request of any kind and spends nothing.")
    a = ap.parse_args()

    dom = load_domain()
    kit_path = ROOT / dom.reader.kit_path
    if dom.reader.kit_sha256 and sha256_file(kit_path) != dom.reader.kit_sha256:
        sys.exit("kit sha256 does not match domain.yaml; never edit the kit")
    reference, batches, source = load_kit(kit_path)

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

    if a.annotate_only:
        return annotate(prior, prior_path, cb, batches, source, dom, cache)

    prior_usd, why = resolve_prior_spend(a.prior_spend_usd, prior)
    ceiling = a.max_usd - prior_usd
    key = store.env_value("OPENROUTER_API_KEY")
    if not key:
        sys.exit("no OPENROUTER_API_KEY")
    prov = OpenRouterProvider(key, timeout=READ_TIMEOUT)

    before = credits_remaining(prov)
    print(f"openrouter credits remaining before the run: ${before:.2f} "
          f"(ceiling ${a.max_usd:.2f} less ${prior_usd:.2f} already spent [{why}] "
          f"= ${ceiling:.2f})", flush=True)
    if ceiling <= 0:
        sys.exit(f"nothing left of the ${a.max_usd:.2f} ceiling: ${prior_usd:.2f} already spent ({why})")
    if before < ceiling:
        sys.exit(f"remaining credits ${before:.2f} < remaining ceiling ${ceiling:.2f}; top up or lower --max-usd")
    sp = stability_path(dom, cb)
    if not sp.exists():
        # the measurement itself is the stability run for v2: grant a provisional
        # record so pre-flight lets the reads start, replaced with the real one below
        sp.parent.mkdir(parents=True, exist_ok=True)
        write_json(sp, {"codebook": cb.id, "codebook_sha": cb.sha, "provisional": True,
                        "note": "measurement in progress"}, indent=1)
        print(f"wrote provisional stability record {sp.name}", flush=True)

    budget = {"remaining": ceiling, "spent": 0.0, "real_spent": 0.0}
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
            reconcile(prov, before, ceiling, budget, print)
            continue
        real_delta = reconcile(prov, before, ceiling, budget, print)
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

    # Selection is decided over every candidate on record, not only the ones this process
    # ran, so `--only` can never crown its single candidate by construction (I8).
    merged_scores = {**(prior.get("scores") or {}), **scores}
    all_pins = {**(prior.get("pins") or {}), **pins}
    sel = select_reader(merged_scores)
    manifest = {"kit_sha256": dom.reader.kit_sha256, "kit_path": dom.reader.kit_path,
                "codebook": cb.id, "codebook_sha": cb.sha, "budget_usd": a.max_usd,
                "prior_spend_usd": round(prior_usd, 4), "prior_spend_source": why,
                "effective_budget_usd": round(ceiling, 4),
                "approved_ceiling_usd": APPROVED_CEILING, "discarded_attempts_usd": DISCARDED_ATTEMPTS,
                "reasoning": REASONING, "max_tokens": Request.max_tokens,
                "credits_before": round(before, 4), "spent_usd": round(budget["real_spent"], 4),
                "tracked_spend_usd": round(budget["spent"], 4),
                "pins": pins, "skipped": skipped, "failed": failed, "not_run": not_run,
                "scores": scores, "selection": sel, "spend_by_candidate": spend_by,
                "tracked_spend_by_candidate": tracked_by,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if sel["winner"] and sel["winner"] not in pin_objs:
        w = sel["winner"]
        if all_pins.get(w):
            wpin = pin_from_label(all_pins[w], dom.reader.families)
            manifest["winner_pin"] = wpin.label
            manifest["winner_model"] = {"model_id": wpin.model_id, "family": wpin.family,
                                        "provider_name": wpin.provider_name, "precision": wpin.precision}
        print(f"\n== winner {w} was recorded by an earlier process and not re-run here; its "
              f"batch-size pair and stability check are carried forward from the prior manifest "
              f"(nothing spent on them)", flush=True)
    elif sel["winner"]:
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
            d5 = reconcile(prov, before, ceiling, budget, print)
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
            d1 = reconcile(prov, before, ceiling, budget, print)
            spend_by[f"{w}:stab1"] = charged(d1, o1.spend_usd)
            o2 = run_candidate(wpin, sub("st2"), source, dom, prov, budget, cache, print)
            d2 = reconcile(prov, before, ceiling, budget, print)
            spend_by[f"{w}:stab2"] = charged(d2, o2.spend_usd)
            stab = stability_agreement(o1, o2)
            stable = bool(stab) and all(v >= STABILITY_BAR for v in stab.values())
            manifest["stability"] = stab
            manifest["stable"] = stable
            manifest["stability_stops"] = [o1.stop.kind, o2.stop.kind]
            write_json(sp, {"codebook": cb.id, "codebook_sha": cb.sha, "model_pin": wpin.label,
                            "sample": dom.reader.stability_sample, "agreement": stab, "stable": stable,
                            "bar": STABILITY_BAR, "ts": manifest["ts"]}, indent=1)
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
    manifest["total_task_spend_usd"] = round(prior_usd + (manifest["spent_usd"] or 0.0), 4)
    write_json(prior_path, merge_manifest(prior, manifest), indent=1, sort_keys=True)
    print(dumps(sel, indent=1), flush=True)
    print(f"this process charged ${manifest['spent_usd']} of the ${ceiling:.2f} it had left; "
          f"measurement total ${manifest['total_task_spend_usd']} of ${a.max_usd:.2f} "
          f"(driver-tracked ${budget['spent']:.2f}); credits after {manifest['credits_after']}", flush=True)
    print("set reader.model in domain.yaml to:", dumps(manifest.get("winner_model")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
