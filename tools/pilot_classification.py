"""Freeze a private development pilot; execute API requests only with --execute."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.ingest import ingest_company, read_table
from cantill.llm import OpenAIClassifier, context_for
from cantill.pilot import PILOT_PROTOCOL, cost_estimate, digest, score_predictions, select_samples
from cantill.pipeline import run_company


REPO = Path(__file__).resolve().parents[1]


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(config, config_path):
    inputs = {"source:" + source.name: file_hash(config.base_dir / source.table.path) for source in config.sources}
    inputs["taxonomy"] = file_hash(config.base_dir / config.taxonomy.path)
    for role, table in (("fx", config.fx), ("labels", config.labels)):
        if table is not None:
            inputs[role] = file_hash(config.base_dir / table.path)
    code = {str(path.relative_to(REPO)): file_hash(path) for path in (REPO / "src/cantill").glob("*.py")}
    code["tools/pilot_classification.py"] = file_hash(__file__)
    return {"config": file_hash(config_path), "inputs": inputs, "code": code}


def deny_label_read(base, table, role):
    if role == "labels":
        raise AssertionError("Pilot inference attempted to read labels")
    return read_table(base, table, role)


def prepare(config, config_path, directory, *, sample_size, source, cohort):
    directory = Path(directory)
    path = directory / "freeze.json"
    if path.exists():
        raise ConfigError("Pilot already frozen; reuse it with run, or choose a new private directory")
    before = fingerprint(config, config_path)
    started = perf_counter()
    with patch("cantill.ingest.read_table", deny_label_read):
        local = run_company(replace(config, labels=None), classification=ClassificationConfig(mode="local"))
    local_seconds = perf_counter() - started
    cohort_ids = None
    if cohort == "included-labels":
        # Selection uses label availability/inclusion, never category/entity values.
        # This is explicitly a biased labelled development cohort, not population accuracy.
        labels = ingest_company(config, load_labels=True).labels
        cohort_ids = set(labels.loc[labels["include"] == "1", "record_id"]) if "include" in labels else set(labels.record_id)
    ingested = local.resolved.matched.eligible.normalized.ingested
    samples, partitions, summary = select_samples(local.records, ingested.taxonomy,
                                                   sample_size=sample_size, source=source, cohort_ids=cohort_ids)
    if not samples:
        raise ConfigError("No development records available for the requested pilot cohort")
    if fingerprint(config, config_path) != before:
        raise ConfigError("Pilot inputs or code changed during preparation")
    payload = {"protocol": PILOT_PROTOCOL, "company_id": config.company_id, "fingerprint": before,
               "source": source, "cohort": cohort, "summary": summary, "local_pipeline_seconds": local_seconds,
               "taxonomy": ingested.taxonomy, "samples": samples, "partitions": partitions}
    frozen = {"integrity": digest(payload), "payload": payload}
    directory.mkdir(parents=True, exist_ok=True)
    # Exclusive create prevents accidentally overwriting the chosen evaluation sample.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(frozen, stream, ensure_ascii=False, indent=2)
    return summary


def load_frozen(config, config_path, directory):
    try:
        frozen = json.loads((Path(directory) / "freeze.json").read_text(encoding="utf-8"))
        payload = frozen["payload"]
        if frozen["integrity"] != digest(payload) or payload["protocol"] != PILOT_PROTOCOL:
            raise ConfigError("Pilot freeze integrity/protocol mismatch")
        if payload["fingerprint"] != fingerprint(config, config_path):
            raise ConfigError("Pilot inputs/config/code changed since freeze; use a new private directory")
        samples = payload["samples"]
        if not samples or any(sample["partition"] != "development" for sample in samples):
            raise ConfigError("Pilot must contain development records only")
        return payload, frozen["integrity"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError("Cannot read the frozen private pilot") from None


def run_model(samples, taxonomy, company_id, model, rates, directory, *, max_requests, max_tokens, workers,
              backend_factory=OpenAIClassifier, label_assisted=False, reference_fingerprint=""):
    """One synthetic gate, one cold run, then a strictly cache-only warm run."""
    options = ClassificationConfig(mode="openai", model=model, workers=workers, retries=0,
                                   max_requests=1, max_tokens=max_tokens)
    gate_context = context_for({"description": "Steel hexagonal bolts M12", "unit": "EA", "po_unit": str(uuid4())})
    gate = backend_factory((("Goods", "Bolts"), ("Services", "Cleaning")), options,
                           company_id="synthetic-pilot-preflight", cache_dir=directory / "preflight")
    gate_allowance = gate.reservation(gate_context)
    if max_requests < 2 or max_tokens <= gate_allowance:
        if getattr(gate, "owns_client", False):
            gate.client.close()
        return {"status": "blocked_budget", "company_requests": 0}, None
    gate_result, _, gate_flag = gate.classify_many([gate_context])[0]
    preflight = {"usage": dict(gate.stats), "flag": gate_flag, "cost": cost_estimate(gate.stats, rates, 1)}
    if gate_result is None:
        return {"status": "blocked_preflight", "preflight": preflight, "company_requests": 0}, None
    contexts = [sample["context"] for sample in samples]
    cold_options = replace(options, max_requests=max_requests - 1, max_tokens=max_tokens - gate_allowance)
    cache_dir = directory / "decisions"
    if cache_dir.exists():
        raise ConfigError("Cold pilot cache must be new")
    assisted = {"label_assisted": True, "reference_fingerprint": reference_fingerprint} if label_assisted else {}
    cold = backend_factory(taxonomy, cold_options, company_id=company_id, cache_dir=cache_dir, **assisted)
    needed_tokens = sum(cold.reservation(context) for context in contexts)
    if cold_options.max_requests < len(contexts) or cold_options.max_tokens < needed_tokens:
        if getattr(cold, "owns_client", False):
            cold.client.close()
        return {"status": "blocked_budget", "preflight": preflight, "company_requests": 0,
                "required_company_requests": len(contexts), "required_company_token_allowance": needed_tokens}, None
    started = perf_counter()
    decisions = cold.classify_many(contexts)
    cold_seconds = perf_counter() - started
    predictions, api_predictions, api_samples = [], [], []
    for sample, (result, method, flag) in zip(samples, decisions, strict=True):
        prediction = ((cold.paths[result["category_id"]], result["confidence"]) if result is not None
                      else (tuple(sample.get("fallback_path", sample["local_path"])),
                            sample.get("fallback_confidence", sample["local_confidence"])))
        predictions.append(prediction)
        if result is not None:
            api_samples.append(sample)
            api_predictions.append(prediction)
    warm = backend_factory(taxonomy, replace(cold_options, mode="auto", max_requests=0), company_id=company_id, cache_dir=cache_dir, **assisted)
    started = perf_counter()
    warm_decisions = warm.classify_many(contexts)
    warm_seconds = perf_counter() - started
    if warm.stats.get("requests", 0):
        raise AssertionError("Warm pilot unexpectedly called the API")
    report = {"status": "measured" if len(api_samples) == len(samples) else "partial", "pricing_snapshot": rates,
              "preflight": preflight, "company_requests": cold.stats.get("requests", 0),
              "api_coverage_rows": len(api_samples), "sample_rows": len(samples),
              "cold": {"seconds": cold_seconds, "seconds_per_sample_line": cold_seconds / len(samples),
                       "usage": dict(cold.stats), "cost": cost_estimate(cold.stats, rates, len(samples)),
                       "flags": {flag: sum(item[2] == flag for item in decisions) for flag in sorted({item[2] for item in decisions if item[2]})}},
              "warm": {"seconds": warm_seconds, "usage": dict(warm.stats),
                       "cache_rows": sum(method == "cache" for _, method, _ in warm_decisions),
                       "successful_cold_decisions_reproduced": all(cold_item[0] is None or cold_item[0] == warm_item[0]
                                                                  for cold_item, warm_item in zip(decisions, warm_decisions, strict=True)),
                       "cost": cost_estimate(warm.stats, rates, len(samples))}}
    if report["status"] == "measured" and (report["warm"]["cache_rows"] != len(samples)
                                            or not report["warm"]["successful_cold_decisions_reproduced"]):
        report["status"] = "cache_verification_failed"
    return report, {"all": predictions, "api_samples": api_samples, "api_predictions": api_predictions,
                    "methods": [method for _, method, _ in decisions], "flags": [flag for _, _, flag in decisions]}


def run(config, config_path, directory, *, execute, models, prices, max_requests, max_tokens, workers):
    payload, integrity = load_frozen(config, config_path, directory)
    for model in models:
        cost_estimate({}, prices.get(model), 1)  # Validate prices before any request.
    samples = payload["samples"]
    run_dir = Path(directory) / "runs" / uuid4().hex
    run_dir.mkdir(parents=True)
    report = {"protocol": PILOT_PROTOCOL, "freeze_integrity": integrity,
              "status": "dry_run" if not execute else "executed", "sample_summary": payload["summary"],
              "cohort": payload["cohort"], "models": {},
              "limits": "Development diagnostics only; previous full-data baseline/eligibility review disclosed. Stratified unique contexts and labelled B seeds do not estimate population performance."}
    pending = {}
    # No labels or their values are read during any API/local inference phase.
    with patch("cantill.ingest.read_table", deny_label_read):
        if execute:
            per_requests, per_tokens = max_requests // len(models), max_tokens // len(models)
            for model in models:
                try:
                    result, predictions = run_model(samples, payload["taxonomy"], payload["company_id"], model,
                                                    prices.get(model), run_dir / digest(model)[:16],
                                                    max_requests=per_requests, max_tokens=per_tokens, workers=workers)
                except ConfigError as exc:
                    result, predictions = {"status": "blocked_configuration", "company_requests": 0, "reason": str(exc)}, None
                report["models"][model] = result
                if predictions is not None:
                    pending[model] = predictions
                if result.get("preflight", {}).get("usage", {}).get("http_401") or result.get("preflight", {}).get("usage", {}).get("http_403"):
                    report["status"] = "blocked_authentication"
                    break
    # Gold values open only after every model's inference has finished.
    labels = ingest_company(config, load_labels=True).labels.set_index("record_id").to_dict("index") if config.labels is not None else {}
    local_predictions = [(tuple(sample["local_path"]), sample["local_confidence"]) for sample in samples]
    report["local"] = score_predictions(samples, local_predictions, labels)
    for model, predictions in pending.items():
        report["models"][model]["hybrid_metrics"] = score_predictions(samples, predictions["all"], labels)
        report["models"][model]["api_only_metrics"] = score_predictions(predictions["api_samples"], predictions["api_predictions"], labels) if predictions["api_samples"] else None
        details = [{"record_id": sample["record_id"], "path": path, "confidence": confidence, "method": method, "flag": flag}
                   for sample, (path, confidence), method, flag in zip(samples, predictions["all"], predictions["methods"], predictions["flags"], strict=True)]
        (run_dir / (digest(model)[:16] + "_predictions.json")).write_text(json.dumps(details, indent=2), encoding="utf-8")
    if execute and report["status"] != "blocked_authentication":
        report["status"] = "measured" if len(report["models"]) == len(models) and all(item["status"] == "measured" for item in report["models"].values()) else "incomplete"
    if payload["fingerprint"] != fingerprint(config, config_path):
        raise ConfigError("Pilot inputs/code changed during execution")
    report["inputs_and_code_unchanged"] = True
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=40)
    parser.add_argument("--source")
    parser.add_argument("--cohort", choices=("all", "included-labels"), default="all")
    parser.add_argument("--execute", action="store_true", help="Allow bounded company-data API requests after a synthetic gate")
    parser.add_argument("--models", nargs="+", default=[ClassificationConfig().model])
    parser.add_argument("--pricing-file", type=Path, default=REPO / "configs/openai_pricing.json")
    parser.add_argument("--max-requests", type=int, default=41, help="Total attempts across models, including synthetic gates")
    parser.add_argument("--max-tokens", type=int, default=1_000_000, help="Total conservative allowance across models and gates")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    try:
        if not args.pilot_dir.resolve().is_relative_to((REPO / "private").resolve()):
            raise ConfigError("Pilot artifacts must stay under this repository's ignored private directory")
        ClassificationConfig(max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
        if not 1 <= len(args.models) <= 4 or len(set(args.models)) != len(args.models) or any(not model.strip() for model in args.models):
            raise ConfigError("Pilot models must be one to four unique nonblank model IDs")
        config = load_config(args.config, args.data_dir)
        if args.action == "prepare":
            report = prepare(config, args.config, args.pilot_dir, sample_size=args.sample_size, source=args.source, cohort=args.cohort)
        else:
            prices = json.loads(args.pricing_file.read_text(encoding="utf-8"))
            if not isinstance(prices, dict):
                raise ConfigError("Pilot pricing file must be a model-to-rates mapping")
            report = run(config, args.config, args.pilot_dir, execute=args.execute, models=args.models, prices=prices,
                         max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
    except (ConfigError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(report, indent=2))
    return 1 if report.get("status") in ("blocked_authentication", "incomplete") else 0


if __name__ == "__main__":
    raise SystemExit(main())
