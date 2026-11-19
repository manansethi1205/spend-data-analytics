# Financial and date normalization

Stage 6 adds normalization after lossless ingestion. It processes every record,
including records that may later be excluded or matched as duplicates. It does
not decide inclusion, de-duplicate purchases or report a final spend total.

## Usage and results

```powershell
uv run --locked cantill-spend normalize --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend normalize --config configs/company_B.yaml --data-dir "<kit-root>"
```

The CLI prints aggregate JSON quality/provenance counts only. It writes no records,
reads no labels and modifies no source files. Exit 0 means every financial amount
resolved; exit 1 means some amounts remain unresolved; config/source errors exit 2.
Informational date/default flags can coexist with resolved amounts. B currently
exits 1 intentionally because eight financial rows remain unresolved.

Python API:

```python
from cantill.config import load_config
from cantill.ingest import ingest_company
from cantill.normalize import normalize_company

company = ingest_company(load_config(config_path, data_root))
normalized = normalize_company(company)
print(normalized.summary())
```

`normalized.records` retains every canonical field, original string and `raw`
dictionary, and adds parsed values/provenance. Missing/unusable normalized values
are `None`, never fabricated zeros. Inputs are unchanged. `financial_ready` means
the amount can be computed, not that the record is eligible procurement spend.

## Number and tax rules

Sources declare `number_format.decimal` and `thousands`. Parsing validates grouping
before removing separators; it does not guess a locale per row. Dot/comma decimals,
declared grouping, signed values, parentheses for negative values and scientific
notation are supported. A space grouping declaration also accepts nonbreaking
spaces. Nonnumeric/null/nonfinite strings remain unresolved. Grouping declarations
cannot use digits, letters, signs or percent markers.

In particular, B's `1.000` quantities and three-decimal FX values retain their dot
decimal meaning. A tool's comma thousands groups are removed using its declaration.
Optional quantity/unit-cost values are parsed where present; invalid nonblank
values are flagged without blocking an otherwise computable purchase amount.

- `net`: retain the original parsed amount without another tax deduction.
- `gross`: divide by `1 + VAT`. Decimal fractional VAT, whole percentages and
  percent-suffixed strings are accepted. Bare values up to 1 are fractional rates;
  larger bare values or percent-suffixed values are divided by 100. Rates must
  resolve to [0, 1]. Invalid nonblank VAT is not replaced by a default.
- `as_provided`: retain the amount because no separate tax-removal rule is supplied.

A ERP uses net `value_zar` and a configured ZAR currency, preserving differing
document-currency metadata separately. A tool uses gross values and defaults only
blank VAT to the specified 15%; explicit zero remains zero. B is `as_provided`:
there is no B VAT column or supplied additional tax-removal formula.

Decimal calculations use 50 significant digits for division/multiplication and
do not round to cents here. Same-currency amounts and zero-VAT amounts are preserved
exactly without unnecessary division by one. Financial calculations do not use
binary floating point. A final export rounding convention remains a later-stage
decision; no two-decimal rule is attributed to the brief.

## Currency conversion and provenance

Currency codes are trimmed/uppercased for matching and must be three ASCII letters;
original strings remain unchanged. No currency is assumed for a missing field.

1. A reporting-currency line retains its amount and uses identity rate 1, regardless
   of any supplied rate metadata. USD values are not converted again.
2. A non-reporting line with a supplied positive rate uses that rate. The source's
   `rate_convention` defaults to `units_per_reporting` (division), or can explicitly
   be `reporting_per_unit` (multiplication). B declares division explicitly.
3. A non-USD line with a blank rate uses its parsed invoice month to look up the
   configured monthly `units_per_usd` table. That table always requires division,
   independently of any direct line-rate convention, and supports USD reporting.
4. A nonblank invalid/zero/negative line rate, unusable invoice date, missing
   monthly key or invalid monthly rate leaves the amount unresolved. No posting-
   month, nearest-month, inverse-rate or zero-value substitution occurs.

Monthly FX config additionally accepts `number_format` (default dot/no grouping)
and `month_format` (default `%Y-%m`). Invalid reference keys/rates are counted in
`reference_flags`; normalized currency/month collisions fail clearly rather than
selecting an arbitrary rate. Rows using invalid/missing referenced rates are flagged.
Monthly USD tables are rejected for non-USD reporting; no triangulation is invented.

