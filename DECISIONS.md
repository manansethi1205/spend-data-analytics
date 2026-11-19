# Decisions and unresolved policies

## Status and evidence boundary

This log begins with stage 2 profiling. `Accepted` means an implementation
direction has evidence or an explicit brief rule; it does not mean the code was
implemented at that milestone. `Pending` means evidence was incomplete or policy
had not been chosen. Later entries record implementation and measured results.
Current release status is in [REHEARSAL.md](./REHEARSAL.md); final named A/B
submission outputs remain incomplete.

Aggregate evidence is in `DATA_PROFILE.md`; confidential record-level evidence
and hashes are in ignored `private/profiling/profile.json`. The profiling utility
must not become a source of golden-label mappings for inference or evaluation.

## D01 - Keep confidential audit artifacts local (accepted)

Added `.gitignore` before generating diagnostics, as a prerequisite for this audit.
Ignore `private/`, `data/`, supplied confidential filenames, secrets and caches.
The public profiler contains schema names and generic audit logic, not records,
supplier names, account mappings, labelled examples or hard-coded categories.
Do not publish private diagnostics. Submission output CSVs remain permitted by
the brief and are not blanket-ignored. Full Git/history auditing belongs to release.

## D02 - Parse source dates explicitly and retain originals (accepted direction)

ERP A and B nonblank dates are ISO. A tool has three observed formats, with slash
evidence supporting day-first: 2,050 day-first-only dates, no month-first-only
dates, and 1,195 dates with different valid interpretations. Configure that source
as day-first; retain original values and flag missing/ambiguous dates. Do not
require dates for every A match: most A dates are missing.

For B, distinguish syntax from chronology. All nonblank dates parse, but 149
invoice/posting gaps exceed 366 days. Flag anomalies; do not silently replace
invoice date with posting date or call every out-of-year date impossible.

## D03 - Normalize financial values according to the brief (accepted)

- Preserve A `value_zar` as net ZAR even where document-currency metadata differs.
- Parse A tool VAT representations before division by `1 + rate`. Missing means
  15% under the supplied rule; explicit zero remains zero.
- Preserve B USD values; divide non-USD by positive line rate or invoice-month FX.
- Configure dot decimal parsing for observed B numbers. A three-decimal quantity
  or FX value is not a thousands group merely because it ends in three digits.
- Preserve original strings, signs and conversion provenance.

No default VAT is inferred for B, which has no VAT field. Its amount semantics
must be explicit in config and documentation; the supplied brief prescribes USD
conversion but provides no additional B tax-removal calculation.

## D04 - Missing financial values (flagged); final included-row resolution (pending)

Three B rows have missing amounts; they have no seed labels and no direct unit
cost field. Five non-USD rows lack both line rates and invoice-month FX, also
without seed labels. Posting-month FX exists for those five but would be an
exception to the stated rule. Do not choose nearest/posting month, zero spend,
fabricated amounts, or an invented exclusion code silently.

Stage 6 exposes these separately as `AMOUNT_MISSING` and `FX_RATE_MISSING`, with
`None` reporting values and `financial_ready=False`. It does not impute amounts,
substitute posting/nearest-month FX or exclude records for financial incompleteness.
All eight exceptions remain visible for stage 7 eligibility/context review. A final
included unresolved value cannot pass the output validator; obtain a justified
resolution or fail clearly before publication. The final treatment of those eight
records remains pending, rather than being silently represented as zero spend.

## D05 - Missing payment is not non-approval; unavailable status stays explicit

B has no explicit status column. The included seeds contain 617 records with
blank paid date, while 412 excluded seeds have paid dates. Do not equate payment
presence with procurement eligibility or payment absence with non-approval.
ERP A similarly has no explicit invoice status field; A tool does.

Stage 7 implements exact tool status mappings. Exports without a status mapping
use an explicit `unavailable` policy: keep candidates absent non-procurement evidence
and flag `STATUS_UNAVAILABLE`, without claiming verified approval. Config cannot
ignore a declared status. This is an operational convention for incomplete exports,
not a supplied fact about approval. Document types alone are not validated status
mappings. Actual approval on status-absent records remains an information limitation.

## D06 - Preserve credits and zero values for investigation (accepted direction)

There are 434 negative ERP A values, 321 negative tool gross amounts, and 833
negative B amounts. B also has 918 zero amounts. Signs alone do not prove
non-procurement, cancellation or duplication. Preserve signs through conversion;
inspect document and purchase context before exclusions. Credit/reversal
eligibility and spend-weighting conventions must be finalized in stages 7/12.

## D07 - Match purchases using multiple fields and allocation capacity (implemented)

Source IDs identify input rows, not necessarily real purchases. A PO extraction
experiment retrieves candidates for 16,743 tool rows; 2,405 have multiple ERP
candidates at exact net cents. Repeated lines within POs/invoices are common.
Candidate retrieval is not enough to mark duplicates. Stage 8 implements
line/group granularity, supplier/quantity/text evidence and quantity/amount budgets;
see D18 and `MATCHING.md`. Earlier candidate counts are descriptive, not truth.

Fifty tool excess rows and 613 B excess rows are identical to another row except
for source ID. Treat these as high-priority review candidates, not automatically
verified duplicate exports. Stage 8 applies a stricter normalized business
fingerprint and flags conflicting invoice-line versions. It retains ERP for
supported cross-source overlaps.

## D08 - Scope identifiers and use golden labels only in permitted routes (accepted)

B has 74 vendor IDs and nine material codes used across multiple source systems.
Use source-scoped identifiers as the initial representation; merge across systems
only with supporting evidence. No supplier names or golden B supplier labels exist
to establish every cross-system identity. Do not claim those identities are solved.

A supplier names and source/vendor codes are consistent with golden supplier
keys where present. Use them for development/evaluation only in labelled routes.
Item scoring must report coverage: 15,816 A golden item keys are blank.

## D09 - Excluded-row output convention and primary reason precedence

The template demonstrates blank categories with populated entity keys/confidence
on a duplicate, but does not define every excluded-row case. Stage 5 validation
therefore permits blank or populated keys and either entirely blank or valid full
category paths on excluded rows. Whitespace-only keys are not useful keys. Included
records require both keys and a complete terminal classification. Confidence must
be finite and in [0, 1] on every row.

