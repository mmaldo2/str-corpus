from corpus_engine.domain import load_domain

def test_str_domain_loads_with_cycle_004_scope():
    d = load_domain("str-right-to-let")
    assert d.eras == ("pre-1860", "1860-1900", "1900-1930", "1930-1970", "1970-2020")
    for j in ("Tex.", "Pa.", "La.", "N.Y.", "Mass.", "Conn.", "N.J.", "Cal.", "Ohio", "D.C."):
        assert j in d.jurisdictions
    assert set(d.reporter_slugs) == {"f-cas", "us", "dc"}
    assert d.regions["Mass."] == "northeast" and d.regions["Tex."] == "south"
    assert d.letting_tiers["householder"] == "householder"
    assert d.letting_tiers["non_resident_owner"] == "owner"
    assert "polarity" in d.judged_fields and "review.notes" in d.curatorial_fields
    assert d.selectors_path.exists() and d.ontology_path.exists()


def test_letting_tiers_cover_exactly_the_reader_schema_who_values():
    """The tradition matrix buckets a record by `letting_tiers[who_was_letting]` and falls
    back to "unclear" on a miss, so a spelling split between the domain and the schema the
    reader answers under silently empties a tier instead of failing. `owner_nonresident`
    did exactly that from Stage 1 until 2026-09-05: the `owner` tier was empty in every
    cell while 14 records carried `non_resident_owner`."""
    from corpus_engine.reader.schema import WHO_VALUES
    assert set(load_domain("str-right-to-let").letting_tiers) == set(WHO_VALUES)
