# Label-assisted classification

Labelled retrieval is an explicit opt-in for a known company. The normal pipeline
does not read label files or load an index. Omit `--retrieval-index` for C, for
the A labels-hidden experiment, and whenever a labelled reference is unavailable.
Index loading rejects a different company or category tree, including changed
category names/paths. No category names are hard-coded in the implementation.

## Build boundary

The builder first runs the configured pipeline in forced local mode with label
loading disabled. It recomputes the related-record groups and requires exact
agreement with the supplied pilot freezes. Input/config hashes, freeze integrity
and company/tree must also match. Historical application code may differ; this
does not allow changes to the evaluation population or grouping.

All held-out groups and all groups containing any supplied pilot record are
excluded from training. For B, supply both the labelled and challenge freezes.
Only included, labelled rows outside those groups contribute examples. Missing,
excluded or out-of-tree labels are skipped. Golden supplier/item keys are never
copied into the index. Categories and example contexts are confidential, and the
builder only writes under ignored `private/`, refusing existing destinations.

```powershell
uv run --locked python tools/build_retrieval_index.py --config configs/company_A.yaml --data-dir "<kit-root>" --reference-freeze private/pilot/v2/A/freeze.json --output private/retrieval/v1/A/index.json
uv run --locked python tools/build_retrieval_index.py --config configs/company_B.yaml --data-dir "<kit-root>" --reference-freeze private/pilot/v2/B/freeze.json private/pilot/v2/B_challenge/freeze.json --output private/retrieval/v1/B/index.json
```

Each index records training-row/group provenance, excluded groups, evaluation IDs,
source/config/code hashes and an integrity digest. Loading rechecks company/tree,
integrity, positive support counts, valid category paths and disjoint provenance.
This detects accidental corruption; an editable hash is not a security signature.
Do not merge an evaluation group's labels into a later index while reporting its
score as independent. New evaluation cohorts require rebuilt exclusion manifests.

## Retrieval and prediction

The retriever uses a local inverted TF-IDF index of word/character features.
Description/service text has full weight, account description 0.4 and material
type 0.15. This is lexical retrieval, not a pretrained semantic embedding model.
Up to four examples are retrieved, using cosine similarity >=0.2 or an exact
source-system-scoped item-code match. Those limits are initial development choices.
Scoped codes are hashed locally and never sent in API example fields.

Identical context/code examples retain every labelled category and its support,
including minority labels. Codes and examples provide evidence rather than a
forced category assignment. Local retrieval aggregates normalized category votes;
its confidence is an uncalibrated evidence margin, with conflicts flagged. Without
evidence, the existing taxonomy lexical classifier provides the fallback.

Run locally without API requests:

```powershell
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --classifier local --retrieval-index private/retrieval/v1/A/index.json
```

For LLM classification, the same opt-in supplies retrieved contexts, possible
category paths, support, similarity and evidence type to the existing bounded
backend. Supplier names, raw item codes, source IDs and provenance are not sent as
reference fields. The LLM is instructed to consider noisy/conflicting examples
and always return a valid terminal category ID. This mode sends additional
confidential development-example context to OpenAI; inference still does not
open source label files. It uses a distinct `cantill-labelled-openai-v1` cache
namespace incorporating the index fingerprint and full reference context.
Zero-label backends reject contexts containing labelled examples.

```powershell
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --classifier openai --retrieval-index private/retrieval/v1/A/index.json --llm-max-requests 20
```

That command permits a bounded, potentially partial API run: inspect method and
budget flags. Remaining rows retain retrieval/lexical fallback. It is not an
equal-coverage pilot comparison or a final full-run command. API failures do not
change spend, inclusion, supplier/item keys or the output contract. Summary
`labels_used` is true when an index is supplied. Without it, normal zero-label
and local-fallback behavior remain available.

## Evaluation scope

### Prepared retrieval-assisted LLM pilot

The comparison implementation is ready in [pilot_retrieval.py](./tools/pilot_retrieval.py).
Its current immutable snapshot is `private/pilot/retrieval_v2/freeze.json`.
It contains the same A 40, B 40 and B challenge 12 records, their retrieved
examples, local retrieval fallbacks, index fingerprints and original zero-label
predictions. Both B cohorts use the same index with their combined related groups
excluded. Original contexts, IDs, spending values and groups are checked against
the historical baseline; query categories are not supplied to the LLM.

Run from the PowerShell terminal where the API key works:

```powershell
uv run --locked python tools/pilot_retrieval.py run --data-dir "<kit-root>" --execute
```

Omitting `--execute` previews the comparison offline without API requests. Defaults
permit at most 95 requests: 40 A, 40 B, 12 challenge and three fresh synthetic
gates, with retries disabled. The conservative token allowance is three million,
divided equally across cohorts. Offline reservation estimates including gates
are 508,177 A, 453,472 B and 133,855 challenge; all fit the default allowances.
These byte-based estimates are application safeguards, not exact billing limits.
Insufficient allowances fail before the first API request. A failed cohort stops
subsequent cohorts, and API/caching failures cannot produce a complete comparison.

