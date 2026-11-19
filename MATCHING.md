# Purchase matching and count-once logic

Stage 8 adds configuration-driven export-repeat detection and cross-source
purchase matching after eligibility. All input rows remain present. A matched
secondary record receives `DUPLICATE`, zero counted spend and links to retained
records. Existing cancelled/not-approved/non-procurement reasons are preserved.

## Usage and API

```powershell
uv run --locked cantill-spend deduplicate --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend deduplicate --config configs/company_B.yaml --data-dir "<kit-root>"
```

The CLI prints aggregate counts only and writes no submission files. It reads no
labels or golden entity keys. Exit 0 means retained amounts are resolved; exit 1
means some included financial values are unresolved; config/source errors exit 2.
B still exits 1 for the same eight financial exceptions.

```python
from cantill.matching import count_purchases

matched = count_purchases(eligible)
print(matched.summary())
```

`eligible` is an `EligibleCompany`. `matched.records` preserves all previous fields
and adds:

| Field | Meaning |
| --- | --- |
| `include`, `exclusion_reason` | Counted-record decision and blank/permitted reason |
| `spend_value` | Original normalized reporting amount if counted; zero if excluded |
| `duplicate_of` | Tuple of final retained record IDs, possibly several receipts |
| `match_method` | Export repeat, PO/line, no-PO, receipt/invoice group or quantity coverage |
| `match_score` | Uncalibrated similarity ranking; not classification confidence |
| `match_evidence` | Evidence role names, without original cell values |
| `matching_flags` | Ambiguity, conflicts, missing evidence and coverage diagnostics |

`matched.allocations` records direct/group matches and quantity/amount claims.
Duplicate chains are flattened: a repeated tool export that later matches ERP
links to the retained ERP records, not to an excluded intermediate tool record.
The actual `supplier_key`, `item_key`, category predictions and confidence have
not been generated yet; this is not a complete submission output.

## Repeat exports

Repeat detection is explicitly enabled per logical source. A enables tool repeats
and retains all eligible ERP receipts; B enables invoice-source repeats. The
default for a new config is disabled, rather than guessing duplicate semantics.

A repeat needs a nonblank invoice reference, supplier evidence, a resolved amount,
and either invoice-line/item identity or informative description. The fingerprint
uses business/context fields, parsed numbers/dates and original unmapped fields.
It normalizes declared reference formatting and text case/whitespace, but does
not fuzzy-merge descriptions. Record IDs are excluded from comparison, not altered.

Allowed-status transitions and payment/due/posting-date changes do not create
another purchase. Invoice date, line identity, amounts, quantities, item/account,
site/company and other business differences remain significant. Unknown extra
columns are compared exactly rather than silently ignored. The smallest stable
record ID is retained. Disallowed-status copies keep their existing reason.

An invoice-line key by itself is insufficient. Conflicting versions/allocations
remain separate unless a subgroup has an equivalent business fingerprint.
`INVOICE_LINE_CONFLICT` surfaces differences instead of choosing the largest amount
or latest version. Without invoice-line IDs, equivalent rows may still be genuine
repeated purchases; `REPEAT_WITHOUT_LINE_ID` makes that information limit explicit.
Generic/blank lines without adequate item/line evidence are not collapsed.

## Cross-source matching

Each configured pair declares preferred and secondary sources. A prefers ERP over
tool. The code contains no company-name branches or category lookup tables.

1. Parse PO and optional PO-line references using a configured regex. The engine
   does not assume ten-digit POs universally. Numeric PO-line display variants
   such as `10.0` and `10` compare consistently; output record IDs retain zeros.
2. Retrieve known-PO candidates from an index; check net reporting amount,
   quantity, supplier-name evidence and description. Explicit conflicting PO lines
   never match. A nonblank different PO is not ignored to force a text match.
3. Allocate direct matches deterministically, prioritizing constrained candidate
   sets. Each receipt initially has one full-record allocation capacity per pair.
   Near-tied candidates from materially different item/order groups stay ambiguous.
4. Try full same-item receipt groups against one invoice line, and same-invoice
   line groups against one receipt. Quantities and net amounts must reconcile.
   Groups are bounded and indexed by PO; arbitrary amount-only subset sums are
   not searched. Conflicting invoice dates prevent invoice-line aggregation.
5. For remaining known-PO lines, allow full quantity coverage by a larger receipt
   or a bounded allocation across same-item receipts at compatible unit prices.
   Quantity and amount ledgers prevent allocating beyond the recorded receipt.
6. Match missing/unparseable-PO records only with stronger supplier/text evidence,
   equal quantities, net amount and compatible dates where available. Conflicting
   numeric specifications and generic descriptions reject this route. Multiple
   PO references and contradictory line metadata are not guessed.

Descriptions and service text are compared separately; numeric specification
disagreements on otherwise strong known-PO matches remain visible as flags.
Supplier name comparison removes common legal suffixes for similarity only; it
does not establish the final supplier grouping keys. A weaker name can be supported
by near-exact text plus PO/quantity/amount evidence. Generic descriptions require
an explicit compatible PO line and exact normalized supplier evidence.

Known POs support matching despite missing or anomalous dates, with diagnostic
flags for long cross-system gaps. Missing-PO matches use a tighter date window
when dates exist; unique strong non-date evidence may still match when dates are
missing. Neither route fabricates or repairs a date.

