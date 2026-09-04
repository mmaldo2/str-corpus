import pytest
from corpus_engine.domain import load_domain
from corpus_engine.selector.model import (KIND_SPECS, Partition, SeedSet, Selector, SelectorSpecError,
                                          load_selectors, parse_selector)

def test_partition_key_and_seed_hash():
    assert Partition("pre-1860", "Tex.").key == "pre-1860|Tex."
    a = SeedSet.build("x", [3, 1, 2]); b = SeedSet.build("x", (1, 2, 3))
    assert a.case_ids == (1, 2, 3) and a.hash == b.hash and len(a.hash) == 16

def test_parse_expands_scopes_and_validates_params():
    dom = load_domain()
    s = parse_selector({"id": "a", "version": 1, "concept": "c", "type": "fts_phrase", "polarity": "favorable-candidate",
                        "pattern": '"x"', "era_scope": "all", "jurisdiction_scope": ["Tex."], "status": "active"},
                       eras=dom.eras, jurisdictions=dom.jurisdictions)
    assert s.kind == "fts_phrase" and s.era_scope == dom.eras and s.jurisdiction_scope == ("Tex.",)
    assert s.params["index"] == "raw" and s.label == "a@v1" and len(s.digest()) == 16
    with pytest.raises(SelectorSpecError):
        parse_selector({"id": "b", "version": 1, "concept": "c", "type": "embedding", "polarity": "p"}, eras=dom.eras, jurisdictions=dom.jurisdictions)
    with pytest.raises(SelectorSpecError):
        parse_selector({"id": "b", "version": 1, "concept": "c", "type": "nope", "polarity": "p", "pattern": "x"}, eras=dom.eras, jurisdictions=dom.jurisdictions)
    assert set(KIND_SPECS) == {"fts_phrase", "fts_near", "regex", "embedding", "citation_graph", "relevance_feedback"}

def test_load_real_selectors_file():
    dom = load_domain()
    sels = load_selectors(dom)
    assert len(sels) == 36 and len({s.key for s in sels}) == 36
    kinds = {s.kind for s in sels}
    assert {"fts_phrase", "fts_near", "embedding"} <= kinds
    assert dom.sharding.batch_size == 18 and dom.sharding.min_seeds == 5