Our planned exporter will leave excluded categories blank, retain supported keys
where available, and use exclusion-decision confidence (0 if unassessed). Included
confidence describes classification. This is a local convention, not an additional
brief rule or implemented exporter. Stage 7 uses cancelled before not-approved,
then non-procurement. Stage 8 marks duplicates only among eligible candidates,
without replacing existing exclusion reasons. All matched evidence remains visible.
This ordering resolves overlap where the brief does not define precedence.
Mandatory reason/spend rules remain
unchanged: permitted code, zero excluded spend and blank included exclusion reason.

## D10 - Blank descriptions need separate evaluation (accepted)

B has 16,695 blank descriptions, including whitespace-only strings. Of these,
12,525 have a material number; 4,170 do not. All included seed descriptions are
nonblank after trimming. Report coverage separately and evaluate blank-description
handling through reviewed samples or other defensible evidence. Do not extend a
seed-only accuracy claim to that population.

Use available item/context fields with honest confidence. Account text is not
necessarily item text; 21 of 28 labelled source/account groups span categories.
A also has 282 exact-description strings spanning categories. Text identity or
account identity is not a universal category lookup rule.

## D11 - Procurement rule evidence and noisy labels (implemented with limits)

Seeds provide 450 non-procurement examples and evidence of accounting/supplier
context, but document types and some contexts mix included/excluded examples.
The stage 2 audit learned no production rule or threshold. Stage 7 froze a
description-grouped split before rule development and adopted generic intercompany
account and explicit tax-control evidence. No per-record lookup or opaque
supplier-type blacklist is shipped. The first reserved evaluation exposed missed
tax wording; the amended rule's subsequent all-seed match is a development recheck,
not independent validation. Original metrics and replay config remain preserved.

Full-label descriptive profiling has already happened. A later development holdout
is not equivalent to a never-seen external test; disclose this limitation. The
actual blind test remains independent. Strict A labels-hidden inference must
exclude every A-golden-derived artifact and use labels only after prediction.

## D12 - Generalize configuration and tree handling before freeze (accepted direction)

Current trees are valid three-level trees. Implement generic runtime path loading
and validate synthetic four-level/variable-depth cases before the build deadline.
No C input schema is available; arbitrary-schema support is not yet demonstrated.
Schema mappings in `DATA_PROFILE.md` were specifications at stage 2; A/B configs
and generic ingestion are now implemented in stage 4 (D14). Do not embed the
A-specific PO token pattern as a universal assumption.

## D13 - Isolated, locked project setup (accepted and verified)

Stage 3 uses an installed `src/cantill` package, Python 3.12, `pyproject.toml`,
`uv.lock` and a local `.venv/`. The native CPython 3.12.11 environment was verified;
the shell's unrelated Python lacks pip and is not used for project installation.
uv's default user cache was not writable, so project configuration keeps its
cache under ignored `.cache/uv` without changing global settings.

The current runtime dependencies are pandas/PyYAML for upcoming ingestion/config
work; pytest is development-only. ML/API dependencies are deferred until needed.
Installed versions are recorded by the lock; no API keys or model downloads are
required. Standard build dependencies are declared separately in `pyproject.toml`.

Verification: installed help/version entry points and imports pass; locked offline
re-sync and `uv pip check` pass; all 26 synthetic-path confidentiality tests pass.
Built wheel/source archives contain only declared package/metadata files and no
confidential data or caches. Local build artifacts stay in ignored
`private/build-check/`. There are currently no tracked files or commits, so there
is no historical data exposure to inspect yet; repeat index/history review before
publication. No commit or publication was performed during setup.

At stage 3 the CLI exposed only help/version. Stages 4-8 now add ingestion,
normalization, eligibility, matching and output validation. The final
submission-producing command is not available yet.

## D14 - Lossless ingestion with opt-in label references (implemented and verified)

Stage 4 implements `configs/company_A.yaml`, `configs/company_B.yaml`, safe
YAML/JSON configuration and one shared ingestion path. CSV cells remain strings:
no trimming, NA inference, identifier coercion, tax calculation or date repair.
Each canonical row preserves all source columns in `raw`, mapped semantic fields,
logical source, one-based data-record ordinal and its exact prefixed output ID.
Unmapped future columns remain in `raw`. Source parsing/amount declarations stay
in config for use by later processing stages.

Runtime taxonomy paths support one to four levels with variable-depth leaves;
paths and FX currency/month keys are validated structurally. Source IDs must be
nonblank and output IDs globally unique. Repeated source file paths, malformed
CSV widths, duplicate headers, missing mapped columns and invalid configs fail
clearly. Header-only purchase files are valid. Input cell anomalies remain for
later parsing/flags, preserving the one-record-per-input contract.

Labels are not opened during default ingestion, even when their path is configured
or the file is missing. `--with-labels` loads a separate table with exact ID joins;
it never merges golden categories or entity keys into canonical purchase fields.
This prevents accidental ingestion leakage, but does not replace the later strict
labels-hidden inference/evaluation protocol. No classifier exists yet.

Verified every original cell and source-derived ID for all 65,549 A and 41,028 B
purchase records. Loaded all 37,029 A and 3,000 B labels separately and confirmed
identical canonical records with/without labels. All eight source hashes match
the stage 2 audit. Confidential verification summaries remain in ignored
`private/ingestion/verification.json`; no submission outputs are produced.

The synthetic suite now has 70 passing tests, including the original 26 privacy
checks, a new schema with a four-level tree, same-config fresh records, alternate
delimiters, lossless blanks/multiline text and invalid-input handling. This verifies
ingestion generality, not arbitrary C schema support or classification accuracy.
Financial exceptions and approval policies from D04-D11 are still unresolved.

## D15 - Structural output validation before spend generation (implemented)

