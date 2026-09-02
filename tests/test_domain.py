from corpus_engine.domain import load_domain

def test_str_domain_loads_with_cycle_004_scope():
    d = load_domain("str-right-to-let")
    assert d.eras == ("pre-1860", "1860-1900", "1900-1930", "1930-1970", "1970-2020")
    for j in ("Tex.", "Pa.", "La.", "N.Y.", "Mass.", "Conn.", "N.J.", "Cal.", "Ohio", "D.C."):
        assert j in d.jurisdictions
    assert set(d.reporter_slugs) == {"f-cas", "us", "dc"}
    assert d.regions["Mass."] == "northeast" and d.regions["Tex."] == "south"
    assert d.letting_tiers["householder"] == "householder"
    assert d.letting_tiers["owner_nonresident"] == "owner"
    assert "polarity" in d.judged_fields and "review.notes" in d.curatorial_fields
    assert d.selectors_path.exists() and d.ontology_path.exists()
