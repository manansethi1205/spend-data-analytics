"""Freeze reserved-group samples; evaluate the fixed classifier before label scoring."""

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
from cantill.pilot import cost_estimate, digest, partition_records, score_predictions, stratum
from cantill.pipeline import run_company
from cantill.retrieval import RetrievalIndex
from pilot_classification import REPO, deny_label_read, file_hash, fingerprint, run_model
from pilot_retrieval import check_training, load_current as load_development, paired_changes, private_path, read_freeze


PROTOCOL = "cantill-reserved-evaluation-v1"
ARMS = (("A_zero", "A", False), ("A_assisted", "A", True), ("B_assisted", "B", True))


def select_reserved(records, partitions, company, size, *, source=None, cohort_ids=None):
    """One row per reserved group/context, selected by hash without category labels."""
    if type(size) is not int or not 1 <= size <= 500:
        raise ConfigError("Reserved sample size must be in [1, 500]")
    rows = records.to_dict("records")
    if {r["record_id"] for r in rows} != set(partitions):
        raise ConfigError("Reserved split does not cover current records")
    candidates = [r for r in rows if r["include"] and partitions[r["record_id"]]["partition"] == "holdout"
                  and (source is None or r["source"] == source)
                  and (cohort_ids is None or r["record_id"] in cohort_ids)]
    candidates.sort(key=lambda row: digest([PROTOCOL, company, row["record_id"]]))
    selected, groups, contexts = [], set(), set()
    for row in candidates:
        group, context = partitions[row["record_id"]]["group"], digest(context_for(row))
        if group not in groups and context not in contexts:
            selected.append(row)
            groups.add(group)
            contexts.add(context)
        if len(selected) == size:
            break
    if not selected:
        raise ConfigError("No eligible reserved records available")
    return selected, {"candidate_rows": len(candidates), "selected_rows": len(selected),
                      "requested_rows": size, "available_candidate_groups": len({partitions[r['record_id']]['group'] for r in candidates})}


def strategy_fingerprint(config, config_path, index_path):
    return {"pipeline": fingerprint(config, config_path), "index": file_hash(index_path),
            "evaluation_tool": file_hash(__file__), "reference_tool": file_hash(REPO / "tools/pilot_retrieval.py")}


def prepare(data_dir, root, size):
    root = private_path(root)
    if (root / "freeze.json").exists():
        raise ConfigError("Reserved evaluation already frozen; do not overwrite it")
    development, development_integrity = load_development(data_dir, REPO / "private/pilot/retrieval_v2")
    model, arms, selection = development["model"], {}, {}
    for company in ("A", "B"):
        config_path = REPO / "configs" / f"company_{company}.yaml"
        config = load_config(config_path, data_dir)
        index_path = REPO / "private/retrieval/v1" / company / "index.json"
        before = strategy_fingerprint(config, config_path, index_path)
        reference, _ = read_freeze(REPO / "private/pilot/v2" / company / "freeze.json")
        with patch("cantill.ingest.read_table", deny_label_read):
            local = run_company(replace(config, labels=None), classification=ClassificationConfig(mode="local"))
        records = local.records
        partitions = partition_records(records.to_dict("records"))
        if partitions != reference["partitions"]:
            raise ConfigError("Reserved group assignments changed since development")
        cohort_ids = None
        if company == "B":
            # Only ID/inclusion availability is mapped for cohort selection; no category values.
            spec = replace(config.labels, fields={k: v for k, v in config.labels.fields.items() if k in ("record_id", "include")})
            labels = ingest_company(replace(config, labels=spec), load_labels=True).labels
            cohort_ids = set(labels.loc[labels["include"] == "1", "record_id"])
        selected, selection[company] = select_reserved(records, partitions, company, size,
                                                       source=reference["source"] if company == "A" else None,
                                                       cohort_ids=cohort_ids)
        ids = {row["record_id"] for row in selected}
        index_payload, _ = read_freeze(index_path)
        check_training(index_payload, reference, ids)
        taxonomy = local.resolved.matched.eligible.normalized.ingested.taxonomy
        index = RetrievalIndex.load(index_path, company_id=company, taxonomy=taxonomy)
        lexical = TaxonomyClassifier(taxonomy)
        samples = []
        for row in selected:
            rid = row["record_id"]
            path = [row[f"l{i}"] for i in range(1, 5) if row[f"l{i}"]]
            retrieval = index.predict(row)
            samples.append({"record_id": rid, **partitions[rid], "context": context_for(row),
                            "local_path": path, "local_confidence": row["confidence"],
                            "spend": str(row["spend_value"]) if row["spend_value"] is not None else None,
                            "stratum": stratum(row, lexical),
                            "fallback_path": list(retrieval[0]) if retrieval else path,
                            "fallback_confidence": retrieval[1] if retrieval else row["confidence"],
                            "reference_context": index.context(row)})
        for name, owner, assisted in ARMS:
            if owner != company:
                continue
            arm_samples = []
            for sample in samples:
                entry = {k: v for k, v in sample.items() if k != "reference_context"}
                if assisted:
                    entry["context"] = sample["reference_context"]
                else:
                    entry.pop("fallback_path")
                    entry.pop("fallback_confidence")
                arm_samples.append(entry)
            arms[name] = {"company_id": company, "assisted": assisted, "samples": arm_samples,
                          "taxonomy": taxonomy, "fingerprint": before,
                          "reference_fingerprint": index.fingerprint if assisted else ""}
        if before != strategy_fingerprint(config, config_path, index_path):
            raise ConfigError("Classifier/index/input changed during reserved preparation")
    payload = {"protocol": PROTOCOL, "model": model, "development_integrity": development_integrity,
               "selection": selection, "arms": arms}
    root.mkdir(parents=True, exist_ok=True)
    with (root / "freeze.json").open("x", encoding="utf-8") as stream:
        json.dump({"integrity": digest(payload), "payload": payload}, stream, ensure_ascii=False, indent=2)
    return {"status": "prepared", "selection": selection, "api_requests": 0,
            "required_requests": sum(len(arm["samples"]) + 1 for arm in arms.values())}


