"""Evaluate frozen eligibility rules on the reserved B development/holdout split.

Private manifests contain IDs; public reports should contain aggregates only.
The split is label-independent. Descriptive full-label profiling predates it.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from collections import Counter
from pathlib import Path

from cantill.config import load_config
from cantill.eligibility import assess_eligibility
from cantill.evaluation import ELIGIBILITY_PROTOCOL, eligibility_group, eligibility_partition
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    parser.add_argument("--partition", choices=["development", "holdout", "all"], default="development")
    parser.add_argument("--config", type=Path, help="Optional config, including a saved baseline replay config")
    parser.add_argument("--report-tag", choices=["baseline", "post_review"], default="post_review")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    company = ingest_company(load_config(args.config or repo / "configs/company_B.yaml", args.kit_dir), load_labels=True)
    predicted = assess_eligibility(normalize_company(company)).records.set_index("record_id")
    rows = company.records.set_index("record_id")
    manifest = [{"record_id": row["record_id"], "group_sha256": eligibility_group(rows.loc[row["record_id"]]),
                 "split": eligibility_partition(eligibility_group(rows.loc[row["record_id"]]))}
                for row in company.labels.to_dict("records")]
    destination = repo / "private/eligibility"
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "split_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert previous["protocol"] == ELIGIBILITY_PROTOCOL and previous["records"] == manifest, "Frozen split changed"
    else:
        manifest_path.write_text(json.dumps({"protocol": ELIGIBILITY_PROTOCOL, "records": manifest}, indent=2), encoding="utf-8")
    splits = {row["record_id"]: row["split"] for row in manifest}
    signature = {
        "rules": [asdict(rule) for rule in company.config.eligibility_rules],
        "status_policies": [{"source": s.name, "policy": s.status_policy,
                             "approved": s.approved_statuses, "cancelled": s.cancelled_statuses}
                            for s in company.config.sources],
    }
    rule_sha256 = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    reports, failures = {}, []
    for partition in ("development", "holdout"):
        if args.partition not in (partition, "all"):
            continue
        counts, rules = Counter(), Counter()
        for label in company.labels.to_dict("records"):
            key = label["record_id"]
            if splits[key] != partition:
                continue
            actual = predicted.loc[key]
            expected = label["include"] == "1"
            guess = bool(actual["eligible"])
            counts["records"] += 1
            counts["included_labels" if expected else "excluded_labels"] += 1
            counts["true_positive_exclusion" if not expected and not guess else
                   "false_positive_exclusion" if expected and not guess else
                   "false_negative_exclusion" if not expected and guess else "true_negative_exclusion"] += 1
            correct = guess == expected and (expected or actual["eligibility_reason"] == label["exclusion_reason"])
            counts["exact_decision_correct"] += correct
            if not correct:
                failures.append({"record_id": key, "partition": partition,
                                 "expected_include": expected, "predicted_include": guess})
            if not expected:
                rules.update(actual["eligibility_evidence"])
        tp, fp, fn = counts["true_positive_exclusion"], counts["false_positive_exclusion"], counts["false_negative_exclusion"]
        reports[partition] = {**dict(counts), "false_positive_exclusion": fp, "false_negative_exclusion": fn,
                              "decision_accuracy": counts["exact_decision_correct"] / counts["records"],
                              "exclusion_precision": tp / (tp + fp) if tp + fp else None,
                              "exclusion_recall": tp / (tp + fn) if tp + fn else None,
                              "matched_evidence_on_excluded": dict(rules)}
    output = {"protocol": ELIGIBILITY_PROTOCOL, "rule_sha256": rule_sha256, "partitions": reports,
              "evaluation_status": "initial reserved evaluation" if args.report_tag == "baseline" else "development recheck after reviewing initial reserved errors",
              "limitation": "Full-label descriptive profiling predates this split; seeds are selective/noisy and are not the blind test"}
    report_path = destination / (args.report_tag + "_" + args.partition + "_evaluation.json")
    if args.report_tag == "baseline" and report_path.exists():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        assert previous["rule_sha256"] == rule_sha256 and previous["partitions"] == reports, "Baseline results changed"
    report_path.write_text(json.dumps({**output, "failures": failures}, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
