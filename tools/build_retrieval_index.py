"""Build a private labelled index, excluding reserved and pilot-related groups."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.ingest import ingest_company
from cantill.pilot import partition_records, score_predictions
from cantill.pipeline import run_company
from cantill.retrieval import RetrievalIndex, build_payload, digest
from pilot_classification import REPO, deny_label_read, fingerprint


def build(config_path, data_dir, freezes, output):
    output = Path(output).resolve()
    if not output.is_relative_to((REPO / "private").resolve()):
        raise ConfigError("Retrieval artifacts must stay under this repository's ignored private directory")
    if output.exists() or output.with_suffix(".report.json").exists():
        raise ConfigError("Retrieval destination already exists; choose a new path")
    config = load_config(config_path, data_dir)
    if config.labels is None:
        raise ConfigError("Labelled retrieval requires configured development labels; use zero-label mode otherwise")
    before = fingerprint(config, config_path)
    reference, evaluation_ids, samples = None, set(), {}
    for path in freezes:
        frozen = json.loads(Path(path).read_text(encoding="utf-8"))
        payload = frozen["payload"]
        if digest(payload) != frozen["integrity"] or payload["company_id"] != config.company_id:
            raise ConfigError("Invalid reference freeze integrity/company")
        # Historical application code may differ. Source/config fingerprints must match,
        # and all split assignments are recomputed from the current label-free pipeline.
        if any(payload["fingerprint"][key] != before[key] for key in ("inputs", "config")):
            raise ConfigError("Reference freeze inputs/config changed")
        if reference is not None and any(payload[key] != reference[key] for key in ("partitions", "taxonomy")):
            raise ConfigError("Reference freezes must use the same company split/tree")
        reference = payload
        for sample in payload["samples"]:
            if sample["partition"] != "development":
                raise ConfigError("Development pilot contains a reserved record")
            evaluation_ids.add(sample["record_id"])
            samples[sample["record_id"]] = sample
    if reference is None:
        raise ConfigError("At least one evaluation reference freeze is required")
    with patch("cantill.ingest.read_table", deny_label_read):
        local = run_company(replace(config, labels=None), classification=ClassificationConfig(mode="local"))
    records = local.records
    partitions = partition_records(records.to_dict("records"))
    if partitions != reference["partitions"]:
        raise ConfigError("Current related-record split differs from the reference; do not reuse evaluation scores")
    taxonomy = local.resolved.matched.eligible.normalized.ingested.taxonomy
    if sorted(map(tuple, taxonomy)) != sorted(map(tuple, reference["taxonomy"])):
        raise ConfigError("Current taxonomy differs from the evaluation reference")
    # Labels open only after deterministic grouping and evaluation exclusions are fixed.
    labels = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
    payload = build_payload(records, labels, taxonomy, config.company_id, partitions, evaluation_ids)
    payload["build_fingerprint"] = before
    index = RetrievalIndex(payload, company_id=config.company_id, taxonomy=taxonomy)
    by_id = records.set_index("record_id").to_dict("index")
    selected, predictions, hits = list(samples.values()), [], 0
    for sample in selected:
        row = by_id[sample["record_id"]]
        result = index.predict(row)
        hits += result is not None
        predictions.append((result[0], result[1]) if result is not None
                           else (tuple(sample["local_path"]), sample["local_confidence"]))
    report = {"status": "built_and_evaluated_offline", "company_id": config.company_id,
              "training_rows": index.training_rows, "examples": len(index.examples),
              "excluded_groups": len(payload["excluded_groups"]), "evaluation_rows": len(selected),
              "retrieval_coverage_rows": hits, "api_requests": 0,
              "local_metrics": score_predictions(selected, [(tuple(s["local_path"]), s["local_confidence"]) for s in selected], labels),
              "retrieval_with_lexical_fallback_metrics": score_predictions(selected, predictions, labels),
              "index_integrity": index.fingerprint,
              "limits": "Development diagnostics only; all reserved and pilot-related groups excluded from training. Retrieval confidence is uncalibrated. No retrieval-assisted LLM measurement yet."}
    if fingerprint(config, config_path) != before:
        raise ConfigError("Inputs/application code changed during index preparation")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"integrity": digest(payload), "payload": payload}, stream, ensure_ascii=False, indent=2)
    with output.with_suffix(".report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--reference-freeze", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(args.config, args.data_dir, args.reference_freeze, args.output)
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
