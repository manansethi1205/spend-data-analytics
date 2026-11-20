"""Train a private company crosswalk and measure deterministic half-label coverage."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import random

from cantill.config import load_config
from cantill.eligibility import assess_eligibility
from cantill.entities import opaque_key, resolve_entities
from cantill.ingest import ingest_company
from cantill.matching import count_purchases, supplier_key
from cantill.metrics import grouping_metrics
from cantill.normalize import normalize_company
from cantill.supplier_crosswalk import SupplierCrosswalk


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = args.report_dir.resolve()
    if not destination.is_relative_to((ROOT / "private").resolve()) or destination.exists():
        parser.error("Choose a new directory under ignored private/")
    config = load_config(args.config, args.data_dir)
    ingested = ingest_company(config, load_labels=True)
    if "supplier_key" not in ingested.labels:
        parser.error("Configured labels have no supplier_key")
    labels = ingested.labels[ingested.labels.supplier_key.str.strip().ne("")].copy()
    ids = sorted(labels.record_id)
    random.Random(2026).shuffle(ids)
    if len(ids) < 4:
        parser.error("At least four supplier-labelled rows are required")
    training_ids = set(ids[:len(ids) // 2])
    training = labels[labels.record_id.isin(training_ids)]
    test = labels[~labels.record_id.isin(training_ids)]
    half = SupplierCrosswalk.fit(config.company_id, ingested.records, training)
    # Inference receives no labels; only the explicitly trained half-label artifact.
    ingested.labels = None
    ingested.config = replace(config, labels=None)
    matched = count_purchases(assess_eligibility(normalize_company(ingested)))
    baseline = resolve_entities(matched).records.set_index("record_id")
    assisted = resolve_entities(matched, supplier_crosswalk=half).records.set_index("record_id")
    heldout = test.set_index("record_id")
    source = ingested.records.set_index("record_id").loc[heldout.index]
    hits = source.supplier_name.map(supplier_key).isin(half.names)
    hit_predictions = source.supplier_name.map(supplier_key).map(half.names)
    expected = heldout.supplier_key.map(lambda key: opaque_key(
        "supervised_supplier", config.company_id, key.strip()))
    coverage = {"heldout_rows": len(heldout), "matched_rows": int(hits.sum()),
                "row_coverage": float(hits.mean()),
                "matched_rows_correct": int((hit_predictions[hits] == expected[hits]).sum()),
                "matched_row_accuracy": float((hit_predictions[hits] == expected[hits]).mean()) if hits.any() else None,
                "heldout_distinct_normalized_names": int(source.supplier_name.map(supplier_key).nunique()),
                "matched_distinct_normalized_names": int(source.loc[hits].supplier_name.map(supplier_key).nunique())}
    # Freeze half-label predictions before fitting a production artifact on all labels.
    report = {"protocol": "cantill-supplier-crosswalk-evaluation-v1", "company_id": config.company_id,
              "api_requests": 0, "split": "seed-2026 shuffled sorted record IDs, floor(n/2) training",
              "training_rows": len(training), "training_names": len(half.names),
              "training_ambiguous_names": len(half.ambiguous_names), "coverage": coverage,
              "baseline_holdout": grouping_metrics(baseline.loc[heldout.index, "supplier_key"], heldout.supplier_key),
              "crosswalk_holdout": grouping_metrics(assisted.loc[heldout.index, "supplier_key"], heldout.supplier_key),
              "limitations": ["Row-disjoint recurrence test, not unseen-name or chronological generalization",
                              "Underlying label-free resolver sees all unlabelled source rows",
                              "Future name reuse and identity stability are not guaranteed",
                              "Full-label training fit is not a held-out accuracy measurement"]}
    full = SupplierCrosswalk.fit(config.company_id, ingested.records, labels)
    destination.mkdir(parents=True)
    full.save(destination / "supplier_crosswalk.json")
    half.save(destination / "half_label_crosswalk.json")
    assisted.loc[heldout.index, ["supplier_key", "item_key"]].to_json(destination / "holdout_predictions.json", orient="index")
    report["production"] = {"training_rows": len(labels), "names": len(full.names),
                            "ambiguous_names": len(full.ambiguous_names),
                            "artifact_sha256": sha256((destination / "supplier_crosswalk.json").read_bytes()).hexdigest()}
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
