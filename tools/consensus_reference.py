"""The who-was-letting reference for the kit cases nobody ever reviewed on that field
(spec section 7, decision D3).

155 of the 195 kit cases came from human-reviewed ledger records, but the review that
produced them was about relevance and polarity: 154 of them carry a who_was_letting value no
human ever checked. Scoring a reader against an unchecked label measures agreement with
whatever the first reader said. So: where at least 4 of the 5 measured finalists returned the
same non-null post-gate value under mapper-v2, that value becomes the reference on a machine
basis; the rest go to the user on a second review page.

Three kinds of case are never touched, because a human already decided them (R8, and the
scope note in tools/apply_reference_review.py):

  * a reviewer-basis `who_was_letting` patch already stands in the ledger;
  * the case was on the reference-v1 contested queue for `who_was_letting` at all - the
    adjudication is the user's whether or not they moved the value;
  * the ledger's CURRENT `relevant` flag is false. A case the user put out of the corpus
    carries no labels: it gets no consensus value and is not put back in front of them.

Offline. Reads the frozen kit, the measurement-v1 manifest and the purchased response cache;
issues no request and spends nothing.

Usage:
  .venv\\Scripts\\python tools\\consensus_reference.py --dry-run
  .venv\\Scripts\\python tools\\consensus_reference.py
"""
from __future__ import annotations
import argparse
import copy
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine.domain import load_domain                          # noqa: E402
from corpus_engine.ledger import LedgerView, open_ledger              # noqa: E402
from corpus_engine.ledger.fold import apply_patch                     # noqa: E402
from corpus_engine.ledger.types import Basis, Patch                   # noqa: E402
from corpus_engine.reader.cache import ResponseCache                  # noqa: E402
from corpus_engine.reader.codebook import load_codebook               # noqa: E402
from corpus_engine.reader.driver import plan_batch_extraction         # noqa: E402
from corpus_engine.reader.measure import load_kit                     # noqa: E402
from corpus_engine.reader.model import Budget                         # noqa: E402
from corpus_engine.reader.schema import WHO_VALUES                    # noqa: E402


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIELD = "who_was_letting"
# The vocabulary is the reader's schema, not a literal kept in step by hand: the consensus
# copies a value into the reference, it never invents one. `non_resident_owner` is the
# canonical spelling (domain.yaml letting_tiers matches it).
CONSENSUS_VOCABULARY = WHO_VALUES
CANDIDATES = ("anthropic/claude-opus-5", "openai/gpt-5.6-terra", "z-ai/glm-5.3",
              "google/gemini-3.7-flash", "anthropic/claude-sonnet-5")
CONSENSUS_K = 4
CONSENSUS_MODEL = "model-consensus:mapper-v2:4of5"
PROMPT_VERSION = "mapper-v2"
RUN_ID = "reference-v2-consensus"
DEFAULT_KIT = "data/reader/kit-v1/kit.json"
DEFAULT_CONTESTED = "data/reader/review/reference-v2/contested-who.json"
DEFAULT_STEM = "reports/review-queue-reference-v2"
MANIFEST = "data/reader/measurement-v1/manifest.json"
CACHE = "data/reader/cache"
UNREVIEWED = "data/reader/review/reference-v1/contested.json"      # carries who_was_letting_unreviewed

PAGE = {
    "title": "Reference adjudication v2 — who was letting",
    "md_title": "Reference adjudication v2 - who was letting, never human-reviewed",
    "intro": """These are reader-kit cases whose <code>who_was_letting</code> label
<b>no human has ever checked</b>, and on which the five measured reader models did
<b>not</b> reach 4-of-5 agreement under mapper-v2. Where they did agree, the agreed value is
now the reference on a machine basis; these are what is left. A model majority is not
authority — your decision is what the reference carries, and the kit is what every future
reader is scored against. Cases you already adjudicated on this field, and cases you ruled
out of the corpus, are not here. Decisions are saved into this page itself when you press
<b>Save decisions</b>; if the viewer cannot save, use <b>Copy JSON</b> and paste it back.
Citations link to CourtListener.""",
    "blurbs": {
        "B": """Who the letting party was ({n} cases). <b>Ledger says</b> is the
  never-reviewed label the kit currently carries — treat it as a first reader's guess, not
  as a reference. No quotes are offered: this field is not quote-gated, so the candidates
  were never asked to point at language for it. Each candidate's holding summary is shown
  instead.""",
    },
    "lede": ("{cases} kit cases whose who_was_letting label no human ever checked and on "
             "which fewer than 4 of the 5 reader finalists agreed; {decisions} decisions."),
}


