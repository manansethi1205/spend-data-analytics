# Data profile and implementation mappings

## Scope and reproduction

Stage 2 audited all eight supplied CSVs using Python's standard library. Sources
were read with UTF-8 BOM support and never modified. SHA-256 hashes before and
after the run matched. Detailed values, record examples, source hashes and
cross-tabs are deliberately confined to ignored `private/profiling/profile.json`.
This document contains aggregate findings and schema mappings, not raw records.

Reproduce from the repository root:

```powershell
python -B tools/profile_data.py --kit-dir "<path-to-Cantill_DataML_Task_Kit>"
```

The profiler is an exploratory audit, not production financial parsing, matching,
classification, a benchmark, or a submission command. Number/date interpretations
are labelled exploratory where ambiguity exists. The source file names are the
same as those provided with the kit.

## Inventory and structural integrity

| File | Rows | Columns | Record key / relationship |
| --- | ---: | ---: | --- |
| A ERP receipts | 37,029 | 26 | `line_id`; unique and nonblank |
| A tool export | 28,520 | 11 | `tool_record_id`; unique and nonblank |
| A labels | 37,029 | 6 | `record_id`; unique; joins every ERP row using `ERP:` prefix |
| A taxonomy | 40 | 3 | Unique full three-level paths |
| B invoices | 41,028 | 28 | `line_id`; unique and nonblank |
| B monthly FX | 683 | 3 | Unique `(currency, month)` |
| B seed labels | 3,000 | 6 | `line_id`; unique; all join B invoices |
| B taxonomy | 40 | 3 | Unique full three-level paths |

All files have consistent CSV row widths and no exact duplicate rows including
their IDs. The expected output sizes are **65,549 rows for A** and **41,028 for B**,
before any exclusions: excluded records must remain in the output.

A taxonomy has 5/24/40 distinct categories at L1/L2/L3; B has 9/25/40.
Both have no blank path cells, duplicate paths or surrounding path whitespace.
Every A label and every included B seed label has a valid tree path. The current
trees do not exercise L4; synthetic four-level coverage remains necessary.

## A: missingness and financial/date findings

| Observation | Count | Consequence |
| --- | ---: | --- |
| Missing ERP posting date | 24,370 | Dates cannot be a mandatory matching prerequisite |
| Missing ERP vendor ID | 24,370 | Supplier-name resolution is necessary |
| Missing ERP material number | 15,816 | Item resolution cannot depend solely on material codes |
| Missing ERP service text | 36,442 | Use service text only where available |
| Missing ERP cost centre | 31,756 | Context is optional, not universal |
| Missing tool invoice date | 18,660 | Keep explicit missing-date flags |
| Missing tool PO reference | 5,199 | PO-only matching cannot recover every overlapping purchase |
| Missing tool VAT rate | 6,542 | Apply the brief's 15% default |
| Explicit zero tool VAT rate | 1,580 | Preserve zero; it is not missing |
| Negative ERP values | 434 | Do not classify every negative value as non-procurement |
| Negative tool gross amounts | 321 | Preserve signs through VAT normalization |

All ERP values and tool gross amounts are numerically parseable under the observed
conventions. ERP uses dot decimals; tool amounts also use comma thousands groups.
No ambiguous single separator was observed in these amount columns.

Observed VAT representations are `0.15`, `15%`, `15`, zero and blank. Treat them
as rate representations, not as interchangeable literal divisors.

All 12,659 nonblank ERP dates are ISO dates. All 9,860 nonblank tool dates parse
as ISO, day/month/year, or day-abbreviated-month-two-digit-year. Among slash dates,
2,050 require day-first interpretation and none requires month-first. Another
1,195 rows have different valid day-first/month-first interpretations. Configure
day-first for this source and retain the originals; do not infer orientation
independently per row.

All tool currencies are ZAR. ERP document metadata contains 16 non-ZAR codes and
15,816 blank currency values, but the brief explicitly defines `value_zar` as net
ZAR. No independent FX conversion is justified for this already-reporting field.

## A: matching and entity evidence

- 5,323 ERP PO groups contain multiple rows; 3,170 tool invoice/supplier groups
  contain multiple rows. Invoice/PO identity is not line identity.