`cantill.output.validate_output` and CLI `validate-output` read a candidate CSV
against exact ingested source IDs and runtime taxonomy paths, without labels.
Header order and strict CSV structure, exact ID coverage, keys, inclusion/reasons,
finite spend/confidence and complete terminal paths are checked. Negative and
included zero spend are valid; numeric locale repair belongs to normalization.
Dot-decimal/scientific values are accepted; grouping separators and null/nonfinite
tokens are not. Names and IDs are compared exactly without silent trimming.

Exact decimal aggregation avoids process-context rounding. Totals are exposed by
`summary()` only for a fully valid file. Diagnostics count all detected row-level
errors while retaining at most 20 examples with ordinals and codes, never raw
record values. Structural CSV failures may prevent further checks. Excluded-row
behavior follows D09. Passing the contract does not establish spend, grouping,
matching, category or confidence accuracy.

The suite has 147 passing tests including prior stages, and verifies invalid
outputs cannot pass merely by matching row count. Valid CLI exit is 0, invalid
output is 1, and config/source/argument failure is 2. The validator never repairs,
rewrites or generates submissions. No actual A/B prediction outputs exist yet.
See `OUTPUT_VALIDATION.md` for the full contract and API.

## D16 - Preserve uncertainty during financial/date normalization (implemented)

Stage 6 adds `normalize_company` and CLI `normalize`, preserving original records
and adding Decimal/date values, conversion provenance and explicit quality flags.
Tax/FX calculations use 50 significant digits without cent rounding; identity and
zero-VAT values avoid unnecessary division. Dates follow configured formats and
distinct matching dates are marked ambiguous rather than selected arbitrarily.
Chronology flags use the same diagnostic definitions as the stage 2 audit and do
not imply cancellation, non-approval, non-procurement or date repair.

A ERP values stay net ZAR; tool VAT defaults only for blank rates. B remains
as-provided for tax. Reporting-currency values ignore rate metadata; positive
direct rates take precedence; blank foreign rates fall back strictly to invoice-
month FX. Invalid nonblank rates do not silently fall back. Direct rate direction
is configurable. The monthly units-per-USD reference has explicit number/month
formats and supports USD reporting only. Normalized reference-key collisions fail
clearly, while invalid/missing rates are flagged on affected records.

Real A: all 65,549 financial values resolve, including 6,542 specified VAT defaults.
Real B: 41,020 resolve; the eight exceptions match D04. The normalizer reproduces
the audited 149 long invoice/posting gaps, 233 invoices after posting, 13 due dates
before invoice and 16 paid dates before invoice. Original cells/IDs and source
hashes are unchanged. `tools/verify_normalization.py` independently checks every
computable amount with exact rational arithmetic and every mapped date against
the observed kit formats. It does not use labels. Detailed exception IDs remain
in ignored `private/normalization/verification.json`.

The full suite has 222 passing tests. CLI exit 1 means unresolved financial values,
not an invented exclusion; missing dates alone need not block an identity/direct
rate conversion. Later stages 7/8 implement eligibility and counting once; supplier,
item and category resolution remain. See `NORMALIZATION.md` for API/flag details.

## D17 - Traceable eligibility and explicit evaluation reuse (implemented)

Stage 7 adds `assess_eligibility`, CLI `eligibility`, configurable source statuses
and shared non-procurement rules. It returns candidate eligibility, primary reason,
all matching rule/field evidence, audit flags and candidate amount. Excluded amounts
are zero while original normalized values remain untouched. Financial data failure,
blank text, credit/zero values and missing payment do not themselves justify a
non-procurement reason. No numeric confidence is invented for rule decisions.

Seven generic patterns cover intercompany accounts/transfers, tax-control lines,
royalty payments, partner billing, financing and revenue controls. Only intercompany
and tax patterns have labelled B support; other patterns are verified synthetically,
not measured on real labelled examples. Additional/disabled rules and translated
status vocabularies support configuration-only adaptation. No categories, golden
record IDs or company-specific opaque supplier/account-code lists are embedded.

The fixed `cantill-eligibility-v1` split uses normalized description, or scoped
invoice identity for blank text, without target labels. It yields 2,446 development
and 554 reserved seeds. Stage 2 had already explored full-label descriptive
aggregates; the reserved set is not an untouched external test. Initial development
matched 2,446/2,446. Initial reserved matched 505/554 (91.2%): exclusion precision
100%, recall 45.6%, with 49 missed exclusions and no false exclusions.

Error review identified an explicit state/local-tax wording absent from the first
rule. The amended rule matches all 3,000 seeds, but those reviewed cases are now
development data. Do not present this as 100% independent held-out accuracy. Both
reports and the original-rule replay config/signature remain in ignored private
storage. Replaying the original config reproduces the initial numbers/signature.
See `ELIGIBILITY.md` for exact methodology and commands.

Full-data results: A retains 65,046 candidates, excluding 188 cancelled and 315
not-approved tool rows. B retains 38,545 candidates, with 2,483 non-procurement rule
exclusions: 2,041 intercompany controls and 442 tax lines. These whole-data rule
counts are not independent truth labels. All eight B financial exceptions were
reviewed and remain eligible candidates with unresolved amounts; no account/status
evidence supports excluding them. A ERP/B status absence is retained as a flag.

All 294 tests pass. Label-free integration verifies cells/IDs, normalized values,
source hashes, reason/amount invariants and explicit tool statuses. No record is
dropped. Duplicate detection is now implemented in stage 8; no final spend cube or submission
output is generated. Supported financial resolution for the eight candidates is
still necessary before export.

## D18 - Purchase allocations, repeats and residual uncertainty (implemented)

Stage 8 adds configurable preferred/secondary pairs and repeat-export sources,
`count_purchases` and CLI `deduplicate`. It keeps every original record and previous
exclusion, retains preferred ERP purchases, marks supported overlaps `DUPLICATE`
with zero counted spend and flattens links to retained roots. No input labels or
golden supplier/item mappings are used. Similarity scores are not probabilities
and must not be reused as category confidence.

Repeat fingerprints require invoice/supplier/line-or-item evidence and a resolved
amount. Numeric/date/reference representations are compared consistently, while
business context, invoice date and unknown extra fields remain significant.
Approval/payment/due/posting lifecycle changes do not create another purchase.
Conflicting invoice-line versions stay visible instead of choosing an arbitrary
latest/largest value. Without line IDs, repetition is inherently less certain and
flagged. A enables tool repeats; B enables invoice repeats; ERP A is not collapsed.

