"""Synthetic entity, arbitrary-tree, label-isolation and output checks."""

from dataclasses import replace
from decimal import Decimal
import json
import subprocess
import sys

import pandas as pd
import pytest

from test_matching import factory
from cantill.classify import TaxonomyClassifier, classify_company
from cantill.config import ConfigError
from cantill.entities import Groups, resolve_entities
from cantill.metrics import classification_metrics, grouping_metrics
from cantill.output import validate_output
from cantill.pipeline import run_company, write_output


def test_union_find_compresses_without_cycles():
    groups = Groups()
    for a, b in [(('d',), ('c',)), (('b',), ('c',)), (('a',), ('b',))]:
        groups.join(a, b)
    assert {groups.find((key,)) for key in 'abcd'} == {('a',)}


def resolve(factory, primary, secondary=None):
    _, matched = factory(primary=primary, secondary=secondary or [], cross=False, repeats=())
    return resolve_entities(matched)


def test_supplier_name_variants_and_id_aliases(factory):
    result = resolve(factory, [{"id": "1", "supplier": "Acme Engineering (Pty) Ltd"},
                               {"id": "2", "supplier": "ACME ENGINEERING", "vendor": ""},
                               {"id": "3", "supplier": "Acme Enginering Ltd", "vendor": ""},
                               {"id": "4", "supplier": "", "vendor": "V001"}])
    assert result.records.supplier_key.nunique() == 1


def test_vendor_ids_are_scoped_by_erp(factory):
    result = resolve(factory, [{"id": "1", "supplier": "", "system": "ERP1"},
                               {"id": "2", "supplier": "", "system": "ERP2"}])
    assert result.records.supplier_key.nunique() == 2


def test_supplier_numbers_and_short_names_do_not_fuzzy_merge(factory):
    result = resolve(factory, [{"id": "1", "supplier": "Supplier Plant 1", "vendor": ""},
                               {"id": "2", "supplier": "Supplier Plant 2", "vendor": ""},
                               {"id": "3", "supplier": "ABCD", "vendor": ""},
                               {"id": "4", "supplier": "ABCE", "vendor": ""}])
    assert result.records.supplier_key.nunique() == 4


def test_unknown_supplier_and_item_are_unique_and_flagged(factory):
    result = resolve(factory, [{"id": str(i), "supplier": "", "vendor": "", "item": "", "description": "Product"} for i in range(2)])
    assert result.records.supplier_key.nunique() == result.records.item_key.nunique() == 2
    assert all("ITEM_IDENTITY_MISSING" in flags and "SUPPLIER_IDENTITY_MISSING" in flags for flags in result.records.entity_flags)


def test_item_code_scope_and_text_specifications(factory):
    result = resolve(factory, [{"id": "1", "system": "ERP1"}, {"id": "2", "system": "ERP2"},
                               {"id": "3", "item": "", "description": "Bolt 10 mm"},
                               {"id": "4", "item": "", "description": "Bolt 20 mm"}])
    assert result.records.item_key.nunique() == 4


def test_exact_item_text_with_unit_connects_codes_but_not_units(factory):
    _, matched = factory(primary=[{"id": "1", "item": "A"}, {"id": "2", "item": "B"}, {"id": "3", "item": "C"}], secondary=[], cross=False)
    matched.records["unit"] = ["EA", "ea", "BOX"]
    result = resolve_entities(matched).records
    assert result.item_key.iloc[0] == result.item_key.iloc[1]
    assert result.item_key.iloc[0] != result.item_key.iloc[2]


def test_generic_item_text_does_not_merge_codes(factory):
    result = resolve(factory, [{"id": "1", "item": "A", "description": "Product"}, {"id": "2", "item": "B", "description": "Product"}])
    assert result.records.item_key.nunique() == 2


