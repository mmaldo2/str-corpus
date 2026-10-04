# Ledger Answers and the Running Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the attorney collaborator's first five questions from the existing ledger as reproducible entries in a running log (local master, published to a shared Drive folder).

**Architecture:** A generic engine in `corpus_engine/answers/` (questions-file validation, record selection, citation sets, two-tier summaries, HTML/CSV/JSON rendering) and `corpus_engine/concordance.py` (full-text counts, rates, earliest uses), driven by `tools/gluck_log.py`. The question definitions and every output live in the gitignored `reports/gluck/`; the agent publishes outputs to Drive with the Drive connector.

**Tech Stack:** Python 3.11.15, SQLite FTS5 (`fts_raw`, `fts_porter`), PyYAML, pytest, the Google Drive connector (agent-side).

**Spec:** `docs/superpowers/specs/2026-10-04-ledger-answers-running-log-design.md`

## Global Constraints

- Branch `answers/part-1` in the main checkout (corpus.db and `.venv` are untracked and resolve from the checkout root). The user merges locally.
- Run Python as `.venv/Scripts/python` from the repo root; tests as `.venv/Scripts/python -m pytest -q -p no:cacheprovider`.
- The repository is PUBLIC: nothing under `reports/gluck/` is committed (`.gitignore` gains `reports/gluck/`), and no code, test or commit message mentions the collaborator's own writing.
- Read-only on the ledger and the corpus: corpus connections use `file:<path>?mode=ro` URIs; no ledger `apply`.
- Two-tier counts are never blended: no output adds human-reviewed and machine-only into one number.
- No dollar figures in any output.
- The standing caveats, verbatim: "Counts are lower bounds." / "Machine-only precision is unmeasured until the audit is applied." / "Nothing here is citable before a citator check and a page-image pin-cite check."
- Files UTF-8 with LF line endings (`newline="\n"`; CSV `lineterminator="\n"`).
- Edit with the Edit/Write tools, not shell heredocs (heredocs here have turned "\n" escapes into real newlines).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never add or commit `Gluck Prompts.md`.
- Tasks 6 and 7 are controller tasks (live runs, readings and their fact-check, Drive publishing, the user gate).

## Review Focus

- Unquoted `yes`/`no` in YAML parse as booleans; the questions file must be refused with a hint to quote them, never silently match nothing. (Task 2, parametrized case "quote yes/no".)
- A record whose quotes are all `verified-fuzzy` (no exact `verified`) must give an empty `quote`, never a crash or a fuzzy quote presented as exact. (Task 4, `test_case_rows_carry_...`.)
- A merged copy still counted in the ledger (a human-value group) must list the decision's whole citation set, identical to its twin's. (Task 3, `test_every_copy_of_a_decision_carries_the_whole_citation_set`.)
- A malformed FTS expression in a concordance question must stop the run naming the question and the term, before any output folder is written. (Task 5, `test_a_bad_fts_expression_is_refused_without_writing`.)
- Running the same question twice on one day must keep both outputs (suffix `-2`), never overwrite. (Task 5, `test_a_second_run_the_same_day_gets_its_own_folder`.)

---

### Task 1: Concordance module and the KWIC CLI

**Files:**
- Create: `corpus_engine/concordance.py`
- Modify: `pipeline/kwic.py` (`cmd_freq`, new `cmd_earliest`, `main(argv=None, db=None)`, read-only connection)
- Create: `tests/test_concordance.py`

**Interfaces:**
- Produces: `fts_query(term: str, *, expr: bool = False) -> str`; `cell_counts(conn, term, *, expr=False, stem=False, jur=None) -> dict[tuple[str, str], int]` ((era, jurisdiction) -> matching canonical opinions); `denominators(conn) -> dict[tuple[str, str], int]`; `rate(matches: int, opinions: int) -> float | None`; `by_era(cells) -> dict[str, int]`; `era_table(cells, dens, *, jur=None, eras=None) -> dict[str, dict]` (era -> {"matches", "opinions", "rate"}); `earliest(conn, term, *, expr=False, stem=False, jur=None, n=5, tokens=16) -> list[dict]` (keys case_id, cite, name, year, jurisdiction, context).
- Produces: `pipeline/kwic.py main(argv=None, db=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_concordance.py`:

```python
"""corpus_engine.concordance and the KWIC CLI over the fixture corpus (spec section 5)."""
import importlib.util
import sqlite3
from pathlib import Path
import pytest
from corpus_engine import concordance as cc

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("kwic", ROOT / "pipeline" / "kwic.py")
kwic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kwic)


@pytest.fixture
def conn(fixture_db):
    c = sqlite3.connect(f"file:{fixture_db.as_posix()}?mode=ro", uri=True)
    yield c
    c.close()


def _direct(conn, table, match):
    return conn.execute(f"SELECT count(*) FROM {table} JOIN cases c ON c.case_id = {table}.rowid "
                        f"WHERE {table} MATCH ? AND c.is_duplicate_of IS NULL", (match,)).fetchone()[0]


def test_fts_query_quotes_a_plain_phrase_and_passes_an_expression_through():
    assert cc.fts_query("lodger") == "lodger"
    assert cc.fts_query("taking in lodgers") == '"taking in lodgers"'
    assert cc.fts_query("NEAR(board lodging, 5)", expr=True) == "NEAR(board lodging, 5)"


def test_cell_counts_sum_to_the_canonical_matches(conn):
    cells = cc.cell_counts(conn, "lodger")
    assert sum(cells.values()) == _direct(conn, "fts_raw", "lodger") > 0
    assert all(len(k) == 2 for k in cells)


def test_stemming_widens_and_near_expressions_work(conn):
    raw = sum(cc.cell_counts(conn, "lodger").values())
    stem = sum(cc.cell_counts(conn, "lodger", stem=True).values())
    assert stem >= raw and stem == _direct(conn, "fts_porter", "lodger")
    near = sum(cc.cell_counts(conn, "NEAR(board lodging, 5)", expr=True).values())
    assert near == _direct(conn, "fts_raw", "NEAR(board lodging, 5)") > 0


def test_jurisdiction_filter_and_rates(conn):
    every = cc.cell_counts(conn, "lodger")
    assert cc.cell_counts(conn, "lodger", jur="N.Y.") == {k: v for k, v in every.items() if k[1] == "N.Y."}
    dens = cc.denominators(conn)
    assert sum(dens.values()) == conn.execute(
        "SELECT count(*) FROM cases WHERE is_duplicate_of IS NULL").fetchone()[0]
    assert cc.rate(3, 1500) == 2.0 and cc.rate(1, 0) is None
    table = cc.era_table(every, dens)
    era, row = next(iter(table.items()))
    assert row["opinions"] == sum(v for k, v in dens.items() if k[0] == era)
    assert row["matches"] == cc.by_era(every).get(era, 0)


def test_earliest_uses_are_in_year_order_with_context(conn):
    rows = cc.earliest(conn, "lodger", n=3)
    assert 0 < len(rows) <= 3
    assert [r["year"] for r in rows] == sorted(r["year"] for r in rows)
    assert all("[" in r["context"] for r in rows)


def test_kwic_freq_prints_rates_by_jurisdiction(fixture_db, capsys):
    assert kwic.main(["freq", "lodger", "--rate", "--by", "jurisdiction"], db=fixture_db) == 0
    out = capsys.readouterr().out
    assert "lodger" in out and "N.Y." in out


def test_kwic_earliest_runs_an_expression(fixture_db, capsys):
    assert kwic.main(["earliest", "NEAR(board lodging, 5)", "--expr", "--n", "2"], db=fixture_db) == 0
    assert "[" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_concordance.py`
Expected: FAIL at import (`cannot import name 'concordance'`).

- [ ] **Step 3: Write `corpus_engine/concordance.py`**

