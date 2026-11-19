"""A zero-label ablations on the original fixed sample; preview never calls an API."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

from cantill.classify import TaxonomyClassifier, decision_confidence
from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.ingest import ingest_company
from cantill.llm import OpenAIClassifier, ZeroLabelClassifier, context_for
from cantill.pilot import digest, score_predictions
from pilot_classification import REPO, file_hash, fingerprint, run_model
from pilot_retrieval import private_path, read_freeze


PROTOCOL = "cantill-zero-ablation-v1"
VARIANTS = {"flat": ("flat", False), "hierarchical": ("hierarchical", False),
            "shortlist": ("shortlist", False), "supplier": ("hierarchical", True)}
HISTORY = REPO / "private/evaluation/reserved_v1"
HISTORICAL_RUN = HISTORY / "runs/67448e8f3bb44b70b94d52f7543549f5"


def reliability(samples, predictions, labels):
    rows = []
    for sample, (path, probability) in zip(samples, predictions, strict=True):
        label = labels[sample["record_id"]]
        golden = tuple(label.get(f"l{i}", "") for i in range(1, 5) if label.get(f"l{i}", ""))
        rows.append((probability, int(tuple(path) == golden)))
    bins = []
    for index in range(10):
        bucket = [(p, y) for p, y in rows if min(9, int(p * 10)) == index]
        if bucket:
            bins.append({"bin": index, "rows": len(bucket), "mean_confidence": sum(p for p, _ in bucket) / len(bucket),
                         "accuracy": sum(y for _, y in bucket) / len(bucket)})
    return {"rows": len(rows), "brier": sum((p - y) ** 2 for p, y in rows) / len(rows),
            "ece_10_bins": sum(b["rows"] * abs(b["accuracy"] - b["mean_confidence"]) for b in bins) / len(rows),
            "bins": bins, "calibration_fitted": False}


def current(config, path):
    return {"pipeline": fingerprint(config, path), "evaluation_tool": file_hash(__file__)}


def variant_samples(samples, variant):
    return [{**sample, "context": {**sample["context"], **({"supplier_name": sample["supplier_name"]} if VARIANTS[variant][1] else {})}}
            for sample in samples]


def factory_for(variant):
    strategy, supplier = VARIANTS[variant]
    def factory(paths, options, **kwargs):
        return ZeroLabelClassifier(paths, replace(options, zero_label_strategy=strategy,
                                                   include_supplier_context=supplier, confidence_mode="raw"), **kwargs)
    return factory


def allowances(payload, variant):
    factory = factory_for(variant)
    options = ClassificationConfig(mode="auto", model=payload["model"], retries=0)
    probe = factory(payload["taxonomy"], options, company_id="A", client=object())
    gate = factory((("Goods", "Bolts"), ("Services", "Cleaning")), options,
                   company_id="synthetic-pilot-preflight", client=object())
    contexts = [s["context"] for s in variant_samples(payload["samples"], variant)]
    unique = {probe.key_for(c): c for c in contexts}
    gate_context = context_for({"description": "Steel hexagonal bolts M12", "unit": "EA", "po_unit": "0" * 36})
    return {"requests": 1 + sum(probe.request_count(c) for c in unique.values()),
            "token_allowance": gate.reservation(gate_context) + sum(probe.reservation(c) for c in unique.values())}


def prepare(data_dir, root):
    if (root / "freeze.json").exists():
        raise ConfigError("Ablation freeze exists; choose a new private root")
    original, integrity = read_freeze(HISTORY / "freeze.json")
    arm = original["arms"]["A_zero"]
    path = REPO / "configs/company_A.yaml"
    config = load_config(path, data_dir)
    before = current(config, path)
    if before["pipeline"]["inputs"] != arm["fingerprint"]["pipeline"]["inputs"]:
        raise ConfigError("Historical A inputs changed")
    data = ingest_company(replace(config, labels=None))
    if sorted(data.taxonomy) != sorted(map(tuple, arm["taxonomy"])):
        raise ConfigError("Historical taxonomy changed")
    by_id = data.records.set_index("record_id").to_dict("index")
    lexical = TaxonomyClassifier(data.taxonomy)
    samples, historical_decisions = [], []
    historical = OpenAIClassifier(data.taxonomy, ClassificationConfig(mode="auto", model=original["model"]),
                                  company_id="A", client=object(), cache_dir=HISTORICAL_RUN / "A_zero/decisions")
    for sample in arm["samples"]:
        if "labelled_examples" in sample["context"] or sample["partition"] != "holdout":
            raise ConfigError("Expected zero-label held-out samples")
        row = by_id[sample["record_id"]]
        if context_for(row) != sample["context"]:
            raise ConfigError("Historical context changed")
        samples.append({**sample, "supplier_name": row["supplier_name"]})
        decision = historical.read_cache(historical.key_for(sample["context"]))
        if decision is None:
            raise ConfigError("Historical decision missing; no replacement API call allowed")
        historical_decisions.append(decision)
    payload = {"protocol": PROTOCOL, "model": original["model"], "taxonomy": data.taxonomy,
               "historical_integrity": integrity, "fingerprint": before, "samples": samples,
               "historical_decisions": historical_decisions}
    # Selection/shortlists are fixed before gold labels open. No labelled index is loaded.
    ranks = [lexical.rank(*(s["context"].get(f, "") for f in
                           ("description", "service_text", "account_description", "material_type"))) for s in samples]
    planned = {variant: allowances(payload, variant) for variant in VARIANTS}
    labels = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
    raw, blended = [], []
    for sample, decision in zip(samples, historical_decisions, strict=True):
        selected = historical.paths[decision["category_id"]]
        raw.append((selected, decision["confidence"]))
        blended.append((selected, decision_confidence(lexical, sample["context"], selected, decision, "blended")))
    hits = sum(tuple(labels[s["record_id"]].get(f"l{i}", "") for i in range(1, 4))
               in {p for p, _ in rank[:8]} for s, rank in zip(samples, ranks, strict=True))
    report = {"status": "prepared_not_live_measured", "api_requests": 0, "sample_rows": len(samples),
              "planned_allowances": planned, "historical_raw_metrics": score_predictions(samples, raw, labels),
              "historical_raw_reliability": reliability(samples, raw, labels),
              "historical_blended_reliability": reliability(samples, blended, labels),
              "lexical_top8_gold_recall": hits / len(samples),
              "new_strategy_accuracy": None,
              "limits": "Reused original reserved sample now serves as regression/development evidence, not a fresh test. Blend weights fixed without fitting labels. Historical confidence replay does not measure new hierarchy/shortlist accuracy."}
    if current(config, path) != before:
        raise ConfigError("Inputs/code changed during preparation")
    root.mkdir(parents=True, exist_ok=True)
    (root / "freeze.json").write_text(json.dumps({"integrity": digest(payload), "payload": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "preparation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run(data_dir, root, variant, execute, max_requests, max_tokens, workers):
    payload, integrity = read_freeze(root / "freeze.json")
    config_path = REPO / "configs/company_A.yaml"
    config = load_config(config_path, data_dir)
    if payload["protocol"] != PROTOCOL or current(config, config_path) != payload["fingerprint"]:
        raise ConfigError("Ablation input/code/config changed; prepare a new freeze")
    needed = allowances(payload, variant)
    if not execute:
        return {"status": "preview", "variant": variant, "api_requests": 0, "required": needed}
    if max_requests < needed["requests"] or max_tokens < needed["token_allowance"]:
        raise ConfigError("Explicit allowances must cover every hierarchy level and gate before API execution")
    samples = variant_samples(payload["samples"], variant)
    directory = root / "runs" / (variant + "_" + uuid4().hex)
    directory.mkdir(parents=True)
    rates = json.loads((REPO / "configs/openai_pricing.json").read_text())[payload["model"]]
    report, predictions = run_model(samples, payload["taxonomy"], "A", payload["model"], rates, directory,
                                    max_requests=max_requests, max_tokens=max_tokens, workers=workers,
                                    backend_factory=factory_for(variant))
    report.update(variant=variant, freeze_integrity=integrity, limitation="Reused historical regression sample; no fresh independent accuracy claim")
    if predictions is not None:
        # Gold opens only after inference and cache-only verification complete.
        labels = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
        probe = factory_for(variant)(payload["taxonomy"], ClassificationConfig(mode="auto", model=payload["model"]),
                                     company_id="A", client=object(), cache_dir=directory / "decisions")
        lexical = TaxonomyClassifier(payload["taxonomy"])
        blended = []
        for sample, prediction in zip(samples, predictions["all"], strict=True):
            decision = probe.read_cache(probe.key_for(sample["context"]))
            blended.append((prediction[0], decision_confidence(lexical, sample["context"], prediction[0], decision, "blended"))
                           if decision else prediction)
        report["raw_metrics"] = score_predictions(samples, predictions["all"], labels)
        report["blended_metrics"] = score_predictions(samples, blended, labels)
        report["raw_reliability"] = reliability(samples, predictions["all"], labels)
        report["blended_reliability"] = reliability(samples, blended, labels)
        report["api_only_metrics"] = score_predictions(predictions["api_samples"], predictions["api_predictions"], labels) if predictions["api_samples"] else None
    if current(config, config_path) != payload["fingerprint"]:
        raise ConfigError("Ablation changed during execution")
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, default=REPO / "private/evaluation/zero_v3_1")
    parser.add_argument("--variant", choices=VARIANTS, default="hierarchical")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        ClassificationConfig(max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
        root = private_path(args.evaluation_root)
        result = prepare(args.data_dir, root) if args.action == "prepare" else run(args.data_dir, root, args.variant, args.execute, args.max_requests, args.max_tokens, args.workers)
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("prepared_not_live_measured", "preview", "measured") else 1


if __name__ == "__main__":
    raise SystemExit(main())
