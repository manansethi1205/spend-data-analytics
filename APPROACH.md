# Spend pipeline approach

Python 3.12, pandas and YAML configs map source columns into a common record
schema; a new company supplies its files, mappings and runtime category tree.
The pipeline preserves input IDs/raw values, parses explicit number/date formats,
removes configured VAT and divides non-USD amounts by units-per-USD rates. Every
input record remains represented. Ordered eligibility rules explain exclusions;
financial incompleteness alone is not a valid exclusion.

A's purchase matching prefers ERP receipts. Normalized PO/line references,
supplier/text evidence, quantity/amount capacity and complete invoice groups
identify cross-system overlaps; strict fingerprints detect repeated exports.
Ambiguous/incomplete matches remain counted and flagged. Supplier/item resolution
uses scoped IDs, conservative normalized-name/text/unit links and stable opaque
keys. Conflicting material-code descriptions cannot bridge different items.
A supplier pair precision is 100% but recall only 10%; anonymized aliases remain
a material limitation. Matching coverage is not measured ground-truth recall.

Classification has two paths. Without labels, a local word/character TF-IDF
taxonomy baseline supplies an unattended fallback; an optional OpenAI LLM selects
a terminal category ID from a strict schema built from the current tree. No
category names are hard-coded. Zero-label LLM inference now selects children
recursively; optional top-eight TF-IDF shortlist selection uses hierarchy on
no overlap. Supplier name is supporting context. Confidence blends review and
local margin heuristically; new live accuracy is pending. Known-company retrieval indexes add up to four
relevant labelled examples using lexical similarity/scoped material codes, retaining
conflicting label support. Inference never opens source labels. C and A's
labels-hidden evaluation omit the index. Confidence is uncalibrated.

The fixed model is `gpt-5.4-mini-2026-03-17`. Private caches bind decisions to
company, tree, prompt/model, reference index and exact context. Request/token
allowances, concurrency, timeouts, retries and authentication stops are bounded;
failures use visible local fallback. Keys remain in environment variables.

Reserved-group evaluation used one record per group, 100 scorable records per
company. Historical flat zero-label inference preceded label scoring: terminal accuracy **14%**
(spend-weighted 9.77%). Retrieval-assisted A scored **39%** (28.25% weighted);
B scored **84%** (88.31% weighted). A corrected 28 zero-label errors and regressed
three. These group-balanced diagnostics and B's imperfect seed labels do not
estimate population or unseen-C accuracy; prior whole-data baseline review is
disclosed. Reserved groups were excluded from retrieval training.

Local full runs measured 127 seconds A/52 seconds B. A now has complete LLM/cache
coverage and a validated 65,549-row export. Its partial resumed run took 75.7
minutes; recovery took 219.69 seconds and USD 0.08411 for the retry only.
Cold runtime and historical total cost remain unverified; no 25,000-line
API-runtime claim is made yet.
B was finalized with 18,054 LLM-classified rows and 19,856 local fallback rows
after credits exhausted (6,937 HTTP 429 errors). Its cold run took 60.96 minutes
for 41,028 input rows and was incomplete. This mixed output is not the reserved
sample's 84% accuracy result; its population accuracy remains unmeasured.
Reserved-sample company-call costs were USD 0.746 per 1,000 A unique contexts and
1.289 for B, using reported usage and saved standard prices, not a full-run
forecast. All 303 evaluation requests cost an estimated USD 0.25259 including gates.

Atomic output writing and independent validation enforce row coverage, allowed
exclusions, numeric spend, finite confidence and valid terminal paths. B now opts
into a documented fallback: three blank amounts use flagged zero placeholders;
five unavailable invoice-month rates use flagged nearest supplied months.
These estimates permit export but leave spend accuracy uncertain; all other
companies default to strict handling. See [FINANCIAL_POLICY.md](./FINANCIAL_POLICY.md). Confidential
inputs, indexes, caches and diagnostics remain outside the public repository.
Codex assisted development; the official OpenAI SDK is used for optional inference.
