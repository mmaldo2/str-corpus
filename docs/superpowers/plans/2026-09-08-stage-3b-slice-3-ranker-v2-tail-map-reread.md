# Stage 3B Slice 3 — Reviewer Protection, Ranker v2, the Cycle-004 Tail Map, the Cycles 1–3 Re-read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ledger refuse to let a machine read overwrite a human decision, retrain and re-test the candidate ranker on a second frozen held-out slice built only from human labels, spend a fixed case budget on the unread cycle-004 tail in global rank order, re-read the 693 relevant records of cycles 1–3 under mapper-v3 so they carry the same fields as cycle 004, and run the review rounds those produce.

**Architecture:** Four independent pieces stacked in the spec's order (D1). `corpus_engine/ledger/fold.py` gains per-field provenance and a rejection rule, exposed through `LedgerView.conflicts()` / `LedgerView.provenance()`; nothing else in the ledger changes and the real patch log still replays byte-for-byte. `corpus_engine/ranker/` gains a second label builder (human decisions only) and a three-way evaluation, driven by the existing two thin CLIs. `corpus_engine/mapper/` gains a budgeted, globally-ordered walk beside the existing per-cell walk — a second method on `MapRunner`, not a rewrite of the first. A new `tools/reread_records.py` plans and reads the cycles 1–3 records through the same `MapRunner`, and `tools/admit_map.py --reread` turns that map into fill / replace / conflict decisions instead of fresh admissions. The review round gains one section, G, placed first.

**Tech Stack:** Python 3.11 (`.venv/Scripts/python`), SQLite, numpy + scikit-learn (ranker), subprocess (Claude CLI, Codex CLI), rapidfuzz, PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-stage-3b-slice-3-ranker-v2-tail-map-reread-design.md` (binding; D1–D10 are its decisions). Authority on conflicts: that spec, then the slice-2 spec (`docs/superpowers/specs/2026-09-06-stage-3b-slice-2-map-runner-design.md`), ADR-0007, ADR-0004, `CONTEXT.md`.

## Global Constraints

Spec section 11 verbatim, plus this slice's operational rules. Every task's requirements implicitly include this section.

- LF line endings, UTF-8 without BOM, one trailing newline on every file written. Write bytes explicitly (`path.write_bytes(text.encode("utf-8"))`); never PowerShell `Set-Content`.
- Never commit `.env`, `data/db/`, `data/raw/`, `data/reader/cache/`, `runs/*/batches`, `runs/*/extractions`.
- No paid request in this slice: Opus on the subscription, Codex on its subscription; OpenRouter is untouched. No task constructs an `OpenRouterProvider`.
- `kit-v1`, `kit-v2`, both measurement manifests (`data/reader/measurement-v1/manifest.json`, `data/reader/measurement-v2/manifest.json`) and **held-out v1** (`data/eval/ranker-heldout-v1.jsonl`) are never edited.
- Published counts come only from `open_ledger().view().counts()` — never from a file scan, never blended across tiers (`TierCount.__int__` and `__add__` raise).
- No model-assisted decision enters the human tier without the user's confirmation and the assisted-by note (`--assisted-by`).
- **No live reader or ranker run from any task except the live-run tasks.** Tasks 1–7 use `ScriptedProvider`, fixtures and the tiny fixture store only. If a task's test would invoke `claude`, `codex`, `httpx`, or would train against `data/db/corpus.db`, the test is wrong. **Every live run is controller-gated:** an agent executing this plan stops and reports before each one and does not start it on its own authority.
- The reader pin is fixed and not re-decided here: `claude-cli/claude-opus-5`, effort `low`, batch size 18, codebook `mapper-v3` (`f92016681314`), read timeout 1500 s, `max_tokens` 64000. Checker: `codex-cli` / `gpt-5.6-terra`. No Gemini screen (D5): `--screen` is never passed.
- Python 3.11; tests are `.venv/Scripts/python -m pytest -q` from `C:\Users\marcu\Desktop\Str-corpus`. Baseline **576 passed, 1 xfailed**. A task is done when the whole suite is green, not just its own file.
- Branch `refactor/stage-3b-slice-3`, cut from `main` at `0e0552a`. Commit after every task with the trailer block:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3
  ```

---

## Facts the plan is built on (verified read-only, 2026-09-08)

Every number here came from `open_ledger().view()` or from reading a tracked file. None came from `data/db/corpus.db`.

- **The log.** `data/ledger/patches.jsonl` holds 42,984 patches: 12,963 `admit`, 24,462 `set`, 5,545 `append`, 14 `drop_quote`. 12,907 distinct cases; cycles: `cycle-001` 712, `cycle-002` 2,683, `cycle-003` 2,672, `cycle-004` 6,840.
- **Bases.** Every `admit` patch carries a reader basis (12,963 of 12,963). `set` on a judged field: 16,549 reader, 1,432 human, 14 rule. All 14 rule `set`s are retractions to `None` or the v3 vocabulary remap (`rule_id` `retraction-cascade-v1` ×12, `vocab-v3-cleanup` ×2). All 14 `drop_quote`s carry a reviewer basis.
- **The overwrite that D2 forbids has never happened as a `set`.** No reader-basis `set` on a judged field ever lands on a field a reviewer had already decided.
- **But 56 cases were re-admitted**, and 55 of them had a reviewer `set` between the two `admit` patches. The second admit body re-states `relevant` (55 cases), `polarity` (54) and `characterization` (52) on fields that by then carried human provenance — **and in every one of those 161 writes the body's value equals the reviewer's value.** No judged field was ever dropped by a re-admit. This is why T1's rule treats a value-identical write as a silent no-op: without that, replay would add 161 conflicts and 55 `needs-review:` flags and the snapshot would not reproduce.
- **Re-read scope (D7).** 693 relevant records in cycles 001–003, every one admitted under `mapper-v1`; 141 of them are human-reviewed. Field state across those 693:

  | field | reader-set | reviewer-set | empty (reader) | empty (rule) | empty (never set) |
  |---|---|---|---|---|---|
  | `relevant` | 693 | 0 | 0 | 0 | 0 |
  | `polarity` | 612 | 64 | 15 | 2 | 0 |
  | `who_was_letting` | 650 | 43 | 0 | 0 | 0 |
  | `duration_of_occupancy` | 690 | 0 | 3 | 0 | 0 |
  | `characterization` | 545 | 44 | 104 | 0 | 0 |
  | `holding_summary` | 620 | 4 | 69 | 0 | 0 |
  | `under_thirty_days` | 0 | 0 | 0 | 0 | 693 |
  | `restriction_nature` | 0 | 0 | 0 | 0 | 693 |
  | `owner_freedom_characterization` | 0 | 0 | 0 | 0 | 693 |

  So the re-read has **2,079 guaranteed fills** (the three mapper-v3-only fields on every record), **191 further fills** where a value is currently empty, and **155 reviewer-held fields** it may disagree with and must card rather than change.
- **Held-out v2 candidates (D3), counted from the ledger's own `year`/`jurisdiction`:** 821 human-confirmed relevant positives, 295 reviewer-overturned negatives, 1,116 in all, spread over 92 `(era, jurisdiction, label)` strata covering **all ten jurisdictions** (Cal., Conn., D.C., La., Mass., N.J., N.Y., Ohio, Pa., Tex.). 8 strata hold a single member and are skipped; `ceil(25%)` of the rest is **≈304** rows. The tool's own numbers, computed from the store's `era_partition`/`jurisdiction` with duplicates dropped, are the ones that get pinned.
- **Held-out v1** is 1,533 rows over four jurisdictions, sha `d2d3dd74…`, pinned at `domain.yaml` `ranking.heldout_sha256`. Never edited; the trainer excludes it too.
- **Published counts today:** relevant 2,716 (821 human-reviewed / 1,895 machine-only), favorable 1,229, mixed 171, favorable householder 303. `tests/test_ledger_committed.py` pins all three.
- **The tail.** `runs/cycle-004-shard-01/` holds 1,845 batch files / 32,795 cases; the map read 380 batches / 6,840 cases across all 50 cells (`totals` in `map-manifest.json`), leaving **1,465 unread batches / ~26,400 cases** at mean `rank_score` 0.04–0.06. A batch file is `{batch_id, ranker_id, era_partition, jurisdiction, cases[]}`; a case is `{case_id, era_partition, jurisdiction, rank_score, signals[]}`.
- `runs/*/shard-manifest.json` is **not** gitignored (`.gitignore` covers only `runs/*/batches/` and `runs/*/extractions/`), so shard-02's is committable.
- `corpus_engine/reader/schema.py` defines `FLAG_PREFIX = "needs-review:"`. The ledger sits upstream of the reader and cannot import it, so T1 re-declares the constant and a test pins the two equal.

---

## File Structure

```
corpus_engine/ledger/
  fold.py          MOD  T1  per-field provenance, the rejection rule, conflicts, FLAG_PREFIX
  ledger.py        MOD  T1  LedgerView.conflicts() / .provenance()
corpus_engine/ranker/
  labels.py        MOD  T2  human_relevance_decisions, human_labelled_reads, check_heldout(pin=)
  evaluate.py      MOD  T3  ships() — D6 in one place
  classifier.py    MOD  T3  train(): heldout_pin, extra_rankers, overwrite guard
corpus_engine/store.py        MOD  T2  case_partitions(conn, case_ids)
corpus_engine/selector/packing.py  MOD  T4  restrict_ids on build_batches / pack_batches
corpus_engine/mapper/
  cells.py         MOD  T5  Cell.uncapped, build_budget_cells, global_batch_order
  runner.py        MOD  T5  RunnerCaps.case_budget, MapRunner.global_order, _run_budget, _finish
  admit.py         MOD  T6  reread_patches, RereadOutcome, REREAD_WHY
  queue.py         MOD  T7  section G, CONFLICT_KEYS, conflicts_from_view, QueueCard.conflict
  __init__.py      MOD  T5/T6/T7  export the new names
corpus_engine/domain.py       MOD  T2  RankingSpec.heldout_v2 / heldout_v2_sha256
domains/str-right-to-let/domain.yaml  MOD  T2 (v2 pin), T8 (classifier_version, if it ships)
pipeline/rank.py              MOD  T4  --from-run / --exclude-read, source provenance
tools/
  build_ranker_heldout.py  MOD  T2  main(argv), --out/--human-only/--fraction/--seed
  train_ranker.py          MOD  T3  --heldout v1|v2, --tag, --force, --report
  map_reader.py            MOD  T5  --case-budget
  reread_records.py        NEW  T6  --plan / read, uncapped cells, no yield stop
  admit_map.py             MOD  T6  --reread
  make_map_review.py       MOD  T7  section G on the page
  export_review_cards.py   MOD  T7  section G in the exports
  apply_map_review.py      MOD  T7  section-G decision semantics
tests/
  test_ledger_fold.py            MOD  T1
  test_ledger_committed.py       MOD  T1
  test_build_ranker_heldout.py   NEW  T2
  test_ranker_labels.py          MOD  T2
  test_ranker_classifier.py      MOD  T3
  test_train_ranker_tool.py      NEW  T3
  test_rank_cli.py               MOD  T4
  test_ranker_packing.py         MOD  T4
  test_mapper_cells.py           MOD  T5
  test_mapper_runner.py          MOD  T5
  test_map_reader_tool.py        MOD  T5
  test_reread_records.py         NEW  T6
  test_mapper_admit.py           MOD  T6
  test_mapper_queue.py           MOD  T7
  test_map_review_tools.py       MOD  T7
data/eval/ranker-heldout-v2.jsonl     generated + TRACKED (T8)
data/ranker/v2/{model.npz,manifest.json}   generated + TRACKED (T8)
runs/cycle-004-shard-02/shard-manifest.json, map-manifest.json   TRACKED (T8)
runs/cycles-001-003-reread/{case-ids.json,map-manifest.json,reread-conflicts.json,reread-admission.json}  TRACKED (T8)
reports/ranking-v2.md, reports/map-cycle-004-shard-02.md, reports/reread-cycles-001-003.md  (T8)
CONTEXT.md   MOD  T1 (Provenance, Conflict)
```

**Task order.** T1 first: T6 and T7 both depend on its provenance and conflict shapes. T2 → T3 is a chain (the slice, then the trainer that reads it). T4 depends on T3's shipped-or-not answer only at run time, not at build time. T5 is independent of T2–T4. T6 depends on T1 and on T5's `Cell.uncapped`. T7 depends on T1 and T6. T8 runs last and is the only task that spends anything.

---

### Task 1: Reviewer protection in the fold (spec section 3, D2)

A field a human has decided is never overwritten by a machine read. The fold tracks per-field
provenance, rejects the write, records the attempt, flags the record, and carries on — a
rejection is never an exception, because `Ledger.view()` replays the whole log on every call
and a raise would take the corpus down (spec section 9).

Two rules that the spec's prose leaves to the plan, both forced by the real log:

1. **A value-identical write is not an overwrite.** 161 writes in the log re-state a reviewer's
   own value from a later `admit` body. Rejecting them loudly would add 161 conflicts and 55
   `needs-review:` flags to records that changed in no way, and the byte-identical replay the
   spec demands would fail. They are no-ops: not applied, not recorded.
2. **Only a *reader* write is rejected.** The spec's section 1 says what the protection is for:
   human decisions must survive *later machine reads*. Every rule-basis `set` in the log is the
   consequence of a reviewer's own action (the retraction cascade after a reviewer's
   `drop_quote`; the v3 vocabulary ruling), and six of them null a field a reviewer had decided.
   Rejecting those would leave a judged value standing on a quote a human deleted — the opposite
   of evidence discipline. So the gate is `basis.model and not basis.reviewer`.

Provenance is **sticky at `human`**: once a human has decided a field, a rule that later
withdraws the value does not un-make the judgment, and the field keeps `human` provenance so a
re-read cannot silently re-fill it — it gets a conflict card instead (T6, T7).

**Files:**
- Modify: `corpus_engine/ledger/fold.py`, `corpus_engine/ledger/ledger.py`, `CONTEXT.md`
- Test: `tests/test_ledger_fold.py`, `tests/test_ledger_committed.py`

