"""Command-line entry point; pipeline commands arrive with their implementation."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from cantill import __version__
from cantill.config import ClassificationConfig, ConfigError, load_config
from cantill.ingest import ingest_company
from cantill.output import validate_output
from cantill.normalize import normalize_company
from cantill.eligibility import assess_eligibility
from cantill.matching import count_purchases
from cantill.entities import resolve_entities
from cantill.pipeline import run_company, write_output


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cantill-spend",
        description="Configuration-driven spend pipeline with local or bounded OpenAI classification.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    ingest = commands.add_parser("ingest", help="Validate and ingest a company; print aggregate counts only")
    ingest.add_argument("--config", type=Path, required=True)
    ingest.add_argument("--data-dir", type=Path, help="Root for relative input paths; defaults to config directory")
    ingest.add_argument("--with-labels", action="store_true", help="Explicitly load separate development labels")
    validate = commands.add_parser("validate-output", help="Check a submission CSV against source IDs and runtime taxonomy")
    validate.add_argument("--config", type=Path, required=True)
    validate.add_argument("--data-dir", type=Path, help="Root for relative input paths; defaults to config directory")
    validate.add_argument("--output", type=Path, required=True, help="Existing submission CSV to validate, read-only")
    normalize = commands.add_parser("normalize", help="Normalize financial/date values; print aggregate quality counts")
    normalize.add_argument("--config", type=Path, required=True)
    normalize.add_argument("--data-dir", type=Path, help="Root for relative input paths; defaults to config directory")
    eligibility = commands.add_parser("eligibility", help="Assess procurement candidates; print aggregate evidence counts")
    eligibility.add_argument("--config", type=Path, required=True)
    eligibility.add_argument("--data-dir", type=Path, help="Root for relative input paths; defaults to config directory")
    deduplicate = commands.add_parser("deduplicate", help="Count purchases once; print aggregate match/quality counts")
    deduplicate.add_argument("--config", type=Path, required=True)
    deduplicate.add_argument("--data-dir", type=Path, help="Root for relative input paths; defaults to config directory")
    resolve = commands.add_parser("resolve", help="Resolve supplier/item groups without labels; print aggregate counts")
    resolve.add_argument("--config", type=Path, required=True)
    resolve.add_argument("--data-dir", type=Path)
    run = commands.add_parser("run", help="Run the label-free baseline; optionally write validated output")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--data-dir", type=Path)
    run.add_argument("--output", type=Path, help="Write only if every included financial value is resolved")
    run.add_argument("--classifier", choices=("local", "openai", "auto"))
    run.add_argument("--model", help="OpenAI model ID; overrides company classification config")
    run.add_argument("--llm-max-requests", type=int, help="Maximum API attempts, including retries")
    run.add_argument("--llm-max-tokens", type=int, help="Conservative application token allowance, including retries")
    run.add_argument("--llm-workers", type=int)
    run.add_argument("--retrieval-index", type=Path, help="Opt in to a private company/tree-specific labelled index; omit for zero-label inference")
    run.add_argument("--zero-label-strategy", choices=("flat", "hierarchical", "shortlist"))
    run.add_argument("--shortlist-size", type=int)
    run.add_argument("--no-supplier-context", dest="include_supplier_context", action="store_false", default=None)
    run.add_argument("--confidence-mode", choices=("raw", "blended"))
    smoke = commands.add_parser("check-openai", help="Make one synthetic API classification request; no company data")
    smoke.add_argument("--model", default=ClassificationConfig().model)
    args = parser.parse_args()
    if args.command == "check-openai":
        from cantill.llm import OpenAIClassifier
        try:
            backend = OpenAIClassifier((("Goods", "Fasteners"), ("Services", "Cleaning")),
                                       ClassificationConfig(mode="openai", model=args.model, retries=0,
                                                            max_requests=1, max_tokens=64000),
                                       company_id="synthetic-smoke")
            # A fresh synthetic context makes this a live credentials/model check.
            from uuid import uuid4
            context = {"description": "Steel hexagonal bolts M12 for machine maintenance", "service_text": "",
                       "account_description": "", "material_type": "", "unit": "EA", "po_unit": str(uuid4())}
            result, method, flag = backend.classify_many([context])[0]
        except ConfigError as exc:
            parser.exit(2, f"error: {exc}\n")
        print(json.dumps({"success": result is not None, "method": method, "flag": flag,
                          "model": args.model, "usage": dict(backend.stats)}, indent=2))
        return 0 if result is not None else 1
    if args.command == "run":
        try:
            config = load_config(args.config, args.data_dir)
            overrides = {key: value for key, value in {
                "mode": args.classifier, "model": args.model, "max_requests": args.llm_max_requests,
                "max_tokens": args.llm_max_tokens, "workers": args.llm_workers}.items() if value is not None}
            overrides.update({key: value for key, value in {
                "zero_label_strategy": args.zero_label_strategy, "shortlist_size": args.shortlist_size,
                "include_supplier_context": args.include_supplier_context,
                "confidence_mode": args.confidence_mode}.items() if value is not None})
            result = run_company(config, classification=replace(config.classification, **overrides),
                                 retrieval_index=args.retrieval_index)
            if args.output:
                write_output(result, args.output)
        except (ConfigError, OSError) as exc:
            parser.exit(2, f"error: {exc}\n")
        summary = result.summary()
        print(json.dumps(summary, indent=2))
        return 0 if summary["included_unresolved_financial_rows"] == 0 else 1
    if args.command in ("ingest", "validate-output", "normalize", "eligibility", "deduplicate", "resolve"):
        try:
            company = ingest_company(load_config(args.config, args.data_dir), load_labels=getattr(args, "with_labels", False))
            normalized = normalize_company(company) if args.command in ("normalize", "eligibility", "deduplicate", "resolve") else None
            eligible = assess_eligibility(normalized) if args.command in ("eligibility", "deduplicate", "resolve") else None
            matched = count_purchases(eligible) if args.command in ("deduplicate", "resolve") else None
            resolved = resolve_entities(matched) if args.command == "resolve" else None
        except ConfigError as exc:
            parser.exit(2, f"error: {exc}\n")
        if args.command == "validate-output":
            result = validate_output(args.output, company.records["record_id"], company.taxonomy)
            print(json.dumps(result.summary(), indent=2))
            return 0 if result.valid else 1
        if args.command == "normalize":
            summary = normalized.summary()
            print(json.dumps(summary, indent=2))
            return 0 if summary["all_amounts_resolved"] else 1
        if args.command == "eligibility":
            summary = eligible.summary()
            print(json.dumps(summary, indent=2))
            return 0 if summary["eligible_unresolved_financial_rows"] == 0 else 1
        if args.command in ("deduplicate", "resolve"):
            summary = (resolved if resolved is not None else matched).summary()
            print(json.dumps(summary, indent=2))
            return 0 if summary["included_unresolved_financial_rows"] == 0 else 1
        print(json.dumps(company.summary(), indent=2))
    else:
        parser.print_help()
    return 0
