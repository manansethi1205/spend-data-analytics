"""Read-only A/B matching invariants and allocation ledger audit, without labels.

This verifies conservation and traceability, not ground-truth matching accuracy.
Detailed links and review samples are confidential and remain under private/.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import pandas as pd

from cantill.config import load_config
from cantill.eligibility import assess_eligibility
from cantill.ingest import ingest_company
from cantill.matching import count_purchases
from cantill.normalize import normalize_company


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.kit_dir.glob("company_*/*.csv")}
    summaries, reports, samples = [], {}, []
    for name in ("A", "B"):
        config = load_config(repo / f"configs/company_{name}.yaml", args.kit_dir)
        ingested = ingest_company(config)
        assert ingested.labels is None
        eligible = assess_eligibility(normalize_company(ingested))
        before = eligible.records.copy(deep=True)
        matched = count_purchases(eligible)
        pd.testing.assert_frame_equal(eligible.records, before)
        pd.testing.assert_frame_equal(matched.records[before.columns], before)
        assert matched.records.record_id.tolist() == before.record_id.tolist()
        rows = matched.records.set_index("record_id").to_dict("index")
        eligible_total = retained_total = duplicate_total = Fraction(0)
        links, unresolved = [], []
        method_samples = defaultdict(list)
        for key, row in rows.items():
            if not row["eligible"]:
                assert row["include"] == 0 and row["exclusion_reason"] == row["eligibility_reason"]
            if row["include"]:
                assert row["spend_value"] == row["reporting_amount_value"]
                assert row["exclusion_reason"] == "" and not row["duplicate_of"]
                if row["spend_value"] is None:
                    unresolved.append(key)
                else:
                    retained_total += Fraction(row["spend_value"])
            else:
                assert row["spend_value"] == 0
            if row["eligible"] and row["reporting_amount_value"] is not None:
                eligible_total += Fraction(row["reporting_amount_value"])
            if row["exclusion_reason"] == "DUPLICATE":
                assert row["duplicate_of"] and row["eligible"]
                assert all(target in rows and rows[target]["include"] == 1 for target in row["duplicate_of"])
                duplicate_total += Fraction(row["reporting_amount_value"])
                links.append({"record_id": key, **{c: row[c] for c in (
                    "duplicate_of", "match_method", "match_score", "match_evidence", "matching_flags")}})
                method_samples[row["match_method"]].append(key)
        assert eligible_total == retained_total + duplicate_total
        q_claims, amount_claims = defaultdict(Fraction), defaultdict(Fraction)
        for allocation in matched.allocations:
            if allocation["method"] == "repeat_export":
                continue
            pair = tuple(allocation["source_pair"])
            for key in allocation["preferred_ids"]:
                row = rows[key]
                assert row["source"] == pair[0] and row["include"] == 1
                quantity = allocation.get("quantity_claims", {}).get(key, abs(row["quantity_value"]))
                amount = allocation.get("amount_claims", {}).get(key, abs(row["reporting_amount_value"]))
                q_claims[(pair, key)] += Fraction(quantity)
                amount_claims[(pair, key)] += Fraction(amount)
            assert all(rows[key]["source"] == pair[1] and rows[key]["exclusion_reason"] == "DUPLICATE" for key in allocation["secondary_ids"])
        for ledger_key, quantity in q_claims.items():
            row = rows[ledger_key[1]]
            assert quantity <= Fraction(abs(row["quantity_value"]))
            budget = Fraction(abs(row["reporting_amount_value"]))
            assert amount_claims[ledger_key] <= budget + max(budget, Fraction(1)) / 10**50
        for method, keys in method_samples.items():
            selected = list(dict.fromkeys(keys[:2] + sorted(keys, key=lambda k: (rows[k]["match_score"], k))[:2]))
            fields = ("source", "invoice_number", "po_number", "po_line", "supplier_name", "description",
                      "quantity_value", "reporting_amount_value", "posting_date", "invoice_date")
            for key in selected:
                samples.append({"company_id": name, "method": method, "secondary_id": key,
                                "secondary": {f: rows[key][f] for f in fields},
                                "preferred": [{"record_id": p, **{f: rows[p][f] for f in fields}} for p in rows[key]["duplicate_of"]],
                                "evidence": rows[key]["match_evidence"]})
        summaries.append({**matched.summary(), "source_rows_preserved": True,
                          "amount_reconciliation": True, "allocation_budgets_verified": True})
        reports[name] = {"allocations": matched.allocations, "links": links, "unresolved_included_ids": unresolved}
        print(json.dumps(summaries[-1]))
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    destination = repo / "private/matching"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "verification.json").write_text(json.dumps({"source_hashes_unchanged": True, "companies": summaries,
                                                              "details": reports}, indent=2, default=str), encoding="utf-8")
    (destination / "review_samples.json").write_text(json.dumps(samples, indent=2, default=str), encoding="utf-8")
    print("Verified all source rows/values, prior exclusions, duplicate roots, exact reconciliation and quantity/amount budgets; sources unchanged.")


if __name__ == "__main__":
    main()
