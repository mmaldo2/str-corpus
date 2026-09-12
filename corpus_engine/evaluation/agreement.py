"""Measure 4: reviewer agreement per round, pair and field, on substantive labels."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from corpus_engine.evaluation.stats import cohens_kappa, estimate
from corpus_engine.evaluation.types import Envelope, Uncertainty, Provenance, Estimate

METHOD_VERSION = "agreement-1"
WITHDRAWN, UNSURE = "WITHDRAWN", "UNSURE"
PAIRS = (("claude", "astra"), ("claude", "user"), ("astra", "user"))
_MISSING = object()


@dataclass(frozen=True)
class PairStat:
    n: int
    raw: Estimate
    kappa: Estimate


@dataclass(frozen=True)
class RoundAgreement:
    round_id: str
    kind: str
    selection_rule: str
    exposure: str                 # "blind" | "exposure-affected"
    pairs: dict                   # {"claude-astra": {field: PairStat}}


@dataclass(frozen=True)
class Agreement:
    envelope: Envelope
    rounds: tuple[RoundAgreement, ...]
    excluded: tuple[dict, ...]
    unregistered_run_ids: tuple[str, ...]


def effective_label(d: Mapping, card: Mapping, checker_values: Mapping | None) -> str:
    field, decision = d.get("field"), d.get("decision")
    decide_fields = card.get("decide_fields") or [card.get("decide_field")]
    if field == "relevant" and decision == "adopt":
        # The apply tool's semantics: a relevant adopt on a queued card can only ever have
        # disagreed to False, so resolve it like any other adopt (via the checker's value),
        # and fall back to WITHDRAWN when the checker has no value for it.
        val = (checker_values or {}).get(field, _MISSING)
        if val is _MISSING or val in (False, "false", "False"):
            return WITHDRAWN
        return str(val)
    if (field == "relevant" and decision == "set" and d.get("value") in (False, "false", "False")
            and field not in decide_fields):
        # A card queued to decide a different field (e.g. who_was_letting) whose reader instead
        # answers "relevant: False" is withdrawing the whole card, spread to every judged field
        # below. A card queued to decide relevant itself is just answering that question, so its
        # explicit False is a real value (falls through to the literal-value return below), kept
        # distinct from an `adopt` of the checker's False (still WITHDRAWN, see above) — the
        # three-way sheet counted an independent False against an adopted False as a disagreement.
        return WITHDRAWN
    if decision == "unsure":
        return UNSURE
    if decision == "keep":
        return str((card.get("values") or {}).get(field))
    if decision == "adopt":
        return str((checker_values or {}).get(field))
    return str(d.get("value"))


def _cards(queue: Mapping) -> dict[int, Mapping]:
    out = {}
    for lst in (queue.get("sections") or {}).values():
        for c in lst:
            out[int(c["case_id"])] = c
    return out


def _labels(decisions: Sequence[Mapping], cards: Mapping[int, Mapping], checker: Mapping, *,
            initial: bool = False) -> dict[tuple[int, str], str]:
    """{(case_id, field): label}. A withdrawal labels every field of its card WITHDRAWN so a
    withdrawal against a field value is a disagreement and two withdrawals agree."""
    out: dict[tuple[int, str], str] = {}
    for d in decisions or ():
        cid = int(d["case_id"]); card = cards.get(cid)
        if card is None:
            continue
        fields = card.get("decide_fields") or [card.get("decide_field")]
        chk = (checker.get(str(cid)) or {}).get("values") if checker else None
        dd = dict(d)
        if initial and "initial_value" in d:
            dd["value"] = d["initial_value"]
        lab = effective_label(dd, card, chk)
        if lab == WITHDRAWN:
            for f in fields:
                out[(cid, f)] = WITHDRAWN
        elif d.get("field") in fields:
            out.setdefault((cid, d["field"]), lab)
    return out


def _pair(a: Mapping, b: Mapping, fields: Sequence[str]) -> dict[str, PairStat]:
    out = {}
    for f in fields:
        keys = [k for k in a if k[1] == f and k in b]
        pairs = [(a[k], b[k]) for k in keys]
        n = len(pairs)
        agree = sum(1 for x, y in pairs if x == y)
        kap = cohens_kappa(pairs)
        out[f] = PairStat(n, estimate(agree, n),
                          Estimate(kap, n, None, None, "ok") if kap is not None else Estimate(None, n, None, None, "undefined"))
    return out


def agreement(registry: Mapping, files: Mapping[str, object], *, ledger_run_ids: Sequence[str]) -> Agreement:
    rounds, excluded, named = [], [], set()
    for e in registry.get("rounds") or ():
        named.update(e.get("apply_run_ids") or ())
        queue = files[e["queue"]]; cards = _cards(queue)
        checker = files.get(e["checker"]) if e.get("checker") else {}
        fields = sorted({f for c in cards.values() for f in (c.get("decide_fields") or [c.get("decide_field")])})
        if e.get("user_mode") == "bulk_adopted_astra":
            # Excluded from every USER pair only: the claude-astra pair is still built below,
            # and the round still appears in `rounds` (with only claude-astra) as well as here.
            excluded.append({"round_id": e["round_id"],
                              "reason": "the user adopted Astra's view in bulk; user pairs excluded",
                              "cards": len(cards)})
        readers = {}
        if e.get("claude"):
            readers["claude"] = _labels(files[e["claude"]], cards, checker)
        if e.get("astra"):
            readers["astra"] = _labels(files[e["astra"]], cards, checker)
        if e.get("user") and e.get("user_mode") == "card_by_card":
            readers["user"] = _labels(files[e["user"]], cards, checker, initial=(e.get("kind") == "audit"))
        pairs = {f"{x}-{y}": _pair(readers[x], readers[y], fields) for x, y in PAIRS if x in readers and y in readers}
        rounds.append(RoundAgreement(e["round_id"], e.get("kind", "historical"), e.get("selection_rule", ""),
                                     "blind" if e.get("kind") == "audit" else "exposure-affected", pairs))
    named.update((registry.get("dispositions") or {}).keys())
    unregistered = tuple(sorted(set(ledger_run_ids) - named))
    env = Envelope(METHOD_VERSION,
                   "review-round cards decided by two model readers and, where the user decided card by card, the user",
                   ("rounds where the user adopted one reader in bulk are excluded from every user pair",),
                   Uncertainty("sampling", 0.95, "wilson"),
                   ("Historical rounds are workflow evidence: cards were selected by rules, readers saw the machine "
                    "values and the checker, and the user saw both readers' notes; only the audit round is blind.",),
                   Provenance(inputs=tuple((p, "", "registry-file") for p in sorted(files))))
    return Agreement(env, tuple(rounds), tuple(excluded), unregistered)