**Interfaces:**
- Consumes: `Basis`, `Patch` from `corpus_engine.ledger.types`; `State`, `apply_patch`, `REVIEW_DEFAULT`, `JUDGED_DEFAULT` as they stand.
- Produces (T6 and T7 consume exactly these):
  - `corpus_engine.ledger.fold.FLAG_PREFIX: str = "needs-review:"`
  - `corpus_engine.ledger.fold.PROVENANCE_KINDS: tuple = ("human", "reader", "rule")`
  - `corpus_engine.ledger.fold.provenance_kind(basis: Basis) -> str`
  - `corpus_engine.ledger.fold.is_reader_write(basis: Basis) -> bool`
  - `State.provenance: dict[int, dict[str, str]]` — `{case_id: {field: "human"|"reader"|"rule"}}`
  - `State.conflicts: dict[int, list[dict]]` — each entry exactly:
    `{"field": str, "attempted": Any, "standing": Any, "by": dict, "at": int, "op": "set"|"admit"}`
    (`by` is `Basis.to_json()`; `at` is the patch's `seq`)
  - `LedgerView.conflicts(case_id: int | None = None) -> dict[int, list[dict]]`
  - `LedgerView.provenance(case_id: int) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ledger_fold.py`:

```python
from corpus_engine.ledger.fold import FLAG_PREFIX, is_reader_write, provenance_kind

READER = Basis(model="claude-opus-5@claude-cli", prompt_version="mapper-v3:f92016681314",
               run_id="cycles-001-003-reread")
HUMAN = Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1")


def _admitted() -> State:
    s = State()
    apply_patch(s, Patch(5, "admit", "", REC, "v", Basis(model="m", prompt_version="mapper-v1",
                                                         run_id="cycle-001"), cycle="cycle-001"))
    return s


def test_the_fold_flag_prefix_is_the_readers_flag_prefix():
    """One spelling of the flag. The ledger cannot import the reader (it is upstream of it),
    so the constant is re-declared there and pinned equal here instead."""
    from corpus_engine.reader.schema import FLAG_PREFIX as READER_PREFIX
    assert FLAG_PREFIX == READER_PREFIX == "needs-review:"


def test_a_reader_set_never_overwrites_a_reviewer_value():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    assert s.provenance[5]["polarity"] == "human"
    old = apply_patch(s, Patch(5, "set", "polarity", "favorable", "re-read", READER, seq=99))
    assert old is UNSET                                     # nothing was replaced
    assert s.records[5]["polarity"] == "adverse"            # the human's value stands
    assert s.provenance[5]["polarity"] == "human"
    assert s.conflicts[5] == [{"field": "polarity", "attempted": "favorable",
                               "standing": "adverse", "by": READER.to_json(), "at": 99,
                               "op": "set"}]
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_a_reader_set_of_the_same_value_is_silent():
    """161 writes in the real log do exactly this. Nothing is overwritten, so nothing is
    reported - and the committed snapshot still reproduces."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "re-read", READER, seq=99))
    assert s.records[5]["polarity"] == "adverse"
    assert 5 not in s.conflicts
    assert s.records[5]["review"]["flags"] == []


def test_a_reader_retraction_to_none_is_rejected_on_a_reviewer_field():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "who_was_letting", "householder", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "who_was_letting", None, "re-read", READER, seq=101))
    assert s.records[5]["who_was_letting"] == "householder"
    assert s.conflicts[5][0]["attempted"] is None and s.conflicts[5][0]["at"] == 101
    assert s.records[5]["review"]["flags"] == ["needs-review:who_was_letting"]


def test_a_reader_set_replaces_a_reader_value_and_keeps_reader_provenance():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "mixed", "re-read", READER))
    assert s.records[5]["polarity"] == "mixed"
    assert s.provenance[5]["polarity"] == "reader" and 5 not in s.conflicts


def test_a_rule_retraction_applies_over_a_reviewer_value_but_the_field_stays_human():
    """The retraction cascade fires because a REVIEWER dropped the quote; refusing it would
    leave a judged value standing on evidence a human deleted. The provenance stays `human`
    so a later re-read cards the field rather than quietly re-filling it."""
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", None, "cascade",
                         Basis(rule_id="retraction-cascade-v1")))
    assert s.records[5]["polarity"] is None
    assert s.provenance[5]["polarity"] == "human" and 5 not in s.conflicts
    apply_patch(s, Patch(5, "set", "polarity", "favorable", "re-read", READER, seq=7))
    assert s.records[5]["polarity"] is None and s.conflicts[5][0]["standing"] is None


def test_a_reviewer_may_always_redecide():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    apply_patch(s, Patch(5, "set", "polarity", "mixed", "round 2", Basis(reviewer="mmaldo2")))
    assert s.records[5]["polarity"] == "mixed" and 5 not in s.conflicts


def test_a_re_admit_body_may_not_change_a_reviewer_decided_field():
    s = _admitted()
    apply_patch(s, Patch(5, "set", "polarity", "adverse", "round 1", HUMAN))
    body = {**REC, "polarity": "favorable", "characterization": "tenancy"}
    apply_patch(s, Patch(5, "admit", "", body, "re-read", READER, cycle="cycle-001", seq=42))
    assert s.records[5]["polarity"] == "adverse"            # the human's value survives
    assert s.records[5]["characterization"] == "tenancy"    # a reader field does not
    assert s.conflicts[5] == [{"field": "polarity", "attempted": "favorable",
                               "standing": "adverse", "by": READER.to_json(), "at": 42,
                               "op": "admit"}]
    assert s.records[5]["review"]["flags"] == ["needs-review:polarity"]


def test_provenance_and_reader_write_helpers():
    assert provenance_kind(HUMAN) == "human"
    assert provenance_kind(READER) == "reader"
    assert provenance_kind(Basis(rule_id="r")) == "rule"
    assert provenance_kind(Basis()) == "reader"             # an admit body with a bare basis
    assert is_reader_write(READER) is True
    assert is_reader_write(HUMAN) is False
    assert is_reader_write(Basis(rule_id="retraction-cascade-v1")) is False
    assert is_reader_write(Basis(reviewer="m", rule_id="r")) is False
```

Add to `tests/test_ledger_committed.py`:

```python
def test_the_protection_rule_rejects_nothing_in_the_committed_log(repo_root):
    """Spec section 3's claim, proved over the real 42,984-patch log: no machine read has ever
    overwritten a human decision, so the new rule changes no committed byte. The 161
    value-identical re-admit writes are no-ops and must not appear here."""
    v = open_ledger(domain=load_domain()).view()
    assert v.conflicts() == {}
    assert v.state.provenance                                  # it is being tracked at all
    assert v.provenance(v.state.order[0])["relevant"] == "reader"


def test_the_protection_rule_leaves_the_published_counts_untouched(repo_root):
    v = open_ledger(domain=load_domain()).view()
    assert v.counts().total.human_reviewed + v.counts().total.machine_only == 2716
    assert v.counts().total.human_reviewed == 821
    flagged = sum(1 for cid in v.state.order
                  for f in (v.state.records[cid].get("review") or {}).get("flags") or ()
                  if f.startswith("needs-review:"))
    assert flagged == 1035        # replace with the number the first green run prints
```

For the last assertion: run the suite once, read the number the failure reports, and pin it.
It is the count of `needs-review:` flags **already in the committed log** — the point of the
assertion is that the rule adds none.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_ledger_fold.py tests/test_ledger_committed.py`
Expected: FAIL — `ImportError: cannot import name 'FLAG_PREFIX'` / `AttributeError: 'State' object has no attribute 'provenance'`.

- [ ] **Step 3: Write the implementation — `corpus_engine/ledger/fold.py`**

Add the constants and helpers below `REVIEW_DEFAULT`:

```python
# The flag a rejected write leaves on the record. It MUST equal
# `corpus_engine.reader.schema.FLAG_PREFIX`; the ledger is upstream of the reader and cannot
# import it, so the two are pinned equal by a test instead of by an import.
FLAG_PREFIX = "needs-review:"
PROVENANCE_KINDS = ("human", "reader", "rule")


def provenance_kind(basis) -> str:
    """The provenance a patch writes: human | reader | rule.

    `Basis.kind()` has a fourth answer, "none", for a bare basis. A judged value can only
    reach the fold under a basis that can judge (`MissingBasis`), so a bare basis here is
    either an admit body or a retraction to None - both records of a read, and "reader" is
    the honest name for them."""
    kind = basis.kind()
    return kind if kind in PROVENANCE_KINDS else "reader"


def is_reader_write(basis) -> bool:
    """Whether this patch is a machine read speaking on its own authority (D2).

    A reviewer patch is not. Neither is a rule patch: every rule-basis `set` in the log is the
    CONSEQUENCE of a reviewer's own decision - `retraction-cascade-v1` after a reviewer's
    `drop_quote`, `vocab-v3-cleanup` after the v3 vocabulary ruling - and six of them null a
    field a reviewer had decided. Rejecting those would leave a judged value standing on a
    quote a human deleted, which is the opposite of what the protection is for: spec section 1
    protects human decisions from LATER MACHINE READS."""
    return bool(basis.model) and not basis.reviewer
```

Add the two side maps to `State` (beside `cycles`, `in_file` and `prompts`, and for the same
reason: a key on the record itself would change every rendered line and break the snapshot):

```python
    # Per-field provenance, `{case_id: {field: kind}}` (D2). Written by every applied `set` on
    # a judged field and by every judged field an `admit` body carries. STICKY AT "human": once
    # a human has decided a field, a rule that later withdraws the value has not un-made the
    # judgment, and a field that quietly reverted to rule provenance would be silently
    # re-fillable by the next machine read.
    provenance: dict[int, dict[str, str]] = field(default_factory=dict)
    # Writes the rule refused, `{case_id: [entry, ...]}`. An entry is
    # {"field", "attempted", "standing", "by", "at", "op"}. A rejection never raises: `view()`
    # replays the whole log on every call and a raise would take the corpus down (spec §9).
    conflicts: dict[int, list[dict]] = field(default_factory=dict)
```

Add the two write helpers above `apply_patch`:

```python
def _record_provenance(state: "State", case_id: int, field_name: str, basis) -> None:
    """See `State.provenance` for the stickiness rule."""
    fields = state.provenance.setdefault(case_id, {})
    if fields.get(field_name) == "human":
        return
    fields[field_name] = provenance_kind(basis)


def _may_write(state: "State", case_id: int, field_name: str, value, basis, *, seq: int,
               op: str, standing, target: dict) -> bool:
    """Whether `field_name` may take `value` (D2), recording the refusal when it may not.

    A write of the SAME value is not an overwrite: it changes nothing, so it is neither
    applied nor reported. That is what keeps the 161 value-identical re-admit writes in the
    committed log silent, and it is what makes a fresh replay reproduce the four cycle files
    byte for byte. `target` is the record the flag goes on - on a re-admit that is the NEW
    record, not the one being replaced."""
    if state.provenance.get(case_id, {}).get(field_name) != "human":
        return True
    if not is_reader_write(basis):
        return True
    if standing == value:
        return False
    state.conflicts.setdefault(case_id, []).append(
        {"field": field_name, "attempted": value, "standing": standing,
         "by": basis.to_json(), "at": int(seq), "op": op})
    review = target.setdefault("review", copy.deepcopy(REVIEW_DEFAULT))
    flag = f"{FLAG_PREFIX}{field_name}"
    if flag not in review.setdefault("flags", []):
        review["flags"].append(flag)
    return False
```

In `apply_patch`'s `admit` branch, the existing-record path becomes:

```python
        if p.case_id in state.records:
            if state.cycles[p.case_id] != p.cycle:
                raise DuplicateRecord(f"{p.case_id} already admitted in {state.cycles[p.case_id]}")
            old = state.records[p.case_id]
            # A re-admit REPLACES the record, so its body is a write of every judged field it
            # names. D2 applies to those writes exactly as it applies to a `set`.
            for f in judged:
                if f in rec and not _may_write(state, p.case_id, f, rec[f], p.basis,
                                               seq=p.seq, op="admit", standing=old.get(f),
                                               target=rec):
                    rec[f] = old.get(f)
            state.records[p.case_id] = rec
            state.in_file[p.case_id] = bool(rec.get("relevant"))
            for f in judged:
                if f in rec:
                    _record_provenance(state, p.case_id, f, p.basis)
            _record_admitting_prompt(state, p.case_id, p.basis, admit=True)
            return old
        state.records[p.case_id] = rec
        state.order.append(p.case_id)
        state.cycles[p.case_id] = p.cycle
        state.in_file[p.case_id] = bool(rec.get("relevant"))
        for f in judged:
            if f in rec:
                _record_provenance(state, p.case_id, f, p.basis)
        _record_admitting_prompt(state, p.case_id, p.basis, admit=True)
        return UNSET
```

And in the `set` branch, between the `MissingBasis` check and `_record_admitting_prompt`:

```python
        if p.field in judged:
            if not _may_write(state, p.case_id, p.field, p.new, p.basis, seq=p.seq, op="set",
                              standing=rec.get(p.field), target=rec):
                return UNSET               # the value stands; the attempt is on the record
            _record_admitting_prompt(state, p.case_id, p.basis)
            _record_provenance(state, p.case_id, p.field, p.basis)
```

(The `drop_quote` cascade still nulls a supported field directly and is deliberately left
alone: the patch that triggers it carries a reviewer basis in all 14 cases in the log, and
provenance is sticky, so a cascaded null over a human field keeps `human` provenance.)

- [ ] **Step 4: Write the implementation — `corpus_engine/ledger/ledger.py`**

Add to `LedgerView`, beside `reviewed()`:

```python
    def conflicts(self, case_id: int | None = None) -> dict[int, list[dict]]:
        """Every write the fold refused because a human had already decided the field (D2).

        `{case_id: [{"field", "attempted", "standing", "by", "at", "op"}, ...]}`. Copies, not
        the fold's own lists: the queue reads this and must not be able to edit the state."""
        rows = self.state.conflicts
        if case_id is not None:
            return {case_id: [dict(c) for c in rows.get(case_id, ())]} if case_id in rows else {}
        return {cid: [dict(c) for c in entries] for cid, entries in rows.items()}

    def provenance(self, case_id: int) -> dict[str, str]:
        """`{field: "human"|"reader"|"rule"}` for this record. Empty for a case with no
        judged field ever written - never a KeyError, because the re-read asks about every
        record it re-reads and a missing entry means "nobody has decided this field"."""
        return dict(self.state.provenance.get(case_id, {}))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_ledger_fold.py tests/test_ledger_committed.py tests/test_ledger_apply.py tests/test_ledger_bootstrap.py`
Expected: PASS. Then the whole suite: `.venv/Scripts/python -m pytest -q` — expected 576+ passed, 1 xfailed.

If `test_committed_log_renders_to_the_committed_snapshot` fails, the rule is rejecting
something the log expects to apply. Print the conflicts and read them before changing the
test — the test is the specification here, not the code.

- [ ] **Step 6: CONTEXT.md**

Add to the **Ledger** part of the glossary, in the house style, immediately after **Review
tier**:

```markdown
**Provenance**:
Who decided a field on a record: human, reader, or rule. Tracked per
field by the fold and sticky at human - a rule that later withdraws the
value does not un-make the judgment.
_Avoid_: source, origin

**Conflict**:
A machine read that disagrees with a human decision. Never applied: the
human value stands, the attempt is recorded, and the record is flagged so
the disagreement reaches a review card.
_Avoid_: mismatch, error
```

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/ledger/fold.py corpus_engine/ledger/ledger.py tests/test_ledger_fold.py tests/test_ledger_committed.py CONTEXT.md
git commit -m "ledger: a reader write never overwrites a human decision (D2)

Per-field provenance on State, sticky at human; a reader-basis set or
re-admit body that would change a human-decided field is rejected, the
attempt recorded in State.conflicts and the record flagged. A
value-identical write is a no-op, which is why the committed log still
replays byte-for-byte.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 2: Held-out slice v2 — human labels only (spec section 4, D3)

A second frozen evaluation slice built from decisions people actually made: positives are the
human-reviewed relevant records, negatives are the records a reviewer took out of the corpus.
No machine-only label enters it, so it measures the ranker against people rather than against
an earlier version of itself. Held-out v1 is not touched.

One consequence to write down rather than discover later: because **every** row of v2 is
human-decided, `evaluate_scores`'s "reviewed view" (`reviewed or label == 0`) is the whole
slice, so `ap_reviewed == ap_all` on v2 and D6's two-view test is arithmetically one view.
That is a fact about the slice, not a defect; T3's report says so out loud.

**Files:**
- Modify: `corpus_engine/ranker/labels.py`, `corpus_engine/store.py`, `corpus_engine/domain.py`, `domains/str-right-to-let/domain.yaml`, `tools/build_ranker_heldout.py`
- Test: `tests/test_build_ranker_heldout.py` (new), `tests/test_ranker_labels.py`

**Interfaces:**
- Consumes: `LedgerView.patches` / `.state` / `.reviewed()`; `Label`, `build_heldout`, `write_heldout`, `sha256_file` as they stand.
- Produces (T3 and T6 consume exactly these):
  - `corpus_engine.store.case_partitions(conn, case_ids) -> dict[int, tuple[str, str]]` — `{case_id: (era_partition, jurisdiction)}`, duplicates (`is_duplicate_of is not null`) omitted
  - `corpus_engine.ranker.labels.human_relevance_decisions(view) -> tuple[set[int], set[int]]` — `(confirmed_relevant, overturned_irrelevant)`
  - `corpus_engine.ranker.labels.human_labelled_reads(view, conn) -> list[Label]`
  - `corpus_engine.ranker.labels.check_heldout(domain, path, *, pin: str = "heldout_sha256") -> str`
  - `RankingSpec.heldout_v2: str`, `RankingSpec.heldout_v2_sha256: str | None`
  - `tools/build_ranker_heldout.py`: `build(argv) -> dict` and `main(argv=None) -> int`, flags `--out`, `--human-only`, `--fraction`, `--seed`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_ranker_heldout.py`:

```python
"""Guards on the held-out v2 builder (spec section 4, D3). Nothing here touches the live
ledger or the live store: a fake view supplies the decisions, the tiny fixture store supplies
the era/jurisdiction, and the output goes to tmp_path."""
import importlib.util
import json
from pathlib import Path

import pytest

from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.ranker.labels import (check_heldout, human_labelled_reads,
                                         human_relevance_decisions, load_heldout, sha256_file,
                                         write_heldout, Label)
from tests.helpers.ranker_fixture import make_ranker_db

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_ranker_heldout",
                                               ROOT / "tools" / "build_ranker_heldout.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

HUMAN = Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1")
READER = Basis(model="m@p", prompt_version="mapper-v3:abc", run_id="cycle-004-shard-01")


class _View:
    """The slice of LedgerView the builder actually uses."""

    def __init__(self, records, reviewed=(), patches=()):
        class S:
            pass
        self.state = S()
        self.state.order = list(records)
        self.state.in_file = {c: True for c in records}
        self.state.records = {c: {"relevant": r} for c, r in records.items()}
        self._rev, self.patches = set(reviewed), list(patches)

    def reviewed(self, cid):
        return cid in self._rev


def test_human_relevance_decisions_takes_only_human_decided_records():
    view = _View({1: True, 2: True, 3: False, 4: False},
                 reviewed=[1],
                 patches=[Patch(3, "set", "relevant", False, "overturn", HUMAN),
                          Patch(4, "set", "relevant", False, "reader", READER)])
    pos, neg = human_relevance_decisions(view)
    assert pos == {1}            # 2 is relevant but machine-only
    assert neg == {3}            # 4 was called irrelevant by a machine, not a person


def test_human_labelled_reads_weights_and_marks_both_classes_reviewed(tmp_path, fixture_db,
                                                                      repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    a, b = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 2")]
    view = _View({a: True, b: False}, reviewed=[a],
                 patches=[Patch(b, "set", "relevant", False, "overturn", HUMAN)])
    labs = {l.case_id: l for l in human_labelled_reads(view, conn)}
    assert labs[a].label == 1 and labs[a].weight == 3.0 and labs[a].reviewed is True
    assert labs[b].label == 0 and labs[b].weight == 1.0 and labs[b].reviewed is True
    assert labs[a].era and labs[a].jurisdiction


def test_the_builder_refuses_to_overwrite_and_refuses_the_v1_path(tmp_path):
    out = tmp_path / "v2.jsonl"
    write_heldout(out, [Label(1, 1, 3.0, True, "pre-1860", "N.Y.")])
    with pytest.raises(SystemExit) as exc:
        bh.main(["--out", str(out), "--human-only"])
    assert "is a new version, not an overwrite" in str(exc.value)
    with pytest.raises(SystemExit) as exc:
        bh.main(["--out", "data/eval/ranker-heldout-v1.jsonl", "--human-only"])
    assert "held-out v1 is never edited" in str(exc.value)


def test_check_heldout_reads_the_pin_it_is_given(tmp_path):
    p = tmp_path / "v2.jsonl"
    write_heldout(p, [Label(1, 1, 3.0, True, "pre-1860", "N.Y.")])

    class D:
        pass

    dom = D(); dom.ranking = D()
    dom.ranking.heldout_sha256 = "not-this-one"
    dom.ranking.heldout_v2_sha256 = sha256_file(p)
    assert check_heldout(dom, p, pin="heldout_v2_sha256") == dom.ranking.heldout_v2_sha256
    with pytest.raises(ValueError):
        check_heldout(dom, p)                       # the v1 pin, against the v2 file
    dom.ranking.heldout_v2_sha256 = None
    with pytest.raises(ValueError):
        check_heldout(dom, p, pin="heldout_v2_sha256")


def test_the_builder_writes_a_stratified_frozen_slice_and_reports_its_strata(tmp_path,
                                                                            fixture_db,
                                                                            repo_root, capsys,
                                                                            monkeypatch):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    ids = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 12")]
    records = {c: (i % 2 == 0) for i, c in enumerate(ids)}
    patches = [Patch(c, "set", "relevant", False, "overturn", HUMAN)
               for c, rel in records.items() if not rel]
    view = _View(records, reviewed=[c for c, rel in records.items() if rel], patches=patches)
    monkeypatch.setattr(bh, "open_ledger", lambda **kw: type("L", (), {"view": lambda s: view})())
    monkeypatch.setattr(bh.store, "connect", lambda *a, **kw: conn)
    out = tmp_path / "v2.jsonl"
    report = bh.main(["--out", str(out), "--human-only"])
    assert report == 0 and out.exists()
    rows = load_heldout(out)
    assert rows and all(l.reviewed for l in rows)
    assert out.read_bytes().endswith(b"\n") and b"\r" not in out.read_bytes()
    printed = capsys.readouterr().out
    assert "sha256:" in printed and "heldout_v2_sha256" in printed
```

Append to `tests/test_ranker_labels.py`:

```python
def test_case_partitions_drops_duplicates(tmp_path, fixture_db, repo_root):
    from corpus_engine.store import case_partitions
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    a, b = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 2")]
    conn.execute("UPDATE cases SET is_duplicate_of=? WHERE case_id=?", (a, b)); conn.commit()
    meta = case_partitions(conn, [a, b, 424242])
    assert a in meta and b not in meta and 424242 not in meta
    assert len(meta[a]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_build_ranker_heldout.py tests/test_ranker_labels.py`
Expected: FAIL — `ImportError: cannot import name 'human_relevance_decisions'`.

- [ ] **Step 3: Write `corpus_engine/store.case_partitions` and rewire `labelled_reads`**

Add to `corpus_engine/store.py`:

```python
def case_partitions(conn, case_ids) -> dict[int, tuple[str, str]]:
    """`{case_id: (era_partition, jurisdiction)}` for the live (non-duplicate) cases among
    `case_ids`, read in chunks of 500 so a 30,000-id list is one bounded query per chunk.

    One function, two callers on purpose: the two held-out slices must be stratified on
    exactly the same facts, and the re-read's batch planner must group cases into the same
    cells the map used."""
    ids = sorted({int(c) for c in case_ids})
    out: dict[int, tuple[str, str]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, era, jur, dup in conn.execute(
                f"SELECT case_id, era_partition, jurisdiction, is_duplicate_of "
                f"FROM cases WHERE case_id IN ({ph})", chunk):
            if dup is None:
                out[int(cid)] = (era, jur)
    return out
```

In `corpus_engine/ranker/labels.py` replace the inline meta query inside `labelled_reads`
with `meta = case_partitions(conn, wanted)` (import it at the top:
`from corpus_engine.store import case_partitions`). Behaviour is unchanged — same query, same
duplicate rule.

- [ ] **Step 4: Write the v2 label builders and the generalised pin check**

Add to `corpus_engine/ranker/labels.py`:

```python
def human_relevance_decisions(view) -> tuple[set[int], set[int]]:
    """(confirmed relevant, overturned to irrelevant) - the two label classes of held-out v2.

    D3: positives are records a human reviewed and that stand relevant; negatives are the
    records a reviewer took OUT of the corpus with a reviewer-basis `set relevant False`. A
    machine's `relevant: false` is not a negative here - it is exactly the kind of label the
    slice exists not to grade the ranker against."""
    overturned = {p.case_id for p in view.patches
                  if p.basis.reviewer and p.op == "set" and p.field == "relevant"
                  and p.new is False}
    pos: set[int] = set()
    neg: set[int] = set()
    for cid in view.state.order:
        if not view.state.in_file.get(cid):
            continue
        rec = view.state.records[cid]
        if rec.get("relevant"):
            if view.reviewed(cid):
                pos.add(cid)
        elif rec.get("relevant") is False and cid in overturned:
            neg.add(cid)
    return pos, neg


def human_labelled_reads(view, conn) -> list[Label]:
    """The D3 candidate pool: every human relevance decision, as a `Label`.

    `reviewed=True` on BOTH classes, because both are human decisions. One consequence worth
    knowing before reading the numbers: `evaluate_scores`'s reviewed view is
    `reviewed or label == 0`, so on this slice it is the whole slice and `ap_reviewed` equals
    `ap_all`. D6's two-view test is then arithmetically one view - a property of a slice made
    entirely of human labels, not a defect."""
    pos, neg = human_relevance_decisions(view)
    meta = case_partitions(conn, pos | neg)
    out = []
    for cid in sorted(pos | neg):
        if cid not in meta:
            continue
        era, jur = meta[cid]
        if cid in pos:
            out.append(Label(cid, 1, POS_WEIGHT_REVIEWED, True, era, jur))
        else:
            out.append(Label(cid, 0, NEG_WEIGHT, True, era, jur))
    return out
```

Replace `check_heldout` with:

```python
def check_heldout(domain, path: Path, *, pin: str = "heldout_sha256") -> str:
    """The frozen slice's sha, verified against the domain key `pin`.

    `pin` names WHICH slice is being checked (`heldout_sha256` for v1, `heldout_v2_sha256` for
    v2), so one function guards both and neither can be trained against unverified."""
    h = sha256_file(path)
    want = getattr(domain.ranking, pin, None)
    if not want:
        raise ValueError(f"domain.ranking.{pin} is not pinned; held-out file {path} is not frozen")
    if h != want:
        raise ValueError(f"held-out file {path} sha256 {h[:12]}… does not match domain.yaml "
                         f"{pin} {str(want)[:12]}…; never edit it, make a new version")
    return h
```

- [ ] **Step 5: Add the domain keys**

`corpus_engine/domain.py`, in `RankingSpec`, after `heldout_sha256`:

```python
    heldout_v2: str = ""
    heldout_v2_sha256: str | None = None
```

`domains/str-right-to-let/domain.yaml`, in the `ranking:` block after `heldout_sha256`:

```yaml
  # Held-out v2 (slice 3, D3): human decisions only - human-reviewed relevant positives and
  # reviewer-overturned negatives - stratified by (era, jurisdiction, label) at ceil(25%).
  # Covers all ten jurisdictions, unlike v1's four. Frozen; v1 is never edited.
  heldout_v2: data/eval/ranker-heldout-v2.jsonl
  heldout_v2_sha256: null                # pinned by tools/build_ranker_heldout.py (T8 step 2)
```

- [ ] **Step 6: Rewrite `tools/build_ranker_heldout.py` as a testable CLI**

```python
"""Freeze a ranker held-out slice (spec section 4). Refuses to overwrite an existing file.

  .venv\\Scripts\\python tools\\build_ranker_heldout.py                       # v1's rule
  .venv\\Scripts\\python tools\\build_ranker_heldout.py --human-only \\
      --out data\\eval\\ranker-heldout-v2.jsonl                               # D3's rule
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                          # noqa: E402
from corpus_engine.domain import load_domain                             # noqa: E402
from corpus_engine.ledger import open_ledger                             # noqa: E402
from corpus_engine.ranker.labels import (HELDOUT_SEED, build_heldout,    # noqa: E402
                                          human_labelled_reads, labelled_reads,
                                          read_extractions, sha256_file, write_heldout)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="build_ranker_heldout.py",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None,
                    help="the file to freeze (default: domain.ranking.heldout for the v1 rule, "
                         "domain.ranking.heldout_v2 with --human-only)")
    ap.add_argument("--human-only", action="store_true",
                    help="D3: build from human relevance decisions alone - human-reviewed "
                         "relevant positives and reviewer-overturned negatives. No "
                         "machine-only label enters the slice.")
    ap.add_argument("--fraction", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=HELDOUT_SEED)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    dom = load_domain()
    pin = "heldout_v2_sha256" if a.human_only else "heldout_sha256"
    default = dom.ranking.heldout_v2 if a.human_only else dom.ranking.heldout
    out = Path(a.out) if a.out else ROOT / default
    if not out.is_absolute():
        out = ROOT / out
    frozen_v1 = (ROOT / dom.ranking.heldout).resolve()
    if a.human_only and out.resolve() == frozen_v1:
        sys.exit(f"{out} is held-out v1, which is never edited (spec section 11); "
                 f"pass --out data/eval/ranker-heldout-v2.jsonl")
    if out.exists():
        sys.exit(f"{out} exists; a new slice is a new version, not an overwrite")
    conn = store.connect()
    view = open_ledger(domain=dom).view()
    if a.human_only:
        labels = human_labelled_reads(view, conn)
    else:
        labels = labelled_reads(view, read_extractions(store.paths().runs), conn)
    held = build_heldout(labels, fraction=a.fraction, seed=a.seed)
    write_heldout(out, held)
    pos, hpos = sum(l.label for l in labels), sum(l.label for l in held)
    print(f"candidates: {len(labels)} ({pos} pos / {len(labels) - pos} neg); "
          f"held-out: {len(held)} ({hpos} pos / {len(held) - hpos} neg)")
    strata: dict[tuple, int] = {}
    for l in labels:
        strata[(l.era, l.jurisdiction, l.label)] = strata.get((l.era, l.jurisdiction, l.label), 0) + 1
    taken: dict[tuple, int] = {}
    for l in held:
        taken[(l.era, l.jurisdiction, l.label)] = taken.get((l.era, l.jurisdiction, l.label), 0) + 1
    print(f"{len(strata)} strata, "
          f"{sum(1 for n in strata.values() if n < 2)} skipped for holding fewer than 2")
    for k in sorted(strata):
        print(f"  {k[0]:>10} {k[1]:>6} label={k[2]}: {taken.get(k, 0)} of {strata[k]}")
    print(f"jurisdictions covered: {', '.join(sorted({k[1] for k in taken}))}")
    print("sha256:", sha256_file(out))
    print(f"now set ranking.{pin} in domain.yaml to that value")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_build_ranker_heldout.py tests/test_ranker_labels.py tests/test_domain.py`
Expected: PASS. Then the whole suite.

- [ ] **Step 8: Commit**

```bash
git add corpus_engine/store.py corpus_engine/ranker/labels.py corpus_engine/domain.py domains/str-right-to-let/domain.yaml tools/build_ranker_heldout.py tests/test_build_ranker_heldout.py tests/test_ranker_labels.py
git commit -m "ranker: held-out v2 builder over human relevance decisions only (D3)

human_relevance_decisions / human_labelled_reads select human-reviewed
relevant positives and reviewer-overturned negatives; check_heldout takes
the domain pin to verify against; the builder gains --out/--human-only and
refuses both an overwrite and the v1 path.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 3: Trainer v2 and the ship rule (spec section 4, D6)

Train `classifier:v2` on the labelled reads minus **both** frozen slices, evaluate three
rankers on held-out v2 — classifier v2, the shipped classifier v1, and fusion — apply D6
exactly, and write the report. Same features, same weights (human-reviewed positives 3.0,
machine 1.0), same `C` grid as v1: nothing about the model changes, only what it is trained on
and what it is judged against.

D6 has no margin and no tie-break: `>` on `ap_all` **and** `>` on `ap_reviewed`. It lives in
one function so the tool and the report cannot disagree about it.

**Files:**
- Modify: `corpus_engine/ranker/evaluate.py`, `corpus_engine/ranker/classifier.py`, `tools/train_ranker.py`
- Test: `tests/test_ranker_classifier.py`, `tests/test_train_ranker_tool.py` (new)

**Interfaces:**
- Consumes: `check_heldout(domain, path, *, pin=...)`, `RankingSpec.heldout_v2` (T2); `ClassifierRanker`, `FusionRanker`, `evaluate_scores` as they stand.
- Produces (T8 consumes exactly these):
  - `corpus_engine.ranker.evaluate.ships(classifier: dict, fusion: dict) -> bool`
  - `corpus_engine.ranker.classifier.train(conn, domain, labels, heldout, *, version, out_dir, commit, layout=None, heldout_path=None, heldout_pin="heldout_sha256", extra_rankers=None, overwrite=False) -> dict` — `manifest["metrics"]` is `{"classifier": {...}, "fusion": {...}, **extra}` and `manifest["heldout"]` is `{"path", "sha256", "n", "pin"}`
  - `tools/train_ranker.py`: `build_parser()`, `split_labels(labels, held_v1, held_v2, *, evaluate_on)`, `write_report(path, *, metrics, tag, heldout, strata, shipped, commit, cv, train)`, `main(argv=None) -> int`; flags `--tag` (alias `--version`), `--heldout {v1,v2}`, `--report`, `--force`
  - `reports/ranking-v2.md`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ranker_classifier.py`:

```python
from corpus_engine.ranker.evaluate import ships
from corpus_engine.ranker.ports import NullRanker


def test_the_ship_rule_needs_both_views_and_gives_no_margin():
    """D6 verbatim: strictly greater on ap_all AND on ap_reviewed. A tie does not ship."""
    better = {"ap_all": 0.51, "ap_reviewed": 0.41}
    fusion = {"ap_all": 0.50, "ap_reviewed": 0.40}
    assert ships(better, fusion) is True
    assert ships({"ap_all": 0.50, "ap_reviewed": 0.41}, fusion) is False   # tie on ap_all
    assert ships({"ap_all": 0.51, "ap_reviewed": 0.40}, fusion) is False   # tie on ap_reviewed
    assert ships({"ap_all": 0.51, "ap_reviewed": 0.39}, fusion) is False   # worse on one view


def test_train_refuses_to_overwrite_a_shipped_model_directory(tmp_path, fixture_db, repo_root):
    conn, dom, train_set, held = _training_inputs(tmp_path, fixture_db, repo_root)
    out = tmp_path / "v9f"
    train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x")
    with pytest.raises(ValueError, match="already holds a trained model"):
        train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x")
    train(conn, dom, train_set, held, version="v9f", out_dir=out, commit="x", overwrite=True)


def test_train_records_extra_rankers_and_the_pin_it_verified(tmp_path, fixture_db, repo_root):
    conn, dom, train_set, held = _training_inputs(tmp_path, fixture_db, repo_root)
    heldout = tmp_path / "v2.jsonl"
    write_heldout(heldout, held)
    dom.ranking.heldout_v2_sha256 = sha256_file(heldout)
    man = train(conn, dom, train_set, held, version="v9g", out_dir=tmp_path / "v9g", commit="x",
                heldout_path=heldout, heldout_pin="heldout_v2_sha256",
                extra_rankers={"classifier:v1": NullRanker()})
    assert man["heldout"]["pin"] == "heldout_v2_sha256"
    assert set(man["metrics"]) == {"classifier", "fusion", "classifier:v1"}
    assert man["metrics"]["classifier:v1"]["n_all"] == len(held)
```

`_training_inputs(tmp_path, fixture_db, repo_root) -> (conn, domain, train_set, heldout)` is a
helper added at the top of that file by lifting the four setup lines out of the existing
`test_train_writes_a_model_and_a_manifest`, so both paths build their inputs once. `dom` must
be a mutable copy for the pin assignment: build it with
`dataclasses.replace(load_domain().ranking, heldout_v2_sha256=None)` folded back onto the
domain, or use the existing test's `types.SimpleNamespace` domain stub if that is what it
already does — match the file.

Create `tests/test_train_ranker_tool.py`:

```python
"""Guards on tools/train_ranker.py. Nothing here trains against the live store: the parser,
the two-slice exclusion and the report renderer are the units under test, and each is a pure
function over data the test supplies."""
import importlib.util
from pathlib import Path

from corpus_engine.ranker.labels import Label

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("train_ranker", ROOT / "tools" / "train_ranker.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)


def test_the_parser_carries_the_v2_flags():
    a = tr.build_parser().parse_args(["--heldout", "v2", "--tag", "v2"])
    assert a.heldout == "v2" and a.tag == "v2" and a.force is False
    assert tr.build_parser().parse_args(["--version", "v3"]).tag == "v3"   # the old spelling
    assert tr.build_parser().parse_args([]).heldout == "v1"


def test_the_training_set_excludes_both_frozen_slices():
    labels = [Label(i, i % 2, 1.0, False, "pre-1860", "N.Y.") for i in range(1, 11)]
    v1, v2 = labels[:2], labels[2:4]
    train_set, evaluated = tr.split_labels(labels, v1, v2, evaluate_on="v2")
    assert {l.case_id for l in train_set} == {5, 6, 7, 8, 9, 10}
    assert {l.case_id for l in evaluated} == {3, 4}
    train_set, evaluated = tr.split_labels(labels, v1, v2, evaluate_on="v1")
    assert {l.case_id for l in train_set} == {5, 6, 7, 8, 9, 10}
    assert {l.case_id for l in evaluated} == {1, 2}


def test_the_report_states_the_rule_the_numbers_and_the_outcome(tmp_path):
    metrics = {"classifier": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.71,
                              "ap_reviewed": 0.71, "p50_all": 0.9, "p200_all": 0.6,
                              "per_cell": {"pre-1860|N.Y.": {"n": 10, "ap": 0.5, "p50": 0.4}}},
               "classifier:v1": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.64,
                                 "ap_reviewed": 0.64, "p50_all": 0.8, "p200_all": 0.5,
                                 "per_cell": {}},
               "fusion": {"n_all": 300, "n_reviewed": 300, "ap_all": 0.40, "ap_reviewed": 0.40,
                          "p50_all": 0.6, "p200_all": 0.3, "per_cell": {}}}
    out = tmp_path / "ranking-v2.md"
    tr.write_report(out, metrics=metrics, tag="v2",
                    heldout={"path": "data/eval/x.jsonl", "sha256": "abcdef123456789",
                             "n": 300, "pin": "heldout_v2_sha256"},
                    strata={"pre-1860|N.Y.|1": 10}, shipped=True, commit="deadbeef",
                    cv={"cv_C": 0.3, "cv_ap": 0.8}, train={"n_pos": 5, "n_neg": 5})
    text = out.read_text(encoding="utf-8")
    assert "classifier:v2" in text and "fusion:v1" in text and "classifier:v1" in text
    assert "0.7100" in text and "0.4000" in text
    assert "SHIPS" in text and "ap_reviewed equals ap_all" in text
    assert out.read_bytes().endswith(b"\n") and b"\r" not in out.read_bytes()


def test_the_report_says_what_happens_when_it_does_not_ship(tmp_path):
    metrics = {"classifier": {"n_all": 9, "n_reviewed": 9, "ap_all": 0.30, "ap_reviewed": 0.30,
                              "p50_all": 0.1, "p200_all": 0.1, "per_cell": {}},
               "fusion": {"n_all": 9, "n_reviewed": 9, "ap_all": 0.40, "ap_reviewed": 0.40,
                          "p50_all": 0.2, "p200_all": 0.2, "per_cell": {}}}
    out = tmp_path / "r.md"
    tr.write_report(out, metrics=metrics, tag="v2",
                    heldout={"path": "p", "sha256": "abcdef123456789", "n": 9,
                             "pin": "heldout_v2_sha256"},
                    strata={}, shipped=False, commit="c", cv={"cv_C": 1.0, "cv_ap": 0.5},
                    train={"n_pos": 1, "n_neg": 1})
    text = out.read_text(encoding="utf-8")
    assert "DOES NOT SHIP" in text and "classifier v1 ordering" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_ranker_classifier.py tests/test_train_ranker_tool.py`
Expected: FAIL — `ImportError: cannot import name 'ships'`, `AttributeError: module 'train_ranker' has no attribute 'build_parser'`.

- [ ] **Step 3: `ships()` in `corpus_engine/ranker/evaluate.py`**

```python
def ships(classifier: dict, fusion: dict) -> bool:
    """D6, exactly as Stage 2C pre-registered it: the classifier becomes `ranking.default`
    only if its average precision EXCEEDS fusion's on BOTH views - all held-out reads, and the
    reviewed view. No margin, no tie-break, no per-cell override: `>` on both, or it does not
    ship. It lives here so the tool that decides and the report that explains the decision
    cannot drift apart."""
    return (classifier["ap_all"] > fusion["ap_all"]
            and classifier["ap_reviewed"] > fusion["ap_reviewed"])
```

- [ ] **Step 4: `train()` gains the pin, the extra rankers and the overwrite guard**

In `corpus_engine/ranker/classifier.py`, change the signature:

```python
def train(conn, domain, labels, heldout, *, version: str, out_dir: Path, commit: str,
         layout: FeatureLayout | None = None, heldout_path: Path | None = None,
         heldout_pin: str = "heldout_sha256", extra_rankers: dict | None = None,
         overwrite: bool = False) -> dict:
```

Immediately after the overlap check, before anything is fitted:

```python
    out_dir = Path(out_dir)
    if (out_dir / MANIFEST_FILE).exists() and not overwrite:
        raise ValueError(f"{out_dir} already holds a trained model; a retrain of a shipped "
                         f"version is a new version, not an overwrite (spec section 9). Pass "
                         f"overwrite=True (tools/train_ranker.py --force) only deliberately.")
```

The held-out verification becomes `h = check_heldout(domain, heldout_path, pin=heldout_pin)`,
and both manifest shapes carry the pin so a reader of `data/ranker/<tag>/manifest.json` can see
which slice the numbers are about:

```python
        heldout_manifest = {"path": rel, "sha256": h, "n": len(heldout), "pin": heldout_pin}
    else:
        heldout_manifest = {"n": len(heldout), "pin": None}
```

The metrics block evaluates the extras on the same ids:

```python
    ranker = ClassifierRanker(out_dir); hid = [l.case_id for l in heldout]
    f = domain.ranking.fusion
    metrics = {"classifier": evaluate_scores(heldout, ranker.score(conn, "train", hid)),
               "fusion": evaluate_scores(heldout,
                                         FusionRanker(layout, f["lexical_weight"],
                                                      f["cosine_weight"]).score(conn, "train",
                                                                                hid))}
    # Every other ranker this run is told to compare against, on the SAME slice and the SAME
    # ids - the shipped classifier v1 in slice 3, so the report can say whether v2 beats what
    # is in the field as well as whether it beats fusion (D6 only tests the latter).
    for name, other in (extra_rankers or {}).items():
        metrics[name] = evaluate_scores(heldout, other.score(conn, "train", hid))
    manifest["metrics"] = metrics
    (out_dir / MANIFEST_FILE).write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    return manifest
```

- [ ] **Step 5: Rewrite `tools/train_ranker.py`**

```python
r"""Train classifier:<tag> on the labelled reads minus BOTH frozen held-out slices, evaluate
it against the shipped classifier and fusion on one of them, and apply the ship rule (D6).

  .venv\Scripts\python tools\train_ranker.py --heldout v2 --tag v2 --report reports\ranking-v2.md

It never edits domain.yaml. That file carries the comments this project's decisions are
recorded in, and a programmatic rewrite would drop every one of them; the tool prints the one
line to change and the operator makes that edit by hand.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                   # noqa: E402
from corpus_engine.domain import load_domain                                      # noqa: E402
from corpus_engine.ledger import open_ledger                                      # noqa: E402
from corpus_engine.ranker.classifier import ClassifierRanker, train               # noqa: E402
from corpus_engine.ranker.evaluate import ships                                   # noqa: E402
from corpus_engine.ranker.labels import (labelled_reads, load_heldout,            # noqa: E402
                                          read_extractions)

PINS = {"v1": "heldout_sha256", "v2": "heldout_v2_sha256"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="train_ranker.py", description=__doc__.splitlines()[0])
    ap.add_argument("--tag", "--version", dest="tag", default=None,
                    help="the classifier version this run trains, and the directory it writes "
                         "(data/ranker/<tag>); default: domain.ranking.classifier_version")
    ap.add_argument("--heldout", default="v1", choices=sorted(PINS),
                    help="which frozen slice to EVALUATE on. Both are always excluded from "
                         "training, whichever one is evaluated against.")
    ap.add_argument("--report", default=None, help="write the markdown report here")
    ap.add_argument("--force", action="store_true",
                    help="retrain into a directory that already holds a model")
    return ap


def split_labels(labels, held_v1, held_v2, *, evaluate_on: str):
    """(training set, evaluation slice). BOTH frozen slices leave the training set, whichever
    one is being evaluated: a model trained on v1's rows and graded on v2's would still have
    seen v1's, and the two overlap wherever a v1 case has since been human-decided.

    The evaluation slice is narrowed to the labels this run actually has - a held-out case
    with no label today (a duplicate marked since, a case dropped from the store) is not
    scored rather than scored as a miss."""
    excluded = {l.case_id for l in held_v1} | {l.case_id for l in held_v2}
    train_set = [l for l in labels if l.case_id not in excluded]
    chosen = held_v2 if evaluate_on == "v2" else held_v1
    known = {l.case_id for l in labels}
    return train_set, [l for l in chosen if l.case_id in known]


def write_report(path: Path, *, metrics, tag, heldout, strata, shipped, commit, cv, train) -> None:
    """reports/ranking-<tag>.md: what the slice is made of, the AP table for every ranker
    evaluated, the rule verbatim, and the outcome."""
    rows = [(f"classifier:{tag}", metrics["classifier"])]
    rows += [(name, m) for name, m in sorted(metrics.items())
             if name not in ("classifier", "fusion")]
    rows.append(("fusion:v1", metrics["fusion"]))
    c, f = metrics["classifier"], metrics["fusion"]
    lines = [f"# Ranker {tag}: held-out {heldout['pin']}, three-way evaluation, ship rule", "",
             f"**Trained at commit `{commit}`.** Training set: {train['n_pos']} positives / "
             f"{train['n_neg']} negatives, both frozen slices excluded. Cross-validated `C` = "
             f"{cv['cv_C']} (mean AP {cv['cv_ap']:.4f}).", "",
             "## 1. The held-out slice", "",
             f"- Path: `{heldout['path']}` (sha256 `{str(heldout['sha256'])[:12]}...`, pinned "
             f"in domain.yaml as `{heldout['pin']}`).",
             f"- Rows scored: {heldout['n']}. Every row is a human relevance decision (D3): "
             f"human-reviewed relevant positives, reviewer-overturned negatives.",
             "- Because every row is human-decided, the reviewed view "
             "(`reviewed or label == 0`) is the whole slice, so **ap_reviewed equals ap_all** "
             "here and D6's two-view test is arithmetically one view. That is a property of a "
             "slice made only of human labels, not a defect in the rule.", "",
             "### Per-stratum counts", "", "| era \\| jurisdiction \\| label | n |", "|---|---|"]
    lines += [f"| {k} | {strata[k]} |" for k in sorted(strata)]
    lines += ["", "## 2. Average precision on the held-out slice", "",
              "| Ranker | ap_all | ap_reviewed | p50_all | p200_all |", "|---|---|---|---|---|"]
    for name, m in rows:
        lines.append(f"| {name} | {m['ap_all']:.4f} | {m['ap_reviewed']:.4f} | "
                     f"{m['p50_all']:.3f} | {m['p200_all']:.3f} |")
    lines += ["", "## 3. Ship rule (D6)", "",
              f"> classifier {tag} ships as `ranking.default` only if its average precision "
              "exceeds fusion's on BOTH views (all held-out reads, human-reviewed reads). "
              "No margin.", "",
              f"- ap_all: {c['ap_all']:.4f} vs fusion {f['ap_all']:.4f} - "
              f"{'passes' if c['ap_all'] > f['ap_all'] else 'FAILS'}",
              f"- ap_reviewed: {c['ap_reviewed']:.4f} vs fusion {f['ap_reviewed']:.4f} - "
              f"{'passes' if c['ap_reviewed'] > f['ap_reviewed'] else 'FAILS'}", "",
              f"**Outcome: classifier:{tag} " + ("SHIPS" if shipped else "DOES NOT SHIP")
              + ".** " + (f"Set `ranking.classifier_version: {tag}` in domain.yaml; the tail "
                          f"map runs on it."
                          if shipped else
                          "domain.yaml is unchanged: the tail map runs on the existing "
                          "classifier v1 ordering under the same budget (D6)."), "",
              "## 4. Per-cell AP (the evaluated classifier)", "",
              "| Cell | n | ap | p50 |", "|---|---|---|---|"]
    for cell, m in sorted(metrics["classifier"]["per_cell"].items()):
        lines.append(f"| {cell} | {m['n']} | {m['ap']:.4f} | {m['p50']:.3f} |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines).replace("\r\n", "\n") + "\n").encode("utf-8"))


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    dom = load_domain()
    tag = a.tag or dom.ranking.classifier_version
    hpath = ROOT / (dom.ranking.heldout_v2 if a.heldout == "v2" else dom.ranking.heldout)
    held_v1 = load_heldout(ROOT / dom.ranking.heldout)
    v2_path = ROOT / dom.ranking.heldout_v2 if dom.ranking.heldout_v2 else None
    held_v2 = load_heldout(v2_path) if v2_path and v2_path.exists() else []
    conn = store.connect()
    labels = labelled_reads(open_ledger(domain=dom).view(),
                            read_extractions(store.paths().runs), conn)
    train_set, evaluated = split_labels(labels, held_v1, held_v2, evaluate_on=a.heldout)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    extra = {}
    shipped_dir = ROOT / "data" / "ranker" / dom.ranking.classifier_version
    if dom.ranking.classifier_version != tag and (shipped_dir / "manifest.json").exists():
        extra[f"classifier:{dom.ranking.classifier_version}"] = ClassifierRanker(shipped_dir)
    man = train(conn, dom, train_set, evaluated, version=tag,
                out_dir=ROOT / "data" / "ranker" / tag, commit=commit, heldout_path=hpath,
                heldout_pin=PINS[a.heldout], extra_rankers=extra, overwrite=a.force)
    c, f = man["metrics"]["classifier"], man["metrics"]["fusion"]
    print(f"train {man['train']} cv_C={man['cv_C']} cv_ap={man['cv_ap']:.4f}")
    print(f"held-out {a.heldout} n={c['n_all']} (reviewed view n={c['n_reviewed']})")
    for name, m in sorted(man["metrics"].items()):
        print(f"  {name:>16}: ap_all={m['ap_all']:.4f} ap_reviewed={m['ap_reviewed']:.4f} "
              f"p50={m['p50_all']:.3f} p200={m['p200_all']:.3f}")
    shipped = ships(c, f)
    print("SHIP RULE (D6):",
          f"classifier:{tag} beats fusion on both views and ships" if shipped
          else f"classifier:{tag} did NOT beat fusion on both views; it does not ship")
    print(f"domain.yaml: {'set ranking.classifier_version to ' + tag if shipped else 'unchanged'}")
    if a.report:
        strata: dict[str, int] = {}
        for l in evaluated:
            key = f"{l.era}|{l.jurisdiction}|{l.label}"
            strata[key] = strata.get(key, 0) + 1
        report = Path(a.report)
        write_report(report if report.is_absolute() else ROOT / report, metrics=man["metrics"],
                     tag=tag, heldout=man["heldout"], strata=strata, shipped=shipped,
                     commit=commit, cv=man, train=man["train"])
        print(f"report -> {a.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_ranker_classifier.py tests/test_train_ranker_tool.py tests/test_ranker_ports.py`
Expected: PASS. Then the whole suite.

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/ranker/evaluate.py corpus_engine/ranker/classifier.py tools/train_ranker.py tests/test_ranker_classifier.py tests/test_train_ranker_tool.py
git commit -m "ranker: trainer v2 - both slices excluded, three rankers scored, D6 in one place

evaluate.ships() is the pre-registered rule verbatim; train() takes the
held-out pin, extra rankers to score on the same ids, and refuses to
overwrite a shipped model directory. train_ranker.py gains --heldout,
--tag, --report and never edits domain.yaml.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 4: Re-rank the unread tail into `cycle-004-shard-02` (spec section 5)

`pipeline/rank.py` packs from the whole `signals` table. The tail is a strict subset of one
earlier run's pool, so the tool has to be told which pool to re-score: `--from-run` restricts
the candidate set to the cases packed into `cycle-004-shard-01`, and the already-read exclusion
(now spelled `--exclude-read`, unchanged as the default) removes the 6,840 the map has read.
What is left is the 1,465 unread batches' cases, re-scored with the shipped ranker and
re-packed under `runs/cycle-004-shard-02/batches/`.

`build_batches` already sorts each cell's cases by descending score and then orders the batches
globally by mean score, carrying `era_partition` and `jurisdiction` on every case, so "re-packs
them in descending score" needs no new packing logic — only the restriction.

**Files:**
- Modify: `corpus_engine/selector/packing.py`, `pipeline/rank.py`
- Test: `tests/test_ranker_packing.py`, `tests/test_rank_cli.py`

**Interfaces:**
- Consumes: `already_read_ids`, `gold_ids`, `load_ranker`, `load_heldout`, `corpus_engine.mapper.cells.load_batches`.
- Produces (T5 and T8 consume exactly these):
  - `corpus_engine.selector.packing.build_batches(conn, run_id, *, gold_ids, exclude_ids, batch_size=18, ranker=None, ts=None, restrict_ids: set[int] | None = None)`, same new keyword on `pack_batches`
  - `pipeline.rank.pool_case_ids(runs_dir: Path, run_id: str) -> set[int]`
  - `pipeline.rank.build_parser() -> argparse.ArgumentParser`
  - `pipeline.rank.rerank(conn, run_id, *, ranker_id, runs_dir, ledger_dir, domain=None, out_dir=None, log=print, heldout_path=None, from_run: str | None = None, exclude_read: bool = True) -> dict`
  - `runs/cycle-004-shard-02/shard-manifest.json` gains, beside `"ranker"`:
    `"source": {"run_id": str, "pool_cases": int, "excluded_read": int, "excluded_case_ids": [int, ...], "packed_cases": int}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ranker_packing.py`:

```python
def test_restrict_ids_narrows_the_pool_before_the_exclusion(tmp_path, fixture_db, repo_root):
    from corpus_engine.selector.packing import build_batches
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    everything = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=set())
                  for c in b["cases"]}
    keep = set(sorted(everything)[:20])
    packed = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=set(),
                                                  restrict_ids=keep) for c in b["cases"]}
    assert packed == keep and packed < everything
    drop = set(sorted(keep)[:5])
    packed = {c["case_id"] for b in build_batches(conn, "r", gold_ids=set(), exclude_ids=drop,
                                                  restrict_ids=keep) for c in b["cases"]}
    assert packed == keep - drop          # restriction and exclusion compose
```

Append to `tests/test_rank_cli.py`:

```python
def test_rerank_from_a_source_run_packs_only_its_unread_cases(tmp_path, fixture_db, repo_root):
    """The tail: the source run's pool minus what has been read. The manifest records the
    source, the ranker and the ids left out, so the shard is re-derivable from that file."""
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    runs = tmp_path / "runs"
    src = runs / "cycle-004-shard-01" / "batches"; src.mkdir(parents=True)
    all_ids = sorted({r[0] for r in conn.execute("SELECT DISTINCT case_id FROM signals")})
    pool, read = all_ids[:24], all_ids[:6]
    (src / "batch-001.json").write_text(json.dumps(
        {"batch_id": "cycle-004-shard-01-batch-001", "ranker_id": "classifier:v1",
         "era_partition": "1900-1930", "jurisdiction": "N.Y.",
         "cases": [{"case_id": c, "era_partition": "1900-1930", "jurisdiction": "N.Y.",
                    "rank_score": 0.5, "signals": []} for c in pool]}), encoding="utf-8")
    ext = runs / "cycle-004-shard-01" / "extractions"; ext.mkdir(parents=True)
    (ext / "b.json").write_text(json.dumps([{"case_id": c} for c in read]), encoding="utf-8")
    dst = runs / "cycle-004-shard-02"; (dst / "batches").mkdir(parents=True)
    rep = rank_cli.rerank(conn, "cycle-004-shard-02", ranker_id="null", runs_dir=runs,
                          ledger_dir=tmp_path / "ledger", from_run="cycle-004-shard-01",
                          log=lambda *_: None)
    packed = {c["case_id"] for f in (dst / "batches").glob("batch-*.json")
              for c in json.loads(f.read_text(encoding="utf-8"))["cases"]}
    assert packed == set(pool) - set(read) and rep["cases"] == len(packed)
    m = json.loads((dst / "shard-manifest.json").read_text(encoding="utf-8"))
    assert m["source"] == {"run_id": "cycle-004-shard-01", "pool_cases": len(pool),
                           "excluded_read": len(read), "excluded_case_ids": sorted(read),
                           "packed_cases": len(packed)}
    assert m["ranker"]["ranker_id"] == "null"


def test_rerank_packs_batches_in_descending_score_order(tmp_path, fixture_db, repo_root):
    conn = make_ranker_db(tmp_path, fixture_db, repo_root)
    runs = tmp_path / "runs"; (runs / "r3" / "batches").mkdir(parents=True)
    rank_cli.rerank(conn, "r3", ranker_id="fusion", runs_dir=runs,
                    ledger_dir=tmp_path / "ledger", log=lambda *_: None)
    means = []
    for f in sorted((runs / "r3" / "batches").glob("batch-*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        means.append(sum(c["rank_score"] for c in b["cases"]) / len(b["cases"]))
        assert all(c["era_partition"] == b["era_partition"] for c in b["cases"])
        assert all(c["jurisdiction"] == b["jurisdiction"] for c in b["cases"])
    assert means == sorted(means, reverse=True)


def test_the_parser_carries_the_tail_flags():
    a = rank_cli.build_parser().parse_args(["--run-id", "cycle-004-shard-02",
                                            "--from-run", "cycle-004-shard-01",
                                            "--exclude-read"])
    assert a.from_run == "cycle-004-shard-01" and a.exclude_read is True
    assert rank_cli.build_parser().parse_args(["--run-id", "x"]).exclude_read is True
    assert rank_cli.build_parser().parse_args(["--run-id", "x",
                                               "--include-read"]).exclude_read is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_ranker_packing.py tests/test_rank_cli.py`
Expected: FAIL — `TypeError: build_batches() got an unexpected keyword argument 'restrict_ids'`.

- [ ] **Step 3: `restrict_ids` in `corpus_engine/selector/packing.py`**

Add `restrict_ids: set[int] | None = None` to both signatures, pass it through from
`pack_batches`, and add one block in `build_batches` immediately **before** the `exclude_ids`
block:

```python
    if restrict_ids is not None:
        # The pool this run may consider at all: a re-rank of one earlier run's tail packs
        # that run's cases and no others, even though `signals` holds every case the selectors
        # have ever hit. Applied BEFORE the exclusion, so the manifest's excluded count is
        # about the restricted pool - the number an operator can check against the map.
        for key in list(groups):
            groups[key] = [e for e in groups[key] if e["case_id"] in restrict_ids]
        groups = {k: v for k, v in groups.items() if v}
```

- [ ] **Step 4: `--from-run` / `--exclude-read` in `pipeline/rank.py`**

```python
def pool_case_ids(runs_dir: Path, run_id: str) -> set[int]:
    """Every case packed into `run_id`'s batches.

    The batch files are the record of what that run's pool WAS. `rankings` rows say what was
    scored, which is the same set only until the next re-pack; `signals` says what the
    selectors ever hit, which is far more."""
    from corpus_engine.mapper.cells import load_batches
    batches_dir = Path(runs_dir) / run_id / "batches"
    if not batches_dir.is_dir():
        raise SystemExit(f"no source pool: {batches_dir} does not exist")
    return {int(c["case_id"]) for b in load_batches(batches_dir) for c in (b.get("cases") or ())}
```

`rerank` gains `from_run: str | None = None, exclude_read: bool = True`, and inside it:

```python
    exclude = already_read_ids(runs_dir, ledger_dir) if exclude_read else set()
    restrict = pool_case_ids(runs_dir, from_run) if from_run else None
    ...
    n = pack_batches(conn, run_id, out, gold_ids=gold, exclude_ids=exclude,
                     batch_size=domain.sharding.batch_size, ranker=ranker, ts=ts,
                     restrict_ids=restrict)
```

Move the `cases = sum(...)` line above the manifest write, and after the `"ranker"` block add:

```python
    if restrict is not None:
        # Provenance for a shard that is a subset of another shard: which run it came from,
        # how big that pool was, and exactly which of its cases were left out for having been
        # read already. The ids are written out rather than counted, so this file alone is
        # enough to re-derive the shard.
        left_out = sorted(restrict & exclude)
        manifest["source"] = {"run_id": from_run, "pool_cases": len(restrict),
                              "excluded_read": len(left_out), "excluded_case_ids": left_out,
                              "packed_cases": cases}
```

Replace the inline parser in `main` with a `build_parser()` the test can inspect:

```python
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rank.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ranker", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--from-run", default=None,
                    help="re-score and re-pack only the cases packed into this earlier run; "
                         "its batch files are the record of its pool")
    ap.add_argument("--exclude-read", dest="exclude_read", action="store_true", default=True,
                    help="leave out every case already read (the default)")
    ap.add_argument("--include-read", dest="exclude_read", action="store_false",
                    help="pack already-read cases too; only for a diagnostic re-pack")
    return ap


def main() -> int:
    a = build_parser().parse_args()
    conn = store.connect(); store.ensure_schema(conn); store.migrate(conn)
    p = store.paths()
    rerank(conn, a.run_id, ranker_id=a.ranker, runs_dir=p.runs, ledger_dir=p.ledger,
           out_dir=Path(a.out_dir) if a.out_dir else None, from_run=a.from_run,
           exclude_read=a.exclude_read)
    return 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_ranker_packing.py tests/test_rank_cli.py tests/test_selector_coverage.py`
Expected: PASS. Then the whole suite.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/selector/packing.py pipeline/rank.py tests/test_ranker_packing.py tests/test_rank_cli.py
git commit -m "rank: --from-run restricts the pool to an earlier run's unread tail

build_batches gains restrict_ids, applied before the already-read
exclusion; rank.py gains --from-run / --exclude-read / --include-read and
records the source run, the pool size and the excluded case ids in the
shard manifest.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 5: `--case-budget` — a global-order walk under a fixed case budget (spec section 5, D4)

The tail is ~26,400 cases at mean `rank_score` 0.04–0.06; D4 spends a fixed 3,000 of them
top-down on the re-ranked order **across all cells**, not cell by cell. Cell caps are not used
at all (the manifest records `cap: none`), and the slice-2 yield-floor rule — window 3,
threshold 2 — still stops a cell that has stopped paying.

The existing per-cell walk is untouched. A budgeted run goes through a second method,
`_run_budget`, rather than through a rewritten `run()`: the cell-major path is what read the
whole cycle-004 map and what `--retry-lost` and the screen are written against, and a
refactor that interleaved cells would move the screen's trigger point and the per-cell
`wall_seconds` for a feature that is off this slice. Both paths share `_finish`.

**Files:**
- Modify: `corpus_engine/mapper/cells.py`, `corpus_engine/mapper/runner.py`, `corpus_engine/mapper/__init__.py`, `tools/map_reader.py`
- Test: `tests/test_mapper_cells.py`, `tests/test_mapper_runner.py`, `tests/test_map_reader_tool.py`

**Interfaces:**
- Consumes: `Cell`, `CellProgress`, `BatchSource`, `load_batches`, `batch_mean_rank_score`, `MapRunner`, `RunnerCaps`, `merge_manifest` as they stand.
- Produces (T6 and T8 consume exactly these):
  - `Cell.uncapped: bool = False` (last field, defaulted, so every existing construction still works); `Cell.to_json()` gains `"cap": "none" if self.uncapped else "batches"`
  - `corpus_engine.mapper.cells.build_budget_cells(batches) -> list[Cell]`
  - `corpus_engine.mapper.cells.global_batch_order(batches) -> tuple[tuple[str, str], ...]` — `(cell_key, batch_id)`, best mean rank score first
  - `corpus_engine.mapper.runner.RunnerCaps(max_units: int, max_wall_seconds: float, case_budget: int | None = None)`
  - `MapRunner(..., global_order: Sequence[tuple[str, str]] | None = None)`
  - `corpus_engine.mapper.runner.default_max_units_for_budget(case_budget: int, batch_size: int = 18) -> int`
  - `PROCESS_STOPS` gains `"budget:cases"`
  - manifest additions: `flags.case_budget: int | None`, `flags.order: "global" | "cell"`, per-cell `"cap": "none"`, and `process.stop` / `stop` may be `"budget:cases"`
  - `tools/map_reader.py` flag `--case-budget N`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mapper_cells.py`:

```python
from corpus_engine.mapper.cells import build_budget_cells, global_batch_order


def _b(bid, era, jur, *scores):
    return {"batch_id": bid, "era_partition": era, "jurisdiction": jur,
            "cases": [{"case_id": i, "rank_score": s} for i, s in enumerate(scores, 1)]}


def test_budget_cells_are_uncapped_and_say_so():
    """D4: the budget stops the run, not the cap, so every batch in a cell is walkable and the
    manifest records `cap: none` rather than a number that governs nothing."""
    cells = build_budget_cells([_b("b1", "1930-1970", "N.Y.", 0.9, 0.7),
                                _b("b2", "1930-1970", "N.Y.", 0.1),
                                _b("b3", "pre-1860", "Pa.", 0.5)])
    by_key = {c.key: c for c in cells}
    ny = by_key["1930-1970|N.Y."]
    assert ny.cap_batches == 2 and ny.capped_ids == ("b1", "b2") and ny.uncapped is True
    assert ny.to_json()["cap"] == "none" and ny.to_json()["n_batches"] == 2
    assert [c.key for c in cells] == ["1930-1970|N.Y.", "pre-1860|Pa."]   # by mean, desc


def test_the_global_order_is_every_batch_best_first_regardless_of_cell():
    order = global_batch_order([_b("a", "1930-1970", "N.Y.", 0.2),
                                _b("b", "pre-1860", "Pa.", 0.9),
                                _b("c", "1930-1970", "N.Y.", 0.5)])
    assert order == (("pre-1860|Pa.", "b"), ("1930-1970|N.Y.", "c"), ("1930-1970|N.Y.", "a"))


def test_the_global_order_breaks_ties_on_batch_id():
    order = global_batch_order([_b("z", "pre-1860", "Pa.", 0.5), _b("a", "pre-1860", "Pa.", 0.5)])
    assert [bid for _k, bid in order] == ["a", "z"]
```

Append to `tests/test_mapper_runner.py` (using the file's existing fake reader / batch-source
fixtures — match their names):

```python
def test_a_budgeted_run_stops_when_the_budget_is_spent(tmp_path):
    """Three batches of two cases, budget 4: two batches are read, the third is not begun, and
    the process stop is the budget's own kind."""
    runner, source = _runner(tmp_path, batches=[("c1", "b1", 2), ("c1", "b2", 2),
                                                ("c1", "b3", 2)],
                             caps=RunnerCaps(max_units=99, max_wall_seconds=999,
                                             case_budget=4))
    out = runner.run()
    assert out.stop == "budget:cases"
    assert out.manifest["totals"]["cases_read"] == 4
    assert out.manifest["totals"]["batches_completed"] == 2
    assert out.manifest["flags"]["case_budget"] == 4
    assert out.manifest["flags"]["order"] == "global"


def test_a_budgeted_run_walks_the_global_order_not_the_cells(tmp_path):
    """Cell A's second-best batch must wait behind cell B's best one: the budget is spent on
    the best batches in the POOL, which is the whole point of D4."""
    runner, source = _runner(tmp_path,
                             batches=[("a", "a1", 2, 0.9), ("a", "a2", 2, 0.1),
                                      ("b", "b1", 2, 0.5)],
                             caps=RunnerCaps(max_units=99, max_wall_seconds=999,
                                             case_budget=6))
    out = runner.run()
    read = [u["unit_id"] for key in out.manifest["cell_order"]
            for u in out.manifest["cells"][key]["units"]]
    assert sorted(read) == ["a1", "a2", "b1"]
    assert runner_call_order(runner) == ["a1", "b1", "a2"]     # the fixture's call recorder


def test_the_yield_floor_still_stops_a_quiet_cell_in_a_budgeted_run(tmp_path):
    """Window 3, threshold 2 applies per cell exactly as in a capped run: once cell A has
    stopped paying, the walk skips A's remaining batches and spends the budget elsewhere."""
    runner, source = _runner(tmp_path, batches=[("a", f"a{i}", 2, 0.9 - i / 100)
                                                for i in range(1, 6)] + [("b", "b1", 2, 0.1)],
                             relevant_per_batch=0, caps=RunnerCaps(max_units=99,
                                                                   max_wall_seconds=999,
                                                                   case_budget=99))
    out = runner.run()
    a = out.manifest["cells"]["a"]
    assert a["batches_completed"] == 3 and a["stop"]["kind"] == "yield_floor"
    assert out.manifest["cells"]["b"]["batches_completed"] == 1
    assert out.stop == "done"


def test_a_capped_run_still_records_the_cell_order_and_no_budget(tmp_path):
    """The existing walk is untouched: no global order, no budget, `order: cell`."""
    runner, source = _runner(tmp_path, batches=[("c1", "b1", 2)])
    out = runner.run()
    assert out.manifest["flags"]["order"] == "cell"
    assert out.manifest["flags"]["case_budget"] is None
```

Append to `tests/test_map_reader_tool.py`:

```python
def test_the_case_budget_flag_switches_the_run_to_a_global_uncapped_walk(wired, capsys):
    assert mr.main(["--run-id", RUN_ID, "--case-budget", "2", "--sample-pct", "0"]) == 0
    doc = _manifest(wired)
    assert doc["flags"]["case_budget"] == 2 and doc["flags"]["order"] == "global"
    assert all(c["cap"] == "none" for c in doc["cells"].values())
    assert doc["totals"]["cases_read"] == 2 and doc["stop"] == "budget:cases"
    assert "case budget 2" in capsys.readouterr().out


def test_a_case_budget_of_zero_is_refused(wired):
    with pytest.raises(SystemExit) as exc:
        mr.main(["--case-budget", "0"])
    assert "reads nothing" in str(exc.value)


def test_the_parser_carries_the_budget_flag():
    ap = mr.build_parser()
    assert "--case-budget" in {a for action in ap._actions for a in action.option_strings}
    assert ap.parse_args([]).case_budget is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_mapper_cells.py tests/test_mapper_runner.py tests/test_map_reader_tool.py`
Expected: FAIL — `ImportError: cannot import name 'build_budget_cells'`.

- [ ] **Step 3: `corpus_engine/mapper/cells.py`**

Add `uncapped: bool = False` as the **last** field of `Cell` and extend `to_json`:

```python
    def to_json(self) -> dict:
        return {"era": self.era, "jurisdiction": self.jurisdiction,
                "n_batches": len(self.batch_ids), "cap_batches": self.cap_batches,
                "mean_rank_score": round(self.mean_rank_score, 6),
                # D4: a budgeted run has no per-cell cap - the budget stops the run and the
                # yield floor stops a cell - so the manifest says `none` rather than repeating
                # a `cap_batches` that is only the cell's own size and governs nothing.
                "cap": "none" if self.uncapped else "batches"}
```

Add the two builders below `build_cells`:

```python
def build_budget_cells(batches: Sequence[Mapping]) -> list[Cell]:
    """The cells of a budgeted run (D4): every batch is walkable, so the cap is the cell's own
    size and `uncapped` says the number means nothing. The order is still by mean rank score,
    which matters only for the manifest's `cell_order` - a budgeted run walks
    `global_batch_order`, not the cells."""
    by_cell: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for b in batches:
        by_cell.setdefault((b["era_partition"], b["jurisdiction"]), []).append(
            (batch_mean_rank_score(b), b["batch_id"]))
    cells = []
    for (era, jur), rows in by_cell.items():
        rows.sort(key=lambda r: (-r[0], r[1]))
        scores = [s for s, _bid in rows]
        cells.append(Cell(era, jur, tuple(bid for _s, bid in rows), len(rows),
                          sum(scores) / len(scores), uncapped=True))
    cells.sort(key=lambda c: (-c.mean_rank_score, c.era, c.jurisdiction))
    return cells


def global_batch_order(batches: Sequence[Mapping]) -> tuple[tuple[str, str], ...]:
    """`(cell_key, batch_id)` for every batch in the pool, best mean rank score first, batch id
    breaking ties (D4). This is the order a budgeted run spends its cases in: top down across
    ALL cells, so the last batch bought is the worst one the budget could reach - which is the
    number the D5 test in the report is about."""
    rows = [(batch_mean_rank_score(b), b["batch_id"],
             f"{b['era_partition']}|{b['jurisdiction']}") for b in batches]
    rows.sort(key=lambda r: (-r[0], r[1]))
    return tuple((cell_key, bid) for _s, bid, cell_key in rows)
```

- [ ] **Step 4: `corpus_engine/mapper/runner.py`**

`PROCESS_STOPS` gains the new kind, `RunnerCaps` the budget, and a new default-units helper:

```python
PROCESS_STOPS = ("budget:units", "budget:wall", "budget:usd", "budget:cases")


@dataclass(frozen=True)
class RunnerCaps:
    max_units: int
    max_wall_seconds: float
    # D4. Cases READ by this process, checked between batches like every other ceiling. A
    # resume re-counts the cases it replays from cache, and that is right: the budget is a
    # statement about how much of the tail is mapped, not about what a process spent.
    case_budget: int | None = None


def default_max_units_for_budget(case_budget: int, batch_size: int = 18) -> int:
    """Every batch the budget can pay for, plus the same tenth `default_max_units` adds for
    split halves."""
    return math.ceil(math.ceil(case_budget / batch_size) * (1 + UNIT_MARGIN_PCT / 100))
```

`MapRunner.__init__` takes `global_order: Sequence[tuple[str, str]] | None = None` and stores
`self.global_order = tuple(global_order) if global_order is not None else None`.

`_gate` gains the budget check, first, because it is the cheapest and the one an operator set:

```python
    def _gate(self, counts: dict, t0: float) -> str | None:
        """The per-PROCESS ceilings, checked before a batch is begun."""
        if self.caps.case_budget is not None and counts["cases"] >= self.caps.case_budget:
            return "budget:cases"
        if counts["reader"] >= self.caps.max_units:
            return "budget:units"
        if self.clock() - t0 >= self.caps.max_wall_seconds:
            return "budget:wall"
        return None
```

In `_read_batch`, count the cases as the rows are appended:

```python
            row = self._unit_doc(u, keys, out.disagreements, retry=retry)
            acc["units"].append(row)
            counts["cases"] = counts.get("cases", 0) + (row["cases_read"] or 0)
```

Both `run()` and `_run_budget` initialise `counts = {"reader": 0, "checker": 0,
"screen_pinned": 0, "cases": 0}`.

Extract the existing `finally` body into a method both paths call:

```python
    def _finish(self, cells, progress, records, counts, totals, seen, t0, started, stop):
        """The manifest, merged onto whatever is on disk and written whole. Called from both
        walks' `finally`, possibly with an exception already in flight - see
        `_merge_onto_prior`."""
        fresh = self._manifest(cells, progress, records, counts, totals, seen, t0, started, stop)
        manifest, written = self._merge_onto_prior(fresh, counts, totals, t0)
        self._write(written, manifest)
        self.log(f"manifest -> {written}")
        self.log(f"resume: {manifest['resume_command']}")
        return manifest, written
```

`run()` dispatches at the top and otherwise keeps its body verbatim:

```python
    def run(self, cells=None, *, retry_ids=None) -> MapOutcome:
        cells = list(self.cells if cells is None else cells)
        if self.global_order is not None and retry_ids is None:
            return self._run_budget(cells)
        ...                                    # the existing cell-major body, unchanged
```

And the budgeted walk:

```python
    def _run_budget(self, cells: Sequence[Cell]) -> MapOutcome:
        """D4's walk: every cell's batches interleaved by rank score, top down, until the case
        budget is spent.

        Deliberately a second method rather than a generalisation of `run()`. The cell-major
        walk is what read the whole cycle-004 map, and it is what `--retry-lost` and the screen
        are written against; interleaving cells there would move the screen's trigger point and
        turn each cell's `wall_seconds` from a duration into a span. This walk runs no screen
        (D5: there is none this slice), plans no retries, and finalises every cell's stop after
        the walk instead of at the end of the cell - because in this order a cell does not end
        until the pool does."""
        t0 = self.clock()
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        counts = {"reader": 0, "checker": 0, "screen_pinned": 0, "cases": 0}
        totals = {"input_tokens": 0, "output_tokens": 0, "spend_usd": 0.0, "unpriced_requests": 0}
        seen = {"provider": None, "provider_reported": set(), "tool_version": None}
        by_key = {c.key: c for c in cells}
        progress: dict[str, CellProgress] = {}
        records: dict[str, dict] = {}
        cell_t0: dict[str, float] = {}
        stop = "done"
        try:
            for cell_key, batch_id in self.global_order:
                cell = by_key.get(cell_key)
                if cell is None:
                    continue                   # a `--cells` subset: not this run's business
                if cell_key not in progress:
                    progress[cell_key] = CellProgress(cell_key, cell.cap_batches)
                    records[cell_key] = {**cell.to_json(), "units": [],
                                         "screen": dict(CELL_SCREEN_OFF), "screen_pinned": [],
                                         "wall_seconds": 0.0}
                    cell_t0[cell_key] = self.clock()
                prog = progress[cell_key]
                if prog.should_stop(window=self.window, threshold=self.threshold) is not None:
                    continue                   # this cell has stopped paying; the walk goes on
                stop = self._gate(counts, t0) or stop
                if stop in PROCESS_STOPS:
                    break
                stop = self._read_batch(cell, self.batch_source.get(batch_id), records[cell_key],
                                        prog, counts, totals, seen, t0) or stop
                records[cell_key]["wall_seconds"] = round(self.clock() - cell_t0[cell_key], 1)
                if stop in PROCESS_STOPS:
                    break
            for key, prog in progress.items():
                cell_stop = prog.should_stop(window=self.window, threshold=self.threshold)
                records[key]["cell_stop"] = cell_stop.to_json() if cell_stop else None
        finally:
            walked = [c for c in cells if c.key in records]
            manifest, written = self._finish(walked, progress, records, counts, totals, seen,
                                             t0, started, stop)
        return MapOutcome([manifest["cells"][k] for k in manifest["cell_order"]],
                          counts["reader"], round(self.clock() - t0, 1), stop, manifest,
                          written, manifest["resume_command"])
```

`_manifest`'s `flags` block records what this run was:

```python
            "flags": {"window": self.window, "threshold": self.threshold,
                      "depth_column": self.depth_column,
                      "max_units": self.caps.max_units,
                      "max_wall_seconds": self.caps.max_wall_seconds,
                      # D4, recorded by the runner rather than by the CLI so it cannot be
                      # forgotten by a caller that builds a MapRunner directly.
                      "case_budget": self.caps.case_budget,
                      "order": "global" if self.global_order is not None else "cell",
                      **self.flags},
```

Export `build_budget_cells`, `global_batch_order` and `default_max_units_for_budget` from
`corpus_engine/mapper/__init__.py`.

- [ ] **Step 5: `--case-budget` in `tools/map_reader.py`**

Add the flag:

```python
    ap.add_argument("--case-budget", type=int, default=None,
                    help="D4: read at most N cases, spent top-down on the GLOBAL rank order "
                         "across every cell rather than cell by cell. Per-cell caps are not "
                         "used (the manifest records cap: none); the yield floor still stops "
                         "a cell that has stopped paying. The ceiling is checked between "
                         "batches, so a run overshoots by at most one batch.")
```

and in `main`, replacing the single `build_cells` call:

```python
    if a.case_budget is not None and a.case_budget < 1:
        sys.exit(f"--case-budget {a.case_budget} reads nothing; pass 1 or more, or omit it")
    batches = load_batches(batches_dir)
    if a.case_budget is not None:
        cells = build_budget_cells(batches)
        order = global_batch_order(batches)
    else:
        cells = build_cells(batches, era_depth=DEPTH_COLUMNS[a.depth_column])
        order = None
```

The default unit ceiling and the log line follow the budget when there is one:

```python
    if a.case_budget is not None:
        default_units = default_max_units_for_budget(a.case_budget, dom.sharding.batch_size)
    elif retry_ids is not None:
        default_units = sum(len(v) for v in retry_ids.values())
    else:
        default_units = default_max_units(cells)
    caps = RunnerCaps(max_units=a.max_units if a.max_units is not None else default_units,
                      max_wall_seconds=a.max_wall_seconds, case_budget=a.case_budget)
    budget_note = f", case budget {a.case_budget} in global rank order" if a.case_budget else ""
    log(f"{len(cells)} cells, {sum(c.cap_batches for c in cells)} walkable batches{budget_note}, "
        f"caps: {caps.max_units} reader units (+2 worst case, see --help) / "
        f"{caps.max_wall_seconds:.0f} s")
```

Pass `global_order=order` to `MapRunner(...)` and add `"case_budget": a.case_budget` to the
`flags={...}` dict is **not** needed — the runner writes it. `--case-budget` and `--retry-lost`
are mutually exclusive; refuse the combination with the same shape the tool already uses for
`--retry-lost --dry-run-batches`:

```python
    if a.retry_lost and a.case_budget is not None:
        sys.exit("--retry-lost re-reads the cases the map lost, which the budget does not "
                 "govern; run it without --case-budget")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_mapper_cells.py tests/test_mapper_runner.py tests/test_mapper_yield.py tests/test_mapper_screen.py tests/test_map_reader_tool.py tests/test_mapper_admit.py`
Expected: PASS. Then the whole suite.

- [ ] **Step 7: Commit**

```bash
git add corpus_engine/mapper/cells.py corpus_engine/mapper/runner.py corpus_engine/mapper/__init__.py tools/map_reader.py tests/test_mapper_cells.py tests/test_mapper_runner.py tests/test_map_reader_tool.py
git commit -m "mapper: --case-budget walks the global rank order under a fixed case budget

build_budget_cells / global_batch_order give an uncapped cell set and one
pool-wide order; RunnerCaps gains case_budget and MapRunner a _run_budget
walk beside the untouched cell-major one. The manifest records the budget,
the order, and cap: none per cell.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 6: The cycles 1–3 re-read and its admission (spec section 6, D7/D8)

Re-read the 693 relevant records of cycles 001–003 under mapper-v3 so the oldest records carry
the same fields as cycle 004, and admit the result as fills and replacements — never as an
overwrite of a human decision.

Two things the spec leaves to the plan, both forced by how the fold works:

1. **The re-admit body must carry the record forward.** `apply_patch`'s `admit` op replaces the
   whole record. A body holding only the re-read's identity, relevance and quotes would wipe
   every judged value the record already has, human decisions included. So the body is the
   ledger's current judged values plus the re-read's identity, quotes and gate notes, with
   `relevant` taken from the ledger. T1's rule makes the reviewer-held values in that body
   value-identical no-ops; the per-field `set` patches that follow are what actually change
   anything.
2. **"18-case units in case-id order" means in case-id order within a cell.** A batch carries
   one `era_partition` and one `jurisdiction` — `render_unit` puts them in the prompt header
   and `_unit_for` reads them as scalars — so a unit spanning two cells would be a prompt that
   lies about what it holds. Cases are grouped by cell, then ordered by case id inside it.

**Files:**
- Create: `tools/reread_records.py`, `tests/test_reread_records.py`
- Modify: `corpus_engine/mapper/admit.py`, `corpus_engine/mapper/__init__.py`, `tools/admit_map.py`
- Test: `tests/test_mapper_admit.py`

**Interfaces:**
- Consumes: `LedgerView.provenance()` (T1); `Cell(..., uncapped=True)` (T5); `store.case_partitions` (T2); `MapRunner`, `RunnerCaps`, `BatchSource`, `load_batches`, `records_from_manifest`, `basis_for`, `IDENTITY_FIELDS`, `MAPPER_FIELDS`, `AdmittedRecord`, `FLAG_PREFIX`.
- Produces (T7 and T8 consume exactly these):
  - `tools/reread_records.py`: `RUN_ID = "cycles-001-003-reread"`, `NO_YIELD_STOP = -1`, `relevant_case_ids(view, cycles=("cycle-001","cycle-002","cycle-003")) -> list[int]`, `plan_batches(case_ids, meta, *, run_id, size=18) -> list[dict]`, `reread_cells(batches) -> list[Cell]`, `build_parser()`, `main(argv=None) -> int`
  - `runs/cycles-001-003-reread/case-ids.json`: `{"run_id", "cycles", "as_of", "case_ids"}`
  - `runs/cycles-001-003-reread/map-manifest.json` — the same `map-manifest-v1` document the map writes, with `flags.order == "cell"`, `flags.threshold == -1`, every cell `"cap": "none"`
  - `corpus_engine.mapper.admit.REREAD_WHY = "cycles 001-003 re-read"`
  - `corpus_engine.mapper.admit.RereadOutcome(patches: list[Patch], conflicts: list[dict], counts: dict)`
  - `corpus_engine.mapper.admit.reread_patches(admitted, *, manifest, view) -> RereadOutcome`
  - `counts` shape: `{"records": int, "skipped": [int], "conflicts": int, "relevant_false_conflicts": [int], "by_field": {field: {"fill": int, "replace": int, "agree": int, "conflict": int, "skipped": int}}}`
  - each conflict dict (the shape T7's section-G card is built from): `{"case_id", "field", "human_value", "human_basis", "human_at", "reread_value", "reread_basis", "kind", "cell_key", "batch_id"}` with `kind` in `("value", "relevant_false")`
  - `runs/cycles-001-003-reread/reread-conflicts.json` (a JSON list of those) and `reread-admission.json` (the counts), written by `tools/admit_map.py --reread --apply`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reread_records.py`:

```python
"""Guards on tools/reread_records.py. The planner is pure (ids + a partition map in, batch
documents out) and the read path runs against a ScriptedProvider over the tiny fixture store,
exactly as tests/test_map_reader_tool.py does. Nothing here calls claude or codex."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from corpus_engine.reader.model import ModelPin
from corpus_engine.reader.providers.scripted import ScriptedProvider

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("reread_records", ROOT / "tools" / "reread_records.py")
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


class _View:
    def __init__(self, records):
        class S:
            pass
        self.state = S()
        self.state.order = list(records)
        self.state.records = {c: {"relevant": rel} for c, (rel, _cy) in records.items()}
        self.state.in_file = {c: True for c in records}
        self.state.cycles = {c: cy for c, (_rel, cy) in records.items()}
        self.as_of = 42


def test_the_scope_is_the_relevant_records_of_cycles_one_to_three():
    view = _View({1: (True, "cycle-001"), 2: (False, "cycle-002"),
                  3: (True, "cycle-003"), 4: (True, "cycle-004")})
    assert rr.relevant_case_ids(view) == [1, 3]


def test_batches_are_eighteen_cases_in_case_id_order_within_a_cell():
    ids = list(range(1, 41))
    meta = {c: (("pre-1860", "N.Y.") if c <= 20 else ("1930-1970", "Pa.")) for c in ids}
    batches = rr.plan_batches(ids, meta, run_id="cycles-001-003-reread")
    assert [b["batch_id"] for b in batches] == [f"cycles-001-003-reread-batch-{n:03d}"
                                                for n in (1, 2, 3, 4)]
    assert [len(b["cases"]) for b in batches] == [18, 2, 18, 2]
    assert {(b["era_partition"], b["jurisdiction"]) for b in batches} == {
        ("1930-1970", "Pa."), ("pre-1860", "N.Y.")}
    for b in batches:                         # homogeneous, ordered, no signals to show
        assert all(c["era_partition"] == b["era_partition"] for c in b["cases"])
        assert [c["case_id"] for c in b["cases"]] == sorted(c["case_id"] for c in b["cases"])
        assert all(c["signals"] == [] for c in b["cases"])


def test_a_case_with_no_store_row_is_left_out_of_the_plan():
    batches = rr.plan_batches([1, 2], {1: ("pre-1860", "N.Y.")}, run_id="r")
    assert [c["case_id"] for b in batches for c in b["cases"]] == [1]


def test_the_cells_are_uncapped_and_the_yield_floor_never_fires():
    batches = rr.plan_batches(list(range(1, 41)),
                              {c: ("pre-1860", "N.Y.") for c in range(1, 41)}, run_id="r")
    cells = rr.reread_cells(batches)
    assert len(cells) == 1 and cells[0].uncapped is True
    assert cells[0].cap_batches == len(cells[0].batch_ids) == 3
    # NO_YIELD_STOP is what the runner is given: a relevant-accepted count is never negative,
    # so `got <= threshold` can never be true. Every one of the 693 records is read.
    assert rr.NO_YIELD_STOP == -1


def test_plan_writes_the_case_id_list_and_the_batches_and_buys_nothing(tmp_path, monkeypatch,
                                                                      fixture_db, repo_root):
    """--plan is offline: the ledger view and one SELECT, no provider constructed at all."""
    conn = _fixture_conn(tmp_path, fixture_db)          # see the fixture below
    ids = [r[0] for r in conn.execute(
        "SELECT case_id FROM cases WHERE is_duplicate_of IS NULL ORDER BY case_id LIMIT 5")]
    view = _View({c: (True, "cycle-001") for c in ids})
    monkeypatch.setattr(rr, "ROOT", tmp_path)
    monkeypatch.setattr(rr, "open_ledger", lambda **kw: type("L", (), {"view": lambda s: view})())
    monkeypatch.setattr(rr.store, "connect", lambda *a, **kw: conn)
    monkeypatch.setattr(rr, "provider_for", lambda cand: pytest.fail("--plan bought something"))
    assert rr.main(["--plan"]) == 0
    doc = json.loads((tmp_path / "runs" / rr.RUN_ID / "case-ids.json").read_text(encoding="utf-8"))
    assert doc["case_ids"] == sorted(ids) and doc["run_id"] == rr.RUN_ID
    assert doc["cycles"] == ["cycle-001", "cycle-002", "cycle-003"] and doc["as_of"] == 42
    assert len(list((tmp_path / "runs" / rr.RUN_ID / "batches").glob("batch-*.json"))) == 1


def test_the_read_walks_every_planned_batch_and_writes_the_manifest(wired_reread):
    assert rr.main([]) == 0
    doc = json.loads(wired_reread["manifest"].read_text(encoding="utf-8"))
    assert doc["run_id"] == rr.RUN_ID and doc["stop"] == "done"
    assert doc["flags"]["threshold"] == rr.NO_YIELD_STOP
    assert all(c["cap"] == "none" for c in doc["cells"].values())
    assert doc["totals"]["batches_completed"] == doc["totals"]["batches_attempted"]
    assert doc["codebook_id"] == "mapper-v3"
```

`_fixture_conn` and `wired_reread` mirror `tests/test_map_reader_tool.py`'s `wired` fixture:
copy `fixture_db` under `tmp_path/data/db/corpus.db`, monkeypatch `rr.ROOT`, `rr.provider_for`
and `rr.CodexCliProvider`, and pre-write a planned pool under `tmp_path/runs/<RUN_ID>/batches`.

Append to `tests/test_mapper_admit.py`:

```python
from corpus_engine.mapper.admit import REREAD_WHY, reread_patches


class _RereadView:
    """The slice of LedgerView `reread_patches` uses: the records and their provenance."""

    def __init__(self, records, provenance, history=()):
        class S:
            pass
        self.state = S(); self.state.records = dict(records)
        self._prov = dict(provenance); self.patches = list(history)

    def provenance(self, cid):
        return dict(self._prov.get(cid, {}))

    def history(self, cid):
        return [p for p in self.patches if p.case_id == cid]


def _reread(record):
    return AdmittedRecord(record["case_id"], "pre-1860|N.Y.", "b1", "key", record, "")


def test_a_reread_fills_an_empty_field_and_replaces_a_reader_value():
    view = _RereadView({7: {"case_id": 7, "relevant": True, "polarity": "favorable",
                            "under_thirty_days": None}},
                       {7: {"polarity": "reader"}})
    out = reread_patches([_reread({"case_id": 7, "relevant": True, "polarity": "adverse",
                                   "under_thirty_days": "yes", "quotes": []})],
                         manifest=MANIFEST, view=view)
    sets = {(p.field, p.new) for p in out.patches if p.op == "set"}
    assert ("polarity", "adverse") in sets and ("under_thirty_days", "yes") in sets
    assert out.counts["by_field"]["polarity"]["replace"] == 1
    assert out.counts["by_field"]["under_thirty_days"]["fill"] == 1
    assert out.conflicts == []


def test_a_reread_never_touches_a_reviewer_value_and_cards_the_disagreement():
    view = _RereadView({7: {"case_id": 7, "relevant": True, "polarity": "favorable"}},
                       {7: {"polarity": "human"}},
                       history=[Patch(7, "set", "polarity", "favorable", "round 1",
                                      Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1"),
                                      seq=900)])
    out = reread_patches([_reread({"case_id": 7, "relevant": True, "polarity": "adverse",
                                   "quotes": []})], manifest=MANIFEST, view=view)
    assert not [p for p in out.patches if p.op == "set" and p.field == "polarity"]
    assert out.conflicts == [{"case_id": 7, "field": "polarity", "human_value": "favorable",
                              "human_basis": {"reviewer": "mmaldo2",
                                              "run_id": "map-cycle-004-round-1"},
                              "human_at": 900, "reread_value": "adverse",
                              "reread_basis": basis_for(MANIFEST).to_json(), "kind": "value",
                              "cell_key": "pre-1860|N.Y.", "batch_id": "b1"}]
    assert out.counts["by_field"]["polarity"]["conflict"] == 1
    flags = [p for p in out.patches if p.op == "append" and p.field == "review.flags"]
    assert [p.new for p in flags] == ["needs-review:polarity"]
    assert any(p.op == "append" and p.field == "review.notes" and "stands" in p.new
               for p in out.patches)


def test_a_reread_agreeing_with_a_reviewer_writes_nothing_and_is_counted_as_agreement():
    view = _RereadView({7: {"case_id": 7, "relevant": True, "polarity": "favorable"}},
                       {7: {"polarity": "human"}})
    out = reread_patches([_reread({"case_id": 7, "relevant": True, "polarity": "favorable",
                                   "quotes": []})], manifest=MANIFEST, view=view)
    assert out.conflicts == [] and out.counts["by_field"]["polarity"]["agree"] == 1


def test_a_reread_relevant_false_on_a_human_judged_record_is_a_conflict_never_an_overturn():
    view = _RereadView({7: {"case_id": 7, "relevant": True}}, {7: {"relevant": "human"}})
    out = reread_patches([_reread({"case_id": 7, "relevant": False, "quotes": []})],
                         manifest=MANIFEST, view=view)
    assert not [p for p in out.patches if p.op == "set" and p.field == "relevant"]
    assert out.conflicts[0]["kind"] == "relevant_false"
    assert out.counts["relevant_false_conflicts"] == [7]
    admit = next(p for p in out.patches if p.op == "admit")
    assert admit.new["relevant"] is True             # the ledger's relevance, not the re-read's


def test_the_re_admit_body_carries_every_judged_value_forward():
    """`apply_patch`'s admit REPLACES the record. A body that named only the re-read's own
    fields would wipe the values the record already carries, human decisions included."""
    view = _RereadView({7: {"case_id": 7, "relevant": True, "polarity": "favorable",
                            "who_was_letting": "householder", "holding_summary": "h"}},
                       {7: {"polarity": "human", "who_was_letting": "reader"}})
    out = reread_patches([_reread({"case_id": 7, "relevant": True, "polarity": "adverse",
                                   "cite": "9 X 9", "quotes": [{"text": "q"}]})],
                         manifest=MANIFEST, view=view)
    admit = next(p for p in out.patches if p.op == "admit")
    assert admit.new["polarity"] == "favorable"      # the reviewer's value, carried through
    assert admit.new["who_was_letting"] == "householder"
    assert admit.new["holding_summary"] == "h"
    assert admit.new["cite"] == "9 X 9" and admit.new["quotes"] == [{"text": "q"}]
    assert admit.basis.prompt_version.startswith("mapper-v3:")


def test_a_reread_of_a_case_the_ledger_does_not_hold_is_skipped():
    out = reread_patches([_reread({"case_id": 99, "relevant": True, "quotes": []})],
                         manifest=MANIFEST, view=_RereadView({}, {}))
    assert out.patches == [] and out.counts["skipped"] == [99]
```

`MANIFEST` is the module-level mapper-v3 manifest stub the file already uses for `basis_for`;
reuse it rather than writing a second one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_reread_records.py tests/test_mapper_admit.py`
Expected: FAIL — the tool module does not exist; `ImportError: cannot import name 'reread_patches'`.

- [ ] **Step 3: `reread_patches` in `corpus_engine/mapper/admit.py`**

```python
REREAD_WHY = "cycles 001-003 re-read"
# The two kinds of disagreement a re-read can have with a human decision. Both become section-G
# cards (spec section 7); neither ever becomes a value change.
CONFLICT_VALUE, CONFLICT_RELEVANT = "value", "relevant_false"


@dataclass(frozen=True)
class RereadOutcome:
    patches: list
    conflicts: list
    counts: dict


def _human_decision(view, case_id: int, field: str) -> tuple[dict, int]:
    """(basis, seq) of the reviewer patch a conflict is against - the LAST reviewer `set` on
    that field. The card has to name the decision it is asking the reviewer to revisit, and
    "some human, at some point" is not a thing a reviewer can check."""
    last = None
    for p in view.history(case_id):
        if p.basis.reviewer and p.op == "set" and p.field == field:
            last = p
    return (last.basis.to_json(), int(last.seq)) if last is not None else ({}, 0)


def reread_patches(admitted, *, manifest: Mapping, view) -> RereadOutcome:
    """A re-read of records the ledger already holds, as patches, conflicts and counts (D7).

    Per record: one re-admit under mapper-v3, which moves the record onto the six-field quote
    support rule (`fold.supported_fields`), then per field fill / replace / agree / conflict.

    The re-admit body is the ledger's own judged values plus the re-read's identity, quotes and
    gate notes, and `relevant` is the LEDGER's. That is not belt and braces: `apply_patch`'s
    `admit` op replaces the whole record, so a body naming only the re-read's fields would wipe
    every value the record already carries - reviewer decisions included. The values carried
    through are value-identical writes, which the fold treats as no-ops (D2), so nothing about
    provenance moves.

    A field whose provenance is `human` is never written. If the re-read agrees, that is an
    agreement; if it differs, the tool records a conflict, flags the field and writes a note,
    and emits NO set - it does not emit a patch for the fold to reject, because a rejected
    patch is still a line in an append-only log that every later replay has to re-reject."""
    basis = basis_for(manifest)
    reread_basis = basis.to_json()
    cell_order = manifest.get("cell_order") or list(manifest.get("cells") or {})
    order = {k: i for i, k in enumerate(cell_order)}
    out: list[Patch] = []
    conflicts: list[dict] = []
    skipped: list[int] = []
    relevant_false: list[int] = []
    by_field: dict[str, dict] = {}

    def count(field: str, kind: str) -> None:
        row = by_field.setdefault(field, {"fill": 0, "replace": 0, "agree": 0, "conflict": 0,
                                          "skipped": 0})
        row[kind] += 1

    def conflict(a, field, human_value, reread_value, kind) -> None:
        human_basis, human_at = _human_decision(view, a.case_id, field)
        conflicts.append({"case_id": int(a.case_id), "field": field,
                          "human_value": human_value, "human_basis": human_basis,
                          "human_at": human_at, "reread_value": reread_value,
                          "reread_basis": reread_basis, "kind": kind,
                          "cell_key": a.cell_key, "batch_id": a.batch_id})
        count(field, "conflict")

    for a in sorted(admitted, key=lambda a: (order.get(a.cell_key, len(order)), a.cell_key,
                                             a.case_id)):
        rec = view.state.records.get(a.case_id)
        if rec is None:
            skipped.append(int(a.case_id))      # a re-read admits nothing the ledger lacks
            continue
        new = a.record
        note = f"cache {a.cache_key}; batch {a.batch_id}; cell {a.cell_key}"
        if new.get("relevant") is False and rec.get("relevant") is True:
            # D7: never an overturn. Even where the standing relevance is a reader's, the
            # record is in the corpus and taking it out is a human decision, not a re-read's.
            conflict(a, "relevant", rec.get("relevant"), False, CONFLICT_RELEVANT)
            relevant_false.append(int(a.case_id))
        body = {f: rec.get(f) for f in JUDGED_DEFAULT if f in rec}
        body.update({f: new[f] for f in IDENTITY_FIELDS if f in new})
        body["case_id"] = int(a.case_id)
        body["relevant"] = rec.get("relevant")
        out.append(Patch(a.case_id, "admit", "", body, f"{REREAD_WHY}: re-admit under "
                         f"{CODEBOOK_ID}", basis, cycle=str(manifest.get("cycle") or ""),
                         note=note))
        for field in MAPPER_FIELDS:
            value = new.get(field)
            current = rec.get(field)
            if view.provenance(a.case_id).get(field) == "human":
                if value is None or value == "" or value == [] or value == current:
                    count(field, "agree" if value == current else "skipped")
                else:
                    conflict(a, field, current, value, CONFLICT_VALUE)
                continue
            if value is None or value == "" or value == []:
                count(field, "skipped")
            elif current is None:
                out.append(Patch(a.case_id, "set", field, value, f"{REREAD_WHY}: {field} filled",
                                 basis))
                count(field, "fill")
            elif value == current:
                count(field, "agree")
            else:
                out.append(Patch(a.case_id, "set", field, value,
                                 f"{REREAD_WHY}: {field} replaced", basis))
                count(field, "replace")
        for c in [c for c in conflicts if c["case_id"] == int(a.case_id)]:
            out.append(Patch(a.case_id, "append", "review.flags",
                             f"{FLAG_PREFIX}{c['field']}", f"{REREAD_WHY}: {c['field']}", basis))
            out.append(Patch(a.case_id, "append", "review.notes",
                             f"{REREAD_WHY}: the re-read read {c['field']} as "
                             f"{c['reread_value']!r}; the reviewer's {c['human_value']!r} "
                             f"stands and the disagreement is queued as a review card",
                             f"{REREAD_WHY}: {c['field']}", basis))
    counts = {"records": len(admitted) - len(skipped), "skipped": skipped,
              "conflicts": len(conflicts), "relevant_false_conflicts": relevant_false,
              "by_field": by_field}
    return RereadOutcome(out, conflicts, counts)
```

Import what it needs at the top of `admit.py`:
`from corpus_engine.ledger.fold import FLAG_PREFIX, JUDGED_DEFAULT`.

- [ ] **Step 4: `--reread` in `tools/admit_map.py`**

Add the flag and the branch. Everything else — the codebook check, the duplicate-run guard, the
`--dry-run` / `--apply` split, the before/after counts — is unchanged:

```python
    ap.add_argument("--reread", action="store_true",
                    help="admit a RE-READ of records the ledger already holds (spec section 6): "
                         "one re-admit under mapper-v3 per record, then per field fill when the "
                         "value is empty, replace when it is a reader's or a rule's, and a "
                         "CONFLICT CARD when it is a reviewer's. Never overwrites a human "
                         "decision and never overturns relevance.")
```

```python
    if a.reread:
        outcome = reread_patches(admitted, manifest=manifest, view=head)
        patches, conflicts, counts = outcome.patches, outcome.conflicts, outcome.counts
        print(f"{counts['records']} records re-read, {len(patches)} patches, "
              f"{counts['conflicts']} conflicts "
              f"({len(counts['relevant_false_conflicts'])} of them relevance)", flush=True)
        for field in sorted(counts["by_field"]):
            row = counts["by_field"][field]
            print(f"  {field}: fill {row['fill']}, replace {row['replace']}, "
                  f"agree {row['agree']}, conflict {row['conflict']}, "
                  f"skipped {row['skipped']}", flush=True)
    else:
        patches = patches_for(admitted, manifest=manifest)
```

and, on the `--apply` path only, after `led.apply(...)` succeeds:

```python
    if a.reread:
        # The queue's input (spec section 7). Written after the apply, not before: a conflict
        # file naming decisions that were never written would put cards in front of the user
        # for a round that does not exist.
        _write_json(run_dir / "reread-conflicts.json", conflicts)
        _write_json(run_dir / "reread-admission.json", {"run_id": run_id, **counts})
        print(f"conflicts -> {run_dir / 'reread-conflicts.json'} "
              f"({len(conflicts)} cards for section G)", flush=True)
```

with a two-line helper beside `_summary`:

```python
def _write_json(path: Path, doc) -> None:
    """LF, UTF-8, one trailing newline - explicit bytes, like every other artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
```

- [ ] **Step 5: Write `tools/reread_records.py`**

```python
r"""Re-read the relevant records of cycles 001-003 under mapper-v3 (spec section 6, D7/D8).

Two invocations, and only one of them costs anything:

  .venv\Scripts\python tools\reread_records.py --plan          # offline: the ids and the pool
  .venv\Scripts\python tools\reread_records.py --dry-run-batches 2
  .venv\Scripts\python tools\reread_records.py --max-wall-seconds 21600

`--plan` reads the ledger view and one SELECT and writes `case-ids.json` plus the batch files;
it constructs no provider. The read walks those batches through the SAME `MapRunner`, `Reader`,
response cache and Codex checker sample the map uses, so the manifest it writes is a
`map-manifest-v1` document and `tools/admit_map.py --reread` can re-derive every record from
the cache offline. Re-running the same command is how a re-read is resumed.

The cells are uncapped and the yield floor is switched off (`--threshold -1`): every one of the
693 records is already known relevant, so a quiet unit is not evidence that a cell has stopped
paying, and stopping early would leave old records short of the mapper-v3 fields this exists to
fill.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpus_engine import store                                                     # noqa: E402
from corpus_engine.domain import load_domain                                        # noqa: E402
from corpus_engine.ledger import open_ledger                                        # noqa: E402
from corpus_engine.mapper.cells import BatchSource, Cell, load_batches              # noqa: E402
from corpus_engine.mapper.runner import (DEFAULT_MAX_WALL_SECONDS, MapRunner,       # noqa: E402
                                          RunnerCaps, default_max_units)
from corpus_engine.mapper.yield_stop import WINDOW                                  # noqa: E402
from corpus_engine.reader.cache import ResponseCache                                # noqa: E402
from corpus_engine.reader.codebook import load_codebook                             # noqa: E402
from corpus_engine.reader.driver import Reader                                      # noqa: E402
from corpus_engine.reader.model import ModelPin                                     # noqa: E402
from corpus_engine.reader.providers.codex_cli import CodexCliProvider               # noqa: E402
from corpus_engine.reader.providers.factory import READ_TIMEOUT, provider_for       # noqa: E402
from corpus_engine.reader.sources import StoreCaseSource                            # noqa: E402
from corpus_engine.store import case_partitions                                     # noqa: E402
from corpus_engine.textnorm_version import NORM_VERSION                             # noqa: E402

RUN_ID = "cycles-001-003-reread"
CYCLES = ("cycle-001", "cycle-002", "cycle-003")
STORE_NORM_VERSION = f"v{NORM_VERSION}"
UNIT_SIZE = 18
# `CellProgress.should_stop` fires when the window's relevant-accepted count is <= threshold.
# A count is never negative, so -1 is "never stop on yield" - stated as a constant rather than
# left as a magic argument, because switching the stop rule off is a decision (D7), not a knob.
NO_YIELD_STOP = -1
DRY_RUN_FIELDS = ("unit_id", "status", "cache_hit", "retried", "finish_reason", "status_counts",
                  "dropped_quotes", "nulled_fields", "relevant_accepted", "checker", "error")


def relevant_case_ids(view, cycles=CYCLES) -> list[int]:
    """The re-read scope (D7): every case admitted in those cycles that still stands relevant.
    Irrelevant records are not re-read - there is nothing in them to fill."""
    return sorted(cid for cid in view.state.order
                  if view.state.cycles.get(cid) in cycles
                  and view.state.in_file.get(cid)
                  and view.state.records[cid].get("relevant"))


def plan_batches(case_ids, meta, *, run_id: str, size: int = UNIT_SIZE) -> list[dict]:
    """18-case units, in case-id order, one unit per batch.

    Grouped by CELL first. A batch carries one `era_partition` and one `jurisdiction` -
    `render_unit` puts them in the prompt header and `admit._unit_for` reads them as scalars -
    so a unit spanning two cells would be a prompt that lies about what it holds. A case with
    no live store row (a duplicate marked since it was admitted) is left out; the caller
    compares the planned count against the scope.

    `signals` is empty: a re-read asks about a record the corpus already holds, and there is no
    retrieval provenance to show for it."""
    by_cell: dict[tuple[str, str], list[int]] = {}
    for cid in sorted(case_ids):
        if cid in meta:
            by_cell.setdefault(meta[cid], []).append(int(cid))
    out: list[dict] = []
    n = 0
    for era, jur in sorted(by_cell):
        ids = by_cell[(era, jur)]
        for i in range(0, len(ids), size):
            n += 1
            out.append({"batch_id": f"{run_id}-batch-{n:03d}", "ranker_id": "",
                        "era_partition": era, "jurisdiction": jur,
                        "cases": [{"case_id": c, "era_partition": era, "jurisdiction": jur,
                                   "signals": []} for c in ids[i:i + size]]})
    return out


def reread_cells(batches) -> list[Cell]:
    """One uncapped cell per (era, jurisdiction), in key order. There are no rank scores to
    order by - these records are already in the corpus - so the order is the cell key's, which
    is at least the same on every machine."""
    by_cell: dict[tuple[str, str], list[str]] = {}
    for b in batches:
        by_cell.setdefault((b["era_partition"], b["jurisdiction"]), []).append(b["batch_id"])
    return [Cell(era, jur, tuple(sorted(ids)), len(ids), 0.0, uncapped=True)
            for (era, jur), ids in sorted(by_cell.items())]


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))


def checker_pin(dom) -> ModelPin | None:
    c = dom.reader.checker
    return ModelPin(c["model_id"], c["family"], extra={"cli_model": c["cli_model"]}) if c else None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reread_records.py", description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=RUN_ID)
    ap.add_argument("--plan", action="store_true",
                    help="write case-ids.json and the batch files and stop; buys nothing")
    ap.add_argument("--dry-run-batches", type=int, default=None,
                    help="read the first N batches, print the parse / gate / checker "
                         "diagnostics, and stop")
    ap.add_argument("--max-units", type=int, default=None)
    ap.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    ap.add_argument("--sample-pct", type=int, default=None,
                    help="checker sample percentage (default: domain.yaml's checker_sample_pct)")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.dry_run_batches is not None and a.dry_run_batches < 1:
        sys.exit(f"--dry-run-batches {a.dry_run_batches} buys nothing; pass 1 or more")

    def log(msg):
        print(msg, flush=True)

    dom = load_domain()
    run_dir = ROOT / "runs" / a.run_id
    batches_dir = run_dir / "batches"
    if a.plan:
        view = open_ledger(domain=dom).view()
        ids = relevant_case_ids(view)
        conn = store.connect(ROOT / "data" / "db" / "corpus.db")
        meta = case_partitions(conn, ids)
        batches = plan_batches(ids, meta, run_id=a.run_id)
        write_json(run_dir / "case-ids.json",
                   {"run_id": a.run_id, "cycles": list(CYCLES), "as_of": view.as_of,
                    "case_ids": ids})
        batches_dir.mkdir(parents=True, exist_ok=True)
        for old in batches_dir.glob("batch-*.json"):
            old.unlink()
        for n, b in enumerate(batches, 1):
            write_json(batches_dir / f"batch-{n:03d}.json", b)
        planned = sum(len(b["cases"]) for b in batches)
        log(f"{len(ids)} relevant records in {', '.join(CYCLES)}; {planned} planned into "
            f"{len(batches)} batches over {len(reread_cells(batches))} cells -> {batches_dir}")
        if planned != len(ids):
            log(f"WARNING: {len(ids) - planned} cases have no live store row and are not in "
                f"the pool")
        return 0

    if not batches_dir.is_dir():
        sys.exit(f"no pool to read: {batches_dir} does not exist; run --plan first")
    batches = load_batches(batches_dir)
    cells = reread_cells(batches)
    if a.dry_run_batches is not None:
        first = cells[0]
        cells = [Cell(first.era, first.jurisdiction,
                      first.batch_ids[:a.dry_run_batches], min(a.dry_run_batches,
                                                               first.cap_batches),
                      0.0, uncapped=True)]
        log(f"dry run: its cells are MERGED into {run_dir / 'map-manifest.json'}")

    cb = load_codebook(dom, dom.reader.codebook)
    provider, pin, why = provider_for(dict(dom.reader.model))
    if provider is None:
        sys.exit(f"cannot run the re-read: {why}")
    log(f"reader {pin.label}: {why}")
    checker = CodexCliProvider(dom.reader.checker["cli_model"]) if dom.reader.checker else None
    if checker is not None and not checker.is_available():
        sys.exit("codex cli not available; the checker sample is part of the read (D5)")
    conn = store.connect(ROOT / "data" / "db" / "corpus.db")
    cache = ResponseCache(ROOT / "data" / "reader" / "cache")
    source = StoreCaseSource(conn)
    caps = RunnerCaps(max_units=a.max_units if a.max_units is not None
                      else default_max_units(cells), max_wall_seconds=a.max_wall_seconds)
    log(f"{len(cells)} cells, {sum(c.cap_batches for c in cells)} batches, "
        f"caps: {caps.max_units} reader units / {caps.max_wall_seconds:.0f} s, "
        f"yield stop OFF (threshold {NO_YIELD_STOP})")

    def factory():
        return Reader(provider, source, checker=checker, cache=cache, log=log, domain=dom,
                      store_norm_version=STORE_NORM_VERSION)

    runner = MapRunner(factory, cells, batch_source=BatchSource(batches_dir), cache=cache,
                       manifest_path=run_dir / "map-manifest.json", caps=caps, log=log,
                       codebook=cb, pin=pin,
                       checker_pin=checker_pin(dom) if checker is not None else None,
                       sample_pct=(a.sample_pct if a.sample_pct is not None
                                   else dom.reader.checker_sample_pct),
                       run_id=a.run_id, extractions_dir=run_dir / "extractions",
                       window=WINDOW, threshold=NO_YIELD_STOP, depth_column="0.25",
                       era_depth={}, screen=None, families=dom.reader.families,
                       read_timeout_seconds=READ_TIMEOUT, resume_args=argv,
                       flags={"reread": True, "dry_run_batches": a.dry_run_batches,
                              "sample_pct": (a.sample_pct if a.sample_pct is not None
                                             else dom.reader.checker_sample_pct)})
    try:
        out = runner.run()
    except KeyboardInterrupt:
        log(f"interrupted; the manifest of what was bought is {run_dir / 'map-manifest.json'}")
        return 130
    t = out.manifest["totals"]
    log(f"stop={out.stop} batches={t['batches_completed']} cases={t['cases_read']} "
        f"relevant={t['relevant_accepted']} irrelevant={t['irrelevant_accepted']} "
        f"failed={t['failed_units']} cases_lost={t['cases_lost']} units={out.units} "
        f"checker_units={out.manifest['process']['checker_units']} "
        f"wall={out.wall_seconds:.0f}s")
    if a.dry_run_batches is not None:
        for key in [c.key for c in cells if c.key in out.manifest["cells"]]:
            for unit in out.manifest["cells"][key]["units"]:
                log(json.dumps({f: unit[f] for f in DRY_RUN_FIELDS}, sort_keys=True))
    log(f"resume: {out.resume_command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`MapRunner.resume_command()` spells `tools\map_reader.py`; give `MAP_RESUME_TOOL` a
constructor override (`resume_tool: str = MAP_RESUME_TOOL` on `MapRunner.__init__`, used by
`resume_command`) and pass `resume_tool="tools\\reread_records.py"` here, so the line the tool
prints is the line that resumes it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_reread_records.py tests/test_mapper_admit.py tests/test_map_reader_tool.py`
Expected: PASS. Then the whole suite.

- [ ] **Step 7: Commit**

```bash
git add tools/reread_records.py tools/admit_map.py corpus_engine/mapper/admit.py corpus_engine/mapper/runner.py corpus_engine/mapper/__init__.py tests/test_reread_records.py tests/test_mapper_admit.py
git commit -m "mapper: re-read the cycles 1-3 relevant records and admit them as fills

reread_records.py plans 18-case units per cell over the 693 relevant
records and reads them through the same MapRunner with the yield stop off;
admit_map.py --reread turns that map into a mapper-v3 re-admit that carries
every judged value forward, plus per-field fill / replace / agree, and
writes a conflict card instead of touching a reviewer's value.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 7: Section G — re-read conflicts with a human decision (spec section 7, D9)

A seventh queue section, **placed first**, one card per conflicting field. It shows the human
value, the re-read value, both bases, the quotes and the full opinion text. Its decisions are
`keep` (the default expectation: the human value stands), `set` (the reviewer revises their own
earlier decision, and the note names the one being superseded) and `unsure`. There is no
`adopt`: a section-G card's second opinion is the re-read, not the checker, and it is already
on the card as `reread_value`.

Two rules that differ from A–F and are worth saying out loud:

- **Section G cards are on records that are already human-reviewed.** `select_queue` skips a
  reviewed record for A–F because the round exists to move machine-only records into the human
  tier; a G card exists for the opposite reason, so G is built before that filter.
- **A case may carry more than one G card**, one per conflicting field (spec section 7). The
  "one appearance per record" rule is an A–F rule, and the card key is `(case_id, field)`
  everywhere the round is read back.

**Files:**
- Modify: `corpus_engine/mapper/queue.py`, `corpus_engine/mapper/__init__.py`, `tools/make_map_review.py`, `tools/export_review_cards.py`, `tools/apply_map_review.py`
- Test: `tests/test_mapper_queue.py`, `tests/test_map_review_tools.py`

**Interfaces:**
- Consumes: the conflict dict shape from T6; `LedgerView.conflicts()` / `.history()` from T1; `QueueCard`, `Queue`, `select_queue`, `check_queue` as they stand.
- Produces (T8 consumes exactly these):
  - `SECTIONS` becomes `(("G", "reread_conflict", "Re-read conflicts with a human decision"), ("A", …), …)` — G first
  - `corpus_engine.mapper.queue.CONFLICT_KEYS: tuple` and `CONFLICT_KINDS = ("value", "relevant_false")`
  - `corpus_engine.mapper.queue.conflicts_from_view(view) -> list[dict]` — the fold's own rejected attempts rendered into the same dict shape T6 writes
  - `QueueCard(..., conflict: dict | None = None)`; `QueueCard.decide_field` returns `conflict["field"]` for a G card; `QueueCard.to_json()` gains `"conflict"`
  - `select_queue(view, run_id, *, manifest, cases, cap=QUEUE_CAP, sections=SECTIONS, conflicts=())`
  - `tools/apply_map_review.py`: `card_index(queue_doc) -> dict[tuple[int, str], dict]`, and `patches_for(..., cards: Mapping | None = None)`
  - the exported card gains `"conflict"`; `--full-text-sections` accepts `G`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mapper_queue.py`:

```python
from corpus_engine.mapper.queue import CONFLICT_KEYS, conflicts_from_view

CONFLICT = {"case_id": 70, "field": "polarity", "human_value": "favorable",
            "human_basis": {"reviewer": "mmaldo2", "run_id": "map-cycle-004-round-1"},
            "human_at": 900, "reread_value": "adverse",
            "reread_basis": {"model": "claude-opus-5@claude-cli",
                             "prompt_version": "mapper-v3:f92016681314",
                             "run_id": "cycles-001-003-reread"},
            "kind": "value", "cell_key": "pre-1860|N.Y.", "batch_id": "b1"}


def test_section_g_is_first_and_its_card_decides_the_conflicting_field():
    rec = _rec(70, polarity="favorable")
    q = select_queue(_View([rec], "r", reviewed=[70]), "r", manifest=_manifest([70]),
                     cases=_Cases(), conflicts=[CONFLICT])
    assert [s for s, _k, _t in SECTIONS][0] == "G"
    assert [c.section for c in q.cards] == ["G"]
    card = q.cards[0]
    assert card.decide_field == "polarity" and card.reason == "reread_conflict"
    assert card.to_json()["conflict"] == CONFLICT
    assert set(CONFLICT) == set(CONFLICT_KEYS)
    assert list(q.to_json()["sections"]) [0] == "G"
    assert q.to_json()["titles"]["G"] == "Re-read conflicts with a human decision"


def test_a_reviewed_record_is_queued_for_g_though_it_is_skipped_for_a_to_f():
    """A G card exists BECAUSE a human decided the field; the A-F rule that skips a reviewed
    record would throw away every card the re-read exists to raise."""
    rec = _rec(70, polarity="favorable", under_thirty_days="yes")
    q = select_queue(_View([rec], "r", reviewed=[70]), "r", manifest=_manifest([70]),
                     cases=_Cases(), conflicts=[CONFLICT])
    assert [(c.section, c.case_id) for c in q.cards] == [("G", 70)]     # not also section A


def test_one_card_per_conflicting_field_on_the_same_case():
    second = {**CONFLICT, "field": "who_was_letting", "human_value": "householder",
              "reread_value": "commercial_operator"}
    q = select_queue(_View([_rec(70)], "r", reviewed=[70]), "r", manifest=_manifest([70]),
                     cases=_Cases(), conflicts=[second, CONFLICT])
    assert [(c.case_id, c.decide_field) for c in q.cards] == [(70, "polarity"),
                                                              (70, "who_was_letting")]


def test_g_cards_come_before_every_other_section_under_the_cap():
    recs = [_rec(80, polarity="mixed"), _rec(81, polarity="mixed")]
    q = select_queue(_View(recs, "r"), "r", manifest=_manifest([80, 81]), cases=_Cases(),
                     conflicts=[{**CONFLICT, "case_id": 82}], cap=1)
    assert [c.section for c in q.cards] == ["G"] and q.deferred == (80, 81)


def test_a_conflict_for_a_case_the_ledger_does_not_hold_is_dropped():
    q = select_queue(_View([], "r"), "r", manifest=_manifest([]), cases=_Cases(),
                     conflicts=[CONFLICT])
    assert q.cards == ()


def test_conflicts_from_view_renders_the_folds_rejections_in_the_same_shape():
    """The fold records what it REFUSED; the re-read tool records what it declined to attempt.
    Both are section-G cards, so both arrive in one shape."""
    class _V:
        def conflicts(self):
            return {70: [{"field": "polarity", "attempted": "adverse", "standing": "favorable",
                          "by": CONFLICT["reread_basis"], "at": 901, "op": "set"}]}

        def history(self, cid):
            return [Patch(70, "set", "polarity", "favorable", "round 1",
                          Basis(reviewer="mmaldo2", run_id="map-cycle-004-round-1"), seq=900)]

    rows = conflicts_from_view(_V())
    assert set(rows[0]) == set(CONFLICT_KEYS)
    assert rows[0]["human_value"] == "favorable" and rows[0]["reread_value"] == "adverse"
    assert rows[0]["human_at"] == 900 and rows[0]["kind"] == "value"
```

`_rec`, `_View`, `_Cases` and `_manifest` are the file's existing helpers; `_View` gains a
`reviewed=` argument if it does not already take one (it does — `test_mapper_queue.py` line
~173 uses it).

Append to `tests/test_map_review_tools.py`:

```python
def test_a_section_g_keep_confirms_the_human_value_against_the_reread():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = amr.patches_for([{"case_id": 70, "field": "polarity", "decision": "keep",
                                "value": None, "note": ""}],
                              {70: {"polarity": "favorable"}}, "mmaldo2",
                              run_id="reread-round-1", cards=cards)
    notes = [p.new for p in patches if p.field == "review.notes"]
    assert any("confirmed by the reviewer" in n and "adverse" in n for n in notes)
    assert not [p for p in patches if p.op == "set" and p.field == "polarity"]
    assert any(p.field == "review.status" and p.new == "human-adjudicated" for p in patches)


def test_a_section_g_set_records_that_the_reviewer_revised_their_own_decision():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = amr.patches_for([{"case_id": 70, "field": "polarity", "decision": "set",
                                "value": "adverse", "note": ""}],
                              {70: {"polarity": "favorable"}}, "mmaldo2",
                              run_id="reread-round-1", cards=cards)
    note = next(p.new for p in patches if p.field == "review.notes")
    assert "revises their own earlier decision" in note
    assert "map-cycle-004-round-1" in note and "seq 900" in note and "adverse" in note
    value = next(p for p in patches if p.op == "set" and p.field == "polarity")
    assert value.new == "adverse" and value.basis.reviewer == "mmaldo2"


def test_a_section_g_card_refuses_adopt():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    with pytest.raises(ValueError, match="no checker value to adopt"):
        amr.patches_for([{"case_id": 70, "field": "polarity", "decision": "adopt",
                          "value": None, "note": ""}],
                        {70: {"polarity": "favorable"}}, "mmaldo2", cards=cards)


def test_a_section_g_unsure_leaves_the_record_machine_free_of_a_status_change():
    cards = {(70, "polarity"): {"case_id": 70, "section": "G", "decide_field": "polarity",
                                "conflict": CONFLICT}}
    patches = amr.patches_for([{"case_id": 70, "field": "polarity", "decision": "unsure",
                                "value": None, "note": ""}],
                              {70: {"polarity": "favorable"}}, "mmaldo2", cards=cards)
    assert any(p.field == "review.flags" and p.new == "needs-review:polarity" for p in patches)
    assert not [p for p in patches if p.field == "review.status"]


def test_card_index_keys_on_case_and_field_so_two_g_cards_do_not_collide():
    doc = {"sections": {"G": [{"case_id": 70, "decide_field": "polarity", "section": "G"},
                              {"case_id": 70, "decide_field": "who_was_letting",
                               "section": "G"}]}}
    idx = amr.card_index(doc)
    assert set(idx) == {(70, "polarity"), (70, "who_was_letting")}


def test_the_page_and_the_export_show_the_conflict(tmp_path):
    queue = {"run_id": "cycles-001-003-reread", "cap": 250,
             "titles": {s: t for s, _k, t in SECTIONS},
             "sections": {s: [] for s, _k, _t in SECTIONS},
             "deferred": [], "fuzzy_auto_accepted": []}
    queue["sections"]["G"] = [{"case_id": 70, "section": "G", "reason": "reread_conflict",
                               "other_reasons": [], "decide_field": "polarity",
                               "cite": "1 X 1", "name": "A v B", "court": "c", "jur": "N.Y.",
                               "year": 1880, "values": {"polarity": "favorable"},
                               "holding_summary": "h", "quotes": [], "nulled_fields": [],
                               "extraction_status": "ok", "disagreements": [], "fuzzy": [],
                               "conflict": CONFLICT}]
    html, md, _n = mmr.build_pages(queue, tmp_path / "page")
    text = html.read_text(encoding="utf-8")
    assert "Re-read conflicts with a human decision" in text and "reread_value" not in text
    cards = erc.cards_from_queue(queue, {})
    assert cards[0]["conflict"] == CONFLICT
    body = erc.markdown_for(cards, "cycles-001-003-reread")
    assert "Your earlier decision: polarity = favorable" in body
    assert "The mapper-v3 re-read reads it as: adverse" in body
```

(`amr`, `mmr`, `erc` are the file's existing module handles for `apply_map_review`,
`make_map_review` and `export_review_cards`; `CONFLICT` is the same dict as in
`tests/test_mapper_queue.py` — define it once at the top of each file rather than importing
across test modules.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_mapper_queue.py tests/test_map_review_tools.py`
Expected: FAIL — `ImportError: cannot import name 'CONFLICT_KEYS'`.

- [ ] **Step 3: `corpus_engine/mapper/queue.py`**

```python
SECTIONS = (("G", "reread_conflict", "Re-read conflicts with a human decision"),
            ("A", "favorable_under_thirty", "Favorable and under thirty days"),
            ("B", "householder_nights", "Householder letting by the night"),
            ("C", "checker_disagreement", "Reader / checker disagreement"),
            ("D", "polarity_mixed", "Polarity mixed"),
            ("E", "gate_erased", "Judged fields erased by the quote gate"),
            ("F", "fuzzy_quote", "Fuzzy quote match"))
# The dict a section-G card is built from. ONE shape, two producers: what
# `tools/admit_map.py --reread` writes to runs/<run-id>/reread-conflicts.json, and what
# `conflicts_from_view` renders the fold's own rejected attempts into.
CONFLICT_KEYS = ("case_id", "field", "human_value", "human_basis", "human_at",
                 "reread_value", "reread_basis", "kind", "cell_key", "batch_id")
CONFLICT_KINDS = ("value", "relevant_false")
```

```python
def conflicts_from_view(view) -> list[dict]:
    """The fold's own rejected writes, as section-G cards (D2, spec section 3).

    Belt to `reread-conflicts.json`'s braces. The re-read tool declines to EMIT a patch the
    fold would reject, so in the ordinary case this returns nothing; anything it does return is
    a write some other path attempted and the ledger refused, and that is exactly the thing
    that must not disappear silently."""
    out = []
    for case_id, rows in sorted(view.conflicts().items()):
        for row in rows:
            field = row["field"]
            human_basis, human_at = {}, 0
            for p in view.history(case_id):
                if p.basis.reviewer and p.op == "set" and p.field == field:
                    human_basis, human_at = p.basis.to_json(), int(p.seq)
            out.append({"case_id": int(case_id), "field": field,
                        "human_value": row.get("standing"), "human_basis": human_basis,
                        "human_at": human_at, "reread_value": row.get("attempted"),
                        "reread_basis": row.get("by") or {},
                        "kind": "relevant_false" if field == "relevant" else "value",
                        "cell_key": "", "batch_id": ""})
    return out
```

`QueueCard` gains a final defaulted field and two small changes:

```python
    # The re-read disagreement this card exists for (section G only), in `CONFLICT_KEYS`
    # shape. A plain dict, not a dataclass: it is read from a JSON file, rendered into a page
    # and read back out of the queue manifest, and one shape through all three is worth more
    # than a type.
    conflict: dict | None = None

    @property
    def decide_field(self) -> str:
        if self.reason == "reread_conflict":
            return str((self.conflict or {}).get("field") or "polarity")
        ...                                   # the existing branches, unchanged
```

and `to_json()` gains `"conflict": dict(self.conflict) if self.conflict else None`.

`select_queue` gains the parameter and the G pass, before the A–F loop:

```python
def select_queue(view, run_id: str, *, manifest: Mapping, cases, cap: int = QUEUE_CAP,
                 sections=SECTIONS, conflicts: Sequence[Mapping] = ()) -> Queue:
    ...
    cards: list[QueueCard] = []
    # Section G first, and BEFORE the reviewed filter below: a G card exists precisely because
    # a human decided the field, so the A-F rule that skips a reviewed record would throw away
    # every card the re-read exists to raise. One card per conflicting FIELD (spec section 7),
    # so a case with two disagreements gets two cards - the only place the "one appearance per
    # record" rule does not hold.
    for c in sorted(conflicts, key=lambda c: (int(c["case_id"]), str(c["field"]))):
        rec = view.state.records.get(int(c["case_id"]))
        if rec is None:
            continue
        cards.append(QueueCard(int(c["case_id"]), "G", "reread_conflict", (), rec, (), (),
                               conflict=dict(c)))
    ...                                       # the existing A-F loop appends to `cards`
    order = {key: i for i, (_s, key, _t) in enumerate(sections)}
    cards.sort(key=lambda c: (order[c.reason], c.case_id, c.decide_field))
    return Queue(run_id, tuple(cards[:cap]), tuple(c.case_id for c in cards[cap:]), cap,
                 tuple(accepted))
```

Export `CONFLICT_KEYS`, `CONFLICT_KINDS` and `conflicts_from_view` from
`corpus_engine/mapper/__init__.py`.

- [ ] **Step 4: The page — `tools/make_map_review.py`**

`cards_from_doc` carries the conflict through so a `--check` pass over a G round rebuilds the
same card:

```python
            cards.append(QueueCard(int(c["case_id"]), sec, c["reason"],
                                   tuple(c.get("other_reasons") or ()), record,
                                   tuple(c.get("disagreements") or ()),
                                   tuple(c.get("fuzzy") or ()),
                                   conflict=c.get("conflict")))
```

In `CONTENT_TMPL`'s card renderer, after the `nulled` block, add:

```javascript
  const cf = it.conflict;
  const conflict = cf ? `<div class="warn">A mapper-v3 re-read disagrees with a decision you
       already made. Your <b>${esc(cf.field)}</b> is <code>${esc(show(cf.human_value))}</code>
       (${esc(String((cf.human_basis || {}).reviewer || 'reviewer'))}, run
       ${esc(String((cf.human_basis || {}).run_id || '?'))}); the re-read reads
       <code>${esc(show(cf.reread_value))}</code>. Your value stands unless you change it
       here.</div>` : '';
```

interpolate `${conflict}` on the line after `${nulled}`, and suppress the adopt row on a G
card, because its second opinion is the re-read and it is already on the card:

```javascript
  const adoptRow = (sec === 'G' || cv === undefined) ? ''
    : `<label><input type="radio" name="d-${k}" value="adopt"> Adopt checker value <code>${esc(show(cv))}</code></label>`;
```

- [ ] **Step 5: The export — `tools/export_review_cards.py`**

In `cards_from_queue`, add one key to the emitted dict:

```python
                "conflict": c.get("conflict"),
```

and in `markdown_for`, after the `nulled_fields` line:

```python
        if c.get("conflict"):
            cf = c["conflict"]
            lines.append(f"- **Your earlier decision: {cf['field']} = {_fmt(cf['human_value'])}**"
                         f" ({(cf.get('human_basis') or {}).get('reviewer') or 'reviewer'}, run "
                         f"{(cf.get('human_basis') or {}).get('run_id') or '?'}, seq "
                         f"{cf.get('human_at')})")
            lines.append(f"- **The mapper-v3 re-read reads it as: {_fmt(cf['reread_value'])}**"
                         + (" (and reads the case as NOT a letting case at all)"
                            if cf.get("kind") == "relevant_false" else ""))
            lines.append("- Decide: keep (your value stands - the default), set (you revise "
                         "your own earlier decision), or unsure.")
```

`--full-text-sections` needs no code change (it splits on commas and matches the card's
`section`), but T8 passes `G,C,D` so every conflict card carries the opinion text — spec
section 7 requires full text on every card in these rounds.

- [ ] **Step 6: The apply — `tools/apply_map_review.py`**

Add the index helper beside `check_against_queue`:

```python
def card_index(queue_doc: Mapping) -> dict[tuple[int, str], dict]:
    """(case_id, decide_field) -> the card the round queued.

    Keyed on the FIELD as well as the case because section G queues one card per conflicting
    field, so a case can carry two cards and a case-only key would silently drop one."""
    out: dict[tuple[int, str], dict] = {}
    for cards in (queue_doc.get("sections") or {}).values():
        for c in cards or ():
            out[(int(c["case_id"]), str(c["decide_field"]))] = dict(c)
    return out
```

`check_against_queue` keeps working unchanged (it already builds `{case_id: decide_field}`);
change its map to accept either of a case's G fields:

```python
    decide_fields: dict[int, set] = {}
    for cards in (queue_doc.get("sections") or {}).values():
        for c in cards or ():
            decide_fields.setdefault(int(c["case_id"]), set()).add(str(c["decide_field"]))
    errors = []
    for d in decisions:
        cid, field = d["case_id"], d["field"]
        want = decide_fields.get(cid)
        if want is None:
            errors.append(f"case {cid}: not a card in the round's queue manifest")
        elif field not in want and field != "relevant":
            errors.append(f"case {cid}: this round's cards decide "
                          f"{', '.join(sorted(repr(w) for w in want))}, not {field!r}")
```

`patches_for` gains `cards: Mapping | None = None` and one branch, placed immediately after the
`relevant` overturn branch so a G card can still be overturned to irrelevant by the generic
path if that is genuinely what the reviewer means:

```python
        card = (cards or {}).get((cid, field)) or {}
        if card.get("section") == "G":
            # Spec section 7. The re-read disagreed with a decision this reviewer already made.
            # `keep` is the default expectation and writes no value; `set` is the reviewer
            # revising their OWN earlier decision, and the note names the decision it
            # supersedes so the ledger records a revision rather than a fresh opinion; `unsure`
            # takes the ordinary flag path. There is no `adopt`: this card's second opinion is
            # the re-read, and it is on the card.
            conflict = card.get("conflict") or {}
            was = conflict.get("human_basis") or {}
            if decision == "adopt":
                raise ValueError(f"case {cid}: a section-G card has no checker value to adopt "
                                 f"- its second opinion is the re-read's "
                                 f"{conflict.get('reread_value')!r}, already on the card. "
                                 f"Decide keep, set or unsure.")
            if decision == "keep":
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} {old!r} confirmed by the reviewer against "
                                 f"the mapper-v3 re-read's {conflict.get('reread_value')!r}",
                                 why, basis))
                out += arr._clear_flag(live, records, cid, field, why, basis, tag)
            elif decision == "set":
                value = _checked(cid, field, _value(field, d.get("value")))
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} {old!r} -> {value!r}; the reviewer revises "
                                 f"their own earlier decision "
                                 f"({was.get('reviewer') or 'reviewer'}, run "
                                 f"{was.get('run_id') or '?'}, seq {conflict.get('human_at')}) "
                                 f"after the mapper-v3 re-read read it as "
                                 f"{conflict.get('reread_value')!r}", why, basis))
                out.append(Patch(cid, "set", field, value, why, basis))
                out += arr._clear_flag(live, records, cid, field, why, basis, tag)
            else:                                                   # unsure
                out.append(Patch(cid, "append", "review.flags", f"{FLAG_PREFIX}{field}", why,
                                 basis))
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: {field} left unsure by the reviewer; the human value "
                                 f"stands and the re-read's "
                                 f"{conflict.get('reread_value')!r} waits for a full read",
                                 why, basis))
                live.setdefault(cid, arr._live_flags(records, cid)).append(f"{FLAG_PREFIX}{field}")
            if assisted_by:
                out.append(Patch(cid, "append", "review.notes",
                                 f"{tag}: first pass drafted by {assisted_by}; "
                                 + ("left unsure, not confirmed" if decision == "unsure"
                                    else "confirmed by the reviewer"), why, basis))
            if d.get("note"):
                out.append(Patch(cid, "append", "review.notes", f"user note: {d['note']}", why,
                                 basis))
            if decision != "unsure":
                out.append(Patch(cid, "set", "review.status", "human-adjudicated", why, basis))
            continue
```

`main` builds the index whenever it has a queue and passes it through:

```python
    queue_doc = json.loads(Path(a.queue).read_text(encoding="utf-8")) if a.queue and Path(
        a.queue).exists() else {}
    ...
    patches = patches_for(decisions, head.state.records, dom.reviewer_default,
                          run_id=a.run_id, checker=checker, assisted_by=a.assisted_by,
                          cards=card_index(queue_doc))
```

(the `--decisions` path already loads `queue_doc`; hoist that load so `--saved` gets it too,
and keep `check_against_queue` on the `--decisions` path only, as now).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_mapper_queue.py tests/test_map_review_tools.py tests/test_apply_reference_review.py tests/test_make_reference_review.py`
Expected: PASS. Then the whole suite. Every existing section A–F assertion must still pass
byte-for-byte: the G branch is additive and nothing above it moved.

- [ ] **Step 8: Commit**

```bash
git add corpus_engine/mapper/queue.py corpus_engine/mapper/__init__.py tools/make_map_review.py tools/export_review_cards.py tools/apply_map_review.py tests/test_mapper_queue.py tests/test_map_review_tools.py
git commit -m "review: section G - re-read conflicts with a human decision, queued first

One card per conflicting field, built before the reviewed-record filter
because a G card exists because a human decided the field. keep / set /
unsure only; a set is recorded as the reviewer revising their own earlier
decision, with the superseded decision named in the note.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

### Task 8: The live runs, the admissions, the review rounds and the reports

The only task that spends anything. **Every step marked CONTROLLER is gated:** an agent
executing this plan stops, reports what the previous step produced, and waits. It never starts
a live run, never publishes a page, and never invents a decision.

| Step | Spends | What |
| --- | --- | --- |
| 2 | none | build and freeze held-out v2 |
| 3 | none (CPU) | train classifier v2, three-way evaluation, ship rule |
| 5 | none | re-rank the tail into `cycle-004-shard-02` |
| 6 | **subscription** | two-batch dry run of the tail map |
| 8 | **subscription** | the tail-map field run, detached, 3,000 cases |
| 9 | none (writes the ledger) | `admit_map.py --run-id cycle-004-shard-02 --apply` |
| 11 | **subscription** | two-batch dry run of the re-read |
| 13 | **subscription** | the re-read field run, detached, 693 records |
| 14 | none (writes the ledger) | `admit_map.py --run-id cycles-001-003-reread --reread --apply` |
| 16 | **subscription (codex)** | the 100% checker pass over each round's queue (≤250 units) |
| 19 | none (writes the ledger) | `apply_map_review.py` per round |

**Files:**
- Create: `data/eval/ranker-heldout-v2.jsonl`, `data/ranker/v2/{model.npz,manifest.json}`, `runs/cycle-004-shard-02/{shard-manifest.json,map-manifest.json}`, `runs/cycles-001-003-reread/{case-ids.json,map-manifest.json,reread-conflicts.json,reread-admission.json}`, `runs/*/review-round-*.json` + `-checker.json`, `reports/ranking-v2.md`, `reports/map-cycle-004-shard-02.md`, `reports/reread-cycles-001-003.md`, `reports/review-queue-reread.{html,md}`
- Modify: `domains/str-right-to-let/domain.yaml` (`heldout_v2_sha256`; `classifier_version` only if it ships), `reports/handoff-cycle-004.md`, `README.md`, `tests/test_ledger_committed.py` (the pinned counts, after each apply)
- Not created: anything under `runs/*/batches/` or `runs/*/extractions/` stays gitignored.

**Interfaces:**
- Consumes: everything T1–T7 produced.
- Produces: the frozen v2 slice and its pin; the shipped-or-not answer; two tracked map manifests; the re-read conflict file; the published two-tier counts at five points (before the tail map, after its admission, after the re-read admission, after each review round).

- [ ] **Step 1: Pre-flight (free)**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -c "from corpus_engine.ledger import open_ledger; v=open_ledger().view(); print(v.counts().total.as_claim('relevant records')); print('conflicts', len(v.conflicts()))"
.venv/Scripts/python -c "from corpus_engine.domain import load_domain; from corpus_engine.reader.codebook import load_codebook, stability_path; d=load_domain(); cb=load_codebook(d,'mapper-v3'); print(cb.id, cb.sha[:12], stability_path(d,cb).exists())"
claude --version
codex --version
```

Expected: green suite; `2716 relevant records (821 human-reviewed, 1895 machine-only; lower
bound)`; `conflicts 0`; `mapper-v3 f92016681314 True`; both CLIs present.

- [ ] **Step 2: Freeze held-out v2 (free) — CONTROLLER**

```bash
.venv/Scripts/python tools/build_ranker_heldout.py --human-only --out data/eval/ranker-heldout-v2.jsonl
```

Expect roughly `candidates: 1116 (821 pos / 295 neg); held-out: ~304`, 92 strata, and all ten
jurisdictions in the coverage line. Copy the printed sha256 into `domain.yaml` as
`heldout_v2_sha256`, then verify the pin:

```bash
.venv/Scripts/python -c "from pathlib import Path; from corpus_engine.domain import load_domain; from corpus_engine.ranker.labels import check_heldout; d=load_domain(); print(check_heldout(d, Path('data/eval/ranker-heldout-v2.jsonl'), pin='heldout_v2_sha256')[:12])"
git add data/eval/ranker-heldout-v2.jsonl domains/str-right-to-let/domain.yaml
```

If the jurisdiction line shows fewer than ten, stop and report: D3 promises coverage of all
ten, and a gap is a fact about the review history, not something to paper over.

- [ ] **Step 3: Train classifier v2 and apply the ship rule (free; CPU) — CONTROLLER**

```bash
.venv/Scripts/python tools/train_ranker.py --heldout v2 --tag v2 --report reports/ranking-v2.md
```

Read the printed table. Three outcomes and what each means:
- **classifier:v2 beats fusion on both views** → it ships. Set `ranking.classifier_version: v2`
  in `domain.yaml` by hand (one line; `ranking.default` is already `classifier` and does not
  move). The tail map runs on v2.
- **it does not** → `domain.yaml` is unchanged, the tail map runs on classifier v1, and
  `reports/ranking-v2.md` says so (D6). This is a legitimate outcome, not a failure to fix.
- **v2 is worse than v1 on v2's slice** → it still ships or not by D6 alone (the rule is against
  fusion), but say so prominently in the report: shipping a model that is worse than the one in
  the field would be a decision the ship rule does not make for us. Stop and report before
  editing `domain.yaml` in that case.

```bash
git add data/ranker/v2 reports/ranking-v2.md domains/str-right-to-let/domain.yaml
```

- [ ] **Step 4: Commit the ranker work (free)**

```bash
git commit -m "ranker v2: held-out v2 frozen and pinned, classifier v2 trained and judged

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

- [ ] **Step 5: Re-rank the tail (free) — CONTROLLER**

```bash
.venv/Scripts/python pipeline/rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01 --exclude-read
```

Expect roughly 1,465 batches and ~26,400 cases packed, `6840 already-read excluded`. Check
`runs/cycle-004-shard-02/shard-manifest.json`: `source.run_id` is `cycle-004-shard-01`,
`source.pool_cases` is 32,795, `source.excluded_read` is 6,840, and `ranker.ranker_id` is the
one step 3 shipped. Then:

```bash
.venv/Scripts/python -c "
from pathlib import Path
from corpus_engine.mapper.cells import build_budget_cells, global_batch_order, load_batches
from corpus_engine.mapper.runner import default_max_units_for_budget
b = load_batches(Path('runs/cycle-004-shard-02/batches'))
cells = build_budget_cells(b); order = global_batch_order(b)
print(len(b), 'batches', len(cells), 'cells', default_max_units_for_budget(3000), 'default max-units')
print('best', order[0], 'worst reachable at 3000 cases', order[3000 // 18])
"
git add runs/cycle-004-shard-02/shard-manifest.json
```

- [ ] **Step 6: LIVE DRY RUN — two batches of the tail map (SPENDS; CONTROLLER)**

```bash
.venv/Scripts/python tools/map_reader.py --run-id cycle-004-shard-02 --case-budget 36 --dry-run-batches 2
```

- [ ] **Step 7: Inspect the dry run before anything else is bought (free)**

Read `runs/cycle-004-shard-02/map-manifest.json` and the two extraction files:
- **parse** — both units `status: "ok"`, no `failures`, `units_retried_after_split` 0.
- **gate** — 36 records, every `extraction_status` `ok` or `partial`.
- **budget** — `flags.case_budget` 36, `flags.order` `"global"`, every cell `"cap": "none"`,
  and the two units read are the first two entries of `global_batch_order` from step 5.
- **manifest** — `reader_pin` `claude-cli/claude-opus-5@claude-cli:-`, `effort` `low`,
  `codebook_sha` `f9201668…`, `totals.spend_usd` 0.0, `cache_keys` naming keys that exist under
  `data/reader/cache/`.
- **yield** — note how many of the 36 are relevant. At mean `rank_score` 0.04–0.06 a low yield
  is expected; a yield of zero across both batches is worth reporting before the field run.

**Stop and report. The field run is authorised only after this passes.**

- [ ] **Step 8: THE TAIL-MAP FIELD RUN (SPENDS; CONTROLLER)**

```bash
.venv/Scripts/python tools/map_reader.py --run-id cycle-004-shard-02 --case-budget 3000 --max-wall-seconds 21600
```

Detached, monitored, one line per batch. 3,000 cases is about 167 batches; at the measured
~108 s a batch that is roughly five hours, so it may take two invocations — re-run the same
line, the cache replays what is done for free, and stop when `stop` is `done` or
`budget:cases`. Never pass `--screen` (D5).

```bash
git add runs/cycle-004-shard-02/map-manifest.json
git status --porcelain runs/          # ONLY the two manifests may appear
```

- [ ] **Step 9: ADMIT THE TAIL MAP (writes the ledger; CONTROLLER)**

```bash
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --dry-run
.venv/Scripts/python tools/admit_map.py --run-id cycle-004-shard-02 --apply
git add data/ledger
```

`before:` must read `relevant 2716 records (821 human-reviewed, 1895 machine-only; lower
bound)`. `replay_ok=True` is required; if it is False, do not commit.

- [ ] **Step 10: Plan the re-read (free) — CONTROLLER**

```bash
.venv/Scripts/python tools/reread_records.py --plan
```

Expect `693 relevant records in cycle-001, cycle-002, cycle-003; 693 planned into N batches
over M cells`. If the planned count is under 693, the warning names how many cases have no live
store row — record the number, it belongs in the report.

```bash
git add runs/cycles-001-003-reread/case-ids.json
```

- [ ] **Step 11: LIVE DRY RUN — two batches of the re-read (SPENDS; CONTROLLER)**

```bash
.venv/Scripts/python tools/reread_records.py --dry-run-batches 2
```

- [ ] **Step 12: Inspect the re-read dry run (free)**

The same five checks as step 7, plus the two this read exists for:
- every record carries `under_thirty_days`, `restriction_nature` and
  `owner_freedom_characterization` — the three fields no cycles-1–3 record has;
- `flags.threshold` is `-1` and each cell's `cap` is `"none"`, so nothing will stop early.

Then a paper dry run of the admission over those two batches:

```bash
.venv/Scripts/python tools/admit_map.py --run-id cycles-001-003-reread --reread --dry-run
```

Read the per-field fill / replace / agree / conflict line. **Stop and report.**

- [ ] **Step 13: THE RE-READ FIELD RUN (SPENDS; CONTROLLER)**

```bash
.venv/Scripts/python tools/reread_records.py --max-wall-seconds 21600
```

Detached, monitored, re-invoked until `stop` is `done`. ~39 batches of 18; roughly 70 minutes.

```bash
git add runs/cycles-001-003-reread/map-manifest.json
```

- [ ] **Step 14: ADMIT THE RE-READ (writes the ledger; CONTROLLER)**

```bash
.venv/Scripts/python tools/admit_map.py --run-id cycles-001-003-reread --reread --dry-run
.venv/Scripts/python tools/admit_map.py --run-id cycles-001-003-reread --reread --apply
```

Expected shape, against the table in "Facts the plan is built on": ~2,079 fills on the three
mapper-v3-only fields, ~191 further fills on the empty ones, replacements on reader-held values,
and **at most 155 conflicts** — the reviewer-held fields. `relevant_false_conflicts` are cards,
never overturns. `replay_ok=True` required. Then check the rule did its job:

```bash
.venv/Scripts/python -c "from corpus_engine.ledger import open_ledger; v=open_ledger().view(); print('fold rejections:', sum(len(r) for r in v.conflicts().values()))"
git add data/ledger runs/cycles-001-003-reread/reread-conflicts.json runs/cycles-001-003-reread/reread-admission.json
```

`fold rejections: 0` is the expected answer — the tool declines to emit what the fold would
reject. Anything above zero is a bug in T6, not a curiosity; report it.

- [ ] **Step 15: Build each review round (free)**

Cap 250, section G first, full opinion text on every card. One round at a time:

```bash
.venv/Scripts/python -c "
import json
from pathlib import Path
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.mapper.queue import conflicts_from_view, select_queue
from corpus_engine.reader.sources import StoreCaseSource
RUN, N = 'cycles-001-003-reread', 1
dom = load_domain()
m = json.loads(Path(f'runs/{RUN}/map-manifest.json').read_text(encoding='utf-8'))
conf = json.loads(Path(f'runs/{RUN}/reread-conflicts.json').read_text(encoding='utf-8'))
view = open_ledger(domain=dom).view()
conn = store.connect(Path('data/db/corpus.db'))
q = select_queue(view, RUN, manifest=m, cases=StoreCaseSource(conn), cap=250,
                 conflicts=conf + conflicts_from_view(view))
Path(f'runs/{RUN}/review-round-{N}.json').write_bytes(
    (json.dumps(q.to_json(), indent=1, sort_keys=True) + chr(10)).encode('utf-8'))
print({k: len(v) for k, v in q.to_json()['sections'].items()}, 'deferred', len(q.deferred))
"
```

The same snippet with `RUN = 'cycle-004-shard-02'` and `conflicts=[]` builds the tail map's
rounds. Run the tail-map rounds first or the re-read rounds first as the controller directs;
section G is first *within* a round, not across runs.

- [ ] **Step 16: THE 100% CHECKER PASS (SPENDS codex; CONTROLLER)**

```bash
.venv/Scripts/python tools/make_map_review.py --check --queue runs/<run>/review-round-<n>.json
```

At most 250 Codex units, one case per unit. Confirm the printed tally is `{'ok': 250}` or names
what else happened, and that `checker_path` landed in the queue manifest.

- [ ] **Step 17: Export the cards and build the page (free)**

```bash
.venv/Scripts/python tools/export_review_cards.py --queue runs/<run>/review-round-<n>.json --full-text --chunks 8 --out-stem reports/review-round-<n>-cards
.venv/Scripts/python tools/make_map_review.py --build --queue runs/<run>/review-round-<n>.json --out-stem reports/review-queue-reread
```

`--full-text` on every card, not `--full-text-sections`: spec section 7 requires the full
opinion on every card in these rounds (the slice-2 lesson). Confirm the HTML ends with a
newline, carries no `\r`, shows seven section headings, and that a G card renders the conflict
block.

- [ ] **Step 18: First pass and confirmation (CONTROLLER + user)**

A model may draft the first pass from the exported cards, writing a decisions file in the
`{case_id, field, decision, value, note}` schema. **Every card is then confirmed by the user,
card by card**, and the run is marked `--assisted-by "<name>"`. On a section-G card the
expected decision is `keep`: the human value stands unless the reviewer, with the full opinion
in front of them, decides to revise their own earlier call.

The controller publishes the page and the user decides; **an agent executing this plan does not
publish it and does not invent decisions.** Stop here until the confirmed decisions come back.

- [ ] **Step 19: APPLY THE ROUND (writes the ledger; CONTROLLER)**

```bash
.venv/Scripts/python tools/apply_map_review.py --queue runs/<run>/review-round-<n>.json --decisions runs/<run>/review-round-<n>-decisions.json --assisted-by "<name>" --run-id reread-round-<n> --dry-run
.venv/Scripts/python tools/apply_map_review.py --queue runs/<run>/review-round-<n>.json --decisions runs/<run>/review-round-<n>-decisions.json --assisted-by "<name>" --run-id reread-round-<n>
git add data/ledger runs/<run>/review-round-<n>*.json
```

Repeat steps 15–19 per round until the controller stops. After each round update the three
pinned counts in `tests/test_ledger_committed.py` and re-run the suite.

- [ ] **Step 20: `reports/map-cycle-004-shard-02.md` (free)**

Spec section 8, in this order:
- **What ran**: the ranker the tail was ordered by (v2 or v1, and why — the D6 outcome), the
  pin, the checker, the budget (3,000 cases, global order, cell caps `none`, window 3,
  threshold 2), and how many invocations it took.
- **Cells read**: cell, era, jurisdiction, pool batches, batches read, cases read, relevant
  accepted, irrelevant accepted, stop reason. Cells stopped on yield versus cells never
  reached, because in a budgeted run "not reached" is the common case and is not a stop.
- **The budget boundary — the D5 test**: the mean `rank_score` of the first and last batches
  bought, and the yield of the last ten. **If the last cells were still yielding above the
  floor when the budget ran out, say so plainly**: D5 says the Gemini screen is reconsidered on
  exactly that evidence.
- **Checker**: units sampled, disagreement rate per field, and what the 100% pass found.
- **Failures**: every `failures` entry with status and error, and whether a later invocation
  re-read it.
- **Cost**: subscription units and wall clock, stated as **not a charge** (`spend_usd` is 0.0
  by construction). Screen: **off, not run**.
- **Published counts** before and after admission, via `view().counts()`, always two-tier.
- **Reproduction commands** and the note that re-running resumes from the cache for free.

- [ ] **Step 21: `reports/reread-cycles-001-003.md` (free)**

- **What ran**: 693 records, mapper-v3, the pin, the checker at 10%, yield stop off and why,
  units and wall clock; how many cases had no live store row.
- **Fills, replacements, agreements and conflicts per field**, from `reread-admission.json`,
  against the before-table in this plan: the three mapper-v3-only fields should be ~693 fills
  each.
- **How many human values the protection rule shielded**: the conflict count per field, and the
  count of `relevant false` reads on human-judged-relevant records that became cards instead of
  overturns. Name the number of fold-level rejections too (expected 0) and explain why: the
  tool never emits a patch the fold would reject.
- **What section G asked and what the reviewer decided** per round: keep / set / unsure.
- **Published counts** before and after, two-tier.

- [ ] **Step 22: Handoff, README, CONTEXT (free)**

`reports/handoff-cycle-004.md`: mark the two slice-3 carry-forwards done — held-out v2 frozen
with the ship rule re-run, and the cycles 1–3 re-read — and carry forward what is left: the
deferred review cards, the unread remainder of the tail after the 3,000-case budget, and
whether D5's screen is back on the table.

`README.md`, under the per-cycle review pipeline:

```
# Held-out v2 + ranker v2 (offline)
.venv\Scripts\python tools\build_ranker_heldout.py --human-only --out data\eval\ranker-heldout-v2.jsonl
.venv\Scripts\python tools\train_ranker.py --heldout v2 --tag v2 --report reports\ranking-v2.md
# The unread tail, under a fixed case budget in global rank order
.venv\Scripts\python pipeline\rank.py --run-id cycle-004-shard-02 --from-run cycle-004-shard-01 --exclude-read
.venv\Scripts\python tools\map_reader.py --run-id cycle-004-shard-02 --case-budget 3000
# Re-read the cycles 1-3 relevant records under mapper-v3
.venv\Scripts\python tools\reread_records.py --plan
.venv\Scripts\python tools\reread_records.py --max-wall-seconds 21600
.venv\Scripts\python tools\admit_map.py --run-id cycles-001-003-reread --reread --dry-run
```

`CONTEXT.md` already gained **Provenance** and **Conflict** in T1; add nothing further unless a
round turned up a term the glossary lacks.

- [ ] **Step 23: Full suite, commit (free)**

```bash
.venv/Scripts/python -m pytest -q
git status --porcelain          # no batches/, extractions/, .env, data/db, reader cache
git add reports CONTEXT.md README.md tests/test_ledger_committed.py
git commit -m "slice 3: ranker v2, the cycle-004 tail map, the cycles 1-3 re-read, review rounds

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TwxFMknjsnQydVkyekYWL3"
```

---

## Self-review notes (done while writing)

**1. Spec coverage**

| Spec section / decision | Where it is implemented |
| --- | --- |
| 1 Goal | T1–T8 |
| 2 D1 order | Task order: T1 protection → T2/T3 ranker → T4/T5 tail → T6 re-read → T7 rounds → T8 reports |
| 2 D2 reviewer basis never overwritten | T1 (`_may_write`, `State.provenance`, `State.conflicts`) |
| 2 D3 held-out v2 selection, stratification, freeze, pin | T2 (`human_relevance_decisions`, `--human-only`, `heldout_v2_sha256`) |
| 2 D4 fixed case budget, global order, yield floor still stops | T5 (`--case-budget`, `global_batch_order`, `_run_budget`) |
| 2 D5 no Gemini screen; report the boundary | Global Constraints (`--screen` never passed); T8 step 20 (the boundary test) |
| 2 D6 ship rule, both views, no margin | T3 (`ships()`), T8 step 3 |
| 2 D7 re-read scope, fill/replace/never-touch, relevant-false is a card | T6 (`relevant_case_ids`, `reread_patches`) |
| 2 D8 provenance of re-read and tail patches | T6 (`basis_for` under `mapper-v3`, run id `cycles-001-003-reread`); T4/T8 (`cycle-004-shard-02`) |
| 2 D9 existing round tooling, one new section | T7 |
| 2 D10 terms of use | Global Constraints (subscription only, no paid request) |
| 3 fold protection, conflicts, flag, `LedgerView.conflicts()`, byte-identical replay | T1 steps 3–5 |
| 4 builder, trainer, ship rule, reports | T2, T3 |
| 5 re-rank, `--case-budget`, admission unchanged | T4, T5, T8 step 9 |
| 6 case-id list, 18-case units, admission modes, counts | T6 |
| 7 section G first, card shape, decision semantics, cap 250, full text, Codex 100% | T7, T8 steps 15–19 |
| 8 the three reports, handoff, CONTEXT terms, counts | T8 steps 20–22, T1 step 6 |
| 9 error handling: rejections never raise, no rejected patch emitted, tools refuse overwrites | T1 (`_may_write` returns, never raises), T6 (conflicts emit no `set`), T2/T3 (overwrite refusals) |
| 10 testing | Every task's step 1; the live dry runs are T8 steps 6 and 11 |
| 11 constraints | Global Constraints |

**2. Placeholder scan.** No "TBD", "similar to Task N", or "add error handling" survives. Two
values are deliberately left to be filled from a first run and both say exactly how: the
`needs-review:` flag count in `test_the_protection_rule_leaves_the_published_counts_untouched`
(run once, read the number, pin it) and the run/round names in T8's `<run>` / `<n>`
placeholders, which are loop variables of a controller-driven loop, not undecided design. The
test helpers `_training_inputs`, `_fixture_conn` and `wired_reread` are described by what they
must return and which existing fixture they are lifted from, rather than re-printed.

**3. Type consistency.** Checked across tasks:
- The conflict dict has one shape, `CONFLICT_KEYS`, produced by `reread_patches` (T6) and
  `conflicts_from_view` (T7) and consumed by `select_queue(conflicts=...)` and
  `QueueCard.conflict`. The fold's own lower-level entry (`{field, attempted, standing, by, at,
  op}`) is a different, deliberately narrower record of a *rejected attempt*; `conflicts_from_view`
  is the one place that converts between them.
- `FLAG_PREFIX` is defined in `fold.py` (T1), imported by `admit.py` (T6), pinned equal to
  `reader/schema.py`'s by a test, and never re-spelled as a literal.
- `Cell.uncapped` (T5) is used by `build_budget_cells` and by `reread_cells` (T6) and read by
  `Cell.to_json()`'s `"cap"` key, which T8's checks assert.
- `check_heldout(domain, path, *, pin=...)` (T2) is called by `train()` (T3) through
  `heldout_pin`, and both spellings of the pin (`heldout_sha256`, `heldout_v2_sha256`) exist as
  `RankingSpec` fields.
- `RunnerCaps.case_budget` (T5) is read only by `MapRunner._gate` and written into
  `flags.case_budget`; `default_max_units_for_budget` is used by `map_reader.py` (T5) and by
  T8's pre-flight snippet.
- `patches_for(..., cards=...)` (T7) takes the index `card_index` builds; the key is
  `(case_id, decide_field)` in both.
- `store.case_partitions` (T2) is the only era/jurisdiction lookup, used by `labelled_reads`,
  `human_labelled_reads` and `reread_records.plan_batches`.
