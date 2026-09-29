# Lawyer Explainer, Checkpoint 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish, as a private Artifact, a ten-minute page that lets the litigation team retell how the right-to-let record was built and how the method maps onto corpus-linguistics practice, with every figure pinned to ledger seq 83,531 (pre-audit).

**Architecture:** One small committed tool, `tools/explainer_snapshot.py`, reads every figure at the pinned sequence (ledger API, `corpus.db`, the published evaluation JSON, the audit sample manifest) into `snapshot.json`, and renders `{{snap:dotted.path}}` placeholders into the script and the page, with a lint for the guardrails. The content (evidence pack, script, page) lives in the gitignored `reports/explainer/` because the repo is public. Content passes an independent fact-check and two user gates (script, page) before anyone else sees it.

**Tech Stack:** Python 3.11 (`.venv`), sqlite3, pytest; one self-contained HTML page (inline SVG, CSS, a little vanilla JS); Playwright MCP for browser QA; the Artifact tool for publishing.

**Spec:** `docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md`

## Global Constraints

- Snapshot: ledger seq **83531**, label **"Checkpoint 1"**, date **2026-09-12**; the audit is "drawn, not yet read".
- At most **six figures** on the page, all from `snapshot.json` (library size, opinions read, relevant two-tier with favorable subsets, audit, known-case benchmark, unread tail).
- **No dollar figures** anywhere (spend history, unit prices, list-equivalent costs); models named neutrally ("Claude Opus", "a GPT model"); no discussion of billing routes.
- **No reference** to `reports/right-to-let-guide.html`, `reports/attorney-report.html`, "The Right-to-Let Record", or "Right-to-Let Corpus Engine".
- `reports/explainer/` is **gitignored** (public repo); only the tool, its tests, `.gitignore`, the spec, and this plan are committed.
- The eleven accuracy guardrails in spec section 7 are acceptance criteria for the script and the page.
- Tests build their own ledgers and databases under `tmp_path`; **no test reads the live ledger, `corpus.db`, or gold files**.
- Files are written UTF-8, LF, via `export_review_cards.write_text`; never through a cp1252 default.
- Run Python as `.venv\Scripts\python` from the repo root (Windows; PowerShell or Git Bash).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Inputs from different ledger states.** An evaluation published at another seq, a sample drawn after the snapshot, or a ledger whose head is below the requested seq must make `snapshot` refuse, naming the mismatch. It must never write a snapshot mixing states. Pinned in Task 1.
2. **Checkpoint 2 re-run.** At a later `--as-of`, the sample (drawn at 83531) predates the snapshot; that must be accepted while a sample drawn *after* the snapshot is refused. Pinned in Task 1.
3. **A figure typed by hand.** A literal grouped number (`4,351`) in a template drifts from the snapshot at Checkpoint 2, so the template lint flags it. Pinned in Task 2.
4. **A placeholder typo.** `{{snap:ledger.relevent.total}}` must fail the render, listing every unknown key. It must never ship the raw braces. Pinned in Task 2.
5. **Years and identifiers rendered as counts.** `1671` must never render as `1,671` and the seed must never render as `20,260,912`: years and identifiers are stored as strings, counts as ints, and floats/booleans refuse to render. Pinned in Tasks 1 and 2.

---

### Task 1: Snapshot figures (tool, part 1)

**Files:**
- Create: `tools/explainer_snapshot.py`
- Create: `tests/test_explainer_snapshot.py`
- Modify: `.gitignore` (append `reports/explainer/`)

**Interfaces:**
- Consumes: `corpus_engine.ledger.open_ledger(root, *, domain)`, `Ledger.view(as_of) -> LedgerView` (whose `.as_of` is the last patch seq actually replayed), `LedgerView.counts(**filters).total -> TierCount(human_reviewed, machine_only)`, `LedgerView.state.order`, `LedgerView.patches[-1].at`; `corpus_engine.store.connect(db_path)`; `corpus_engine.domain.load_domain().jurisdictions`; `export_review_cards.write_text(path, text)`.
- Produces (Task 2 and Task 3 rely on these exact names):
  - `class SnapshotError(Exception)`
  - `tier(t) -> {"human_reviewed": int, "machine_only": int, "total": int}`
  - `millions(n: int) -> str` e.g. `"about 1.8 million"`
  - `long_date(iso: str) -> str` e.g. `"September 12, 2026"`
  - `ledger_figures(view, as_of: int) -> dict`
  - `library_figures(conn, jurisdictions) -> dict`
  - `benchmark_figures(evaluation: Mapping) -> dict`
  - `tail_figures(evaluation: Mapping) -> dict`
  - `audit_figures(sample: Mapping) -> dict`
  - `check_consistency(as_of: int, ledger: Mapping, evaluation: Mapping, sample: Mapping) -> None`
  - `build_snapshot(*, label, as_of, view, conn, jurisdictions, evaluation, sample, git_revision, inputs) -> dict`
  - `main(argv: list[str] | None = None) -> int` with subcommand `snapshot`
  - `snapshot.json` shape:
    ```
    snapshot: {label, as_of:int, date:"YYYY-MM-DD", date_display, git_revision, generated_at}
    library:  {canonical_total:int, in_scope:int, outside_scope:int, jurisdictions:int,
               first_year:str, last_year:str, in_scope_display:str, outside_scope_display:str}
    ledger:   {as_of:int, date, opinions_read:int, relevant:tier, favorable:tier, favorable_householder:tier}
    benchmark:{entries, resolved, read, kept, kept_human, unresolved:int,
               lost:{unsignaled, reader_negative, withdrawn, other:int, total:int}}
    tail:     {unread:int, low:int, high:int}
    audit:    {n:int, frame_size:int, seed:str, drawn_seq:int, drawn_date, status:str}
    inputs:   {evaluation_sha256, sample_sha256, ledger_content_sha256}
    ```

- [ ] **Step 1: Ignore the content folder**

Append to `.gitignore`:

```
# Lawyer explainer content (public repo): script, evidence, snapshot, page
reports/explainer/
```

