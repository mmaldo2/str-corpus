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
    got = ar.earliest_per_jurisdiction(recs, {"restriction_nature": ("zoning",)}, domain=dom, reviewed={3})
    assert [(g["jurisdiction"], g["case_id"], g["year"]) for g in got] == [("N.Y.", 2, 1915), ("Tex.", 3, 1930)]
    assert [g["review_tier"] for g in got] == ["machine-only", "human-reviewed"]
