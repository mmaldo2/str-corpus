"""Pre-registered reader-model measurement, version 2 (spec section 6, ADR-0007 as
amended 2026-09-05).

Two transports, one tool. A candidate whose `provider` is `claude-cli` is read through the
user's Claude subscription (`ClaudeCliProvider`) and has no dollar price at all: its budget
is units and wall-clock, it never touches the OpenRouter credits endpoint, and nothing about
it may be counted as a charge. Every other candidate is read through OpenRouter exactly as
in Stage 3A - probed, pinned to a named bf16/fp8 endpoint when it is open-weight, and paid
for out of ONE shared dollar ceiling for the whole slice (D5, $15).

Every response is cached, so a re-run resumes for free over completed units. Never edits
the kit: the kit sha256 is checked against domain.yaml before anything is spent.

`--dry-run <candidate>` / `--dry-run-batches N` buys the first N kit batches (default 1) for
the named candidate into the SAME cache and measurement directory, writes the parse / gate /
schema diagnostics, and exits without selecting anything. The later full run reuses those
cached units, so the gate costs nothing twice.
"""
from __future__ import annotations
import argparse, json, math, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                             # noqa: E402
from corpus_engine.domain import load_domain                                                # noqa: E402
from corpus_engine.ranker.labels import sha256_file                                         # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                        # noqa: E402
from corpus_engine.reader.codebook import load_codebook, stability_path                     # noqa: E402
from corpus_engine.reader.driver import (RESUME_TOOL, Reader, plan_batch_extraction,        # noqa: E402
                                          schema_for)
from corpus_engine.reader.gate import gate_unit                                             # noqa: E402
from corpus_engine.reader.measure import (excluded_fields, load_kit, score_candidate,       # noqa: E402
                                          select_reader, stability as stability_decided,
                                          stability_agreement)
from corpus_engine.reader.model import Budget, ModelPin, Request, effort_of                 # noqa: E402
from corpus_engine.reader.parse import parse_records, split_unit                            # noqa: E402
from corpus_engine.reader.providers.claude_cli import ClaudeCliProvider                     # noqa: E402
from corpus_engine.reader.providers.factory import (EFFORT, OPEN_PRECISIONS, READ_TIMEOUT,  # noqa: E402
                                                    REASONING, SUBSCRIPTION_MAX_UNITS,
                                                    SUBSCRIPTION_MAX_WALL_SECONDS,
                                                    SUBSCRIPTION_PROVIDER, SUBSCRIPTION_UNIT_MARGIN,
                                                    budget_for, cli_pin, credits_remaining,
                                                    endpoints, is_subscription, needs_openrouter,
                                                    pin_for, process_unit_cap, provider_for,
                                                    sample_batches, small_batches)
from corpus_engine.reader.providers.openrouter import OpenRouterProvider                    # noqa: E402
from corpus_engine.reader.render import render_unit                                         # noqa: E402
from corpus_engine.reader.schema import record_schema, schema_sha                           # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                                     # noqa: E402

# Pre-flight check (1) compares the codebook's `validated_norm_version` header against the
# normalizer the texts were produced by. Left unpassed it is None and the check silently
# short-circuits, so the only real caller was disarming the guard that 3B's live-store read
# depends on (I10). The kit's texts were inlined from the store by tools/build_reader_kit.py
# under this same normalizer, and `corpus_engine.verification` spells it the same way.
STORE_NORM_VERSION = f"v{NORM_VERSION}"
STABILITY_BAR = 0.90
# D5: the whole slice's OpenRouter spend. Three candidates over the kit plus, if the winner
# is an OpenRouter model, its stability pair and batch-size pair. The subscription has no
# dollar budget; its ceilings are units and wall-clock.
OPENROUTER_CEILING = 15.0
DRY_RUN_MAX_USD = 2.0
OUT_DIR = "measurement-v2"
# The ONE manifest directory this slice spends against. The OpenRouter ceiling is enforced per
# directory (`resolve_prior_spend` reads the manifest in the directory the run writes), so a
# paid run that names another one is refused unless --allow-measurement-dir says so (I3).
DEFAULT_MEASUREMENT_DIR = f"data/reader/{OUT_DIR}"
# v1 provenance, read only by --annotate-only over data/reader/measurement-v1.
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((dumps(obj, **kw) + "\n").encode("utf-8"))


def label_provider(label: str) -> str | None:
    """The provider name out of a pin label, spelled exactly as `pin_from_label` reads it."""
    prov = str(label).partition("@")[2].rpartition(":")[0]
    return None if prov in ("", "-") else prov


def subscription_labels(dom, pins: dict | None = None, prior: dict | None = None) -> set[str]:
    """The pin LABELS of every subscription candidate on record - the form D4's tie-break is
    keyed on (`measure.select_reader`, `measure.subscription_keys`).

    Three sources, because selection is decided over every candidate on record and not only
    the ones this process ran: the labels of the pins this process actually built, the labels
    a prior manifest recorded whose provider part is `claude-cli`, and - for a subscription
    candidate that was selected but never got as far as a pin (skipped, failed, not run) -
    the label `cli_pin` deterministically builds for it.

    Passing bare model ids here is the bug this replaces: the tie-break compared model ids
    against keys that may be spelled as labels, so it could never match and the subscription
    branch was dead code. A label matches either spelling; a model id only matches one."""
    out = {cli_pin(c).label for c in dom.reader.candidates
           if is_subscription(c) and c.get("cli_model")}
    recorded = {**((prior or {}).get("pins") or {}), **(pins or {})}
    out |= {label for label in recorded.values()
            if label_provider(label) == SUBSCRIPTION_PROVIDER}
    return out


def selected_candidates(dom, only: str | None = None, dry_run: str | None = None) -> list[dict]:
    """The candidates this invocation will actually try, in domain.yaml order."""
    want = dry_run or only
    return [c for c in dom.reader.candidates if want is None or c["model_id"] == want]


def run_candidate(pin: ModelPin, provider, budget: Budget, kit_batches, source, dom, cb, cache,
                  log, budget_state):
    plan = plan_batch_extraction(kit_batches, cb.id, pin, budget, worker="reader",
                                 json_schema=record_schema(cb), resume_tool=RESUME_TOOL)
    out = Reader(provider, source, cache=cache, log=log, domain=dom,
                 store_norm_version=STORE_NORM_VERSION).read(plan)
    budget_state["remaining"] -= out.spend_usd
    budget_state["spent"] += out.spend_usd
    return out


