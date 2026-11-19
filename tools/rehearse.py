"""Plan and rehearse complete company runs with the evaluated classifier unchanged."""

import argparse
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from cantill.classify import classify_company
from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.llm import OpenAIClassifier, context_for
from cantill.output import validate_output
from cantill.pilot import cost_estimate, digest
from cantill.pipeline import run_company, write_output
from cantill.retrieval import RetrievalIndex
from evaluate_holdout import load_current as load_evaluated
from evaluate_holdout import PROTOCOL as EVALUATION_PROTOCOL, strategy_fingerprint
from pilot_classification import REPO, deny_label_read, file_hash, fingerprint
from pilot_retrieval import private_path, read_freeze


PROTOCOL = "cantill-full-rehearsal-v1"


def current_fingerprint(config, config_path, index_path):
    return {"pipeline": fingerprint(config, config_path), "index": file_hash(index_path),
            "rehearsal_tool": file_hash(__file__)}


def config_for(company, data_dir):
    path = REPO / "configs" / f"company_{company}.yaml"
    return load_config(path, data_dir), path, REPO / "private/retrieval/v1" / company / "index.json"


def components(config, index_path):
    with patch("cantill.ingest.read_table", deny_label_read):
        local = run_company(replace(config, labels=None), classification=ClassificationConfig(mode="local"))
    tree = local.resolved.matched.eligible.normalized.ingested.taxonomy
    index = RetrievalIndex.load(index_path, company_id=config.company_id, taxonomy=tree)
    rows = local.records.loc[local.records.include == 1].to_dict("records")
    return local, index, rows


def gate_context():
    return context_for({"description": "Steel hexagonal bolts M12", "unit": "EA", "po_unit": str(uuid4())})


def gate_backend(model, *, client=None, cache_dir=None):
    return OpenAIClassifier((("Goods", "Bolts"), ("Services", "Cleaning")),
                            ClassificationConfig(mode="openai", model=model, retries=0, max_requests=1, max_tokens=64000),
                            company_id="synthetic-rehearsal-preflight", client=client, cache_dir=cache_dir)


def requirements(local, index, rows, model):
    tree = local.resolved.matched.eligible.normalized.ingested.taxonomy
    probe = OpenAIClassifier(tree, ClassificationConfig(mode="auto", model=model), company_id=local.resolved.matched.eligible.normalized.ingested.config.company_id,
                             client=object(), label_assisted=True, reference_fingerprint=index.fingerprint)
    contexts = [index.context(row) for row in rows]
    unique = {probe.key_for(context): context for context in contexts}
    gate_tokens = gate_backend(model, client=object()).reservation(gate_context())
    return contexts, {"unique_contexts": len(unique), "included_rows": len(rows),
                      "required_requests_including_gate": len(unique) + 1,
                      "required_token_allowance_including_gate": gate_tokens + sum(probe.reservation(c) for c in unique.values())}


def independently_validate(result, path):
    ingested = result.resolved.matched.eligible.normalized.ingested
    validation = validate_output(path, ingested.records.record_id, ingested.taxonomy)
    if not validation.valid:
        raise ConfigError("Rehearsal output failed independent validation")
    return validation.summary()


def financial_update_provenance(data_dir):
    """Disclose a new financial version without rewriting the historical evaluation."""
    evaluated, integrity = read_freeze(REPO / "private/evaluation/reserved_v1/freeze.json")
    if evaluated["protocol"] != EVALUATION_PROTOCOL:
        raise ConfigError("Unexpected historical evaluation protocol")
    changes = {}
    allowed = {"src/cantill/config.py", "src/cantill/normalize.py"}
    for name, arm in evaluated["arms"].items():
        company = "A" if name.startswith("A_") else "B"
        config, path, index = config_for(company, data_dir)
        current = strategy_fingerprint(config, path, index)
        previous = arm["fingerprint"]
        if any(current[key] != previous[key] for key in ("index", "evaluation_tool", "reference_tool")):
            raise ConfigError("Financial update cannot change reference indexes/evaluation tools")
        old, new = previous["pipeline"], current["pipeline"]
        if old["inputs"] != new["inputs"] or set(old["code"]) != set(new["code"]):
            raise ConfigError("Financial update cannot change raw inputs or code inventory")
        changed = [key for key in old["code"] if old["code"][key] != new["code"][key]]
        if any(key.replace("\\", "/") not in allowed for key in changed):
            raise ConfigError("Financial update changed code outside config/normalization")
        if company == "A" and old["config"] != new["config"]:
            raise ConfigError("A configuration must remain unchanged")
        changes[name] = {"changed_code": changed, "config_changed": old["config"] != new["config"]}
    return evaluated, {"historical_evaluation_integrity": integrity,
                       "scope": "Financial normalization/config update; historical scores are not a re-evaluation",
                       "changes": changes}


