"""Submission contract tests use synthetic rows and runtime category trees."""

import copy
import csv
import json
import subprocess
import sys
from decimal import Decimal, localcontext

import pytest

from cantill.output import OUTPUT_COLUMNS, validate_output


IDS = ("ERP:001", "TOOL:002")
TREE = (("Root", "Branch", "Family", "Leaf"), ("Root", "Other terminal"))


@pytest.fixture
def rows():
    return [
        dict(zip(OUTPUT_COLUMNS, ["ERP:001", "1", "", "supplier, one", "item-001",
                                 "-12.30", "Root", "Branch", "Family", "Leaf", "0.8"])),
        dict(zip(OUTPUT_COLUMNS, ["TOOL:002", "0", "DUPLICATE", "supplier, one", "item-001",
                                 "0", "", "", "", "", "0.95"])),
    ]


def save(tmp_path, rows, header=OUTPUT_COLUMNS):
    path = tmp_path / "output.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows([row.get(c, "") for c in header] for row in rows)
    return path


def test_valid_output_preserves_credits_and_is_read_only(tmp_path, rows):
    path = save(tmp_path, rows)
    before = path.read_bytes()
    result = validate_output(path, IDS, TREE)
    assert result.valid
    assert result.row_count == 2
    assert result.included_rows == result.excluded_rows == 1
    assert result.summary()["total_spend"] == "-12.30"
    assert path.read_bytes() == before


def test_row_order_does_not_change_exact_coverage(tmp_path, rows):
    assert validate_output(save(tmp_path, rows[::-1]), IDS, TREE).valid


@pytest.mark.parametrize("header", [OUTPUT_COLUMNS[::-1], OUTPUT_COLUMNS[:-1],
                                      (*OUTPUT_COLUMNS, "extra"), (*OUTPUT_COLUMNS[:-1], "spend")])
def test_exact_header_required(tmp_path, rows, header):
    result = validate_output(save(tmp_path, rows, header), IDS, TREE)
    assert not result.valid and result.error_counts["HEADER_MISMATCH"] == 1


@pytest.mark.parametrize("reason", ["CANCELLED", "NOT_APPROVED", "NON_PROCUREMENT", "DUPLICATE"])
def test_all_permitted_exclusions(tmp_path, rows, reason):
    rows[1]["exclusion_reason"] = reason
    assert validate_output(save(tmp_path, rows), IDS, TREE).valid


@pytest.mark.parametrize("reason", ["", "OTHER", "duplicate", " DUPLICATE"])
def test_invalid_exclusion_reason(tmp_path, rows, reason):
    rows[1]["exclusion_reason"] = reason
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.error_counts["EXCLUDED_REASON_INVALID"] == 1


def test_included_reason_must_be_exactly_blank(tmp_path, rows):
    rows[0]["exclusion_reason"] = " "
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["INCLUDED_EXCLUSION_REASON"] == 1


@pytest.mark.parametrize("include", ["true", "False", "1.0", " 1", "2", ""])
def test_invalid_include(tmp_path, rows, include):
    rows[0]["include"] = include
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["INVALID_INCLUDE"] == 1


@pytest.mark.parametrize("column", ["supplier_key", "item_key"])
@pytest.mark.parametrize("value", ["", "   "])
def test_included_entity_keys_required(tmp_path, rows, column, value):
    rows[0][column] = value
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.error_counts[f"{column.upper()}_REQUIRED"] == 1


def test_excluded_keys_may_be_blank_without_invented_grouping(tmp_path, rows):
    rows[1].update(supplier_key="", item_key="")
    assert validate_output(save(tmp_path, rows), IDS, TREE).valid


def test_whitespace_is_not_an_excluded_entity_key(tmp_path, rows):
    rows[1]["item_key"] = " "
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["WHITESPACE_ENTITY_KEY"] == 1


@pytest.mark.parametrize("value", ["NaN", "inf", "-Infinity", "1,000.00", "1_000", "", " ", "False"])
def test_invalid_spend(tmp_path, rows, value):
    rows[0]["spend"] = value
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.error_counts["INVALID_SPEND"] == 1
    assert result.summary()["total_spend"] is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "", "-0.01", "1.01", "true", "0,95"])
