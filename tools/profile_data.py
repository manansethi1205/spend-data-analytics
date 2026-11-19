"""Read-only kit audit. Detailed reports are confidential and stay in private/.

This is an exploratory profiler, not the production parser or matching engine.
Uses only Python's standard library. Never modifies source files or fits a model.
"""

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path


FILES = {
    "A_erp": ("company_A/erp_goods_receipts.csv", "line_id"),
    "A_tool": ("company_A/invoice_tool_export.csv", "tool_record_id"),
    "A_labels": ("company_A/labels_A.csv", "record_id"),
    "A_tree": ("company_A/taxonomy_A.csv", None),
    "B_lines": ("company_B/invoice_lines.csv", "line_id"),
    "B_fx": ("company_B/fx_rates_usd.csv", None),
    "B_labels": ("company_B/seed_labels.csv", "line_id"),
    "B_tree": ("company_B/taxonomy_B.csv", None),
}
NUMBER_COLUMNS = {
    "A_erp": ["value_zar", "unit_cost_zar", "quantity"],
    "A_tool": ["gross_amount", "vat_rate", "quantity"],
    "B_lines": ["line_amount", "currency_rate", "quantity"],
    "B_fx": ["units_per_usd"],
}
DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
    "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d/%m/%y", "%m/%d/%y",
    "%Y%m%d",
)


