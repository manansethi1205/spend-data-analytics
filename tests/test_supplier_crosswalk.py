"""Supervised aliases are explicit, company-scoped, and evaluated without test labels."""

import json

import pandas as pd
import pytest

from cantill.config import ConfigError
from cantill.entities import resolve_entities
from cantill.matching import supplier_key
from cantill.pipeline import run_company
from cantill.supplier_crosswalk import SupplierCrosswalk
from test_matching import factory


def test_known_unrelated_names_merge_and_unseen_names_keep_fallback(factory):
    _, matched = factory(primary=[{"id": "1", "supplier": "Alpha Mining", "vendor": "A"},
                                 {"id": "2", "supplier": "Omega Chemicals", "vendor": "B"},
                                 {"id": "3", "supplier": "Unseen Engineering", "vendor": "C"},
                                 {"id": "4", "supplier": "ALPHA MINING LTD", "vendor": ""}],
                         secondary=[], cross=False)
    labels = pd.DataFrame({"record_id": ["P:1", "P:2"], "supplier_key": ["parent", "parent"]})
    crosswalk = SupplierCrosswalk.fit("synthetic", matched.records, labels)
    before = resolve_entities(matched).records.set_index("record_id")
    result = resolve_entities(matched, supplier_crosswalk=crosswalk)
    after = result.records.set_index("record_id")
    assert after.loc[["P:1", "P:2", "P:4"], "supplier_key"].nunique() == 1
    assert after.loc["P:3", "supplier_key"] == before.loc["P:3", "supplier_key"]
    assert result.summary()["supplier_labels_used"] is True
    assert resolve_entities(matched).summary()["supplier_labels_used"] is False
    pd.testing.assert_frame_equal(before.drop(columns=["supplier_key", "item_key", "entity_flags"]),
                                  after.drop(columns=["supplier_key", "item_key", "entity_flags"]))


def test_conflicting_normalized_name_abstains(factory):
    _, matched = factory(primary=[{"id": "1", "supplier": "Alpha Mining Ltd"},
                                 {"id": "2", "supplier": "ALPHA MINING"}], secondary=[], cross=False)
    labels = pd.DataFrame({"record_id": ["P:1", "P:2"], "supplier_key": ["one", "two"]})
    crosswalk = SupplierCrosswalk.fit("synthetic", matched.records, labels)
    assert not crosswalk.names
    assert crosswalk.ambiguous_names == (supplier_key("Alpha Mining"),)
    before = resolve_entities(matched).records.supplier_key
    after = resolve_entities(matched, supplier_crosswalk=crosswalk).records
    assert before.equals(after.supplier_key)
    assert all("SUPPLIER_CROSSWALK_AMBIGUOUS" in flags for flags in after.entity_flags)


def test_fit_uses_only_supplied_labels_and_ignores_blank_identity():
    records = pd.DataFrame({"record_id": ["1", "2", "3"], "supplier_name": ["Alpha Mining", "Omega Supply", ""]})
    labels = pd.DataFrame({"record_id": ["1", "3"], "supplier_key": ["parent", "parent"]})
    crosswalk = SupplierCrosswalk.fit("A", records, labels)
    assert set(crosswalk.names) == {supplier_key("Alpha Mining")}


def test_artifact_roundtrip_company_guard_and_pipeline_without_label_file(factory, tmp_path):
    _, matched = factory(secondary=[], cross=False)
    config = matched.eligible.normalized.ingested.config
    labels = pd.DataFrame({"record_id": ["P:p1"], "supplier_key": ["parent"]})
    crosswalk = SupplierCrosswalk.fit(config.company_id, matched.records, labels)
    path = tmp_path / "crosswalk.json"
    crosswalk.save(path)
    assert SupplierCrosswalk.load(path, company_id=config.company_id) == crosswalk
    with pytest.raises(FileExistsError):
        crosswalk.save(path)
    with pytest.raises(ConfigError, match="company"):
        SupplierCrosswalk.load(path, company_id="C")
    with pytest.raises(ConfigError, match="company"):
        resolve_entities(matched, supplier_crosswalk=SupplierCrosswalk("C", {}))
    assert not (tmp_path / "not-loaded.csv").exists()
    summary = run_company(config, supplier_crosswalk=path).summary()
    assert summary["supplier_labels_used"] is True and summary["labels_used"] is True
    assert summary["classification_labels_used"] is False
    assert run_company(config).summary()["supplier_labels_used"] is False


@pytest.mark.parametrize("payload", [[], {}, {"protocol": "wrong", "company_id": "A"},
    {"protocol": "cantill-supplier-crosswalk-v1", "company_id": "A", "names": {"alpha": "bad"}, "ambiguous_names": []},
    {"protocol": "cantill-supplier-crosswalk-v1", "company_id": "A", "names": {"alpha": "supervised_supplier_a"}, "ambiguous_names": ["alpha"]}])
def test_invalid_artifact_is_rejected(tmp_path, payload):
    path = tmp_path / "crosswalk.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigError):
        SupplierCrosswalk.load(path, company_id="A")