```python
"""Concordance over the corpus full-text index (spec 2026-10-04-ledger-answers-running-log,
section 5).

Counts are of canonical opinions (`is_duplicate_of IS NULL`) that match, per era partition and
jurisdiction. `fts_raw` matches exact words ("lodger" and "lodgers" differ); `fts_porter`
(`stem=True`) matches stems. An expression (`expr=True`) is FTS5 syntax passed through unquoted
- `NEAR(a b, 10)`, a prefix `lodg*`, `OR`; a plain term with a space becomes a phrase."""
from __future__ import annotations
from collections import defaultdict
from typing import Mapping, Sequence


def fts_query(term: str, *, expr: bool = False) -> str:
    t = term.strip()
    if expr:
        return t
    return f'"{t}"' if " " in t else t


def _table(stem: bool) -> str:
    return "fts_porter" if stem else "fts_raw"


def cell_counts(conn, term: str, *, expr: bool = False, stem: bool = False,
                jur: str | None = None) -> dict[tuple[str, str], int]:
    """{(era, jurisdiction): canonical opinions matching}."""
    t = _table(stem)
    q = (f"SELECT c.era_partition, c.jurisdiction, count(*) FROM {t} "
         f"JOIN cases c ON c.case_id = {t}.rowid "
         f"WHERE {t} MATCH ? AND c.is_duplicate_of IS NULL")
    params: list = [fts_query(term, expr=expr)]
    if jur:
        q += " AND c.jurisdiction = ?"
        params.append(jur)
    q += " GROUP BY 1, 2"
    return {(e, j): n for e, j, n in conn.execute(q, params)}


def denominators(conn) -> dict[tuple[str, str], int]:
    """Canonical opinions per (era, jurisdiction): the denominators of every rate (one scan)."""
    return {(e, j): n for e, j, n in conn.execute(
        "SELECT era_partition, jurisdiction, count(*) FROM cases "
        "WHERE is_duplicate_of IS NULL GROUP BY 1, 2")}


def rate(matches: int, opinions: int) -> float | None:
    """Matches per 1,000 opinions; None when the cell holds no opinions."""
    return round(1000 * matches / opinions, 3) if opinions else None


def by_era(cells: Mapping[tuple[str, str], int]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for (era, _), n in cells.items():
        out[era] += n
    return dict(out)


def _era_order(eras) -> list[str]:
    return sorted(eras, key=lambda e: (not str(e).startswith("pre"), str(e)))


def era_table(cells: Mapping[tuple[str, str], int], dens: Mapping[tuple[str, str], int], *,
              jur: str | None = None, eras: Sequence[str] | None = None) -> dict[str, dict]:
    """era -> {"matches", "opinions", "rate"}; with `jur`, the denominators are that jurisdiction's."""
    order = list(eras) if eras is not None else _era_order({e for e, _ in dens})
    out = {}
    for e in order:
        m = sum(n for (ce, _), n in cells.items() if ce == e)
        d = sum(n for (de, j), n in dens.items() if de == e and (jur is None or j == jur))
        out[e] = {"matches": m, "opinions": d, "rate": rate(m, d)}
    return out


def earliest(conn, term: str, *, expr: bool = False, stem: bool = False, jur: str | None = None,
             n: int = 5, tokens: int = 16) -> list[dict]:
    """The `n` earliest canonical opinions matching, with a highlighted context line."""
    t = _table(stem)
    q = (f"SELECT c.case_id, c.cite, c.name_abbreviation, c.decision_year, c.jurisdiction, "
         f"snippet({t}, 0, '[', ']', '...', {int(tokens)}) FROM {t} "
         f"JOIN cases c ON c.case_id = {t}.rowid "
         f"WHERE {t} MATCH ? AND c.is_duplicate_of IS NULL AND c.decision_year IS NOT NULL")
    params: list = [fts_query(term, expr=expr)]
    if jur:
        q += " AND c.jurisdiction = ?"
        params.append(jur)
    q += " ORDER BY c.decision_year, c.case_id LIMIT ?"
    params.append(int(n))
    return [{"case_id": cid, "cite": cite, "name": name, "year": year, "jurisdiction": j,
             "context": snip}
            for cid, cite, name, year, j, snip in conn.execute(q, params)]
```

- [ ] **Step 4: Rework `pipeline/kwic.py`**

- Add `sys.path.insert(0, str(ROOT))` after `ROOT` and `from corpus_engine import concordance as cc  # noqa: E402`.
- Replace `cmd_freq` with:

```python
def _eras(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT era_partition FROM cases WHERE era_partition IS NOT NULL ORDER BY era_partition")]


def _fmt(n: int, d: int | None, as_rate: bool) -> str:
    if not as_rate:
        return str(n)
    r = cc.rate(n, d or 0)
    return "-" if r is None else f"{r:g}"


def cmd_freq(conn, args):
    dens = cc.denominators(conn) if args.rate else {}
    eras = _eras(conn)
    unit = "per 1,000 opinions" if args.rate else "opinions matching"
    if args.by == "era":
        print(f"({unit})")
        print("term".ljust(28) + "".join(e.rjust(12) for e in eras))
    for term in args.terms:
        cells = cc.cell_counts(conn, term, expr=args.expr, stem=args.stem, jur=args.jur)
        if args.by == "jurisdiction":
            jurs = sorted({j for _, j in cells} | {j for _, j in dens if not args.jur or j == args.jur})
            print(f"{term}  ({unit})")
            print("era".ljust(12) + "".join(str(j).rjust(9) for j in jurs))
            for e in eras:
                print(e.ljust(12) + "".join(
                    _fmt(cells.get((e, j), 0), dens.get((e, j)), args.rate).rjust(9) for j in jurs))
        else:
            table = cc.era_table(cells, dens, jur=args.jur, eras=eras)
            print(term.ljust(28) + "".join(
                _fmt(table[e]["matches"], table[e]["opinions"], args.rate).rjust(12) for e in eras))


def cmd_earliest(conn, args):
    for r in cc.earliest(conn, args.term, expr=args.expr, stem=args.stem, jur=args.jur, n=args.n):
        print(f"{r['year']}  {r['cite']} ({r['jurisdiction']}) {r['name']} | {r['context']}")
```

- Replace `main` with `def main(argv=None, db=None) -> int:`; in it keep the `kwic` and `colloc` parsers as they are, and:

```python
    f = sub.add_parser("freq")
    f.add_argument("terms", nargs="+")
    f.add_argument("--expr", action="store_true", help="pass each term to FTS5 unquoted (NEAR, prefix*, OR)")
    f.add_argument("--stem", action="store_true", help="use the stemmed index (fts_porter)")
    f.add_argument("--jur")
    f.add_argument("--by", choices=("era", "jurisdiction"), default="era")
    f.add_argument("--rate", action="store_true", help="matches per 1,000 canonical opinions")
    e = sub.add_parser("earliest")
    e.add_argument("term")
    e.add_argument("--expr", action="store_true")
    e.add_argument("--stem", action="store_true")
    e.add_argument("--jur")
    e.add_argument("--n", type=int, default=5)
    args = ap.parse_args(argv)
    conn = sqlite3.connect(f"file:{Path(db or DB).as_posix()}?mode=ro", uri=True)
    {"kwic": cmd_kwic, "colloc": cmd_colloc, "freq": cmd_freq, "earliest": cmd_earliest}[args.cmd](conn, args)
    return 0
```

- Update the module docstring's usage lines with `freq "NEAR(transient lodging, 10)" --expr --stem --rate --by jurisdiction` and `earliest "tourist home" --stem`.

- [ ] **Step 5: Run the tests, then the suite**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_concordance.py` then the full suite.
Expected: 7 passed; full suite 860 passed, 1 xfailed (853 + 7).

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/concordance.py pipeline/kwic.py tests/test_concordance.py
git commit -F - <<'EOF'
concordance: full-text counts per era and jurisdiction, rates per 1,000 opinions, earliest uses; kwic freq gains --expr/--stem/--jur/--by/--rate and an earliest command

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: The questions file

**Files:**
- Create: `corpus_engine/answers/__init__.py` (empty docstring module)
- Create: `corpus_engine/answers/questions.py`
- Create: `tests/test_answers_questions.py`

**Interfaces:**
- Produces: `QuestionError(ValueError)`; `Term(label: str, expr: str, is_expr: bool = False, stem: bool = False)` (frozen); `Question(id: str, title: str, kind: str = "records", population: dict = {}, any_of: tuple = (), group_by: tuple = (), earliest_per_jurisdiction: dict | None = None, text_match: dict | None = None, review_list: bool = False, terms: tuple = ())` (frozen; `population` and each `any_of` item map field -> tuple of values; `text_match` = {"terms": tuple[str], "in": tuple[str]}); `load_questions(path, domain) -> list[Question]`; `VOCAB` (field -> allowed values).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_answers_questions.py`:

```python
"""The questions file: loading and validation (spec section 4)."""
import textwrap
import pytest
from corpus_engine.domain import load_domain
from corpus_engine.answers.questions import QuestionError, load_questions

GOOD = """
- id: q1
  title: Favorable before 1900
  population: {polarity: [favorable], era: [pre-1860, 1860-1900]}
  group_by: [characterization]
- id: q2
  title: Short stays
  population: {polarity: [favorable]}
  any_of:
    - {duration_of_occupancy: [nights, weeks]}
    - {under_thirty_days: ["yes"]}
  group_by: [era, who_was_letting]
- id: q4
  title: Vocabulary
  kind: concordance
  terms:
    - {label: transient near lodging, expr: "NEAR(transient lodging, 10)", fts_expression: true, stem: true}
    - {label: tourist home, expr: tourist home}
- id: q5
  title: Seasonal
  population: {polarity: [favorable], who_was_letting: [non_resident_owner]}
  text_match: {terms: ["season*", summer, furnished house], in: [quotes, holding_summary, opinion]}
  review_list: true
"""


def _write(tmp_path, body):
    p = tmp_path / "questions.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_a_good_file_loads_into_questions(tmp_path):
    qs = load_questions(_write(tmp_path, GOOD), load_domain())
    assert [q.id for q in qs] == ["q1", "q2", "q4", "q5"]
    assert qs[0].population == {"polarity": ("favorable",), "era": ("pre-1860", "1860-1900")}
    assert qs[0].group_by == ("characterization",)
    assert qs[1].any_of == ({"duration_of_occupancy": ("nights", "weeks")}, {"under_thirty_days": ("yes",)})
    assert qs[2].kind == "concordance"
    assert qs[2].terms[0].is_expr and qs[2].terms[0].stem and not qs[2].terms[1].is_expr
    assert qs[3].text_match == {"terms": ("season*", "summer", "furnished house"),
                                "in": ("quotes", "holding_summary", "opinion")}
    assert qs[3].review_list is True


@pytest.mark.parametrize("body, message", [
    ("- {id: q1, title: t, population: {polarity: [favourable]}}", "favourable"),
    ("- {id: q1, title: t, population: {polarty: [favorable]}}", "unknown field 'polarty'"),
    ("- {id: q1, title: t, popluation: {polarity: [favorable]}}", "unknown key 'popluation'"),
    ("- {id: q1, title: t, population: {under_thirty_days: [yes]}}", "quote yes/no"),
    ("- {id: q1, title: t, group_by: [colour]}", "group_by"),
    ("- {id: q1, title: t, population: {era: [1800-1860]}}", "1800-1860"),
    ("- {id: q1, title: t}\n- {id: q1, title: u}", "duplicate id"),
    ("- {id: q1}", "title"),
    ("- {id: q4, title: t, kind: concordance}", "terms"),
    ("- {id: q5, title: t, text_match: {terms: [x], in: [footnotes]}}", "footnotes"),
])
def test_a_bad_file_is_refused_naming_the_problem(tmp_path, body, message):
    with pytest.raises(QuestionError, match=message):
        load_questions(_write(tmp_path, body), load_domain())
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_answers_questions.py`
Expected: FAIL at import.

