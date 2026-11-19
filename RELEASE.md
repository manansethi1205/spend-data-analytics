# Clean-checkout and new-company readiness

The user confirmed that the original deadline no longer applies. Historic
deadline notes describe the original task schedule, not an active development
restriction. The instruction to make no further paid API calls remains active.

## Fresh checkout, no API credits

The public code runs without private classification caches, retrieval indexes or
source labels. Install with `uv sync --locked`, keep the raw task kit outside the
repository, then run:

```powershell
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --classifier local --output private/fresh_A.csv
uv run --locked cantill-spend run --config configs/company_B.yaml --data-dir "<kit-root>" --classifier local --output private/fresh_B.csv
```

These are local taxonomy baseline outputs. They are not exact regenerations of
the selected LLM/retrieval submissions: the historical private indexes and API
decisions are deliberately unpublished. Final selected CSVs and their checksums
are in [submission/](./submission/README.md). Category differences on a fresh
local run are expected; financial handling, eligibility and output validation
remain the configured pipeline. Local functionality is not evidence of equal
classification accuracy.

## New company and four-level tree

Run the entirely invented [C example](./examples/company_C/README.md):

```powershell
uv run --locked cantill-spend run --config configs/company_C.example.yaml --data-dir . --classifier local --output private/demo_C.csv
```

It verifies six records, three included rows, three reason-coded exclusions,
net USD 325, complete four-level classification, and operation without labels,
keys or a trained index. Category names come from its tree file.

For actual new data, copy the example config to a new company config and map its
source paths, ID, amount, currency/rate, date, status, supplier and description
columns. Declare number/date formats, net/gross basis and rate direction from
that data's specification. Map the tree's contiguous L1 through deepest supplied
level. Omit labels and retrieval indexes for an unseen company. Do not substitute
the demo's category paths for the new tree. Validate before accepting an output:

```powershell
uv run --locked cantill-spend run --config configs/company_C.yaml --data-dir "<new-data-root>" --classifier local --llm-max-requests 0 --llm-max-tokens 0 --output submission/manan__C.csv
uv run --locked cantill-spend validate-output --config configs/company_C.yaml --data-dir "<new-data-root>" --output submission/manan__C.csv
```

A2/B2 reuse A/B configs against roots with the same relative filenames. C needs
its actual files/tree before its real config or output can be produced. Strict
financial handling remains the default for new companies; B's documented
fallback is opt-in. An unresolved included financial value blocks export.

## Independent installation check

```powershell
uv run --locked python tools/verify_clean_checkout.py --data-dir "<kit-root>"
```

This copies only publishable Git candidates into ignored temporary storage,
creates a fresh environment, installs the locked project non-editably with
`uv sync --offline`, removes all OpenAI environment variables, and runs the
synthetic C example plus optional full A/B local jobs. Each output is independently
validated. No Git internals, private artifacts or existing virtual environment
are copied. It reuses only the dependency download/build cache, so it verifies a
clean project installation but does not claim an empty-cache internet install.
No API requests are made. Reports and generated outputs stay in ignored storage.

The completed Windows/Python 3.12 check passed: isolated locked installation
13.01 seconds; synthetic C 24.07 seconds; full A 69.23 seconds; full B 43.62
seconds. These CLI wall times include startup, processing and export. Separate
output validation passed for all three. Real A/B row counts, eligibility and
spend totals match the selected submissions, while categories use the weaker
local baseline. This establishes installed no-cost operation, not reproduction
of historical LLM decisions or a cold API-runtime benchmark.
The full regression suite passes 549 tests. Both selected submission hashes are
unchanged, and a heuristic working-tree candidate scan found no raw/private files
or matching API-key strings. Git history has not been certified for publication.

## Publication remains separate

The intended public repository is `manansethi1205/spend-data-analytics`.
Source/output auditing and initial project publication are being prepared.
Publish only an audited project branch containing source, configs, synthetic
examples, documentation and approved final CSVs. Internal agent checkpoint refs
are not release history and must not be mirrored. Do not add source inputs,
private indexes/caches, local environments or credentials. The selected outputs
are structurally valid; accuracy/runtime/cost limitations remain in
[APPROACH.md](./APPROACH.md) and [submission notes](./submission/README.md).