def consensus(values: Mapping[str, object], k: int = CONSENSUS_K) -> tuple[object | None, int, int]:
    """The value at least `k` candidates returned, ignoring the ones that returned nothing.

    A null is not a vote: a candidate that left the field blank, or lost it to the gate, is
    silent, not a dissenter. Sorted so an exact tie is resolved the same way every run. A
    value outside the reader's vocabulary is counted (it is something the candidate said)
    but never awarded - it is not a reference label, however many candidates returned it."""
    counts = Counter(v for v in values.values() if v is not None)
    if not counts:
        return None, 0, 0
    value, n = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
    agreed = n >= k and value in CONSENSUS_VOCABULARY
    return (value if agreed else None), n, sum(counts.values())


def adjudicated_who(doc: Mapping) -> set[int]:
    """R8b: the cases the reference-v1 page put in front of the user on `who_was_letting`.
    Being asked is what matters, not the answer: a `keep` is as much the user's decision as
    an `adopt`, and an item they left blank is theirs to finish, not ours to overwrite."""
    return {int(c["case_id"]) for c in doc.get("contested", [])
            if FIELD in (c.get("contested_fields") or [])}


def reviewer_decided(view) -> set[int]:
    """R8a: cases where a human already set `who_was_letting` on a reviewer basis."""
    return {p.case_id for p in view.patches
            if p.basis.reviewer and p.op == "set" and p.field == FIELD}


def partition(ids: Iterable[int], view, adjudicated: Iterable[int]) -> tuple[list[int], list[int], list[int]]:
    """Split the never-reviewed ids into (eligible, skipped_reviewed, skipped_irrelevant).

    Disjoint, sorted, and in that precedence: a case the user decided is reported as
    decided even if it later went irrelevant. A case with no ledger record at all is not
    eligible - there is nothing to patch."""
    decided = reviewer_decided(view) | set(adjudicated)
    eligible, skipped_reviewed, skipped_irrelevant = [], [], []
    for cid in sorted({int(c) for c in ids}):
        if cid in decided:
            skipped_reviewed.append(cid)
        elif not (view.state.records.get(cid) or {}).get("relevant"):
            skipped_irrelevant.append(cid)
        else:
            eligible.append(cid)
    return eligible, skipped_reviewed, skipped_irrelevant


def patches_for(agreed: Mapping[int, tuple], records: Mapping[int, dict]) -> list[Patch]:
    """Machine-basis patches. `Basis.can_judge()` needs model + prompt_version + run_id, so
    all three are set; `reviewer` is never set - this is a model consensus, not a review."""
    basis = Basis(model=CONSENSUS_MODEL, prompt_version=PROMPT_VERSION, run_id=RUN_ID)
    out: list[Patch] = []
    for cid in sorted(agreed):
        value, n, non_null = agreed[cid]
        old = (records.get(cid) or {}).get(FIELD)
        why = f"reference v2 consensus: {FIELD} {n} of {non_null} finalists agreed"
        moved = f"{old!r} confirmed" if old == value else f"{old!r} -> {value!r}"
        out.append(Patch(int(cid), "set", FIELD, value, why, basis))
        out.append(Patch(int(cid), "append", "review.notes",
                         f"reference v2 consensus: {FIELD} {moved} "
                         f"({n} of {non_null} finalists under mapper-v2; never human-reviewed)",
                         why, basis))
    return out


