"""Derive the patch log from the artifacts the old scripts consumed, in the
order they applied them. One-time; every why starts with 'bootstrap:'."""
from __future__ import annotations
import json, sys
from pathlib import Path
from corpus_engine.ledger.fold import State, apply_patch
from corpus_engine.ledger.types import Basis, Patch

CYCLES = [("cycle-001", "cycle-001-shard-02"), ("cycle-002", "cycle-002-shard-01"),
          ("cycle-003", "cycle-003-shard-01")]
SLICE_OF_LIFE = {"147 A.3d 947", "154 A.3d 408", "176 A.3d 396", "164 A.3d 633"}
SLICE_FLAG = ("abrogation-risk: Slice of Life v. Hamilton Twp., 207 A.3d 886 "
              "(Pa. 2019) — per human review note; verify via citator")
SHVEKH = 12315742


def _records(dirpath: Path) -> list[dict]:
    out = []
    for f in sorted(dirpath.glob("*.json")):
        out.extend(json.loads(f.read_text(encoding="utf-8")))
    return out


def _coerce(field: str, value):
    if field == "relevant":
        return value if isinstance(value, bool) else str(value).lower() == "true"
    return value


def _cycle_patches(root: Path, cycle: str, run: str, reviewer: str, state: State) -> list[Patch]:
    sys.path.insert(0, str(root / "pipeline"))
    from make_review import load_data  # noqa: E402
    data = load_data(run)
    decisions = json.loads((root / "runs" / run / "decisions-final.json").read_text(encoding="utf-8"))
    human = Basis(reviewer=reviewer)
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    reader = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id=run)
    remap_records = _records(root / "runs" / f"{cycle}-remap" / "verified")
    remap_ids = {r["case_id"] for r in remap_records}
    for r in _records(root / "runs" / run / "verified"):
        # remap replaces the original outright (apply_adjudications.py:67-71):
        # the shadowed original never enters the ledger, so it never holds a
        # position for the remap record to "replace in place" -- the remap
        # record is admitted fresh below and lands at the end, in remap order.
        if r["case_id"] in remap_ids:
            continue
        emit(Patch(r["case_id"], "admit", "", r, "bootstrap: verified extraction", reader, cycle=cycle))
    remap_basis = Basis(model="sonnet@claude-cli", prompt_version="mapper-v1", run_id=f"{cycle}-remap")
    for r in remap_records:
        emit(Patch(r["case_id"], "admit", "", r, "bootstrap: remap replaces original", remap_basis, cycle=cycle))

    def known(cid):
        return cid in state.records

    for i, e in enumerate(data["C"]):
        st = decisions.get(f"C-{i}") or {}
        if not known(e.get("case_id")) or not st.get("decision"):
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"), "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            f = e["field"]; value = _coerce(f, value)
            emit(Patch(e["case_id"], "set", f, value, "bootstrap: section C adjudication", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"{f} adjudicated -> {value} (disagreement resolved, human-confirmed)", "bootstrap: section C note", human))
            emit(Patch(e["case_id"], "set", "review.status", "human-adjudicated", "bootstrap: section C status", human))
    for i, e in enumerate(data["D"]):
        st = decisions.get(f"D-{i}") or {}
        if not known(e.get("case_id")) or not st.get("decision"):
            continue
        if st["decision"] == "other":
            emit(Patch(e["case_id"], "append", "review.flags", f"open-question:{e.get('field')}", "bootstrap: section D open question", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"user note: {st.get('note')}", "bootstrap: section D note", human))
            emit(Patch(e["case_id"], "set", "review.status", "pending-user-question", "bootstrap: section D status", human))
            continue
        value = {"accept-rec": e.get("recommendation"), "claude": e.get("claude"), "codex": e.get("codex")}.get(st["decision"])
        if value is not None and e.get("field"):
            f = e["field"]; value = _coerce(f, value)
            emit(Patch(e["case_id"], "set", f, value, "bootstrap: section D adjudication", human))
            emit(Patch(e["case_id"], "append", "review.notes", f"{f} adjudicated -> {value}", "bootstrap: section D note", human))
            emit(Patch(e["case_id"], "set", "review.status", "human-adjudicated", "bootstrap: section D status", human))
    for i, e in enumerate(data["A"]):
        st = decisions.get(f"A-{i}") or {}
        if not known(e.get("case_id")):
            continue
        if st.get("decision") == "accept":
            emit(Patch(e["case_id"], "set", "review.status", "human-accepted", "bootstrap: section A accept", human))
        elif st.get("decision") == "needs-work":
            emit(Patch(e["case_id"], "set", "review.status", "needs-work", "bootstrap: section A needs-work", human))
        if st.get("note"):
            emit(Patch(e["case_id"], "append", "review.notes", f"user note: {st['note']}", "bootstrap: section A note", human))
        if st.get("citator"):
            emit(Patch(e["case_id"], "append", "review.flags", "citator-checked", "bootstrap: section A citator", human))
    for i, e in enumerate(data["B"]):
        st = decisions.get(f"B-{i}") or {}
        if st.get("decision") == "mismatch" and known(e.get("case_id")):
            emit(Patch(e["case_id"], "drop_quote", "quotes", e["quote"], "bootstrap: section B mismatch", human))
            emit(Patch(e["case_id"], "append", "review.notes", "quote removed: human judged fuzzy match a real mismatch", "bootstrap: section B note", human))
    if known(SHVEKH) and state.cycles[SHVEKH] == cycle:
        emit(Patch(SHVEKH, "set", "who_was_letting", "unclear", "bootstrap: Shvekh correction", human))
        emit(Patch(SHVEKH, "append", "review.notes", "who_was_letting corrected householder->unclear per human review: family resided elsewhere; whole-home VRBO rental of non-primary house", "bootstrap: Shvekh note", human))
        emit(Patch(SHVEKH, "set", "review.status", "human-adjudicated", "bootstrap: Shvekh status", human))
    rule = Basis(rule_id="slice-of-life-abrogation-risk-v1")
    for cid in list(state.order):
        if state.cycles[cid] == cycle and (state.records[cid].get("cite") or "") in SLICE_OF_LIFE:
            emit(Patch(cid, "append", "review.flags", SLICE_FLAG, "bootstrap: Slice of Life risk flag", rule))
    # apply_adjudications.py wrote each cycle's file once, from the *then-current*
    # `relevant` value, right after this cycle's own admits/C/D/A/B/Shvekh/Slice-of-Life
    # patches (apply_adjudications.py:159-162: `relevant = [r for r in ledger.values()
    # if r.get("relevant")]`, computed after those patches, before any later cross-cycle
    # hygiene pass). `in_file` is set only at "admit" time in fold.py, so a C/D
    # adjudication that changes `relevant` (a disagreement over relevance itself) needs
    # an explicit re-sync here to match that one-time snapshot. A later cross-cycle
    # patch (relevance re-check, run_id="relevance-recheck") mutates an
    # already-on-disk line without removing it (relevance_recheck.py: "leave the counts
    # but stay in the file for audit") -- those never re-close this cycle's admission
    # set, so they must not go through this loop; it only runs once, here, at the end
    # of this cycle's own build.
    for cid in list(state.order):
        if state.cycles[cid] != cycle:
            continue
        want = bool(state.records[cid].get("relevant"))
        if want != state.in_file.get(cid, False):
            # An admit asserts where the record came from; keep the same origin
            # basis this cid's most recent real admit used in this cycle (the
            # human's contribution already lives in the adjacent `set relevant`
            # patch). `admit` never checks can_judge, so nothing else changes.
            origin = remap_basis if cid in remap_ids else reader
            emit(Patch(cid, "admit", "", state.records[cid],
                       "bootstrap: cycle build closes with current relevant value", origin, cycle=cycle))
    return ps


