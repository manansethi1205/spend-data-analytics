# Step 11D: fixed classification pilot

All three prepared pilots completed successfully from the user's authenticated
PowerShell terminal. Saved predictions, metrics, costs, coverage and freeze
fingerprints were verified offline. The earlier agent-process HTTP 401 did not
prevent execution through the same-terminal launcher. This does not establish
that the agent's separate environment has been refreshed.

## Measured development results

The single tested model was `gpt-5.4-mini-2026-03-17`, using classifier protocol v1.
These measurements describe the historical baseline, not the revised v2 prompt.

| Cohort | Scored / sampled | Local terminal accuracy | LLM terminal accuracy | LLM absolute-spend-weighted accuracy | Company-request estimate (USD) |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 40 / 40 | 10.0% | 35.0% | 51.10% | 0.01566735 |
| B labelled seeds | 40 / 40 | 32.5% | 80.0% | 58.77% | 0.03684750 |
| B challenge | 1 / 12 | 0 / 1 correct | 1 / 1 correct | Not population evidence | 0.01095300 |

All 92 company contexts received valid API decisions without fallback. Three
synthetic gates bring the observed total to 95 requests and the public-price
estimate to **USD 0.06445710**, including gates. A's reported cached input tokens
reduce its estimate. Warm application-cache runs reproduced all decisions with
zero API requests. Cold company-batch wall times were 18.19 s A, 12.14 s B and
4.42 s B challenge; these do not establish full-run runtime.

These stratified development samples do not estimate whole-company or blind-test
accuracy. Eleven challenge rows have no scoring label. Only one model was tested,
so no model-comparison winner is established. A remains weak: only 1/12 generic
and 0/4 non-ASCII sample rows were correct. Self-reported confidence is not
calibrated; A's confidence-above-0.3 band was only 12/26 correct.

The original offline review was run without API calls:

```powershell
uv run --locked python tools/review_pilot_results.py --data-dir "<kit-root>"
```

The review reopens scoring labels only after reading the saved predictions,
checks current input/code fingerprints against the freezes, validates prediction
IDs/order, terminal paths and confidence, recomputes metrics and token-price
estimates, and checks reported warm-cache coverage. It requires exactly one
matching measured run per cohort to avoid silently selecting a rerun. Its
aggregate is saved to ignored `private/pilot/v1/summary.json`.

## Protocol v2 development result (historical)

