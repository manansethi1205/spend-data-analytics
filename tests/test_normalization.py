"""Synthetic financial/date behavior; no source records or golden mappings."""

import csv
from dataclasses import replace
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal, localcontext

import pandas as pd
import pytest
import yaml

from cantill.config import ConfigError, FinancialFallbackConfig, load_config
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company, parse_date, parse_number


@pytest.fixture
def factory(tmp_path):
    def build(changes=None, options=None, fx=None, fx_options=None, reporting="USD", rows=None):
        row = {"id": "0001", "amount": "115", "currency": "USD", "currency_rate": "", "vat": "",
               "invoice": "2024-01-15", "posting": "2024-01-16", "due": "2024-02-15", "paid": "",
               "quantity": "1.000", "unit_cost": ""}
        row.update(changes or {})
        source = {
            "name": "purchases", "path": "purchases.csv", "amount_basis": "net",
            "number_format": {"decimal": ".", "thousands": ""},
            "date_formats": {k: ["%Y-%m-%d"] for k in ("invoice_date", "posting_date", "due_date", "paid_date")},
            "fields": {"source_record_id": "id", "amount": "amount", "currency": "currency",
                       "currency_rate": "currency_rate", "vat_rate": "vat", "invoice_date": "invoice",
                       "posting_date": "posting", "due_date": "due", "paid_date": "paid",
                       "quantity": "quantity", "unit_cost": "unit_cost"},
        }
        source.update(options or {})
        config = {"schema_version": 1, "company_id": "synthetic", "reporting_currency": reporting,
                  "sources": [source], "taxonomy": {"path": "tree.csv", "fields": {"l1": "category"}},
                  "labels": {"path": "missing-labels.csv", "fields": {"record_id": "id"}}}
        with (tmp_path / "purchases.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerows(rows if rows is not None else [row])
        (tmp_path / "tree.csv").write_text("category\nSynthetic terminal\n", encoding="utf-8")
        if fx is not None:
            with (tmp_path / "rates.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["currency", "month", "units_per_usd"])
                writer.writeheader()
                writer.writerows(fx)
            config["fx"] = {"path": "rates.csv", "fields": {
                "currency": "currency", "month": "month", "units_per_usd": "units_per_usd"}, **(fx_options or {})}
        path = tmp_path / "company.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        ingested = ingest_company(load_config(path))
        return ingested, normalize_company(ingested)
    return build


@pytest.mark.parametrize("value,formats,expected", [
    ("1,234.56", {"decimal": ".", "thousands": ","}, "1234.56"),
    ("1.234,56", {"decimal": ",", "thousands": "."}, "1234.56"),
    ("1\u00a0234,56", {"decimal": ",", "thousands": " "}, "1234.56"),
    ("1.000", {"decimal": ".", "thousands": ""}, "1"),
    ("1,234", {"decimal": ",", "thousands": ""}, "1.234"),
    ("(1,234.56)", {"decimal": ".", "thousands": ","}, "-1234.56"),
    (" -1.25e2 ", {"decimal": ".", "thousands": ""}, "-125"),
    (".5", {"decimal": ".", "thousands": ""}, "0.5"),
])
def test_declared_number_formats(value, formats, expected):
    assert parse_number(value, formats) == Decimal(expected)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1_000", "12,34.56", "1,2,3", "(-1)", "", " ", "USD 1"])
def test_invalid_numbers_are_not_guessed(value):
    assert parse_number(value, {"decimal": ".", "thousands": ","}) is None


def test_blank_amount_fallback_is_opt_in_and_preserves_raw(factory):
    ingested, strict = factory(changes={"amount": ""})
    assert not strict.records.iloc[0].financial_ready
    ingested.config = replace(ingested.config, financial_fallback=FinancialFallbackConfig(missing_amount="zero"))
    row = normalize_company(ingested).records.iloc[0]
    assert row.amount == "" and row.reporting_amount_value == Decimal(0)
    assert row.financial_ready and row.financial_estimated
    assert {"AMOUNT_MISSING", "AMOUNT_ESTIMATED_ZERO"} <= set(row.quality_flags)


def test_zero_policy_does_not_hide_invalid_amount(factory):
    ingested, _ = factory(changes={"amount": "broken"})
    ingested.config = replace(ingested.config, financial_fallback=FinancialFallbackConfig(missing_amount="zero"))
    row = normalize_company(ingested).records.iloc[0]
    assert not row.financial_ready and not row.financial_estimated


@pytest.mark.parametrize("invoice,expected_month,expected", [
    ("2024-02-15", "2024-01", "57.5"),  # Equal-distance tie chooses earlier.
    ("2024-04-15", "2024-03", "28.75"),
    ("2023-12-15", "2024-01", "57.5"),
])
def test_nearest_fx_is_opt_in_and_auditable(factory, invoice, expected_month, expected):
    ingested, strict = factory(changes={"currency": "CAD", "invoice": invoice}, fx=[
        {"currency": "CAD", "month": "2024-01", "units_per_usd": "2"},
        {"currency": "CAD", "month": "2024-03", "units_per_usd": "4"},
        {"currency": "EUR", "month": "2024-02", "units_per_usd": "100"}])
    assert not strict.records.iloc[0].financial_ready
    ingested.config = replace(ingested.config, financial_fallback=FinancialFallbackConfig(missing_fx="nearest_month"))
    row = normalize_company(ingested).records.iloc[0]
    assert row.reporting_amount_value == Decimal(expected)
    assert row.fx_reference_month == expected_month and row.fx_month == invoice[:7]
    assert row.exchange_rate_source == "nearest_month_fx" and row.financial_estimated
    assert "FX_RATE_MISSING" in row.quality_flags


@pytest.mark.parametrize("rate,expected,estimated", [("3", "3", False), ("broken", None, False)])
def test_nearest_fx_preserves_direct_rate_precedence(factory, rate, expected, estimated):
    ingested, _ = factory(changes={"currency": "CAD", "currency_rate": rate}, fx=[
        {"currency": "CAD", "month": "2024-02", "units_per_usd": "2"}])
    ingested.config = replace(ingested.config, financial_fallback=FinancialFallbackConfig(missing_fx="nearest_month"))
    row = normalize_company(ingested).records.iloc[0]
    assert row.exchange_rate_value == (Decimal(expected) if expected else None)
    assert row.financial_estimated == estimated


def test_nearest_fx_without_currency_reference_stays_unresolved(factory):
    ingested, _ = factory(changes={"currency": "CAD"}, fx=[])
    ingested.config = replace(ingested.config, financial_fallback=FinancialFallbackConfig(missing_fx="nearest_month"))
    assert not normalize_company(ingested).records.iloc[0].financial_ready


@pytest.mark.parametrize("kwargs", [{"missing_amount": "average"}, {"missing_fx": "posting_month"}])
def test_unknown_financial_policy_rejected(kwargs):
    with pytest.raises(ConfigError):
        FinancialFallbackConfig(**kwargs)


@pytest.mark.parametrize("value,formats,expected,issue", [
    ("2024-02-29", ("%Y-%m-%d",), date(2024, 2, 29), ""),
    ("2023-02-29", ("%Y-%m-%d",), None, "INVALID"),
    ("", ("%Y-%m-%d",), None, "MISSING"),
    ("07-Feb-24", ("%d-%b-%y",), date(2024, 2, 7), ""),
    ("03/04/2024", ("%d/%m/%Y",), date(2024, 4, 3), ""),
    ("03/04/2024", ("%d/%m/%Y", "%m/%d/%Y"), None, "AMBIGUOUS"),
    ("12/12/2024", ("%d/%m/%Y", "%m/%d/%Y"), date(2024, 12, 12), ""),
])
def test_date_formats_and_ambiguity(value, formats, expected, issue):
    parsed, used, actual_issue = parse_date(value, formats)
    assert parsed == expected and actual_issue == issue
    assert bool(used) == (expected is not None)


@pytest.mark.parametrize("vat", ["0.15", "15", "15%", "15 %", ""])
def test_vat_representations_and_blank_default(factory, vat):
    _, result = factory({"vat": vat}, {"amount_basis": "gross", "vat_default": "0.15"})
    row = result.records.iloc[0]
    assert row.net_amount_value == row.reporting_amount_value == Decimal("100")
    assert row.vat_rate_value == Decimal("0.15")
    assert row.vat_source == ("default" if not vat else "line")
    assert ("VAT_DEFAULTED" in row.quality_flags) == (not vat)


def test_explicit_zero_vat_is_not_defaulted(factory):
    _, result = factory({"vat": "0"}, {"amount_basis": "gross", "vat_default": "0.15"})
    assert result.records.iloc[0].reporting_amount_value == Decimal("115")
    assert "VAT_DEFAULTED" not in result.records.iloc[0].quality_flags


@pytest.mark.parametrize("vat", ["invalid", "-15", "150%"])
def test_invalid_nonblank_vat_does_not_use_default(factory, vat):
    _, result = factory({"vat": vat}, {"amount_basis": "gross", "vat_default": "0.15"})
    row = result.records.iloc[0]
    assert row.reporting_amount_value is None
    assert "VAT_INVALID" in row.quality_flags


def test_missing_vat_without_default_is_unresolved(factory):
    _, result = factory(options={"amount_basis": "gross"})
    assert "VAT_MISSING" in result.records.iloc[0].quality_flags
    assert not result.records.iloc[0].financial_ready


@pytest.mark.parametrize("basis", ["net", "as_provided"])
def test_net_or_as_provided_does_not_remove_vat(factory, basis):
    _, result = factory({"vat": "15%"}, {"amount_basis": basis})
    assert result.records.iloc[0].net_amount_value == Decimal("115")
    assert result.records.iloc[0].vat_source == "not_applicable"


@pytest.mark.parametrize("rate", ["2", "0", "-1", "invalid"])
def test_reporting_currency_identity_ignores_line_rate(factory, rate):
    _, result = factory({"currency_rate": rate})
    row = result.records.iloc[0]
    assert row.reporting_amount_value == Decimal("115")
    assert row.exchange_rate_source == "identity"


@pytest.mark.parametrize("convention,rate", [("units_per_reporting", "2"), ("reporting_per_unit", "0.5")])
def test_line_rate_direction_is_configured(factory, convention, rate):
    _, result = factory({"currency": "EUR", "currency_rate": rate}, {"rate_convention": convention})
    assert result.records.iloc[0].reporting_amount_value == Decimal("57.5")
    assert result.records.iloc[0].exchange_rate_source == "line"


def test_line_rate_precedes_monthly_rate(factory):
    _, result = factory({"currency": "EUR", "currency_rate": "4"}, fx=[
        {"currency": "EUR", "month": "2024-01", "units_per_usd": "2"}])
    assert result.records.iloc[0].reporting_amount_value == Decimal("28.75")


def test_monthly_fx_uses_invoice_month_and_table_number_format(factory):
    _, result = factory({"currency": "eur", "posting": "2024-02-01"},
                        fx=[{"currency": "EUR", "month": "01/2024", "units_per_usd": "2,0"}],
                        fx_options={"month_format": "%m/%Y", "number_format": {"decimal": ",", "thousands": "."}})
    row = result.records.iloc[0]
    assert row.reporting_amount_value == Decimal("57.5")
    assert row.exchange_rate_source == "monthly_fx" and row.fx_month == "2024-01"


def test_no_posting_or_nearest_month_substitution(factory):
    _, result = factory({"currency": "EUR", "posting": "2024-02-01"}, fx=[
        {"currency": "EUR", "month": "2024-02", "units_per_usd": "2"}])
    row = result.records.iloc[0]
    assert row.reporting_amount_value is None and "FX_RATE_MISSING" in row.quality_flags


def test_monthly_table_convention_is_independent_of_line_rate_convention(factory):
    _, result = factory({"currency": "EUR"}, {"rate_convention": "reporting_per_unit"}, fx=[
        {"currency": "EUR", "month": "2024-01", "units_per_usd": "2"}])
    row = result.records.iloc[0]
    assert row.reporting_amount_value == Decimal("57.5")
    assert row.exchange_rate_convention == "units_per_reporting"


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "invalid"])
def test_invalid_line_rate_is_not_silently_replaced(factory, rate):
    _, result = factory({"currency": "EUR", "currency_rate": rate}, fx=[
        {"currency": "EUR", "month": "2024-01", "units_per_usd": "2"}])
    assert result.records.iloc[0].reporting_amount_value is None
    assert "LINE_RATE_INVALID" in result.records.iloc[0].quality_flags