def _file_order(state: State) -> list[int]:
    """Records as they sit in the three files: per cycle, in_file only, sorted by year (stable)."""
    out = []
    for cycle, _ in CYCLES:
        ids = [c for c in state.order if state.cycles[c] == cycle and state.in_file[c]]
        out.extend(sorted(ids, key=lambda c: state.records[c].get("year") or 0))
    return out


def _polarity_patches(root: Path, reviewer: str, state: State, *, why_prefix: str = "bootstrap:") -> list[Patch]:
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    pr = root / "runs" / "polarity-review"
    dec = json.loads((pr / "decisions-final.json").read_text(encoding="utf-8"))
    queue = json.loads((pr / "review-queue.json").read_text(encoding="utf-8"))["disagreements"]
    decisions = {}
    for i, e in enumerate(queue):
        st = dec.get(f"C-{i}") or {}
        d = st.get("decision")
        if not d:
            continue
        value = {"accept-rec": e["recommendation"], "claude": "favorable", "codex": e["recommendation"]}.get(d)
        if d == "other":
            value = None
        decisions[e["case_id"]] = (value, st.get("note"), e["recommendation"])
    hb = Basis(reviewer=reviewer, run_id="polarity-review")
    for cid in _file_order(state):
        if cid not in decisions:
            continue
        value, note, rec = decisions[cid]
        r = state.records[cid]
        if value and value != r.get("polarity"):
            emit(Patch(cid, "append", "review.notes", f"polarity {r.get('polarity')} -> {value} (polarity re-review 2026-09-01, owner-right-to-let definition; reader rec {rec})", f"{why_prefix} polarity re-review note", hb))
            emit(Patch(cid, "set", "polarity", value, f"{why_prefix} polarity re-review", hb))
        elif value:
            emit(Patch(cid, "append", "review.notes", "polarity re-review: favorable confirmed by human", f"{why_prefix} polarity re-review confirmed", hb))
        else:
            emit(Patch(cid, "append", "review.flags", "polarity-open-question", f"{why_prefix} polarity open question", hb))
        if note:
            emit(Patch(cid, "append", "review.notes", f"user note: {note}", f"{why_prefix} polarity re-review user note", hb))
        emit(Patch(cid, "set", "review.status", "human-adjudicated", f"{why_prefix} polarity re-review status", hb))
    return ps