Each cohort uses a new private cold cache followed by a cache-only warm run with
zero request allowance. Both use the labelled namespace and same index fingerprint.
The synthetic authentication gate has no labels or company data. Labels open for
scoring only after all inference has stopped. API failures use the same retrieval
or lexical fallback as production, with partial coverage reported explicitly.

Reports and per-record predictions are saved under
`private/pilot/retrieval_v2/runs/<id>/`. Each report includes original zero-label,
lexical, retrieval, assisted hybrid and API-only metrics, scoring denominators,
strata, spend weighting, paired corrections/regressions, actual token usage,
public-price estimates, timings and warm-cache checks. No model is selected
automatically. A blocked/partial/cache-failed execution exits nonzero.

The original zero-label comparison is a historical v1 run, not a fresh stochastic
repeat. The assisted classifier uses the current v2 base prompt plus references,
so a change versus v1 cannot be attributed solely to retrieval. Also compare with
the historical v2 zero-label results (35% A, 72.5% B), and preserve reserved groups
for final strategy evaluation. Eleven challenge rows still lack scoring labels.
No assisted accuracy gain or model winner is claimed until the live run is scored.

After an intentional code/index/input change, prepare a new root rather than
editing the existing snapshot:

```powershell
uv run --locked python tools/pilot_retrieval.py prepare --data-dir "<kit-root>" --pilot-root private/pilot/retrieval_next
uv run --locked python tools/pilot_retrieval.py run --data-dir "<kit-root>" --pilot-root private/pilot/retrieval_next --execute
```

The current suite passes 506 tests, including 15 retrieval-pilot checks for training
provenance, budget rejection, inference-before-label-scoring, authentication stops,
cache isolation/failure, production-equivalent fallback and baseline context drift.
Live execution still requires the working terminal credential; offline preparation
and mocked requests do not establish retrieval-assisted LLM accuracy or cost.

The user subsequently completed this development pilot. Verified terminal accuracy
was 37.5% A and 87.5% B (40 scorable rows each), compared with historical v1 values
35% and 80%. Spend-weighted accuracy was 54.78% A and 99.83% B. A corrected two
original errors and regressed one; B corrected five and regressed two. All 92
contexts received API decisions; warm runs reproduced them without requests.
The reported usage implies USD 0.09574860 including three gates. These are small,
reused development samples; the challenge still has only one scorable row.
The fixed candidate now proceeds to the separately prepared evaluation in
[HOLDOUT.md](./HOLDOUT.md), without prompt or index tuning.

The builder scores local retrieval with lexical fallback on the supplied pilot
records only after the index is built. Reports distinguish training size,
retrieval coverage, scorable rows, strata, hierarchy accuracy and spend weighting.
These are reused development diagnostics, not final reserved-group scores.
No retrieval-assisted LLM accuracy is established by the offline report.

The initial private indexes were built from 18,822 A training rows (3,201 distinct
context/code examples) and 866 B training rows (460 examples). B's labelled and
challenge pilots share one record, so their union contains 51 rows, of which 40
have scoring labels. Retrieval found evidence for 36/40 A and 41/51 B union rows.

| Fixed development sample | Lexical terminal accuracy | Retrieval with lexical fallback | Retrieval spend-weighted accuracy |
| --- | ---: | ---: | ---: |
| A, 40 scorable rows | 10.0% | 27.5% | 46.69% |
| B union, 40 scorable rows | 32.5% | 77.5% | 96.30% |

These results do not exceed the original LLM's terminal accuracy (35% A, 80% B).
They support testing retrieved evidence with the LLM, not replacing the LLM based
on these samples. The high B spend-weighted score is sample-specific. Training
provenance was independently checked against every reserved/pilot-related group;
no evaluation context is present in either example index. No API calls were made
to build or score these indexes. The full 491-test suite passes, and offline wheel
and source builds contain the retrieval module without private inputs or indexes.

For reproduction from a clean checkout, regenerate reference freezes with the
current `pilot_classification.py prepare` commands in [PILOT.md](./PILOT.md), then
build the indexes from the original build kit. Private freezes/indexes are not
published. Keep the original kit and private indexes available for A2/B2; do not
train on blind-test labels or silently rebuild a model from a different dataset.

The next measurement compares the original zero-label LLM, local retrieval and
retrieval-assisted LLM on identical frozen development records, then reserves a
separate final evaluation for the selected strategy. Existing v1/v2 reports remain
historical evidence; their old code fingerprints intentionally reject new runs
after implementation changes. Do not overwrite their freezes to bypass that check.

Full local inference with the real private indexes also passed with source label
reads blocked. A processed 65,549 records (46,325 included) in 127.34 seconds;
45,870 included lines used retrieval and 455 used lexical fallback. B processed
41,028 records (37,910 included) in 52.38 seconds; 20,522 used retrieval and
17,388 lexical fallback. All included paths were valid runtime-tree terminals.
Both runs made zero API requests. These are measured local runtimes on this
machine, not retrieval-assisted LLM runtime forecasts. B retains its eight
financial exceptions and remains blocked from final export.