@pytest.mark.parametrize("rate", ["0", "-1", "NaN"])
def test_invalid_monthly_rate_is_flagged(factory, rate):
    _, result = factory({"currency": "EUR"}, fx=[
        {"currency": "EUR", "month": "2024-01", "units_per_usd": rate}])
    assert result.reference_flags["FX_RATE_INVALID"] == 1
    assert "FX_RATE_INVALID" in result.records.iloc[0].quality_flags


def test_monthly_fx_normalization_cannot_hide_duplicate_keys(factory):
    with pytest.raises(ConfigError, match="duplicate normalized"):
        factory({"currency": "EUR"}, fx=[
            {"currency": "EUR", "month": "2024-01", "units_per_usd": "2"},
            {"currency": "eur", "month": "2024-01", "units_per_usd": "3"}])


def test_invalid_fx_key_is_visible_in_reference_audit(factory):
    _, result = factory({"currency": "EUR"}, fx=[
        {"currency": "EUR", "month": "invalid", "units_per_usd": "2"}])
    assert result.reference_flags["FX_KEY_INVALID"] == 1
    assert not result.records.iloc[0].financial_ready


@pytest.mark.parametrize("amount,flag", [("", "AMOUNT_MISSING"), ("invalid", "AMOUNT_INVALID")])
def test_unresolved_amount_is_not_zero_or_excluded(factory, amount, flag):
    _, result = factory({"amount": amount})
    assert result.records.iloc[0].reporting_amount_value is None
    assert flag in result.records.iloc[0].quality_flags
    assert result.summary()["unresolved_financial_rows"] == 1
    assert "include" not in result.records.columns


