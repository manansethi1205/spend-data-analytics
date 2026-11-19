"""Synthetic contract and config-only onboarding tests; no kit records."""

import copy
import csv
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
import yaml

from cantill.config import ConfigError, load_config
from cantill.ingest import ingest_company


def write_csv(path, columns, rows, delimiter=","):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(columns)
        writer.writerows(rows)


@pytest.fixture
def company(tmp_path):
    columns = ["doc", "money", "memo", "vendor", "when", "extra"]
    rows = [
        ["0001", "1.234,50", "élémént\nsize 02", "0007", "31.12.2024", "NA"],
        ["0002", "", "   ", "0007", "not-a-date", "null"],
        ["0003", "-4,50", "NA", "0008", "", "unmapped"],
    ]
    write_csv(tmp_path / "purchases.dat", columns, rows, ";")
    write_csv(tmp_path / "tree.csv", ["top", "middle", "family", "leaf"], [
        ["Synthetic root", "Branch", "Family", "Terminal"],
        ["Synthetic root", "Other terminal", "", ""],
    ])
    spec = {
        "schema_version": 1, "company_id": "synthetic-new-company", "reporting_currency": "USD",
        "csv": {"delimiter": ";"},
        "sources": [{
            "name": "purchases", "path": "purchases.dat", "record_id_prefix": "X:",
            "amount_basis": "as_provided", "number_format": {"decimal": ",", "thousands": "."},
            "constants": {"currency": "EUR"}, "date_formats": {"invoice_date": ["%d.%m.%Y"]},
            "fields": {"source_record_id": "doc", "amount": "money", "description": "memo",
                       "supplier_id": "vendor", "invoice_date": "when"},
        }],
        "taxonomy": {"path": "tree.csv", "csv": {"delimiter": ","},
                     "fields": {"l1": "top", "l2": "middle", "l3": "family", "l4": "leaf"}},
        # Deliberately absent on disk: normal inference must not open it.
        "labels": {"path": "missing-labels.csv", "fields": {"record_id": "id", "l1": "gold"},
                   "record_id_prefix": "X:", "csv": {"delimiter": ","}},
    }
    return tmp_path, spec, columns, rows


def configured(company, *, spec=None, extension="yaml", data_dir=None):
    root, original, _, _ = company
    path = root / f"company.{extension}"
    value = spec if spec is not None else original
    path.write_text(json.dumps(value) if extension == "json" else yaml.safe_dump(value), encoding="utf-8")
    return load_config(path, data_dir)


@pytest.mark.parametrize("extension", ["yaml", "json"])
def test_config_only_new_layout_is_lossless_and_label_free(company, extension):
    root, _, columns, rows = company
    result = ingest_company(configured(company, extension=extension))
    assert result.labels is None
    assert result.records["record_id"].tolist() == ["X:0001", "X:0002", "X:0003"]
    assert result.records["source_row"].tolist() == [1, 2, 3]
    assert result.records["amount"].tolist() == [r[1] for r in rows]
    assert result.records["description"].tolist() == [r[2] for r in rows]
    assert result.records["invoice_date"].tolist() == [r[4] for r in rows]
    assert result.records["supplier_id"].tolist() == ["0007", "0007", "0008"]
    assert result.records["currency"].tolist() == ["EUR"] * 3
    assert result.records["raw"].tolist() == [dict(zip(columns, row)) for row in rows]
    assert not result.records.isna().any().any()
    assert not {"supplier_key", "item_key", "l1", "include"} & set(result.records.columns)
    assert tuple(map(len, result.taxonomy)) == (4, 2)
    assert result.summary()["record_count"] == 3


def test_labels_are_separate_and_do_not_change_records(company):
    root, _, _, _ = company
    cfg = configured(company)
    without = ingest_company(cfg)
    write_csv(root / "missing-labels.csv", ["id", "gold"], [["0001", "Synthetic root"]])
    with_labels = ingest_company(cfg, load_labels=True)
    pd.testing.assert_frame_equal(without.records, with_labels.records)
    assert with_labels.labels["record_id"].tolist() == ["X:0001"]