def prepare(data_dir, root, companies, *, financial_policy_update=False):
    root = private_path(root)
    if (root / "plan.json").exists():
        raise ConfigError("Rehearsal already planned; reuse it or choose a new private root")
    if financial_policy_update:
        evaluated, provenance = financial_update_provenance(data_dir)
    else:
        evaluated, _ = load_evaluated(data_dir, REPO / "private/evaluation/reserved_v1")
        provenance = {"scope": "Unchanged evaluated pipeline"}
    model = evaluated["model"]
    plan = {"protocol": PROTOCOL, "model": model, "provenance": provenance, "companies": {}}
    for company in companies:
        config, config_path, index_path = config_for(company, data_dir)
        before = current_fingerprint(config, config_path, index_path)
        started = perf_counter()
        local, index, rows = components(config, index_path)
        _, needed = requirements(local, index, rows, model)
        fallback = classify_company(local.resolved, options=ClassificationConfig(mode="local"), retrieval=index)
        summary = fallback.summary()
        directory = root / company
        directory.mkdir(parents=True, exist_ok=True)
        unresolved = fallback.records[(fallback.records.include == 1) & ~fallback.records.financial_ready.astype(bool)]
        exceptions = [{"record_id": row["record_id"], "quality_flags": list(row["quality_flags"]),
                       "amount": row["amount"], "currency": row["currency"],
                       "invoice_date": row["invoice_date"], "posting_date": row["posting_date"]}
                      for row in unresolved.to_dict("records")]
        (directory / "financial_exceptions.json").write_text(json.dumps(exceptions, indent=2), encoding="utf-8")
        estimated = fallback.records[(fallback.records.include == 1) & fallback.records.financial_estimated.astype(bool)]
        audit = [{key: str(row[key]) if key in ("amount_value", "exchange_rate_value", "reporting_amount_value") else row[key]
                  for key in ("record_id", "amount", "amount_value", "currency", "fx_month", "fx_reference_month",
                              "exchange_rate_value", "exchange_rate_source", "reporting_amount_value", "quality_flags")}
                 for row in estimated.to_dict("records")]
        (directory / "financial_estimates.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        validation = None
        if not exceptions:
            output = directory / "local_fallback.csv"
            write_output(fallback, output)
            validation = independently_validate(fallback, output)
        if before != current_fingerprint(config, config_path, index_path):
            raise ConfigError("Input/code/index changed during rehearsal planning")
        entry = {"fingerprint": before, **needed, "source_rows": len(local.records),
                 "financial_exceptions": len(exceptions), "financial_estimated_rows": len(audit), "financial_export_ready": not exceptions,
                 "local_seconds": perf_counter() - started, "local_summary": summary,
                 "local_output_validation": validation, "api_requests": 0}
        plan["companies"][company] = entry
        (directory / "preparation.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
    with (root / "plan.json").open("x", encoding="utf-8") as stream:
        json.dump({"integrity": digest(plan), "payload": plan}, stream, indent=2)
    return {"status": "planned", "api_requests": 0,
            "companies": {name: {key: entry[key] for key in ("source_rows", "included_rows", "unique_contexts",
                         "required_requests_including_gate", "required_token_allowance_including_gate",
                         "financial_exceptions", "financial_export_ready", "local_seconds")}
                          for name, entry in plan["companies"].items()}}


def load_plan(data_dir, root, company):
    plan, integrity = read_freeze(root / "plan.json")
    if plan["protocol"] != PROTOCOL or company not in plan["companies"]:
        raise ConfigError("Company not present in this rehearsal plan")
    config, config_path, index_path = config_for(company, data_dir)
    if current_fingerprint(config, config_path, index_path) != plan["companies"][company]["fingerprint"]:
        raise ConfigError("Rehearsal input/config/code/index changed; prepare a new plan")
    return plan, integrity, config, config_path, index_path


def run(data_dir, root, company, *, execute, max_requests, max_tokens, workers):
    root = private_path(root)
    started = perf_counter()
    plan, integrity, config, config_path, index_path = load_plan(data_dir, root, company)
    entry = plan["companies"][company]
    if not execute:
        return {"status": "preview", "company": company, "plan": entry, "api_requests": 0}
    if not entry["financial_export_ready"]:
        raise ConfigError("Final export is blocked by unresolved financial values; no API calls made")
    if max_requests < entry["required_requests_including_gate"] or max_tokens < entry["required_token_allowance_including_gate"]:
        raise ConfigError("Explicit allowances must cover the prepared full-company plan before any API request")
    rates = json.loads((REPO / "configs/openai_pricing.json").read_text(encoding="utf-8")).get(plan["model"])
    cost_estimate({}, rates, 1)
    directory = root / company / "runs" / uuid4().hex
    directory.mkdir(parents=True)
    report = {"protocol": PROTOCOL, "plan_integrity": integrity, "company_id": company,
              "model": plan["model"], "status": "blocked_preflight", "pricing_snapshot": rates,
              "execution": {"workers": workers, "retries": 0, "timeout_seconds": 30,
                            "max_output_tokens": 512, "max_requests": max_requests, "max_tokens": max_tokens}}
    gate = gate_backend(plan["model"], cache_dir=directory / "gate")
    context = gate_context()
    gate_allowance = gate.reservation(context)
    decision, _, flag = gate.classify_many([context])[0]
    report["preflight"] = {"flag": flag, "usage": dict(gate.stats), "cost": cost_estimate(gate.stats, rates, 1)}
    if decision is not None:
        local, index, rows = components(config, index_path)
        contexts, needed = requirements(local, index, rows, plan["model"])
        if any(needed[key] != entry[key] for key in needed):
            raise ConfigError("Full-company query population changed since planning")
        options = ClassificationConfig(mode="openai", model=plan["model"], workers=workers, retries=0,
                                       max_requests=max_requests - 1, max_tokens=max_tokens - gate_allowance)
        cache = root / company / "decisions"
        initial_cache_files = len(list(cache.glob("*.json"))) if cache.exists() else 0
        inference_start = perf_counter()
        with patch("cantill.ingest.read_table", deny_label_read):
            result = classify_company(local.resolved, options=options, retrieval=index, cache_dir=cache)
        inference_seconds = perf_counter() - inference_start
        tree = result.resolved.matched.eligible.normalized.ingested.taxonomy
        warm = OpenAIClassifier(tree, replace(options, mode="auto", max_requests=0, max_tokens=0),
                                 company_id=company, cache_dir=cache, label_assisted=True,
                                 reference_fingerprint=index.fingerprint)
        warm_start = perf_counter()
        warmed = warm.classify_many(contexts)
        warm_seconds = perf_counter() - warm_start
        included = result.records[result.records.include == 1].to_dict("records")
        api_rows = [row["classification_method"] in ("openai_retrieval", "cache_retrieval") for row in included]
        reproduced = all(not success or (decision is not None and tuple(warm.paths[decision["category_id"]]) ==
                         tuple(row[f"l{i}"] for i in range(1, 5) if row[f"l{i}"])
                         and decision["confidence"] == row["confidence"]
                         and decision["needs_review"] == ("OPENAI_NEEDS_REVIEW" in row["classification_flags"]))
                         for row, success, (decision, _, _) in zip(included, api_rows, warmed, strict=True))
        if warm.stats.get("requests", 0):
            raise AssertionError("Warm verification called the API")
        output = directory / f"{company}.csv"
        write_output(result, output)
        validation = independently_validate(result, output)
        usage = result.diagnostics
        cost = cost_estimate(usage, rates, len(result.records))
        cost["usd_per_1000_input_records"] = cost.pop("usd_per_1000_sample_lines")
        gate_usd, inference_usd = report["preflight"]["cost"]["usd"], cost["usd"]
        report.update(status="measured" if all(api_rows) and reproduced else "partial_api_or_cache",
                      source_rows=len(result.records), included_rows=len(included), api_covered_rows=sum(api_rows),
                      unique_contexts=needed["unique_contexts"], initial_cache_files=initial_cache_files,
                      cache_scope="cold" if initial_cache_files == 0 else "resumed",
                      inference_seconds=inference_seconds, summary=result.summary(), cost=cost,
                      estimated_total_usd_including_gate=str(Decimal(gate_usd) + Decimal(inference_usd)) if gate_usd is not None and inference_usd is not None else None,
                      warm={"seconds": warm_seconds, "usage": dict(warm.stats),
                            "covered_rows": sum(d is not None for d, _, _ in warmed), "successful_decisions_reproduced": reproduced},
                      output=str(output.relative_to(REPO)), output_validation=validation)
    if load_plan(data_dir, root, company)[1] != integrity:
        raise ConfigError("Rehearsal changed during execution")
    report["wall_seconds"] = perf_counter() - started
    report["within_60_minutes"] = report["wall_seconds"] <= 3600
    report["cold_runtime_verified"] = (report.get("cache_scope") == "cold" and report["status"] == "measured"
                                       and report["within_60_minutes"])
    report["inputs_code_index_unchanged"] = True
    if report["status"] == "measured" and not report["within_60_minutes"]:
        report["status"] = "runtime_failed"
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--rehearsal-root", type=Path, default=REPO / "private/rehearsal/v2")
    parser.add_argument("--companies", choices=("A", "B"), nargs="+", default=["A", "B"], help="Companies to prepare")
    parser.add_argument("--company", choices=("A", "B"), default="A", help="Company to run")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=0, help="Explicit paid-run attempt cap from the prepared plan")
    parser.add_argument("--max-tokens", type=int, default=0, help="Explicit conservative allowance from the prepared plan")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--financial-policy-update", action="store_true", help="Prepare a new plan after disclosed config/normalization-only changes")
    args = parser.parse_args()
    try:
        ClassificationConfig(max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers)
        if len(set(args.companies)) != len(args.companies):
            raise ConfigError("Companies must be unique")
        result = (prepare(args.data_dir, args.rehearsal_root, args.companies, financial_policy_update=args.financial_policy_update) if args.action == "prepare" else
                  run(args.data_dir, args.rehearsal_root, args.company, execute=args.execute,
                      max_requests=args.max_requests, max_tokens=args.max_tokens, workers=args.workers))
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("planned", "preview", "measured") else 1


if __name__ == "__main__":
    main()