Cross-source passes use indexed PO/amount candidates, quantity, supplier/text and
line evidence, then bounded receipt/invoice groups and unit-price quantity coverage.
Missing-PO matches use stricter evidence and a date window where dates are available.
Wrong known PO/line references are not ignored to force a match. Candidate ambiguity,
numeric-description disagreement, missing dates, weaker names and incomplete
coverage are traceable. Strong known-PO matches may outweigh faulty dates/text,
with that uncertainty preserved rather than claiming repaired values.

The data shows smaller invoices covered by larger receipts and invoices spanning
same-item receipts. Quantity coverage consumes per-pair quantity and amount budgets;
later invoices cannot reuse consumed receipt quantities. Partially covered invoice
records remain included at their full original normalized amount with a flag. No
unsupported residual spend is invented. These retained overlaps and ambiguities
can cause residual double counting; no complete matching recall is claimed.

Chosen tolerances/thresholds are explicit config values, not supplied rules or
measured optimal settings. Groups and allocations use 60-digit arithmetic. No
arbitrary subset search, general chained-system optimizer or amount imputation is
implemented. A configured preferred source cannot also be a secondary source.

Current A results: 46,325 counted records, comprising all 37,029 ERP and 9,296 tool;
18,721 duplicates plus the earlier 503 status exclusions. Methods: 11,723 PO,
4,133 PO-line, 2,277 no-PO, 334 quantity-coverage, 5 receipt-group and 249 repeated
exports. Current B: 37,910 counted, 635 equivalent export repeats and the earlier
2,483 non-procurement exclusions. Repeated B invoice-line keys with conflicting
business fields are not blanket-excluded. B seeds evaluate procurement eligibility,
not complete duplicate identity; their eligibility scores do not validate matching.

All 353 tests pass, including 59 matching cases. Label-free real-data verification
checks cells/IDs, prior reasons, zero excluded amounts, unchanged included amounts,
retained duplicate targets, exact resolved-amount reconciliation and per-pair
quantity/amount capacities. All source hashes are unchanged. Stratified real
examples, including lower-score/grouped links, were reviewed for consistency with
their recorded evidence; this is not a labelled precision/recall study. Detailed
allocations, links and samples remain in ignored `private/matching/`.

The same eight B financial exceptions remain included: their invoice-line
identities are distinct and no supported repeat match resolves them. Supported
financial resolution is still required before export. Entity keys, categories and
final submission files remain future work. See `MATCHING.md` for configuration,
criteria, limits and reproducible verification.

## D19: Label-free entity resolution and conservative identity evidence (stages 9-10)

Vendor and material IDs are scoped by ERP (logical source when absent). Supplier
normalization removes legal suffixes and punctuation; exact name evidence connects
IDs, with bounded complete-link fuzzy matching for long names at 0.94 similarity
and matching numeric tokens. Unknown identities remain per-record groups. These
criteria are chosen engineering policies, not additional supplied rules.

Items use scoped catalogue codes; uncoded descriptions are supplier/unit-specific
and preserve specifications. Different codes can join on exact informative text,
supplier and explicit unit only when each code's text/unit signature is consistent.
Initial evaluation exposed recycled descriptions linking unrelated catalogue codes;
the generic consistency guard reduces false merged item pairs from 659,298 to 113.
That change used error review, so the final entity metrics are a development
recheck. No confidential alias/golden-key table is embedded in code or saved as
a public model. Hash keys are deterministic within an input set, not a persistent
cross-run entity registry or a confidentiality guarantee.

A supplier pair precision/recall is 100%/10.00%; B-cubed recall 47.33%. Golden
supplier groups can span unrelated anonymized names, so a label-free spelling
method cannot establish all aliases. No unsupported name merges are invented.
A item pair precision/recall is 99.9956%/48.08%; B-cubed precision/recall is
99.91%/89.76%. Item scoring covers only 21,213/37,029 ERP rows with nonblank labels.
There is no B supplier/item truth; scoped IDs are a conservative fallback, not
proof of globally resolved suppliers. See [BASELINE.md](./BASELINE.md).

## D20: Taxonomy-only lexical baseline, isolated inference and export (stage 10)

The local classifier builds word/character TF-IDF cosine representations from
runtime terminal paths only, with no category names or label-derived artifacts
in code. Description/service fields take priority over lower-weight account and
material-type context. It supports variable depth through L4. Generic English
normalization and character overlap are a baseline, not multilingual semantics.
Best-minus-next similarity is bounded confidence; it is not a calibrated probability.
No overlap/ties receive confidence zero and deterministic flagged paths.

A evaluation removes the labels config and rejects label-table reads throughout
inference; labels open only afterward for scoring. This demonstrates labels-hidden
inference, while prior aggregate profiling and eligibility label review remain
disclosed. Terminal accuracy is 15.26% A, 29.50% on 2,549 retained included B seed
rows. Absolute-spend-weighted results are 23.24% and 28.99%. Negative spend uses
absolute weights, missing spend is separately counted, and zeros have zero weight.
One included B seed is excluded as a purchase duplicate. These seed results are
biased toward available nonblank descriptions; there is no unseen-C measurement.
Weak lexical accuracy requires later improvements; structural coverage is not
semantic accuracy. Confidence-band results are retained in the private report.

`run` now executes the baseline with no API key or external calls. A's local output
passes all contract checks. Export is atomic after validation and cannot overwrite
configured input/reference files. Excluded categories/confidence are blank/zero;
their entity keys remain populated. The eight B financial exceptions still prevent
export; no unsupported spend, exclusion or date/rate correction has been added.
All 392 tests pass; source hashes remain unchanged. Latest inference takes about 71s A
and 32s B on the current Windows/Python 3.12.11 environment, excluding scoring/export;
this is not the final clean-release benchmark. Current API cost is zero.

## D21: Opt-in OpenAI integration, zero-label caching and usage bounds (11A-11C)