- Simple alphanumeric PO cleanup plus exact net cents finds candidates for
  4,250 tool rows. Extracting the single observed ten-digit PO token, including
  from prefixed and line-suffixed references, raises this to 16,743 rows.
- Of those 16,743 rows, 2,405 have multiple ERP candidates. Adding exact
  normalized supplier and quantity evidence leaves a unique ERP candidate for
  13,570 tool rows. These are retrieval diagnostics, **not confirmed matches,
  duplicate counts, recall estimates, or final exclusion decisions**.
- The extraction is a source-specific exploratory hypothesis. Production config
  must describe reference normalization; C cannot be assumed to use ten-digit POs.
- Candidate statuses include disallowed statuses, so matching cannot override
  status eligibility or its documented precedence.
- 49 tool groups are identical in every column except record ID, with 50 excess
  rows. A broader normalized purchase fingerprint finds 319 groups/363 excess
  rows, but may also collapse legitimate repeated purchase lines.
- ERP has no rows identical in every column except record ID. This does not prove
  all ERP purchases are unique under alternative representations.

All A golden supplier keys are present. There are 193 distinct observed supplier
names and 70 golden suppliers. An exact name maps consistently to one golden
supplier in this dataset. All 97 nonblank `(source_system, vendor_id)` combinations
also map consistently. These full-data checks are descriptive; do not export the
resulting golden mappings into the labels-hidden inference route.

There are 21,213 nonblank golden item labels representing 2,426 keys. The 15,816
missing item labels occur in free-text, service and catalogue rows. Evaluate item
resolution only where ground truth exists and report the excluded coverage.
All 3,142 labelled source/material combinations map consistently to an item key.
However, 282 of 4,336 exact material-description strings span multiple L3 labels.
Text identity alone cannot establish category identity.

## B: amounts, currencies and date integrity

| Financial route | Rows |
| --- | ---: |
| USD: preserve amount | 17,959 |
| Non-USD: positive supplied line rate | 19,726 |
| Non-USD: needs monthly FX | 3,343 |
| Monthly FX available for invoice month | 3,338 |
| Monthly FX unavailable for invoice month | 5 |

These routes partition the 41,028 records; missing amount is a separate flag.
There are 25 currencies. FX keys are unique and all supplied line/FX rates are
positive and numerically parseable. Amounts use dot decimals; three amounts are
blank, 833 are negative, and 918 are zero. Do not sum mixed original currencies
and describe that result as total spend.

The three blank amounts are not seed-labelled and have no direct unit-cost field
from which to reconstruct an amount. The five unavailable FX cases have invoice
months outside available currency/month coverage and are not seed-labelled.
Posting-month rates exist for those five, but substituting them would depart
from the specified invoice-month rule. These policies remain explicit open
decisions; the audit has not silently imputed a value or excluded a row.

All nonblank B dates are syntactically valid ISO dates. That does not establish
business validity:

- 1,719 invoice dates are outside 2024.
- 149 invoice/posting gaps exceed 366 days.
- 233 invoices are dated after posting, 13 due dates precede their invoice date,
  and 16 paid dates precede their invoice date.

These flags overlap and are not automatically errors or exclusions. Keep the
original invoice month for prescribed FX unless a justified exception is recorded.
There are 10,322 missing paid dates. Neither a missing paid date nor a document
type alone proves approval/cancellation status.

## B: descriptions, identifiers, repeated records and labels

- 16,695 descriptions are blank after trimming, including 9,838 whitespace-only
  values. There are also 3,159 whitespace-only supplier-type values.
- Of the blank descriptions, 12,525 have material numbers and 4,170 do not.
  Every row has at least one of description, material number or account text,
  but account text may be an accounting abbreviation rather than item evidence.
- 1,026 descriptions contain non-ASCII characters; this measures character
  coverage, not language detection or translation quality.
- Vendor IDs comprise 3,995 raw values and 4,072 source-scoped values; 74 raw
  values occur in multiple systems. Nine material codes occur in multiple systems.
  Collisions do not establish either shared identity or distinct identity.
- 453 groups are identical in every field except `line_id`, with 613 excess rows.
  These deserve duplicate review. Unique source IDs alone do not prove unique
  real purchases, but identical fields alone do not prove accidental duplication.