- [ ] **Step 3: Write the module**

`corpus_engine/answers/__init__.py`:

```python
"""Ledger answers: questions over the counted record, rendered for the running log."""
```

`corpus_engine/answers/questions.py`:

```python
"""The questions file (spec 2026-10-04-ledger-answers-running-log, section 4): load and
validate. Every field and value is checked against the mapper-v3 vocabulary or the domain, so a
typo can never yield a silently empty answer."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from corpus_engine.reader.schema import (CHARACTERIZATION_VALUES, DURATION_VALUES,
                                         OWNER_FREEDOM_VALUES, POLARITY_VALUES,
                                         RESTRICTION_VALUES, UNDER_THIRTY_VALUES, WHO_VALUES)

VOCAB = {"polarity": POLARITY_VALUES, "who_was_letting": WHO_VALUES,
         "duration_of_occupancy": DURATION_VALUES, "characterization": CHARACTERIZATION_VALUES,
         "under_thirty_days": UNDER_THIRTY_VALUES,
         "owner_freedom_characterization": OWNER_FREEDOM_VALUES,
         "restriction_nature": RESTRICTION_VALUES}
KEYS = {"id", "title", "kind", "population", "any_of", "group_by", "earliest_per_jurisdiction",
        "text_match", "review_list", "terms"}
TERM_KEYS = {"label", "expr", "fts_expression", "stem"}
TEXT_IN = ("quotes", "holding_summary", "opinion")


class QuestionError(ValueError):
    ...


@dataclass(frozen=True)
class Term:
    label: str
    expr: str
    is_expr: bool = False
    stem: bool = False


@dataclass(frozen=True)
class Question:
    id: str
    title: str
    kind: str = "records"
    population: dict = field(default_factory=dict)
    any_of: tuple = ()
    group_by: tuple = ()
    earliest_per_jurisdiction: dict | None = None
    text_match: dict | None = None
    review_list: bool = False
    terms: tuple = ()


def _allowed(name: str, domain) -> list | None:
    if name in VOCAB:
        return [v for v in VOCAB[name] if v is not None]
    if name == "era":
        return list(domain.eras)
    if name == "jurisdiction":
        return list(domain.jurisdictions)
    return None


def _mapping(qid: str, where: str, raw, domain) -> dict:
    if not isinstance(raw, dict):
        raise QuestionError(f"{qid}: {where} must be a mapping of field -> values")
    out = {}
    for name, values in raw.items():
        allowed = _allowed(name, domain)
        if allowed is None:
            raise QuestionError(f"{qid}: {where}: unknown field {name!r}")
        values = values if isinstance(values, list) else [values]
        bad = [v for v in values if v not in allowed]
        if bad:
            hint = " (quote yes/no in YAML: unquoted they read as true/false)" if any(
                isinstance(v, bool) for v in bad) else ""
            raise QuestionError(f"{qid}: {where}.{name}: {bad} not in {allowed}{hint}")
        out[name] = tuple(values)
    return out


def _terms(qid: str, raw) -> tuple:
    if not raw or not isinstance(raw, list):
        raise QuestionError(f"{qid}: a concordance question needs a non-empty list of terms")
    out = []
    for k, t in enumerate(raw):
        if not isinstance(t, dict) or not str(t.get("label") or "").strip() or not str(t.get("expr") or "").strip():
            raise QuestionError(f"{qid}: terms[{k}] needs a label and an expr")
        unknown = sorted(set(t) - TERM_KEYS)
        if unknown:
            raise QuestionError(f"{qid}: terms[{k}]: unknown key {unknown[0]!r}")
        out.append(Term(str(t["label"]), str(t["expr"]), bool(t.get("fts_expression", False)),
                        bool(t.get("stem", False))))
    return tuple(out)


def _text_match(qid: str, raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"terms", "in"}:
        raise QuestionError(f"{qid}: text_match takes terms and in")
    terms = raw.get("terms") or []
    if not terms or not all(isinstance(t, str) and t.strip() for t in terms):
        raise QuestionError(f"{qid}: text_match.terms must be a non-empty list of words or phrases")
    where = raw.get("in") or []
    bad = [w for w in where if w not in TEXT_IN]
    if not where or bad:
        raise QuestionError(f"{qid}: text_match.in: {bad or where} not in {list(TEXT_IN)}")
    return {"terms": tuple(terms), "in": tuple(where)}


def load_questions(path, domain) -> list[Question]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if not isinstance(doc, list):
        raise QuestionError(f"{path}: a list of questions expected")
    out, seen = [], set()
    for i, raw in enumerate(doc):
        if not isinstance(raw, dict):
            raise QuestionError(f"question {i + 1}: a mapping expected")
        qid = str(raw.get("id") or "").strip()
        if not qid:
            raise QuestionError(f"question {i + 1}: id is required")
        if qid in seen:
            raise QuestionError(f"{qid}: duplicate id")
        seen.add(qid)
        unknown = sorted(set(raw) - KEYS)
        if unknown:
            raise QuestionError(f"{qid}: unknown key {unknown[0]!r}")
        title = str(raw.get("title") or "").strip()
        if not title:
            raise QuestionError(f"{qid}: title is required")
        kind = raw.get("kind", "records")
        if kind not in ("records", "concordance"):
            raise QuestionError(f"{qid}: kind must be records or concordance")
        if kind == "concordance":
            out.append(Question(qid, title, kind, terms=_terms(qid, raw.get("terms"))))
            continue
        group_by = tuple(raw.get("group_by") or ())
        bad = [g for g in group_by if _allowed(g, domain) is None]
        if bad:
            raise QuestionError(f"{qid}: group_by: unknown field {bad[0]!r}")
        epj = raw.get("earliest_per_jurisdiction")
        out.append(Question(
            qid, title, kind,
            population=_mapping(qid, "population", raw.get("population") or {}, domain),
            any_of=tuple(_mapping(qid, f"any_of[{k}]", m, domain)
                         for k, m in enumerate(raw.get("any_of") or [])),
            group_by=group_by,
            earliest_per_jurisdiction=(_mapping(qid, "earliest_per_jurisdiction", epj, domain)
                                       if epj is not None else None),
            text_match=_text_match(qid, raw.get("text_match")),
            review_list=bool(raw.get("review_list", False))))
    return out
```

- [ ] **Step 4: Run the tests, then the suite**

Expected: 11 passed (1 + 10 parametrized); full suite 871 passed, 1 xfailed.

- [ ] **Step 5: Commit**

```bash
git add corpus_engine/answers/__init__.py corpus_engine/answers/questions.py tests/test_answers_questions.py
git commit -F - <<'EOF'
answers: the questions file, validated against the mapper-v3 vocabulary and the domain (unknown fields, values, keys and unquoted yes/no are refused)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Citation sets with a preferred citation

**Files:**
- Modify: `corpus_engine/domain.py` (`Domain.citation_preference`, loader)
- Modify: `domains/str-right-to-let/domain.yaml` (new `citation_preference` block)
- Create: `corpus_engine/answers/citations.py`
- Create: `tests/test_answers_citations.py`

**Interfaces:**
- Consumes: `corpus_engine.ingest.parallel.winner_map(conn) -> dict[int, int]`.
- Produces: `Domain.citation_preference: Mapping[str, tuple[str, ...]]`; `reporter_of(cite: str) -> str`; `order_cites(cites, preference) -> list[str]`; `citation_sets(conn, case_ids, *, jurisdiction_of: Mapping[int, str], preference: Mapping[str, Sequence[str]]) -> dict[int, list[str]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_answers_citations.py`:

```python
"""Every citation of a decision, preferred first (spec section 3)."""
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.answers.citations import citation_sets, order_cites, reporter_of
from corpus_engine.ingest import parallel as par


def test_reporter_of_reads_the_text_between_volume_and_page():
    assert reporter_of("98 N.Y. 98") == "N.Y."
    assert reporter_of("12 N.Y. St. Rep. 783") == "N.Y. St. Rep."
    assert reporter_of("22 Ohio C.C. (n.s.) 334") == "Ohio C.C. (n.s.)"
    assert reporter_of("not a cite") == ""


def test_order_puts_listed_reporters_first_in_list_order_then_the_rest_alphabetically():
    pref = ("N.Y.", "A.D.", "N.Y.S.")
    got = order_cites(["2 N.Y. Crim. 539", "114 N.Y.S. 789", "98 N.Y. 98", "98 N.Y. 98",
                       "5 Abb. Pr. 1", "62 A.D. 259"], pref)
    assert got == ["98 N.Y. 98", "62 A.D. 259", "114 N.Y.S. 789", "2 N.Y. Crim. 539", "5 Abb. Pr. 1"]


def test_the_domain_prefers_official_state_reports():
    ny = load_domain().citation_preference["N.Y."]
    assert ny[0] == "N.Y." and ny.index("N.Y.") < ny.index("N.Y.S.") < ny.index("N.Y. Crim.")


def test_every_copy_of_a_decision_carries_the_whole_citation_set(tmp_path):
    conn = store.connect(tmp_path / "c.db")
    store.ensure_schema(conn)
    for cid, cite in ((1, "2 N.Y. Crim. 539"), (2, "98 N.Y. 98"), (3, "40 Barb. 1")):
        conn.execute("INSERT INTO cases (case_id, cite, jurisdiction) VALUES (?,?,?)", (cid, cite, "N.Y."))
        conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                     (cid, cite, cite.lower(), "official"))
    conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                 (2, "1 N.Y. Ann. Cas. 5", "1 n.y. ann. cas. 5", "parallel"))
    conn.commit()
    par.apply_merges(conn, [(1, 2, 0.9)], method="m", run_id="r", ts="t")
    pref = {"N.Y.": ("N.Y.", "Barb.", "N.Y. Crim.")}
    sets = citation_sets(conn, [1, 2, 3], jurisdiction_of={1: "N.Y.", 2: "N.Y.", 3: "N.Y."},
                         preference=pref)
    assert sets[1] == sets[2] == ["98 N.Y. 98", "2 N.Y. Crim. 539", "1 N.Y. Ann. Cas. 5"]
    assert sets[3] == ["40 Barb. 1"]
    conn.close()
