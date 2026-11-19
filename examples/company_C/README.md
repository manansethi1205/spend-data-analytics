# Synthetic new-company example

These six invented records and three four-level category paths contain no task
data. They exercise configuration-only onboarding, gross-to-net VAT, direct FX,
approved/paid status, cancellation, unapproved status and repeated export removal.
No labels, trained index, API key or existing classification cache are required.

From the repository root:

```powershell
uv run --locked cantill-spend run --config configs/company_C.example.yaml --data-dir . --classifier local --output private/demo_C.csv
uv run --locked cantill-spend validate-output --config configs/company_C.example.yaml --data-dir . --output private/demo_C.csv
```

Expected: six output rows, three included, three excluded (one each CANCELLED,
NOT_APPROVED and DUPLICATE), USD 325 total spend, and populated L4 on included
rows. This is a small functionality check, not an unseen-industry accuracy test.
For an actual C, map its real columns, number/date formats and runtime taxonomy
in a separate configuration; do not reuse these invented category paths.