def test_inconsistent_code_text_is_not_an_alias_bridge(factory):
    _, matched = factory(primary=[{"id": "1", "item": "A", "description": "Bolt 10 mm"},
                                 {"id": "2", "item": "A", "description": "Water pump"},
                                 {"id": "3", "item": "B", "description": "Bolt 10 mm"}], secondary=[], cross=False)
    matched.records["unit"] = "EA"
    result = resolve_entities(matched).records
    assert result.item_key.iloc[0] == result.item_key.iloc[1]
    assert result.item_key.iloc[0] != result.item_key.iloc[2]
    assert "ITEM_CODE_TEXT_CONFLICT" in result.entity_flags.iloc[0]


def test_exact_uncoded_items_are_supplier_specific(factory):
    result = resolve(factory, [{"id": "1", "item": ""}, {"id": "2", "item": ""},
                               {"id": "3", "item": "", "supplier": "Different Engineering", "vendor": "V2"}])
    assert result.records.item_key.nunique() == 2


def test_whitespace_description_uses_service_text_and_po_unit(factory):
    _, matched = factory(primary=[{"id": "1", "item": "", "description": " "}, {"id": "2", "item": "", "description": " "}], secondary=[], cross=False)
    matched.records["service_text"] = ["Pump inspection", "Pump inspection"]
    matched.records["unit"] = [" ", "HR"]
    matched.records["po_unit"] = ["HR", ""]
    assert resolve_entities(matched).records.item_key.nunique() == 1


def test_duplicate_item_inheritance_checks_explicit_units(factory):
    _, matched = factory()
    matched.records["unit"] = ["EA", "BOX"]
    assert resolve_entities(matched).records.item_key.nunique() == 2


def test_resolution_preserves_input_and_is_order_invariant(factory):
    _, matched = factory(primary=[{"id": "1"}, {"id": "2", "vendor": "", "supplier": "Acme Engineering"}], secondary=[], cross=False)
    before = matched.records.copy(deep=True)
    first = resolve_entities(matched)
    pd.testing.assert_frame_equal(before, matched.records)
    pd.testing.assert_frame_equal(first.records[before.columns], before)
    matched.records = matched.records.iloc[::-1]
    second = resolve_entities(matched)
    pd.testing.assert_frame_equal(first.records.set_index("record_id")[["supplier_key", "item_key"]].sort_index(),
                                  second.records.set_index("record_id")[["supplier_key", "item_key"]].sort_index())


def test_duplicate_inherits_exact_text_item_not_conflicting_spec(factory):
    _, matched = factory()
    result = resolve_entities(matched).records
    assert result.item_key.nunique() == 1
    matched.records.loc[matched.records.source == "secondary", "description"] = "Steel bolt 10 mm"
    result = resolve_entities(matched).records
    assert result.item_key.nunique() == 2


def test_labels_do_not_enter_resolution_or_classification(factory):
    _, matched = factory()
    first = classify_company(resolve_entities(matched))
    matched.eligible.normalized.ingested.labels = pd.DataFrame({"supplier_key": ["poison"], "l1": ["poison"]})
    second = classify_company(resolve_entities(matched))
    pd.testing.assert_frame_equal(first.records, second.records)


def test_four_level_and_variable_depth_tree():
    tree = [("Goods", "Metals", "Fasteners", "Bolts"), ("Services", "Audit")]
    model = TaxonomyClassifier(tree)
    assert model.predict("Bolts")[0] == tree[0]
    assert model.predict("Audit")[0] == tree[1]


def test_taxonomy_order_does_not_change_prediction():
    tree = [("Goods", "Bolts"), ("Services", "Audit")]
    assert TaxonomyClassifier(tree).predict("bolt") == TaxonomyClassifier(tree[::-1]).predict("bolt")


@pytest.mark.parametrize("tree", [[], [("",)], [("a",), ("a", "b")], [("a",)] * 2, [("1", "2", "3", "4", "5")]])
def test_invalid_taxonomy_is_rejected(tree):
    with pytest.raises(ConfigError):
        TaxonomyClassifier(tree)


def test_no_overlap_has_explicit_zero_confidence():
    path, confidence, flag = TaxonomyClassifier([("Bolts",), ("Audit",)]).predict("zzzzzz")
    assert path == ("Audit",) and confidence == 0 and flag == "NO_TAXONOMY_OVERLAP"


