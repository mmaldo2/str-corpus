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
