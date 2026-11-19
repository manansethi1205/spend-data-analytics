"""Synthetic eligibility evidence, precedence and label-independent splitting."""

import csv
import json
import subprocess
import sys
from decimal import Decimal

import pandas as pd
import pytest
import yaml

from cantill.config import ConfigError, load_config
from cantill.eligibility import assess_eligibility
from cantill.evaluation import eligibility_group, eligibility_partition
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company


@pytest.fixture
def factory(tmp_path):
    def build(changes=None, with_status=False, options=None, rules=None, rows=None):
        row = {"id": "0001", "amount": "10", "currency": "USD", "description": "ordinary replacement part",
               "account": "purchases", "status": "Paid", "paid": "", "supplier_type": "",
               "supplier": "Generic supplier", "doc_type": "ordinary"}
        row.update(changes or {})
        fields = {"source_record_id": "id", "amount": "amount", "currency": "currency", "description": "description",
                  "account_description": "account", "paid_date": "paid", "supplier_type": "supplier_type",
                  "supplier_name": "supplier", "document_type": "doc_type"}
        if with_status:
            fields["status"] = "status"
        source = {"name": "purchases", "path": "purchases.csv", "amount_basis": "net", "fields": fields,
                  "number_format": {"decimal": ".", "thousands": ""}, "date_formats": {"paid_date": ["%Y-%m-%d"]}}
        source.update(options or {})
        config = {"schema_version": 1, "company_id": "synthetic", "reporting_currency": "USD", "sources": [source],
                  "taxonomy": {"path": "tree.csv", "fields": {"l1": "category"}},
                  "labels": {"path": "not-loaded.csv", "fields": {"record_id": "id"}}}
        if rules is not None:
            config["eligibility"] = rules
        with (tmp_path / "purchases.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerows(rows if rows is not None else [row])
        (tmp_path / "tree.csv").write_text("category\nSynthetic terminal\n", encoding="utf-8")
        path = tmp_path / "company.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        normalized = normalize_company(ingest_company(load_config(path)))
        return normalized, assess_eligibility(normalized)
    return build


@pytest.mark.parametrize("status", ["Approved", "Paid", "  PAID  ", "Ａｐｐｒｏｖｅｄ"])
def test_only_explicit_allowed_statuses_count(factory, status):
    _, result = factory({"status": status}, with_status=True)
    assert result.records.iloc[0].eligible
    assert result.records.iloc[0].eligibility_reason == ""


@pytest.mark.parametrize("status", ["On Hold", "Rejected", "Submitted", "Disputed", "Unpaid", "Paid pending", "", " "])
def test_other_or_missing_status_is_not_approved(factory, status):
    _, result = factory({"status": status}, with_status=True)
    assert result.records.iloc[0].eligibility_reason == "NOT_APPROVED"
    assert result.records.iloc[0].eligible_amount_value == Decimal(0)


@pytest.mark.parametrize("status", ["Cancelled", "Canceled", "  CANCELLED "])
def test_cancelled_status_has_its_own_code(factory, status):
    _, result = factory({"status": status}, with_status=True)
    assert result.records.iloc[0].eligibility_reason == "CANCELLED"


@pytest.mark.parametrize("status,reason", [("Cancelled", "CANCELLED"), ("Rejected", "NOT_APPROVED"), ("Paid", "NON_PROCUREMENT")])
def test_status_precedes_non_procurement_and_keeps_all_evidence(factory, status, reason):
    _, result = factory({"status": status, "description": "Sales Tax Expense -"}, with_status=True)
    row = result.records.iloc[0]
    assert row.eligibility_reason == reason
    assert "rule:tax_control_line:description" in row.eligibility_evidence


@pytest.mark.parametrize("column,value,rule", [
    ("account", "IC42", "intercompany_account"),
    ("account", "I/C Payable", "intercompany_account"),
    ("account", "IC Payables", "intercompany_account"),
    ("account", "Inter-company receivables", "intercompany_account"),
    ("description", "Sales Tax Expense -", "tax_control_line"),
    ("description", "GST Input Tax -", "tax_control_line"),
    ("description", "State & Local Taxes -", "tax_control_line"),
    ("description", "State and Local Taxes - reconciliation", "tax_control_line"),
    ("description", "Input VAT", "tax_control_line"),
    ("account", "VAT payable: monthly control", "tax_control_line"),
    ("description", "Intercompany transfer - settlement", "intercompany_transfer"),
    ("description", "Royalty payment for mineral rights", "royalty_payment"),
    ("description", "Royalties", "royalty_payment"),
    ("description", "Partner billing: settlement", "partner_billing"),
    ("description", "Loan interest", "financing_cost"),
    ("description", "Financing costs - annual", "financing_cost"),
    ("account", "Sales revenue - export", "revenue_control"),
    ("account", "Accounts receivable", "revenue_control"),
])
def test_explicit_non_procurement_context(factory, column, value, rule):
    _, result = factory({column: value}, with_status=True)
    row = result.records.iloc[0]
    assert row.eligibility_reason == "NON_PROCUREMENT"
    assert any(e.startswith("rule:" + rule + ":") for e in row.eligibility_evidence)


@pytest.mark.parametrize("description", [
    "Tax advisory services", "Customs clearance and duties", "Interest rate analysis software",
    "Revenue management software", "Royalty management software", "Financing advisory services",
    "Intercompany transfer pricing advisory services", "IC chip replacement", "Partner training services",
    "State and local taxes advisory services",
])
def test_related_words_do_not_automatically_exclude_procurement(factory, description):
    _, result = factory({"description": description}, with_status=True)
    assert result.records.iloc[0].eligible


def test_supplier_name_does_not_trigger_generic_tax_description_rule(factory):
    _, result = factory({"supplier": "Sales Tax Expense"}, with_status=True)
    assert result.records.iloc[0].eligible


def test_missing_status_and_paid_date_are_visible_but_not_invented_rejections(factory):
    _, result = factory()
    row = result.records.iloc[0]
    assert row.eligible and "STATUS_UNAVAILABLE" in row.eligibility_flags
    assert "PAID_DATE_MISSING" in row.quality_flags
    assert "status:allowed" not in row.eligibility_evidence


@pytest.mark.parametrize("amount", ["0", "-10"])
def test_sign_or_zero_is_not_non_procurement_evidence(factory, amount):
    _, result = factory({"amount": amount, "doc_type": "credit"}, with_status=True)
    assert result.records.iloc[0].eligible
    assert result.records.iloc[0].eligible_amount_value == Decimal(amount)


def test_financial_failure_is_not_an_exclusion(factory):
    _, result = factory({"amount": ""}, with_status=True)
    row = result.records.iloc[0]
    assert row.eligible and row.eligible_amount_value is None
    assert "ELIGIBLE_AMOUNT_UNRESOLVED" in row.eligibility_flags
    assert result.summary()["eligible_unresolved_financial_rows"] == 1


def test_confirmed_non_procurement_can_have_zero_eligible_amount_without_repair(factory):
    _, result = factory({"amount": "", "description": "Input VAT"}, with_status=True)
    row = result.records.iloc[0]
    assert not row.eligible and row.eligible_amount_value == 0
    assert row.reporting_amount_value is None and "AMOUNT_MISSING" in row.quality_flags
    assert result.summary()["eligible_unresolved_financial_rows"] == 0


def test_original_normalized_records_are_unchanged_and_labels_unused(factory):
    normalized, result = factory({"description": "Input VAT"})
    pd.testing.assert_frame_equal(result.records[normalized.records.columns], normalized.records)
    assert normalized.ingested.labels is None
    assert "include" not in result.records.columns


def test_custom_status_vocabulary_is_config_only(factory):
    _, result = factory({"status": "VALIDÉ"}, with_status=True,
                        options={"approved_statuses": ["validé"], "cancelled_statuses": ["annulé"]})
    assert result.records.iloc[0].eligible


def test_custom_language_rule_and_source_scope(factory):
    _, result = factory({"description": "TVA collectée"}, rules={"additional_rules": [{
        "name": "local_tax_control", "fields": ["description"], "pattern": "^tva collectée$", "sources": ["purchases"],
    }]})
    assert result.records.iloc[0].eligibility_reason == "NON_PROCUREMENT"
    assert "rule:local_tax_control:description" in result.records.iloc[0].eligibility_evidence


def test_default_rule_can_be_disabled_by_config_for_a_different_chart(factory):
    _, result = factory({"account": "IC42"}, rules={"disabled_rules": ["intercompany_account"]})
    assert result.records.iloc[0].eligible


@pytest.mark.parametrize("options", [
    {"status_policy": "guess"}, {"status_policy": "require_approved"},
    {"approved_statuses": []}, {"approved_statuses": ["paid"], "cancelled_statuses": ["PAID"]},
    {"approved_statuses": [20]},
])
def test_invalid_status_config_is_rejected(factory, options):
    with pytest.raises(ConfigError):
        factory(options=options)


def test_config_cannot_ignore_a_declared_status_field(factory):
    with pytest.raises(ConfigError, match="status policy"):
        factory(with_status=True, options={"status_policy": "unavailable"})


@pytest.mark.parametrize("rules", [
    {"disabled_rules": ["unknown"]},
    {"additional_rules": [{"name": "bad", "fields": ["record_id"], "pattern": ".*"}]},
    {"additional_rules": [{"name": "bad", "fields": [], "pattern": ".*"}]},
    {"additional_rules": [{"name": "bad", "fields": ["description"], "pattern": "["}]},
    {"additional_rules": [{"name": "bad", "fields": ["description"], "pattern": ".*", "sources": ["unknown"]}]},
    {"additional_rules": [{"name": "intercompany_account", "fields": ["description"], "pattern": ".*"}]},
])
def test_invalid_custom_rule_is_rejected(factory, rules):
    with pytest.raises(ConfigError):
        factory(rules=rules)


def test_empty_inputs_keep_the_eligibility_schema(factory):
    _, result = factory(rows=[])
    assert result.summary()["record_count"] == 0
    assert result.summary()["eligible_unresolved_financial_rows"] == 0


def test_description_grouping_keeps_repeats_together_without_labels():
    left = {"description": "  VALVE   KIT ", "source_system": "one", "supplier_id": "x", "invoice_number": "1", "include": "1"}
    right = {**left, "description": "valve kit", "source_system": "two", "invoice_number": "2", "include": "0"}
    assert eligibility_group(left) == eligibility_group(right)
    assert eligibility_partition(eligibility_group(left)) == eligibility_partition(eligibility_group(right))


def test_blank_description_grouping_uses_invoice_scope():
    row = {"description": " ", "source_system": "one", "supplier_id": "vendor", "invoice_number": "invoice"}
    assert eligibility_group(row) == eligibility_group({**row, "description": ""})
    assert eligibility_group(row) != eligibility_group({**row, "supplier_id": "different"})


def test_cli_exit_codes_and_bounded_aggregate_output(factory, tmp_path):
    factory(with_status=True)
    command = [sys.executable, "-m", "cantill", "eligibility", "--config", str(tmp_path / "company.yaml")]
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["eligible_rows"] == 1
    assert "0001" not in good.stdout and "Generic supplier" not in good.stdout
    factory({"amount": ""}, with_status=True)
    incomplete = subprocess.run(command, capture_output=True, text=True)
    assert incomplete.returncode == 1
    assert json.loads(incomplete.stdout)["eligible_unresolved_financial_rows"] == 1
