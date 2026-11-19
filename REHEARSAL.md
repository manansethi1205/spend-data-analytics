# Full-company rehearsal and release state

**Finalization decision:** the user chose no further API spending after credits
were exhausted. Selected A and B outputs are now finalized as
[manan__A.csv](./submission/manan__A.csv) and [manan__B.csv](./submission/manan__B.csv).
Both independently validate, and both are byte-for-byte copies of the selected
run exports. B intentionally retains local fallback on 19,856 included rows and
eight financial estimates. Its historical partial status is preserved.
Commands below document earlier runs; no further paid run is required for this
selected release. See [submission notes](./submission/README.md).

The production classifier, prompt, model and private indexes remain unchanged
from the reserved evaluation. That evaluation measured 14% A zero-label, 39% A
assisted and 84% B assisted on 100 group-balanced scorable records per arm.
Detailed sample limitations remain in [HOLDOUT.md](./HOLDOUT.md). This stage measures
the complete chosen pipeline and validates available exports; it does not tune on
the reserved scores or retrain an index.

## Financial readiness

**Superseded for the new financial-policy version:** the user subsequently
authorized the fallback in [FINANCIAL_POLICY.md](./FINANCIAL_POLICY.md).
The strict-policy findings below explain the original block. B now opts into
flagged zero placeholders for blank amounts and nearest supplied month FX for
missing invoice-month entries. Historical plans are retained unchanged. Prepare
and run the new version with a distinct root:

```powershell
uv run --locked python tools/rehearse.py prepare --data-dir "<kit-root>" --rehearsal-root private/rehearsal/financial_fallback_v1 --companies B --financial-policy-update
uv run --locked python tools/run_rehearsal.py run --data-dir "<kit-root>" --rehearsal-root private/rehearsal/financial_fallback_v1 --company B
```

The explicit update flag verifies raw inputs, classifier and reference indexes
are unchanged while recording config/normalization changes. It does not certify
the new financial estimates or overwrite historical evaluation fingerprints.
Preview first; execute with the new plan's explicit allowances only after it
passes financial readiness and output validation.

B still has three missing amounts and five non-USD rows without a line rate or
supplied invoice-month FX. A source recheck found no matching invoice-line values
to recover them. Existing chronology flags do not prove the invoice dates are
wrong. Posting-month rates, zero values, estimated prices and non-procurement
exclusions are not substituted merely to obtain a numeric export.

The current policy remains strict: retain the rows as eligible candidates, flag
the missing financial evidence, and block final B export. Authoritative corrected
amounts/rates or another explicitly justified policy is required. B's failed
readiness check prevents paid company-data API requests in the rehearsal runner.
Private per-record diagnostics are written with the plan; no exception IDs or
raw examples belong in public documentation.

## Plan before paid execution

[rehearse.py](./tools/rehearse.py) computes the real context population without API
calls. It preserves the evaluated model/index, counts distinct complete LLM
queries including references, calculates required request/token allowances, audits
financial readiness, and writes an independently validated local-fallback CSV for
financially ready companies. This CSV is a local rehearsal artifact, not the
selected LLM output or a final named submission.

```powershell
uv run --locked python tools/rehearse.py prepare --data-dir "<kit-root>"
uv run --locked python tools/rehearse.py run --data-dir "<kit-root>" --company A
```

The active root is `private/rehearsal/v2/`. Plans are immutable and cannot be
overwritten. The preview makes no API requests and shows the exact required
allowances. A new input/config/code/index requires a new root, not an edited plan.

The runner prints its result at completion, so a blank terminal alone does not
mean it has stopped. In a second terminal, observe saved progress without making
API requests:

```powershell
uv run --locked python tools/watch_rehearsal.py --company A
```

The monitor refreshes every ten seconds; Ctrl+C stops only the monitor. Cached
decision counts and final report statuses do not prove that a process is alive.
Do not launch overlapping paid runs. If the original process has exited, rerun
the same rehearsal command to reuse saved successful decisions; its report will
describe a resumed run rather than a cold runtime measurement.

For visible progress within the runner terminal, replace `tools/rehearse.py` with
`tools/run_rehearsal.py` in the run command, preserving all other arguments.
This launcher prints elapsed time, saved-decision count and the current main-thread
code stage every 15 seconds. It invokes the existing CLI, preserves its exit code,
and does not change classifier code, frozen fingerprints, cache keys or budgets.
Progress output is diagnostic; only the final report verifies coverage and cost.

For paid execution, use the same terminal where authentication succeeds and copy
the exact allowances from the prepared plan:

```powershell
uv run --locked python tools/rehearse.py run --data-dir "<kit-root>" --company A --execute --max-requests <required_requests_including_gate> --max-tokens <required_token_allowance_including_gate>
```

Budgets default to zero; insufficient allowances fail before the synthetic gate.
The gate is fresh and contains no company data. Company requests only follow a
valid response. Concurrency defaults to four and retries are disabled, matching
the evaluated candidate. The token allowance is conservative application accounting,
not a tokenizer count or billing guarantee. Classification/financial readiness
must be distinguished: a valid fallback output is not complete LLM coverage.

Each run saves a separate private report and validated company CSV. Successful
decisions persist in a company/index/context-specific private cache; rerunning
the same command can resume missing decisions. Reports distinguish cold/resumed
runs, source/included/unique-context counts, API/fallback coverage, actual usage,
cost per 1,000 input records, gate cost, end-to-end time and warm-cache reproduction
of paths, confidence and review flags. Cache-only verification permits no requests.

`measured` requires complete included-row API/cache coverage and consistent warm
decisions. Partial/error/fallback execution exits nonzero even when its CSV passes
the output contract. A run over the full-company 60-minute rehearsal target is
flagged; a fast resumed run does not verify cold runtime. A full-company run is
larger than the brief's 25,000-line benchmark, so these measures are reported with
their actual row counts, without claiming general unseen-data performance.