```

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL at import.

- [ ] **Step 3: Domain field and preference lists**

In `corpus_engine/domain.py`: add `field` to the `dataclasses` import; append to `Domain` (last field):
`citation_preference: Mapping[str, tuple[str, ...]] = field(default_factory=dict)`;
and in `load_domain`'s `Domain(...)` call add
`citation_preference={k: tuple(v) for k, v in (cfg.get("citation_preference") or {}).items()},`.

Append to `domains/str-right-to-let/domain.yaml`:

```yaml
citation_preference:   # reporter abbreviations, official state reports first (answers spec section 3)
  N.Y.: [N.Y., N.Y.2d, N.Y.3d, A.D., A.D.2d, A.D.3d, Misc., Misc.2d, Misc.3d, Barb., Hun, Abb. Pr., Abb. Pr. (n.s.), How. Pr., Daly, E.D. Smith, N.Y. Sup. Ct., N.Y.S., N.Y.S.2d, N.Y.S.3d, N.Y. St. Rep., N.Y. Crim.]
  Tex.: [Tex., Tex. Crim., Tex. Civ. App., S.W., S.W.2d, S.W.3d]
  Ohio: [Ohio St., Ohio St. 2d, Ohio St. 3d, Ohio, Ohio App., Ohio App. 2d, Ohio App. 3d, Ohio C.C., Ohio C.C. (n.s.), Ohio C.C. Dec., Ohio Law Abs., N.E., N.E.2d]
  Pa.: [Pa., Pa. Super., Pa. Commw., A., A.2d, A.3d]
  Mass.: [Mass., Mass. App. Ct., N.E., N.E.2d]
  Conn.: [Conn., Conn. App., Conn. Supp., A., A.2d]
  N.J.: [N.J., N.J.L., N.J. Eq., N.J. Super., N.J. Tax, A., A.2d]
  Cal.: [Cal., Cal. 2d, Cal. 3d, Cal. 4th, Cal. App., Cal. App. 2d, Cal. App. 3d, Cal. App. 4th, P., P.2d, Cal. Rptr.]
  La.: [La., La. Ann., La. App., So., So. 2d]
  D.C.: [App. D.C., D.C., F.2d, A.2d]
  U.S.: [U.S., F. Cas., F., F.2d]
```

- [ ] **Step 4: Write `corpus_engine/answers/citations.py`**

```python
"""Every citation of a decision, preferred citation first (spec section 3).

A decision's citations are the kept record's own cite, CAP's `citations` rows for it, and the
cites of every case merged into it as a parallel report (and of the case it was merged into, when
the record is itself a merged copy). CAP's `official` type is not used for order: it marks each
case's own cite in every reporter (spec section 10). Order is the jurisdiction's preference list
from the domain, then everything else alphabetically."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Iterable, Mapping, Sequence
from corpus_engine.ingest.parallel import winner_map

_REPORTER = re.compile(r"^\s*\d+\s+(.+?)\s+\d+\s*$")


def reporter_of(cite: str) -> str:
    m = _REPORTER.match(cite or "")
    return m.group(1).strip() if m else ""


def order_cites(cites: Iterable[str], preference: Sequence[str]) -> list[str]:
    rank = {r: i for i, r in enumerate(preference)}
    uniq = list(dict.fromkeys(c.strip() for c in cites if c and c.strip()))
    listed = sorted((c for c in uniq if reporter_of(c) in rank), key=lambda c: (rank[reporter_of(c)], c))
    rest = sorted(c for c in uniq if reporter_of(c) not in rank)
    return listed + rest


def citation_sets(conn, case_ids: Iterable[int], *, jurisdiction_of: Mapping[int, str],
                  preference: Mapping[str, Sequence[str]]) -> dict[int, list[str]]:
    ids = [int(c) for c in case_ids]
    winner_of = winner_map(conn)
    members: dict[int, set[int]] = defaultdict(set)
    for loser, winner in winner_of.items():
        members[winner].add(loser)
    group = {cid: {winner_of.get(cid, cid)} | members.get(winner_of.get(cid, cid), set()) for cid in ids}
    every = sorted(set().union(*group.values())) if group else []
    raw: dict[int, list[str]] = defaultdict(list)
    for i in range(0, len(every), 500):
        chunk = every[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, cite in conn.execute(f"SELECT case_id, cite FROM cases WHERE case_id IN ({ph})", chunk):
            raw[cid].append(cite)
        for cid, cite in conn.execute(f"SELECT case_id, cite FROM citations WHERE case_id IN ({ph})", chunk):
            raw[cid].append(cite)
    return {cid: order_cites([c for m in sorted(group[cid]) for c in raw.get(m, [])],
                             preference.get(jurisdiction_of.get(cid), ()))
            for cid in ids}
```

- [ ] **Step 5: Run the tests, then the suite**

Expected: 4 passed; full suite 875 passed, 1 xfailed.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/domain.py domains/str-right-to-let/domain.yaml corpus_engine/answers/citations.py tests/test_answers_citations.py
git commit -F - <<'EOF'
answers: citation sets (own cite, CAP parallel cites, merged copies' cites) ordered by a per-jurisdiction reporter preference in the domain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Selecting records, case rows and two-tier summaries

**Files:**
- Modify: `corpus_engine/ledger/tally.py` (add `counted_records`)
- Create: `corpus_engine/answers/records.py`
- Create: `tests/test_answers_records.py`

**Interfaces:**
- Consumes: Task 2 `Question`.
- Produces: `tally.counted_records(view) -> list[dict]`; in `records`: `COLUMNS`, `REVIEWER_COLUMNS`, `FIELDS`; `era_of(rec, domain) -> str`; `matches(rec, era, mapping) -> bool`; `record_text_hits(records, terms, where) -> set[int]`; `opinion_text_hits(conn, case_ids, terms) -> set[int]`; `select(view, domain, question, *, conn=None) -> list[dict]` (sorted by year, case_id); `names_and_courts(conn, case_ids) -> dict[int, tuple[str, str]]`; `case_rows(records, *, domain, reviewed, names, citations) -> list[dict]`; `summary(records, *, domain, reviewed, group_by) -> dict` (keys total, by_jurisdiction_era, by_group); `earliest_per_jurisdiction(records, mapping, *, domain) -> list[dict]` (keys jurisdiction, case_id, year, cite).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_answers_records.py`:

```python
"""Selecting counted records, case rows and two-tier summaries (spec sections 3-4)."""
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch
from corpus_engine.answers.questions import Question
from corpus_engine.answers import records as ar

READER = Basis(model="m", prompt_version="v", run_id="r")
USER = Basis(reviewer="marcus", run_id="x")
MERGE = Basis(rule_id="parallel-report-merge-v1", run_id="m")


def _rec(cid, year, *, relevant=True, polarity="favorable", who="householder", duration="nights",
         u30="yes", char="lodging", freedom="incident_of_ownership", restriction=None, jur="N.Y.",
         holding="h", quotes=(("q", "verified", "12"),)):
    return {"case_id": cid, "cite": f"{cid} N.Y. 1", "year": year, "jurisdiction": jur,
            "relevant": relevant, "polarity": polarity if relevant else None,
            "who_was_letting": who, "duration_of_occupancy": duration, "characterization": char,
            "under_thirty_days": u30, "owner_freedom_characterization": freedom,
            "restriction_nature": restriction, "holding_summary": holding,
            "quotes": [{"text": t, "supports": ["polarity"], "status": s, "reporter_page": p}
                       for t, s, p in quotes],
            "extraction_status": "ok"}


def _view(tmp_path, recs, *, reviewed=(), copies=()):
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    led.apply([Patch(r["case_id"], "admit", "", r, "v", READER, cycle="cycle-004") for r in recs], note="seed")
    more = [Patch(c, "set", "polarity", "favorable", "u", USER) for c in reviewed]
    more += [Patch(c, "set", "duplicate_of", w, "copy", MERGE, cycle="cycle-004") for c, w in copies]
    if more:
        led.apply(more, note="more")
    return led.view()


def test_select_applies_population_any_of_and_era_and_skips_copies_and_irrelevant(tmp_path):
    v = _view(tmp_path, [_rec(1, 1850), _rec(2, 1880, duration="months", u30="no"), _rec(3, 1950),
                         _rec(4, 1850, relevant=False), _rec(5, 1855)], copies=[(5, 1)])
    dom = load_domain()
    q = Question("q", "t", population={"polarity": ("favorable",), "era": ("pre-1860", "1860-1900")})
    assert [r["case_id"] for r in ar.select(v, dom, q)] == [1, 2]
    q2 = Question("q", "t", population={"polarity": ("favorable",)},
                  any_of=({"duration_of_occupancy": ("nights", "weeks")}, {"under_thirty_days": ("yes",)}))
    assert [r["case_id"] for r in ar.select(v, dom, q2)] == [1, 3]


def test_text_match_reads_quotes_holdings_and_opinion_text(tmp_path):
    v = _view(tmp_path, [_rec(1, 1850, holding="a summer cottage let furnished"),
                         _rec(2, 1850, quotes=(("for the season", "verified", "3"),)),
                         _rec(3, 1850), _rec(4, 1850)])
    conn = store.connect(tmp_path / "c.db")
    store.ensure_schema(conn)
    store.ensure_fts(conn)
    for cid, text in ((3, "the whole furnished house was let"), (4, "nothing relevant here")):
        conn.execute("INSERT INTO cases (case_id, norm_text) VALUES (?,?)", (cid, text))
    conn.execute("INSERT INTO fts_raw(fts_raw) VALUES('rebuild')")
    conn.commit()
    q = Question("q", "t", text_match={"terms": ("season*", "cottage", "furnished house"),
                                       "in": ("quotes", "holding_summary", "opinion")})
    assert [r["case_id"] for r in ar.select(v, load_domain(), q, conn=conn)] == [1, 2, 3]
    only_quotes = Question("q", "t", text_match={"terms": ("furnished house",), "in": ("quotes",)})
    assert ar.select(v, load_domain(), only_quotes) == []
    conn.close()


def test_case_rows_carry_names_citations_quotes_tiers_and_blank_reviewer_columns(tmp_path):
    v = _view(tmp_path, [_rec(1, 1850), _rec(2, 1880, quotes=(("fuzzy", "verified-fuzzy", "4"),))],
              reviewed=[1])
    dom = load_domain()
    rows = ar.case_rows(ar.select(v, dom, Question("q", "t")), domain=dom, reviewed=v.reviewed_ids(),
                        names={1: ("A v. B", "Court of Appeals")},
                        citations={1: ["98 N.Y. 98", "2 N.Y. Crim. 539"]})
    assert list(rows[0]) == list(ar.COLUMNS)
    assert rows[0]["case_name"] == "A v. B" and rows[0]["court"] == "Court of Appeals"
    assert rows[0]["citations"] == "98 N.Y. 98; 2 N.Y. Crim. 539" and rows[0]["era"] == "pre-1860"
    assert rows[0]["quote"] == "q" and rows[0]["quote_page"] == "12"
    assert rows[0]["review_tier"] == "human-reviewed"
    assert rows[1]["quote"] == "" and rows[1]["quote_page"] == "" and rows[1]["review_tier"] == "machine-only"
    assert rows[1]["citations"] == "2 N.Y. 1"
    assert all(rows[0][c] == "" for c in ar.REVIEWER_COLUMNS)


def test_summary_is_two_tier_by_jurisdiction_era_and_group(tmp_path):
    v = _view(tmp_path, [_rec(1, 1850), _rec(2, 1850, char="lease"), _rec(3, 1880, jur="Tex.")],
              reviewed=[1])
    dom = load_domain()
    s = ar.summary(ar.select(v, dom, Question("q", "t")), domain=dom, reviewed=v.reviewed_ids(),
                   group_by=("characterization",))
    assert s["total"] == {"human_reviewed": 1, "machine_only": 2}
    assert {(c["jurisdiction"], c["era"]): (c["human_reviewed"], c["machine_only"])
            for c in s["by_jurisdiction_era"]} == {("N.Y.", "pre-1860"): (1, 1), ("Tex.", "1860-1900"): (0, 1)}
    assert {c["key"]["characterization"]: (c["human_reviewed"], c["machine_only"])
            for c in s["by_group"]} == {"lodging": (1, 1), "lease": (0, 1)}


def test_earliest_per_jurisdiction(tmp_path):
    v = _view(tmp_path, [_rec(1, 1920, polarity="adverse", restriction="zoning"),
                         _rec(2, 1915, polarity="adverse", restriction="zoning"),
                         _rec(3, 1930, polarity="adverse", restriction="zoning", jur="Tex."),
                         _rec(4, 1900, polarity="adverse", restriction="licensing")])
    dom = load_domain()
    recs = ar.select(v, dom, Question("q", "t", population={"polarity": ("adverse",)}))
    got = ar.earliest_per_jurisdiction(recs, {"restriction_nature": ("zoning",)}, domain=dom)
    assert [(g["jurisdiction"], g["case_id"], g["year"]) for g in got] == [("N.Y.", 2, 1915), ("Tex.", 3, 1930)]
```

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL at import.

- [ ] **Step 3: `counted_records` in `corpus_engine/ledger/tally.py`** (after `_population`)

```python
def counted_records(view) -> list[dict]:
    """The records every count is taken over (relevant, in the cycle files, not a parallel copy),
    in ledger order."""
    return [r for _, r in _population(view)]
```

- [ ] **Step 4: Write `corpus_engine/answers/records.py`**

```python
"""Ledger answers: select counted records, build case rows, and summarise them in two tiers
(spec 2026-10-04-ledger-answers-running-log, sections 3-4). Read-only on the ledger and corpus."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Iterable, Mapping, Sequence
from corpus_engine.ledger.tally import counted_records
from corpus_engine.store import era_partition

