"""Label-free supplier candidates, then private A golden-key tuning and B scope audit."""

import argparse
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
import re

from cantill.config import EntityResolutionConfig, load_config
from cantill.eligibility import assess_eligibility
from cantill.entities import resolve_entities
from cantill.ingest import ingest_company, read_table
from cantill.matching import count_purchases, similarity
from cantill.metrics import grouping_metrics
from cantill.normalize import normalize_company


ROOT = Path(__file__).resolve().parents[1]
GRID = ((.94, .8), (.94, .85), (.94, .9), (.94, 1.0), (.92, .8), (.90, .8))


def legacy_clusters(names, *unused):
    blocks, result = defaultdict(list), []
    for name in sorted(names):
        blocks[name[:3]].append(name)
    for block in blocks.values():
        clusters = []
        for name in block:
            candidates = [c for c in clusters if len(block) <= 200 and len(name) >= 8 and all(
                len(other) >= 8 and re.findall(r"\d+", name) == re.findall(r"\d+", other)
                and similarity(name, other) >= .94 for other in c)]
            if len(candidates) == 1:
                candidates[0].append(name)
            else:
                clusters.append([name])
        result.extend(clusters)
    return result


def deny_labels(base, table, role):
    if role == "labels":
        raise AssertionError("Supplier inference opened golden labels")
    return read_table(base, table, role)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "private/supplier_tuning/v1")
    args = parser.parse_args()
    destination = args.report_dir.resolve()
    if not destination.is_relative_to((ROOT / "private").resolve()) or destination.exists():
        parser.error("Choose a new directory under ignored private/")
    inputs = {str(p.resolve()): sha256(p.read_bytes()).hexdigest() for p in args.data_dir.glob("company_*/*.csv")}
    code = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in (ROOT / "src/cantill").glob("*.py")}
    config = load_config(ROOT / "configs/company_A.yaml", args.data_dir)
    started = perf_counter()
    predictions = {}
    with patch("cantill.ingest.read_table", deny_labels):
        matched = count_purchases(assess_eligibility(normalize_company(ingest_company(replace(config, labels=None)))))
        with patch("cantill.entities.supplier_name_clusters", legacy_clusters):
            predictions["legacy"] = resolve_entities(matched).records.set_index("record_id")[["supplier_key", "item_key"]]
        for sequence, jaccard in GRID:
            name = f"sequence_{sequence}_jaccard_{jaccard}"
            normalized = matched.eligible.normalized
            normalized.ingested.config = replace(config, entity_resolution=EntityResolutionConfig(sequence, jaccard))
            predictions[name] = resolve_entities(matched).records.set_index("record_id")[["supplier_key", "item_key"]]
        normalized.ingested.config = config
    # Every candidate partition is fixed before opening golden values.
    labels = ingest_company(config, load_labels=True).labels.set_index("record_id")
    evaluation = {}
    audit_mask = labels.supplier_key.map(lambda value: int(sha256(value.encode()).hexdigest()[:8], 16) % 5 == 0)
    for name, prediction in predictions.items():
        evaluation[name] = {}
        for field in ("supplier_key", "item_key"):
            evaluation[name][field] = grouping_metrics(prediction.loc[labels.index, field], labels[field])
        for split, mask in (("development", ~audit_mask), ("supplier_disjoint_audit", audit_mask)):
            subset = labels.loc[mask]
            evaluation[name][split] = grouping_metrics(prediction.loc[subset.index, "supplier_key"], subset.supplier_key)
    eligible = [name for name in evaluation if name != "legacy" and
                (evaluation[name]["development"]["pair_precision"] or 0) >= .99]
    selected = max(eligible, key=lambda name: (evaluation[name]["development"]["pair_recall"],
                                               evaluation[name]["development"]["pair_precision"], -list(evaluation).index(name))) if eligible else "legacy"
    b_config = load_config(ROOT / "configs/company_B.yaml", args.data_dir)
    b = ingest_company(replace(b_config, labels=None)).records
    known = b.loc[b.supplier_id.str.strip().ne("")]
    erps = known.groupby("supplier_id").source_system.nunique()
    b_labels = ingest_company(b_config, load_labels=True).labels
    b_scope = {"source_systems": int(b.source_system.nunique()), "unique_vendor_ids": int(known.supplier_id.nunique()),
               "vendor_ids_reused_across_erps": int((erps > 1).sum()),
               "rows_with_supplier_names": int(b.supplier_name.str.strip().ne("").sum()),
               "golden_supplier_keys_available": "supplier_key" in b_labels.columns,
               "decision": "Retain ERP scope: code reuse and category labels do not establish cross-ERP supplier identity"}
    assert inputs == {p: sha256(Path(p).read_bytes()).hexdigest() for p in inputs}
    assert code == {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in code}
    report = {"status": "development_tuning_complete", "api_requests": 0, "seconds": perf_counter() - started,
              "all_inference_preceded_labels": True, "source_hashes_unchanged": True,
              "source_code_hashes": code, "metrics": evaluation, "selected_on_development": selected,
              "B_scope_audit": b_scope,
              "limits": "A labels used for threshold selection; full-A metrics are development evidence. Audit suppliers are golden-key disjoint, but cross-split false merges require full-set pair precision inspection. No entity-specific alias table enters inference. B seed labels provide no supplier identity truth."}
    destination.mkdir(parents=True)
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, prediction in predictions.items():
        prediction.to_json(destination / f"{name}.json", orient="index")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