def test_invalid_confidence(tmp_path, rows, value):
    rows[0]["confidence"] = value
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["INVALID_CONFIDENCE"] == 1


@pytest.mark.parametrize("value", ["0", "1"])
def test_confidence_boundaries(tmp_path, rows, value):
    rows[0]["confidence"] = value
    assert validate_output(save(tmp_path, rows), IDS, TREE).valid


@pytest.mark.parametrize("value", ["1", "-0.01"])
def test_excluded_spend_is_zero(tmp_path, rows, value):
    rows[1]["spend"] = value
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["EXCLUDED_SPEND_NONZERO"] == 1


def test_zero_included_spend_is_not_automatically_excluded(tmp_path, rows):
    rows[0]["spend"] = "0"
    assert validate_output(save(tmp_path, rows), IDS, TREE).valid


@pytest.mark.parametrize("amount", ["1.25e2", " +125.00 "])
def test_standard_numeric_encodings_are_accepted(tmp_path, rows, amount):
    rows[0].update(spend=amount, confidence=" 8e-1 ")
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.valid
    assert result.total_spend == Decimal("125")


@pytest.mark.parametrize("categories", [
    ("Root", "Branch", "Family", ""), ("Root", "", "Family", "Leaf"),
    ("Root", "Branch", "Family", "Leaf "), ("Root", "Other terminal", "", "invented"),
    ("Wrong root", "Branch", "Family", "Leaf"),
])
def test_path_must_be_exact_complete_terminal(tmp_path, rows, categories):
    rows[0].update(zip(("l1", "l2", "l3", "l4"), categories))
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["INVALID_CATEGORY_PATH"] == 1


def test_included_category_is_required(tmp_path, rows):
    rows[0].update(l1="", l2="", l3="", l4="")
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["CATEGORY_REQUIRED"] == 1


def test_shallow_terminal_and_excluded_valid_category_are_allowed(tmp_path, rows):
    rows[0].update(l2="Other terminal", l3="", l4="")
    rows[1].update(l1="Root", l2="Branch", l3="Family", l4="Leaf")
    assert validate_output(save(tmp_path, rows), IDS, TREE).valid


def test_excluded_nonblank_categories_are_also_validated(tmp_path, rows):
    rows[1].update(l1="invented")
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["INVALID_CATEGORY_PATH"] == 1


def test_parent_row_is_not_accepted_as_lowest_level(tmp_path, rows):
    rows[0].update(l2="", l3="", l4="")
    assert validate_output(save(tmp_path, rows), IDS, (*TREE, ("Root",))).error_counts["INVALID_CATEGORY_PATH"] == 1


def test_duplicate_can_hide_a_missing_record_at_same_row_count(tmp_path, rows):
    rows[1]["record_id"] = rows[0]["record_id"]
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.row_count == len(IDS)
    assert result.error_counts["DUPLICATE_RECORD_ID"] == 1
    assert result.error_counts["MISSING_RECORDS"] == 1
    assert result.error_counts["EXTRA_RECORDS"] == 1


def test_unknown_id_does_not_satisfy_expected_coverage(tmp_path, rows):
    rows[1]["record_id"] = "TOOL:unexpected"
    result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.error_counts["MISSING_RECORDS"] == result.error_counts["EXTRA_RECORDS"] == 1


def test_dropped_excluded_record_is_missing_too(tmp_path, rows):
    result = validate_output(save(tmp_path, rows[:1]), IDS, TREE)
    assert result.error_counts["MISSING_RECORDS"] == 1


def test_blank_id_fails(tmp_path, rows):
    rows[1]["record_id"] = " "
    assert validate_output(save(tmp_path, rows), IDS, TREE).error_counts["BLANK_RECORD_ID"] == 1


def test_literal_na_keys_and_ids_are_not_nulls(tmp_path, rows):
    rows[0].update(record_id="NA", supplier_key="NA", item_key="null")
    assert validate_output(save(tmp_path, rows), ("NA", IDS[1]), TREE).valid