@pytest.mark.parametrize("amount", ["-115", "0"])
def test_signs_and_zero_survive_tax_and_fx(factory, amount):
    _, result = factory({"amount": amount, "vat": "15%", "currency": "EUR", "currency_rate": "2"},
                        {"amount_basis": "gross"})
    assert result.records.iloc[0].reporting_amount_value == Decimal("-50" if amount.startswith("-") else "0")


def test_missing_or_invalid_date_blocks_only_monthly_fx(factory):
    _, monthly = factory({"currency": "EUR", "invoice": "impossible"})
    assert "INVOICE_DATE_INVALID" in monthly.records.iloc[0].quality_flags
    assert "FX_INVOICE_DATE_UNRESOLVED" in monthly.records.iloc[0].quality_flags
    _, line = factory({"currency": "EUR", "invoice": "impossible", "currency_rate": "2"})
    assert line.records.iloc[0].financial_ready


def test_chronology_flags_do_not_repair_or_exclude_dates(factory):
    _, result = factory({"invoice": "2025-02-01", "posting": "2024-01-01",
                         "due": "2025-01-01", "paid": "2024-12-01"})
    row = result.records.iloc[0]
    assert {"INVOICE_AFTER_POSTING", "INVOICE_POSTING_GAP_OVER_366_DAYS", "DUE_BEFORE_INVOICE", "PAID_BEFORE_INVOICE"} <= set(row.quality_flags)
    assert row.invoice_date_value == date(2025, 2, 1)
    assert row.financial_ready