def contested_doc(splits: Mapping[int, tuple], texts: Mapping[int, object],
                  reference: Mapping[int, dict], per_candidate: Mapping[int, Mapping[str, object]],
                  holdings: Mapping[int, Mapping[str, str]] | None = None) -> dict:
    """A contested-style document for make_reference_review.build_pages: one entry per case
    the finalists could not agree 4-of-5 on, contested on who_was_letting only.

    `who_was_letting` is not quote-gated, so no candidate was ever asked to point at
    language for it and there is no quote evidence to offer. What the candidates did write
    is a holding summary, and that is what the page shows instead."""
    holdings = holdings or {}
    contested = []
    for cid in sorted(splits):
        _value, _n, non_null = splits[cid]
        values = dict(per_candidate.get(cid) or {})
        top = sorted(Counter(v for v in values.values() if v is not None).items(),
                     key=lambda kv: (-kv[1], str(kv[0])))
        t = texts.get(cid)
        seen, evidence = set(), []
        for cand in CANDIDATES:                      # at most two, distinct, in pinned order
            h = (holdings.get(cid) or {}).get(cand)
            if h and h not in seen and len(evidence) < 2:
                seen.add(h)
                evidence.append({"candidate": cand, "quote": "", "holding_summary": h})
        contested.append({
            "case_id": int(cid),
            "name": getattr(t, "name", ""), "cite": getattr(t, "cite", ""),
            "court": getattr(t, "court", ""), "jurisdiction": getattr(t, "jurisdiction", ""),
            "year": getattr(t, "year", None),
            "contested_fields": [FIELD],
            "reference": {"relevant": (reference.get(cid) or {}).get("relevant"),
                          "polarity": (reference.get(cid) or {}).get("polarity"),
                          FIELD: (reference.get(cid) or {}).get(FIELD)},
            "majority": {FIELD: {"majority_value": top[0][0] if top else None,
                                 "majority_n": top[0][1] if top else 0,
                                 "non_null_n": non_null,
                                 "reference_value": (reference.get(cid) or {}).get(FIELD)}},
            "candidates": {c: {"record_present": c in values,
                               FIELD: {"model_value": values.get(c), "gated_value": values.get(c),
                                       "gate_nulled": False}}
                           for c in CANDIDATES},
            "evidence_for_majority": {FIELD: evidence},
            "evidence_for_reference": {FIELD: []},
        })
    return {"generated_from": {"kit": DEFAULT_KIT, "cache": CACHE, "manifest": MANIFEST,
                               "candidates": list(CANDIDATES),
                               "never_reviewed_from": UNREVIEWED},
            "method": (f"Decision D3: the {FIELD} reference for kit cases never reviewed on that "
                       f"field is the value at least {CONSENSUS_K} of the {len(CANDIDATES)} "
                       f"finalists returned (post-gate, under {PROMPT_VERSION}). These are the "
                       f"cases where they did not. Cases the user already adjudicated on {FIELD}, "
                       f"and cases the ledger now records as irrelevant, are excluded (R8). No "
                       f"quote evidence is offered because {FIELD} is not quote-gated; each "
                       f"candidate's holding summary is shown instead."),
            "counts": {"splits": len(contested)},
            "page": PAGE,
            "contested": contested}


def _published(view) -> dict:
    """The three published counts D3 must not disturb. `who_was_letting` enters only the
    third, so the first two are a control and the third is the number to explain."""
    t = {"relevant": view.counts(relevant=True).total,
         "favorable": view.counts(relevant=True, polarity="favorable").total,
         "favorable_householder": view.counts(relevant=True, polarity="favorable",
                                              who_was_letting="householder").total}
    return {k: (v.human_reviewed, v.machine_only) for k, v in t.items()}


