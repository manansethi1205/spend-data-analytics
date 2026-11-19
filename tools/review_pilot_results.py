"""Verify saved pilot predictions and aggregate results without making API calls."""

import argparse
from collections import Counter
from decimal import Decimal
import json
import math
from pathlib import Path

from cantill.config import ConfigError, load_config
from cantill.ingest import ingest_company
from cantill.pilot import cost_estimate, digest, score_predictions
from pilot_classification import REPO, load_frozen


def verify_predictions(samples, details, taxonomy):
    expected = [sample["record_id"] for sample in samples]
    if [row["record_id"] for row in details] != expected or len(set(expected)) != len(expected):
        raise ConfigError("Prediction IDs/order do not match the frozen sample")
    paths = {tuple(path) for path in taxonomy}
    for row in details:
        confidence = row["confidence"]
        if (tuple(row["path"]) not in paths or type(confidence) not in (int, float)
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ConfigError("Prediction has an invalid taxonomy path/confidence")
        if row["method"] != "openai" or row["flag"]:
            raise ConfigError("Complete pilot contains a fallback or flagged prediction")
    return [(tuple(row["path"]), row["confidence"]) for row in details]


def review(data_dir, root):
    root = Path(root).resolve()
    if not root.is_relative_to((REPO / "private").resolve()):
        raise ConfigError("Review artifacts must remain under private")
    summary, total_cost, requests = {}, Decimal(0), 0
    for cohort in ("A", "B", "B_challenge"):
        config_path = REPO / "configs" / ("company_A.yaml" if cohort == "A" else "company_B.yaml")
        config = load_config(config_path, data_dir)
        payload, integrity = load_frozen(config, config_path, root / cohort)
        measured = []
        for path in (root / cohort / "runs").glob("*/report.json"):
            report = json.loads(path.read_text(encoding="utf-8"))
            if report["status"] == "measured" and report["freeze_integrity"] == integrity:
                measured.append((path, report))
        if len(measured) != 1:
            raise ConfigError(f"Expected exactly one matching measured run for {cohort}; found {len(measured)}")
        path, report = measured[0]
        labels = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
        samples = payload["samples"]
        local = score_predictions(samples, [(tuple(s["local_path"]), s["local_confidence"]) for s in samples], labels)
        if report["local"] != local or not report["inputs_and_code_unchanged"]:
            raise ConfigError("Local metrics/fingerprint verification failed")
        models = {}
        for model, result in report["models"].items():
            details = json.loads((path.parent / (digest(model)[:16] + "_predictions.json")).read_text(encoding="utf-8"))
            predictions = verify_predictions(samples, details, payload["taxonomy"])
            metrics = score_predictions(samples, predictions, labels)
            if metrics != result["hybrid_metrics"] or metrics != result["api_only_metrics"]:
                raise ConfigError("Saved predictions do not reproduce reported metrics")
            warm = result["warm"]
            if (result["api_coverage_rows"] != len(samples) or warm["cache_rows"] != len(samples)
                    or warm["usage"].get("requests", 0) or not warm["successful_cold_decisions_reproduced"]):
                raise ConfigError("Coverage/warm-cache checks failed")
            for phase, lines in (("cold", len(samples)), ("preflight", 1)):
                item = result[phase]
                cost = cost_estimate(item["usage"], result["pricing_snapshot"], lines)
                if cost != item["cost"] or cost["usd"] is None:
                    raise ConfigError("Cost estimate could not be reproduced")
                total_cost += Decimal(cost["usd"])
                requests += item["usage"].get("requests", 0)
            changes = Counter()
            for sample, prediction in zip(samples, predictions, strict=True):
                label = labels.get(sample["record_id"], {})
                gold = tuple(label.get(f"l{i}", "") for i in range(1, 5) if label.get(f"l{i}", ""))
                if not gold or label.get("include", "1") != "1":
                    continue
                before, after = tuple(sample["local_path"]) == gold, prediction[0] == gold
                changes[("correct" if before else "wrong") + "_to_" + ("correct" if after else "wrong")] += 1
            models[model] = {"metrics": metrics, "paired_changes": dict(changes),
                             "cold": result["cold"], "warm_seconds": warm["seconds"]}
        summary[cohort] = {"report": str(path.relative_to(REPO)), "sample_rows": len(samples),
                           "local": local, "models": models}
    summary["verification"] = {"status": "verified_measured", "api_requests_in_review": 0,
                               "observed_pilot_requests": requests,
                               "estimated_pilot_usd_including_gates": str(total_cost),
                               "limits": "Development samples; B challenge has only one scorable row. No held-out or full-run LLM estimate."}
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary["verification"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, default=REPO / "private/pilot/v1")
    args = parser.parse_args()
    try:
        result = review(args.data_dir, args.pilot_root)
    except (ConfigError, OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