Run: `git check-ignore -v reports/explainer/snapshot.json`
Expected: prints the `.gitignore` line that matches.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_explainer_snapshot.py`:

```python
"""tools/explainer_snapshot.py: the explainer's figures at one pinned ledger seq, refused when
the inputs describe different ledger states (spec 2026-09-29 lawyer explainer, section 8)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import explainer_snapshot as es  # noqa: E402
from corpus_engine.domain import load_domain  # noqa: E402
from corpus_engine.ledger import Basis, Patch, open_ledger  # noqa: E402

AT = "2026-09-12T08:55:22"


def _rec(cid, year, *, relevant=True, pol="favorable", who="householder"):
    return {"case_id": cid, "cite": f"{cid} X", "year": year, "jurisdiction": "N.Y.",
            "relevant": relevant, "polarity": pol, "who_was_letting": who,
            "duration_of_occupancy": "nights", "characterization": "lodging",
            "holding_summary": "h", "quotes": [{"text": "q", "supports": "polarity"}],
            "extraction_status": "ok"}


def _ledger(tmp_path):
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    reader = Basis(model="m", prompt_version="mapper-v1", run_id="r")
    led.apply([Patch(1, "admit", "", _rec(1, 1850), "v", reader, cycle="cycle-001"),
               Patch(2, "admit", "", _rec(2, 1900, who="non_resident_owner"), "v", reader, cycle="cycle-001"),
               Patch(3, "admit", "", _rec(3, 1900, relevant=False), "v", reader, cycle="cycle-001")],
              note="seed", at=AT)
    led.apply([Patch(1, "set", "review.status", "human-adjudicated", "confirmed", Basis(reviewer="u"))],
              note="review", at=AT)
    return led


def _library(tmp_path):
    path = tmp_path / "lib.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cases (case_id INTEGER, jurisdiction TEXT, decision_year INTEGER, "
                 "is_duplicate_of INTEGER)")
    conn.executemany("INSERT INTO cases VALUES (?,?,?,?)", [
        (1, "N.Y.", 1799, None), (2, "Cal.", 2019, None), (3, "U.S.", 1900, None), (4, "N.Y.", 1650, 1)])
    conn.commit()
    return path, conn


def _evaluation(seq, rel=(1, 1), fav=(1, 1), hh=(1, 0)):
    c = lambda t: {"human_reviewed": t[0], "machine_only": t[1]}  # noqa: E731
    return {"ledger": {"reporting_seq": seq, "content_sha256": "ab" * 32,
                       "counts": {"relevant": c(rel), "favorable": c(fav), "favorable_householder": c(hh)}},
            "gold_recovery": {
                "union": {"entries": 65, "resolved": 36, "read": 28, "relevant": 10, "relevant_human": 8},
                "misses": ([{"lost_at": "unsignaled"}] * 8 + [{"lost_at": "reader-negative"}] * 17
                           + [{"lost_at": "withdrawn"}]),
                "unresolved": [{"cite": "x"}] * 29},
            "coverage": {"bands": [{"unread_cases": 14000}, {"unread_cases": 255}],
                         "scenarios": [{"estimated_relevant": 817}, {"estimated_relevant": 409},
                                       {"estimated_relevant": 1568}]}}


def _sample(seq):
    return {"drawn_at": "2026-09-12T17:09:26+00:00", "ledger_head_seq": seq, "frame_size": 2842,
            "seed": 20260912, "n": 150}


def test_ledger_figures_counts_reads_and_tiers_at_the_pinned_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    assert f["as_of"] == head and f["date"] == "2026-09-12"
    assert f["opinions_read"] == 3                       # every admitted case, relevant or not
    assert f["relevant"] == {"human_reviewed": 1, "machine_only": 1, "total": 2}
    assert f["favorable"] == {"human_reviewed": 1, "machine_only": 1, "total": 2}
    assert f["favorable_householder"] == {"human_reviewed": 1, "machine_only": 0, "total": 1}


def test_ledger_figures_refuses_a_seq_beyond_the_ledger_head(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    with pytest.raises(es.SnapshotError, match="head"):
        es.ledger_figures(led.view(as_of=head + 10), head + 10)


def test_library_figures_separate_the_searched_jurisdictions_from_the_rest(tmp_path):
    _, conn = _library(tmp_path)
    f = es.library_figures(conn, ("N.Y.", "Cal."))
    assert (f["canonical_total"], f["in_scope"], f["outside_scope"]) == (3, 2, 1)   # duplicate excluded
    assert f["jurisdictions"] == 2
    assert (f["first_year"], f["last_year"]) == ("1799", "2019")                    # strings, not counts


def test_display_helpers():
    assert es.millions(1_795_165) == "about 1.8 million"
    assert es.long_date("2026-09-12") == "September 12, 2026"


def test_benchmark_figures_break_down_every_loss():
    f = es.benchmark_figures(_evaluation(4))
    assert (f["entries"], f["resolved"], f["read"], f["kept"], f["kept_human"], f["unresolved"]) == (65, 36, 28, 10, 8, 29)
    assert f["lost"] == {"unsignaled": 8, "reader_negative": 17, "withdrawn": 1, "other": 0, "total": 26}


def test_benchmark_figures_refuse_losses_that_do_not_add_up():
    ev = _evaluation(4)
    ev["gold_recovery"]["misses"].pop()
    with pytest.raises(es.SnapshotError, match="26"):
        es.benchmark_figures(ev)


def test_tail_figures_sum_unread_and_span_the_scenarios():
    assert es.tail_figures(_evaluation(4)) == {"unread": 14255, "low": 409, "high": 1568}


def test_audit_figures_report_the_frozen_draw_with_the_seed_as_text():
    f = es.audit_figures(_sample(83531))
    assert f == {"n": 150, "frame_size": 2842, "seed": "20260912", "drawn_seq": 83531,
                 "drawn_date": "2026-09-12", "status": "drawn, not yet read"}


def test_consistency_refuses_an_evaluation_from_another_seq(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    with pytest.raises(es.SnapshotError, match="evaluation"):
        es.check_consistency(head, f, _evaluation(head - 1), _sample(head))


def test_consistency_refuses_counts_that_disagree_with_the_evaluation(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    with pytest.raises(es.SnapshotError, match="relevant"):
        es.check_consistency(head, f, _evaluation(head, rel=(2, 0)), _sample(head))


def test_consistency_accepts_an_earlier_sample_and_refuses_a_later_one(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    f = es.ledger_figures(led.view(as_of=head), head)
    es.check_consistency(head, f, _evaluation(head), _sample(head - 2))     # Checkpoint 2 shape
    with pytest.raises(es.SnapshotError, match="sample"):
        es.check_consistency(head, f, _evaluation(head), _sample(head + 1))


def test_cli_snapshot_writes_utf8_lf_json(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head)), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head)), encoding="utf-8")
    out = tmp_path / "explainer" / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head), "--label", "Checkpoint 1", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db),
                  "--out", str(out)])
    assert rc == 0
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    snap = json.loads(raw.decode("utf-8"))
    assert snap["snapshot"]["label"] == "Checkpoint 1" and snap["snapshot"]["as_of"] == head
    assert snap["snapshot"]["date_display"] == "September 12, 2026"
    assert snap["ledger"]["relevant"]["total"] == 2 and snap["tail"]["unread"] == 14255
    assert snap["inputs"]["ledger_content_sha256"] == "ab" * 32
    assert len(snap["inputs"]["evaluation_sha256"]) == 64


def test_cli_snapshot_refuses_and_writes_nothing_on_a_mismatch(tmp_path):
    led = _ledger(tmp_path)
    head = led.view().as_of
    db, _ = _library(tmp_path)
    ev, sm = tmp_path / "ev.json", tmp_path / "sample.json"
    ev.write_text(json.dumps(_evaluation(head - 1)), encoding="utf-8")
    sm.write_text(json.dumps(_sample(head)), encoding="utf-8")
    out = tmp_path / "explainer" / "snapshot.json"
    rc = es.main(["snapshot", "--as-of", str(head), "--label", "Checkpoint 1", "--evaluation", str(ev),
                  "--sample", str(sm), "--ledger-dir", str(tmp_path / "ledger"), "--db", str(db),
                  "--out", str(out)])
    assert rc == 2 and not out.exists()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_explainer_snapshot.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'explainer_snapshot'`.

- [ ] **Step 4: Write the implementation**

Create `tools/explainer_snapshot.py`:

```python
"""The lawyer explainer's figures (spec: docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md).

snapshot  every figure the explainer shows, read at ONE pinned ledger seq from the ledger API,
          corpus.db, the published evaluation JSON and the audit sample manifest; refused (exit 2,
          nothing written) when those inputs describe different ledger states.

Counts are ints; years and identifiers are strings, so a later render never groups them."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from export_review_cards import write_text                     # noqa: E402
from corpus_engine import store                                # noqa: E402
from corpus_engine.domain import load_domain                   # noqa: E402
from corpus_engine.ledger import open_ledger                   # noqa: E402

AUDIT_STATUS = "drawn, not yet read"
LOSS_KEYS = {"unsignaled": "unsignaled", "reader-negative": "reader_negative", "withdrawn": "withdrawn"}
TIERS = ("relevant", "favorable", "favorable_householder")


class SnapshotError(Exception):
    """The inputs disagree about which ledger state they describe, or a figure cannot be derived."""


def tier(t) -> dict:
    return {"human_reviewed": t.human_reviewed, "machine_only": t.machine_only,
            "total": t.human_reviewed + t.machine_only}


def millions(n: int) -> str:
    return f"about {n / 1_000_000:.1f} million"