def load_current(data_dir, root):
    payload, integrity = read_freeze(root / "freeze.json")
    if payload["protocol"] != PROTOCOL or set(payload["arms"]) != {name for name, _, _ in ARMS}:
        raise ConfigError("Unexpected reserved evaluation protocol/arms")
    for name, company, assisted in ARMS:
        arm = payload["arms"][name]
        config_path = REPO / "configs" / f"company_{company}.yaml"
        config = load_config(config_path, data_dir)
        if arm["fingerprint"] != strategy_fingerprint(config, config_path, REPO / "private/retrieval/v1" / company / "index.json"):
            raise ConfigError("Fixed classifier/config/index/input changed since reserved freeze")
        if not arm["samples"] or arm["assisted"] != assisted or any(s["partition"] != "holdout" for s in arm["samples"]):
            raise ConfigError("Invalid reserved arm/split")
        if any(("labelled_examples" in s["context"]) != assisted for s in arm["samples"]):
            raise ConfigError("Zero-label/reference contexts are mixed")
        if not assisted and any("fallback_path" in s or "fallback_confidence" in s for s in arm["samples"]):
            raise ConfigError("Zero-label evaluation contains a labelled fallback")
    a, b = payload["arms"]["A_zero"]["samples"], payload["arms"]["A_assisted"]["samples"]
    if ([s["record_id"] for s in a] != [s["record_id"] for s in b]
            or any(context_for(x["context"]) != context_for(y["context"]) for x, y in zip(a, b, strict=True))):
        raise ConfigError("A comparison arms must use identical records and line contexts")
    return payload, integrity


def planned_allowances(payload):
    options = ClassificationConfig(mode="auto", model=payload["model"], retries=0)
    gate = OpenAIClassifier((("Goods", "Bolts"), ("Services", "Cleaning")), options,
                            company_id="synthetic-pilot-preflight", client=object())
    gate_tokens = gate.reservation(context_for({"description": "Steel hexagonal bolts M12", "unit": "EA",
                                               "po_unit": "00000000-0000-0000-0000-000000000000"}))
    result = {}
    for name, arm in payload["arms"].items():
        probe = OpenAIClassifier(arm["taxonomy"], options, company_id=arm["company_id"], client=object(),
                                 label_assisted=arm["assisted"], reference_fingerprint=arm["reference_fingerprint"])
        result[name] = {"requests": len(arm["samples"]) + 1,
                        "token_allowance": gate_tokens + sum(probe.reservation(s["context"]) for s in arm["samples"])}
    return result