def norm(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def number(value):
    """Exploratory locale heuristic; ambiguous single separators are reported."""
    value = value.strip().replace("\u00a0", "").replace(" ", "")
    if not value:
        return None
    sign = -1 if value.startswith("(") and value.endswith(")") else 1
    value = value.strip("()").rstrip("%")
    if "," in value and "." in value:
        decimal = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in value:
        # A trailing three-digit group is ambiguous and must not be treated as proof.
        value = value.replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", value) else value.replace(",", ".")
    try:
        result = Decimal(value) * sign
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


@lru_cache(maxsize=100000)
def date_options(value):
    value = value.strip()
    if not value:
        return []
    found = []
    for fmt in DATE_FORMATS:
        try:
            found.append((fmt, datetime.strptime(value, fmt).date().isoformat()))
        except ValueError:
            pass
    return found


def top(counter, limit=25):
    return dict(counter.most_common(limit))


def groups(rows, columns):
    result = defaultdict(list)
    for row in rows:
        result[tuple(row[c] for c in columns)].append(row)
    return result


def collisions(rows, key_columns, value_column):
    mapping = defaultdict(set)
    for row in rows:
        key = tuple(row[c] for c in key_columns)
        if all(key) and row[value_column]:
            mapping[key].add(row[value_column])
    bad = {str(k): sorted(v) for k, v in mapping.items() if len(v) > 1}
    return {"keys": len(mapping), "multi_value_keys": len(bad), "examples": dict(list(bad.items())[:20])}


def profile(rows, fields, id_col, number_cols):
    result = {"rows": len(rows), "columns": fields,
              "blank": {c: sum(not r[c].strip() for r in rows) for c in fields},
              "distinct": {c: len({r[c] for r in rows}) for c in fields},
              "ragged_rows": sum(None in r or any(v is None for v in r.values()) for r in rows)}
    result["exact_duplicate_rows"] = len(rows) - len({tuple(r[c] for c in fields) for r in rows})
    if id_col:
        ids = Counter(r[id_col] for r in rows)
        result["id"] = {"column": id_col, "blank": ids.get("", 0),
                        "duplicate_excess": sum(n - 1 for n in ids.values()),
                        "examples": top(Counter({k: n for k, n in ids.items() if n > 1}))}
    result["values"] = {c: top(Counter(r[c] for r in rows)) for c in fields
                        if len({r[c] for r in rows}) <= 100}
    result["numbers"] = {}
    for col in number_cols:
        values = [number(r[col]) for r in rows]
        valid = [v for v in values if v is not None]
        invalid = [r[col] for r, v in zip(rows, values) if r[col].strip() and v is None]
        ambiguous = Counter(r[col] for r in rows if re.fullmatch(r"[+-]?\d{1,3}[,.]\d{3}", r[col].strip()))
        result["numbers"][col] = {
            "parsed": len(valid), "invalid_nonblank": len(invalid), "invalid_examples": invalid[:10],
            "negative": sum(v < 0 for v in valid), "zero": sum(v == 0 for v in valid),
            "min": str(min(valid)) if valid else None, "max": str(max(valid)) if valid else None,
            "sum_exploratory": str(sum(valid)), "ambiguous_single_separator_rows": sum(ambiguous.values()),
            "ambiguous_examples": top(ambiguous, 10),
            "shapes": top(Counter(re.sub(r"\d", "9", r[col]) for r in rows)),
        }
    result["dates"] = {}
    for col in [c for c in fields if "date" in c]:
        format_counts, invalid, ambiguous, dates = Counter(), Counter(), Counter(), []
        for row in rows:
            value = row[col]
            options = date_options(value)
            if options:
                format_counts.update([options[0][0]])
                dates.append(options[0][1])
                if len({d for _, d in options}) > 1:
                    ambiguous[value] += 1
            elif value.strip():
                invalid[value] += 1
        result["dates"][col] = {
            "formats_first_match": dict(format_counts), "parsed_nonblank": len(dates),
            "invalid_nonblank": sum(invalid.values()), "invalid_examples": top(invalid),
            "ambiguous_rows": sum(ambiguous.values()), "ambiguous_examples": top(ambiguous, 10),
            "min_first_match": min(dates) if dates else None, "max_first_match": max(dates) if dates else None,
        }
    return result


def labels_a(erp, labels, tree):
    by_id = {r["line_id"]: r for r in erp}
    label_ids = {r["record_id"] for r in labels}
    paths = {tuple(r[f"category_l{i}"] for i in range(1, 4)) for r in tree}
    joined = []
    for label in labels:
        key = label["record_id"].removeprefix("ERP:")
        if key in by_id:
            joined.append({**by_id[key], **label})
    return {
        "joined": len(joined), "label_record_id_examples": sorted(label_ids)[:3],
        "missing_erp_labels": len(erp) - len(joined),
        "out_of_tree": sum(tuple(r[f"category_l{i}"] for i in range(1, 4)) not in paths for r in labels),
        "supplier_name_to_key": collisions(joined, ["supplier_name"], "supplier_key"),
        "vendor_to_key": collisions(joined, ["source_system", "vendor_id"], "supplier_key"),
        "material_to_item": collisions(joined, ["source_system", "material_number"], "item_key"),
        "text_to_category": collisions(joined, ["material_short_text"], "category_l3"),
        "blank_item_by_spend_type": dict(Counter(r["spend_type"] for r in joined if not r["item_key"])),
        "supplier_keys": len({r["supplier_key"] for r in labels}),
        "nonblank_item_keys": len({r["item_key"] for r in labels if r["item_key"]}),
    }


def labels_b(lines, labels, tree):
    by_id = {r["line_id"]: r for r in lines}
    paths = {tuple(r[f"category_l{i}"] for i in range(1, 4)) for r in tree}
    joined = [{**by_id[r["line_id"]], **r} for r in labels if r["line_id"] in by_id]
    crosstabs = {}
    for col in ["source_system", "document_type", "supplier_type", "gl_account_description"]:
        tab = defaultdict(Counter)
        for row in joined:
            tab[row[col]][row["include"] + ":" + row["exclusion_reason"]] += 1
        crosstabs[col] = {k: dict(v) for k, v in tab.items()}
    return {
        "joined": len(joined), "orphan_labels": len(labels) - len(joined),
        "included_out_of_tree": sum(tuple(r[f"category_l{i}"] for i in range(1, 4)) not in paths for r in labels if r["include"] == "1"),
        "excluded_with_categories": sum(any(r[f"category_l{i}"] for i in range(1, 4)) for r in labels if r["include"] == "0"),
        "included_missing_paid_date": sum(r["include"] == "1" and not r["paid_date"] for r in joined),
        "excluded_with_paid_date": sum(r["include"] == "0" and bool(r["paid_date"]) for r in joined),
        "included_blank_description": sum(r["include"] == "1" and not r["line_description"] for r in joined),
        "crosstabs": crosstabs,
        "description_to_category": collisions([r for r in joined if r["include"] == "1"], ["line_description"], "category_l3"),
        "account_to_category": collisions([r for r in joined if r["include"] == "1"], ["source_system", "gl_account"], "category_l3"),
    }


def b_financial(lines, fx):
    rates = groups(fx, ["currency", "month"])
    result = {"duplicate_fx_keys": sum(len(v) > 1 for v in rates.values()),
              "conflicting_fx_keys": sum(len({r["units_per_usd"] for r in v}) > 1 for v in rates.values()),
              "sources": {}, "unresolved_examples": []}
    for source, rows in groups(lines, ["source_system"]).items():
        counts = Counter()
        for r in rows:
            amount, rate = number(r["line_amount"]), number(r["currency_rate"])
            counts["rows"] += 1
            if amount is None:
                counts["missing_or_invalid_amount"] += 1
            if r["currency"] == "USD":
                counts["usd_identity"] += 1
                continue
            if rate is not None and rate > 0:
                counts["positive_line_rate"] += 1
                continue
            counts["needs_fx"] += 1
            options = date_options(r["invoice_date"])
            months = {d[:7] for _, d in options}
            if len(months) != 1:
                counts["ambiguous_or_invalid_invoice_month"] += 1
            else:
                key = (r["currency"], next(iter(months)))
                found = rates.get(key, [])
                if len(found) == 1 and (number(found[0]["units_per_usd"]) or 0) > 0:
                    counts["fx_available_unambiguous_month"] += 1
                else:
                    counts["fx_unavailable"] += 1
                    if len(result["unresolved_examples"]) < 20:
                        result["unresolved_examples"].append({"line_id": r["line_id"], "currency": r["currency"], "invoice_date": r["invoice_date"]})
        result["sources"][source[0]] = dict(counts)
    result["fx_months"] = sorted({r["month"] for r in fx})
    return result


def a_matching(erp, tool):
    candidates = defaultdict(list)
    for row in erp:
        value = number(row["value_zar"])
        if value is not None:
            candidates[(norm(row["po_number"]), value.quantize(Decimal("0.01")))].append(row)
    counts = Counter()
    duplicate_groups = defaultdict(list)
    statuses = Counter()
    for row in tool:
        gross, vat = number(row["gross_amount"]), number(row["vat_rate"])
        if vat is None and not row["vat_rate"].strip():
            vat = Decimal("0.15")
        elif vat is not None and ("%" in row["vat_rate"] or vat > 1):
            vat /= 100
        if gross is None or vat is None or vat == -1:
            counts["unusable_amount_or_vat"] += 1
            continue
        net = (gross / (1 + vat)).quantize(Decimal("0.01"))
        key = (norm(row["po_reference"]), net)
        matches = candidates.get(key, []) if key[0] else []
        counts["tool_rows"] += 1
        counts["blank_po" if not key[0] else "nonblank_po"] += 1
        if matches:
            counts["po_net_candidate_rows"] += 1
            counts["unique_candidate_rows" if len(matches) == 1 else "multiple_candidate_rows"] += 1
            if any(norm(r["supplier_name"]) == norm(row["supplier_name_as_captured"]) for r in matches):
                counts["po_net_exact_normalized_supplier_rows"] += 1
            statuses[row["status"]] += 1
        fingerprint = (norm(row["invoice_number"]), norm(row["supplier_name_as_captured"]),
                       norm(row["po_reference"]), net, row["quantity"], norm(row["line_text"]))
        duplicate_groups[fingerprint].append(row)
    repeated = [v for v in duplicate_groups.values() if len(v) > 1]
    return {"candidate_counts_not_ground_truth": dict(counts), "candidate_statuses": dict(statuses),
            "repeat_fingerprint_groups": len(repeated), "repeat_fingerprint_excess": sum(len(v) - 1 for v in repeated),
            "repeat_groups_with_conflicting_status": sum(len({r["status"] for r in v}) > 1 for v in repeated),
            "repeat_examples": [[r["tool_record_id"] for r in v] for v in repeated[:10]],
            "erp_multi_line_po_groups": sum(len(v) > 1 for v in groups(erp, ["po_number"]).values()),
            "tool_multi_line_invoice_groups": sum(len(v) > 1 for v in groups(tool, ["invoice_number", "supplier_name_as_captured"]).values())}


def further_audit(data):
    """Evidence for open issues; candidate counts never imply confirmed matches."""
    erp, tool, lines = data["A_erp"], data["A_tool"], data["B_lines"]
    lines_by_id = {r["line_id"]: r for r in lines}
    seed = {r["line_id"]: r for r in data["B_labels"]}
    result = {}
    for company in ["A", "B"]:
        tree = data[f"{company}_tree"]
        paths = [tuple(r[f"category_l{i}"] for i in range(1, 4)) for r in tree]
        result[f"{company}_taxonomy"] = {
            "distinct_levels": [len({p[i] for p in paths}) for i in range(3)],
            "duplicate_paths": len(paths) - len(set(paths)),
            "blank_path_rows": sum(any(not v.strip() for v in p) for p in paths),
            "surrounding_whitespace_cells": sum(v != v.strip() for p in paths for v in p),
        }
    result["B_date_relationships"] = {}
    for source, rows in groups(lines, ["source_system"]).items():
        counts = Counter()
        for r in rows:
            inv, post, due = [datetime.fromisoformat(r[c]).date() for c in ["invoice_date", "posting_date", "due_date"]]
            counts["invoice_after_posting"] += inv > post
            counts["invoice_posting_gap_over_366_days"] += abs((inv - post).days) > 366
            counts["due_before_invoice"] += due < inv
            counts["invoice_outside_2024"] += inv.year != 2024
            if r["paid_date"].strip():
                paid = datetime.fromisoformat(r["paid_date"]).date()
                counts["paid_before_invoice"] += paid < inv
        result["B_date_relationships"][source[0]] = dict(counts)
    result["B_missing_amount_rows"] = [
        {**r, "seed": seed.get(r["line_id"])} for r in lines if not r["line_amount"].strip()]
    result["B_description_coverage"] = {
        "blank_description_with_material": sum(not r["line_description"].strip() and bool(r["material_number"].strip()) for r in lines),
        "blank_description_and_material": sum(not r["line_description"].strip() and not r["material_number"].strip() for r in lines),
        "blank_description_material_and_account_text": sum(not any(r[c].strip() for c in ["line_description", "material_number", "gl_account_description"]) for r in lines),
        "non_ascii_description": sum(any(ord(c) > 127 for c in r["line_description"]) for r in lines),
        "included_seed_categories": len({r["category_l3"] for r in seed.values() if r["include"] == "1"}),
        "included_seed_blank_after_strip": sum(r["include"] == "1" and not lines_by_id[r["line_id"]]["line_description"].strip() for r in seed.values()),
    }
    # Scope IDs; shared codes alone cannot prove entity identity across systems.
    result["B_scoped_vendor_count"] = len({(r["source_system"], r["vendor_id"]) for r in lines})
    result["B_scoped_material_count"] = len({(r["source_system"], r["material_number"]) for r in lines if r["material_number"].strip()})
    result["B_signed_amount_by_doc_type"] = {}
    for kind, rows in groups(lines, ["document_type"]).items():
        amounts = [number(r["line_amount"]) for r in rows]
        result["B_signed_amount_by_doc_type"][kind[0]] = {
            "rows": len(rows), "negative": sum(v is not None and v < 0 for v in amounts),
            "zero": sum(v == 0 for v in amounts),
        }
    result["B_whitespace_only"] = {c: sum(bool(r[c]) and not r[c].strip() for r in lines) for c in lines[0]}
    result["A_currency_rows"] = dict(Counter(r["document_currency"] for r in erp))
    result["A_non_zar_currency_value_checks"] = [
        {c: r[c] for c in ["line_id", "document_currency", "value_zar", "quantity", "unit_cost_zar"]}
        for r in erp if r["document_currency"] not in ["", "ZAR"]]
    result["A_tool_date_slash_orientation"] = dict(Counter(
        "dayfirst_only" if int(r["invoice_date"].split("/")[0]) > 12 else
        "monthfirst_only" if int(r["invoice_date"].split("/")[1]) > 12 else "ambiguous_or_equal"
        for r in tool if re.fullmatch(r"\d{2}/\d{2}/\d{4}", r["invoice_date"])))
    fx_keys = {(r["currency"], r["month"]) for r in data["B_fx"]}
    result["B_unavailable_fx_seed_evidence"] = []
    for r in lines:
        if r["currency"] == "USD" or (number(r["currency_rate"]) or 0) > 0:
            continue
        if (r["currency"], r["invoice_date"][:7]) not in fx_keys:
            result["B_unavailable_fx_seed_evidence"].append({
                "line_id": r["line_id"], "seed": seed.get(r["line_id"]),
                "posting_month_fx_exists": (r["currency"], r["posting_date"][:7]) in fx_keys,
            })
    result["B_currency_counts"] = dict(Counter(r["currency"] for r in lines))

    def po(value):
        matches = re.findall(r"(?<!\d)\d{10}(?!\d)", value)
        return matches[0] if len(matches) == 1 else None

    index = defaultdict(list)
    for r in erp:
        index[(po(r["po_number"]), number(r["value_zar"]).quantize(Decimal("0.01")))].append(r)
    counts, statuses, examples = Counter(), Counter(), []
    for r in tool:
        reference = po(r["po_reference"])
        if r["po_reference"].strip() and reference is None:
            counts["nonblank_unrecognized_po"] += 1
        vat = number(r["vat_rate"])
        if vat is None:
            vat = Decimal("0.15")
        elif "%" in r["vat_rate"] or vat > 1:
            vat /= 100
        net = (number(r["gross_amount"]) / (1 + vat)).quantize(Decimal("0.01"))
        matches = index.get((reference, net), []) if reference else []
        if matches:
            counts["po_net_candidate_rows"] += 1
            counts["unique_candidate_rows" if len(matches) == 1 else "multiple_candidate_rows"] += 1
            supplier = [e for e in matches if norm(e["supplier_name"]) == norm(r["supplier_name_as_captured"])]
            counts["po_net_supplier_candidate_rows"] += bool(supplier)
            quantity = [e for e in supplier if number(e["quantity"]) == number(r["quantity"])]
            counts["po_net_supplier_quantity_candidate_rows"] += bool(quantity)
            counts["unique_supplier_quantity_candidate_rows"] += len(quantity) == 1
            statuses[r["status"]] += 1
        if len(matches) > 1 and len(examples) < 10:
            examples.append({"tool_id": r["tool_record_id"], "erp_ids": [e["line_id"] for e in matches]})
    result["A_extracted_po_candidates_not_truth"] = {"counts": dict(counts), "statuses": dict(statuses), "ambiguous_examples": examples}
    result["repeat_purchase_fingerprints_not_truth"] = {}
    for name, id_col in [("A_erp", "line_id"), ("A_tool", "tool_record_id"), ("B_lines", "line_id")]:
        rows = data[name]
        columns = [c for c in rows[0] if c != id_col]
        count = Counter(tuple(r[c] for c in columns) for r in rows)
        result["repeat_purchase_fingerprints_not_truth"][name] = {
            "identical_except_record_id_groups": sum(n > 1 for n in count.values()),
            "identical_except_record_id_excess": sum(n - 1 for n in count.values()),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "private" / "profiling"
    destination.mkdir(parents=True, exist_ok=True)
    data, report, hashes = {}, {"warning": "CONFIDENTIAL LOCAL DIAGNOSTICS; NOT A PRODUCTION PIPELINE"}, {}
    for name, (relative, id_col) in FILES.items():
        path = args.kit_dir / relative
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows, fields = list(reader), reader.fieldnames
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError(f"Ragged CSV rows in {relative}; inspect before profiling")
        data[name] = rows
        report[name] = profile(rows, fields, id_col, NUMBER_COLUMNS.get(name, []))
    report["A_label_audit"] = labels_a(data["A_erp"], data["A_labels"], data["A_tree"])
    report["B_label_audit"] = labels_b(data["B_lines"], data["B_labels"], data["B_tree"])
    report["B_financial_audit"] = b_financial(data["B_lines"], data["B_fx"])
    report["A_matching_audit"] = a_matching(data["A_erp"], data["A_tool"])
    report["further_audit"] = further_audit(data)
    report["B_vendor_across_systems"] = collisions(data["B_lines"], ["vendor_id"], "source_system")
    report["B_material_across_systems"] = collisions(data["B_lines"], ["material_number"], "source_system")
    report["B_date_by_source"] = {
        source[0]: {col: {"formats": dict(Counter(date_options(r[col])[0][0] for r in rows if date_options(r[col]))),
                         "invalid_nonblank": sum(bool(r[col]) and not date_options(r[col]) for r in rows)}
                    for col in ["invoice_date", "posting_date", "paid_date"]}
        for source, rows in groups(data["B_lines"], ["source_system"]).items()
    }
    for relative, digest in hashes.items():
        assert hashlib.sha256((args.kit_dir / relative).read_bytes()).hexdigest() == digest, "Source changed during audit"
    report["source_sha256"] = hashes
    output = destination / "profile.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Profiled {len(FILES)} files; source hashes unchanged. Confidential report: {output}")


if __name__ == "__main__":
    main()