## Quantity coverage and safe limits

The data contains invoice quantities smaller than a receipt, and quantities that
span receipts at the same unit price. A line can be fully represented even when
its amount differs from every individual receipt amount.

Quantity coverage requires a known PO, compatible line/item grouping, same amount
sign, supplier/text evidence and compatible unit prices. It allocates deterministic
receipt portions and checks the resulting net total. Claims consume both quantity
and amount budgets; later invoices cannot reuse the consumed quantity. A partially
used receipt is not subsequently available for another full-record match.

If only part of an invoice is covered, retain the entire original invoice amount
with a coverage flag; do not silently replace its spend with an invented residual.
This is an explicit unresolved-overlap limitation, not proof that the full invoice
is new spend. Positive amounts with negative quantities are not repaired by taking
absolute quantities for coverage. Credit matches can use differing quantity-sign
conventions only when both monetary amounts are negative. Original signs remain.

There is no unrestricted many-to-many optimizer, cross-invoice subset search,
posting-date repair or amount imputation. Ambiguous candidates remain counted
and flagged, accepting possible residual overlap instead of suppressing uncertain
purchases. These limits can affect spend totals and matching recall.

## Configuration and chosen thresholds

Root `matching` supports `repeat_sources` and `cross_sources`. Each cross-source
pair requires `preferred`, `secondary` and `po_pattern` with a named `po` capture;
optional named `line` captures a line suffix. Unknown sources, self-pairs, repeated
secondary assignments, invalid patterns and chained/cyclic preference graphs fail.
A preferred source can serve several distinct secondary sources; each pair has
its own allocation ledger. General chained multi-system reconciliation is not
implemented; the supplied A has one pair and B/C are single purchase sources.

| Parameter | A setting | Meaning |
| --- | ---: | --- |
| `amount_tolerance` | `0.01` | Absolute reporting-currency tolerance; multiplied by contributing group size for grouped rounding |
| `quantity_tolerance` | `0.000001` | Quantity representation tolerance |
| `supplier_similarity` | 0.85 | Normal PO supplier threshold |
| `description_similarity` | 0.80 | Normal PO text threshold |
| `weak_supplier_similarity` | 0.65 | Weaker name route additionally requires text similarity >= 0.97 |
| `no_po_supplier_similarity` | 0.90 | Stricter missing-PO supplier threshold |
| `no_po_description_similarity` | 0.92 | Stricter missing-PO text threshold |
| `max_no_po_date_gap_days` | 45 | Missing-PO date window; longer known-PO gaps are flagged |
| `max_candidates` | 200 | Valid direct candidate limit; exceeding it leaves the record visible |
| `max_group_size` | 50 | Receipt/invoice group or quantity-allocation size limit |

These are engineering choices, not thresholds supplied by the brief or measured
optimal values. Similarities are sequence scores, not probabilities. Group and
allocation arithmetic uses 60-digit Decimal precision; source amounts are not
rounded to cents or changed. Existing 50-digit normalized values are retained.

## Real-data results and verification

| Company | All input records | Counted records | Duplicates | Earlier exclusions |
| --- | ---: | ---: | ---: | ---: |
| A | 65,549 | 46,325 | 18,721 | 503 |
| B | 41,028 | 37,910 | 635 | 2,483 |

A retains all 37,029 ERP records and 9,296 unmatched tool records. Its duplicate
methods are 11,723 PO, 4,133 PO-line, 2,277 no-PO, 334 quantity-coverage, 5 full
receipt-group and 249 repeat-export decisions. B's duplicates are equivalent
export fingerprints; conflicting invoice-line versions remain flagged. Payment-
lifecycle changes explain some repeats beyond byte-identical source copies.

Unmatched does not mean proven source-only. A has ambiguity and incomplete-coverage
diagnostics; they may persist after a stronger later matching pass resolves a
candidate. The number of flagged records is not a count of incorrect matches.
Several known-PO links have numeric-text disagreement, weaker supplier names or
anomalous/missing dates. Preserve that evidence for entity/classification review;
do not treat every purchase link as unconditional item-text equivalence.

Reproduce label-free integration checks:

```powershell
uv run --locked python tools/verify_matching.py --kit-dir "<kit-root>"
```

The audit verifies every original row/value/ID, prior exclusion reason, zero
excluded spend, unchanged included amount, retained duplicate target, exact
resolved-amount reconciliation and per-pair quantity/amount budget. Source hashes
remain unchanged. Detailed links, allocations and stratified review examples stay
in ignored `private/matching/`. Spot checks of lower-score and grouped real links
were consistent with the recorded evidence, but are not a labelled accuracy study.

All 353 tests pass, including 59 matching tests for hard negatives, capacity,
grouping, partial coverage, repeat chains, lifecycle changes and deterministic
ordering. No complete real purchase-match truth is provided, so no real precision
or recall estimate is claimed. Synthetic tests and ledger conservation do not
prove every linkage correct or all overlap recovered.

B's eight financial exceptions have distinct invoice-line identities and no
supported repeat match; they remain included with unresolved amounts. No final
submission outputs exist. Next is stage 9 supplier and item resolution.
