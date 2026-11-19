"""Token evidence improves recall without vendor-ID or transitive-chain shortcuts."""

import pytest

from cantill.config import ConfigError, EntityResolutionConfig
from cantill.entities import resolve_entities, supplier_name_clusters, supplier_tokens
from cantill.matching import supplier_key
from test_matching import factory


def names(values):
    return {supplier_key(value): {supplier_tokens(value)} for value in values}


def test_reordered_name_tokens_cross_prefix_blocks(factory):
    _, matched = factory(primary=[{"id": "1", "vendor": "", "supplier": "Acme North Mining Supply Parts"},
                                 {"id": "2", "vendor": "", "supplier": "Parts Supply Mining North Acme Ltd"}],
                         secondary=[], cross=False)
    assert resolve_entities(matched).records.supplier_key.nunique() == 1


def test_jaccard_point_eight_boundary_is_configurable():
    values = names(["Alpha Bravo Charlie Delta Echo", "Delta Charlie Bravo Alpha"])
    assert len(supplier_name_clusters(values, jaccard_threshold=.8)) == 1
    assert len(supplier_name_clusters(values, jaccard_threshold=.81)) == 2


def test_numeric_tokens_are_order_independent_but_not_dropped():
    assert len(supplier_name_clusters(names(["Acme Plant 10 20", "Plant Acme 20 10"]))) == 1
    assert len(supplier_name_clusters(names(["Acme Plant 10 20", "Plant Acme 20 11"]))) == 2
    assert len(supplier_name_clusters(names(["Acme Plant 01", "Plant Acme 1"]))) == 2


def test_complete_link_rejects_token_similarity_chain():
    values = names(["Alpha Bravo Charlie Delta Echo", "Alpha Bravo Charlie Delta Echo Foxtrot",
                    "Alpha Bravo Charlie Delta Echo Foxtrot Golf"])
    assert sorted(map(len, supplier_name_clusters(values))) == [1, 2]


def test_supplier_tokens_preserve_word_boundaries_and_remove_legal_suffix():
    assert supplier_tokens("\u00c1cme Engineering (Pty) Ltd") == ("acme", "engineering")


def test_names_without_shared_identity_do_not_merge_and_scope_is_preserved(factory):
    _, matched = factory(primary=[{"id": "1", "supplier": "", "vendor": "V1", "system": "ERP1"},
                                 {"id": "2", "supplier": "", "vendor": "V1", "system": "ERP2"}],
                         secondary=[], cross=False)
    assert resolve_entities(matched).records.supplier_key.nunique() == 2


def test_jaccard_resolution_remains_order_invariant(factory):
    _, matched = factory(primary=[{"id": "1", "vendor": "", "supplier": "Acme North Mining Supply Parts"},
                                 {"id": "2", "vendor": "", "supplier": "Parts Supply Mining North Acme"}],
                         secondary=[], cross=False)
    first = resolve_entities(matched).records.set_index("record_id").supplier_key.to_dict()
    matched.records = matched.records.iloc[::-1]
    assert first == resolve_entities(matched).records.set_index("record_id").supplier_key.to_dict()


@pytest.mark.parametrize("value", [True, .4, 1.1, float("nan"), "0.8"])
def test_invalid_entity_thresholds_rejected(value):
    with pytest.raises(ConfigError):
        EntityResolutionConfig(supplier_jaccard_threshold=value)