Company configs retain local mode by default. Optional local/openai/auto modes
and CLI overrides choose an API classifier after deterministic purchase processing.
The SDK reads OPENAI_API_KEY from the process environment; configs reject keys.
The model snapshot is configurable (initial candidate gpt-5.4-mini-2026-03-17),
not selected through a quality/cost benchmark yet. Only six semantic text/unit
fields and the runtime tree are transmitted; no supplier identities, amounts,
record IDs, labels or raw dictionaries. All input strings are untrusted data.

Structured terminal-ID output is independently validated before mapping back to
exact category paths. API results cannot alter earlier pipeline decisions.
Private atomic caches include company, protocol, model, prompt/schema, complete
tree and all transmitted fields. Only validated API decisions are cached. This
is a zero-label protocol; future label-assisted modes require separate namespaces.
API confidence is self-report, local confidence is lexical margin, and neither
is assumed calibrated. Method and uncertainty/fallback flags remain observable.

The initial allowance is 20 attempt slots, one retry, four workers, 30-second
timeouts and a conservative million-token application allowance. Reserve every
possible retry before scheduling, with deterministic context-hash order. Token
allowances use request UTF-8 bytes plus framing/output allowance and are not an
exact tokenizer count or guaranteed billing cap. Actual returned usage is reported
separately. SDK retries are disabled; bounded connection/transient retries and
401/403 circuit behavior prevent runaway calls. Failures use the local classifier;
openai mode requires a key and auto supports no-key operation. No exception/body
text or credential is logged. The endpoint is pinned to OpenAI and store=False;
this is not a broader data-retention guarantee.

All 440 tests pass. The real B zero-request run preserves 41,028 rows, classifies
37,910 included rows locally and retains eight unresolved amounts; its exit 1 is
the existing financial diagnostic. No company records were sent during integration
checks. A synthetic live request reached OpenAI but returned HTTP 401 for the
agent-visible credential. Live authentication and model access are unverified;
the next pilot must run with a valid credential in its launching process. No API
classification accuracy or cost improvement is claimed. See [LLM.md](./LLM.md).

## D22: Fixed development pilot, scorable/challenge cohorts and honest cost reporting (11D)

The pilot freezes label-independent connected groups before sampling: repeated
classifier contexts/descriptions, scoped items/invoices and matched purchases stay
together. Hash assignment reserves roughly one fifth of groups, not rows. Sample
only included development rows with deterministic unique-context round-robin
strata. No golden category/entity key defines a partition. Previous aggregate
baseline/eligibility review remains disclosed; these groups are not claimed to
be previously unseen by the developer.

Active private freezes are under private/pilot/v1: A ERP 40 examples without
label-based selection, B 40 included labelled seeds for scorable diagnostics, and
B 12 all-record challenges including two blank descriptions. Seed inclusion/ID
availability selects the B scored cohort but category values never enter inference.
The B seed bias is explicit: no included blank-description seed exists. Eleven
of twelve challenge examples have no usable category label, so no invented
ground truth or blank-description accuracy is reported. Fingerprints preserve
code/config/source identity; freezes cannot be overwritten or reused after changes.

A synthetic live gate must succeed before each model's company requests. Default
allowance is 41 attempts across all selected models (including gates), with no
retries; insufficient full-sample allowance sends no partial company subset.
Fresh cold caches and strictly zero-request warm runs separate API from cache
throughput. API failures after scheduling remain visibly partial. Scoring labels
open after every model's inference. Reports separate local, hybrid and API-only
denominators, strata, confidence and absolute-spend-weighted metrics. No automatic
winner is chosen from incomparable or incomplete coverage.

Standard public USD token rates are versioned with date/source and copied into
measured reports. Actual input, cached-input and output counts drive estimates;
unknown prices or failed-call usage produce null costs. Synthetic-gate cost is
separate. Scaling to 1,000 sample lines is explicitly not full-company forecasting:
unique-context stratification changes reuse and category mix. Account-specific
pricing/taxes are not inferred. These are estimates, not guaranteed billed amounts.

All 460 tests pass, including 20 pilot cases. Three real-data freezes/previews
verify unchanged source/code fingerprints with no company API calls. Local sample
terminal accuracy is 10.0% A and 32.5% B, with only 1/12 B challenge rows scorable;
these are small development diagnostics, not new whole-company or LLM scores.
A reserves 9,056 source rows and B 3,065 in held-out groups. Authentication retry
again returns HTTP 401 for the agent-visible credential. Actual API measurements,
model selection and cost remain pending valid authentication. See [PILOT.md](./PILOT.md).

## D23: Separate terminal/agent credential environments

The user reports a successful check-openai result using the configured model in
their PowerShell terminal. The agent's process has an OPENAI_API_KEY, but no saved
Windows User/Machine variable and no organization/project override were found.
Only presence/equality booleans were inspected, never key values. A process-local
PowerShell assignment does not update an already-running agent's environment;
different/stale process credentials are the likely cause of the differing results.
The exact working terminal value was not read or copied, so equality is not claimed.

A same-terminal launcher now runs all prepared cohorts while inheriting that
terminal's environment in memory. It never places credentials in arguments/files.
The default global allowance is 95 attempts (41 A, 41 B, 13 B challenge) and three
million conservative token units; every cohort retains its synthetic gate and
the launcher stops on a failed child run. Saving the working key as a User
environment variable and explicitly reloading it in an agent child process is
the alternative; registry values never silently override an application key.

All 464 tests pass, including four launcher checks. No frozen code/sample changed;
actual company-data API measurements remain pending an authenticated execution
environment. The success reported by the user is not a company classification
accuracy or cost result. See [PILOT.md](./PILOT.md) for the one-command workflow.

## D24: Successful live pilot and saved-result verification

The user's same-terminal launcher completed A, B and B challenge with the frozen
candidate `gpt-5.4-mini-2026-03-17`. All 92 company contexts received API decisions;
three synthetic gates bring the total to 95 requests. No application fallback was
needed. All warm decisions reproduced cold results with zero additional requests.
This resolves the execution workflow; it does not prove the separate agent
process credential changed.

