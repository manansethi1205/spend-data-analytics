# Financial fallback policy

This policy was explicitly requested after the strict pipeline identified eight
included B rows without usable financial values. It permits a numeric best-effort
export while keeping the uncertainty visible. It does not recover ground truth.
Raw inputs remain unchanged. A and newly configured companies remain strict
unless their configuration explicitly opts in.

```yaml
financial_fallback:
  missing_amount: zero
  missing_fx: nearest_month
```

## Missing amounts

Only a blank source amount becomes decimal zero. The row remains eligible under
the ordinary eligibility rules, receives its supplier/item/category, and retains
`AMOUNT_MISSING` plus `AMOUNT_ESTIMATED_ZERO`. Raw amount remains blank. Invalid
nonblank numbers still block export. Three current B rows use this policy.

Zero is an unknown-value placeholder, not a finding of no spend. It omits the
unknown signed amounts from the total; the true variance cannot be bounded from
the kit and may have either sign. Quantity and neighbouring descriptions do not
provide sufficient evidence for imputing prices. Missingness alone is not a
permitted exclusion reason, so these rows are not relabelled non-procurement.

## Missing invoice-month FX

Preserve the existing order: reporting-currency identity, usable supplied line
rate, then exact invoice-month reference rate. Only when the line rate is blank
and the invoice-month reference entry is absent may the fallback select the
nearest valid month for that same currency. Distance is absolute calendar-month
distance; ties choose the earlier month. No other currency is substituted.
Divide the signed source amount by the selected units-per-USD rate.

Preserve the invoice date and requested `fx_month`, record `fx_reference_month`
and `exchange_rate_source=nearest_month_fx`, and retain `FX_RATE_MISSING` plus
`FX_ESTIMATED_NEAREST_MONTH`. Invalid supplied rates, invalid reference entries,
unparseable invoice dates and currencies with no valid reference remain blocked.
Five current B rows use this policy.

In the supplied kit, all five choose December 2022 CAD units-per-USD of 1.35,
five to seven months after their requested invoice months. Their combined
estimated contribution is approximately USD -504.14. This does not bound the
error from the three unknown amounts. The independently validated local B export
contains 41,028 records, including 37,910 spend rows and eight estimated rows.

This is an approximation beyond the brief's invoice-month rule when the required
month is unavailable. A distant rate, potentially from after the invoice, is not
historically accurate evidence. Posting dates are not silently treated as invoice
dates. The selected reference month and rate are retained in a private audit.

## Audit and versioning

`financial_estimated=true` marks estimated rows internally. Numeric readiness now
means an output value exists, not that its original value is known. The fixed
submission schema has no quality-flag column, so flags stay in the internal
records and ignored private `financial_estimates.json`; this document discloses
their interpretation. Final output validation checks structure, not accuracy.

The new B rehearsal plan records financial version changes and verifies unchanged
raw input hashes, classification code, prompt, model and reference indexes.
Historical evaluation/results and A caches remain untouched. Earlier plans reject
changed fingerprints; use the newly prepared root rather than editing old plans.
Historical accuracy measurements were not rerun and are not measurements of this
new financial policy. No per-record corrections or category overrides are encoded.

If authoritative values become available, replace this policy with a separately
audited correction workflow and rerun. For new data the same configured rules
apply unattended; missing amounts/rates outside their defined coverage still fail
closed. The user has since confirmed that the original deadline no longer applies;
historical reports and output provenance remain preserved.
