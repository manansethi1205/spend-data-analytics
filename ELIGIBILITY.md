# Procurement eligibility and exclusion reasons

Stage 7 assesses procurement candidates after normalization. It preserves every
record, including excluded records. Cross-system and repeat-export duplicates are
stage 8; these candidate decisions are not final submission inclusion decisions.

## Usage and output

```powershell
uv run --locked cantill-spend eligibility --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend eligibility --config configs/company_B.yaml --data-dir "<kit-root>"
```

CLI output is aggregate JSON, without IDs, descriptions, supplier names or amounts.
Exit 0 means no eligible candidate has an unresolved financial value. Exit 1 means
some eligible amounts remain unresolved; exit 2 is a config/source failure. No
labels are read and no submission files are written. B currently exits 1 because
the eight financial exceptions still have no supported exclusion evidence.

Python API:

```python
from cantill.eligibility import assess_eligibility

assessed = assess_eligibility(normalized)
print(assessed.summary())
```

`normalized` is a `NormalizedCompany`. Original canonical/normalized values and
quality flags remain unchanged. Added columns are:

| Column | Meaning |
| --- | --- |
| `eligible` | Procurement candidate before duplicate matching |
| `eligibility_reason` | Blank if eligible; otherwise a permitted non-duplicate exclusion code |
| `eligibility_basis` | Primary status/rule that selected the decision |
| `eligibility_evidence` | Matching status/rule IDs and semantic field names, without cell values |
| `eligibility_flags` | Unavailable/missing/disallowed status or unresolved eligible amount |
| `eligible_amount_value` | Normalized amount for eligible rows, otherwise zero; eligible unresolved values remain `None` |

## Status policy and precedence

Each source supports:

- `status_policy: require_approved`: exact normalized membership in
  `approved_statuses` counts. Default values are approved/paid. Configured cancelled
  statuses receive `CANCELLED`; other values, including unknown/blank status,
  receive `NOT_APPROVED`. Matching normalizes Unicode compatibility, case and
  whitespace, not substrings: `Unpaid` and `Paid pending` do not become `Paid`.
- `status_policy: unavailable`: for exports without a mapped status. These records
  remain candidates absent non-procurement evidence and receive `STATUS_UNAVAILABLE`.
  Their approval is **not verified**. The policy cannot ignore a declared status
  mapping/constant; config validation rejects that mismatch.

Defaults select the first policy when status is mapped, otherwise the second.
A/B configs state their policy explicitly. A tool maps its actual statuses; A ERP
receipts and B AP invoices have no explicit status field. B seeds include unpaid
records, so a missing paid date cannot supply a rejection rule. Candidate retention
for status-absent exports is a documented operational choice, not a claim that the
brief supplied approval evidence. It remains a limitation for unseen data.

Primary reason precedence is `CANCELLED`, then `NOT_APPROVED`, then
`NON_PROCUREMENT`. All matching rule evidence remains visible even when status
determines the primary reason. Stage 8 should assign `DUPLICATE` only to eligible
candidates already represented by a retained purchase, preserving existing reasons.
This precedence is a project convention where the brief leaves multiple reasons
possible; it is not presented as an extra supplied rule.

## Non-procurement evidence

Seven shared, named rules operate on appropriate semantic text fields:

| Rule | Evidence sought |
| --- | --- |
| `intercompany_account` | Explicit intercompany/intragroup account text or control-account shorthand |
| `tax_control_line` | Explicit tax-only/control-line text, including sales, GST/VAT and state/local taxes |
| `intercompany_transfer` | Intercompany transfer/charge/billing text, excluding advisory/pricing phrasing |
| `royalty_payment` | Explicit royalty payment/expense text |
| `partner_billing` | Partner billing/recharge/settlement text |
| `financing_cost` | Explicit interest/financing/loan/dividend payment text |
| `revenue_control` | Revenue/customer-receivable control-line text |

Rules do not treat every mention of tax, interest, revenue or intercompany as an
exclusion. Tax advisory, customs clearance/duties, royalty-management software and
transfer-pricing advisory services have positive synthetic checks. The rules are
conservative evidence patterns, not a comprehensive language-understanding model.