An offline review verifies existing freeze/input/code fingerprints, exact sample
IDs/order, taxonomy terminal paths, finite confidence, saved metrics, token-price
estimates and reported warm-cache coverage. Its private aggregate supersedes the
earlier blocked-authentication summary. It does not make API requests or modify
the frozen classifier/configs/samples. Multiple matching measured reruns require
explicit review rather than silently choosing the most recent result.

A's terminal accuracy is 14/40 versus 4/40 local, with absolute-spend weighting
51.10% versus 24.99%. B is 32/40 versus 13/40, weighted 58.77% versus 19.30%.
A corrects 11 local errors and regresses one; B corrects 20 and regresses one.
Only one B challenge row is scorable (correct by API, wrong locally); eleven
unlabelled rows supply coverage evidence only. These are small stratified
development diagnostics, not held-out or population estimates.

Reported usage and saved standard prices imply USD 0.06445710 including gates.
A's input-cache usage is accounted for separately from the application cache.
This is an estimate, not a billing statement or full-company forecast. Only one
candidate model was measured, so no comparison winner is selected. A remains
weak on generic (1/12 correct) and non-ASCII (0/4) sample descriptions; its
confidence above 0.3 was only 12/26 correct. Subsequent improvements must preserve
the reserved groups and use a new freeze when classifier code changes.

## D25: Controlled zero-label prompt revision

The v1 A development errors include physical components mapped to service
categories with a shared application word. Generic descriptions also receive
equipment-specific guesses without supporting application information. The
candidate v2 prompt therefore adds category-independent goods/service evidence,
full-hierarchy interpretation and explicit application-ambiguity guidance. No
company category names, golden mappings, labels or new API parameters are added.
This targets an observed failure mode; it is not proof of an accuracy gain.

A's four non-ASCII pilot descriptions contain valid technical symbols when read
as UTF-8. The initial diagnostic used the Windows default encoding and displayed
mojibake; correcting that reader removed the apparent corruption. No encoding
repair is shipped. Unicode input preservation is verified with a mocked request.

Protocol v2 and the changed prompt isolate its cache from v1. The baseline's
private reports and frozen samples remain unchanged; current-code fingerprint
checks intentionally prevent replaying the old freeze after application changes.
Fresh v2 preparation retains the original selection algorithm and labels-hidden
inference. Record IDs, original contexts, local predictions, group assignments
and input hashes are compared across preparations before the next measurement.
No reserved-group labels are used for prompt tuning. The same-terminal launcher
is still required for live execution because the working terminal credential is
not available to this agent process. See [PILOT.md](./PILOT.md).

## D26: Explicit labelled retrieval and evaluation-group exclusions

Known-company classification can opt in to a private retrieval index. Source
label files remain outside inference: only the offline builder opens them. It
recomputes related-record partitions without labels, checks reference input/config
hashes and exact split agreement, excludes every held-out group and every group
containing a supplied evaluation record, then selects included labelled training
rows. B uses both labelled and challenge pilot references. Historical freeze code
may differ; source/config fingerprints and recomputed groups must still agree.

The local inverted TF-IDF retriever uses the existing word/character features,
description/service text and weaker account/material context. It returns at most
four examples with cosine >=0.2 or an exact scoped item-code match. These are
initial engineering choices, not tuned held-out thresholds. Same-context/code
examples retain conflicting/minority category counts. Item identity is hashed
locally; raw codes, source IDs, supplier names and provenance are not reference
fields sent to OpenAI. Category paths and training-description context are sent
only when the user opts into a retrieval-assisted API run.

Local prediction uses an uncalibrated category-vote margin with conflict/no-evidence
flags and lexical fallback. The LLM receives examples as noisy, untrusted evidence,
returns one runtime-tree ID, and uses a separate labelled cache protocol containing
the index fingerprint and exact references. A zero-label backend rejects labelled
contexts. Normal runs never load an index. Company/tree mismatches and invalid
artifacts fail; confidential indexes/provenance/reports remain under ignored private
storage. Missing labels/C use the existing zero-label path. Inference does not
modify eligibility, finances, matching or entity keys.

A trains on 18,822 rows/3,201 examples and B on 866 rows/460 examples after exclusion.
Local retrieval with lexical fallback scores 11/40 A (27.5%, spend-weighted 46.69%)
and 31/40 B (77.5%, weighted 96.30%). The B pilot union has 51 distinct rows,
including 11 unscored rows. These are development diagnostics, not reserved-group
or retrieval-assisted LLM scores. Neither exceeds original LLM terminal accuracy;
the next experiment must measure the combination rather than assume improvement.

All 491 tests pass, including 16 new boundary/inference tests. Real provenance and
exact-context checks show no excluded group or evaluation context in either index.
Offline wheel/source archives exclude confidential data and include the new module.
See [RETRIEVAL.md](./RETRIEVAL.md) for usage, reproduction and limitations.

Full real-data local inference with the private indexes passed in 127.34 seconds
A and 52.38 seconds B, with source label reads blocked and zero API requests.
All included rows have valid terminal paths. Counts/exclusions are unchanged;
the same eight B financial exceptions remain unresolved and final export blocked.
This establishes local integration/runtime only; it does not establish the
retrieval-assisted LLM's accuracy or runtime.

## D27: Fixed retrieval-assisted LLM measurement

The next experiment reuses the exact A 40, B 40 and B challenge 12 development
records. Preparation checks original IDs, contexts, groups and spend against the
historical baseline, verifies current lexical predictions, and validates index
training provenance against actual reference split assignments. Every reserved
group and all groups containing either B cohort remain excluded from training.
Retrieved examples/fallbacks and original predictions are frozen privately with
source/config/code/index fingerprints in `private/pilot/retrieval_v2/`.

The comparison uses the existing official-SDK backend and request guards. Three
synthetic gates plus 92 company contexts require at most 95 attempts, with retries
disabled. The default three-million conservative token allowance is split equally;
computed requirements including gates are 508,177 A, 453,472 B and 133,855 challenge.
Insufficient budgets fail before API calls. A failed cohort stops subsequent
cohorts. Cold/warm labelled cache options and index fingerprints must agree; a
missing or inconsistent warm cache cannot yield a complete measurement.