The user subsequently completed all three v2 API pilots. A terminal accuracy
remained 35% (spend-weighted 54.63%, versus v1's 51.10%). B terminal accuracy
fell to 72.5% (weighted 53.09%, versus v1's 58.77%). All 92 contexts were covered;
warm reruns made no API requests. The samples are small and reused development
data; they do not establish statistical significance. They provide no evidence
of an overall v2 improvement. Label-assisted retrieval is now implemented as a
separate next experiment; see [RETRIEVAL.md](./RETRIEVAL.md).

Reading the private JSON explicitly as UTF-8 confirms A's four non-ASCII sample
descriptions contain valid technical symbols. They supply evidence about
equipment-versus-service ambiguity, not multilingual performance. A diagnostic
initially used Windows' default encoding and made those symbols appear corrupt;
that diagnostic was corrected and the proposed repair was removed. No encoding
repair or source-text transformation was introduced.

The revised, category-independent prompt distinguishes physical goods/spares
from service activities, uses the full hierarchy, and treats generic component
names without application context as ambiguous. No labels, equipment-category
mapping, or golden IDs were added. Model, output schema and request limits are
unchanged. Protocol/prompt cache keys isolate new decisions from v1. Original
Unicode classification contexts are preserved in requests and sampling.

New snapshots live under `private/pilot/v2/`. Preparation uses the same selection
algorithm; record IDs, original contexts, local predictions and reserved group
assignments are checked against v1. The old snapshots/reports remain unchanged.
Historical freezes intentionally fail a current-code fingerprint check after
further implementation changes. Prepare a new matching-code freeze for new
executions; do not overwrite v1/v2 snapshots. These reused development
samples are for prompt tuning; they remain unsuitable as final held-out scores.

Historical v2 commands, requiring the corresponding v2 application code:

```powershell
uv run --locked python tools/run_prepared_pilots.py --data-dir "<kit-root>" --pilot-root private/pilot/v2 --execute
uv run --locked python tools/review_pilot_results.py --data-dir "<kit-root>" --pilot-root private/pilot/v2
```

The first command allows up to 95 requests including gates; token allowances stay
at three million conservative units. Omit `--execute` for an offline preview.
The second command verifies saved results without API calls. Compare sample
metrics to the v1 table, including regressions and spend weighting, before treating
the revision as an improvement. Full-run runtime, final grouped evaluation and
optional label-assisted learning remain separate work.

This keeps prompts versioned and evaluation separate, as described in the
[official OpenAI prompting guidance](https://developers.openai.com/api/docs/guides/prompting).

The current suite passes **475 tests**, including new Unicode-preservation and
previous-protocol cache-isolation checks. Exact comparison confirms that all
92 selected rows, their original contexts/local predictions, complete group
partitions, taxonomies and input/config hashes match v1. Preparation evidence is
stored in ignored `private/pilot/v2/preparation_check.json`.

## Prepared samples and leakage boundaries

Three private sample freezes are prepared under `private/pilot/v1/`:

| Directory | Cohort | Requested sample | Purpose |
| --- | --- | ---: | --- |
| `A/` | ERP source, no label-based selection | 40 | A labels-hidden inference comparison |
| `B/` | Included labelled seed IDs | 40 | Scorable B development diagnostics |
| `B_challenge/` | All included records | 12 | Challenge coverage, including blank descriptions |

Preparation runs the entire pipeline in forced local mode with label loading
disabled. It then freezes related-record groups before reading any optional
cohort labels. Related records share a group through identical classifier context,
informative normalized description, scoped material code, scoped supplier/invoice
or matched-purchase links. Connected groups are assigned development/holdout by
hash; approximately 20% of groups, not necessarily 20% of rows, are held out.

Only included development rows can enter a pilot. Round-robin strata cover blank,
generic/very short, non-ASCII, short and longer text, plus lexical account/text
disagreement when available. This last stratum is a heuristic disagreement, not
verified account error. Unique contexts are sampled deterministically; repeated
contexts do not consume additional pilot slots.

A preparation does not load category/entity labels. B's labelled cohort uses only
seed inclusion/ID availability for selection, not category values. This cohort
is biased: B has no included blank-description seed examples. The challenge cohort
is therefore separate, often lacks scoring labels, and cannot establish accuracy
on blank descriptions without additional ground truth.

These are development diagnostics. Earlier full-data lexical baseline results and
eligibility label review are disclosed; the newly reserved groups are not claimed
to be previously unseen by the developer. Future prompt/model tuning must not use
their holdout scores. Golden supplier/item keys never enter inference.

Each freeze includes private contexts, local predictions, spending values, all
record partitions and fingerprints of input/config/application code. Its integrity
hash detects accidental edits. Preparation refuses to overwrite it; changed
inputs or code require a newly prepared private directory. The hash is not a
security signature against a malicious local editor.

## Run the offline preview

From the repository root, set `<kit-root>` to the extracted input-kit directory:

```powershell
uv run --locked python tools/pilot_classification.py run --config configs/company_A.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/v1/A
uv run --locked python tools/pilot_classification.py run --config configs/company_B.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/v1/B
uv run --locked python tools/pilot_classification.py run --config configs/company_B.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/v1/B_challenge
```

Without `--execute`, no OpenAI client/request is created. The report contains local
sample metrics and explicitly has status `dry_run`; it is not an LLM measurement.

To prepare a new sample after an intentional code/input change:

```powershell
uv run --locked python tools/pilot_classification.py prepare --config configs/company_A.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/new_A --source erp --cohort all --sample-size 40
uv run --locked python tools/pilot_classification.py prepare --config configs/company_B.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/new_B --cohort included-labels --sample-size 40
```

CLI artifact paths must remain under the repository's ignored `private/` directory.
Snapshots contain confidential purchase context and must not enter the public repo.

## Execute after authentication works

### Terminal succeeds but the agent gets 401

A PowerShell `$env:OPENAI_API_KEY` assignment updates that terminal and its future
child processes. It does not update the environment of an agent/VS Code process
that was already running. The SDK reads its own process environment. Thus a
successful terminal check can coexist with a rejected credential in agent jobs;
the successful result is not evidence that both processes used the same key.
No model/prompt change is needed for this environment difference.

The safest session-only workflow is to launch all three prepared pilots from the
same terminal where `check-openai` succeeds:

```powershell
uv run --locked python tools/run_prepared_pilots.py --data-dir "<kit-root>" --execute
```

The launcher inherits that terminal's environment in memory, never copies its key
into a command argument/file, and stops after a failed cohort. Default total
allowance is 95 attempts: 41 A, 41 B and 13 B challenge, including synthetic gates;
the conservative token allowance is three million. Without `--execute` it only
runs offline previews. Reports remain under the existing private cohort directories.

Alternatively, save the working session key as your Windows user environment
variable, without repeating its value:

```powershell
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $env:OPENAI_API_KEY, 'User')
```

An already-running agent still needs to explicitly reload that saved variable into
its child process (or be restarted). The application does not silently prefer a
registry credential over its process environment. Keys remain outside source,
configs, caches and logs. No API key should be pasted into chat. OpenAI documents
[401 authentication causes](https://developers.openai.com/api/docs/guides/error-codes)
and [environment-variable setup](https://developers.openai.com/api/docs/quickstart).

### Individual cohort commands

Use the same PowerShell terminal that holds a valid `OPENAI_API_KEY`:

```powershell
uv run --locked cantill-spend check-openai
uv run --locked python tools/pilot_classification.py run --config configs/company_A.yaml --data-dir "<kit-root>" --pilot-dir private/pilot/v1/A --execute
```

Each model first receives one fresh synthetic request. Failure prevents company
requests for that model; 401/403 stop further model gates. Default total allowance
is 41 attempts and one million conservative token units, with retries disabled:
one synthetic gate plus at most 40 company contexts. Allowances are divided across
models, including their gates. If a model's allowance cannot cover the entire
frozen sample, no partial company subset is sent. Failures after scheduling still
produce a visibly partial report rather than an apparent full comparison.

`--models` accepts one to four candidate IDs. For two models on 40 contexts, use
at least `--max-requests 82` and a sufficient `--max-tokens` allowance. A cold run
uses a new private cache; a warm run uses the same decisions with zero API request
allowance. Warm equivalence/cache coverage and zero requests are checked. Models
are not ranked automatically from partial/differently covered results. The current
default is a candidate, not a measured winner.

## Measurements and costs

After every model's inference completes, labels open for scoring. Reports contain
local, hybrid (including fallbacks) and API-only metrics with explicit denominators,
level/path accuracy, absolute-spend weighting, strata and confidence bands. Missing
gold labels and missing financial values are counted rather than invented.

Cold/warm batch wall time and seconds per sample line measure throughput including
cache work, not individual-request p95 latency. The preparation report records full
local pipeline time separately. Token counts distinguish input, cached input and
output; synthetic gate usage/cost is separate from company classification cost.

[openai_pricing.json](./configs/openai_pricing.json) records standard USD per-million
token rates and source/date for the initial model. Rates are validated before any
request and copied into measured reports. Unknown prices or unknown failed-call
usage produce null dollar estimates. Estimates exclude account-specific discounts,
regional/priority adjustments and taxes; they are not billing guarantees.

Cost per 1,000 sample input lines is scaled from the observed sample and labelled
as such. Unique-context stratification changes reuse and category mix, so this is
not a forecast of full-company or blind-test cost. Final full-run cost/runtime must
be measured separately. See [OpenAI's model price reference](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

Each invocation writes a new private `runs/<id>/report.json`; executed predictions
are saved alongside it for error analysis. Blocked/incomplete runs exit 1, bad
config/freeze/paths exit 2, and dry previews or complete measurements exit 0.
Successful measurements above establish improvement on these fixed development
samples; unseen-company quality remains unmeasured.

## Offline verification results

All 460 tests pass, including 20 pilot tests for grouping, deterministic sampling,
source/cohort filters, gold-value separation, cache-only warm runs, synthetic
authentication gates, insufficient-budget rejection, cost math, immutable freezes
and no-API preview behavior.

All three real-data freezes and previews succeeded with unchanged input/code
fingerprints. A reserves 9,056 of 65,549 input rows across its held-out groups;
B reserves 3,065 of 41,028. Selected records all belong to development groups.

| Local preview | Scored rows | Terminal accuracy | Absolute-spend-weighted accuracy |
| --- | ---: | ---: | ---: |
| A ERP sample | 40/40 | 10.0% | 24.99% |
| B labelled sample | 40/40 | 32.5% | 19.30% |
| B challenge sample | 1/12 | Not meaningful from one label | Not meaningful from one label |

The challenge sample contains two blank-description lines and two from each of
the other five strata. Eleven challenge rows lack usable category labels; no
accuracy is assigned to those rows. These small, deliberately stratified local
scores are not comparable population estimates and are not LLM results.

At that offline-preparation milestone, the agent's synthetic authentication retry
returned HTTP 401 and no company-data pilot measurements existed. The successful
same-terminal measurements at the top of this document supersede that status.

The terminal-environment follow-up adds four launcher tests (464 total passing),
covering global allowances, multiple models, private paths and keeping credentials
out of command arguments. The user subsequently reported a successful synthetic
check in their PowerShell terminal. That confirms authentication in that process;
the agent's separate process environment has no saved Windows user/system key to
reload. Use the same-terminal launcher above, or save and explicitly reload the
working user environment variable. This is an execution-environment handoff; no
prompt, classifier, source data or frozen sample was changed to address it.

The subsequent offline saved-result review passes the full **473-test** suite,
including nine checks for missing/duplicate IDs, invalid taxonomy paths,
non-finite/out-of-range confidence and falsely complete fallback decisions.
All three real-data reviews pass with current freeze fingerprints unchanged;
the aggregate remains ignored by Git. No further API calls were made in review.