@pytest.mark.parametrize("label_ids", [["unmatched"], ["0001", "0001"], [""]])
def test_bad_label_join_fails(company, label_ids):
    root, _, _, _ = company
    write_csv(root / "missing-labels.csv", ["id", "gold"], [[key, "Synthetic root"] for key in label_ids])
    with pytest.raises(ConfigError, match="labels: blank, duplicate or unmatched"):
        ingest_company(configured(company), load_labels=True)


def test_labels_missing_only_fails_when_requested(company):
    cfg = configured(company)
    ingest_company(cfg)
    with pytest.raises(ConfigError, match="labels: cannot read"):
        ingest_company(cfg, load_labels=True)


@pytest.mark.parametrize("identifier", ["0001", "", "   "])
def test_duplicate_or_blank_source_ids_fail(company, identifier):
    root, _, columns, rows = company
    rows[1][0] = identifier
    write_csv(root / "purchases.dat", columns, rows, ";")
    with pytest.raises(ConfigError, match="record ID"):
        ingest_company(configured(company))


@pytest.mark.parametrize("body", [
    "doc;money;memo;vendor;when;extra\na;1;x;v;;\nb;2\n",
    "doc;money;memo;vendor;when;extra\na;1;x;v;;;overflow\n",
    "doc;money;memo;vendor;when;extra\na;1;\"unterminated",
    "doc;doc;memo\na;1;x\n",
    "other;money\na;1\n",
])
def test_invalid_csv_contract_fails(company, body):
    root, _, _, _ = company
    (root / "purchases.dat").write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        ingest_company(configured(company))


@pytest.mark.parametrize("change", [
    lambda s: s.update(unknown=True),
    lambda s: s.update(schema_version=True),
    lambda s: s.update(sources=[]),
    lambda s: s["sources"][0]["fields"].update(typo="memo"),
    lambda s: s["sources"][0]["fields"].pop("amount"),
    lambda s: s["sources"][0]["constants"].update(amount="0"),
    lambda s: s["sources"][0]["constants"].update(description="overwrites input"),
    lambda s: s["sources"][0].update(date_formats={}),
    lambda s: s["sources"][0].update(amount_basis="guess"),
    lambda s: s["sources"][0].update(vat_default="15"),
    lambda s: s["sources"][0].update(vat_default="NaN"),
    lambda s: s["sources"][0].update(vat_default="invalid"),
    lambda s: s["sources"][0]["number_format"].update(thousands=","),
    lambda s: s.update(csv={"delimiter": "||"}),
    lambda s: s["taxonomy"]["fields"].pop("l2"),
    lambda s: s["taxonomy"].update(record_id_prefix="unsupported"),
    lambda s: s["sources"].append(copy.deepcopy(s["sources"][0])),
])
def test_invalid_config_fails_before_ingestion(company, change):
    spec = copy.deepcopy(company[1])
    change(spec)
    with pytest.raises(ConfigError):
        configured(company, spec=spec)


def test_duplicate_yaml_keys_and_unsafe_tags_fail(company):
    root = company[0]
    path = root / "bad.yaml"
    for value in ["company_id: one\ncompany_id: two\n", "!!python/object:builtins.object {}"]:
        path.write_text(value, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)


def test_same_file_or_global_id_collision_across_sources_fails(company):
    root, original, _, _ = company
    for use_same_path in [True, False]:
        spec = copy.deepcopy(original)
        other = copy.deepcopy(spec["sources"][0])
        other["name"] = "other"
        if not use_same_path:
            other["path"] = "other.dat"
            (root / "other.dat").write_bytes((root / "purchases.dat").read_bytes())
        spec["sources"].append(other)
        with pytest.raises(ConfigError, match="same input file|duplicate output record ID"):
            ingest_company(configured(company, spec=spec))