Label scoring occurs only after all inference stops. Reports retain lexical,
retrieval, historical original-zero-label, assisted hybrid and API-only metrics,
explicit scorable/coverage denominators, paired changes, actual usage, prices,
timings and cache checks. Failures use the production retrieval/lexical fallback.
The original v1 LLM baseline is historical, not a fresh stochastic repeat, and
the assisted classifier uses the current v2 base prompt. Differences versus v1
therefore cannot be attributed solely to retrieval; historical v2 zero-label
results also need consideration. No final held-out/unseen-company claim follows.

All 506 tests pass, including 15 new pilot checks. Real-data preparation and
offline preview verify unchanged fingerprints and all original scoring
denominators (40 A, 40 B, 1 challenge) without API requests. Live accuracy and cost
remain unmeasured until the prepared command runs in the authenticated terminal.
See [RETRIEVAL.md](./RETRIEVAL.md).

## D28: Freeze the measured candidate before reserved-group evaluation

Saved development predictions reproduce the user's live retrieval-assisted
results: A 15/40 correct (37.5%, spend-weighted 54.78%) and B 35/40 (87.5%, weighted
99.83%). Relative to original v1, A corrects two errors and regresses one; B
corrects five and regresses two. All 92 classifications completed, and all warm
decisions reproduced without API calls. Actual usage and saved standard prices
imply USD 0.09574860 including three gates. These are reused development results;
the challenge has only one scorable row and eleven without labels.

No application classifier, prompt, model, config or reference index changes were
made for the next evaluation. A new tool reruns the local pipeline with category
label loading disabled, recomputes the existing split, and selects up to 100
reserved groups per company by hash, with one included record per group/context.
A uses ERP records without category-based selection; B uses ID/inclusion-only
seed availability. Every selected group is checked against index training
provenance. The unchanged index already excludes all reserved groups.

Preparation selected 100 A records from 5,145 eligible ERP rows/583 groups and
100 B records from 345 included seed rows/111 groups. The two A arms use identical
records and the same current base prompt/model: tree-only versus retrieval-assisted.
Zero-label A receives no labelled references or retrieval fallback. B evaluates
the fixed assisted candidate. This is 300 company requests plus three synthetic
gates, capped at 303 attempts with no retries and six million conservative token
units divided equally across arms. Labels open for scoring only after all
inference stops; costs, confidence, coverage, cache checks and paired A changes
remain explicit. No reserved LLM result is claimed before live execution.

The freeze and detailed reports remain private. Code/config/input/index changes
invalidate execution; it is not permissible to edit a freeze to preserve a score
after tuning. The sample is group-balanced, not an unbiased spend/row population
estimate. B's seed bias/noise and earlier full-data lexical/eligibility review are
disclosed, so this is not an untouched external test. C remains the blind test.
See [HOLDOUT.md](./HOLDOUT.md).

The full suite passes 522 tests, including 16 new reserved-evaluation checks.
The first full run had one existing CLI subprocess test return empty output;
its focused rerun and a subsequent full-suite run passed. No application fix or
unsupported root-cause claim was made for that transient failure.

## Requirements question disposition

| Question | Evidence / decision | Remaining work |
| --- | --- | --- |
| U01 Dates | D02/D16; production parsing and quality/chronology flags implemented | Later matching/inference use; no automatic date repair |
| U02 Status | D05/D17; strict explicit statuses and flagged unavailable-status policy | Approval cannot be verified when not supplied |
| U03 Amount/FX failures | D03-D04/D16-D17; review found no supported exclusion for eight candidates | Supported financial resolution before export |
| U04 Credits/zero | D06/D17-D18/D20; signs preserved; absolute-spend evaluation weights | Uncertain reversal semantics |
| U05 Matching | D07/D18; direct/group/budgeted allocation and strict repeats implemented | Real precision/recall and ambiguous/partial overlap remain unresolved |
| U06 ID scope | D08/D19; scoped IDs and conservative cross-system name/text links | Low supplier recall; B global identity lacks supporting names/truth |
| U07 Excluded outputs | D09/D15/D20; implemented zero spend/confidence, blank categories, populated keys | Final named output/release checks |
| U08 Reason precedence | D09/D17-D18; duplicates preserve earlier exclusions | Implemented and tested; ordering is a documented choice |
| U09 Blank text/items | D08/D10/D19-D20; flagged distinct unknown identities and lexical fallbacks | Semantic improvement; labels absent for 42.71% of A item rows |
| U10 Label/context disagreement | D10-D11; mixed-category contexts and seed bias quantified | Grouped holdouts, evidence hierarchy and confidence |
| U11 A currency | D03/D16; reporting ZAR preserved despite other metadata | Implemented and independently verified |
| U12 Non-procurement | D11/D17; generic rules implemented; initial reserved/reused metrics separated | Unseen-company accuracy and unsupported pattern coverage remain unmeasured |
| U13 C/config | D12; current schemas mapped; L4 absent from supplied trees | Configuration implementation and four-level rehearsal |

## D29: Preserve the evaluated candidate and rehearse complete exports

The completed reserved run measured leaf accuracy of 14% for A without labels,
39% for A assisted and 84% for B assisted, on 100 sampled records per arm.
Absolute-spend weighted accuracy was 9.77%, 28.25% and 88.31%, respectively.
All 300 decisions reproduced from cache without requests. The 303 live requests,
including gates, cost an estimated USD 0.25258875. These samples do not establish
full-company or unseen-C accuracy; A zero-label performance is a material weakness.
No classifier/prompt/index changes were made in response to these scores.

The new rehearsal runner plans full-company query populations, checks frozen
fingerprints, requires explicit allowances and a fresh synthetic gate, persists
successful decisions, and reports coverage, actual token usage, cost and runtime.
Warm verification makes no requests. Partial fallback execution cannot count as
complete API measurement. A fast resumed run cannot verify cold runtime.

Real-data planning made zero API requests. A has 9,045 unique queries across
46,325 included rows; the independently validated local fallback export contains
all 65,549 source records. B has 12,518 unique queries across 37,910 included rows.
Its three missing amounts and five missing invoice-month rates remain unresolved:
source invoice peers provide no authoritative replacement. Posting dates do not
justify replacing invoice dates; missing financial values do not justify zero
spend or non-procurement exclusions. B execution is blocked before API calls.

