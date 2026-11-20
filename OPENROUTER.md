# OpenRouter free-model classification

OpenRouter is an optional provider for the existing bounded classification path.
OpenAI remains the default. No dependency or API key is committed. The supplier
crosswalk is local and independent of the LLM provider.

## Store your key on Windows

Create a key on [OpenRouter's API keys page](https://openrouter.ai/settings/keys).
Run this in your own PowerShell terminal; paste the key at the masked prompt:

```powershell
$routerSecret = Read-Host "OpenRouter API key" -AsSecureString
$env:OPENROUTER_API_KEY = [System.Net.NetworkCredential]::new("", $routerSecret).Password
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $env:OPENROUTER_API_KEY, "User")
Remove-Variable routerSecret
[bool]$env:OPENROUTER_API_KEY
```

The key is available immediately in this terminal and persists for future
processes through your Windows user environment. Restart VS Code to refresh its
inherited environment, or load the saved value in an existing terminal:

```powershell
$env:OPENROUTER_API_KEY = [Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "User")
```

User environment storage is persistent configuration, not an encrypted secret
vault. The application does not automatically load `.env` files. Do not paste
the key in chat, company YAML, source code or Git. Keep `OPENAI_API_KEY` separate:
an OpenRouter selection only reads `OPENROUTER_API_KEY` and uses the fixed
`https://openrouter.ai/api/v1` endpoint. Inherited alternate base URLs are ignored.

## Candidate model and limits

Starting candidate: `openai/gpt-oss-120b:free`. Its [OpenRouter model page](https://openrouter.ai/openai/gpt-oss-120b:free)
lists free pricing and structured output generation. This is a candidate for
evaluation, not a measured procurement-accuracy recommendation. Pinning the model
avoids the changing model mix of `openrouter/free`. Availability and provider
support must still pass the synthetic schema check below.

As checked on 2026-11-20, the documented free-variant limits are 20 requests/minute
and 50 requests/day without the qualifying credit purchase. Purchasing at least
USD 10 raises the stated daily ceiling to 1,000; that purchase is optional and is
not a zero-spend step. See the [limits documentation](https://openrouter.ai/docs/api_reference/limits)
and its [published constants](https://github.com/OpenRouterTeam/docs/blob/main/snippets/exports/constants.mdx).
Use `GET /api/v1/key` to inspect your account's actual daily allowance; account
exceptions and provider capacity can differ. Limits apply across keys, not per
new key. No top-up is needed for the initial free-tier workflow.

Thousands of unique contexts will not fit a 50-request daily allowance. Even
9,045 single-request contexts need at least 181 daily allowances at 50/day;
hierarchical traversal can use several requests per context. Start with a small
reserved evaluation, use cached decisions and the local/retrieval fallback, and
track daily usage. A free-tier full cold run cannot meet the original runtime
goal at that quota. These are capacity calculations, not measured model runtime.

## Synthetic check and a bounded company run

This check uses only a fabricated procurement description and consumes one free
request. It does not send company records:

```powershell
uv run --locked cantill-spend check-openrouter --model openai/gpt-oss-120b:free
```

Run A with a maximum of ten API attempts and one worker:

```powershell
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --classifier auto --llm-provider openrouter --model openai/gpt-oss-120b:free --llm-workers 1 --llm-max-requests 10 --llm-max-tokens 1000000 --llm-max-output-tokens 2048 --supplier-crosswalk private/supplier_crosswalk/v1/supplier_crosswalk.json --output private/A_openrouter_trial.csv
```

The crosswalk flag requires the trained artifact described in
[SUPPLIER_RESOLUTION.md](./SUPPLIER_RESOLUTION.md); omit it for B/C or a fully
zero-label run. Category retrieval can be added independently with the existing
`--retrieval-index` option. The request cap includes retries; hierarchy reserves
the worst-case path before execution, so ten attempts can cover fewer than ten
unique contexts. Remaining rows use existing local/retrieval fallback. This
command writes every input record, not just API-covered rows. It is a pipeline
trial, not a held-out accuracy evaluation. Inspect usage/methods in the summary.

For persistent company configuration, the same settings can be placed under
`classification` (the historical `openai` mode name means require an API key;
`auto` permits the local fallback):

```yaml
classification:
  mode: auto
  provider: openrouter
  model: openai/gpt-oss-120b:free
  workers: 1
  max_requests: 10
  max_tokens: 1000000
  max_output_tokens: 2048
  retries: 0
  zero_label_strategy: hierarchical
```

## Routing and failure behavior

The integration accepts only fixed `:free` model IDs. Each request sets zero
maximum prompt/completion/request prices, requires parameter support for the
strict schema, disables response storage, and selects `data_collection: deny`.
See [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
and [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection).
It never adds paid-model fallback or silently changes models. Provider caches
are isolated; existing OpenAI cache keys retain their prior format.

These company files are confidential. Some free endpoints explicitly request
that confidential information not be uploaded, including the currently listed
[NVIDIA Lightning endpoint](https://openrouter.ai/nvidia/nemotron-3.5-lightning:free).
Do not use those endpoints for company records. Also disable optional prompt
logging/training in your OpenRouter account privacy settings. Routing filters
can leave no eligible free endpoint: preserve the privacy constraint and use
local fallback in that case. A free endpoint is not guaranteed to meet the
project's confidentiality needs merely because a model page exists.

API attempts are paced at least 3.1 seconds apart across one backend's workers
and retries. This pacing is per process/backend, not an account-wide limiter;
avoid simultaneous runs sharing the account. Daily usage is not reset or tracked
by the application. HTTP 402/429 opens the backend circuit and remaining jobs
fall back locally; 401/403 do likewise. Existing `OPENAI_*` failure/review flags
are retained for compatibility, while the summary records `provider: openrouter`
and successful inference methods use `openrouter`.

The historical rehearsal/evaluation pricing tools and old frozen manifests are
OpenAI-specific. Do not reuse their cost estimates or claim those measurements
apply to this provider. No live OpenRouter request or accuracy measurement was
performed during implementation; tests use synthetic clients only.