@pytest.mark.parametrize("rows", [
    [], [["Root", "", "Gap", ""]], [["Root", "B", "C", "D"]] * 2,
])
def test_invalid_taxonomy_fails(company, rows):
    root = company[0]
    write_csv(root / "tree.csv", ["top", "middle", "family", "leaf"], rows)
    with pytest.raises(ConfigError, match="taxonomy"):
        ingest_company(configured(company))


def test_fx_is_separate_and_duplicate_month_key_fails(company):
    root, original, _, _ = company
    spec = copy.deepcopy(original)
    spec["fx"] = {"path": "rates.csv", "csv": {"delimiter": ","},
                  "fields": {"currency": "ccy", "month": "period", "units_per_usd": "rate"}}
    write_csv(root / "rates.csv", ["ccy", "period", "rate"], [["EUR", "2024-12", "0.95"]])
    result = ingest_company(configured(company, spec=spec))
    assert result.fx.iloc[0]["units_per_usd"] == "0.95"
    assert result.records.iloc[0]["amount"] == "1.234,50"
    write_csv(root / "rates.csv", ["ccy", "period", "rate"], [["EUR", "2024-12", "0.95"]] * 2)
    with pytest.raises(ConfigError, match="fx: blank or duplicate"):
        ingest_company(configured(company, spec=spec))


def test_data_root_override_and_missing_source_error(company):
    root = company[0]
    cfg = configured(company, data_dir=root / "absent")
    with pytest.raises(ConfigError, match="purchases: cannot read"):
        ingest_company(cfg)


def test_same_config_handles_new_records_at_another_data_root(company):
    root, _, columns, rows = company
    configured(company)
    next_root = root / "fresh-data"
    next_root.mkdir()
    fresh_rows = [rows[0].copy()]
    fresh_rows[0][0] = "0099"
    write_csv(next_root / "purchases.dat", columns, fresh_rows, ";")
    (next_root / "tree.csv").write_bytes((root / "tree.csv").read_bytes())
    result = ingest_company(load_config(root / "company.yaml", next_root))
    assert result.records["record_id"].tolist() == ["X:0099"]
    assert result.labels is None


def test_two_sources_with_distinct_prefixes_preserve_repeated_raw_ids(company):
    root, original, _, _ = company
    spec = copy.deepcopy(original)
    other = copy.deepcopy(spec["sources"][0])
    other.update(name="other", path="other.dat", record_id_prefix="Y:")
    (root / "other.dat").write_bytes((root / "purchases.dat").read_bytes())
    spec["sources"].append(other)
    result = ingest_company(configured(company, spec=spec))
    assert len(result.records) == 6
    assert result.records.record_id.is_unique
    assert result.summary()["sources"] == {"purchases": 3, "other": 3}


def test_empty_source_is_not_confused_with_missing_file(company):
    root, _, columns, _ = company
    write_csv(root / "purchases.dat", columns, [], ";")
    result = ingest_company(configured(company))
    assert result.summary()["record_count"] == 0
    assert result.summary()["sources"] == {"purchases": 0}


def test_tab_delimited_source_is_configurable(company):
    root, original, columns, rows = company
    spec = copy.deepcopy(original)
    spec["csv"]["delimiter"] = "\t"
    write_csv(root / "purchases.dat", columns, rows, "\t")
    result = ingest_company(configured(company, spec=spec))
    assert result.records.raw.tolist() == [dict(zip(columns, row)) for row in rows]


def test_cli_summary_and_failure_exit_do_not_dump_records(company):
    root = company[0]
    configured(company)
    command = [sys.executable, "-m", "cantill", "ingest", "--config", str(root / "company.yaml")]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["record_count"] == 3
    assert "élémént" not in result.stdout
    failed = subprocess.run([*command, "--with-labels"], text=True, capture_output=True)
    assert failed.returncode == 2
    assert "Traceback" not in failed.stderr
