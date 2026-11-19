"""Independent A/B arithmetic/date verification; confidential results stay local.

This kit-specific audit uses exact rational arithmetic as an oracle. It is not
the configurable production normalizer and does not use golden labels.
"""

import argparse
import csv
import hashlib
import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import pandas as pd

from cantill.config import load_config
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company


def oracle_date(raw):
    if not raw:
        return None
    if "/" in raw:
        day, month, year = map(int, raw.split("/"))
        return date(year, month, day)
    if len(raw) == 10 and raw[4] == "-":
        return date.fromisoformat(raw)
    day, month, year = raw.split("-")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return date(2000 + int(year), months.index(month) + 1, int(day))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.kit_dir.glob("company_*/*.csv")}
    with (args.kit_dir / "company_B/fx_rates_usd.csv").open(encoding="utf-8-sig", newline="") as stream:
        fx = {(r["currency"], r["month"]): Fraction(r["units_per_usd"]) for r in csv.DictReader(stream)}
    summaries, exceptions = [], []
    for company_id in ("A", "B"):
        cfg = load_config(repo / f"configs/company_{company_id}.yaml", args.kit_dir)
        company = ingest_company(cfg)
        before = company.records.copy(deep=True)
        normalized = normalize_company(company)
        pd.testing.assert_frame_equal(company.records, before)
        pd.testing.assert_frame_equal(normalized.records[before.columns], before)
        checked = 0
        for source in cfg.sources:
            with (args.kit_dir / source.table.path).open(encoding="utf-8-sig", newline="") as stream:
                originals = list(csv.DictReader(stream))
            actual = normalized.records.loc[normalized.records.source == source.name].to_dict("records")
            assert len(originals) == len(actual)
            for raw, row in zip(originals, actual):
                assert row["raw"] == raw
                assert row["record_id"] == source.table.record_id_prefix + raw[source.table.fields["source_record_id"]]
                for name, column in source.table.fields.items():
                    assert row[name] == raw[column]
                for name in source.date_formats:
                    assert row[name + "_value"] == oracle_date(raw[source.table.fields[name]])
                for name in ("quantity", "unit_cost"):
                    value = row[name].strip()
                    assert row[name + "_value"] == (Fraction(value) if value else None)
                raw_amount = row["amount"].replace(",", "")
                expected = Fraction(raw_amount) if raw_amount else None
                if company_id == "A" and source.amount_basis == "gross" and expected is not None:
                    # Observed nonzero VAT representations all mean 15%; blank rule is explicit.
                    vat = Fraction(0) if row["vat_rate"] == "0" else Fraction(15, 100)
                    expected /= 1 + vat
                if company_id == "B" and row["currency"] != "USD":
                    rate = Fraction(row["currency_rate"]) if row["currency_rate"] else fx.get((row["currency"], row["invoice_date"][:7]))
                    expected = expected / rate if expected is not None and rate is not None else None
                converted = row["reporting_amount_value"]
                if expected is None:
                    assert converted is None and not row["financial_ready"]
                    exceptions.append({"record_id": row["record_id"], "quality_flags": row["quality_flags"]})
                else:
                    assert converted is not None and row["financial_ready"]
                    error = abs(Fraction(converted) - expected)
                    assert error <= max(abs(expected), Fraction(1)) / 10**48
                    checked += 1
        summary = {**normalized.summary(), "rational_arithmetic_checks": checked,
                   "all_original_cells_preserved": True, "independent_date_checks": True}
        summaries.append(summary)
        print(json.dumps(summary))
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    destination = repo / "private/normalization"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "verification.json").write_text(json.dumps({
        "source_hashes_unchanged": True, "companies": summaries, "unresolved_records": exceptions,
    }, indent=2), encoding="utf-8")
    print("Verified every A/B record against independent rational/date calculations; source hashes unchanged.")


if __name__ == "__main__":
    main()