The full suite passed 533 tests; 11 rehearsal checks passed again after report
metadata changes. A working-tree candidate audit found no raw input/private files
or matching API-key strings. This heuristic scan does not certify internal Git
checkpoint history. Main has no project commit and no remote is configured.
The approach document is drafted; live full-company measurements, B financial
resolution, final filenames/exports and publication checks remain outstanding.
See [REHEARSAL.md](./REHEARSAL.md) for the active plan and execution command.

## D30: Complete A coverage; preserve B's unresolved financial evidence

A recovery obtained the remaining 91 contexts after connection failures. All
9,045 decisions now cover 46,325 included rows. A separate validation reread
source IDs and taxonomy, checked the 65,549-row saved export, and recorded its
SHA-256 hash privately. Current frozen fingerprints and zero-request warm
reproduction passed. No further API request was made for this verification.
The 219.69-second recovery and USD 0.08411475 estimate apply only to that retry.
The preceding partial resumed run took 75.7 minutes; neither establishes cold
runtime, and historical cost remains unknown. Complete coverage is not an
accuracy measurement or resolution of model review flags.

B still needs three signed source amounts and CAD units-per-USD rates for three
invoice months affecting five rows. A private per-record correction request
contains null replacement/evidence fields. No value, invoice date, eligibility
decision, input or company config was changed. Authoritative corrections or an
explicitly justified fallback policy are needed before final B export; unavailable
source financial evidence cannot be recovered by asking the classification LLM.

## D31: Explicitly authorized financial fallback

The user requested a documented fallback rather than keeping B blocked. B now
opts into two generic config policies; strict remains the default for A/new
companies. Blank source amounts become flagged decimal-zero placeholders while
remaining included under ordinary rules. Invalid nonblank amounts stay unresolved.
Missing line/monthly FX selects the nearest valid supplied month for the same
currency, with calendar-month distance and earlier-month tie-breaking. Invalid
supplied rates/reference entries and unavailable invoice dates remain blocked.

Raw financial values and invoice dates are retained. Estimated rows keep their
original missing-value flags plus AMOUNT_ESTIMATED_ZERO or
FX_ESTIMATED_NEAREST_MONTH, financial_estimated, and reference-month provenance.
This is a numeric completeness policy, not recovery of true spend. Zero omits
unknown signed amounts from totals; nearest-month FX is an explicit approximation
beyond the stated invoice-month rule. See [FINANCIAL_POLICY.md](./FINANCIAL_POLICY.md).

The supplied B data produces three zero placeholders and five FX estimates using
December 2022 CAD rate 1.35. The latter contribute approximately USD -504.14.
All 41,028 output rows independently validate, including 37,910 included rows,
3,118 excluded rows, zero unresolved financial values and eight estimates.
No exclusion reason is fabricated merely to handle missing financial evidence.

Config/normalization source changes create a new version. A distinct B rehearsal
plan records those changes, verifies identical raw input hashes, and rejects
classification/prompt/index changes. Old plans/reports and A's cache/output remain
untouched; their historical pipeline fingerprints are not rewritten. No company
API calls were made in preparing or verifying the new plan. The task's stated
code-freeze deadline still applies; this revision is not the earlier frozen code.
The complete regression suite passes 546 tests, including strict defaults,
fallback boundaries, FX precedence/ties and rejection of classifier-code changes
in the financial-update provenance check.

## D32: Finalize selected outputs without further API spending

After confirming credits were exhausted, the user chose to finalize the existing
B output and specified the filename prefix `manan`. No further inference or API
diagnostic request was made. A and B final files are byte-for-byte copies of the
selected saved exports, independently revalidated against current source IDs
and runtime trees. Source labels were not loaded. Hashes are supplied alongside
the outputs; detailed source-run provenance remains in the ignored private
finalization manifest.

A includes 46,325 LLM/cache-classified spend rows out of 65,549 total records.
B includes 37,910 spend rows out of 41,028 records: 18,054 LLM-classified, 10,661
local retrieval and 9,195 local taxonomy classifications. Its prior run attempted
12,518 company requests and recorded 6,937 HTTP 429 errors. Credit exhaustion
was confirmed by the user; the recorded HTTP status alone did not establish the
subtype. The selected B output remains a mixed result, not complete LLM coverage.

Finalization is a user selection, not a new successful inference measurement.
Historical status `partial_api_or_cache`, unknown total cost, unverified successful
cold runtime, uncalibrated confidence and eight B financial estimates remain
disclosed. No raw input, category, entity key, spend value or exclusion changed
during finalization. Publication and submission have not occurred.
The final regression suite passed 548 tests. A heuristic working-tree candidate
scan found no raw input/private files or matching API-key strings; it does not
certify internal Git history. Both final SHA-256 checksums match their exports.

## D33: Obsolete deadline and clean-install verification

The user explicitly confirmed the original deadline no longer applies. Historical
freeze notes describe provenance and are not active restrictions on further
development. The instruction to avoid further paid API spending remains active.

Added a wholly synthetic company config, six invented invoices and a runtime
four-level tree. Its real CLI run verifies net USD 325, three included records,
three reason-coded exclusions, complete L4 classification, and no labels/index.
These examples are functionality evidence, not a measurement on the actual C.

A clean copy of publishable candidate files was installed non-editably into a
new environment with locked offline uv. No private artifacts, previous virtual
environment or Git internals were copied; all OpenAI environment variables were
removed. Only the dependency cache was reused. Installed C, full A and full B
local runs and independent validation passed. Measured CLI wall times were
24.07, 69.23 and 43.62 seconds respectively; installation took 13.01 seconds.

Fresh local outputs preserve A/B financial and eligibility counts/totals but use
local taxonomy classification. They do not reproduce unpublished historical API
decisions or reference indexes, and their accuracy must not be conflated with
reserved LLM evaluation. Final selected CSVs remain unchanged. No API requests
were made, and no publication occurred. There is no configured GitHub remote or
available GitHub CLI; actual publication remains a separate step.