def run(data_dir, root, *, execute, max_requests, max_tokens, workers):
    root = private_path(root)
    payload, integrity = load_current(data_dir, root)
    rates = json.loads((REPO / "configs/openai_pricing.json").read_text(encoding="utf-8")).get(payload["model"])
    cost_estimate({}, rates, 1)
    planned = planned_allowances(payload)
    if execute and (sum(v["requests"] for v in planned.values()) > max_requests
                    or any(v["token_allowance"] > max_tokens // len(ARMS) for v in planned.values())):
        raise ConfigError("Request/token allowances cannot cover every reserved arm before execution")
    directory = root / "runs" / uuid4().hex
    directory.mkdir(parents=True)
    report = {"protocol": PROTOCOL, "freeze_integrity": integrity, "model": payload["model"],
              "status": "executed" if execute else "dry_run", "selection": payload["selection"],
              "planned_allowances": planned, "arms": {},
              "limits": "Group-balanced reserved samples, not unbiased population/spend estimates. B selects included labelled seed IDs. Earlier full-data lexical/eligibility review disclosed; this is not an untouched external test. Do not tune on these scores."}
    pending = {}
    with patch("cantill.ingest.read_table", deny_label_read):
        if execute:
            for name, _, _ in ARMS:
                arm = payload["arms"][name]
                result, predictions = run_model(arm["samples"], arm["taxonomy"], arm["company_id"], payload["model"],
                                                rates, directory / name, max_requests=planned[name]["requests"],
                                                max_tokens=max_tokens // len(ARMS), workers=workers,
                                                label_assisted=arm["assisted"], reference_fingerprint=arm["reference_fingerprint"])
                report["arms"][name] = result
                if predictions is not None:
                    pending[name] = predictions
                if result["status"] != "measured":
                    report["status"] = "incomplete"
                    break
    labels_by_company = {}
    for name, company, assisted in ARMS:
        arm, samples = payload["arms"][name], payload["arms"][name]["samples"]
        if company not in labels_by_company:
            config = load_config(REPO / "configs" / f"company_{company}.yaml", data_dir)
            labels_by_company[company] = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index")
        labels = labels_by_company[company]
        result = report["arms"].setdefault(name, {"status": "not_executed"})
        local = [(tuple(s["local_path"]), s["local_confidence"]) for s in samples]
        result["lexical_metrics"] = score_predictions(samples, local, labels)
        if assisted:
            result["retrieval_metrics"] = score_predictions(samples, [(tuple(s["fallback_path"]), s["fallback_confidence"]) for s in samples], labels)
        if name in pending:
            predictions = pending[name]
            result["hybrid_metrics"] = score_predictions(samples, predictions["all"], labels)
            result["api_only_metrics"] = score_predictions(predictions["api_samples"], predictions["api_predictions"], labels) if predictions["api_samples"] else None
            details = [{"record_id": s["record_id"], "path": path, "confidence": confidence, "method": method, "flag": flag}
                       for s, (path, confidence), method, flag in zip(samples, predictions["all"], predictions["methods"], predictions["flags"], strict=True)]
            (directory / f"{name}_predictions.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
    if "A_zero" in pending and "A_assisted" in pending:
        report["A_assisted_vs_zero"] = paired_changes(payload["arms"]["A_zero"]["samples"],
                                                      pending["A_zero"]["all"], pending["A_assisted"]["all"], labels_by_company["A"])
    if execute and report["status"] != "incomplete":
        report["status"] = "measured"
    if load_current(data_dir, root)[1] != integrity:
        raise ConfigError("Reserved evaluation changed during execution")
    report["inputs_code_index_unchanged"] = True
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, default=REPO / "private/evaluation/reserved_v1")
    parser.add_argument("--sample-size", type=int, default=100, help="Maximum rows/groups per company during prepare")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=303)
    parser.add_argument("--max-tokens", type=int, default=6_000_000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        ClassificationConfig(max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
        result = (prepare(args.data_dir, args.evaluation_root, args.sample_size) if args.action == "prepare" else
                  run(args.data_dir, args.evaluation_root, execute=args.execute, max_requests=args.max_requests,
                      max_tokens=args.max_tokens, workers=args.workers))
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "incomplete" else 0


if __name__ == "__main__":
    main()