FIELDS = ("who_was_letting", "polarity", "characterization", "owner_freedom_characterization",
          "duration_of_occupancy", "under_thirty_days", "restriction_nature", "holding_summary")
REVIEWER_COLUMNS = ("reviewer_verdict", "reviewer_field", "reviewer_value", "reviewer_note")
COLUMNS = (("case_name", "citations", "year", "era", "jurisdiction", "court") + FIELDS
           + ("quote", "quote_page", "review_tier", "case_id") + REVIEWER_COLUMNS)


def era_of(rec: Mapping, domain) -> str:
    return era_partition(rec.get("year"), domain.era_bounds)


def matches(rec: Mapping, era: str, mapping: Mapping[str, Sequence]) -> bool:
    return all((era if f == "era" else rec.get(f)) in vals for f, vals in mapping.items())


def _pattern(term: str) -> re.Pattern:
    t = term.strip()
    if t.endswith("*"):
        return re.compile(r"\b" + re.escape(t[:-1]), re.I)
    return re.compile(r"\b" + re.escape(t) + r"\b", re.I)


def record_text_hits(records: Iterable[Mapping], terms: Sequence[str], where: Sequence[str]) -> set[int]:
    pats = [_pattern(t) for t in terms]
    hits = set()
    for r in records:
        texts = []
        if "quotes" in where:
            texts += [q.get("text") or "" for q in r.get("quotes") or ()]
        if "holding_summary" in where:
            texts.append(r.get("holding_summary") or "")
        if any(p.search(t) for p in pats for t in texts):
            hits.add(int(r["case_id"]))
    return hits


def _fts_term(term: str) -> str:
    t = term.strip()
    star = t.endswith("*")
    core = t[:-1] if star else t
    return (f'"{core}"' + ("*" if star else "")) if " " in core else t


def opinion_text_hits(conn, case_ids: Iterable[int], terms: Sequence[str]) -> set[int]:
    """Opinion-text matches through `fts_raw`, restricted to `case_ids`."""
    expr = " OR ".join(_fts_term(t) for t in terms)
    ids = sorted({int(c) for c in case_ids})
    hits: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        hits |= {int(r[0]) for r in conn.execute(
            f"SELECT rowid FROM fts_raw WHERE fts_raw MATCH ? AND rowid IN ({ph})", [expr, *chunk])}
    return hits


def select(view, domain, question, *, conn=None) -> list[dict]:
    recs = []
    for r in counted_records(view):
        era = era_of(r, domain)
        if not matches(r, era, question.population):
            continue
        if question.any_of and not any(matches(r, era, m) for m in question.any_of):
            continue
        recs.append(r)
    if question.text_match:
        terms, where = question.text_match["terms"], question.text_match["in"]
        hits = record_text_hits(recs, terms, where)
        if "opinion" in where:
            if conn is None:
                raise ValueError(f"{question.id}: text_match in opinion needs a corpus connection")
            hits |= opinion_text_hits(conn, [r["case_id"] for r in recs], terms)
        recs = [r for r in recs if int(r["case_id"]) in hits]
    return sorted(recs, key=lambda r: (r.get("year") or 0, r["case_id"]))


def names_and_courts(conn, case_ids: Iterable[int]) -> dict[int, tuple[str, str]]:
    ids = sorted({int(c) for c in case_ids})
    out = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for cid, name, court in conn.execute(
                f"SELECT case_id, name_abbreviation, court FROM cases WHERE case_id IN ({ph})", chunk):
            out[int(cid)] = (name or "", court or "")
    return out


def _first_verified_quote(rec: Mapping) -> Mapping:
    return next((q for q in rec.get("quotes") or () if q.get("status") == "verified"), {})