@pytest.mark.parametrize("tail", ["too,few,fields\n", ",".join(["x"] * 12) + "\n", '"unterminated'])
def test_malformed_csv_fails(tmp_path, tail):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(OUTPUT_COLUMNS) + "\n" + tail, encoding="utf-8")
    result = validate_output(path, IDS, TREE)
    assert not result.valid
    assert result.error_counts["CSV_ROW_WIDTH"] or result.error_counts["CSV_READ_ERROR"]


def test_missing_and_empty_output_files_fail(tmp_path):
    path = tmp_path / "missing.csv"
    assert validate_output(path, IDS, TREE).error_counts["CSV_READ_ERROR"] == 1
    path.write_text("", encoding="utf-8")
    assert validate_output(path, IDS, TREE).error_counts["HEADER_MISMATCH"] == 1


def test_empty_input_requires_header_only_output(tmp_path):
    assert validate_output(save(tmp_path, []), (), TREE).valid
    assert validate_output(save(tmp_path, []), IDS, TREE).error_counts["MISSING_RECORDS"] == 2


@pytest.mark.parametrize("expected", [("",), ("same", "same")])
def test_invalid_expected_identity_contract(tmp_path, rows, expected):
    assert validate_output(save(tmp_path, rows), expected, TREE).error_counts["INVALID_EXPECTED_IDS"] == 1


@pytest.mark.parametrize("tree", [(), (("",),), (("Root", "", "Leaf"),), (("A",) * 5,)])
def test_invalid_reference_tree(tmp_path, rows, tree):
    assert validate_output(save(tmp_path, rows), IDS, tree).error_counts["INVALID_TAXONOMY"] == 1


def test_decimal_total_does_not_round_under_low_process_precision(tmp_path, rows):
    rows[0]["spend"] = "123456789012345678901234567890.12"
    rows[1].update(include="1", exclusion_reason="", spend="0.01",
                   l1="Root", l2="Other terminal", l3="", l4="")
    with localcontext() as context:
        context.prec = 4
        result = validate_output(save(tmp_path, rows), IDS, TREE)
    assert result.valid
    assert result.total_spend == Decimal("123456789012345678901234567890.13")


def test_diagnostics_are_bounded_and_do_not_dump_records(tmp_path, rows):
    bad = []
    for index in range(45):
        row = copy.deepcopy(rows[0])
        row.update(record_id=f"secret-record-{index}", confidence="secret-cell")
        bad.append(row)
    result = validate_output(save(tmp_path, bad), (r["record_id"] for r in bad), TREE)
    assert result.error_counts["INVALID_CONFIDENCE"] == 45
    assert len(result.examples) == 20
    assert "secret-record" not in json.dumps(result.summary())
    assert "secret-cell" not in json.dumps(result.summary())
    assert result.summary()["total_spend"] is None


def test_cli_valid_invalid_and_input_error_exit_codes(tmp_path, rows):
    input_path = tmp_path / "purchases.csv"
    input_path.write_text("id,amount\nERP:001,-12.30\nTOOL:002,0\n", encoding="utf-8")
    tree = tmp_path / "tree.csv"
    with tree.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["a", "b", "c", "d"])
        writer.writerows([*path, *([""] * (4 - len(path)))] for path in TREE)
    config = {
        "schema_version": 1, "company_id": "synthetic", "reporting_currency": "USD",
        "sources": [{"name": "purchases", "path": "purchases.csv", "amount_basis": "net",
                     "number_format": {"decimal": ".", "thousands": ""},
                     "fields": {"source_record_id": "id", "amount": "amount"}}],
        "taxonomy": {"path": "tree.csv", "fields": {"l1": "a", "l2": "b", "l3": "c", "l4": "d"}},
        "labels": {"path": "never-open.csv", "fields": {"record_id": "id"}},
    }
    cfg = tmp_path / "company.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    output = save(tmp_path, rows)
    command = [sys.executable, "-m", "cantill", "validate-output", "--config", str(cfg), "--output", str(output)]
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["valid"] is True
    rows[1]["spend"] = "1"
    save(tmp_path, rows)
    bad = subprocess.run(command, capture_output=True, text=True)
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["valid"] is False
    input_path.unlink()
    input_error = subprocess.run(command, capture_output=True, text=True)
    assert input_error.returncode == 2
    assert "Traceback" not in input_error.stderr
