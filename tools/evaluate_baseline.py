"""Reproduce stages 9/10 evaluation; labels are opened only AFTER inference."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pandas as pd

from cantill.config import ConfigError, load_config
from cantill.ingest import ingest_company, read_table
from cantill.metrics import classification_metrics, grouping_metrics
from cantill.output import validate_output
from cantill.pipeline import run_company, write_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    destination = repo / "private/baseline"
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.kit_dir.glob("company_*/*.csv")}
    code_hashes = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (repo / "src/cantill").glob("*.py")}
    results = {}
    for name in ("A", "B"):
        config = load_config(repo / f"configs/company_{name}.yaml", args.kit_dir)
        accessed = []
        def audited_read(base, table, role):
            if role == "labels":
                raise AssertionError("Inference attempted to open labels")
            accessed.append(role)
            return read_table(base, table, role)
        start = perf_counter()
        with patch("cantill.ingest.read_table", audited_read):
            prediction = run_company(replace(config, labels=None))
        elapsed = perf_counter() - start
        records = prediction.records
        ingested = prediction.resolved.matched.eligible.normalized.ingested
        assert ingested.labels is None
        pd.testing.assert_frame_equal(records[ingested.records.columns], ingested.records)
        assert not records.supplier_key.eq("").any() and not records.item_key.eq("").any()
        paths = {tuple(path) for path in ingested.taxonomy}
        for row in records.loc[records.include == 1].to_dict("records"):
            assert tuple(row[f"l{i}"] for i in range(1, 5) if row[f"l{i}"]) in paths
        # Only now open evaluation labels. They never train a model or map keys.
        labels = ingest_company(config, load_labels=True).labels.set_index("record_id")
        indexed = records.set_index("record_id")
        entity_metrics = {}
        for field in ("supplier_key", "item_key"):
            if field in labels:
                entity_metrics[field] = grouping_metrics(indexed.loc[labels.index, field], labels[field])
                entity_metrics[field]["all_reference_rows"] = len(labels)
                entity_metrics[field]["label_coverage"] = labels[field].str.strip().ne("").mean()
        scored, skipped = [], 0
        for rid, label in labels.iterrows():
            if "include" in label and label["include"] != "1":
                continue
            row = indexed.loc[rid]
            if not row["include"]:
                skipped += 1
                continue
            scored.append({"predicted": tuple(row[f"l{i}"] for i in range(1, 5) if row[f"l{i}"]),
                           "golden": tuple(label[f"l{i}"] for i in range(1, 5) if f"l{i}" in label and label[f"l{i}"]),
                           "spend": row["spend_value"], "confidence": row["confidence"]})
        output = destination / f"baseline_{name}.csv"
        export_start = perf_counter()
        if prediction.summary()["included_unresolved_financial_rows"]:
            try:
                write_output(prediction, output)
            except ConfigError:
                export = "blocked_unresolved_financial_values"
            else:
                raise AssertionError("Unresolved output unexpectedly written")
        else:
            write_output(prediction, output)
            assert validate_output(output, records.record_id, ingested.taxonomy).valid
            export = "validated_private_output"
        results[name] = {"summary": prediction.summary(), "inference_seconds": elapsed,
                         "inference_read_roles": accessed, "labels_absent_during_inference": True,
                         "source_columns_preserved": True, "entity_metrics": entity_metrics,
                         "export_and_independent_validation_seconds": perf_counter() - export_start,
                         "classification": classification_metrics(scored),
                         "labelled_included_rows_excluded_by_pipeline": skipped, "export": export}
    assert hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}
    assert code_hashes == {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in code_hashes}
    report = {"protocol": "cantill-taxonomy-lexical-v1", "source_hashes_unchanged": True,
              "inference_code_hashes": code_hashes,
              "limits": "Development baseline: no tuning on these scores; prior aggregate profiling and eligibility review disclosed. Not blind-test performance.",
              "results": results}
    (destination / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