def case_rows(records: Iterable[Mapping], *, domain, reviewed: set[int],
              names: Mapping[int, tuple[str, str]], citations: Mapping[int, Sequence[str]]) -> list[dict]:
    rows = []
    for r in records:
        cid = int(r["case_id"])
        name, court = names.get(cid, ("", ""))
        q = _first_verified_quote(r)
        row = {"case_name": name, "citations": "; ".join(citations.get(cid) or [r.get("cite") or ""]),
               "year": r.get("year"), "era": era_of(r, domain), "jurisdiction": r.get("jurisdiction"),
               "court": court}
        row.update({f: r.get(f) for f in FIELDS})
        row.update({"quote": q.get("text", ""), "quote_page": q.get("reporter_page", ""),
                    "review_tier": "human-reviewed" if cid in reviewed else "machine-only",
                    "case_id": cid})
        row.update({c: "" for c in REVIEWER_COLUMNS})
        rows.append(row)
    return rows


def summary(records: Iterable[Mapping], *, domain, reviewed: set[int],
            group_by: Sequence[str]) -> dict:
    """Two-tier counts: total, by jurisdiction x era, and by the question's grouping. Never a
    blended total (ADR-0002)."""
    total = [0, 0]
    cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    groups: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in records:
        tier = 0 if int(r["case_id"]) in reviewed else 1
        era = era_of(r, domain)
        total[tier] += 1
        cells[(r.get("jurisdiction"), era)][tier] += 1
        groups[tuple(era if f == "era" else r.get(f) for f in group_by)][tier] += 1
    order = {e: i for i, e in enumerate(domain.eras)}
    return {
        "total": {"human_reviewed": total[0], "machine_only": total[1]},
        "by_jurisdiction_era": [
            {"jurisdiction": j, "era": e, "human_reviewed": h, "machine_only": m}
            for (j, e), (h, m) in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), order.get(kv[0][1], 99)))],
        "by_group": [
            {"key": dict(zip(group_by, k)), "human_reviewed": h, "machine_only": m}
            for k, (h, m) in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0]))],
    }


def earliest_per_jurisdiction(records: Iterable[Mapping], mapping: Mapping[str, Sequence], *,
                              domain) -> list[dict]:
    best: dict[str, Mapping] = {}
    for r in records:
        if not matches(r, era_of(r, domain), mapping):
            continue
        j = r.get("jurisdiction")
        key = (r.get("year") or 9999, r["case_id"])
        if j not in best or key < (best[j].get("year") or 9999, best[j]["case_id"]):
            best[j] = r
    return [{"jurisdiction": j, "case_id": int(r["case_id"]), "year": r.get("year"), "cite": r.get("cite")}
            for j, r in sorted(best.items(), key=lambda kv: str(kv[0]))]
```

- [ ] **Step 5: Run the tests, then the suite**

Expected: 5 passed; full suite 880 passed, 1 xfailed.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/ledger/tally.py corpus_engine/answers/records.py tests/test_answers_records.py
git commit -F - <<'EOF'
answers: select counted records (population, any_of, era, text in quotes/holdings/opinions), case rows with blank reviewer columns, two-tier summaries, earliest per jurisdiction

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Rendering and the tool

**Files:**
- Create: `corpus_engine/answers/render.py`
- Create: `tools/gluck_log.py`
- Modify: `.gitignore` (add `reports/gluck/`)
- Create: `tests/test_gluck_log_tool.py`

**Interfaces:**
- Consumes: Tasks 1-4 (`concordance`, `questions`, `citations`, `records`).
- Produces: `render.CAVEATS`, `render.COUNT_COLUMNS`, `render.REVIEW_LIST_LABEL`, `write_text(path, text)`, `write_csv(path, rows, columns)`, `append_log(path, line)`, `stamp(view, questions_path, *, repo, date) -> dict`, `question_json(q) -> dict`, `method_line(q) -> str`, `answer_html(q, stamp, *, n_rows, reading=None, summary=None, earliest=None, concordance=None) -> str`; CLI `tools/gluck_log.py [--root --db --ledger --date] {run [--question ID ...] [--all] | list}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gluck_log_tool.py`:

```python
"""tools/gluck_log.py end to end over a temporary store and ledger (spec sections 6-7)."""
import importlib.util
import json
from pathlib import Path
import pytest
from corpus_engine import store
from corpus_engine.domain import load_domain
from corpus_engine.ledger import open_ledger
from corpus_engine.ledger.types import Basis, Patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gluck_log", ROOT / "tools" / "gluck_log.py")
gl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gl)

QUESTIONS = """
- id: q1
  title: Favorable before 1900
  population: {polarity: [favorable], era: [pre-1860, 1860-1900]}
  group_by: [characterization]
- id: q3
  title: Adverse by restriction
  population: {polarity: [adverse]}
  group_by: [restriction_nature, era]
  earliest_per_jurisdiction: {restriction_nature: [zoning]}
- id: q4
  title: Vocabulary
  kind: concordance
  terms:
    - {label: lodger, expr: lodger}
    - {label: board near lodging, expr: "NEAR(board lodging, 5)", fts_expression: true}
"""


def _rec(cid, year, polarity, restriction=None):
    return {"case_id": cid, "cite": "x", "year": year, "jurisdiction": "N.Y.", "relevant": True,
            "polarity": polarity, "who_was_letting": "householder", "duration_of_occupancy": "nights",
            "characterization": "lodging", "under_thirty_days": "yes",
            "owner_freedom_characterization": "incident_of_ownership", "restriction_nature": restriction,
            "holding_summary": "h", "extraction_status": "ok",
            "quotes": [{"text": "q", "supports": ["polarity"], "status": "verified", "reporter_page": "99"}]}


def _install(tmp_path):
    root = tmp_path / "gluck"
    root.mkdir()
    (root / "questions.yaml").write_text(QUESTIONS, encoding="utf-8")
    db = tmp_path / "c.db"
    conn = store.connect(db)
    store.ensure_schema(conn)
    store.ensure_fts(conn)
    for cid, name, court, cite, year, era, text in (
            (1, "Smith v. Jones", "Court of Appeals", "98 N.Y. 98", 1850, "pre-1860", "a lodger and his board and lodging"),
            (2, "Doe v. Roe", "Supreme Court", "40 Barb. 1", 1925, "1900-1930", "zoning of a lodging house")):
        conn.execute("INSERT INTO cases (case_id, name_abbreviation, court, cite, jurisdiction, decision_year, "
                     "era_partition, norm_text) VALUES (?,?,?,?,?,?,?,?)", (cid, name, court, cite, "N.Y.", year, era, text))
    conn.execute("INSERT INTO fts_raw(fts_raw) VALUES('rebuild')")
    conn.execute("INSERT INTO fts_porter(fts_porter) VALUES('rebuild')")
    conn.commit()
    conn.close()
    led = open_ledger(tmp_path / "ledger", domain=load_domain())
    reader = Basis(model="m", prompt_version="v", run_id="r")
    led.apply([Patch(1, "admit", "", _rec(1, 1850, "favorable"), "v", reader, cycle="cycle-004"),
               Patch(2, "admit", "", _rec(2, 1925, "adverse", "zoning"), "v", reader, cycle="cycle-004")],
              note="seed")
    return root, ["--root", str(root), "--db", str(db), "--ledger", str(tmp_path / "ledger"),
                  "--date", "2026-10-05"]