@pytest.mark.parametrize("currency,flag", [("", "CURRENCY_MISSING"), ("$", "CURRENCY_INVALID")])
def test_currency_is_not_assumed_from_reporting(factory, currency, flag):
    _, result = factory({"currency": currency})
    assert flag in result.records.iloc[0].quality_flags
    assert not result.records.iloc[0].financial_ready


def test_no_premature_cent_rounding_and_controlled_precision(factory):
    with localcontext() as context:
        context.prec = 4
        _, result = factory({"amount": "100", "currency": "EUR", "currency_rate": "3"})
    with localcontext() as context:
        context.prec = 50
        assert result.records.iloc[0].reporting_amount_value == Decimal(100) / 3
    assert result.records.iloc[0].reporting_amount_value != Decimal("33.33")


def test_identity_preserves_more_than_fifty_digits(factory):
    value = "123456789012345678901234567890123456789012345678901234567890.12"
    _, result = factory({"amount": value})
    assert result.records.iloc[0].reporting_amount_value == Decimal(value)


def test_canonical_cells_and_raw_rows_are_unchanged(factory):
    company, result = factory({"currency": "EUR", "currency_rate": "2", "unit_cost": "bad"})
    original = company.records.copy(deep=True)
    pd.testing.assert_frame_equal(result.records[original.columns], original)
    pd.testing.assert_frame_equal(company.records, original)
    assert "UNIT_COST_INVALID" in result.records.iloc[0].quality_flags
    assert result.records.iloc[0].quantity_value == Decimal(1)
    assert result.ingested.labels is None


def test_empty_input_normalizes_without_dropping_schema(factory):
    _, result = factory(rows=[])
    assert result.summary()["record_count"] == 0
    assert result.summary()["all_amounts_resolved"]
    assert "reporting_amount_value" in result.records


def test_config_rejects_wrong_rate_convention_and_non_usd_fx(factory):
    with pytest.raises(ConfigError, match="rate_convention"):
        factory(options={"rate_convention": "guess"})
    with pytest.raises(ConfigError, match="USD reporting"):
        factory(reporting="ZAR", fx=[])


@pytest.mark.parametrize("grouping", ["e", "E", "1", "+", "-", "%"])
def test_config_rejects_number_format_that_could_corrupt_values(factory, grouping):
    with pytest.raises(ConfigError, match="grouping"):
        factory(options={"number_format": {"decimal": ".", "thousands": grouping}})


def test_cli_normalization_exit_codes_and_no_records_in_output(factory, tmp_path):
    factory()
    command = [sys.executable, "-m", "cantill", "normalize", "--config", str(tmp_path / "company.yaml")]
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["all_amounts_resolved"]
    assert "0001" not in good.stdout
    factory({"amount": ""})
    incomplete = subprocess.run(command, capture_output=True, text=True)
    assert incomplete.returncode == 1
    assert json.loads(incomplete.stdout)["unresolved_financial_rows"] == 1