Negative/zero spend, a credit document type, blank descriptions, missing payment,
invalid financial values and an unknown opaque supplier/account code alone do not
prove non-procurement. No company-specific supplier-type blacklist or per-record
label lookup is shipped. The coded intercompany shorthand is inferred from the
development labels and evaluated, rather than assumed to apply to every code.

For a new company, config can add rules or disable a named default when its chart
uses conflicting semantics. `eligibility.additional_rules` entries contain `name`,
`fields`, regex `pattern` and optional logical `sources`. Match any listed field;
do not concatenate unrelated fields. `disabled_rules` lists built-in names. Unknown
names, unsupported fields/sources, duplicate rule names and invalid regexes fail
validation. Record-ID and financial-error matching is not supported as a way to
memorize labels or disguise missing amounts as exclusions.

## Development split and honest evaluation

Before developing the rules, B seeds were grouped by normalized description;
blank descriptions use source/vendor/invoice scope. SHA-256 with fixed protocol
`cantill-eligibility-v1` assigns one in five group hashes to a reserved partition.
It uses no target labels. All exact description repeats stay together across
systems, while blank text does not collapse all blank records into one group.

The frozen local manifest contains 2,446 development and 554 reserved records.
Full-label descriptive profiling had already occurred in stage 2, so this is not
an untouched external test. Seed coverage is selective/noisy, and it cannot stand
in for the blind test or unlabelled/blank-description populations.

| Evaluation | Records | Exact decisions | Exclusion precision | Exclusion recall |
| --- | ---: | ---: | ---: | ---: |
| Initial development | 2,446 | 2,446 | 100% | 100% |
| Initial reserved evaluation | 554 | 505 (91.2%) | 100% | 45.6% |
| Post-review development recheck | 3,000 | 3,000 | 100% | 100% |

The reserved evaluation found 49 missed exclusions and no false exclusions.
Those misses were a tax wording absent from the initial pattern; the rule was
expanded and synthetic positive/negative cases added. The post-review result uses
the reviewed reserved cases and **is not an independent holdout score**. Keep the
initial result when discussing generalization. No clean held-out performance is
claimed for the amended rules.

Reproduce the current development recheck:

```powershell
uv run --locked python tools/evaluate_eligibility.py --kit-dir "<kit-root>" --partition all --report-tag post_review
```

The initial rules/config were fingerprinted before opening the reserved errors.
The original report, fixed split and original-rule replay config remain local
under ignored `private/eligibility/`. In this working checkout, the baseline can
be replayed with `--config private/eligibility/baseline_company_B.yaml --partition
all --report-tag baseline`. It reproduces the original rule signature and numbers.
Current and baseline reports are stored separately; baseline reruns must agree.
Do not publish private manifests or failure/exception IDs.

## Full-data checks and remaining work

| Company | Records | Candidates before duplicates | Rule/status excluded |
| --- | ---: | ---: | ---: |
| A | 65,549 | 65,046 | 503: 188 cancelled, 315 not approved |
| B | 41,028 | 38,545 | 2,483 non-procurement |

B's current rules identify 2,041 intercompany-account records and 442 tax-control
lines. These are rule results on unlabelled records, not independently established
truth for the whole dataset. Generic royalty/partner/finance/revenue patterns are
tested synthetically but have no labelled A/B support demonstrating their accuracy.

Reproduce integration checks without loading labels:

```powershell
uv run --locked python tools/verify_eligibility.py --kit-dir "<kit-root>"
```

They verify original cells/IDs/normalization values, unchanged source hashes,
reason/amount invariants and explicit tool statuses. All 294 tests pass. The eight
B financial exceptions remain candidates with unresolved amounts and visible
flags: their accounting context does not justify a non-procurement exclusion.
Their supported financial resolution remains necessary before final exports.

Stage 8 matching is now implemented in `MATCHING.md`, preserving these reasons and
adding supported duplicate exclusions. No final spend cube, grouped entity keys,
category predictions or submission outputs exist yet. Next is stage 9 entity resolution.
