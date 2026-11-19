# Finalized A and B outputs

The user selected these saved outputs for finalization without further paid API
requests. Copies are byte-for-byte identical to the selected run exports and were
independently revalidated against source record IDs and runtime category trees.

| File | Input records | Included | Excluded | LLM/cache classified included rows | Local fallback included rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| [manan__A.csv](./manan__A.csv) | 65,549 | 46,325 | 19,224 | 46,325 | 0 |
| [manan__B.csv](./manan__B.csv) | 41,028 | 37,910 | 3,118 | 18,054 | 19,856 |

B retains 10,661 local retrieval classifications and 9,195 local taxonomy
classifications after credits were exhausted. Its historical run remains marked
`partial_api_or_cache`; finalizing that output does not turn it into complete LLM
coverage. No inference was rerun or categories changed during finalization.

B also retains eight disclosed financial estimates: three blank source amounts
represented by zero and five absent invoice-month FX rates approximated with the
nearest supplied month. See [FINANCIAL_POLICY.md](../FINANCIAL_POLICY.md).

Validation establishes row/format/tree conformance, not category accuracy or true
spend. Reserved-sample scores in [APPROACH.md](../APPROACH.md) are not measured
accuracy for these full outputs. Confidence is uncalibrated. Successful cold
runtime remains unverified, and historical total API cost is unknown. No further
API requests were made to finalize these files.

The user has confirmed that the original deadline no longer applies. Finalization
did not submit a form. The project was subsequently published at
[manansethi1205/spend-data-analytics](https://github.com/manansethi1205/spend-data-analytics).
Raw inputs, reference indexes,
caches and detailed financial audits remain private. Future blind-test files
require their actual data and, for C, a new configuration and tree.