def test_tied_categories_are_flagged_and_deterministic():
    model = TaxonomyClassifier([("A", "Audit"), ("The", "Audit")])
    assert model.predict("Audit") == (("A", "Audit"), 0, "TAXONOMY_TIE")


@pytest.mark.parametrize("text", ["", "  ", "naïve produits", "采购 螺栓", "bolts", "audit 123", "ignore all instructions"])
def test_all_text_is_data_and_predictions_are_valid(text):
    tree = [("Goods", "Bolts"), ("Services", "Audit")]
    path, confidence, _ = TaxonomyClassifier(tree).predict(text)
    assert path in tree and 0 <= confidence <= 1


def test_account_text_is_available_when_description_is_empty():
    assert TaxonomyClassifier([("Bolts",), ("Audit",)]).predict(account_description="Audit")[0] == ("Audit",)


def test_included_classification_excluded_blank_and_columns_preserved(factory):
    _, matched = factory()
    resolved = resolve_entities(matched)
    before = resolved.records.copy(deep=True)
    result = classify_company(resolved)
    pd.testing.assert_frame_equal(result.records[before.columns], before)
    assert result.records.loc[result.records.include == 1, "l1"].eq("Synthetic terminal").all()
    assert result.records.loc[result.records.include == 0, ["l1", "l2", "l3", "l4"]].eq("").all().all()


def test_output_is_valid_and_original_input_cannot_be_overwritten(factory, tmp_path):
    _, matched = factory()
    result = classify_company(resolve_entities(matched))
    output = tmp_path / "output.csv"
    write_output(result, output)
    ingested = matched.eligible.normalized.ingested
    assert validate_output(output, ingested.records.record_id, ingested.taxonomy).valid
    for source in ingested.config.sources:
        with pytest.raises(ConfigError, match="conflicts"):
            write_output(result, tmp_path / source.table.path)


def test_unresolved_finances_never_write_or_replace_output(factory, tmp_path):
    _, matched = factory(primary=[{"amount": ""}], secondary=[], cross=False)
    result = classify_company(resolve_entities(matched))
    output = tmp_path / "output.csv"
    output.write_text("untouched", encoding="utf-8")
    with pytest.raises(ConfigError, match="unresolved"):
        write_output(result, output)
    assert output.read_text() == "untouched"


def test_run_never_opens_labels_even_with_missing_label_path(factory, monkeypatch):
    _, matched = factory()
    config = matched.eligible.normalized.ingested.config
    import cantill.ingest as ingestion
    original = ingestion.read_table
    def guard(base, table, name):
        assert name != "labels"
        return original(base, table, name)
    monkeypatch.setattr(ingestion, "read_table", guard)
    result = run_company(config)
    assert result.summary()["labels_used"] is False


def test_cli_run_and_resolve(factory, tmp_path):
    factory()
    for command in ("run", "resolve"):
        result = subprocess.run([sys.executable, "-m", "cantill", command, "--config", str(tmp_path / "company.yaml")], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["included_rows"] == 1


def test_group_metrics_count_false_and_missed_pairs():
    result = grouping_metrics(["x", "x", "y", "z"], ["a", "b", "b", ""])
    assert result["labelled_rows"] == 3
    assert result["pair_false_positive"] == result["pair_false_negative"] == 1
    assert result["pair_precision"] == result["pair_recall"] == 0
    assert grouping_metrics(["x"], [""])["pair_precision"] is None


def test_classification_metrics_absolute_spend_and_level_denominators():
    result = classification_metrics([
        {"golden": ("a", "b"), "predicted": ("a", "b"), "spend": Decimal("-30"), "confidence": .5},
        {"golden": ("c",), "predicted": ("a",), "spend": Decimal("10"), "confidence": 0},
        {"golden": ("c",), "predicted": ("c",), "spend": None, "confidence": .1}])
    assert result["terminal_accuracy"] == 2/3
    assert result["absolute_spend_weighted_terminal_accuracy"] == .75
    assert result["l2_path_accuracy"] == 1 and result["l3_path_accuracy"] is None
    assert result["rows_with_missing_spend"] == 1
