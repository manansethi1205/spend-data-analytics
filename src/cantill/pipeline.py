"""Configured spend pipeline; labelled retrieval requires an explicit artifact."""

import csv
import os
from pathlib import Path
import tempfile

from cantill.classify import classify_company
from cantill.config import ConfigError
from cantill.eligibility import assess_eligibility
from cantill.entities import resolve_entities
from cantill.ingest import ingest_company
from cantill.matching import count_purchases
from cantill.normalize import normalize_company
from cantill.output import OUTPUT_COLUMNS, validate_output


def run_company(config, *, classification=None, retrieval_index=None, supplier_crosswalk=None):
    # Labels are never loaded, including when a label path exists in the config.
    normalized = normalize_company(ingest_company(config))
    matched = count_purchases(assess_eligibility(normalized))
    crosswalk = None
    if supplier_crosswalk is not None:
        from cantill.supplier_crosswalk import SupplierCrosswalk
        crosswalk = SupplierCrosswalk.load(supplier_crosswalk, company_id=config.company_id)
    resolved = resolve_entities(matched, supplier_crosswalk=crosswalk)
    retrieval = None
    if retrieval_index is not None:
        from cantill.retrieval import RetrievalIndex
        retrieval = RetrievalIndex.load(retrieval_index, company_id=config.company_id,
                                        taxonomy=normalized.ingested.taxonomy)
    return classify_company(resolved, options=classification, retrieval=retrieval)


def write_output(company, path):
    """Validate a temporary file before atomically replacing the chosen output."""
    records = company.records
    if ((records["include"] == 1) & ~records["financial_ready"].astype(bool)).any():
        raise ConfigError("output: included records have unresolved financial values; no file written")
    path = Path(path)
    config = company.resolved.matched.eligible.normalized.ingested.config
    # A mistaken --output must not overwrite a configured source or reference.
    inputs = [source.table.path for source in config.sources] + [config.taxonomy.path]
    inputs += [table.path for table in (config.fx, config.labels) if table is not None]
    if path.resolve() in {(config.base_dir / item).resolve() for item in inputs}:
        raise ConfigError("output: destination conflicts with a configured input")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for row in records.to_dict("records"):
                output = {column: row[column] for column in OUTPUT_COLUMNS if column != "spend"}
                output["spend"] = str(row["spend_value"])
                writer.writerow(output)
        ingested = company.resolved.matched.eligible.normalized.ingested
        result = validate_output(temporary, ingested.records["record_id"], ingested.taxonomy)
        if not result.valid:
            raise ConfigError("output: generated baseline failed validation")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
