# Company configuration

An optional `classification` section configures local/OpenAI/auto mode, model,
concurrency and request/token/retry limits. Defaults remain local; API keys are
never accepted in company configs. See [LLM.md](../LLM.md) for schema and commands.
Zero-label API defaults: `zero_label_strategy: hierarchical` (`flat`/`shortlist`
are alternatives), `shortlist_size: 8` (2–100), `include_supplier_context: true`
and `confidence_mode: blended` (`raw` is also available). See
[ZERO_LABEL.md](../ZERO_LABEL.md). Labelled retrieval keeps its separate backend.

`company_A.yaml` and `company_B.yaml` implement the semantic mappings from
`DATA_PROFILE.md`. All purchase columns in the supplied files are mapped; unmapped
columns in a future file are still preserved in each record's `raw` dictionary.

## Paths and safe loading

Pass the extracted kit root as `--data-dir`. Relative file paths resolve against
that root; without the option, they resolve against the config's directory.
Absolute input paths are supported for local use, but public configs contain
only relative paths. A2/B2 reuse the same configs against a fresh root containing
the same relative filenames. No source file is modified or copied.

Configs accept safe YAML or its JSON subset. Duplicate keys, unknown settings,
invalid types and missing required mappings are rejected. YAML object execution
is disabled. Diagnostic commands print aggregate counts, not records. The
`run --output` command writes validated submission CSVs.

## Schema version 1

| Setting | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `company_id` | Company identifier string; no company-specific code branch |
| `reporting_currency` | Reporting currency string |
| `csv` | Optional global `encoding` and one-character `delimiter`; defaults UTF-8 BOM support and comma |
| `sources` | Nonempty list of named purchase sources |
| `taxonomy` | Runtime tree file and contiguous `l1` through `l4` column mappings |
| `fx` | Optional monthly table with `currency`, `month`, `units_per_usd` mappings |
| `labels` | Optional development reference; read only with `--with-labels` |
| `eligibility` | Optional additional/disabled non-procurement rules; shared rules are the default |
| `matching` | Optional repeat-export sources and preferred/secondary source pairs; disabled by default |
| `classification` | Optional local/OpenAI/auto settings; local by default |
| `financial_fallback` | Optional missing-amount/FX approximation policies; strict by default, documented in [FINANCIAL_POLICY.md](../FINANCIAL_POLICY.md) |

Every file specification has `path`, `fields` (semantic name to actual column
name), and optional `csv` overrides. Sources additionally require `name`,
`amount_basis` and `number_format`. Source and label specs may supply a
`record_id_prefix`; reference tree/FX prefixes have no meaning and must stay empty.

Source settings:

- `fields` must map `source_record_id` and `amount`. Supported semantic names are
  listed in `cantill.config.FIELDS`. Source headers must match exactly.
- `record_id_prefix` defaults to empty. Output IDs are prefix plus original ID,
  without trimming or numeric conversion. Duplicate output IDs fail ingestion,
  including collisions across files. A uses `ERP:`/`TOOL:`; B uses no prefix.
- `constants` supplies string-valued semantic fields absent from a file. It cannot
  overwrite mapped columns, IDs or amounts. A ERP's reporting `currency` is ZAR;
  its original document currency remains separate.
- `amount_basis` is `net`, `gross` or `as_provided`. B uses `as_provided` because
  the brief supplies no separate B VAT rule. Ingestion does not calculate tax.
- `number_format` declares `decimal` (dot/comma) and `thousands` (a different
  grouping character, or an empty string).
- `date_formats` gives a nonempty list of Python date-format strings for every
  mapped/constant date field. No row-level date parsing occurs during ingestion.
- `vat_default`, where supplied, is a quoted fractional decimal from 0 to 1.
  Gross sources require a VAT field/constant or default. A tool uses `'0.15'`.
- `rate_convention` declares direct currency-rate direction: `units_per_reporting`
  (default, division) or `reporting_per_unit` (multiplication). B declares division.
