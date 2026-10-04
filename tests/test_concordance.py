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
