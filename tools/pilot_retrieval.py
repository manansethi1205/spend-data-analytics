"""Freeze and measure labelled LLM retrieval on the existing development pilots."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cantill.classify import TaxonomyClassifier
from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.ingest import ingest_company
from cantill.llm import OpenAIClassifier, context_for
from cantill.pilot import cost_estimate, digest, score_predictions
from cantill.retrieval import RetrievalIndex
from pilot_classification import REPO, deny_label_read, file_hash, fingerprint, run_model
from review_pilot_results import verify_predictions


COHORTS = (("A", "A"), ("B", "B"), ("B_challenge", "B"))
PROTOCOL = "cantill-retrieval-pilot-v1"


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to((REPO / "private").resolve()):
        raise ConfigError("Retrieval pilot artifacts must remain under private")
    return path


def read_freeze(path):
    frozen = json.loads(Path(path).read_text(encoding="utf-8"))
    if digest(frozen["payload"]) != frozen["integrity"]:
        raise ConfigError("Reference/pilot freeze integrity mismatch")
    return frozen["payload"], frozen["integrity"]


def check_training(index_payload, reference, evaluation_ids):
    partitions = reference["partitions"]
    excluded = {row["group"] for row in partitions.values() if row["partition"] == "holdout"}
    excluded.update(partitions[rid]["group"] for rid in evaluation_ids)
    for row in index_payload["training_rows"]:
        split = partitions.get(row["record_id"])
        if (split is None or split["group"] != row["group"] or split["partition"] != "development"
                or row["group"] in excluded):
            raise ConfigError("Retrieval training overlaps evaluation/reserved groups")


def current_fingerprint(config, config_path, index_path):
    return {"pipeline": fingerprint(config, config_path), "index": file_hash(index_path),
            "pilot_tool": file_hash(__file__)}


def original_predictions(cohort, samples, taxonomy, model):
    directory = REPO / "private/pilot/v1" / cohort
    baseline, integrity = read_freeze(directory / "freeze.json")
    for old, current in zip(baseline["samples"], samples, strict=True):
        if (any(old[key] != current[key] for key in ("record_id", "group", "partition", "spend"))
                or context_for(old["context"]) != context_for(current["context"])):
            raise ConfigError("Original baseline evaluation population/context changed")
    candidates = []
    for path in (directory / "runs").glob("*/report.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["status"] == "measured" and report["freeze_integrity"] == integrity and model in report["models"]:
            candidates.append(path)
    if len(candidates) != 1:
        raise ConfigError("Expected exactly one original measured baseline for the chosen model")
    path = candidates[0].parent / (digest(model)[:16] + "_predictions.json")
    details = json.loads(path.read_text(encoding="utf-8"))
    verify_predictions(samples, details, taxonomy)
    return details


def prepare(data_dir, root, model):
    root = private_path(root)
    if (root / "freeze.json").exists():
        raise ConfigError("Retrieval pilot already frozen; choose a new private root")
    cohorts = {}
    for company in ("A", "B"):
        config_path = REPO / "configs" / f"company_{company}.yaml"
        config = load_config(config_path, data_dir)
        index_path = REPO / "private/retrieval/v1" / company / "index.json"
        before = current_fingerprint(config, config_path, index_path)
        references = {name: read_freeze(REPO / "private/pilot/v2" / name / "freeze.json")[0]
                      for name, owner in COHORTS if owner == company}
        reference = next(iter(references.values()))
        for value in references.values():
            if (value["company_id"] != company or value["partitions"] != reference["partitions"]
                    or any(value["fingerprint"][key] != before["pipeline"][key] for key in ("inputs", "config"))):
                raise ConfigError("Historical reference population/config differs")
        evaluation_ids = {sample["record_id"] for ref in references.values() for sample in ref["samples"]}
        index_payload, _ = read_freeze(index_path)
        check_training(index_payload, reference, evaluation_ids)
        with patch("cantill.ingest.read_table", deny_label_read):
            ingested = ingest_company(replace(config, labels=None))
        index = RetrievalIndex.load(index_path, company_id=company, taxonomy=ingested.taxonomy)
        rows = ingested.records.set_index("record_id").to_dict("index")
        local = TaxonomyClassifier(ingested.taxonomy)
        for name, value in references.items():
            samples = []
            for sample in value["samples"]:
                rid = sample["record_id"]
                row = rows[rid]
                if (sample["partition"] != "development" or sample["group"] != reference["partitions"][rid]["group"]
                        or context_for(row) != sample["context"]):
                    raise ConfigError("Evaluation record/context/split differs from reference")
                predicted = local.predict(*(row[field] for field in ("description", "service_text", "account_description", "material_type")))
                if tuple(sample["local_path"]) != predicted[0] or sample["local_confidence"] != predicted[1]:
                    raise ConfigError("Original lexical prediction changed")
                retrieval = index.predict(row)
                path, confidence = (retrieval[0], retrieval[1]) if retrieval else predicted[:2]
                samples.append({**sample, "context": index.context(row),
                                "fallback_path": list(path), "fallback_confidence": confidence})
            cohorts[name] = {"company_id": company, "fingerprint": before, "samples": samples,
                             "taxonomy": ingested.taxonomy, "reference_fingerprint": index.fingerprint,
                             "original_predictions": original_predictions(name, samples, ingested.taxonomy, model)}
        if before != current_fingerprint(config, config_path, index_path):
            raise ConfigError("Inputs/code/index changed during preparation")
    payload = {"protocol": PROTOCOL, "model": model, "cohorts": cohorts}
    root.mkdir(parents=True, exist_ok=True)
    with (root / "freeze.json").open("x", encoding="utf-8") as stream:
        json.dump({"integrity": digest(payload), "payload": payload}, stream, ensure_ascii=False, indent=2)
    return {"status": "prepared", "cohorts": {k: len(v["samples"]) for k, v in cohorts.items()}, "api_requests": 0}


def load_current(data_dir, root):
    payload, integrity = read_freeze(root / "freeze.json")
    if payload["protocol"] != PROTOCOL or set(payload["cohorts"]) != {name for name, _ in COHORTS}:
        raise ConfigError("Unexpected retrieval pilot protocol/cohorts")
    for name, company in COHORTS:
        config_path = REPO / "configs" / f"company_{company}.yaml"
        config = load_config(config_path, data_dir)
        index_path = REPO / "private/retrieval/v1" / company / "index.json"
        if payload["cohorts"][name]["fingerprint"] != current_fingerprint(config, config_path, index_path):
            raise ConfigError("Retrieval pilot inputs/config/code/index changed since freeze")
    return payload, integrity


def paired_changes(samples, original, assisted, labels):
    changes = {"corrected": 0, "regressed": 0, "both_correct": 0, "both_wrong": 0, "unscored": 0}
    for sample, before, after in zip(samples, original, assisted, strict=True):
        label = labels.get(sample["record_id"], {})
        gold = tuple(label.get(f"l{i}", "") for i in range(1, 5) if label.get(f"l{i}", ""))
        if not gold or label.get("include", "1") != "1":
            changes["unscored"] += 1
            continue
        a, b = tuple(before[0]) == gold, tuple(after[0]) == gold
        changes["both_correct" if a and b else "regressed" if a else "corrected" if b else "both_wrong"] += 1
    return changes


def allowances(payload):
    options = ClassificationConfig(mode="auto", model=payload["model"], retries=0)
    gate = OpenAIClassifier((("Goods", "Bolts"), ("Services", "Cleaning")), options,
                            company_id="synthetic-pilot-preflight", client=object())
    gate_tokens = gate.reservation(context_for({"description": "Steel hexagonal bolts M12", "unit": "EA",
                                               "po_unit": "00000000-0000-0000-0000-000000000000"}))
    result = {}
    for name, cohort in payload["cohorts"].items():
        probe = OpenAIClassifier(cohort["taxonomy"], options, company_id=cohort["company_id"], client=object(),
                                 label_assisted=True, reference_fingerprint=cohort["reference_fingerprint"])
        result[name] = {"requests": len(cohort["samples"]) + 1,
                        "token_allowance": gate_tokens + sum(probe.reservation(s["context"]) for s in cohort["samples"])}
    return result


def run(data_dir, root, *, execute, max_requests, max_tokens, workers):
    root = private_path(root)
    payload, integrity = load_current(data_dir, root)
    model = payload["model"]
    rates = json.loads((REPO / "configs/openai_pricing.json").read_text(encoding="utf-8")).get(model)
    cost_estimate({}, rates, 1)
    planned = allowances(payload)  # Dummy clients: no credential reads or network calls.
    needed = sum(item["requests"] for item in planned.values())
    if execute and max_requests < needed:
        raise ConfigError("Total allowance must cover every frozen company context and synthetic gate")
    if execute and any(item["token_allowance"] > max_tokens // len(COHORTS) for item in planned.values()):
        raise ConfigError("Per-cohort token allowance cannot cover all contexts; increase --max-tokens before execution")
    run_dir = root / "runs" / uuid4().hex
    run_dir.mkdir(parents=True)
    report = {"protocol": PROTOCOL, "freeze_integrity": integrity, "model": model,
              "status": "executed" if execute else "dry_run", "cohorts": {}, "planned_allowances": planned,
              "limits": "Reused development samples; original zero-label baseline is historical, not a fresh paired stochastic repeat. No held-out or unseen-company claim."}
    pending = {}
    # No scoring labels open until every inference phase has finished.
    with patch("cantill.ingest.read_table", deny_label_read):
        if execute:
            for name, _ in COHORTS:
                cohort = payload["cohorts"][name]
                result, predictions = run_model(cohort["samples"], cohort["taxonomy"], cohort["company_id"], model,
                                                rates, run_dir / name, max_requests=len(cohort["samples"]) + 1,
                                                max_tokens=max_tokens // len(COHORTS), workers=workers,
                                                label_assisted=True, reference_fingerprint=cohort["reference_fingerprint"])
                report["cohorts"][name] = result
                if predictions is not None:
                    pending[name] = predictions
                if result.get("status") != "measured":
                    report["status"] = "incomplete"
                    break
    labels_by_company = {}
    for name, company in COHORTS:
        cohort, samples = payload["cohorts"][name], payload["cohorts"][name]["samples"]
        if company not in labels_by_company:
            config = load_config(REPO / "configs" / f"company_{company}.yaml", data_dir)
            labels_by_company[company] = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
        labels = labels_by_company[company]
        original = [(tuple(p["path"]), p["confidence"]) for p in cohort["original_predictions"]]
        local = [(tuple(s["local_path"]), s["local_confidence"]) for s in samples]
        retrieval = [(tuple(s["fallback_path"]), s["fallback_confidence"]) for s in samples]
        result = report["cohorts"].setdefault(name, {"status": "not_executed"})
        result.update({"original_zero_label_metrics": score_predictions(samples, original, labels),
                       "lexical_metrics": score_predictions(samples, local, labels),
                       "retrieval_metrics": score_predictions(samples, retrieval, labels)})
        if name in pending:
            predictions = pending[name]
            result["hybrid_metrics"] = score_predictions(samples, predictions["all"], labels)
            result["api_only_metrics"] = score_predictions(predictions["api_samples"], predictions["api_predictions"], labels) if predictions["api_samples"] else None
            result["paired_vs_original"] = paired_changes(samples, original, predictions["all"], labels)
            details = [{"record_id": sample["record_id"], "path": path, "confidence": confidence,
                        "method": method, "flag": flag}
                       for sample, (path, confidence), method, flag in zip(samples, predictions["all"], predictions["methods"], predictions["flags"], strict=True)]
            (run_dir / f"{name}_predictions.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    if execute and report["status"] != "incomplete":
        report["status"] = "measured"
    if load_current(data_dir, root)[1] != integrity:
        raise ConfigError("Pilot changed during execution")
    report["inputs_code_index_unchanged"] = True
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, default=REPO / "private/pilot/retrieval_v2")
    parser.add_argument("--model", help="Candidate frozen by prepare; omit for run")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=95)
    parser.add_argument("--max-tokens", type=int, default=3_000_000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        ClassificationConfig(max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
        if args.action == "run" and args.model is not None:
            raise ConfigError("Run uses the frozen model; omit --model")
        result = (prepare(args.data_dir, args.pilot_root, args.model or ClassificationConfig().model) if args.action == "prepare" else
                  run(args.data_dir, args.pilot_root, execute=args.execute, max_requests=args.max_requests,
                      max_tokens=args.max_tokens, workers=args.workers))
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
