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