def _relevance_patches(root: Path, reviewer: str, state: State, *, why_prefix: str = "bootstrap:") -> list[Patch]:
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    verdicts = {int(k): v for k, v in json.loads((root / "runs" / "relevance-recheck" / "verdicts.json").read_text(encoding="utf-8")).items()}
    rb = Basis(reviewer=reviewer, run_id="relevance-recheck")
    for cid in _file_order(state):
        v = verdicts.get(cid)
        if v is None:
            continue
        if v.get("relevant") is False:
            emit(Patch(cid, "set", "relevant", False, f"{why_prefix} relevance re-check", rb))
            emit(Patch(cid, "append", "review.notes", f"relevance re-check 2026-09-01 -> irrelevant (user flag + reader): {v.get('justification')}", f"{why_prefix} relevance re-check note", rb))
        else:
            emit(Patch(cid, "append", "review.notes", f"relevance re-check 2026-09-01 -> relevant confirmed: {v.get('justification')}", f"{why_prefix} relevance re-check note", rb))
        emit(Patch(cid, "set", "review.status", "human-adjudicated", f"{why_prefix} relevance re-check status", rb))
    return ps


def _hygiene_patches(root: Path, reviewer: str, state: State) -> list[Patch]:
    return (_polarity_patches(root, reviewer, state) +
            _relevance_patches(root, reviewer, state))


# Two records were corrected by hand in commit 2ca53b9 ("Resolve final two
# adjudications: Hancock v. Rand -> mixed; Hardin v. State kept (mixed, low
# weight). Cycle 001 fully adjudicated; no open questions."), a direct edit of
# data/ledger/cycle-001.jsonl outside any script -- no run/decisions artifact
# records why. See tests/golden/README.md "Unexplained drift (bootstrap)" for
# the full before/after diff for both records.
DRIFT_WHY = "bootstrap: unexplained drift, see tests/golden/README.md"


def _drift_patches(reviewer: str, state: State) -> list[Patch]:
    ps: list[Patch] = []

    def emit(p: Patch):
        apply_patch(state, p, cascade=False)
        ps.append(p)

    human = Basis(reviewer=reviewer)
    # 24 N.Y. Sup. Ct. 279 -- "Hancock v. Rand" per the commit message
    emit(Patch(4453395, "set", "polarity", "mixed", DRIFT_WHY, human))
    emit(Patch(4453395, "set", "review.flags", [], DRIFT_WHY, human))
    emit(Patch(4453395, "append", "review.notes",
               "polarity resolved -> mixed per user: value is classificatory (fixed price/duration does not alter guest status), not rights-protective",
               DRIFT_WHY, human))
    # 47 Tex. Crim. 493 -- "Hardin v. State" per the commit message
    emit(Patch(4539230, "set", "relevance_score", 0.35, DRIFT_WHY, human))
    emit(Patch(4539230, "set", "review.status", "human-adjudicated", DRIFT_WHY, human))
    emit(Patch(4539230, "set", "review.flags", [], DRIFT_WHY, human))
    emit(Patch(4539230, "append", "review.notes",
               "relevance resolved -> keep (mixed, low weight) per user: incidental civil holding distinguishing householder room-letting from boarding-house business (Cady/Howth line)",
               DRIFT_WHY, human))
    return ps


def patches_from_artifacts(root: Path, *, reviewer: str = "mmaldo2") -> list[Patch]:
    state = State()
    ps: list[Patch] = []
    for cycle, run in CYCLES:
        ps.extend(_cycle_patches(root, cycle, run, reviewer, state))
        if cycle == "cycle-001":
            ps.extend(_drift_patches(reviewer, state))
    ps.extend(_hygiene_patches(root, reviewer, state))
    return ps
