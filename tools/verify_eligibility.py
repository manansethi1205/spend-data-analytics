"""Read-only A/B eligibility integration checks; private IDs stay local."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from cantill.config import load_config
from cantill.eligibility import assess_eligibility
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.kit_dir.glob("company_*/*.csv")}
    summaries, unresolved = [], []
    for name in ("A", "B"):
        company = ingest_company(load_config(repo / f"configs/company_{name}.yaml", args.kit_dir))
        assert company.labels is None
        normalized = normalize_company(company)
        before = normalized.records.copy(deep=True)
        assessed = assess_eligibility(normalized)
        pd.testing.assert_frame_equal(normalized.records, before)
        pd.testing.assert_frame_equal(assessed.records[before.columns], before)
        assert assessed.records.record_id.tolist() == company.records.record_id.tolist()
        for row in assessed.records.to_dict("records"):
            if row["eligible"]:
                assert row["eligibility_reason"] == ""
                assert row["eligible_amount_value"] == row["reporting_amount_value"]
                if not row["financial_ready"]:
                    assert "ELIGIBLE_AMOUNT_UNRESOLVED" in row["eligibility_flags"]
                    unresolved.append({"record_id": row["record_id"], "quality_flags": row["quality_flags"],
                                       "eligibility_flags": row["eligibility_flags"]})
            else:
                assert row["eligibility_reason"] in {"CANCELLED", "NOT_APPROVED", "NON_PROCUREMENT"}
                assert row["eligible_amount_value"] == 0
            if name == "A" and row["source"] == "tool":
                status = row["raw"]["status"].strip().lower()
                if status in {"cancelled", "canceled"}:
                    assert row["eligibility_reason"] == "CANCELLED"
                elif status not in {"approved", "paid"}:
                    assert row["eligibility_reason"] == "NOT_APPROVED"
        summary = {**assessed.summary(), "source_rows_preserved": True, "labels_loaded": False}
        summaries.append(summary)
        print(json.dumps(summary))
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    destination = repo / "private/eligibility"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "integration_verification.json").write_text(json.dumps({
        "source_hashes_unchanged": True, "companies": summaries, "unresolved_candidates": unresolved,
    }, indent=2), encoding="utf-8")
    print("Verified source preservation, reason/amount invariants and explicit tool statuses; source hashes unchanged.")


if __name__ == "__main__":
    main()