def test_run_writes_the_answers_and_the_log(tmp_path):
    root, common = _install(tmp_path)
    assert gl.main(common + ["run", "--all"]) == 0
    out = sorted(p.name for p in (root / "out").iterdir())
    assert out == ["2026-10-05-q1-favorable-before-1900", "2026-10-05-q3-adverse-by-restriction",
                   "2026-10-05-q4-vocabulary"]
    q1 = root / "out" / out[0]
    csv_text = (q1 / "cases.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("case_name,citations,") and csv_text.splitlines()[0].endswith("reviewer_note")
    assert "Smith v. Jones" in csv_text and "98 N.Y. 98" in csv_text
    assert b"\r\n" not in (q1 / "cases.csv").read_bytes()
    html = (q1 / "answer.html").read_text(encoding="utf-8")
    assert "Ledger seq 2" in html and "Counts are lower bounds." in html and "pin-cite" in html
    assert "polarity is favorable" in html
    doc = json.loads((q1 / "summary.json").read_text(encoding="utf-8"))
    assert doc["summary"]["total"] == {"human_reviewed": 0, "machine_only": 1}
    assert doc["stamp"]["ledger_seq"] == 2 and doc["question"]["id"] == "q1"
    q3 = json.loads((root / "out" / out[1] / "summary.json").read_text(encoding="utf-8"))
    assert [e["case_id"] for e in q3["earliest"]] == [2] and q3["earliest"][0]["case_name"] == "Doe v. Roe"
    counts = (root / "out" / out[2] / "counts.csv").read_text(encoding="utf-8").splitlines()
    assert counts[0] == "term,era,jurisdiction,matches,opinions,rate_per_1000"
    assert "lodger,pre-1860,N.Y.,1,1,1000.0" in counts
    log = (root / "log.md").read_text(encoding="utf-8")
    assert sum(1 for line in log.splitlines() if line.startswith("- 2026-10-05")) == 3
    assert "Drive: unpublished" in log


def test_a_second_run_the_same_day_gets_its_own_folder(tmp_path):
    root, common = _install(tmp_path)
    gl.main(common + ["run", "--question", "q1"])
    gl.main(common + ["run", "--question", "q1"])
    assert sorted(p.name for p in (root / "out").iterdir()) == [
        "2026-10-05-q1-favorable-before-1900", "2026-10-05-q1-favorable-before-1900-2"]


def test_a_bad_fts_expression_is_refused_without_writing(tmp_path):
    root, common = _install(tmp_path)
    (root / "questions.yaml").write_text(
        "- id: q9\n  title: Bad\n  kind: concordance\n  terms:\n"
        "    - {label: bad, expr: 'NEAR(', fts_expression: true}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="q9.*bad"):
        gl.main(common + ["run", "--all"])
    assert not (root / "out").exists()


def test_unknown_questions_and_a_bad_file_are_refused(tmp_path):
    root, common = _install(tmp_path)
    with pytest.raises(SystemExit, match="no such question: q7"):
        gl.main(common + ["run", "--question", "q7"])
    (root / "questions.yaml").write_text("- {id: q1, title: t, population: {polarity: [favourable]}}\n",
                                         encoding="utf-8")
    with pytest.raises(SystemExit, match="favourable"):
        gl.main(common + ["run", "--all"])


LIVE = ROOT / "data" / "db" / "corpus.db"


@pytest.mark.live_db
@pytest.mark.skipif(not LIVE.exists(), reason="no live corpus")
def test_live_question_one_has_a_two_tier_summary(tmp_path):
    root = tmp_path / "gluck"
    root.mkdir()
    (root / "questions.yaml").write_text(
        "- id: q1\n  title: Live\n  population: {polarity: [favorable], era: [pre-1860], "
        "owner_freedom_characterization: [incident_of_ownership]}\n  group_by: [characterization]\n",
        encoding="utf-8")
    assert gl.main(["--root", str(root), "--date", "2026-10-05", "run", "--all"]) == 0
    doc = json.loads(next((root / "out").iterdir()).joinpath("summary.json").read_text(encoding="utf-8"))
    total = doc["summary"]["total"]
    assert total["human_reviewed"] + total["machine_only"] > 0
```

- [ ] **Step 2: Run them to see them fail**

Expected: FAIL (`tools/gluck_log.py` does not exist).

- [ ] **Step 3: Write `corpus_engine/answers/render.py`**

```python
"""HTML, CSV and JSON for a ledger answer (spec 2026-10-04-ledger-answers-running-log, section 6)."""
from __future__ import annotations
import csv
import dataclasses
import hashlib
import html
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Sequence

CAVEATS = ("Counts are lower bounds.",
           "Machine-only precision is unmeasured until the audit is applied.",
           "Nothing here is citable before a citator check and a page-image pin-cite check.")
COUNT_COLUMNS = ("term", "era", "jurisdiction", "matches", "opinions", "rate_per_1000")
REVIEW_LIST_LABEL = "Candidates for review, not a finding."
STYLE = ("<style>body{font-family:Georgia,serif;max-width:60em;margin:2em auto;line-height:1.4}"
         "table{border-collapse:collapse;margin:.5em 0 1.5em}td,th{border:1px solid #999;padding:.2em .5em;"
         "text-align:left}.stamp{color:#555}</style>")


def write_text(path, text: str) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_csv(path, rows: Iterable[Mapping], columns: Sequence[str]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columns), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: "" if r.get(c) is None else r.get(c) for c in columns})


def append_log(path, line: str) -> None:
    path = Path(path)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# Running log\n\n")
        f.write(line + "\n")


def stamp(view, questions_path, *, repo, date: str) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                                text=True, timeout=30).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    return {"ledger_seq": view.as_of, "date": date, "code_commit": commit,
            "questions_sha256": hashlib.sha256(Path(questions_path).read_bytes()).hexdigest()[:12]}


def question_json(q) -> dict:
    return dataclasses.asdict(q)


def _cond(field: str, values: Sequence) -> str:
    return f"{field.replace('_', ' ')} is {' or '.join(str(v) for v in values)}"


def method_line(q) -> str:
    parts = [_cond(f, v) for f, v in q.population.items()]
    if q.any_of:
        parts.append("(" + " or ".join(" and ".join(_cond(f, v) for f, v in m.items())
                                       for m in q.any_of) + ")")
    if q.text_match:
        parts.append(f"the text of {', '.join(q.text_match['in'])} matches any of: "
                     f"{', '.join(q.text_match['terms'])}")
    base = "Counted ledger records (relevant, not a merged parallel copy)"
    return base + (" where " + "; ".join(parts) if parts else "") + "."