- `status_policy` is `require_approved` when status is mapped/constant, otherwise
  `unavailable`. Explicit policy must agree with the mapping. Missing status on an
  export remains a flagged limitation, not an invented approval or rejection.
- `approved_statuses` and `cancelled_statuses` are string lists, defaulting to
  approved/paid and cancelled/canceled. Case/Unicode/whitespace are normalized;
  the lists must be disjoint and approved statuses cannot be empty.

The optional `fx` table also accepts `number_format` (default dot decimal/no
grouping) and `month_format` (default `%Y-%m`). Its `units_per_usd` semantics require
USD reporting, and monthly fallback always divides by the rate. Normalization
flags missing/invalid lookups. Only an explicit `missing_fx: nearest_month`
fallback may select another supplied month; rate direction is never inferred.

## Canonical data and reference relationships

`ingest_company(load_config(config_path, data_root))` returns `IngestedCompany`:

- `records`: one DataFrame row per purchase input record. Semantic values remain
  original strings, including whitespace, blanks, leading zeros, number/date
  formatting and literal `NA`/`null` text. Absent semantic fields are empty strings.
- Provenance fields: `record_id`, `company_id`, logical `source`, `source_row`
  (one-based data-record ordinal, not physical text-line number), and `raw`
  containing every original source column/value. Multi-line quoted cells retain
  their contents. Original CSV byte hashes are checked separately by the audit.
- `config`: source parsing/financial declarations for later pipeline stages.
- `taxonomy`: exact-name terminal paths; trailing empty levels are removed, while
  internal gaps, duplicate paths and empty trees are rejected. Supports variable
  depths up to four. No category-name dictionary is embedded in processing code.
- `fx`: a separate raw-string table, or `None`. Currency/month keys must be
  nonblank and unique. Conversion/date-month lookup belongs to normalization.
- `labels`: `None` by default, even when a label path is configured. When explicitly
  loaded, each prefixed ID must join exactly one canonical record, with no duplicate
  label IDs. Labels stay separate and are never merged into purchase fields.

Malformed CSV widths, duplicate/blank headers, missing mapped columns, missing
files, blank IDs and repeated source paths fail clearly instead of silently losing
rows. Structurally valid header-only purchase files are permitted. Bad amount/date
cell values are retained for stage 6 to parse and flag, rather than deleting rows.

Supplier/item keys, classification and label category validation are later stages.
Cross-system purchase matching, financial/date normalization and
final output contract validation are available separately; see `NORMALIZATION.md`
and `OUTPUT_VALIDATION.md`.
Eligibility is also implemented separately; see `ELIGIBILITY.md`. Optional root
`eligibility.disabled_rules` lists built-in rule names. `additional_rules` contains
objects with a unique `name`, supported context `fields`, regex `pattern`, and
optional logical `sources`. Rule patterns evaluate fields separately with normalized
case/Unicode/whitespace. No golden label records or category names belong in rules.

Root `matching.repeat_sources` lists logical sources with explicit export-repeat
semantics. `cross_sources` lists objects with `preferred`, `secondary`, and a
`po_pattern` regex capturing `po` and optionally `line`. Monetary/quantity tolerances
are nonnegative decimal strings; similarities are numbers in [0, 1]; candidate/group
bounds are positive integers. Date-window bounds are nonnegative integers. Pairs
must use distinct declared sources, each secondary may appear once, and no source
may be both preferred and secondary. A shared preferred source must use a consistent
PO pattern across its pairs. All settings and defaults are in `MATCHING.md` and
`cantill.match_config.CrossSourceMatch`. A's PO format is configured, not hard-coded
as a universal format. B config enables only strict invoice export repeats.
Loading a four-level tree is not evidence of classification accuracy.

Do not put records, golden mappings, secrets or personal paths into public configs.
Confidential local overrides belong in ignored `private/`. C will require its own
config; its actual schema and inference performance are not yet known.
