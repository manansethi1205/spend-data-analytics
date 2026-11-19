# Submission output validation

Stage 5 checks the file contract before later processing stages generate actual
submission outputs. It is read-only and does not repair a CSV, infer categories,
calculate tax/FX, decide procurement eligibility or create submission files.

## Command and Python API

```powershell
uv run --locked cantill-spend validate-output --config configs/company_A.yaml --data-dir "<kit-root>" --output "<candidate.csv>"
```

Use B's config for B outputs and the future C config for C. Configured sources
supply the exact expected record IDs; the runtime tree supplies valid paths.
Labels are never loaded by this command. All input/source files remain unchanged.

Exit status is 0 for a valid file, 1 for output validation failure (including an
unreadable output), and 2 for a config/source-ingestion or CLI-argument failure.
JSON reports contain counts and at most 20 error examples with one-based data-row
ordinals. They do not contain record IDs, entity names, categories or cell values.

The Python API is:

```python
from cantill.output import validate_output

result = validate_output(output_path, company.records["record_id"], company.taxonomy)
if not result.valid:
    print(result.summary())
```

`company` is the `IngestedCompany` returned by shared ingestion. Check `valid`
before consuming totals. `summary()` exposes `total_spend` only when the entire
file passes; otherwise that field is null. The total uses exact decimal addition,
independent of the process decimal precision, without rounding monetary cells.

## Enforced contract

The header must match this exact order, without missing, extra or duplicate columns:

```text
record_id,include,exclusion_reason,supplier_key,item_key,spend,l1,l2,l3,l4,confidence
```

| Area | Enforced check |
| --- | --- |
| CSV | UTF-8/BOM-compatible comma CSV; consistent widths, valid quoting and exact header |
| Coverage | Exact multiset equality against source-derived IDs; no missing/excess occurrences, blank IDs or duplicates |
| Record order | Any order is accepted; output identity must match exactly, including prefixes/leading zeros |
| Inclusion | Exactly `1` or `0`; an included record's exclusion reason is exactly blank |
| Exclusions | An excluded record has one of `CANCELLED`, `NOT_APPROVED`, `NON_PROCUREMENT`, `DUPLICATE` and numeric zero spend |
| Entity keys | Included records require nonblank supplier/item keys; excluded keys may be blank or populated, but whitespace-only keys fail |
| Spend | Finite numeric amount; signs and included zero values are permitted |
| Categories | Included records require a complete runtime terminal path with exact names and blank unused levels |
| Excluded categories | Entirely blank or a complete valid terminal path; partial/invalid populated paths fail |
| Confidence | A finite number in [0, 1] on every record, including excluded records |

Numbers accept dot-decimal and scientific notation, optional signs and surrounding
whitespace. Grouping separators, decimal commas, underscores, blank numbers,
NaN/infinity and other nonnumeric tokens fail. Input financial locale parsing is
a separate stage: do not copy localized raw amount strings into submission spend.

Terminal validation works with one to four levels and variable-depth leaves.
If a parent path is explicitly listed alongside descendants, the parent is not
accepted as the lowest-level category. Matching names individually across columns
does not establish a valid joint path. Names and IDs are never silently trimmed.

Header-only output is valid only when the configured purchase sources contain
zero records. Excluded records still count toward full source coverage. A correct
row count alone cannot hide a missing record replaced by a repeated one.

## Excluded-row convention and its scope

The brief requires classification of included records. Its example shows an
excluded duplicate with keys, blank categories and confidence. It does not fully
specify every excluded-row field. Accordingly, this validator permits blank or
supported keys and either blank or valid full category paths on excluded rows.
It does not demand fabricated entity groups or classifications to fill cells.

Our planned exporter convention is blank excluded categories, supported entity
keys where available, and exclusion-decision confidence (0 if unassessed). Included
confidence will describe classification confidence. This is a documented project
choice, not an additional task rule. The exporter and confidence estimation do
not exist yet; exclusion precedence remains a stage 7/8 decision.

## Diagnostics and verification limits

Common error groups:

| Error codes | Meaning |
| --- | --- |
| `HEADER_MISMATCH`, `CSV_ROW_WIDTH`, `CSV_READ_ERROR` | File cannot satisfy the CSV structure |
| `BLANK_RECORD_ID`, `DUPLICATE_RECORD_ID`, `MISSING_RECORDS`, `EXTRA_RECORDS` | Identity/coverage failure; excess includes duplicate occurrences |
| `INVALID_INCLUDE`, `INCLUDED_EXCLUSION_REASON`, `EXCLUDED_REASON_INVALID` | Inclusion/reason inconsistency |
| `INVALID_SPEND`, `EXCLUDED_SPEND_NONZERO`, `INVALID_CONFIDENCE` | Numeric or financial-contract failure |
| `SUPPLIER_KEY_REQUIRED`, `ITEM_KEY_REQUIRED`, `WHITESPACE_ENTITY_KEY` | Missing/empty grouping keys |
| `CATEGORY_REQUIRED`, `INVALID_CATEGORY_PATH` | Missing classification or invalid/incomplete terminal path |
| `INVALID_EXPECTED_IDS`, `INVALID_TAXONOMY` | Invalid reference arguments supplied to the Python API |

Structural failures may stop further CSV inspection. Row-level errors otherwise
accumulate; bounded examples do not truncate aggregate error counts. Error counts
are not a count of distinct bad records: one row may violate several checks.

Passing this validator establishes structural consistency, not correct tax/FX,
deduplication, eligibility, entity grouping, category predictions or confidence
calibration. Those require processing and evaluation in later stages. It does not
enforce the candidate's filename, Git confidentiality or submission deadlines;
those are separate release checks. No actual A/B spend outputs have been produced.
