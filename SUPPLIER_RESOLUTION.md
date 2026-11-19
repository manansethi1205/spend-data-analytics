# Supplier token matching and measured limits

The resolver now accepts a long-name pair when either normalized character
similarity is at least 0.94 **or** legal-suffix-stripped token-set Jaccard is at
least 0.8. Both require identical sorted numeric tokens, preserving leading zeros
and repeated numbers. Unicode/accent/case normalization is retained. Tokenization
uses original names before the old compact name key removes word boundaries.

Shared-token candidate lookup complements character-prefix lookup, so reordered
names with different prefixes can meet. Numeric signatures partition candidate
blocks, broad blocks are bounded at 200 names, and ambiguous matches stay split.
Complete-link acceptance requires a new name to match every member of a cluster,
preventing chains of weak edits from bridging increasingly different names.
Short names retain conservative exact-name handling. No labelled alias table or
company-specific supplier names enter inference.

```yaml
entity_resolution:
  supplier_similarity_threshold: 0.94
  supplier_jaccard_threshold: 0.8
```

These are defaults; accepted thresholds are finite numbers in [0.5, 1]. Supplier
identity still uses scoped vendor IDs and normalized names as independent
evidence. Equal vendor IDs across ERPs are not automatically joined.

## A tuning result

Run the offline comparison with a new private destination:

```powershell
uv run --locked python tools/tune_supplier_resolution.py --data-dir "<kit-root>" --report-dir private/supplier_tuning/new_run
```

All candidate supplier/item partitions are produced before golden labels open.
The script compares the exact legacy clustering against six candidate settings:
sequence 0.94 with Jaccard 0.8/0.85/0.9/1.0, and sequence 0.92/0.90 with Jaccard
0.8. It uses the existing pairwise/B-cubed metrics, reports false/missed pairs,
and selects on development suppliers with a 99% minimum pair precision. A
deterministic golden-supplier-disjoint audit and full-set metrics are also
reported. Outputs, mappings and detailed diagnostics stay in ignored private
storage. Input/source hashes are checked; no API is called.

| Full A ERP metric | Legacy | New default | Other five candidates |
| --- | ---: | ---: | ---: |
| Supplier pair precision | 100% | 100% | 100% |
| Supplier pair recall | 9.99946% | 9.99946% | 9.99946% |
| False merged supplier pairs | 0 | 0 | 0 |
| Missed supplier pairs | 203,705,694 | 203,705,694 | 203,705,694 |
| Predicted supplier groups | 191 | 191 | 191 |
| Golden supplier groups | 70 | 70 | 70 |
| Item pair precision | 99.99559% | 99.99559% | 99.99559% |
| Item pair recall | 48.07891% | 48.07891% | 48.07891% |

The requested Jaccard change handles reordered synthetic examples, but it does
**not** produce a measured recall lift on the supplied A data. Defaults remain
0.94/0.8; more aggressive tested character thresholds do not improve this result.
The full tuning/evaluation took 146.92 seconds, not a per-company runtime claim.

One golden supplier key spans 122 distinct raw names across 20,891 ERP records;
all 203,705,694 missed pairs belong to that group. Many names have no lexical
identity connection. This could represent parent identity or an unavailable
crosswalk; it is not proof that the labels are wrong. Merging these unrelated
names solely because labels put them together would memorize private identities
and would not establish transferable A2/C matching. No such map was introduced.

The golden-key-disjoint audit contains only nine suppliers/1,297 rows and already
scores 100% precision/recall under the legacy resolver; the large difficult group
is in development. That audit cannot support a claim of broad recall improvement.
Full-A numbers are development evidence after threshold tuning, not blind-test
accuracy. The desired 40–50% supplier recall has not been achieved.

## B scope and item resolution

B has eight source systems, 3,995 unique nonblank vendor ID strings and 74 ID
strings reused across source systems. It contains zero supplier names. Its seed
labels contain category/inclusion values, but no supplier golden keys. Neither
ID reuse nor category agreement establishes global supplier identity, so ERP
scoping remains unchanged. A supplier master/cross-ERP crosswalk or identity
labels would be needed to validate changing that scope.

Item rules were not broadened by transferring a supplier-name threshold to item
specifications: shared words/numbers do not establish identical dimensions,
material or unit. The tuning script measures item metrics to catch collateral
effects; these remain unchanged. Existing code consistency, specification/unit
checks and duplicate inheritance remain active. Final selected submission CSVs
are unchanged and remain historical artifacts of their earlier resolver version.