def _table(headers: Sequence[str], rows: Iterable[Sequence]) -> str:
    h = html.escape
    head = "".join(f"<th>{h(str(x))}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{h('' if v is None else str(v))}</td>" for v in r) + "</tr>"
                   for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def answer_html(q, stamp: Mapping, *, n_rows: int, reading: str | None = None,
                summary: Mapping | None = None, earliest: Sequence[Mapping] | None = None,
                concordance: Sequence[Mapping] | None = None) -> str:
    h = html.escape
    out = ["<!doctype html><html><head><meta charset='utf-8'>",
           f"<title>{h(q.id.upper())} · {h(q.title)}</title>", STYLE, "</head><body>",
           f"<h1>{h(q.id.upper())} · {h(q.title)}</h1>",
           f"<p class='stamp'>Ledger seq {stamp['ledger_seq']} · {h(stamp['date'])} · code "
           f"{h(stamp['code_commit'])} · questions {h(stamp['questions_sha256'])}</p>"]
    if q.review_list:
        out.append(f"<p><strong>{REVIEW_LIST_LABEL}</strong></p>")
    if q.kind == "records":
        out.append(f"<p><strong>Method.</strong> {h(method_line(q))}</p>")
    if reading:
        out.append("<h2>Reading</h2>" + "".join(f"<p>{h(p.strip())}</p>"
                                                for p in reading.split("\n\n") if p.strip()))
    if summary is not None:
        t = summary["total"]
        out.append("<h2>Counts</h2>" + _table(("human-reviewed", "machine-only"),
                                              [(t["human_reviewed"], t["machine_only"])]))
        if summary["by_group"]:
            keys = list(summary["by_group"][0]["key"])
            out.append("<h3>By " + h(", ".join(k.replace("_", " ") for k in keys)) + "</h3>" + _table(
                [k.replace("_", " ") for k in keys] + ["human-reviewed", "machine-only"],
                [[g["key"][k] for k in keys] + [g["human_reviewed"], g["machine_only"]]
                 for g in summary["by_group"]]))
        out.append("<h3>By jurisdiction and era</h3>" + _table(
            ("jurisdiction", "era", "human-reviewed", "machine-only"),
            [(c["jurisdiction"], c["era"], c["human_reviewed"], c["machine_only"])
             for c in summary["by_jurisdiction_era"]]))
        out.append(f"<p>Case table: {n_rows} rows (the sheet).</p>")
    if earliest:
        out.append("<h3>Earliest per jurisdiction</h3>" + _table(
            ("jurisdiction", "year", "case", "citations"),
            [(e["jurisdiction"], e["year"], e.get("case_name", ""), e.get("citations", ""))
             for e in earliest]))
    for term in concordance or ():
        out.append(f"<h2>{h(term['label'])}</h2><p class='stamp'>FTS: {h(term['expr'])}"
                   f"{' (expression)' if term['fts_expression'] else ''}"
                   f"{' (stemmed)' if term['stem'] else ''}</p>")
        out.append(_table(("era", "opinions matching", "opinions", "per 1,000"),
                          [(e, r["matches"], r["opinions"], r["rate"]) for e, r in term["by_era"].items()]))
        out.append("<h3>Earliest uses</h3>" + _table(
            ("year", "cite", "case", "jurisdiction", "context"),
            [(u["year"], u["cite"], u["name"], u["jurisdiction"], u["context"]) for u in term["earliest"]]))
    out.append("<h2>Caveats</h2><ul>" + "".join(f"<li>{h(c)}</li>" for c in CAVEATS) + "</ul>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Write `tools/gluck_log.py`**

```python
"""Ledger answers into the running log (spec docs/superpowers/specs/2026-10-04-ledger-answers-running-log-design.md).

  .venv/Scripts/python tools/gluck_log.py run --all
  .venv/Scripts/python tools/gluck_log.py run --question q1 --question q3
  .venv/Scripts/python tools/gluck_log.py list

Reads reports/gluck/questions.yaml (gitignored); writes reports/gluck/out/<date>-<id>-<slug>/
(answer.html, cases.csv or counts.csv, summary.json) and appends to reports/gluck/log.md. The
ledger and the corpus are read only. Publishing to Drive is a separate, agent-run step."""
from __future__ import annotations
import argparse
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from corpus_engine import concordance as cc                                # noqa: E402
from corpus_engine.answers import records as ar                            # noqa: E402
from corpus_engine.answers import render as rd                             # noqa: E402
from corpus_engine.answers.citations import citation_sets                  # noqa: E402
from corpus_engine.answers.questions import QuestionError, load_questions  # noqa: E402
from corpus_engine.domain import load_domain                               # noqa: E402
from corpus_engine.ledger import open_ledger                               # noqa: E402


def _ro(db) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-") or "answer"


def _folder(out: Path, name: str) -> Path:
    path, k = out / name, 2
    while path.exists():
        path, k = out / f"{name}-{k}", k + 1
    return path


def build_records(q, *, view, domain, conn, reviewed):
    recs = ar.select(view, domain, q, conn=conn)
    ids = [int(r["case_id"]) for r in recs]
    cites = citation_sets(conn, ids, jurisdiction_of={int(r["case_id"]): r.get("jurisdiction") for r in recs},
                          preference=domain.citation_preference)
    names = ar.names_and_courts(conn, ids)
    rows = ar.case_rows(recs, domain=domain, reviewed=reviewed, names=names, citations=cites)
    earliest = []
    if q.earliest_per_jurisdiction:
        for e in ar.earliest_per_jurisdiction(recs, q.earliest_per_jurisdiction, domain=domain):
            e["case_name"] = names.get(e["case_id"], ("", ""))[0]
            e["citations"] = "; ".join(cites.get(e["case_id"]) or [])
            earliest.append(e)
    return rows, {"summary": ar.summary(recs, domain=domain, reviewed=reviewed, group_by=q.group_by),
                  "earliest": earliest}


def build_concordance(q, *, conn, dens, domain):
    order = {e: i for i, e in enumerate(domain.eras)}
    rows, terms = [], []
    for t in q.terms:
        try:
            cells = cc.cell_counts(conn, t.expr, expr=t.is_expr, stem=t.stem)
            first = cc.earliest(conn, t.expr, expr=t.is_expr, stem=t.stem, n=5)
        except sqlite3.OperationalError as exc:
            raise SystemExit(f"{q.id}: term {t.label!r}: {exc}")
        for (e, j), d in sorted(dens.items(), key=lambda kv: (order.get(kv[0][0], 99), str(kv[0][1]))):
            m = cells.get((e, j), 0)
            rows.append({"term": t.label, "era": e, "jurisdiction": j, "matches": m, "opinions": d,
                         "rate_per_1000": cc.rate(m, d)})
        terms.append({"label": t.label, "expr": t.expr, "fts_expression": t.is_expr, "stem": t.stem,
                      "by_era": cc.era_table(cells, dens, eras=domain.eras), "earliest": first})
    return rows, {"concordance": terms}


def cmd_run(a) -> int:
    root = Path(a.root)
    domain = load_domain()
    try:
        questions = load_questions(root / "questions.yaml", domain)
    except QuestionError as exc:
        raise SystemExit(f"questions.yaml: {exc}")
    missing = sorted(set(a.question) - {q.id for q in questions})
    if missing:
        raise SystemExit(f"no such question: {', '.join(missing)}")
    wanted = [q for q in questions if a.all or q.id in a.question]
    if not wanted:
        raise SystemExit("nothing to run: pass --all or --question <id>")
    view = open_ledger(Path(a.ledger), domain=domain).view()
    reviewed = view.reviewed_ids()
    conn = _ro(a.db)
    st = rd.stamp(view, root / "questions.yaml", repo=ROOT, date=a.date)
    dens = cc.denominators(conn) if any(q.kind == "concordance" for q in wanted) else {}
    built = []                                   # everything is built before anything is written
    for q in wanted:
        if q.kind == "concordance":
            rows, extra = build_concordance(q, conn=conn, dens=dens, domain=domain)
            name, cols = "counts.csv", rd.COUNT_COLUMNS
        else:
            rows, extra = build_records(q, view=view, domain=domain, conn=conn, reviewed=reviewed)
            name, cols = "cases.csv", ar.COLUMNS
        reading_path = root / "readings" / f"{q.id}.md"
        reading = reading_path.read_text(encoding="utf-8") if reading_path.exists() else None
        built.append((q, rows, name, cols, extra, reading))
    out = root / "out"
    for q, rows, name, cols, extra, reading in built:
        folder = _folder(out, f"{a.date}-{q.id}-{slug(q.title)}")
        folder.mkdir(parents=True)
        rd.write_csv(folder / name, rows, cols)
        rd.write_text(folder / "answer.html", rd.answer_html(q, st, n_rows=len(rows), reading=reading, **extra))
        rd.write_text(folder / "summary.json", json.dumps(
            {"question": rd.question_json(q), "stamp": st, **extra}, indent=1, default=str) + "\n")
        rd.append_log(root / "log.md", f"- {a.date} · {q.id} · {q.title} · seq {st['ledger_seq']} · "
                                       f"out/{folder.name} · Drive: unpublished")
        print(f"{q.id}: {len(rows)} rows -> {folder}")
    return 0


def cmd_list(a) -> int:
    root = Path(a.root)
    for q in load_questions(root / "questions.yaml", load_domain()):
        print(f"{q.id}  {q.kind:12} {q.title}")
    log = root / "log.md"
    if log.exists():
        print(log.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT / "reports" / "gluck"))
    ap.add_argument("--db", default=str(ROOT / "data" / "db" / "corpus.db"))
    ap.add_argument("--ledger", default=str(ROOT / "data" / "ledger"))
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--question", action="append", default=[])
    r.add_argument("--all", action="store_true")
    sub.add_parser("list")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return {"run": cmd_run, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
```

Append to `.gitignore`:

```
# The running log: the collaborator's question definitions and every answer (public repo)
reports/gluck/
```

- [ ] **Step 5: Run the tests, then the suite**

Expected: 5 passed (the live smoke runs only where `data/db/corpus.db` exists); full suite 885 passed, 1 xfailed.

- [ ] **Step 6: Commit**

```bash
git add corpus_engine/answers/render.py tools/gluck_log.py tests/test_gluck_log_tool.py .gitignore
git commit -F - <<'EOF'
answers: HTML/CSV/JSON rendering and tools/gluck_log.py (run, list); outputs and question definitions live in the gitignored reports/gluck/

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: The five answers, their readings, and Drive (controller)

**Files:** `reports/gluck/questions.yaml`, `reports/gluck/readings/q1..q5.md`, `reports/gluck/factcheck.md`, `reports/gluck/log.md` (all gitignored; nothing committed in this task).

- [ ] **Step 1: Write `reports/gluck/questions.yaml`**

Write the five question definitions described generically in spec section 4 ("The five shipped definitions") into the gitignored `reports/gluck/questions.yaml`, using the schema in spec section 4. The definitions themselves are not reproduced here: the repository is public.

- [ ] **Step 2: Run all five and sanity-check**

```bash
.venv/Scripts/python tools/gluck_log.py run --all
```
Check each `summary.json` against an independent one-liner over `open_ledger().view()` for q1 and q2 totals; read q3's earliest-zoning list; read q4's era rates (a term with zero matches everywhere means a bad expression, not an absence: re-check it with `pipeline/kwic.py freq ... --expr --stem`); confirm q5's size is reviewable (if over about 300 rows, tighten the terms). Spot-check five citation cells for preferred-first order.

- [ ] **Step 3: Readings and their fact-check**

Write one short paragraph per answer in `reports/gluck/readings/qN.md` ("what this shows and what it does not"), using only figures from that answer's `summary.json`; no dollar figures; consistent caveat wording. Dispatch one independent fact-check agent (most capable model) with the five readings and the five `summary.json` files; it records each claim's check in `reports/gluck/factcheck.md`; apply only material fixes (the project's fact-check standard). Re-run `tools/gluck_log.py run --all` so the answers include the readings (new `-2` folders; the log keeps both).

- [ ] **Step 4: USER GATE**

Show the user each answer's headline (two-tier totals, the grouping table's top lines, q3's earliest zoning per jurisdiction, q4's era rates, q5's size) and the five readings. Wait for a go to publish.

- [ ] **Step 5: Publish to Drive**

With the Drive connector: create the folder "Gluck log" in the user's Drive (`create_file`, content type `application/vnd.google-apps.folder`) once; for each latest answer folder create a Google Doc from `answer.html` (`contentMimeType: text/html`) and a Google Sheet from `cases.csv` / `counts.csv` (`contentMimeType: text/csv`), parent = the folder, titled `<Qn> · <title> · seq <N> · <date>`. Replace `Drive: unpublished` on each published line of `reports/gluck/log.md` with the Doc and Sheet links. Tell the user the folder link; they share it with the collaborator (or ask the agent to use the share tool).

---

### Task 7: Docs and finish (controller)

**Files:**
- Modify: `README.md` (a short "Running log (ledger answers)" section after "Parallel reports")
- Modify: `reports/handoff-cycle-004.md` (a "Ledger answers (part 1)" paragraph)
- Modify: `docs/superpowers/specs/2026-10-04-ledger-answers-running-log-design.md` (append "## 12. As built")

- [ ] **Step 1: README section**

```
## Running log (ledger answers)

.venv\Scripts\python tools\gluck_log.py run --all      # reports\gluck\out\<date>-<id>-<slug>\
.venv\Scripts\python tools\gluck_log.py list
# Question definitions and outputs live in the gitignored reports\gluck\ (public repo);
# publishing to the shared Drive folder is an agent step with the Drive connector.
.venv\Scripts\python pipeline\kwic.py freq "NEAR(transient lodging, 10)" --expr --stem --rate --by jurisdiction
.venv\Scripts\python pipeline\kwic.py earliest "tourist home" --stem
```

- [ ] **Step 2: Handoff paragraph and spec section 12** — the five answers' ledger seq, the Drive folder name, the readings' fact-check outcome, what's parked (review-column import; canonical-copy re-pick by reporter).

- [ ] **Step 3: Full suite, commit, finish**

```bash
.venv/Scripts/python -m pytest -q -p no:cacheprovider
git add README.md reports/handoff-cycle-004.md docs/superpowers/specs/2026-10-04-ledger-answers-running-log-design.md
git commit -F - <<'EOF'
docs: ledger answers and the running log as built (README, handoff, spec section 12)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Then superpowers:finishing-a-development-branch (the user merges locally), push main, update the project memory.