def _projected(view, patches) -> LedgerView:
    """The view these patches would produce, without writing anything - so a dry run can
    show the count deltas it is proposing rather than three identical rows."""
    state = copy.deepcopy(view.state)
    for p in patches:
        apply_patch(state, p, judged=tuple(view.domain.judged_fields), cascade=p.cascade)
    return LedgerView(view.name, view.as_of, state, list(view.patches) + list(patches), view.domain)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kit", default=DEFAULT_KIT)
    ap.add_argument("--out", default=DEFAULT_CONTESTED)
    ap.add_argument("--out-stem", default=DEFAULT_STEM)
    ap.add_argument("--dry-run", action="store_true",
                    help="count and validate only; writes neither the ledger nor the page")
    a = ap.parse_args()

    mr = _tool("measure_reader")
    mrr = _tool("make_reference_review")
    dom = load_domain()
    cb = load_codebook(dom, PROMPT_VERSION)
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("codebook_sha") and cb.sha != manifest["codebook_sha"]:
        sys.exit(f"{PROMPT_VERSION} has changed since measurement-v1 ({cb.sha[:12]} != "
                 f"{manifest['codebook_sha'][:12]}); the purchased cache no longer answers for it")
    reference_rows, batches, source = load_kit(ROOT / a.kit)
    cache = ResponseCache(ROOT / CACHE)

    v1 = json.loads((ROOT / UNREVIEWED).read_text(encoding="utf-8"))
    never_reviewed = {int(r["case_id"]) for r in v1["who_was_letting_unreviewed"]}
    led = open_ledger(domain=dom)
    before = _published(led.view())
    eligible, skipped_reviewed, skipped_irrelevant = partition(
        never_reviewed, led.view(), adjudicated_who(v1))
    print(f"{len(never_reviewed)} kit cases were never human-reviewed on {FIELD}\n"
          f"  {len(skipped_reviewed):>4} skipped: the user already decided them (R8)\n"
          f"  {len(skipped_irrelevant):>4} skipped: the ledger now records them irrelevant\n"
          f"  {len(eligible):>4} eligible for the consensus", flush=True)

    ids = set(eligible)
    per_candidate: dict[int, dict[str, object]] = {cid: {} for cid in ids}
    holdings: dict[int, dict[str, str]] = {cid: {} for cid in ids}
    for model_id in CANDIDATES:
        label = (manifest.get("pins") or {}).get(model_id)
        if not label:
            sys.exit(f"measurement-v1 manifest has no pin for {model_id}")
        pin = mr.pin_from_label(label, dom.reader.families)
        units = plan_batch_extraction(batches, cb.id, pin, Budget(), worker="reader").units
        recs = mr.records_from_cache(cb, pin, units, source, cache, cb.judged_fields)
        found = 0
        for r in recs:
            cid = int(r.get("case_id"))
            if cid in ids and r.get("extraction_status") != "missing":
                per_candidate[cid][model_id] = r.get(FIELD)
                if r.get("holding_summary"):
                    holdings[cid][model_id] = r["holding_summary"]
                found += 1
        print(f"  {model_id:<32} {found:>4} cached records over those cases", flush=True)

    agreed, splits = {}, {}
    for cid in sorted(ids):
        value, n, non_null = consensus(per_candidate[cid])
        (agreed if value is not None else splits)[cid] = (value, n, non_null)
    print(f"consensus ({CONSENSUS_K} of {len(CANDIDATES)}): {len(agreed)} agreed, "
          f"{len(splits)} split", flush=True)

    patches = patches_for(agreed, led.view().state.records)
    res = led.apply(patches, note="reference v2 who-was-letting consensus", dry_run=a.dry_run)
    print(f"{len(res.applied)} patches applied, {len(res.skipped)} already present; "
          f"replay_ok={res.replay_ok}{' (dry run)' if a.dry_run else ''}", flush=True)
    after = _published(_projected(led.view(), res.applied) if a.dry_run else led.view())
    for key in before:
        mark = "" if before[key] == after[key] else "   <- CHANGED"
        print(f"  {key:<22} {before[key]} -> {after[key]}{mark}", flush=True)

    if a.dry_run:
        print("dry run: neither the ledger nor the review page was written", flush=True)
        return 0

    split_ids = sorted(splits)
    texts = {t.case_id: t for t in source.fetch(split_ids)} if split_ids else {}
    doc = contested_doc(splits, texts, {int(r["case_id"]): r for r in reference_rows},
                        per_candidate, holdings)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    html, md, _n = mrr.build_pages(out, ROOT / a.out_stem)
    print(f"wrote {out.as_posix()}, {html.as_posix()} and {md.as_posix()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
