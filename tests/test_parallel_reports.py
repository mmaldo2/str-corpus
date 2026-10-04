"""Parallel reports: detection, scoring, apply and undo (spec 2026-10-04 section 6)."""
import pytest
from corpus_engine import store
from corpus_engine.ingest import parallel as par

BODY = " ".join(f"word{i}" for i in range(400))


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "c.db")
    store.ensure_schema(c)
    yield c
    c.close()


def _case(conn, cid, *, name="Smith v. Jones", court="New York Supreme Court", jur="N.Y.",
          date="1908-04-24", year=1908, reporter="nys", text=BODY, official=False, dup=None):
    cite = f"{cid} {reporter} 1"
    conn.execute("""INSERT INTO cases (case_id, name_abbreviation, cite, court, jurisdiction,
                    decision_date, decision_year, era_partition, reporter, norm_text, raw_text,
                    is_duplicate_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (cid, name, cite, court, jur, date, year, "1900-1930", reporter, text, text, dup))
    conn.execute("INSERT INTO citations (case_id, cite, cite_norm, type) VALUES (?,?,?,?)",
                 (cid, cite, cite.lower(), "official" if official else "parallel"))
    conn.commit()


def test_names_dates_and_shingles():
    assert par.normalize_name("Smith v. Jones, Inc.") == "smith v jones inc"
    assert par.dates_compatible("1908-04", "1908-04-24")
    assert not par.dates_compatible("1908-04-23", "1908-04-24")
    assert not par.dates_compatible("", "1908")
    assert par.shingles("A b c d e f", 5) == frozenset({"a b c d e", "b c d e f"})
    assert par.containment(frozenset(), frozenset({"x"})) == 0.0


def test_candidate_groups_need_the_same_court_year_name_and_two_reporters(conn):
    _case(conn, 1, reporter="nys")
    _case(conn, 2, reporter="misc", date="1908-04")
    _case(conn, 3, reporter="misc", court="New York Court of Appeals")      # other court
    _case(conn, 4, reporter="misc", year=1909, date="1909-01")              # other year
    _case(conn, 5, reporter="ad", name="Brown v. Green")                    # one reporter only
    _case(conn, 6, reporter="ad", name="Brown v. Green")
    _case(conn, 7, reporter="misc", dup=1)                                  # already a duplicate
    _case(conn, 8, reporter="misc", name="In re")                           # name too short
    _case(conn, 9, reporter="nys", name="In re")
    groups = par.candidate_groups(conn)
    assert [[m.case_id for m in g.members] for g in groups] == [[1, 2]]
    assert (groups[0].jurisdiction, groups[0].year, groups[0].era) == ("N.Y.", 1908, "1900-1930")


def test_score_group_measures_both_sizes_and_guards_short_and_empty_texts(conn):
    _case(conn, 1, reporter="nys", official=True)
    _case(conn, 2, reporter="misc", text="Syllabus by the reporter. " + BODY)
    _case(conn, 3, reporter="ad", text=" ".join(f"other{i}" for i in range(400)))
    _case(conn, 4, reporter="hun", text="Judgment affirmed, with costs.")
    _case(conn, 5, reporter="barb", text="")
    [g] = par.candidate_groups(conn)
    winner = par.pick_winner(g.members)
    assert winner.case_id == 1                                   # the official copy
    rows = {r["loser"]: r for r in par.score_group(conn, g, winner)}
    assert rows[2]["c5"] == 1.0 and rows[2]["c3"] == 1.0 and par.passes_guards(rows[2])
    assert rows[3]["c5"] == 0.0
    assert not rows[4]["long_enough"] and not par.passes_guards(rows[4])
    assert rows[5]["c5"] == 0.0 and not rows[5]["size_ok"] and not par.passes_guards(rows[5])


def test_pick_winner_prefers_official_then_lowest_id():
    ms = [par.Member(5, "", "a", "", False), par.Member(9, "", "b", "", True),
          par.Member(2, "", "c", "", False)]
    assert par.pick_winner(ms).case_id == 9
    assert par.pick_winner([m for m in ms if not m.official]).case_id == 2


def test_apply_is_idempotent_and_skips_a_stale_winner(conn):
    for cid, rep in ((1, "nys"), (2, "misc"), (3, "nys"), (4, "misc"), (5, "ad")):
        _case(conn, cid, reporter=rep)
    res = par.apply_merges(conn, [(1, 2, 0.9), (3, 4, 0.8), (4, 5, 0.7)], method="m", run_id="r", ts="t")
    assert res == {"applied": 2, "already": 0, "stale": 1}       # 4 became a loser first: no chain
    marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases"))
    assert marks == {1: None, 2: 1, 3: None, 4: 3, 5: None}
    again = par.apply_merges(conn, [(1, 2, 0.9), (3, 4, 0.8)], method="m", run_id="r", ts="t")
    assert again == {"applied": 0, "already": 2, "stale": 0}


def test_undo_restores_exactly_and_leaves_citation_based_marks(conn):
    _case(conn, 1, reporter="nys")
    _case(conn, 2, reporter="misc")
    _case(conn, 8, reporter="nys", name="Other v. Case")
    _case(conn, 9, reporter="nys", name="Other v. Case", dup=8)        # dedupe.py's mark
    par.apply_merges(conn, [(1, 2, 0.9)], method="m1", run_id="r", ts="t")
    assert par.winner_map(conn) == {2: 1}
    assert par.losers_among(conn, [1, 2, 8, 9]) == {2, 9}
    assert par.undo_merges(conn, "m1") == 1
    marks = dict(conn.execute("SELECT case_id, is_duplicate_of FROM cases"))
    assert marks == {1: None, 2: None, 8: None, 9: 8}
    assert par.winner_map(conn) == {}


def test_winner_map_without_the_table_is_empty(conn):
    assert par.winner_map(conn) == {}