## Date handling and flags

All declared date roles use the configured formats. Missing, invalid and ambiguous
values receive role-specific flags and `None`. If configured formats match distinct
dates, no format is selected silently. Equivalent matches are accepted and the first
matching format is recorded. A tool's explicit day-first declaration resolves its
slash dates; alternate month-first interpretation is not inferred per row.

Parsed dates add `<role>_value` and `<role>_format`; original fields are untouched.
An invalid/missing date blocks financial conversion only when it is needed for
monthly FX. Identity conversion and a positive direct rate do not require an invoice
date. Chronology is audited without repair or automatic exclusion:

- `INVOICE_AFTER_POSTING`
- `INVOICE_POSTING_GAP_OVER_366_DAYS` (diagnostic threshold, not an exclusion rule)
- `DUE_BEFORE_INVOICE`
- `PAID_BEFORE_INVOICE`

A missing paid date is a data flag, not proof of non-approval. Dates outside a
specific reporting year are not automatically rejected; the program embeds no
company-specific year restriction.

## Added financial fields

| Fields | Meaning |
| --- | --- |
| `amount_value`, `quantity_value`, `unit_cost_value` | Parsed original numbers, or `None` |
| `net_amount_value` | Value after configured tax treatment |
| `vat_rate_value`, `vat_source` | Applied fractional rate and `line`/`default`/`not_applicable`/`unresolved` |
| `currency_value` | Matching currency code, or `None` |
| `exchange_rate_value`, `exchange_rate_source` | Applied rate and `identity`/`line`/`monthly_fx`/`unresolved` |
| `exchange_rate_convention`, `fx_month` | Applied direction and month actually used for monthly lookup |
| `reporting_amount_value`, `financial_ready` | Converted value and whether it resolved |
| `quality_flags` | Per-record tuple of explicit quality/provenance codes |

Financial flags include `AMOUNT_MISSING`, `AMOUNT_INVALID`, `VAT_MISSING`,
`VAT_INVALID`, `VAT_DEFAULTED`, `CURRENCY_MISSING`, `CURRENCY_INVALID`,
`LINE_RATE_INVALID`, `FX_RATE_MISSING`, `FX_RATE_INVALID` and
`FX_INVOICE_DATE_UNRESOLVED`. These are audit flags, not submission exclusion codes.
Do not assign `NON_PROCUREMENT` merely because financial data is incomplete.

## Real-data verification and remaining limits

| Company | Input rows | Financially resolved | Unresolved |
| --- | ---: | ---: | ---: |
| A | 65,549 | 65,549 | 0 |
| B | 41,028 | 41,020 | 8 |

A's 6,542 blank VAT rates use the specified default; all other rates parse from
their actual representations. B uses 17,959 identity rates, 19,726 direct rates
and 3,338 monthly rates; five exchange rates remain unresolved. Three additional
records lack amounts. Date flag counts match the independent stage 2 audit:
149 long invoice/posting gaps, 233 invoices after posting, 13 due dates before
invoice and 16 paid dates before invoice.

Reproduce the independent kit-specific audit:

```powershell
uv run --locked python tools/verify_normalization.py --kit-dir "<kit-root>"
```

It checks every computable record against exact rational arithmetic, compares all
mapped dates using an independent parser for the observed kit formats, checks
every original cell/ID and verifies unchanged source hashes. Division error is
bounded relative to 50-digit precision. It does not use golden labels. Detailed
exception IDs stay in ignored `private/normalization/verification.json`.

The normalization milestone passed 222 tests, including prior ingestion, output
and confidentiality checks. Stage 7 has since reviewed the financial exceptions;
all eight remain candidates without supported exclusion evidence. They stay unresolved;
included unresolved amounts cannot become valid numeric submissions without an
explicit supported resolution. Eligibility is now implemented in `ELIGIBILITY.md`;
counting once is implemented in [MATCHING.md](./MATCHING.md). Grouping and
classification have since been implemented. The current
[rehearsal state](./REHEARSAL.md) includes a validated private A fallback output;
final named A/B submission outputs remain pending, and B is financially blocked.