B seeds contain 2,550 included and 450 non-procurement records. Excluded seed
categories are blank. They cover 39 of 40 L3 categories among included examples.
Their coverage is selective:

- No included seed example has a blank description after trimming.
- Two source systems have only excluded seed examples.
- 617 included seed records have no paid date; 412 excluded seeds have a paid date.
- 21 of 28 source/account combinations represented in included labels contain
  multiple categories. Account-only category mapping is insufficient.
- No contradictory L3 labels were found for identical nonblank descriptions
  within the included seed sample. This does not certify the analyst labels as
  correct or representative.

Full-label descriptive aggregates were inspected during profiling. No model,
learned mapping or tuned exclusion rule was produced. Define grouped development
and evaluation splits before fitting; disclose that development data has already
been explored and reserve the actual blind test as independent evidence.

## Proposed semantic mappings for config implementation

These mappings are evidenced by the schema and brief and are now implemented in
the stage 4 A/B configs. Keep source fields available even when not used initially.

| Semantic role | A ERP | A tool | B invoices |
| --- | --- | --- | --- |
| Output identity | `ERP:` + `line_id` | `TOOL:` + `tool_record_id` | `line_id` |
| Source identity | `source_system` | Configured file identity | `source_system` |
| Invoice identity | Unavailable | `invoice_number` | `invoice_number`, `invoice_line` |
| PO identity | `po_number`, `po_item` | Parsed `po_reference`, preserving original | `po_number`, `po_line` |
| Receipt identity | `receipt_document`, `receipt_item` | Unavailable | Unavailable |
| Date fields | `posting_date` | `invoice_date` | `invoice_date`, `posting_date`, `due_date`, `paid_date` |
| Primary amount | `value_zar`, net ZAR | `gross_amount`, gross | `line_amount`; tax semantics beyond supplied brief need explicit configuration |
| Tax | Already net | `vat_rate`, blank default 15% | No explicit VAT column |
| Currency/rate | Reporting ZAR; preserve `document_currency` as metadata | `currency`, ZAR | `currency`, `currency_rate`; monthly FX join on invoice month |
| Supplier | `vendor_id`, `supplier_name`, source scope | `supplier_name_as_captured` | `vendor_id`, source scope; `supplier_type` is context |
| Item | `material_number`, `material_short_text`, optional `service_short_text` | `line_text` | `material_number`, `line_description` |
| Quantity/unit | `quantity`, `uom`, `po_uom`, `unit_cost_zar` | `quantity`; no unit column | `quantity`; no unit column |
| Explicit status | Unavailable | `status` | Unavailable; `document_type` is not automatically status |
| Accounting/context | `material_type`, `spend_type`, `cost_centre`, `opex_capex` | Available invoice fields | `gl_account`, `gl_account_description`, `cost_centre`, `company_code`, `document_type` |
| Site/other context | `site_code`, `site_name`, `contract_status`, `contract_number` | Unavailable | `region`, `plant`, `po_type`, `payment_terms`, `transport_flag` |

Reference mappings:

- A label join: label `record_id` = `ERP:` + ERP `line_id`; no positional joins.
- B label join: exact `line_id`.
- Taxonomy: `category_l1`/`category_l2`/`category_l3` form complete allowed paths.
- B FX: `(currency, invoice month)` joins `(currency, month)` and reads
  `units_per_usd`; non-USD amount is divided by the rate.

## Exit status

All supplied files have been structurally profiled, reference joins verified,
and the 13 requirements questions have evidence or explicit limits in
`DECISIONS.md`. Stage 2 is complete as an audit. It does not claim the unresolved
financial, duplicate, approval or output policies have been implemented or verified.

Stage 4 configuration-driven ingestion is complete and verified losslessly on
both companies; see `README.md` and `configs/README.md`. Stage 5 output contract
validation and stage 6 financial/date normalization are complete; see
`NORMALIZATION.md`. Stage 7 eligibility is implemented in `ELIGIBILITY.md`;
stage 8 matching is implemented in `MATCHING.md`, and entity resolution is next.
Status-absent exports remain a documented
limitation, and the eight financial exceptions remain unresolved candidates.