def keys_for(units, cb, pin: ModelPin, source, cache: ResponseCache, schema, families,
             *, max_tokens: int = Request.max_tokens, effort: str | None = None) -> dict:
    """The v2 cache key for each unit and for the split halves it falls back to. Only keys
    present in the cache are recorded, so the map is evidence rather than prediction.

    `schema` is the PLAN's schema; which dialect this pin's request actually carried is
    decided here by `driver.schema_for`, exactly as the driver decides it, because the key
    hashes what was sent. Hashing the plan schema for every pin is what left
    `openai/gpt-5.6-terra` with an empty unit map in measurement v2 - the default-dialect key
    is simply not in the cache, `keys_for` records only keys it finds, and the hole was
    therefore silent (final-review I2). `max_tokens` and `effort` are parameters rather than
    module constants so an offline re-derivation can pass the values the RUN recorded instead
    of today's."""
    keyer = v2_keyer(cb, families, schema, max_tokens=max_tokens,
                     efforts={} if effort is None else {pin.model_id: effort})
    return keys_in_cache(units, cb, pin, source, cache, keyer)


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
    delta; returns the real spend of the run just finished, or None if /credits failed.
    Never called for a subscription run: there is no credits balance to reconcile and the
    ceiling this defends is not the one that run spends against."""
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
          real_delta: float | None, *, excluded=None) -> dict:
    """Cost per accepted record is priced from the real charge for this run when the
    credits endpoint answered, else from driver-tracked spend. Controller ruling 2: a
    cache hit is a unit some EARLIER process paid for, so this run's own numbers under-count
    it; the first run's recorded spend (manifest `spend_by_candidate`) is added back.

    THE RULE, stated once: a candidate is priced when a usable spend figure exists for it,
    and the figure is `(real_delta if /credits answered else driver-tracked) + recorded`.
    Three sources can supply one, and any of them is enough:

      * `real_delta`    - what /credits says this run was charged, None if the endpoint failed
      * `out.spend_usd` - the driver's own tally of the units it actually bought, which is
                          usable on its own only when nothing was replayed from cache
      * `recorded`      - what an earlier process (a `--dry-run` included) wrote for this
                          same key, which is what covers the replayed units

    A cache hit alone therefore does NOT make a candidate unpriced - that is what marked
    gemini `[UNPRICED]` with `cost_per_accepted` inf on 2026-09-05 after its first kit batch
    replayed from the dry run, against $0.94 of real, reconciled spend. Only a run that
    replayed from cache AND has no credits reading AND no recorded prior spend is left
    unpriced, because then there is genuinely no figure to quote - and an absent price must
    never win a cost comparison by looking cheap.

    A subscription run needs no special case here: every one of its responses carries
    `cost_usd is None`, `score_candidate` sees that and marks the candidate unpriced with
    spend 0.0, whatever override this passes."""
    cached = any(u.cache_hit for u in out.units)
    recorded = prior_spend.get(key)
    base = out.spend_usd if real_delta is None else real_delta
    priced = (not cached) or real_delta is not None or recorded is not None
    if cached and recorded is not None:
        base += recorded
    tracked_by[key] = round(out.spend_usd, 6)
    spend_by[key] = round(base, 6)
    return score_candidate(out, reference, spend_usd_override=(base if priced else None),
                           excluded=excluded)


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
    prov = None if prov in ("", "-") else prov
    extra = ({"effort": EFFORT, "cli_model": model_id.split("/", 1)[-1]}
             if prov == SUBSCRIPTION_PROVIDER else {"reasoning": REASONING})
    pin = ModelPin(model_id, families.get(model_id, "?"), prov,
                   None if prec in ("", "-") else prec, extra)
    if pin.label != label:
        raise ValueError(f"pin label did not round-trip: {label!r} -> {pin.label!r}")
    return pin


def keys_in_cache(units, cb, pin: ModelPin, source, cache: ResponseCache, keyer) -> dict:
    """The cache key of each unit, and of the split halves a unit falls back to when its
    response will not parse, for every key `keyer` computes that is actually on disk. Only
    keys present in the cache are recorded, so the map is evidence rather than prediction.

    `keyer` decides which composition addresses this measurement's purchases - `v1_keyer`
    for the frozen Stage 3A cache, `v2_keyer` for anything bought under the widened key."""
    found = {}
    for unit in units:
        for u in (unit, *split_unit(unit)):
            if not u.case_ids:
                continue
            prompt = render_unit(cb, u, source.fetch(u.case_ids), "reader")
            k = keyer(pin, u, prompt)
            if (cache.dir / f"{k}.json").exists():
                found[u.id] = k
    return found


def v1_keyer(cb):
    """Addresses the purchased measurement-v1 cache: `ResponseCache.key_v1`, the frozen
    Stage 3A composition, which hashes neither the schema nor max_tokens nor effort."""
    def keyer(pin: ModelPin, unit, prompt: str) -> str:
        return ResponseCache.key_v1(cb.sha, pin, unit, prompt)
    return keyer


def v2_keyer(cb, families, schema, *, max_tokens: int = Request.max_tokens, efforts=None):
    """Addresses a cache bought under the widened key: `ResponseCache.key`, hashing the
    schema ACTUALLY SENT for this pin's family (`driver.schema_for`, so an openai-family pin
    is addressed under the strict dialect), max_tokens, and effort.

    `max_tokens` and `efforts` are passed in rather than read from this module's constants so
    an offline re-derivation addresses the cache with the values the RUN recorded, not with
    today's - a later slice that raises either would otherwise silently stop finding the keys
    behind a finished measurement. `efforts` maps model id to the recorded effort; a pin not
    named there falls back to what the pin itself carries."""
    efforts = dict(efforts or {})
    shas: dict[str, str] = {}

    def keyer(pin: ModelPin, unit, prompt: str) -> str:
        if pin.label not in shas:
            shas[pin.label] = schema_sha(schema_for(schema, cb, pin, families))
        return ResponseCache.key(cb.sha, pin, unit, prompt, schema_sha=shas[pin.label],
                                 max_tokens=int(max_tokens),
                                 effort=efforts.get(pin.model_id, effort_of(pin)))
    return keyer


def cache_key_version(prior: dict) -> str:
    """Which key composition addresses THIS manifest's purchases - the single question C1
    turned on. `--annotate-only` used `key_v1` unconditionally while `--measurement-dir`
    defaulted to measurement-v2, so the documented "safe, offline" command found 0 of v2's 94
    keys and overwrote the recorded map with empty objects.

    `cache_key_version` is recorded by every manifest written from now on. Manifests written
    before it existed are told apart by `schema_sha`, which v2's `assemble` writes and v1's
    never did: measurement-v1 is the only manifest without one, and it is frozen, so the
    marker is deliberately NOT backfilled into it - writing one would change the frozen
    file the whole v1 record is checked against."""
    recorded = prior.get("cache_key_version")
    if recorded in ("v1", "v2"):
        return str(recorded)
    return "v2" if prior.get("schema_sha") else "v1"


def keyer_for_manifest(prior: dict, cb, families, schema) -> tuple:
    """(version, keyer) for the manifest being annotated."""
    version = cache_key_version(prior)
    if version == "v1":
        return version, v1_keyer(cb)
    return version, v2_keyer(cb, families, schema,
                             max_tokens=int(prior.get("max_tokens") or Request.max_tokens),
                             efforts=prior.get("effort_by_candidate") or {})


def records_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged,
                       keyer=None) -> list[dict]:
    """One candidate's gated records, re-derived from its own cached responses. Offline:
    reads the response cache and the frozen kit, issues no request, spends nothing. Mirrors
    the driver exactly - parse, split-half fallback on a parse failure, then the quote gate.

    `keyer` says which cache composition answers for this candidate, and defaults to the v1
    one because the only caller that omits it (tools/consensus_reference.py) reads
    measurement-v1 and refuses to run if the codebook has moved off the sha v1 was bought
    under. `annotate` passes the keyer its manifest calls for.

    Kept separate from `accepted_from_cache` because two callers want the same derivation
    for different reasons - the manifest annotation counts these records, and the
    who-was-letting consensus reads their field values. One derivation means the two can
    never disagree about what a candidate said."""
    key = v1_keyer(cb) if keyer is None else keyer

    def cached(u):
        texts = source.fetch(u.case_ids)
        p = cache.dir / f"{key(pin, u, render_unit(cb, u, texts, 'reader'))}.json"
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


def accepted_from_cache(cb, pin: ModelPin, units, source, cache: ResponseCache, judged,
                        keyer=None) -> dict:
    """Re-derive one candidate's accepted counts from its own cached responses, over exactly
    the records `records_from_cache` yields.

    `accepted` (spec section 2 as amended) counts a record that parsed and came back from
    the gate with a decided `relevant` field - `extraction_status` "ok" OR "partial", and
    partial is precisely the status of a record that lost judged fields to the gate.
    `accepted_full` is the strict reading the spec used to carry. The gap between the two
    is why cost per accepted record is a lower bound on the cost of a fully judged record
    (I7). Recomputing `accepted` as well is the control: it has to reproduce what the paid
    run scored, and the annotation records whether it did."""
    live = [r for r in records_from_cache(cb, pin, units, source, cache, judged, keyer)
            if r.get("extraction_status") != "missing"]
    return {"accepted": sum(1 for r in live if r.get("extraction_status") in ("ok", "partial")
                            and r.get("relevant") is not None),
            "accepted_full": sum(1 for r in live if r.get("extraction_status") == "ok"
                                 and r.get("relevant") is not None)}


# The closing sentence of the manifest `note`, per key composition. v1's is the frozen text
# already on disk and describes v1's real limitation; it must not be told about v2's key.
V1_NOTE_LIMITATION = (
    "LIMITATION: the cache "
    "key hashes only the pin label, so it distinguishes neither reasoning effort nor "
    "max_tokens, and two runs differing only in those would collide. The key was left "
    "alone deliberately - changing it would orphan the whole purchased cache - and "
    "fixing it belongs to Stage 3B.")
V2_NOTE_KEY = (
    "The key is the WIDENED one (cache_key_version v2): sha256 over the same parts plus the "
    "sha of the schema actually sent for that pin's family - the openai-strict dialect for an "
    "openai-family pin - plus max_tokens and reasoning effort, both read back from this "
    "manifest rather than from the tool's current constants.")


def annotate(prior: dict, prior_path: Path, cb, batches, source, dom, cache: ResponseCache,
             stability_sample: str = "") -> int:
    """Recompute a measurement manifest's derived records offline. Issues no request of any
    kind: everything comes from the existing manifest, the frozen kit and the response cache,
    so it can be re-run at any time for nothing.

    Which cache composition it addresses is READ OFF THE MANIFEST (`cache_key_version`) and
    never assumed: measurement-v1 was bought under the Stage 3A key, measurement-v2 and
    everything after it under the widened one. Annotating v1 also means naming v1's own
    codebook, kit and sample, because domain.yaml has moved on to mapper-v3 and kit v2:

        --annotate-only --measurement-dir data/reader/measurement-v1
        --codebook mapper-v2 --kit-path data/reader/kit-v1/kit.json
        --stability-sample data/reader/kit-v1/sample-50.json

    Two things are written only for a v1 manifest. `read_timeout_by_candidate` is attributed
    there from cache-file mtimes because v1 straddles the commit that raised the read ceiling
    and recorded no per-candidate value; a v2 manifest records the real setting per candidate
    at run time, and guessing over it from mtimes would replace a measured number with an
    inferred one. `approved_ceiling_usd` / `discarded_attempts_usd` are v1 provenance
    constants and mean nothing for a later measurement."""
    if not prior.get("pins"):
        sys.exit("no manifest with pins to annotate")
    m = dict(prior)
    families = dom.reader.families
    schema = record_schema(cb)
    version, keyer = keyer_for_manifest(prior, cb, families, schema)
    print(f"manifest cache_key_version={version}; keys derived with "
          f"ResponseCache.{'key_v1' if version == 'v1' else 'key'} over codebook {cb.id} "
          f"{cb.sha[:12]}", flush=True)

    cache_keys, timeouts = {}, {}
    sample = stability_sample or dom.reader.stability_sample
    ids50 = set(json.loads((ROOT / sample).read_text(encoding="utf-8")))
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
        found = keys_in_cache(units, cb, pin, source, cache, keyer)
        cache_keys[name] = {"pin": label, "units": found}
        if version != "v1":
            print(f"{name:<36} {len(found):>3} keys", flush=True)
            continue
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
        counts = accepted_from_cache(cb, pin, units, source, cache, cb.judged_fields, keyer)
        counts["accepted_recorded_by_the_run"] = ((m.get("scores") or {}).get(mid) or {}).get("accepted")
        counts["matches_the_run"] = counts["accepted_recorded_by_the_run"] == counts["accepted"]
        accepted[mid] = counts
        print(f"{mid:<36} accepted={counts['accepted']:>4} (run recorded "
              f"{counts['accepted_recorded_by_the_run']}) fully judged={counts['accepted_full']:>4}", flush=True)
    m["accepted_by_candidate"] = accepted

    # Money spent on responses no score rests on: an open-weight candidate whose pin
    # resolved to a different provider on a later run re-bought its whole kit, and the
    # superseded purchase is charged to the measurement but attributed to no candidate.
    #
    # I1: scoped to THIS measurement's own purchases. The provider scan below reads the whole
    # shared cache, which holds every measurement's responses side by side, so a provider
    # counts as a superseded purchase of this one only if the alternate pin's keys - this
    # manifest's codebook, kit and key composition - are actually on disk, and only the cost
    # of THOSE files is summed. Totalling every file the shared cache holds for the model id
    # instead imported a measurement-v2 charge ($1.588175 of z-ai/glm-5.3@AkashML) into the
    # frozen v1 record and moved its superseded total from $1.51 to $3.10.
    by_model: dict[str, set] = {}
    for f in cache.dir.glob("*.json"):
        pr = json.loads(f.read_text(encoding="utf-8")).get("provider_reported") or {}
        if pr.get("model") and pr.get("provider"):
            by_model.setdefault(pr["model"], set()).add(pr["provider"])

    discarded, superseded_keys = {}, {}
    for mid, label in sorted(m["pins"].items()):
        scored = pin_from_label(label, families)
        if not scored.provider_name:
            continue
        for prov in sorted(p for p in by_model.get(mid, set()) if p != scored.provider_name):
            alt = ModelPin(mid, scored.family, prov, scored.precision, {"reasoning": REASONING})
            units = plan_batch_extraction(batches, cb.id, alt, Budget(), worker="reader").units
            found = keys_in_cache(units, cb, alt, source, cache, keyer)
            if not found:
                continue          # this provider's responses belong to some other measurement
            k = f"{mid}@{prov}"
            superseded_keys[k] = {"pin": alt.label, "units": found}
            discarded[k] = round(sum((json.loads((cache.dir / f"{key}.json").read_text(encoding="utf-8"))
                                      .get("cost_usd") or 0.0) for key in found.values()), 6)

    attributed = sum((m.get("spend_by_candidate") or {}).values())
    charged_total = m.get("total_task_spend_usd")           # not `charged`: that is a module function (m1)
    m["cache_keys"] = cache_keys
    m["superseded_cache_keys"] = superseded_keys
    kept = sum(len(v["units"]) for v in cache_keys.values())
    sup = sum(len(v["units"]) for v in superseded_keys.values())
    # Scoped to this measurement, like everything else here: `cache_files` counts the DISTINCT
    # response files this manifest accounts for, not every file in the shared cache directory,
    # which holds v1's and v2's purchases together and would make the number mean nothing.
    # `unaccounted` stays the consistency check it was - it goes negative if one key were
    # recorded twice, as both kept and superseded.
    distinct = len({k for v in cache_keys.values() for k in v["units"].values()}
                   | {k for v in superseded_keys.values() for k in v["units"].values()})
    m["cache_key_coverage"] = {"keys_recorded": kept, "superseded_keys_recorded": sup,
                               "cache_files": distinct, "unaccounted": distinct - kept - sup}
    if version == "v1":
        m["read_timeout_by_candidate"] = timeouts
        m.pop("read_timeout_seconds", None)
        m["approved_ceiling_usd"] = APPROVED_CEILING
        m["discarded_attempts_usd"] = DISCARDED_ATTEMPTS
    else:
        m["cache_key_version"] = version
    m["discarded_spend_by_candidate"] = discarded
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
        + ("read_timeout_by_candidate is attributed from each candidate's own cache-file mtimes "
           "against the commit time of " + TIMEOUT_CHANGE_COMMIT + ", which raised the read "
           "ceiling from " + str(TIMEOUT_BEFORE_CHANGE) + "s to " + str(READ_TIMEOUT) + "s; a "
           "candidate with units on both sides is recorded as \"mixed\". "
           if version == "v1" else "") +
        "accepted_by_candidate re-derives each candidate's accepted records from its own "
        "cached responses (parse, split-half fallback, quote gate - no request, no spend): "
        "`accepted` is the pre-registered denominator and reproduces what the paid run "
        "scored (`matches_the_run`), while `accepted_full` counts only the records whose "
        "judged fields all survived the gate, so `accepted` minus `accepted_full` is how "
        "many accepted records were partial. "
        + (V1_NOTE_LIMITATION if version == "v1" else V2_NOTE_KEY))
    write_json(prior_path, m, indent=1, sort_keys=True)
    print("\ncoverage: " + dumps(m["cache_key_coverage"]), flush=True)
    print("superseded purchases:", dumps(discarded), flush=True)
    print("attribution:", dumps(m["spend_attribution"]), flush=True)
    return 0


MERGE_BY_CANDIDATE = ("pins", "providers", "scores", "spend_by_candidate",
                      "tracked_spend_by_candidate", "list_cost_by_candidate",
                      "priced_by_candidate", "effort_by_candidate", "read_timeout_by_candidate",
                      "cache_keys", "skipped", "failed", "not_run", "dry_runs")


def merge_manifest(prior: dict, manifest: dict) -> dict:
    """Fold this process's results into the manifest already on disk.

    The manifest is the pre-registered record of a five-candidate measurement, and a given
    process may have re-run one of them (`--only`) or none. Writing `manifest` straight over
    the file replaced that record with a one-candidate document whose `selection.winner` was
    that candidate by construction and whose `spend_by_candidate` had lost the other four -
    which then also degrades `resolve_prior_spend`'s ceiling guard on the next run (I8). Git
    was the only thing standing between a `--only` re-run and the loss of the measurement.

    Per-candidate maps merge key by key, this process winning for the candidates it actually
    ran; every other field is whole-manifest and the fresher process owns it. `selection` is
    recomputed by the caller over the MERGED scores, so a re-run of one candidate is judged
    against all five and never against itself alone.

    `subscription_budget` is the one whole-manifest field the fresher process may NOT simply
    own. Its `units_used` is a count of subscription calls the measurement made, and the
    2026-09-05 merge pass - which made none, because every subscription unit replayed from
    cache - wrote its zero over the field run's count and left the manifest saying 0 units
    against a report that says 45 (final-review I5). The maximum is kept rather than the sum:
    a resume re-reads the same units for free, so summing would count them twice; the highest
    figure any process reached is the count of calls the measurement actually made."""
    merged = {**prior, **manifest}
    for k in MERGE_BY_CANDIDATE:
        merged[k] = {**(prior.get(k) or {}), **(manifest.get(k) or {})}
    sub = merged.get("subscription_budget")
    if isinstance(sub, dict):
        merged["subscription_budget"] = {
            **sub,
            "units_used": max(int((prior.get("subscription_budget") or {}).get("units_used") or 0),
                              int((manifest.get("subscription_budget") or {}).get("units_used") or 0))}
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


class Ctx:
    """Everything a run of one candidate needs that is the same for every candidate. It
    exists so the winner's checks and the dry run call `run_candidate` through exactly the
    same arguments as the kit run does, rather than each assembling its own.

    A plain class, not a dataclass: this module is loaded by path (tests, and
    tools/consensus_reference.py's `_tool`) without being registered in `sys.modules`, and
    `@dataclass` resolves its annotations through `sys.modules[cls.__module__]` - which is
    None under that loader and raises at import time."""

    def __init__(self, *, batches, reference, source, dom, cb, cache, schema, excl, budget,
                 prior_spend, spend_by, tracked_by, list_cost_by, cache_keys=None, ids50=(),
                 prov=None, before=None, ceiling=0.0, sub_units_cap=SUBSCRIPTION_MAX_UNITS,
                 sub_max_wall=SUBSCRIPTION_MAX_WALL_SECONDS, clock=time.time, log=print):
        self.batches, self.reference, self.source = batches, reference, source
        self.dom, self.cb, self.cache, self.schema, self.excl = dom, cb, cache, schema, excl
        self.budget, self.prior_spend = budget, prior_spend
        self.spend_by, self.tracked_by, self.list_cost_by = spend_by, tracked_by, list_cost_by
        # The per-unit cache-key map the manifest publishes. It lives on the context because
        # the winner's checks fill it too: spec section 6 asks for per-unit keys for every
        # candidate, and `winner_checks` recorded none, so the b5 and stability reads that
        # decide `stable` had no key evidence behind them at all (final-review I2).
        self.cache_keys = {} if cache_keys is None else cache_keys
        self.ids50 = set(ids50)
        self.prov = prov                     # the OpenRouter provider, or None if unused
        self.before = before                 # credits before this process, or None
        self.ceiling = ceiling
        self.clock, self.log = clock, log
        # Both subscription ceilings belong to the process, not to a read: one shared unit
        # counter (`budget["sub_units"]`) and one deadline set the first time a
        # subscription budget is asked for.
        self.sub_units_cap = int(sub_units_cap)
        self.sub_max_wall = float(sub_max_wall)
        self.sub_deadline = self.clock() + self.sub_max_wall
        self.budget.setdefault("sub_units", 0)

    def keys_for_run(self, out, pin: ModelPin) -> dict:
        """The per-unit cache keys behind one finished read, through this context's inputs."""
        return keys_for(out.plan.units, self.cb, pin, self.source, self.cache, self.schema,
                        self.dom.reader.families)

    def sub_units_left(self) -> int:
        return max(self.sub_units_cap - int(self.budget.get("sub_units", 0)), 0)

    def sub_seconds_left(self) -> float:
        return max(self.sub_deadline - self.clock(), 0.0)

    def budget_for_run(self, cand: dict, bs, *, cap: float | None = None) -> Budget:
        if is_subscription(cand):
            return budget_for(cand, 0.0, max_units=self.sub_units_left(),
                              max_wall_seconds=self.sub_seconds_left())
        remaining = self.budget["remaining"]
        return budget_for(cand, remaining if cap is None else min(remaining, cap))

    def settle(self, cand: dict, out=None) -> float | None:
        """Close the books on the run just finished.

        A subscription run spends units out of the process-wide counter: every one of its
        paid requests is unpriced, so the driver's `unpriced_requests` is exactly how many
        CLI calls it made, split halves included. It is never reconciled - it spends no
        credits, so re-reading /credits would attribute somebody else's spend to it and, on
        a subscription-only invocation, there is no key to read with."""
        if is_subscription(cand):
            if out is not None:
                spent = int((out.manifest or {}).get("unpriced_requests") or 0)
                self.budget["sub_units"] = int(self.budget.get("sub_units", 0)) + spent
                self.log(f"   subscription units {self.budget['sub_units']}/{self.sub_units_cap} "
                         f"used ({spent} this run); {self.sub_seconds_left():.0f}s of the "
                         f"{self.sub_max_wall:.0f}s window left")
            return None
        if self.prov is None or self.before is None:
            return None
        return reconcile(self.prov, self.before, self.ceiling, self.budget, self.log)


def winner_checks(ctx: Ctx, w: str, wpin: ModelPin, provider, cand: dict, b18: dict,
                  sp: Path, ts: str) -> dict:
    """The two checks the winner alone earns: the batch-size pair (5-case batches over the
    same kit) and the stability pair (two reads of the fifty-case sample). Both go through
    the winner's OWN provider and budget kind, so a subscription winner is checked on units
    and wall-clock and buys no OpenRouter credit."""
    log, out_m = ctx.log, {}
    log(f"\n== winner {wpin.label}: batch-size pair (5-case batches over the same kit)")
    small = small_batches(ctx.batches)
    try:
        out5 = run_candidate(wpin, provider, ctx.budget_for_run(cand, small), small, ctx.source,
                             ctx.dom, ctx.cb, ctx.cache, log, ctx.budget)
        d5 = ctx.settle(cand, out5)
        s5 = score(out5, ctx.reference, f"{w}:b5", ctx.prior_spend, ctx.spend_by, ctx.tracked_by,
                   d5, excluded=ctx.excl)
        ctx.list_cost_by[f"{w}:b5"] = s5["list_cost_usd"]
        ctx.cache_keys[f"{w}:b5"] = {"pin": wpin.label, "units": ctx.keys_for_run(out5, wpin)}
        out_m["batch_size_pair"] = {"b18": b18, "b5": s5}
        log(line(s5))
    except Exception as exc:                                    # noqa: BLE001
        out_m["batch_size_pair"] = {"b18": b18, "b5": None,
                                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        log(f"   batch-size pair FAILED {exc}")

    log(f"\n== winner {wpin.label}: stability, two reads of the fifty-case sample")
    st1 = sample_batches(ctx.batches, ctx.ids50, "st1")
    st2 = sample_batches(ctx.batches, ctx.ids50, "st2")
    try:
        o1 = run_candidate(wpin, provider, ctx.budget_for_run(cand, st1), st1, ctx.source, ctx.dom,
                           ctx.cb, ctx.cache, log, ctx.budget)
        d1 = ctx.settle(cand, o1)
        ctx.spend_by[f"{w}:stab1"] = charged(d1, o1.spend_usd)
        ctx.cache_keys[f"{w}:stab1"] = {"pin": wpin.label, "units": ctx.keys_for_run(o1, wpin)}
        o2 = run_candidate(wpin, provider, ctx.budget_for_run(cand, st2), st2, ctx.source, ctx.dom,
                           ctx.cb, ctx.cache, log, ctx.budget)
        d2 = ctx.settle(cand, o2)
        ctx.spend_by[f"{w}:stab2"] = charged(d2, o2.spend_usd)
        ctx.cache_keys[f"{w}:stab2"] = {"pin": wpin.label, "units": ctx.keys_for_run(o2, wpin)}
        # R12: the bar is agreement among the answers BOTH reads decided. A field the
        # second read left null is not instability, it is a decided-rate fact, reported
        # beside it as `decided_rate_b`. `stability_flat_agreement` is the blended v1
        # number, kept only so v2 can be read against v1.
        stab = stability_decided(o1.records, o2.records)
        stable = bool(stab) and all(v["agreement_decided"] >= STABILITY_BAR for v in stab.values())
        out_m["stability"] = stab
        out_m["stable"] = stable
        out_m["stability_flat_agreement"] = stability_agreement(o1, o2)
        out_m["stability_stops"] = [o1.stop.kind, o2.stop.kind]
        write_json(sp, {"codebook": ctx.cb.id, "codebook_sha": ctx.cb.sha, "model_pin": wpin.label,
                        "sample": getattr(ctx.dom.reader, "stability_sample", ""), "agreement": stab,
                        "stable": stable, "bar": STABILITY_BAR, "ts": ts}, indent=1)
        log(f"   stability {dumps(stab)} stable={stable}")
    except Exception as exc:                                    # noqa: BLE001
        out_m["stability"] = None
        out_m["stability_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        log(f"   stability FAILED {exc}")
    return out_m


# Everything `winner_checks` writes. They belong to ONE candidate - the winner that earned
# them - and there is no such thing as half of them applying to somebody else.
WINNER_CHECK_FIELDS = ("batch_size_pair", "stability", "stable", "stability_flat_agreement",
                       "stability_stops", "stability_error")


def prior_checks_owner(prior: dict) -> str | None:
    """Which candidate the manifest's recorded stability and batch-size pair belong to, or
    None if it recorded none. `selection.winner` names it; a manifest that recorded only
    `winner_pin` is resolved back through `pins`."""
    if not any(prior.get(f) is not None for f in WINNER_CHECK_FIELDS):
        return None
    w = (prior.get("selection") or {}).get("winner")
    if w:
        return w
    label = prior.get("winner_pin")
    return next((mid for mid, l in (prior.get("pins") or {}).items() if l == label), None)


def winner_model_fields(pin: ModelPin) -> dict:
    """What domain.yaml's `reader.model` is set from, recorded for the pin that actually ran."""
    return {"winner_pin": pin.label,
            "winner_model": {"model_id": pin.model_id, "family": pin.family,
                             "provider_name": pin.provider_name, "precision": pin.precision,
                             "extra": dict(pin.extra)}}


def unrun_winner_checks(ctx: Ctx, w: str, wpin: ModelPin | None, prior: dict, prov,
                        merged_scores: dict, sp: Path, ts: str) -> dict:
    """3A N5. The winner is recomputed over every candidate on record, so it can be one this
    process did not run - and the `stability` / `batch_size_pair` already in the manifest may
    then belong to a DIFFERENT candidate. `merge_manifest` keeps whole-manifest fields the
    prior process wrote, so simply saying nothing here republished another model's stability
    under the new winner's name, which is the one thing a pre-registered check may never do.

    So: carry the recorded checks forward only when the manifest says they are this winner's;
    otherwise run them for the real winner, on its own transport and inside whatever budget is
    left; and when they cannot be run, write every one of them as null with the reason, so the
    manifest says "missing" rather than showing somebody else's numbers."""
    log, owner = ctx.log, prior_checks_owner(prior)
    if owner == w:
        log(f"\n== winner {w} was recorded by an earlier process and not re-run here; the "
            f"batch-size pair and stability check in the manifest were recorded FOR IT and "
            f"are carried forward (nothing spent on them)")
        return {"winner_checks_source": f"carried forward from the prior manifest, recorded for {w}"}

    cand = next((c for c in ctx.dom.reader.candidates if c["model_id"] == w), None)
    why_not = None
    if cand is None:
        why_not = f"{w} is not a candidate in domain.yaml, so its checks cannot be run here"
    elif not is_subscription(cand) and ctx.budget["remaining"] <= 0:
        why_not = "the OpenRouter budget was exhausted before the winner's checks could run"
    else:
        try:
            provider, pin, why = provider_for(cand, prov)
        except Exception as exc:                                # noqa: BLE001 - as in the kit loop
            provider, pin, why = None, None, f"resolving it raised {type(exc).__name__}: {str(exc)[:300]}"
        if pin is None:
            why_not = f"cannot resolve a transport for {w}: {why}"
        else:
            log(f"\n== winner {w} was not run by this process, and the checks recorded in the "
                f"manifest belong to {owner or 'no candidate on record'} - running them for "
                f"{pin.label} instead ({why})")
            out = winner_checks(ctx, w, pin, provider, cand, merged_scores.get(w), sp, ts)
            out.update(winner_model_fields(pin))
            out["winner_checks_source"] = f"run by this process for {pin.label}, the recomputed winner"
            return out

    log(f"\n!! winner {w}: {why_not}. The batch-size pair and stability check recorded in the "
        f"manifest belong to {owner or 'no candidate on record'} and are NOT carried forward.")
    missing = {f: None for f in WINNER_CHECK_FIELDS}
    missing["winner_checks_source"] = f"missing: {why_not}"
    missing["winner_checks_missing"] = {"winner": w, "recorded_checks_belong_to": owner,
                                        "reason": why_not}
    if wpin is not None:
        missing.update(winner_model_fields(wpin))
    return missing


def dry_run(cands: list[dict], n_batches: int, ctx: Ctx, out_dir: Path, *, prior: dict | None = None,
            prior_usd: float = 0.0, ts: str | None = None) -> int:
    """Buy the first `n_batches` kit batches for each named candidate and stop, into the
    SAME cache and measurement directory the field run uses - so the gate is paid for once
    and the field run replays it for free. It selects nothing: a one-batch read is not a
    measurement, so it writes no `scores` and no `selection`.

    It does, however, write what it SPENT into the manifest, merged per candidate exactly as
    a normal candidate run's spend is (`spend_by_candidate`, `tracked_spend_by_candidate`,
    `cache_keys`, `pins`, `list_cost_by_candidate`, and the task totals). 9a re-review N1: the
    dry-run dispatch sits outside `main`'s try/finally, so until now a dry run's money was
    recorded nowhere. Two things went wrong with that. The next run's `resolve_prior_spend`
    could not see it and re-granted a ceiling that was already partly spent; and `score`
    found no `recorded` figure for the units the field run then replayed from the dry run's
    cache, which is what marked gemini `[UNPRICED]` on 2026-09-05 against $0.94 of real spend.

    A candidate that cannot be resolved or that raises is recorded and the next one is still
    run: `sys.exit` mid-loop would kill the process after earlier candidates had already been
    bought. The exit status is non-zero if any candidate failed, so the gate is never read as
    passed on a partial result."""
    log, failures = ctx.log, {}
    prior = prior or {}
    ts = ts or time.strftime("%Y-%m-%dT%H:%M:%S")
    pins: dict[str, str] = {}
    cache_keys: dict[str, dict] = {}
    dry_runs: dict[str, dict] = {}
    # M3: the record of what this dry run spent is written from a `finally`, exactly as
    # `main` writes its own. `keys_for` and the payload assembly below run AFTER a paid
    # candidate and outside the per-candidate `try`, so a raise there used to lose the
    # spend record - which is the N1 failure this function's docstring says it fixed.
    finished = False
    try:
        for cand in cands:
            mid = cand["model_id"]
            provider, pin, why = provider_for(cand, ctx.prov)
            if pin is None:
                failures[mid] = f"cannot run: {why}"
                log(f"DRY RUN {mid} SKIPPED: {why}")
                continue
            one = ctx.batches[:max(1, int(n_batches))]
            ids = [b["batch_id"] for b in one]
            log(f"DRY RUN {pin.label} over {', '.join(ids)} "
                f"({sum(len(b['cases']) for b in one)} cases): {why}")
            budget = ctx.budget_for_run(cand, one, cap=DRY_RUN_MAX_USD)
            try:
                out = run_candidate(pin, provider, budget, one, ctx.source, ctx.dom, ctx.cb, ctx.cache,
                                    log, ctx.budget)
            except Exception as exc:                                # noqa: BLE001 - one candidate never aborts the gate
                failures[mid] = f"run raised {type(exc).__name__}: {str(exc)[:300]}"
                log(f"DRY RUN {mid} FAILED: {failures[mid]}")
                ctx.settle(cand)
                continue
            real_delta = ctx.settle(cand, out)
            # Scored through `score`, not `score_candidate`, for the same reason the field run
            # is: it is what fills `spend_by`/`tracked_by` and applies the one pricing rule.
            s = score(out, ctx.reference, mid, ctx.prior_spend, ctx.spend_by, ctx.tracked_by,
                      real_delta, excluded=ctx.excl)
            ctx.list_cost_by[mid] = s["list_cost_usd"]
            pins[mid] = pin.label
            unit_keys = keys_for(out.plan.units, ctx.cb, pin, ctx.source, ctx.cache, ctx.schema,
                                 ctx.dom.reader.families)
            cache_keys[mid] = {"pin": pin.label, "units": unit_keys}
            dry_runs[mid] = {"pin": pin.label, "batches": ids, "stop": out.stop.kind,
                             "spend_usd": ctx.spend_by[mid], "priced": s["priced"], "ts": ts}
            payload = {"candidate": mid, "pin": pin.label, "provider": getattr(provider, "name", "?"),
                       "why": why, "batches": ids, "schema_sha": schema_sha(ctx.schema),
                       "stop": out.stop.kind, "effort": EFFORT, "read_timeout_seconds": READ_TIMEOUT,
                       "max_tokens": Request.max_tokens,
                       "budget": {"max_usd": budget.max_usd, "max_units": budget.max_units,
                                  "max_wall_seconds": budget.max_wall_seconds},
                       "units": [{"unit_id": u.unit_id, "status": u.status, "cache_hit": u.cache_hit,
                                  "retried": u.retried, "error": u.error,
                                  "finish_reason": (u.response.finish_reason if u.response else None),
                                  "input_tokens": (u.response.input_tokens if u.response else None),
                                  "output_tokens": (u.response.output_tokens if u.response else None),
                                  "cost_usd": (u.response.cost_usd if u.response else None),
                                  "list_cost_usd": ((u.response.raw or {}).get("list_cost_usd")
                                                    if u.response else None)}
                                 for u in out.units],
                       "status_counts": {st: sum(1 for r in out.records if r.get("extraction_status") == st)
                                         for st in ("ok", "partial", "extraction-invalid", "missing")},
                       "nulled_fields": sorted({f for u in out.units for r in u.records for f in r.nulled_fields}),
                       "dropped_quotes": sum(r.dropped_quotes for u in out.units for r in u.records),
                       "score": s, "priced": s["priced"], "list_cost_usd": s["list_cost_usd"],
                       "spend_usd": out.spend_usd, "wall_seconds": round(out.wall_seconds, 1),
                       "cache_keys": unit_keys,
                       "first_record": (out.records or [None])[0]}
            write_json(out_dir / f"dry-run-{mid.replace('/', '_')}.json", payload, indent=1, sort_keys=True)
            log(dumps({k: payload[k] for k in ("stop", "status_counts", "nulled_fields", "dropped_quotes",
                                               "spend_usd", "list_cost_usd", "wall_seconds")}, indent=1))

        finished = True
    finally:
        m: dict = {"pins": pins, "cache_keys": cache_keys, "dry_runs": dry_runs,
                   "spend_by_candidate": ctx.spend_by, "tracked_spend_by_candidate": ctx.tracked_by,
                   "list_cost_by_candidate": ctx.list_cost_by,
                   "tracked_spend_usd": round(ctx.budget["spent"], 4), "ts": ts}
        if ctx.prov is None:
            m["total_task_spend_usd"] = round(prior_usd, 4)
        else:
            m["credits_before"] = round(ctx.before, 4) if ctx.before is not None else None
            m["spent_usd"] = round(ctx.budget["real_spent"], 4)
            m["total_task_spend_usd"] = round(prior_usd + ctx.budget["real_spent"], 4)
        write_json(out_dir / "manifest.json", merge_manifest(prior, m), indent=1, sort_keys=True)
        log(f"dry run recorded ${m['total_task_spend_usd']} of measurement spend in "
            f"{out_dir / 'manifest.json'} (nothing selected; no scores written)")
        if not finished:
            log('!! the dry run raised before it finished; the spend above is what it had '
                'charged at that point, so the next run\'s ceiling guard is not under-counted')
    if failures:
        log("DRY RUN FAILURES: " + dumps(failures, indent=1))
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, default=OPENROUTER_CEILING,
                    help=f"the whole slice's OpenRouter ceiling; may not exceed ${OPENROUTER_CEILING:.2f} (D5)")
    ap.add_argument("--only", default=None)
    # Omitted, this is read off the prior manifest (see resolve_prior_spend); pass an
    # explicit 0 to deliberately re-grant the whole ceiling.
    ap.add_argument("--prior-spend-usd", type=float, default=None)
    ap.add_argument("--measurement-dir", default=DEFAULT_MEASUREMENT_DIR,
                    help="where the manifest and the dry-run files are written, relative to the "
                         "repo root. measurement-v1 is frozen; pass it only with --annotate-only. "
                         "A run that SPENDS refuses any other value unless --allow-measurement-dir "
                         "is passed with it (the ceiling is per manifest directory).")
    ap.add_argument("--allow-measurement-dir", action="store_true",
                    help="permit a paid run to write somewhere other than "
                         f"{DEFAULT_MEASUREMENT_DIR}. Read the ceiling note on --measurement-dir "
                         "first: prior spend is read from the manifest in THAT directory, so a "
                         "second directory is granted the full --max-usd a second time.")
    ap.add_argument("--dry-run", default=None,
                    help="run the first --dry-run-batches kit batches for this candidate, write "
                         "the inspection file, and stop without selecting anything")
    ap.add_argument("--dry-run-batches", type=int, default=None,
                    help="how many kit batches a dry run buys (default 1). Requires --dry-run: "
                         "a batch count alone names no candidate and must never be read as "
                         "permission to buy them all.")
    ap.add_argument("--sub-max-units", type=int, default=None,
                    help="unit ceiling shared by every subscription read this PROCESS makes "
                         "(default: the units the selected subscription candidates need across "
                         "the kit and the winner's checks, plus a margin - computed and printed)")
    ap.add_argument("--sub-max-wall-seconds", type=float, default=SUBSCRIPTION_MAX_WALL_SECONDS,
                    help="wall-clock ceiling for the whole PROCESS's subscription reads, from "
                         "the moment the run starts (default 6 h)")
    ap.add_argument("--codebook", default=None,
                    help="codebook id to read instead of domain.yaml's. --annotate-only only.")
    ap.add_argument("--kit-path", default=None,
                    help="kit to read instead of domain.yaml's, repo-relative. Its sha256 is "
                         "NOT verified against domain.yaml, so --annotate-only only.")
    ap.add_argument("--stability-sample", default=None,
                    help="fifty-case sample to read instead of domain.yaml's. --annotate-only only.")
    ap.add_argument("--annotate-only", action="store_true",
                    help="recompute the manifest's derived records (cache keys, per-candidate "
                         "read timeout, budget envelope) from the existing manifest and the "
                         "response cache. Makes no request of any kind and spends nothing.")
    a = ap.parse_args(argv)

    # I3: --max-usd is a ceiling on the SLICE, and `resolve_prior_spend` reads what has
    # already been spent out of the manifest in `--measurement-dir` - only that one. A paid
    # run pointed at a fresh directory therefore sees prior spend 0.0 and is granted the whole
    # ceiling again, so two directories can spend $30 of a $15 cap. The slice uses exactly one
    # directory, and a run that spends may not silently move: naming another one is a
    # deliberate act that has to be typed out.
    if (a.measurement_dir != DEFAULT_MEASUREMENT_DIR and not a.annotate_only
            and not a.allow_measurement_dir):
        sys.exit(f"--measurement-dir {a.measurement_dir} is not {DEFAULT_MEASUREMENT_DIR}, and a "
                 f"run that spends reads prior spend only out of the manifest in the directory "
                 f"it writes: a second directory would be granted the whole --max-usd ceiling a "
                 f"second time. Pass --annotate-only (offline), or --allow-measurement-dir if a "
                 f"separate ceiling is really what you want.")
    if a.max_usd > OPENROUTER_CEILING:
        sys.exit(f"--max-usd {a.max_usd} exceeds this slice's approved OpenRouter ceiling "
                 f"${OPENROUTER_CEILING:.2f} (spec decision D5)")
    # Two sharp edges on a money flag, closed here rather than in the dispatch below.
    # `--dry-run-batches 3` alone used to dry-run every candidate, and `0` - the natural
    # spelling of "buy nothing" - is falsy and fell straight through to the paid field run.
    if a.dry_run_batches is not None:
        if not a.dry_run:
            sys.exit("--dry-run-batches names no candidate; pass --dry-run <model_id> with it")
        if a.dry_run_batches < 1:
            sys.exit(f"--dry-run-batches {a.dry_run_batches} buys nothing; pass 1 or more, or "
                     f"omit the flag entirely")

    # The three inputs domain.yaml names may be overridden ONLY for the offline annotation:
    # measurement-v1 was bought under mapper-v2 and kit v1, and re-deriving its records now
    # that domain.yaml names v3/v2 means saying so. A paid run reads what domain.yaml names
    # and nothing else, sha256-verified.
    overridden = sorted(f for f, v in (("--codebook", a.codebook), ("--kit-path", a.kit_path),
                                       ("--stability-sample", a.stability_sample)) if v)
    if overridden and not a.annotate_only:
        sys.exit(f"{', '.join(overridden)} may only be passed with --annotate-only: a run that "
                 f"spends reads the codebook and kit domain.yaml names, verified by sha256")

    dom = load_domain()
    kit_path = ROOT / (a.kit_path or dom.reader.kit_path)
    if a.kit_path:
        print(f"reading {a.kit_path} instead of domain.yaml's kit (sha256 not verified; "
              f"offline annotation only)", flush=True)
    elif dom.reader.kit_sha256 and sha256_file(kit_path) != dom.reader.kit_sha256:
        sys.exit("kit sha256 does not match domain.yaml; never edit the kit")
    reference, batches, source = load_kit(kit_path)

    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    n_cached = len(list(cache.dir.glob("*.json")))
    print(f"response cache: {cache.dir} ({n_cached} entries)", flush=True)
    out_dir = ROOT / a.measurement_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    prior_path = out_dir / "manifest.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
    prior_spend = dict(prior.get("spend_by_candidate") or {})
    spend_by: dict[str, float] = {}
    tracked_by: dict[str, float] = {}
    list_cost_by: dict[str, float | None] = {}

    cb = load_codebook(dom, a.codebook or dom.reader.codebook)
    print(f"codebook {cb.id} sha {cb.sha}", flush=True)

    if a.annotate_only:
        return annotate(prior, prior_path, cb, batches, source, dom, cache,
                        stability_sample=a.stability_sample or dom.reader.stability_sample)

    cands = selected_candidates(dom, a.only, a.dry_run)
    if not cands:
        sys.exit(f"{a.dry_run or a.only} is not a candidate in domain.yaml")
    subscription = sorted(c["model_id"] for c in dom.reader.candidates if is_subscription(c))
    excl = excluded_fields(reference)
    schema = record_schema(cb)
    print(f"schema sha {schema_sha(schema)[:12]}; {len(excl)} cases carry an excluded field", flush=True)

    prior_usd, why_prior = resolve_prior_spend(a.prior_spend_usd, prior)
    ceiling = a.max_usd - prior_usd
    prov, before = None, None
    if needs_openrouter(cands):
        key = store.env_value("OPENROUTER_API_KEY")
        if not key:
            sys.exit("no OPENROUTER_API_KEY")
        prov = OpenRouterProvider(key, timeout=READ_TIMEOUT)
        before = credits_remaining(prov)
        print(f"openrouter credits remaining before the run: ${before:.2f} "
              f"(ceiling ${a.max_usd:.2f} less ${prior_usd:.2f} already spent [{why_prior}] "
              f"= ${ceiling:.2f})", flush=True)
        if ceiling <= 0:
            sys.exit(f"nothing left of the ${a.max_usd:.2f} ceiling: ${prior_usd:.2f} already spent ({why_prior})")
        if before < ceiling:
            sys.exit(f"remaining credits ${before:.2f} < remaining ceiling ${ceiling:.2f}; top up or lower --max-usd")
    else:
        print("subscription-only invocation: no OpenRouter key read, no credits call, "
              "nothing charged against the ceiling", flush=True)

    sp = stability_path(dom, cb)
    if not sp.exists():
        # the measurement itself is the stability run for v2: grant a provisional
        # record so pre-flight lets the reads start, replaced with the real one below
        sp.parent.mkdir(parents=True, exist_ok=True)
        write_json(sp, {"codebook": cb.id, "codebook_sha": cb.sha, "provisional": True,
                        "note": "measurement in progress"}, indent=1)
        print(f"wrote provisional stability record {sp.name}", flush=True)

    # R11: `budget` is the per-process spend state every run threads through, and it is
    # defined here - before the dry run, which uses it too - rather than after the loop.
    # `sub_units` is the shared subscription counter every subscription read draws on.
    budget = {"remaining": ceiling, "spent": 0.0, "real_spent": 0.0, "sub_units": 0}
    ids50 = set(json.loads((ROOT / dom.reader.stability_sample).read_text(encoding="utf-8")))
    sub_cands = [c for c in cands if is_subscription(c)]
    unit_plan = process_unit_cap(len(sub_cands), batches, ids50)
    sub_units_cap = a.sub_max_units if a.sub_max_units is not None else unit_plan["total"]
    if sub_cands:
        print(f"subscription ceilings for THIS PROCESS, shared by every subscription read: "
              f"{sub_units_cap} units ({len(sub_cands)} candidate(s) over {len(batches)} kit "
              f"batches = {unit_plan['kit']}, + {unit_plan['batch_size_pair']} for the 5-case "
              f"pair, + {unit_plan['stability']} for the two stability reads, + "
              f"{unit_plan['margin']} margin for split halves"
              + ("" if a.sub_max_units is None else "; overridden by --sub-max-units") + "); "
              f"{a.sub_max_wall_seconds:.0f}s of wall clock from now", flush=True)
    # Defined before the context so the winner's checks can add their own units to the same
    # map the kit runs fill (I2); `main`'s loop below writes into this very dict.
    cache_keys: dict[str, dict] = {}
    ctx = Ctx(batches=batches, reference=reference, source=source, dom=dom, cb=cb, cache=cache,
              schema=schema, excl=excl, budget=budget, prior_spend=prior_spend, spend_by=spend_by,
              tracked_by=tracked_by, list_cost_by=list_cost_by, cache_keys=cache_keys,
              ids50=ids50, prov=prov, before=before, ceiling=ceiling, sub_units_cap=sub_units_cap,
              sub_max_wall=a.sub_max_wall_seconds, log=print)

    # `--dry-run-batches` alone can no longer get here: it is refused at parse time.
    if a.dry_run:
        return dry_run(cands, a.dry_run_batches or 1, ctx, out_dir, prior=prior, prior_usd=prior_usd)

    scores: dict[str, dict] = {}
    pins: dict[str, str] = {}
    providers: dict[str, str] = {}
    pin_objs: dict[str, ModelPin] = {}
    provider_objs: dict[str, object] = {}
    cand_objs: dict[str, dict] = {}
    efforts: dict[str, str] = {}
    timeouts: dict[str, int] = {}
    skipped: dict[str, str] = {}
    failed: dict[str, str] = {}
    not_run: dict[str, str] = {}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    def selection() -> dict:
        """Selection is decided over every candidate on record, not only the ones this
        process ran, so `--only` can never crown its single candidate by construction (I8).
        It is wrapped because it is also called from the `finally` below, where raising
        again would lose the spend record the finally exists to save.

        D4's tie-break is keyed on pin LABELS, so that is what is handed over - the labels of
        the pins this process built plus the subscription labels a prior manifest recorded
        (`subscription_labels`), never bare model ids, which could not match a label-keyed
        score and left the tie-break dead."""
        try:
            return select_reader({**(prior.get("scores") or {}), **scores},
                                 subscription=subscription_labels(dom, pins, prior))
        except Exception as exc:                                # noqa: BLE001
            return {"winner": None, "rule": f"selection failed: {type(exc).__name__}: {exc}",
                    "survivors": sorted(scores), "eliminated": {}, "shortfall": True,
                    "best_macro": None}

    def assemble(sel_now: dict) -> dict:
        """The manifest as it stands right now. Called on the happy path and again from the
        `finally`, so a process that dies after buying candidates 1..n still records what it
        charged - without which the NEXT run's `resolve_prior_spend` under-counts and
        re-grants a ceiling that was already spent.

        `credits_before` / `spent_usd` are written only when this process actually used
        OpenRouter: a subscription-only run charges nothing, and writing its zero over what
        an earlier OpenRouter process recorded in the same manifest would degrade the
        measurement's own record of what it cost. Omitted here, `merge_manifest`'s
        `{**prior, **manifest}` leaves the prior values standing."""
        m = {"kit_sha256": dom.reader.kit_sha256, "kit_path": dom.reader.kit_path,
             "codebook": cb.id, "codebook_sha": cb.sha, "schema_sha": schema_sha(schema),
             # Which composition of ResponseCache.key addresses this manifest's purchases, so
             # `--annotate-only` never has to guess (C1). measurement-v1 carries no marker and
             # is recognised by the absence of `schema_sha`; see `cache_key_version`.
             "cache_key_version": "v2",
             "openrouter_ceiling_usd": OPENROUTER_CEILING, "budget_usd": a.max_usd,
             "prior_spend_usd": round(prior_usd, 4), "prior_spend_source": why_prior,
             "effective_budget_usd": round(ceiling, 4),
             "subscription_candidates": list(subscription),
             "subscription_pins": sorted(subscription_labels(dom, pins, prior)),
             "subscription_budget": {"max_units": sub_units_cap,
                                     "max_wall_seconds": a.sub_max_wall_seconds,
                                     "units_planned": unit_plan,
                                     "units_used": int(budget.get("sub_units", 0)),
                                     "fallback_max_units": SUBSCRIPTION_MAX_UNITS},
             "reasoning": REASONING, "effort_by_candidate": efforts,
             "read_timeout_by_candidate": timeouts, "max_tokens": Request.max_tokens,
             "batch_size": max((len(b["cases"]) for b in batches), default=0),
             "cache_keys": cache_keys,
             "excluded_fields_by_case": {str(k): sorted(v) for k, v in excl.items()},
             "list_cost_by_candidate": list_cost_by,
             "priced_by_candidate": {k: s["priced"] for k, s in scores.items()},
             "pins": pins, "providers": providers, "skipped": skipped, "failed": failed,
             "not_run": not_run, "scores": scores, "selection": sel_now,
             # D4's floors per candidate, with the exact number each failed on, so a reader
             # sees that glm went out on a polarity decided rate of 0.8983 < 0.90 rather
             # than guessing. Recomputed over the merged scores every run, so it is a
             # whole-manifest field and never merged per candidate: a candidate that
             # re-runs and now survives must not keep a stale elimination reason.
             "eliminated_by_candidate": dict(sel_now.get("eliminated") or {}),
             "spend_by_candidate": spend_by, "tracked_spend_by_candidate": tracked_by,
             "tracked_spend_usd": round(budget["spent"], 4),
             "ts": ts}
        if prov is not None:
            m["credits_before"] = round(before, 4)
            m["spent_usd"] = round(budget["real_spent"], 4)
        return m

    finished = False
    try:
        for cand in cands:
            mid = cand["model_id"]
            if not is_subscription(cand) and budget["remaining"] <= 0:
                not_run[mid] = "budget exhausted before this candidate ran"
                print(f"NOT RUN {mid}: budget exhausted", flush=True)
                continue
            try:
                # provider_for is INSIDE the try: a malformed candidate (`provider:
                # claude-cli` with no `cli_model`) raises KeyError here, and one bad entry
                # in domain.yaml must cost that candidate, not the whole measurement.
                provider, pin, why = provider_for(cand, prov)
                print(f"PIN {mid} -> {pin.label if pin else 'SKIP'}  ({why})", flush=True)
                if pin is None:
                    skipped[mid] = why
                    continue
                print(f"== {pin.label}  (openrouter remaining ${budget['remaining']:.2f})", flush=True)
                out = run_candidate(pin, provider, ctx.budget_for_run(cand, batches), batches,
                                    source, dom, cb, cache, print, budget)
            except Exception as exc:                            # noqa: BLE001 - one candidate never aborts the run
                failed[mid] = f"candidate raised {type(exc).__name__}: {str(exc)[:300]}"
                print(f"   FAILED {failed[mid]}", flush=True)
                ctx.settle(cand)
                continue
            real_delta = ctx.settle(cand, out)
            if out.stop.kind.startswith("preflight:"):
                failed[mid] = f"pre-flight refusal {out.stop.kind}: {out.stop.detail}"
                print(f"   FAILED {failed[mid]}", flush=True)
                continue
            s = score(out, reference, mid, prior_spend, spend_by, tracked_by, real_delta, excluded=excl)
            if s["accepted"] == 0:
                errs = sorted({u.error for u in out.units if u.error})[:2]
                failed[mid] = (f"no accepted records ({len(out.units)} units, stop={out.stop.kind}"
                               + ("; " + "; ".join(errs) if errs else "") + ")")
                print(f"   FAILED {failed[mid]}", flush=True)
                print(line(s), flush=True)
                continue
            scores[mid] = s
            pins[mid] = pin.label
            providers[mid] = getattr(provider, "name", "?")
            pin_objs[mid] = pin
            provider_objs[mid] = provider
            cand_objs[mid] = cand
            efforts[mid] = EFFORT
            timeouts[mid] = READ_TIMEOUT
            list_cost_by[mid] = s["list_cost_usd"]
            cache_keys[mid] = {"pin": pin.label,
                               "units": keys_for(out.plan.units, cb, pin, source, cache, schema,
                                                 dom.reader.families)}
            print(line(s), flush=True)
            if not is_subscription(cand) and budget["remaining"] <= 0:
                print("budget exhausted", flush=True)

        sel = selection()
        all_pins = {**(prior.get("pins") or {}), **pins}
        manifest = assemble(sel)

        w = sel["winner"]
        if w:
            wpin = pin_objs.get(w)
            if wpin is None and all_pins.get(w):
                wpin = pin_from_label(all_pins[w], dom.reader.families)
            if wpin is not None:
                manifest.update(winner_model_fields(wpin))
        if w and w in pin_objs:
            manifest.update(winner_checks(ctx, w, pin_objs[w], provider_objs[w], cand_objs[w],
                                          scores[w], sp, ts))
            manifest["winner_checks_source"] = f"run by this process for {pin_objs[w].label}"
        elif w:
            manifest.update(unrun_winner_checks(ctx, w, wpin, prior, prov,
                                                {**(prior.get("scores") or {}), **scores}, sp, ts))

        # the winner's checks spend and settle, so re-read the counters they moved
        manifest["tracked_spend_usd"] = round(budget["spent"], 4)
        manifest["spend_by_candidate"] = spend_by
        manifest["tracked_spend_by_candidate"] = tracked_by
        manifest["list_cost_by_candidate"] = list_cost_by
        manifest["subscription_budget"]["units_used"] = int(budget.get("sub_units", 0))
        if prov is None:
            manifest["total_task_spend_usd"] = round(prior_usd, 4)
        else:
            try:
                after = credits_remaining(prov)
                manifest["credits_after"] = round(after, 4)
                manifest["spent_usd"] = round(before - after, 4)
            except Exception as exc:                            # noqa: BLE001
                manifest["credits_after"] = None
                manifest["spent_usd"] = round(budget["real_spent"], 4)
                print(f"credits lookup after the run failed: {exc}", flush=True)
            manifest["total_task_spend_usd"] = round(prior_usd + (manifest["spent_usd"] or 0.0), 4)
        write_json(prior_path, merge_manifest(prior, manifest), indent=1, sort_keys=True)
        finished = True
        print(dumps(sel, indent=1), flush=True)
        print(f"this process charged ${manifest.get('spent_usd', 0.0)} of the ${ceiling:.2f} it "
              f"had left; measurement total ${manifest['total_task_spend_usd']} of "
              f"${a.max_usd:.2f} (driver-tracked ${budget['spent']:.2f}); credits after "
              f"{manifest.get('credits_after')}", flush=True)
        print("set reader.model in domain.yaml to:", dumps(manifest.get("winner_model")), flush=True)
        return 0
    finally:
        if not finished:
            partial = assemble(selection())
            partial["incomplete"] = ("this process raised before it finished; the spend recorded "
                                     "here is what it had charged at that point, so the next "
                                     "run's --prior-spend-usd guard is not under-counted")
            if prov is not None:
                partial["total_task_spend_usd"] = round(prior_usd + budget["real_spent"], 4)
            write_json(prior_path, merge_manifest(prior, partial), indent=1, sort_keys=True)
            print(f"\n!! run did not finish; wrote the partial manifest to {prior_path} "
                  f"(charged ${budget['real_spent']:.4f}, driver-tracked ${budget['spent']:.4f}, "
                  f"{int(budget.get('sub_units', 0))} subscription units)", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