## Release checks still required

The prepared v2 plan covers 65,549 A input records, 46,325 included rows and 9,045
unique company queries. Its private local fallback CSV independently validates
with no contract errors. B covers 41,028 input records, 37,910 included rows and
12,518 unique queries, but its eight financial exceptions prevent export. Planning
and local validation took 160.08 seconds for A and 65.91 seconds for B; these times
exclude live API inference. No API requests were made during preparation.

For the current unchanged A plan, run from the authenticated PowerShell terminal:

```powershell
uv run --locked python tools/rehearse.py run --data-dir "C:/Users/HP/Downloads/Cantill_DataML_Task_Kit_vf_extracted/Cantill_DataML_Task_Kit" --company A --execute --max-requests 9046 --max-tokens 114189091
```

This is a paid full-company run with up to 9,046 attempts including its gate. The
114,189,091 allowance is conservative internal accounting, not expected billed
tokens. This command is retained for reproducibility; A coverage is now complete,
so another paid A run is not needed to recover missing decisions.
The suite passed 533 tests, and the 11 focused rehearsal checks passed again after
report metadata changes.

The one-page [APPROACH.md](./APPROACH.md) now records the architecture and measured
accuracy/cost boundaries. Before submission, complete the paid-run measurements,
resolve B's financial blocker, validate final named A/B outputs, and confirm the
submission filename prefix. Audit Git staging/history and package contents for
input data, private examples/caches, credentials and unapproved raw diagnostics.
The audited repository has since been published at
[manansethi1205/spend-data-analytics](https://github.com/manansethi1205/spend-data-analytics).
No external submission form has been sent.

The supplied output specification permits final classified CSVs in the public
repository, but never raw task inputs, private indexes or detailed audit extracts.
Keep provisional outputs under ignored private storage until the release checks
and naming are complete. Blind-test operation must use the frozen code; C supplies
a new config/tree and no labelled retrieval index. Review [README.md](./README.md)
for setup and [DECISIONS.md](./DECISIONS.md) for unresolved policies.

## Completed A recovery

The initial partial resumed run made 7,285 company requests, encountered 91
connection errors and left 223 rows using fallback. Its 4,544.40-second wall time
exceeded the full-company rehearsal target. It was not a cold benchmark.

A subsequent two-worker recovery reused 8,954 cached decisions and successfully
requested the remaining 91 contexts. All 9,045 contexts now cover all 46,325
included rows; no local fallback remains. The private export contains 65,549
records and passes independent validation against source IDs and the runtime
tree. Successful paths, confidence and review flags reproduced from cache with
zero verification requests. Frozen input/code/index fingerprints remain valid.

Recovery wall time was 219.69 seconds, with an estimated USD 0.08411475 including
its gate. This cost belongs only to the recovery, and its per-input-row rate does
not estimate a fresh run. Total historical cost remains unknown because earlier
connection failures lack usage. A cold 25,000-line runtime benchmark remains
outstanding. The 16,947 model review flags and uncalibrated confidence remain
quality limitations despite complete coverage.

B's eight-row private correction request lists the three missing signed source
amounts and five missing CAD conversion rates, grouped into three invoice months.
Replacement values and evidence remain null; no input/config was modified and
no B company-data API run was started.

## Prepared B fallback rehearsal

The active B plan is `private/rehearsal/financial_fallback_v1/`, prepared with
the explicit financial update. All 41,028 local fallback output rows independently
validate, with 37,910 included and 3,118 excluded. There are zero unresolved
included financial values and eight estimated rows. These totals depend on the
documented estimates; validation does not establish their accuracy.

The plan has 12,518 unique company contexts. From the authenticated terminal:

```powershell
uv run --locked python tools/run_rehearsal.py run --data-dir "C:/Users/HP/Downloads/Cantill_DataML_Task_Kit_vf_extracted/Cantill_DataML_Task_Kit" --rehearsal-root private/rehearsal/financial_fallback_v1 --company B --execute --max-requests 12519 --max-tokens 132913730 --workers 4
```

This is a paid full B run, capped at 12,519 attempts including its synthetic gate.
The token allowance is conservative application accounting, not predicted billed
tokens. This stage prepared/verified the plan without making API calls. Continue
to retain the earlier A output and cache; do not rerun old v2 plans, whose code
fingerprints now correctly reject the financial-version change.

### First B API run: incomplete because of HTTP 429

The first cold B run saved 5,581 of 12,518 contexts. It attempted all 12,518
company requests, recording 6,937 HTTP 429 errors with retries disabled. LLM
coverage is 18,054 of 37,910 included rows; 19,856 rows use visible local fallback.
All 41,028 output records validate structurally under the financial policy, but
the report is `partial_api_or_cache`. Wall time was 3,657.66 seconds; no successful
cold-runtime claim can be made. Total cost remains unknown because rejected calls
lack usage. Cached successes remain available for recovery.

The existing report retains HTTP status, not the error subtype. HTTP 429 alone
cannot distinguish throughput limits from billing/quota exhaustion. Before
another full run, use this one-request diagnostic in the authenticated terminal:

```powershell
uv run --locked python tools/diagnose_openai.py --execute
```

It sends one synthetic prompt, makes no retries, and prints only status, sanitized
error code/type and numeric Retry-After. It sends no company data and prints no
API key, error message or full response body. A successful small request does not
verify sustained throughput. See the [official OpenAI error documentation](https://developers.openai.com/api/docs/guides/error-codes)
for rate-limit versus quota recovery. Do not keep restarting the full job while
the cause is unresolved.
