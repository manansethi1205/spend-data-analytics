# OpenAI classification: steps 11A-11C

OpenAI is an optional classifier after financial, eligibility, purchase-matching
and entity processing. Existing A/B configs default to local classification.
Setting an API key alone never starts paid requests.

## Setup and execution

```powershell
uv sync --locked
$env:OPENAI_API_KEY = "your-key-here"
uv run --locked cantill-spend check-openai
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --classifier openai --llm-max-requests 20
uv run --locked cantill-spend run --config configs/company_B.yaml --data-dir "<kit-root>" --classifier auto --llm-max-requests 0
```

The key belongs in the process environment, never a config/cache/repository. A
PowerShell session variable is inherited by child processes, not already-running
VS Code/agent processes. No automatic dotenv loading is implemented.

`check-openai` makes one synthetic live classification attempt, without retries
or company data. It uses a unique synthetic unit reference to avoid a cache hit.
It prints success, model, status counts and usage, never the key or exception body.
Exit 0 means valid API output, 1 means API/output failure, 2 means configuration
failure. The live integration check reached OpenAI but returned HTTP 401 for the
credential visible to the agent process. Run this check from the same terminal
where you set a valid key before the company-data pilot.

The A command above is deliberately bounded: with one retry reserved, 20 attempt
slots allow at most 10 new unique contexts. Other records use the local fallback.
The pilot will determine model, throughput and budget before increasing limits.

## Configuration and modes

Optional company YAML section:

```yaml
classification:
  mode: local                  # local | openai | auto
  model: gpt-5.4-mini-2026-03-17
  workers: 4                  # 1..32 concurrent requests
  max_requests: 20             # includes retry attempts
  max_tokens: 1000000          # conservative allowance, not exact billing
  max_output_tokens: 512
  timeout_seconds: 30
  retries: 1                  # 0..3; SDK automatic retries disabled
```

CLI overrides: `--classifier`, `--model`, `--llm-workers`, `--llm-max-requests`,
`--llm-max-tokens`. The model snapshot is a configurable pilot candidate, not a
benchmarked winner. `openai` requires a key. `auto` works without a key, reusing
valid zero-label cache decisions when available and otherwise falling back.
`local` neither calls OpenAI nor loads its caches. API modes fall back visibly
on failures and limits. A `run` exit code describes financial/export readiness;
inspect `classification_methods`, `classification_flags` and `openai_usage` to
determine actual API coverage. A successful financial run can use local fallbacks.

## Classification contract

Only trimmed description, service text, account description, material type, unit
and PO unit are sent with the runtime terminal tree. Supplier identities, amounts,
raw dictionaries, record IDs and labels are omitted. Excluded rows never call the API.

Terminal paths receive deterministic temporary IDs. Responses API Structured
Outputs constrains the answer to an allowed ID, confidence and boolean
`needs_review`. Local validation checks exact fields, allowed IDs, finite confidence
in [0,1], refusal and completion status before mapping to exact category names.
The LLM cannot change spend, entity keys, include flags or exclusion reasons.
All input/category strings are explicitly untrusted data; no model tools exist.

API/cache confidence is model self-report; local confidence is lexical margin.
Neither is calibrated. `OPENAI_NEEDS_REVIEW` records uncertainty without dropping
a valid path. No API-backed accuracy improvement has been measured yet.

## Cache, limits and failures

Validated decisions are written atomically under ignored `private/llm/`. Keys
include the zero-label protocol, company, full taxonomy/prompt/schema, model and
all transmitted context fields. Entries contain only the opaque hash and decision,
not raw descriptions or credentials; they remain private artifacts. Equal item
keys alone do not permit reuse. Invalid cache data is ignored; failed responses
and local fallbacks are never cached as successful API classifications.

No labels are loaded. Any future label-assisted mode must use a different protocol
and cache namespace; it must not enter the strict A labels-hidden experiment.

Scheduling follows sorted context hashes. Each scheduled context reserves all
potential retry attempts and a conservative token allowance per attempt: UTF-8
request/schema bytes + 4096 framing allowance + maximum output tokens. Reservations
are not reclaimed. This intentionally underutilizes some budgets; it is an
application estimate, not an exact tokenizer count or guaranteed billing cap.
Actual reported input/output/cached-input usage is counted separately. Failed
requests can have unknown usage; their reservations remain consumed.

Concurrency/timeouts/retries are bounded. Only connection/timeout, 408/409/429 and
server errors retry with bounded backoff. 401/403 open a circuit for queued jobs;
already-running workers may finish. Refused, incomplete, malformed and out-of-tree
answers use local predictions with flags. HTTP/count diagnostics exclude response
bodies, exceptions, credentials and source values. The official endpoint is pinned;
requests use `store=False`, which is not a general retention guarantee.

## Verification and next work

Known-company classification can now opt in to a private labelled retrieval index
with `--retrieval-index`. Reference examples preserve conflicting category labels,
use a separate cache namespace, and exclude reserved/pilot-related groups during
construction. The default path does not load an index or source labels. See
[RETRIEVAL.md](./RETRIEVAL.md) for build commands, safeguards and the separate
retrieval-assisted LLM measurement still required.

The current zero-label protocol is `cantill-zero-label-openai-v2`. Its prompt
adds full-hierarchy interpretation, distinguishes physical goods/spares from
service activities, and flags generic application ambiguity without inferring
equipment families. This is a candidate revision motivated by development errors,
not a measured accuracy improvement. Input Unicode is preserved; no encoding
repair is applied. The protocol and full prompt participate in cache keys, so
old v1 decisions cannot masquerade as v2 measurements. Fresh v2 samples and the
same-terminal comparison commands are documented in [PILOT.md](./PILOT.md).

The 11A-11C milestone passed 440 tests, including real-SDK serialization through a mock HTTP transport,
schema validation, invalid confidence/category rejection, cache isolation/reuse,
limits, retry/circuit behavior, no-key fallback and prior-column preservation.
The full B zero-request integration run classifies all included records locally
and preserves its eight financial exceptions. Locked dependencies are compatible;
the installed OpenAI SDK is 2.54.0. No company data was sent in these checks.

Step 11D live pilots succeeded using the user's authenticated terminal: 92 company
contexts and three synthetic gates completed. Offline review reproduced saved
metrics and estimated total cost, USD 0.06445710 including gates. A terminal
accuracy rose from 10% to 35%, B from 32.5% to 80%, on 40 development rows each;
these are not population scores. See [PILOT.md](./PILOT.md). Full-data runs,
calibration, unseen-company quality and release follow.

Official references: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create),
[configured model](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
