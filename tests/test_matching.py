"""Synthetic purchase identity, capacity, grouping and preservation checks."""

import csv
import json
import subprocess
import sys
from decimal import Decimal, localcontext

import pandas as pd
import pytest
import yaml

from cantill.config import ConfigError, load_config
from cantill.eligibility import assess_eligibility
from cantill.ingest import ingest_company
from cantill.matching import count_purchases
from cantill.normalize import normalize_company


PATTERN = r"(?P<po>PO-[0-9]+)(?:/(?P<line>[0-9]+))?"


@pytest.fixture
def factory(tmp_path):
    def build(primary=None, secondary=None, cross=True, repeats=("secondary",), pair_options=None, matching=None):
        def populate(overrides, preferred):
            row = {"id": "p1" if preferred else "s1", "system": "ERP" if preferred else "AP",
                   "supplier": "Acme Engineering (Pty) Ltd" if preferred else "ACME ENGINEERING LTD",
                   "vendor": "V001" if preferred else "", "po": "PO-0001", "po_line": "10.0" if preferred else "",
                   "invoice": "" if preferred else "INV-1", "invoice_line": "", "amount": "100", "quantity": "2",
                   "description": "Steel bolt 25 mm", "item": "MAT-X" if preferred else "",
                   "date": "2024-01-01" if preferred else "2024-01-10", "paid": "", "due": "",
                   "currency": "USD", "status": "Paid", "extra": ""}
            row.update(overrides)
            return row
        p = [populate(r, True) for r in (primary if primary is not None else [{}])]
        s = [populate(r, False) for r in (secondary if secondary is not None else [{}])]
        columns = list(populate({}, True))
        sources = []
        for name, rows, prefix in [("primary", p, "P:"), ("secondary", s, "S:")]:
            with (tmp_path / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            fields = {"source_record_id": "id", "source_system": "system", "supplier_name": "supplier", "supplier_id": "vendor",
                      "po_number": "po", "po_line": "po_line", "invoice_number": "invoice", "invoice_line": "invoice_line",
                      "amount": "amount", "quantity": "quantity", "description": "description", "item_code": "item", "currency": "currency",
                      "paid_date": "paid", "due_date": "due"}
            date_role = "posting_date" if name == "primary" else "invoice_date"
            fields[date_role] = "date"
            if name == "secondary":
                fields["status"] = "status"
            sources.append({"name": name, "path": f"{name}.csv", "record_id_prefix": prefix, "fields": fields,
                            "amount_basis": "net", "number_format": {"decimal": ".", "thousands": ""},
                            "date_formats": {role: ["%Y-%m-%d"] for role in (date_role, "paid_date", "due_date")}})
        pair = {"preferred": "primary", "secondary": "secondary", "po_pattern": PATTERN, **(pair_options or {})}
        policy = {"repeat_sources": list(repeats), "cross_sources": [pair] if cross else []}
        config = {"schema_version": 1, "company_id": "synthetic", "reporting_currency": "USD", "sources": sources,
                  "taxonomy": {"path": "tree.csv", "fields": {"l1": "category"}},
                  "labels": {"path": "not-loaded.csv", "fields": {"record_id": "id"}},
                  "matching": matching if matching is not None else policy}
        (tmp_path / "tree.csv").write_text("category\nSynthetic terminal\n", encoding="utf-8")
        path = tmp_path / "company.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        eligible = assess_eligibility(normalize_company(ingest_company(load_config(path))))
        return eligible, count_purchases(eligible)
    return build


def indexed(result):
    return result.records.set_index("record_id")


def test_preferred_record_is_counted_and_secondary_is_linked(factory):
    eligible, result = factory()
    records = indexed(result)
    assert records.loc["P:p1", "include"] == 1
    assert records.loc["S:s1", "exclusion_reason"] == "DUPLICATE"
    assert records.loc["S:s1", "duplicate_of"] == ("P:p1",)
    assert records.loc["S:s1", "spend_value"] == 0
    pd.testing.assert_frame_equal(result.records[eligible.records.columns], eligible.records)
    assert result.eligible.normalized.ingested.labels is None


def test_reference_formats_and_numeric_po_line_are_configured(factory):
    _, result = factory(secondary=[{"po": "SAP ref PO-0001/10"}])
    row = indexed(result).loc["S:s1"]
    assert row.match_method == "po_line_match"
    assert row.duplicate_of == ("P:p1",)


def test_wrong_explicit_po_line_never_falls_back_to_other_line(factory):
    _, result = factory(secondary=[{"po": "PO-0001/20"}])
    assert indexed(result).loc["S:s1", "include"] == 1


def test_unknown_nonblank_po_is_not_ignored_for_a_text_match(factory):
    _, result = factory(secondary=[{"po": "PO-9999"}])
    assert indexed(result).loc["S:s1", "include"] == 1


def test_conflicting_po_line_metadata_is_flagged(factory):
    _, result = factory(secondary=[{"po": "PO-0001/10", "po_line": "20"}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and "PO_LINE_METADATA_CONFLICT" in row.matching_flags


def test_multiple_po_references_are_not_guessed(factory):
    _, result = factory(secondary=[{"po": "PO-0001 and PO-0002"}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and "MULTIPLE_PO_REFERENCES" in row.matching_flags


@pytest.mark.parametrize("status,reason", [("Cancelled", "CANCELLED"), ("Rejected", "NOT_APPROVED")])
def test_prior_status_exclusion_is_not_replaced(factory, status, reason):
    _, result = factory(secondary=[{"status": status}])
    row = indexed(result).loc["S:s1"]
    assert row.exclusion_reason == reason and row.duplicate_of == ()


def test_non_procurement_primary_cannot_suppress_valid_secondary(factory):
    _, result = factory(primary=[{"description": "Input VAT"}])
    records = indexed(result)
    assert records.loc["P:p1", "exclusion_reason"] == "NON_PROCUREMENT"
    assert records.loc["S:s1", "include"] == 1


def test_capacity_preserves_second_independent_invoice(factory):
    _, result = factory(secondary=[{"id": "s1", "invoice": "INV-1"}, {"id": "s2", "invoice": "INV-2"}])
    records = indexed(result)
    assert records.loc["S:s1", "include"] == 0
    assert records.loc["S:s2", "include"] == 1
    assert "PREFERRED_CAPACITY_EXHAUSTED" in records.loc["S:s2", "matching_flags"]


def test_equivalent_receipts_have_separate_capacity(factory):
    _, result = factory(primary=[{"id": "p1"}, {"id": "p2"}], secondary=[{"id": "s1", "invoice": "I1"}, {"id": "s2", "invoice": "I2"}])
    records = indexed(result)
    assert records.loc["S:s1", "include"] == records.loc["S:s2", "include"] == 0
    assert records.loc["S:s1", "duplicate_of"] != records.loc["S:s2", "duplicate_of"]


def test_missing_po_can_match_unique_supplier_item_amount_quantity(factory):
    _, result = factory(secondary=[{"po": ""}])
    assert indexed(result).loc["S:s1", "match_method"] == "no_po_match"


def test_missing_po_with_two_equivalent_orders_is_ambiguous(factory):
    _, result = factory(primary=[{"id": "p1"}, {"id": "p2", "po": "PO-0002"}], secondary=[{"po": ""}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and "AMBIGUOUS_CROSS_SYSTEM_MATCH" in row.matching_flags


@pytest.mark.parametrize("changes", [{"description": "Parts"}, {"date": "2024-06-01"}, {"supplier": "Entirely Different Vendor"}, {"quantity": "3"}])
def test_missing_po_requires_all_additional_evidence(factory, changes):
    _, result = factory(secondary=[{"po": "", **changes}])
    assert indexed(result).loc["S:s1", "include"] == 1


def test_missing_dates_do_not_invent_a_date_or_block_unique_evidence(factory):
    _, result = factory(primary=[{"date": ""}], secondary=[{"po": "", "date": ""}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 0 and "date_unavailable" in row.match_evidence


def test_no_po_numeric_specs_are_not_lost_in_punctuation_cleanup(factory):
    _, result = factory(primary=[{"description": "Steel bolt 25.6 mm"}], secondary=[{"po": "", "description": "Steel bolt 256 mm"}])
    assert indexed(result).loc["S:s1", "include"] == 1


def test_repeated_exports_require_full_business_fingerprint(factory):
    _, result = factory(primary=[], secondary=[{"id": "s1", "invoice_line": "001"}, {"id": "s2", "invoice_line": "001"}], cross=False)
    assert result.summary()["duplicate_rows"] == 1
    assert indexed(result).loc["S:s2", "duplicate_of"] == ("S:s1",)


def test_same_invoice_line_with_different_amount_or_unknown_dimension_is_retained(factory):
    _, result = factory(primary=[], secondary=[{"id": "s1", "invoice_line": "001"},
                                              {"id": "s2", "invoice_line": "001", "amount": "200"},
                                              {"id": "s3", "invoice_line": "001", "extra": "allocation-2"}], cross=False)
    assert result.summary()["duplicate_rows"] == 0
    assert all("INVOICE_LINE_CONFLICT" in flags for flags in result.records.matching_flags)


def test_different_declared_invoice_lines_are_not_duplicates(factory):
    _, result = factory(primary=[], secondary=[{"id": "s1", "invoice_line": "001"}, {"id": "s2", "invoice_line": "002"}], cross=False)
    assert result.summary()["duplicate_rows"] == 0


def test_payment_lifecycle_changes_do_not_create_another_purchase(factory):
    _, result = factory(primary=[], secondary=[
        {"id": "s1", "invoice_line": "001", "status": "Approved"},
        {"id": "s2", "invoice_line": "001", "paid": "2024-02-01", "due": "2024-01-31"},
    ], cross=False)
    assert result.summary()["duplicate_rows"] == 1


def test_changed_invoice_date_is_still_a_business_conflict(factory):
    _, result = factory(primary=[], secondary=[
        {"id": "s1", "invoice_line": "001"}, {"id": "s2", "invoice_line": "001", "date": "2025-01-10"},
    ], cross=False)
    assert result.summary()["duplicate_rows"] == 0


def test_repeat_export_links_are_flattened_to_counted_erp(factory):
    _, result = factory(secondary=[{"id": "s1"}, {"id": "s2"}])
    records = indexed(result)
    assert result.summary()["duplicate_rows"] == 2
    assert records.loc["S:s2", "duplicate_of"] == ("P:p1",)
    assert records.loc["S:s1", "duplicate_of"] == ("P:p1",)


def test_generic_lines_without_line_identity_are_not_collapsed(factory):
    _, result = factory(primary=[], secondary=[{"id": "s1", "description": "Parts"}, {"id": "s2", "description": "Parts"}], cross=False)
    assert result.summary()["duplicate_rows"] == 0


def test_cancelled_copy_keeps_status_even_when_approved_copy_exists(factory):
    _, result = factory(primary=[], secondary=[{"id": "s1"}, {"id": "s2", "status": "Cancelled"}], cross=False)
    assert indexed(result).loc["S:s2", "exclusion_reason"] == "CANCELLED"


def test_full_receipt_group_matches_one_consolidated_invoice(factory):
    _, result = factory(primary=[{"id": "p1", "amount": "100", "quantity": "1"}, {"id": "p2", "amount": "200", "quantity": "2"}],
                        secondary=[{"amount": "300", "quantity": "3"}])
    row = indexed(result).loc["S:s1"]
    assert row.match_method == "receipt_group"
    assert row.duplicate_of == ("P:p1", "P:p2")


def test_multiple_invoice_lines_match_one_receipt(factory):
    _, result = factory(primary=[{"amount": "300", "quantity": "3"}],
                        secondary=[{"id": "s1", "amount": "100", "quantity": "1"}, {"id": "s2", "amount": "200", "quantity": "2"}])
    records = indexed(result)
    assert records.loc["S:s1", "match_method"] == records.loc["S:s2", "match_method"] == "invoice_group"
    assert records.loc["S:s1", "duplicate_of"] == records.loc["S:s2", "duplicate_of"] == ("P:p1",)


def test_partial_invoices_share_a_receipt_quantity_budget(factory):
    _, result = factory(primary=[{"amount": "100", "quantity": "10"}], secondary=[
        {"id": "s1", "invoice": "I1", "amount": "40", "quantity": "4"},
        {"id": "s2", "invoice": "I2", "amount": "60", "quantity": "6"},
        {"id": "s3", "invoice": "I3", "amount": "10", "quantity": "1"},
    ])
    records = indexed(result)
    assert records.loc["S:s1", "match_method"] == records.loc["S:s2", "match_method"] == "quantity_coverage"
    assert records.loc["S:s3", "include"] == 1
    assert sum(a.get("quantity_claims", {}).get("P:p1", 0) for a in result.allocations) == 10


def test_partly_covered_invoice_is_retained_without_amount_rewrite(factory):
    _, result = factory(primary=[{"amount": "100", "quantity": "10"}], secondary=[{"amount": "150", "quantity": "15"}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and row.spend_value == Decimal(150)
    assert "QUANTITY_COVERAGE_INSUFFICIENT" in row.matching_flags


def test_quantity_coverage_can_span_receipts_and_leave_a_balance(factory):
    _, result = factory(primary=[{"id": "p1", "amount": "50", "quantity": "5"}, {"id": "p2", "amount": "70", "quantity": "7"}],
                        secondary=[{"amount": "100", "quantity": "10"}])
    row = indexed(result).loc["S:s1"]
    assert row.match_method == "quantity_coverage" and row.duplicate_of == ("P:p1", "P:p2")
    assert sum(result.allocations[-1]["quantity_claims"].values()) == 10


def test_incompatible_unit_price_is_not_quantity_coverage(factory):
    _, result = factory(primary=[{"amount": "100", "quantity": "10"}], secondary=[{"amount": "41", "quantity": "4"}])
    assert indexed(result).loc["S:s1", "include"] == 1


def test_positive_amount_with_negative_quantity_is_not_abs_repaired_for_coverage(factory):
    _, result = factory(primary=[{"amount": "100", "quantity": "-10"}], secondary=[{"amount": "40", "quantity": "4"}])
    assert indexed(result).loc["S:s1", "include"] == 1
    assert "QUANTITY_SIGN_CONFLICT" in indexed(result).loc["P:p1", "matching_flags"]


def test_no_po_candidate_limit_leaves_records_visible(factory):
    _, result = factory(primary=[{"id": "p1"}, {"id": "p2", "po": "PO-0002"}],
                        secondary=[{"po": ""}], pair_options={"max_candidates": 1})
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and "MATCH_CANDIDATE_LIMIT" in row.matching_flags


def test_credit_signs_are_preserved_and_not_matched_to_positive_spend(factory):
    _, result = factory(primary=[{"amount": "-100", "quantity": "-2"}], secondary=[{"amount": "100", "quantity": "2"}])
    assert indexed(result).loc["S:s1", "include"] == 1
    _, credit = factory(primary=[{"amount": "-100", "quantity": "-2"}], secondary=[{"amount": "-100", "quantity": "2"}])
    assert indexed(credit).loc["S:s1", "include"] == 0
    assert indexed(credit).loc["P:p1", "spend_value"] == Decimal(-100)


def test_amount_tolerance_is_absolute_and_does_not_round_to_match(factory):
    _, inside = factory(secondary=[{"amount": "100.004"}])
    assert indexed(inside).loc["S:s1", "include"] == 0
    _, outside = factory(secondary=[{"amount": "100.02"}])
    assert indexed(outside).loc["S:s1", "include"] == 1


def test_missing_financial_value_cannot_become_a_duplicate_by_itself(factory):
    _, result = factory(secondary=[{"amount": ""}])
    row = indexed(result).loc["S:s1"]
    assert row.include == 1 and row.spend_value is None
    assert result.summary()["included_unresolved_financial_rows"] == 1


def test_deterministic_under_input_order_changes(factory):
    p = [{"id": "p1"}, {"id": "p2"}]
    s = [{"id": "s1", "invoice": "I1"}, {"id": "s2", "invoice": "I2"}]
    _, forward = factory(p, s)
    _, backward = factory(p[::-1], s[::-1])
    columns = ["include", "exclusion_reason", "spend_value", "duplicate_of", "match_method"]
    pd.testing.assert_frame_equal(indexed(forward)[columns].sort_index(), indexed(backward)[columns].sort_index())


def test_matching_does_not_use_low_process_decimal_precision(factory):
    with localcontext() as context:
        context.prec = 4
        _, result = factory(primary=[{"amount": "123456789.12"}], secondary=[{"amount": "123456789.12"}])
    assert indexed(result).loc["P:p1", "spend_value"] == Decimal("123456789.12")
    assert indexed(result).loc["S:s1", "include"] == 0


def test_empty_company_and_disabled_matching_preserve_schema(factory):
    _, empty = factory([], [])
    assert empty.summary()["record_count"] == 0
    _, disabled = factory(matching={})
    assert disabled.summary()["duplicate_rows"] == 0


@pytest.mark.parametrize("options", [
    {"amount_tolerance": "-1"}, {"amount_tolerance": "NaN"}, {"amount_tolerance": 0.1},
    {"quantity_tolerance": "invalid"}, {"supplier_similarity": 1.1}, {"supplier_similarity": True},
    {"max_candidates": 0}, {"max_group_size": False}, {"max_no_po_date_gap_days": -1},
    {"po_pattern": "["}, {"po_pattern": "[0-9]+"}, {"po_pattern": "(?P<po>.*)"},
    {"preferred": "unknown"}, {"secondary": "primary"},
])
def test_invalid_matching_options_fail(factory, options):
    with pytest.raises(ConfigError):
        factory(pair_options=options)


@pytest.mark.parametrize("policy", [
    {"repeat_sources": ["unknown"]}, {"repeat_sources": ["secondary", "secondary"]},
    {"cross_sources": [
        {"preferred": "primary", "secondary": "secondary", "po_pattern": PATTERN},
        {"preferred": "secondary", "secondary": "primary", "po_pattern": PATTERN},
    ]},
])
def test_invalid_source_policies_fail(factory, policy):
    with pytest.raises(ConfigError):
        factory(matching=policy)


def test_cli_aggregates_and_incomplete_exit(factory, tmp_path):
    factory()
    command = [sys.executable, "-m", "cantill", "deduplicate", "--config", str(tmp_path / "company.yaml")]
    valid = subprocess.run(command, text=True, capture_output=True)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["duplicate_rows"] == 1
    assert "Acme" not in valid.stdout and "P:p1" not in valid.stdout
    factory(secondary=[{"amount": ""}])
    incomplete = subprocess.run(command, text=True, capture_output=True)
    assert incomplete.returncode == 1
    assert json.loads(incomplete.stdout)["included_unresolved_financial_rows"] == 1