def long_date(iso: str) -> str:
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d:%B} {d.day}, {d.year}"


def ledger_figures(view, as_of: int) -> dict:
    if view.as_of != as_of:
        raise SnapshotError(f"ledger head is seq {view.as_of}, not the requested snapshot seq {as_of}")
    return {"as_of": as_of, "date": view.patches[-1].at[:10],
            "opinions_read": len(view.state.order),
            "relevant": tier(view.counts().total),
            "favorable": tier(view.counts(polarity="favorable").total),
            "favorable_householder": tier(view.counts(polarity="favorable",
                                                      who_was_letting="householder").total)}


def library_figures(conn, jurisdictions: Sequence[str]) -> dict:
    marks = ",".join("?" * len(jurisdictions))
    total = conn.execute("SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL").fetchone()[0]
    n, lo, hi = conn.execute(
        f"SELECT count(*), min(decision_year), max(decision_year) FROM cases "
        f"WHERE is_duplicate_of IS NULL AND jurisdiction IN ({marks})", tuple(jurisdictions)).fetchone()
    return {"canonical_total": total, "in_scope": n, "outside_scope": total - n,
            "jurisdictions": len(jurisdictions), "first_year": str(lo), "last_year": str(hi),
            "in_scope_display": millions(n),
            "outside_scope_display": f"about {round((total - n) / 1000):,} thousand"}


def benchmark_figures(evaluation: Mapping) -> dict:
    g = evaluation["gold_recovery"]
    u = g["union"]
    counted = Counter(m["lost_at"] for m in g["misses"])
    lost = {key: counted.get(raw, 0) for raw, key in LOSS_KEYS.items()}
    lost["other"] = sum(n for raw, n in counted.items() if raw not in LOSS_KEYS)
    lost["total"] = sum(counted.values())
    expected = u["resolved"] - u["relevant"]
    if lost["total"] != expected:
        raise SnapshotError(f"benchmark misses list {lost['total']} losses but resolved - kept = {expected}")
    return {"entries": u["entries"], "resolved": u["resolved"], "read": u["read"], "kept": u["relevant"],
            "kept_human": u["relevant_human"], "unresolved": len(g["unresolved"]), "lost": lost}


def tail_figures(evaluation: Mapping) -> dict:
    c = evaluation["coverage"]
    est = [s["estimated_relevant"] for s in c["scenarios"]]
    return {"unread": sum(b["unread_cases"] for b in c["bands"]), "low": min(est), "high": max(est)}


def audit_figures(sample: Mapping) -> dict:
    return {"n": sample["n"], "frame_size": sample["frame_size"], "seed": str(sample["seed"]),
            "drawn_seq": sample["ledger_head_seq"], "drawn_date": sample["drawn_at"][:10],
            "status": AUDIT_STATUS}


def check_consistency(as_of: int, ledger: Mapping, evaluation: Mapping, sample: Mapping) -> None:
    seq = evaluation["ledger"]["reporting_seq"]
    if seq != as_of:
        raise SnapshotError(f"evaluation reports ledger seq {seq}, not the snapshot seq {as_of}")
    for name in TIERS:
        want = evaluation["ledger"]["counts"][name]
        got = ledger[name]
        if (got["human_reviewed"], got["machine_only"]) != (want["human_reviewed"], want["machine_only"]):
            raise SnapshotError(f"{name}: ledger {got['human_reviewed']}/{got['machine_only']} at seq "
                                f"{as_of} but the evaluation says {want['human_reviewed']}/{want['machine_only']}")
    if sample["ledger_head_seq"] > as_of:
        raise SnapshotError(f"audit sample drawn at seq {sample['ledger_head_seq']}, after the snapshot seq {as_of}")


