"""What the answer page states (spec section 6; ADR-0002: counts are never blended)."""
from corpus_engine.answers.questions import Question
from corpus_engine.answers import render as rd

STAMP = {"ledger_seq": 7, "date": "2026-10-05", "code_commit": "abc", "questions_sha256": "def"}
SUMMARY = {"total": {"human_reviewed": 2, "machine_only": 5},
           "by_jurisdiction_era": [{"jurisdiction": "N.Y.", "era": "pre-1860", "human_reviewed": 2, "machine_only": 5}],
           "by_group": [{"key": {}, "human_reviewed": 2, "machine_only": 5}]}


def test_the_page_never_states_a_blended_count():
    html = rd.answer_html(Question("q1", "t"), STAMP, n_rows=7, summary=SUMMARY, earliest=[])
    assert "7 rows" not in html and "<td>7</td>" not in html
    assert "2 human-reviewed and 5 machine-only" in html


def test_no_grouping_means_no_empty_by_table():
    html = rd.answer_html(Question("q1", "t"), STAMP, n_rows=7, summary=SUMMARY, earliest=[])
    assert "<h3>By </h3>" not in html
    assert html.count("<th>human-reviewed</th>") == 2          # the totals and the jurisdiction x era tables


def test_the_earliest_table_names_its_filter_and_each_row_tier():
    q = Question("q3", "t", population={"polarity": ("adverse",)},
                 earliest_per_jurisdiction={"restriction_nature": ("zoning",)})
    earliest = [{"jurisdiction": "N.J.", "year": 1927, "case_name": "Burg v. Ackerman",
                 "citations": "5 N.J. Misc. 96", "review_tier": "machine-only"}]
    html = rd.answer_html(q, STAMP, n_rows=1, summary=SUMMARY, earliest=earliest)
    assert "Earliest per jurisdiction where restriction nature is zoning" in html
    assert "<td>machine-only</td>" in html
