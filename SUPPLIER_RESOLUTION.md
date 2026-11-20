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
Short names retain conservative exact-name handling. This default path uses no
labelled aliases. Known companies can explicitly enable the supervised crosswalk
below; omitting it preserves the original resolver for C and zero-label runs.

```yaml
entity_resolution:
  supplier_similarity_threshold: 0.94
  supplier_jaccard_threshold: 0.8
```

These are defaults; accepted thresholds are finite numbers in [0.5, 1]. Supplier
identity still uses scoped vendor IDs and normalized names as independent
evidence. Equal vendor IDs across ERPs are not automatically joined.

## Supervised supplier crosswalk for A/A2

The supplied A golden supplier keys are legitimate training data for supplier
resolution, just as category labels are for classification. A company-specific
name crosswalk can transfer to fresh A2 records when names recur; transfer to C
is not required. The earlier rejection of this approach was too restrictive.

Build and evaluate an artifact using a new private destination:

```powershell
uv run --locked python tools/build_supplier_crosswalk.py --config configs/company_A.yaml --data-dir "<kit-root>" --report-dir private/supplier_crosswalk/v1
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<A-or-A2-root>" --supplier-crosswalk private/supplier_crosswalk/v1/supplier_crosswalk.json --classifier local --output private/A_supplier_assisted.csv
```

The build command loads labels explicitly, shuffles sorted labelled record IDs
with seed 2026, and trains on 18,514 rows. Predictions for the remaining 18,515
rows are frozen before fitting the production artifact on all 37,029 labels.
The label-free resolver may use all unlabelled source rows, including tool rows.
This is a row-disjoint recurrence evaluation, not a chronological or unseen-name
test and not an estimate of A2's name distribution.

| Half-label held-out measurement | Result |
| --- | ---: |
| Training normalized names / ambiguous names | 181 / 0 |
| Held-out name occurrences covered | 18,504 / 18,515 (99.94059%) |
| Held-out distinct normalized names covered | 168 / 178 |
| Covered rows with correct golden supplier | 18,504 / 18,504 (100%) |
| Baseline supplier pair precision / recall | 100% / 10.06720% |
| Assisted supplier pair precision / recall | 100% / 99.87024% |
| Assisted false merged / missed pairs | 0 / 72,750 |
| Production normalized names / ambiguous names | 191 / 0 |

Artifacts contain normalized names and opaque company/golden-group keys. They
are confidential derived data and stay under ignored `private/`, alongside the
half-label artifact, held-out predictions and aggregate report. No raw golden
key is used as the public output key. Names mapping to multiple golden groups
are excluded from the crosswalk and flagged at inference. Unseen/short/blank
names retain the current resolver. Exact normalized-name hits override supplier
keys before item resolution; existing duplicate inheritance cannot overwrite
a direct crosswalk hit. No fuzzy match to a labelled alias is introduced.

Runtime reads only the explicitly supplied artifact, never the source label
file. Company/protocol mismatch fails rather than applying another company's
aliases. Summary fields separate supplier and classification label use. The
crosswalk is independent of category retrieval: it can be combined with a
classification retrieval index or used with local/API classification. The local
example above makes no API calls. C and B omit `--supplier-crosswalk` and retain
their existing supplier policy.

Measured precision is perfect on this split, not a guarantee of zero future
risk: name reuse by different legal entities, changing supplier identity, noisy
labels or normalization collisions unseen during training can cause errors.
Training ambiguity abstention reduces that risk. Existing final submission CSVs
remain historical artifacts; enabling this option creates a new run.

The full A CLI run with this production artifact and local classification exports
and independently validates all 65,549 input records. Inclusion, exclusions and
per-record spend exactly match the selected submission. All 37,029 labelled ERP
rows form the 70 golden groups with 100% training-fit precision/recall; this fit
check is separate from the half-label result above. The complete suite passes
583 tests. The local verification output stays private and does not replace the
selected LLM-classified submission.

## A label-free tuning result

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
and would not establish transferable C matching. The optional supervised map
above deliberately learns A's provided identities for recurring A/A2 names;
these label-free tuning results remain valid for runs without it.

The golden-key-disjoint audit contains only nine suppliers/1,297 rows and already
scores 100% precision/recall under the legacy resolver; the large difficult group
is in development. That audit cannot support a claim of broad recall improvement.
Full-A numbers are development evidence after threshold tuning, not blind-test
accuracy. The desired 40–50% supplier recall has not been achieved.

## A vendor-account coverage and spend materiality

A follow-up audit joins A's ERP records to golden keys by record ID and examines
the largest group by distinct supplier names. Only 173 of its 20,891 rows have a
nonblank vendor ID; 20,718 (99.17%) do not. The populated rows use four distinct
scoped accounts, with 167, 3, 2 and 1 rows respectively. Each account belongs to
one golden group and one raw name. Only four of the 122 names ever have an ID;
the other 118 have no vendor-account bridge in the supplied ERP records.

The resolver already starts from a scoped vendor ID when present and joins its
normalized name as an alias. This supports name-only rows sharing that alias.
There is no shared vendor account connecting the 122 names. A diagnostic strict
ID-first partition that separates coded rows from existing name-only fallback
groups lowers full-A supplier pair recall from 9.99946% to 8.40494%, retaining
100% precision. That diagnostic removes useful alias links; it is not a proposed
replacement. Current account/name alias behavior is retained.

| Known ERP group spend | Value |
| --- | ---: |
| Net spend, ZAR | 1,178,429,361.39 |
| Absolute spend, ZAR (credit magnitudes included) | 1,192,125,445.67 |
| Share of ERP net spend | 46.15% |
| Share of ERP absolute spend | 44.73% |
| Known ERP group spend / final A net spend | 36.70% |
| Known ERP group absolute spend / final A absolute spend | 35.68% |

This is the largest of A's 70 golden supplier groups by both net and absolute
ERP spend, so it is material in the supplied data. Calculations use exact
decimal amounts; ERP amounts are already net ZAR. The full-A denominator is the
selected submission's included spend, with excluded rows contributing zero.
Golden membership is only known for ERP rows: no unmatched tool purchase is
assigned to this group by assumption. These shares do not predict its A2 share
or scoring impact; supplier scoring weights are unspecified. Detailed account
diagnostics remain private. No inference rule, output CSV or B scope changed,
and no API was called.

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