def build_snapshot(*, label: str, as_of: int, view, conn, jurisdictions: Sequence[str],
                   evaluation: Mapping, sample: Mapping, git_revision: str, inputs: Mapping) -> dict:
    led = ledger_figures(view, as_of)
    check_consistency(as_of, led, evaluation, sample)
    return {"snapshot": {"label": label, "as_of": as_of, "date": led["date"],
                         "date_display": long_date(led["date"]), "git_revision": git_revision,
                         "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "library": library_figures(conn, jurisdictions),
            "ledger": led,
            "benchmark": benchmark_figures(evaluation),
            "tail": tail_figures(evaluation),
            "audit": audit_figures(sample),
            "inputs": dict(inputs)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_snapshot(a) -> int:
    ev_path, sample_path = Path(a.evaluation), Path(a.sample)
    evaluation = json.loads(ev_path.read_text(encoding="utf-8"))
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    domain = load_domain()
    view = open_ledger(Path(a.ledger_dir) if a.ledger_dir else None, domain=domain).view(as_of=a.as_of)
    conn = store.connect(Path(a.db) if a.db else None, wal=False)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    try:
        snap = build_snapshot(label=a.label, as_of=a.as_of, view=view, conn=conn,
                              jurisdictions=domain.jurisdictions, evaluation=evaluation, sample=sample,
                              git_revision=rev,
                              inputs={"evaluation_sha256": _sha256(ev_path), "sample_sha256": _sha256(sample_path),
                                      "ledger_content_sha256": evaluation["ledger"]["content_sha256"]})
    except SnapshotError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    write_text(Path(a.out), json.dumps(snap, indent=1, ensure_ascii=False))
    print(f"{a.label} at seq {a.as_of} -> {Path(a.out).as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="read every explainer figure at one pinned ledger seq")
    s.add_argument("--as-of", type=int, required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--evaluation", required=True)
    s.add_argument("--sample", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--ledger-dir", default=None, help="default: the project ledger")
    s.add_argument("--db", default=None, help="default: data/db/corpus.db")
    a = ap.parse_args(argv)
    return {"snapshot": cmd_snapshot}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_explainer_snapshot.py -q`
Expected: `13 passed`. If `test_ledger_figures_counts_reads_and_tiers_at_the_pinned_seq` fails on `favorable_householder`, confirm case 1 is the only human-reviewed householder (it is, by construction), and do not loosen the assertion.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python -m pytest tests -q`
Expected: everything that passed before still passes (the last recorded baseline was 704+ passed, 1 xfail), plus 13 new.

- [ ] **Step 7: Commit**

```bash
git add .gitignore tools/explainer_snapshot.py tests/test_explainer_snapshot.py
git commit -m "explainer: snapshot figures at one pinned ledger seq, refused on mixed inputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Placeholder render and guardrail lint (tool, part 2)

**Files:**
- Modify: `tools/explainer_snapshot.py` (add render/lint and two subcommands)
- Modify: `tests/test_explainer_snapshot.py` (append tests)

**Interfaces:**
- Consumes: `SnapshotError` and `write_text` from Task 1; `snapshot.json` shape from Task 1.
- Produces (Tasks 5 and 7 rely on these):
  - `PLACEHOLDER` regex: `{{snap:dotted.path}}` (letters, digits, `_`, `.`; no spaces)
  - `resolve(snapshot: Mapping, path: str)`; raises `KeyError(path)`
  - `format_value(value, path: str) -> str`: int becomes `f"{v:,}"`, str is returned as-is, and anything else raises `SnapshotError`
  - `render(text: str, snapshot: Mapping) -> str`: raises `SnapshotError("unknown snapshot keys: a, b")`
  - `lint(text: str, *, template: bool) -> list[str]`: problem strings, each starting with `line N:`
  - `ALLOW_PRICE = "lint-allow: historical price"`: a line containing this marker may carry a `$` amount
  - CLI: `render --template IN --snapshot S --out OUT` (lints the template, renders, lints the output; exit 1 and writes nothing on any problem); `lint --in FILE [--template]` (exit 1 on problems)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_explainer_snapshot.py`:

```python
SNAP = {"ledger": {"relevant": {"total": 4351, "human_reviewed": 1509}, "opinions_read": 24643},
        "library": {"first_year": "1671", "in_scope_display": "about 1.8 million"},
        "audit": {"seed": "20260912"}, "tail": {"ratio": 0.5}, "flag": {"on": True}}


def test_render_substitutes_counts_grouped_and_text_verbatim():
    out = es.render("At least {{snap:ledger.relevant.total}} cases since {{snap:library.first_year}}, "
                    "seed {{snap:audit.seed}}, {{snap:library.in_scope_display}}.", SNAP)
    assert out == "At least 4,351 cases since 1671, seed 20260912, about 1.8 million."


def test_render_fails_listing_every_unknown_key():
    with pytest.raises(es.SnapshotError) as e:
        es.render("{{snap:ledger.relevent.total}} and {{snap:nope}} and {{snap:nope}}", SNAP)
    assert str(e.value) == "unknown snapshot keys: ledger.relevent.total, nope"


def test_render_refuses_floats_booleans_and_whole_blocks():
    for path in ("tail.ratio", "flag.on", "ledger.relevant"):
        with pytest.raises(es.SnapshotError, match=path):
            es.render("{{snap:%s}}" % path, SNAP)


def test_lint_flags_dollar_amounts_but_honours_the_historical_price_marker():
    assert es.lint("It cost $0.02 per million.", template=False) == ["line 1: dollar amount"]
    assert es.lint("rooms at $ 8.50 a week", template=False) == ["line 1: dollar amount"]
    assert es.lint('"$8.50 a week" <!-- lint-allow: historical price -->', template=False) == []


def test_lint_flags_retired_pages_in_any_case():
    probs = es.lint("See reports/right-to-let-guide.html\nand the ATTORNEY-REPORT page", template=False)
    assert probs == ["line 1: reference to retired page 'right-to-let-guide'",
                     "line 2: reference to retired page 'attorney-report'"]


def test_lint_template_flags_literal_grouped_numbers_outside_placeholders():
    assert es.lint("We read 24,643 opinions.", template=True) == [
        "line 1: literal grouped number '24,643' (use a {{snap:...}} placeholder)"]
    assert es.lint("We read {{snap:ledger.opinions_read}} opinions in 1860.", template=True) == []


def test_lint_rendered_flags_leftover_placeholders():
    assert es.lint("x {{snap:a}} y", template=False) == ["line 1: unrendered placeholder"]


def test_cli_render_lints_both_sides_and_refuses_without_writing(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text("Read {{snap:ledger.opinions_read}} — ok\n", encoding="utf-8")
    bad.write_text("Read 24,643 opinions\n", encoding="utf-8")
    out = tmp_path / "out.md"
    assert es.main(["render", "--template", str(good), "--snapshot", str(snap), "--out", str(out)]) == 0
    assert out.read_bytes().decode("utf-8") == "Read 24,643 — ok\n"
    out2 = tmp_path / "out2.md"
    assert es.main(["render", "--template", str(bad), "--snapshot", str(snap), "--out", str(out2)]) == 1
    assert not out2.exists()
    assert es.main(["lint", "--in", str(out)]) == 0
    assert es.main(["lint", "--in", str(bad), "--template"]) == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_explainer_snapshot.py -q -k "render or lint"`
Expected: FAIL with `AttributeError: module 'explainer_snapshot' has no attribute 'render'`.

- [ ] **Step 3: Implement**

In `tools/explainer_snapshot.py`, add `import re` to the imports, extend the module docstring with:

```
render    substitutes {{snap:dotted.path}} placeholders from snapshot.json (ints grouped, text
          verbatim); an unknown key fails the whole render.
lint      the guardrails a text must pass before the team sees it: no dollar amounts, no retired
          pages, nothing left unrendered, and (templates) no literal grouped numbers.
```

then add below `build_snapshot`:

```python
PLACEHOLDER = re.compile(r"\{\{snap:([A-Za-z0-9_.]+)\}\}")
DOLLAR = re.compile(r"\$\s?\d")
GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])")
ALLOW_PRICE = "lint-allow: historical price"
RETIRED = ("right-to-let-guide", "attorney-report", "the right-to-let record", "right-to-let corpus engine")


def resolve(snapshot: Mapping, path: str):
    cur = snapshot
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def format_value(value, path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SnapshotError(f"{{{{snap:{path}}}}} is a {type(value).__name__}; only counts and text render")
    return f"{value:,}" if isinstance(value, int) else value


def render(text: str, snapshot: Mapping) -> str:
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        try:
            return format_value(resolve(snapshot, m.group(1)), m.group(1))
        except KeyError:
            missing.append(m.group(1))
            return m.group(0)

    out = PLACEHOLDER.sub(sub, text)
    if missing:
        raise SnapshotError("unknown snapshot keys: " + ", ".join(sorted(set(missing))))
    return out


def lint(text: str, *, template: bool) -> list[str]:
    problems: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        if DOLLAR.search(line) and ALLOW_PRICE not in line:
            problems.append(f"line {i}: dollar amount")
        low = line.lower()
        for name in RETIRED:
            if name in low:
                problems.append(f"line {i}: reference to retired page {name!r}")
        if template:
            for m in GROUPED.finditer(PLACEHOLDER.sub("", line)):
                problems.append(f"line {i}: literal grouped number {m.group(0)!r} (use a {{{{snap:...}}}} placeholder)")
        elif "{{" in line:
            problems.append(f"line {i}: unrendered placeholder")
    return problems


def _report(problems: list[str], label: str) -> None:
    for p in problems:
        print(f"{label}: {p}", file=sys.stderr)


def cmd_render(a) -> int:
    src = Path(a.template).read_text(encoding="utf-8")
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    problems = lint(src, template=True)
    if problems:
        _report(problems, a.template)
        return 1
    try:
        out = render(src, snap)
    except SnapshotError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    problems = lint(out, template=False)
    if problems:
        _report(problems, "rendered output")
        return 1
    write_text(Path(a.out), out)
    print(f"{Path(a.template).as_posix()} -> {Path(a.out).as_posix()}")
    return 0


def cmd_lint(a) -> int:
    problems = lint(Path(a.input).read_text(encoding="utf-8"), template=a.template)
    _report(problems, a.input)
    return 1 if problems else 0
```

and register the subcommands in `main` (replace the final two lines of `main` before `return`):

```python
    r = sub.add_parser("render", help="fill {{snap:...}} placeholders; lint before and after")
    r.add_argument("--template", required=True)
    r.add_argument("--snapshot", required=True)
    r.add_argument("--out", required=True)
    li = sub.add_parser("lint", help="check a file against the explainer guardrails")
    li.add_argument("--in", dest="input", required=True)
    li.add_argument("--template", action="store_true")
    a = ap.parse_args(argv)
    return {"snapshot": cmd_snapshot, "render": cmd_render, "lint": cmd_lint}[a.cmd](a)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_explainer_snapshot.py -q`
Expected: `21 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/explainer_snapshot.py tests/test_explainer_snapshot.py
git commit -m "explainer: {{snap:...}} render and guardrail lint (dollars, retired pages, hand-typed figures)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The Checkpoint 1 snapshot, and the spec's library wording

**Files:**
- Create (gitignored): `reports/explainer/snapshot.json`
- Modify: `docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md` (section 3 step 1; section 8 figure 1)

**Interfaces:**
- Consumes: `explainer_snapshot.py snapshot` (Task 1).
- Produces: `reports/explainer/snapshot.json`, the only source of figures for Tasks 5 and 7.

- [ ] **Step 1: Generate the snapshot**

Run:
```
.venv\Scripts\python tools\explainer_snapshot.py snapshot --as-of 83531 --label "Checkpoint 1" --evaluation reports\evaluation-cycle-004.json --sample runs\audit-cycle-004\sample-manifest.json --out reports\explainer\snapshot.json
```
Expected: `Checkpoint 1 at seq 83531 -> reports/explainer/snapshot.json` (the library query scans `corpus.db`; allow a minute or two).

- [ ] **Step 2: Verify every figure against the values established during design**

Run:
```
.venv\Scripts\python -c "import json; s=json.load(open('reports/explainer/snapshot.json',encoding='utf-8')); L=s['ledger']; lib=s['library']; b=s['benchmark']; print(s['snapshot']['date'], L['opinions_read'], L['relevant'], L['favorable'], L['favorable_householder']); print(lib); print(b); print(s['tail'], s['audit'])"
```
Expected, exactly:
- date `2026-09-12`; opinions_read `24643`
- relevant `1509 / 2842 / 4351`; favorable `754 / 1200 / 1954`; favorable_householder `161 / 236 / 397`
- library: canonical_total `1874141`, in_scope `1795165`, outside_scope `78976`, jurisdictions `10`, first_year `"1671"`, last_year `"2019"`, in_scope_display `"about 1.8 million"`
- benchmark: entries `65`, resolved `36`, read `28`, kept `10`, kept_human `8`, unresolved `29`, lost `unsignaled 8 / reader_negative 17 / withdrawn 1 / other 0 / total 26`
- tail: unread `14255`, low `409`, high `1568`
- audit: n `150`, frame_size `2842`, seed `"20260912"`, drawn_seq `83531`, status `"drawn, not yet read"`

Any difference: stop and report it; do not edit the JSON by hand.

- [ ] **Step 3: Confirm the folder is ignored**

Run: `git status --short reports/explainer` and `git check-ignore reports/explainer/snapshot.json`
Expected: the first prints nothing; the second prints the path.

- [ ] **Step 4: Correct the spec's library wording**

In the spec, section 3, replace the step-1 "Plain terms" cell with:

```
About 1.8 million reported opinions from the 10 searched jurisdictions (Cal., Conn., D.C., La., Mass., N.J., N.Y., Ohio, Pa., Tex.), 1671-2019, one frozen snapshot of the Caselaw Access Project; the library also holds about 79 thousand federal and stray opinions outside these searches
```

and in section 8, replace figure 1's row with:

```
| 1 | Size of the library | `corpus.db` canonical (non-duplicate) cases in the 10 domain jurisdictions, plus the out-of-scope remainder | 1,795,165 in scope (1671-2019); 78,976 outside (mostly U.S.); 1,874,141 total |
```

- [ ] **Step 5: Commit the spec correction**

```bash
git add docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md
git commit -m "spec: explainer library figure counts the 10 searched jurisdictions, not the federal set

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Evidence pack

**Files:**
- Create (gitignored): `reports/explainer/evidence.md`, `reports/explainer/evidence_pack.py`

**Interfaces:**
- Consumes: the live ledger at `as_of=83531`, `corpus.db` (`cases`, `signals`, `fts_raw`), `selectors/selectors.yaml`, `runs/cycle-004-shard-02/review-round-3*.json`.
- Produces: `evidence.md` with numbered sections §1-§7. The script (Task 5) cites them as `[evidence: §N]`, and the fact-checker (Task 6) reads them.

- [ ] **Step 1: Write the evidence script**

Create `reports/explainer/evidence_pack.py` (gitignored scratch; it reads live data, so it is never a test):

```python
"""Evidence for the lawyer explainer, read at ledger seq 83531. Writes reports/explainer/evidence.md."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import yaml                                                     # noqa: E402
from export_review_cards import write_text                      # noqa: E402
from corpus_engine import store                                 # noqa: E402
from corpus_engine.domain import load_domain                    # noqa: E402
from corpus_engine.ledger import open_ledger                    # noqa: E402

AS_OF = 83531
CASES = {"ackley": 2279220, "jacobs": 1167707, "peet": 2026536}
SELECTORS = ("boarder-core-03", "relevance-feedback-39", "adverse-embed-regulation-29", "embed-short-letting-23")
view = open_ledger(domain=load_domain()).view(as_of=AS_OF)
conn = store.connect(wal=False)
out: list[str] = [f"# Explainer evidence (ledger seq {AS_OF})", ""]


def case_trail(n: int, key: str, cid: int) -> None:
    name, cite, court, year, jur = conn.execute(
        "SELECT name, cite, court, decision_year, jurisdiction FROM cases WHERE case_id=?", (cid,)).fetchone()
    r = view.record(cid)
    out += [f"## §{n} {key}: {name}, {cite} ({court}, {year}; {jur}); case {cid}", "",
            f"- reviewed tier: {view.reviewed(cid)}; review.status: {r['review'].get('status')}",
            f"- provenance: {json.dumps(view.provenance(cid))}",
            "- fields: " + json.dumps({k: r.get(k) for k in load_domain().judged_fields}, ensure_ascii=False),
            f"- holding_summary (reader): {r.get('holding_summary')}", "", "Signals:"]
    for sid, ver, text, cos, run in conn.execute(
            "SELECT selector_id, selector_version, matched_text, cosine, run_id FROM signals WHERE case_id=?", (cid,)):
        out.append(f"- {sid} v{ver} ({run}; cosine {cos}): {text!r}")
    out += ["", "Quotes:"]
    for q in r.get("quotes", []):
        out.append(f"- [{q.get('status')}; supports {q.get('supports')}; p. {q.get('reporter_page')}] {q['text']}")
    out += ["", "Review notes:"] + [f"- {x}" for x in r["review"].get("notes", [])]
    out += ["", "Ledger history:"]
    for p in view.history(cid):
        who = p.basis.reviewer or p.basis.model or p.basis.rule_id
        out.append(f"- seq {p.seq} {p.at} {p.op} {p.field} = {str(p.new)[:120]!r} | {who} | {p.basis.run_id}")
    out.append("")


for i, (k, cid) in enumerate(CASES.items(), 1):
    case_trail(i, k, cid)

# §4 In re Jacobs across review round 3 (checker, both first passes, the user's 3b decision)
out += ["## §4 In re Jacobs in shard-02 review round 3", ""]
for f in ("review-round-3-checker.json", "review-round-3-decisions-claude.json",
          "review-round-3-decisions-astra.json", "review-round-3b-decisions.json"):
    data = json.loads((ROOT / "runs/cycle-004-shard-02" / f).read_text(encoding="utf-8"))
    hits = re.findall(r"\{[^{}]*\"case_id\": 1167707[^{}]*\}", json.dumps(data, ensure_ascii=False))
    out += [f"- {f}:"] + [f"  - {h[:700]}" for h in hits]
out += ["", "Parallel report check (same decision reported as 98 N.Y. 98?):"]
for row in conn.execute("SELECT case_id, name_abbreviation, cite, court, decision_date, is_duplicate_of FROM cases "
                        "WHERE name_abbreviation LIKE '%Jacobs%' AND decision_year = 1885"):
    out.append(f"- {row}")
out.append("")

# §5 selector definitions
sel = {s["id"]: s for s in yaml.safe_load((ROOT / "selectors/selectors.yaml").read_text(encoding="utf-8"))
       if isinstance(s, dict) and "id" in s}
out += ["## §5 Selector definitions", ""]
for sid in SELECTORS:
    out += [f"### {sid}", "```yaml", yaml.safe_dump(sel.get(sid), allow_unicode=True, sort_keys=False).strip(), "```", ""]

# §6 concordance lines for "lodger" from the original text, a few per era, one per case
j = load_domain().jurisdictions
out += ["## §6 Concordance lines: lodger (raw text, one line per case)", ""]
for era in load_domain().eras:
    rows = conn.execute(
        "SELECT c.case_id, c.name_abbreviation, c.cite, c.decision_year, c.jurisdiction, c.raw_text "
        "FROM fts_raw JOIN cases c ON c.case_id = fts_raw.rowid WHERE fts_raw MATCH 'lodger' "
        f"AND c.is_duplicate_of IS NULL AND c.era_partition = ? AND c.jurisdiction IN ({','.join('?' * len(j))}) "
        "LIMIT 4", (era, *j)).fetchall()
    out.append(f"### {era}")
    for cid, name, cite, year, jur, raw in rows:
        m = re.search(r"lodger", raw, re.I)
        if m:
            left = " ".join(raw[max(0, m.start() - 90):m.start()].split())
            right = " ".join(raw[m.end():m.end() + 90].split())
            out.append(f"- {name}, {cite} ({jur} {year}), case {cid}: …{left} **{m.group(0)}**{right}…")
    out.append("")

# §7 earliest in-scope opinions (checks the "1671" start of the library span)
out += ["## §7 Earliest in-scope opinions", ""]
for row in conn.execute(
        "SELECT case_id, name_abbreviation, cite, jurisdiction, decision_year FROM cases WHERE is_duplicate_of IS NULL "
        f"AND jurisdiction IN ({','.join('?' * len(j))}) ORDER BY decision_year LIMIT 8", j):
    out.append(f"- {row}")

write_text(ROOT / "reports/explainer/evidence.md", "\n".join(out))
print("wrote reports/explainer/evidence.md")
```

- [ ] **Step 2: Run it**

Run: `.venv\Scripts\python reports\explainer\evidence_pack.py`
Expected: `wrote reports/explainer/evidence.md`. If `yaml` is missing, use the parser `corpus_engine.selector` already uses; check with `grep -n "yaml" corpus_engine/selector/model.py`.

- [ ] **Step 3: Check the pack answers the script's questions**

Open `reports/explainer/evidence.md` and confirm, writing a one-line answer under a final `## Findings` heading for each:
1. Ackley: every judged field's provenance is `reader`, and review round 1 notes say "first pass drafted by GPT Astra; confirmed by the reviewer".
2. Ackley: which words the `boarder-core-03` selector matches (from §5), stated in plain terms.
3. Jacobs: the checker's verdict, Claude's decision (`keep`), Astra's (`set relevant false`), the user's 3b decision (`relevant false`), and the adverse selector's plain-terms description.
4. Jacobs: whether the corpus record is the Court of Appeals decision reported at 98 N.Y. 98 (same court, same date). If it can't be confirmed from the store, the fact-check (Task 6) confirms it from the web.
5. Concordance: pick 4-5 lines from different eras and jurisdictions for the primer; note if any line shows a non-letting sense (e.g. an unrelated use of "lodge"). Record the picks by case id.
6. Library span: whether the pre-1700 in-scope opinions (§7) are genuine colonial-era reports or dating artifacts. The script says "1671" only if they are genuine; otherwise it says "the colonial era" and flags the question.

- [ ] **Step 4: No commit** (everything here is gitignored). Record in the task report that the pack exists and list the Findings.

---

### Task 5: The script

**Files:**
- Create (gitignored): `reports/explainer/script.md` (template with placeholders), `reports/explainer/script.rendered.md` (rendered)

**Interfaces:**
- Consumes: `snapshot.json` (Task 3), `evidence.md` (Task 4), spec sections 3-8, the `render`/`lint` CLI (Task 2).
- Produces: `script.md`, the single source of every word on the page (Task 7 copies its text verbatim); section anchors `#p1`-`#p8` matching the page's parts.

**Tag syntax** (at the end of the sentence or table row a tag supports; stripped from the page):
`[repo: path]`, `[ledger: seq N or query]`, `[evidence: §N]`, `[auth: short citation]`. Figures are `{{snap:...}}` placeholders and need no tag. A paragraph with a factual claim and no tag fails review.

- [ ] **Step 1: Write the script from this skeleton**

Create `reports/explainer/script.md` with exactly these parts, in this order, with the drafted text below as the starting point (refine wording; do not drop content the spec requires):

```markdown
# How the right-to-let record was built
<!-- Checkpoint banner -->
{{snap:snapshot.label}} · ledger snapshot of {{snap:snapshot.date_display}} (sequence {{snap:snapshot.as_of}}) · before the audit

## p1 The one-sentence version
A corpus-linguistics study of American case law, run at document-review scale. Every AI judgment has to be backed by a quote checked against the opinion, and every human decision is on the record. [repo: CONTEXT.md] [repo: docs/adr/0009-methodology-defensibility-is-a-hard-requirement.md]
The question it answers: did ordinary owners let rooms and dwellings for short periods for pay, and how did courts treat it? [repo: CONTEXT.md]

## p2 Corpus linguistics in 60 seconds
<!-- what it is in litigation: declare a corpus, show your searches, code what comes back, count; courts have used it for ordinary meaning -->
<!-- 4-5 concordance lines for "lodger" from evidence §6, each with cite, rendered as a KWIC block -->
<!-- the turn -->
Same discipline, different question: not what a word meant to ordinary speakers, but what courts did about letting.

## p3 The five steps
<!-- For each step: plain text (spec section 3, corrected in Task 3), "Corpus linguistics calls it…", "Document review calls it…", "How it's checked", and the case card text for Ackley. At step 4, the In re Jacobs card. -->
### Step 1 The library
### Step 2 The search
### Step 3 The first read
### Step 4 The second look
### Step 5 The record
<!-- the loop-back line: what the reading teaches feeds the next round of searches -->

## p4 How it lines up with corpus-linguistics practice
<!-- the ten crosswalk rows from spec section 6, each with verdict and one-line reason, each tagged [auth: ...] -->

## p5 What the record can and can't say
<!-- figures: relevant two-tier with favorable subsets; opinions read; audit status; "what we know we're missing" = benchmark breakdown + unread-tail range -->
<!-- "Say / Don't say" list below -->

## p6 Retell it
### In 30 seconds
### In 2 minutes

## p7 Tough questions (expander)

## p8 Where this comes from
<!-- snapshot identifiers, glossary, authorities with links -->
```

Drafted text to start from:

*p2, what it is:* "When a court asks what a word ordinarily meant, a corpus linguist doesn't guess. They name a large, fixed collection of real writing (the corpus), show exactly what they searched for, read each hit in context, sort the hits by a protocol written in advance, and count. Courts have relied on the method for ordinary meaning. [auth: People v. Harris, 499 Mich. 332 (2016)] [auth: Lee & Mouritsen, Judging Ordinary Meaning, 127 Yale L.J. 788 (2018)]"

*p3, "How it's checked" lines:* Step 1: "The snapshot is frozen and every file in it is recorded with a fingerprint (a hash), so anyone can rebuild it." Step 2: "Every search is saved with its version and where it ran; searches built to find cases against the claim run too." Step 3: "A computer matches every quote against the opinion's text; an answer whose quote doesn't match is erased." Step 4: "A second AI from a different company re-reads the records chosen for review; where they differ, a person decides, and no machine can overwrite that decision." Step 5: "Every decision is logged with who made it, and every count is recomputed from that log."

*p5, Say / Don't say:*
- Say "at least {{snap:ledger.relevant.total}} relevant reported cases". Don't say "all the cases" or "every case".
- Say "{{snap:ledger.relevant.human_reviewed}} confirmed by a person". Don't say "human-verified" about the other {{snap:ledger.relevant.machine_only}}.
- Say "AI models coded the cases; people decided the contested calls". Don't say "the AI found" or "the AI concluded".
- Say "each quote was matched against the opinion's text". Don't say "pin-cited" or "checked against the printed page".
- Say "a random audit of {{snap:audit.n}} machine-only records is under way". Don't say "audited" or "validated".
- Say "built on established practices". Don't say "a court-approved method".

*p6, 30 seconds:* "We took {{snap:library.in_scope_display}} reported opinions from ten jurisdictions and searched them the way a corpus linguist would: with the period's own words for letting rooms, like 'lodgers' and 'boarders,' and with every search logged. AI models did the first-pass review, like contract reviewers in discovery, but every answer had to be backed by a quote that a computer matched against the opinion. A second AI and a person checked the calls that mattered. Every count says how many a person confirmed, and every count is a minimum."

*p6, 2 minutes:* "Here's how the right-to-let record was built, in five steps. First, the library: {{snap:library.in_scope_display}} reported opinions from the ten jurisdictions we cover, as digitized by Harvard's Caselaw Access Project, frozen so anyone can check our work against the same texts. Second, the search. Corpus linguists find a concept by searching for the words people actually used, and we did the same with the period's vocabulary for letting rooms ('lodgers,' 'boarders,' 'furnished rooms'), plus searches by meaning, searches through citations, and searches built to find cases against us. Every search is logged and versioned. Third, the first read. AI models read {{snap:ledger.opinions_read}} opinions against a fixed codebook, the way contract reviewers work from a review protocol in discovery. Every answer had to be backed by a quote from the opinion, and a computer checked each quote against the text: no matching quote, no answer. Fourth, the second look. A second AI from a different company re-read the records chosen for review; disagreements and the most important records went to a person, and no machine can overwrite a person's decision. That's how a case like In re Jacobs, which quotes a line about the right to rent a house but decides nothing about letting, was thrown out. Fifth, the record. Every decision is logged with who made it. Today the record holds at least {{snap:ledger.relevant.total}} relevant cases: {{snap:ledger.relevant.human_reviewed}} confirmed by a person and {{snap:ledger.relevant.machine_only}} resting on the machine readers. And a random sample of {{snap:audit.n}} of those machine-only records has been drawn for a person to read blind, so we can say how often the machines were right."

*p7:* the seven questions and answers from spec section 4, part 7, with figures as placeholders: `{{snap:benchmark.lost.reader_negative}}` known cases judged "not about letting" and never re-checked.

*p5, "what we know we're missing":* "We tested the search against cases we already knew about from briefs and treatises. Of {{snap:benchmark.resolved}} such cases in the library, the searches found and read {{snap:benchmark.read}}, and {{snap:benchmark.kept}} are in the record as letting cases. Of the rest: {{snap:benchmark.lost.unsignaled}} were never found by any search; {{snap:benchmark.lost.reader_negative}} were read and judged not about letting by the AI reader, and no person has re-checked them; {{snap:benchmark.lost.withdrawn}} was withdrawn by a person. Separately, {{snap:tail.unread}} lower-ranked candidates are still unread; at the yields seen so far they hold an estimated {{snap:tail.low}} to {{snap:tail.high}} more relevant cases." [repo: reports/evaluation-cycle-004.md]

(Spec D1 default: the benchmark is presented from the official evaluation, and today's unadjudicated gold-codebook review is not cited.)

- [ ] **Step 2: Lint the template**

Run: `.venv\Scripts\python tools\explainer_snapshot.py lint --in reports\explainer\script.md --template`
Expected: exit 0, no output. Fix every reported line (replace literal grouped numbers with placeholders).

- [ ] **Step 3: Render**

Run: `.venv\Scripts\python tools\explainer_snapshot.py render --template reports\explainer\script.md --snapshot reports\explainer\snapshot.json --out reports\explainer\script.rendered.md`
Expected: `reports/explainer/script.md -> reports/explainer/script.rendered.md`.

- [ ] **Step 4: Check the reading time of the main path**

Run:
```
.venv\Scripts\python -c "import re; t=open('reports/explainer/script.rendered.md',encoding='utf-8').read(); t=re.sub(r'## p7.*?(?=## p8)','',t,flags=re.S); t=re.sub(r'\[(repo|ledger|evidence|auth):[^\]]*\]|<!--.*?-->','',t,flags=re.S); print(len(t.split()),'words on the main path')"
```
Expected: at most 2,300 words (about ten minutes at lawyer reading speed). Over that, shrink p2 into an expander first (spec section 4, part 2).

- [ ] **Step 5: Self-check against the guardrails**

Walk spec section 7, items 1-11, plus the six-figure cap from spec section 8, and write `reports/explainer/guardrails-check.md` with one line per item: where in the script it is met (part and sentence). Every item must be met. For the cap, list each distinct figure family the script shows (library size, opinions read, relevant two-tier with favorable subsets, audit, benchmark, unread tail); anything outside those six is cut or moved into an expander as prose without a number.

- [ ] **Step 6: No commit** (gitignored). Report the word count and the guardrail sheet.

---

### Task 6: Independent fact-check, then user gate A (script)

**Files:**
- Create (gitignored): `reports/explainer/factcheck.md`
- Modify (gitignored): `reports/explainer/script.md` (fixes), `reports/explainer/script.rendered.md` (re-rendered)
- Create (gitignored): `reports/explainer/sources.md`

**Interfaces:**
- Consumes: `script.md`, `script.rendered.md`, `evidence.md`, `snapshot.json`, the spec.
- Produces: a fact-checked script the user approves; `sources.md` (the provenance record).

- [ ] **Step 1: Dispatch a fresh fact-checker**

Dispatch one `general-purpose` agent (it must not inherit this conversation) with this prompt:

```
You are fact-checking a script for a page that explains a legal-research pipeline to litigators.
Repo: C:\Users\marcu\Desktop\Str-corpus. Read: reports/explainer/script.md (tagged template), reports/explainer/script.rendered.md,
reports/explainer/evidence.md, reports/explainer/snapshot.json, and
docs/superpowers/specs/2026-09-29-lawyer-explainer-checkpoint-1-design.md (sections 6-7).
For EVERY sentence carrying a [repo:], [ledger:], [evidence:] or [auth:] tag, and every sentence stating a
fact without a tag, return one row: claim | tag | verdict (SUPPORTED / UNSUPPORTED / WRONG / OVERSTATED) |
the exact source line or URL | the fix. Rules:
- [repo:] and [evidence:] claims: open the file and quote the supporting line.
- [ledger:] claims: run read-only Python against `open_ledger().view(as_of=83531)` (.venv\Scripts\python).
- [auth:] claims: verify the citation (volume, reporter, page, year, court, author) and the proposition
  against the actual source on the web; say where you read it. Include In re Jacobs = 98 N.Y. 98 (1885)
  and, if the script uses it, Snell v. United Specialty Ins. Co., 102 F.4th 1208 (11th Cir. 2024) (Newsom, J.,
  concurring) for the contrast between an LLM as oracle and an LLM as coder.
- Flag anything that overclaims: completeness, "verified" for machine-only records, court approval,
  page-image checking, dollar figures, or references to right-to-let-guide / attorney-report.
Do not edit any file. Write nothing except your report, returned as your final message.
```

- [ ] **Step 2: Save and apply the report**

Save the agent's report verbatim to `reports/explainer/factcheck.md`. Fix every row not marked SUPPORTED in `script.md`: correct it, soften it, or cut it. Append to `factcheck.md` a `## Resolution` line per row. Apply spec D2 (keep the Newsom contrast only if SUPPORTED and apt) and D3 (Peet in the primer only if a real concordance line fits).

- [ ] **Step 3: Re-lint and re-render**

Run the Task 5 Step 2 and Step 3 commands again.
Expected: both exit 0.

- [ ] **Step 4: Write the provenance record**

Run:
```
git rev-parse HEAD
Get-FileHash -Algorithm SHA256 CONTEXT.md, docs\adr\0009-methodology-defensibility-is-a-hard-requirement.md, reports\evaluation-cycle-004.json, runs\audit-cycle-004\sample-manifest.json, selectors\selectors.yaml, domains\str-right-to-let\codebooks\mapper-v3.md, reports\explainer\snapshot.json | Format-Table -AutoSize
```
Write `reports/explainer/sources.md`: the revision, ledger seq 83531 and `snapshot.inputs.ledger_content_sha256`, each file with its sha256, and the list of authorities with the URL where each was verified (from `factcheck.md`).

- [ ] **Step 5: USER GATE A: script review**

Stop. Tell the user the script is ready at `reports/explainer/script.rendered.md` (and the tagged `script.md`), with `factcheck.md` and `guardrails-check.md` beside it. Ask them to review the wording, the case framing, and the crosswalk verdicts. Apply their changes (re-lint, re-render) until they approve. **No page work before an explicit approval.**

---

### Task 7: The page, with browser QA

**Files:**
- Create (gitignored): `reports/explainer/method-explainer.template.html`, `reports/explainer/method-explainer.html` (rendered)

**Interfaces:**
- Consumes: the approved `script.md` (text copied verbatim, tags stripped), `snapshot.json` via `render`.
- Produces: `method-explainer.html`, the page Task 8 publishes.

- [ ] **Step 1: Load the page contract**

Invoke the `artifact-design` skill (the Artifact tool requires it before a page is written) and follow it for the title (two to four words, e.g. "How the Record Was Built"), colour tokens with light and dark themes, allowed CDNs/fonts, phone-width layout with a 16px gutter, and size limits.

- [ ] **Step 2: Build the template**

Write `reports/explainer/method-explainer.template.html` as one self-contained file:
- **Parts p1-p8** in order, text from the approved script with tags removed. Figures stay as `{{snap:...}}` placeholders; no literal grouped numbers.
- **Checkpoint banner** at the top (label, date, sequence, "before the audit").
- **Five-step diagram:** inline SVG, a numbered line of five stations with a single return arrow from 5 to 2 labelled with the loop-back line; `<title>`/`<desc>` for screen readers; no robot or brain imagery.
- **Layout:** at ≥ 960px, a two-column grid in p3 with the diagram in a `position: sticky` column and the step text beside it. An `IntersectionObserver` marks the active station and swaps the case card (Ackley at steps 1-5; the In re Jacobs card appears at step 4 beside Ackley's). Below 960px, the diagram collapses to a sticky compact indicator (five numbered dots) at the top of p3 and the cards sit inline under each step.
- **Case cards:** name, citation, year, the quote, and for the current step what happened, including "field values are the reader's; a person confirmed them" on Ackley. The In re Jacobs card shows the quoted line, why it was withdrawn, and the adverse search that found it. The card region is `aria-live="polite"`.
- **Crosswalk (p4):** a table with a verdict chip per row. "Departs" rows get the same weight as "Matches" rows (same size and contrast; a different hue, never greyed out).
- **Tough questions (p7):** one `<details>` per question.
- **Register:** serif text face, restrained ink with one accent, generous white space; tokens on `:root`, dark tokens under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` and again under `:root[data-theme="dark"]`; explicit `body` background.
- **Print summary:** a `.print-summary` section, hidden on screen, containing the diagram, the 30-second version, the crosswalk in brief (standard + verdict), and the banner. A "Print summary" button calls `window.print()`. Under `@media print` everything except `.print-summary` is hidden, and the summary fits one US Letter page with 0.5in margins.
- **No `localStorage` needed**; no external scripts.

- [ ] **Step 3: Lint and render**

Run:
```
.venv\Scripts\python tools\explainer_snapshot.py render --template reports\explainer\method-explainer.template.html --snapshot reports\explainer\snapshot.json --out reports\explainer\method-explainer.html
```
Expected: `reports/explainer/method-explainer.template.html -> reports/explainer/method-explainer.html`.

- [ ] **Step 4: Text parity with the approved script**

Run:
```
.venv\Scripts\python -c "import re,html; strip=lambda t: re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'<(script|style)[^>]*>.*?</\1>','',t,flags=re.S)))); page=strip(open('reports/explainer/method-explainer.html',encoding='utf-8').read()); s=open('reports/explainer/script.rendered.md',encoding='utf-8').read(); s=re.sub(r'\[(repo|ledger|evidence|auth):[^\]]*\]|<!--.*?-->|[#*_>|`]','',s,flags=re.S); sents=[x.strip() for x in re.split(r'(?<=[.?!])\s+',re.sub(r'\s+',' ',s)) if len(x.split())>=6]; miss=[x for x in sents if x not in page]; print(len(sents),'sentences;',len(miss),'missing'); print('\n'.join(miss[:20]))"
```
Expected: `0 missing`, or only sentences deliberately restructured into table cells or cards; list each and confirm its wording is unchanged.

- [ ] **Step 5: Browser QA**

Serve the folder: `.venv\Scripts\python -m http.server 8765 --directory reports\explainer` (run in the background). With the Playwright MCP tools (`browser_navigate`, `browser_resize`, `browser_take_screenshot`, `browser_evaluate`, `browser_emulate_media`, `browser_console_messages`), on `http://localhost:8765/method-explainer.html`:
1. At 1280×900: screenshot the top, p3 mid-scroll (the sticky diagram with a highlighted station and the Jacobs card at step 4), p4, and p6.
2. At 390×844: screenshot the same points; `browser_evaluate` `document.documentElement.scrollWidth <= window.innerWidth` must be `true` (no horizontal scroll).
3. `browser_emulate_media` with `colorScheme: 'dark'`: screenshot p1 and p4; text contrast must be readable and verdict chips distinct.
4. `browser_emulate_media` with `media: 'print'`: `browser_evaluate` `document.querySelector('.print-summary').getBoundingClientRect().height` must be ≤ 960 (10in at 96px); screenshot it.
5. `browser_console_messages`: no errors.
Fix and re-render until all five pass, then stop the server.

- [ ] **Step 6: No commit** (gitignored). Report the screenshots taken and the five checks' results.

---

### Task 8: Publish privately, user gate B (page), and wrap up

**Files:**
- Modify: `C:\Users\marcu\.claude\projects\C--Users-marcu-Desktop-Str-corpus\memory\attorney-collaborator.md`, `...\memory\str-corpus-project-state.md`, `...\memory\MEMORY.md`

**Interfaces:**
- Consumes: `reports/explainer/method-explainer.html` (Task 7).
- Produces: the private Artifact URL; the memory pointers Checkpoint 2 needs.

- [ ] **Step 1: Publish privately**

Artifact `publish` with `file_path` = `reports/explainer/method-explainer.html`, `icon` = `scale`, and `description` = "How the right-to-let record was built, and how the method maps onto corpus-linguistics practice (Checkpoint 1, before the audit)." Artifacts start private; do not share or pin.

- [ ] **Step 2: USER GATE B: page review**

Give the user the link and ask them to review it on desktop and phone and try "Print summary". Apply requested changes in the template, re-run the Task 7 Step 3 render and Step 5 checks that the change touches, and republish with the same `file_path` (same URL). Repeat until the user approves. The user shares the link with the team; Claude does not.

- [ ] **Step 3: Record the Checkpoint 2 procedure where it will be found**

Update `attorney-collaborator.md` with the Artifact URL and this procedure: after the audit is applied and the evaluation republished at seq N, run `tools\explainer_snapshot.py snapshot --as-of N --label "Checkpoint 2" ...` (extending `audit_figures` with the audit result first, test-first), update the script's audit lines and p5, re-run the fact-check on changed sentences, re-render, and republish to the same URL. Add a pointer line in `str-corpus-project-state.md`; keep `MEMORY.md` to one line per memory.

- [ ] **Step 4: Finish the branch**

Run the full suite (`.venv\Scripts\python -m pytest tests -q`), confirm `git status` shows no tracked changes under `reports/explainer/`, then use the superpowers:finishing-a-development-branch skill (the user merges locally; push after merge per the project's GitHub memory). The branch carries only: `.gitignore`, `tools/explainer_snapshot.py`, `tests/test_explainer_snapshot.py`, the spec, and this plan.
