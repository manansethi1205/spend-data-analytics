# Cantill spend pipeline

A configuration-driven tool for spend normalization, purchase
de-duplication, supplier/item resolution and runtime taxonomy classification.
The final target is unattended processing of A/B and blind-test A2/B2/C.

Public repository: [manansethi1205/spend-data-analytics](https://github.com/manansethi1205/spend-data-analytics).

## Current status

The original task deadline no longer applies, as confirmed by the user. Further
development and release checks continue without additional paid API calls.
See [RELEASE.md](./RELEASE.md) for clean-checkout operation and new-company onboarding.

The pipeline implements ingestion, normalization, eligibility, purchase matching,
entity resolution, runtime-tree classification and validated export. Local mode
runs without API keys. Optional OpenAI classification supports strict category
validation, private caches, bounded usage and visible local fallback. Known A/B
companies can opt in to private labelled retrieval; C and labels-hidden A use the
separate zero-label path. Inference does not read source label files.

Live evaluation succeeded. On 100 group-balanced reserved records per arm, A
zero-label accuracy was 14%, A assisted 39%, and B assisted 84%. These are not
population or blind-test estimates; see [HOLDOUT.md](./HOLDOUT.md). Confidence is
uncalibrated and A classification/entity recall remain material quality limits.

The zero-label LLM path has since been revised to hierarchical child selection,
with an optional TF-IDF shortlist, supplier-name context and a review/local-margin
confidence blend. The 14% result remains the old flat strategy's score; new live
accuracy is pending under the no-further-spending instruction. See
[ZERO_LABEL.md](./ZERO_LABEL.md) for offline replay and paired evaluation.

The finalized outputs retain their earlier classifier/index version. A's completed rehearsal covers all
46,325 included rows with 9,045 cached LLM decisions; all 65,549 output records
pass independent validation. Recovery took 219.69 seconds and an estimated
USD 0.08411475 for that retry only. An earlier partial resumed run took 75.7
minutes; cold runtime and total historical cost remain unverified. See
[REHEARSAL.md](./REHEARSAL.md).
B now explicitly opts into [financial fallback](./FINANCIAL_POLICY.md): blank
amounts use flagged zero placeholders and absent invoice-month FX uses flagged
nearest supplied months. The eight values are estimates, not recovered amounts
or historically verified rates. A and new companies remain strict by default.
The suite passes 562 tests, including zero-label branching/budget/evaluation,
fallback, financial-version provenance,
safe API diagnostics and the published four-level new-company CLI example.
The user chose to finalize B without further API spending after credits were
exhausted. B has 18,054 LLM-classified included rows and 19,856 local fallback rows
(10,661 retrieval, 9,195 taxonomy baseline). Its historical run remains partial;
complete LLM coverage and accuracy are not claimed.

Final named outputs [manan__A.csv](./submission/manan__A.csv) and
[manan__B.csv](./submission/manan__B.csv) independently validate all source records.
They preserve the selected run outputs exactly. See [submission notes](./submission/README.md)
for coverage and limitations. No further API calls were made for finalization.
The audited project branch is published; no external submission form has been
sent. [APPROACH.md](./APPROACH.md) records
measured results and limitations.

## Run the label-free baseline

```powershell
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --output private/baseline_A.csv
uv run --locked cantill-spend run --config configs/company_B.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend resolve --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked python tools/evaluate_baseline.py --kit-dir "<kit-root>"
```

The first command writes A only after validating every record against source IDs
and the runtime tree. Without `--output`, `run` prints aggregate JSON only. Exit 0
means included financial values are resolved; exit 1 reports unresolved values;
requested export with unresolved values fails with exit 2 and preserves an existing
destination. Configured inputs cannot be overwritten. The baseline exporter retains
excluded rows with zero spend, blank categories and zero classification confidence.

Evaluation disables the label config and rejects label reads during inference,
then opens labels only for scoring. Confidential reports and A's validated baseline
CSV stay under ignored `private/baseline/`. No B CSV is fabricated. These are local
development artifacts, not the final named submission. See [BASELINE.md](./BASELINE.md)
for methods, measured accuracy, confidence semantics and limitations.

## Setup

Use Python 3.12 and `uv`. Install uv following its
[official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```powershell
uv sync --locked
uv run --locked cantill-spend --help
uv run --locked python -m cantill --version
uv run --locked pytest
```

No activation or global pip installation is needed. The project uses `.venv/` and
keeps the uv cache in `.cache/uv`; both are ignored. `uv.lock` records the resolved
dependencies. `--locked` checks that the lock is current rather than changing it;
see [uv locking documentation](https://docs.astral.sh/uv/concepts/projects/sync/).
Runtime dependencies are pandas, PyYAML and the official OpenAI SDK; pytest is
development-only. No API key is needed for local mode, setup or profiling.

Setup was verified on native CPython 3.12.11: CLI entry points and dependency
imports pass, all 26 confidentiality checks pass, and locked offline re-sync and
`uv pip check` pass. Wheel/source packages were built and inspected for accidental
input/cache inclusion. This is setup verification, not pipeline accuracy or runtime
evaluation. Python versions outside 3.12 are not currently declared as supported.

## Ingest company data

```powershell
uv run --locked cantill-spend ingest --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend ingest --config configs/company_B.yaml --data-dir "<kit-root>"
```

`<kit-root>` is the extracted directory containing `company_A/` and `company_B/`.
The command validates config, input IDs/headers and runtime references, then prints
aggregate JSON counts only. It does not write records or submission files. Labels
are not read by default; add `--with-labels` only for development checks. Loaded
labels remain separate from canonical purchase records.

All 65,549 A and 41,028 B records were verified against their original cells/IDs,
with unchanged source hashes and identical records with/without labels. The full
ingestion milestone passed 70 test cases, covering malformed inputs, label joins,
config reuse on fresh records and a new layout with a four-level tree. These are
ingestion checks, not matching/classification results. See `configs/README.md` for
the schema, path rules and Python API.

## Validate a submission CSV

```powershell
uv run --locked cantill-spend validate-output --config configs/company_A.yaml --data-dir "<kit-root>" --output "<candidate.csv>"
```

The validator checks the exact header, source ID coverage, inclusion/exclusion
consistency, finite spend/confidence, entity keys and complete terminal taxonomy
paths. It prints bounded JSON diagnostics without record values and changes no
files. Exit codes: 0 valid, 1 invalid output, 2 config/source/argument failure.
Labels stay unloaded. Validation does not prove prediction or financial accuracy.

Output tests cover malformed files, hidden missing records, variable-depth trees,
credit/zero spend, exact decimal totals and CLI success/failure cases.
See `OUTPUT_VALIDATION.md` for output conventions,
all check groups and the API. Selected final A/B outputs are in [submission/](./submission/README.md).

## Normalize amounts and dates

```powershell
uv run --locked cantill-spend normalize --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend normalize --config configs/company_B.yaml --data-dir "<kit-root>"
```

Normalization preserves source fields while adding parsed numbers/dates, VAT/FX
provenance and quality flags. A resolves all 65,549 financial rows. B now produces
numeric values for all 41,028 through its opt-in policy, with eight estimates
explicitly flagged. Both normalization commands exit 0 for the supplied kit;
this indicates numeric readiness rather than financial accuracy. Strict handling
still leaves those eight unresolved if B's fallback is disabled. Config/source
errors exit 2. Neither normalization command generates submission files.

All computable A/B amounts were independently checked with rational arithmetic,
all mapped dates verified, and source hashes/cells/IDs preserved. Reproduce with:

```powershell
uv run --locked python tools/verify_normalization.py --kit-dir "<kit-root>"
```

The normalization milestone passed 222 tests across the implemented stages. See
`NORMALIZATION.md` for financial/date rules, the API, flags and remaining limits.
These are pre-exclusion/pre-deduplication values, not final spend totals.

## Assess procurement eligibility

```powershell
uv run --locked cantill-spend eligibility --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend eligibility --config configs/company_B.yaml --data-dir "<kit-root>"
```

Status and explicit non-procurement evidence produce reason codes with traceable
rule/field IDs. A has 503 status exclusions; B has 2,483 non-procurement rule
exclusions. Every input record remains present. Status-absent exports retain a
`STATUS_UNAVAILABLE` flag; approval is not invented or inferred from paid date.
B's eight financial estimates remain flagged under its configured fallback;
eligibility by itself does not remove purchase duplicates or produce a final total.

The eligibility milestone passed 294 tests. The initial grouped reserved evaluation on 554 B seeds achieved
91.2% exact decisions, 100% exclusion precision and 45.6% exclusion recall. After
reviewing missed tax wording, the current rules match all 3,000 seeds on a
development recheck. That recheck is not independent held-out accuracy. The original
baseline and replay config remain preserved locally. See `ELIGIBILITY.md` for the
split, policies, reproducible checks and limits.

## Count purchases once

```powershell
uv run --locked cantill-spend deduplicate --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend deduplicate --config configs/company_B.yaml --data-dir "<kit-root>"
```

Matching retains every source row, prefers ERP for supported A overlaps and links
duplicate records to retained purchases. It handles export repeats, PO/line and
missing-PO matches, grouped records and quantity-budget coverage. Existing exclusion
reasons and original source values remain unchanged. Ambiguous/partly covered
records stay visible; unmatched does not prove a purchase exists only in one source.

A currently counts 46,325 records (all 37,029 ERP and 9,296 tool), with 18,721
duplicates and the earlier 503 status exclusions. B counts 37,910, with 635 export
duplicates and the earlier 2,483 non-procurement exclusions. B's eight financial
estimates are retained and flagged. This diagnostics command does not write a
submission; the `run --output` command writes validated files.

The stage-8 milestone passed 353 tests. Label-free real-data checks verify source preservation, exact
amount reconciliation, retained duplicate targets and quantity/amount capacity:

```powershell
uv run --locked python tools/verify_matching.py --kit-dir "<kit-root>"
```

See `MATCHING.md` for criteria, configuration, diagnostics and uncertainty. Matching
coverage and conservation checks are not ground-truth precision/recall measurements.

For intentional dependency updates during development, edit `pyproject.toml`, run
`uv lock`, then `uv sync --locked`. Retain earlier lockfiles with historical results
when changing dependencies; the old task deadline is no longer active.

## Confidential inputs and profiling

Keep the extracted kit outside the repository, or under ignored `data/`. Run:

```powershell
uv run --locked python tools/profile_data.py --kit-dir "<path-to-Cantill_DataML_Task_Kit>"
```

The profiler reads all eight source files, verifies they remain unchanged, and
writes detailed confidential diagnostics only to `private/profiling/profile.json`.
That report contains source-derived values and must not be published.

Do not commit task input files, confidential records in tests/docs, trained
artifacts containing golden mappings, credentials, model caches or local diagnostic
extracts. `.gitignore` protects known input names and local storage; review renamed
inputs and generated artifacts too. Required submission CSVs are intentionally not
blanket-ignored. Tests use synthetic paths, without confidential fixtures.

## Layout and next stage

| Location | Purpose |
| --- | --- |
| `src/cantill/` | Installed application and CLI |
| `configs/` | Validated A/B configs and schema documentation |
| `tests/` | Synthetic ingestion/config tests and Git confidentiality safeguards |
| `tools/profile_data.py` | Standalone, read-only exploratory audit |
| `REQUIREMENTS.md` | Requirements and acceptance checks |
| `DATA_PROFILE.md` | Aggregate findings and semantic mappings |
| `DECISIONS.md` | Evidence-backed choices and unresolved policies |
| `OUTPUT_VALIDATION.md` | Output contract, validator usage and diagnostic semantics |
| `NORMALIZATION.md` | Financial/date rules, provenance, quality flags and verification |
| `ELIGIBILITY.md` | Status/non-procurement policies, grouped evaluation and remaining limits |
| `MATCHING.md` | Purchase matching, allocation budgets, repeat detection and limits |
| `BASELINE.md` | Entity resolution, taxonomy-only inference, measured evaluation and export |
| `LLM.md` | OpenAI classification, caching, limits, authentication and fallback |
| `PILOT.md` | Fixed development samples, offline previews and gated accuracy/cost measurements |
| `RETRIEVAL.md` | Private labelled examples, excluded evaluation groups and opt-in retrieval/LLM classification |
| `HOLDOUT.md` | Fixed-strategy reserved-group evaluation and fresh A zero-label comparison |
| `REHEARSAL.md` | Full-company plans, financial readiness, runtime/cost and release status |
| `APPROACH.md` | One-page design and measured evaluation summary |
| `RELEASE.md` | Clean-install verification and no-cost new-company commands |
| `configs/company_C.example.yaml` | Synthetic four-level company configuration |
| `examples/company_C/` | Invented input/tree for public end-to-end verification |
| `submission/` | Selected final A/B outputs, limitations and checksums |
| `private/` | Ignored confidential diagnostics and local artifacts |

Development/reserved measurements and selected A/B output finalization are
documented separately. Clean-checkout verification and actual publication are
tracked in [RELEASE.md](./RELEASE.md) and [REQUIREMENTS.md](./REQUIREMENTS.md).

## AI use

OpenAI Codex assisted with planning, exploratory profiling, documentation and
project setup, ingestion, validation, normalization, eligibility, matching, entity
resolution, classification, OpenAI integration, evaluation and documentation.
Authorized development/reserved runs sent line and retrieved-reference context
to OpenAI. Explicit OpenAI/auto runs can send this context; local mode has no API
cost. Source inputs, labels, indexes, caches, detailed diagnostics and credentials
must remain private. Selected final outputs retain documented partial B LLM
coverage; no further paid inference is authorized.
