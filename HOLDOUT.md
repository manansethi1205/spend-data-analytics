# Fixed classifier evaluation on reserved groups

The classifier, prompts, model and private reference indexes remain unchanged
from the successful retrieval-assisted development measurement. The next step
evaluates that candidate on groups excluded from training and development pilots.
The new tool is [evaluate_holdout.py](./tools/evaluate_holdout.py); it does not
change application classification code or train another model.

## Selection and inference boundaries

Preparation reruns the label-free local pipeline and recomputes related-record
groups, requiring exact agreement with the earlier split. It selects up to 100
included records per company by deterministic hash, with at most one record per
reserved group and unique context. This is a group-balanced diagnostic sample,
not an unbiased estimate of row-level or total-spend population accuracy.

A uses ERP records and selects without loading its category labels. B selects
from included seed-labelled IDs; only ID/inclusion fields are mapped for cohort
selection. Its analyst seeds are incomplete, noisy and biased, including the
previously documented lack of included blank-description labels. Category values
do not determine sample selection. If fewer than 100 eligible groups exist, the
tool selects those available and reports the actual denominator.

The private index's training provenance is checked against the actual group
manifest. Every reserved group must be absent from training. No index is rebuilt.
The frozen sample includes query context, local predictions, normalized spending,
retrieval references for assisted arms, and source/config/code/index fingerprints.
Preparation refuses existing freezes. Changes invalidate later execution.

Three arms are evaluated:

| Arm | Records | Classification evidence |
| --- | --- | --- |
| `A_zero` | Selected reserved A records | Runtime tree and line context only |
| `A_assisted` | Exactly the same A records | Current retrieval-assisted LLM |
| `B_assisted` | Selected reserved B seed records | Current retrieval-assisted LLM |

Both A arms use the same model and current base prompt. Zero-label A receives
neither labelled examples nor a retrieval fallback: API failure uses only its
taxonomy lexical prediction. Its cache remains separate from labelled decisions.
This is an A labels-hidden comparison, not proof of performance on an unseen
company or taxonomy. Actual C remains the external blind test.

All API inference stops before category labels open for scoring. Reports include
scoring denominators, lexical/retrieval baselines, hybrid and API-only results,
hierarchy and absolute-spend-weighted accuracy, strata/confidence bands, API
coverage, timings, usage/cost, cache checks and paired A corrections/regressions.
Failed arms stop later requests; incomplete results are not declared complete.

## Execute the prepared evaluation

The active freeze is under ignored `private/evaluation/reserved_v1/`.
Preparation selected 100 distinct reserved groups for A from 5,145 eligible ERP
rows across 583 groups, and 100 for B from 345 eligible seed-labelled rows across
111 groups. A's two arms share those same 100 records; the plan therefore needs
300 company classifications plus three synthetic gates. No API calls were made
during preparation, and no classifier, prompt or reference index was changed.
Use the PowerShell terminal with the working API key:

```powershell
uv run --locked python tools/evaluate_holdout.py run --data-dir "<kit-root>" --execute
```

The default cap is 303 requests: at most 100 classifications in each of three
arms plus three fresh synthetic gates. Actual usage depends on available reserved
groups. Retries are disabled; workers default to four. The conservative token
allowance is six million, divided equally across arms. The tool checks coverage
budgets before any API request. These byte-based token reservations are safeguards,
not exact tokenizer counts or billing guarantees. Actual reported token usage and
the saved standard-price snapshot determine the cost estimate.

Cold caches are new per run; warm runs have zero request allowance and must
reproduce successful cold decisions. Missing/inconsistent warm caches, failed
authentication, incomplete API coverage or invalid responses prevent a complete
measurement. Do not use warm speed/cost as a full unseen-data forecast.

Without `--execute`, the same command previews the frozen plan and local baseline
scores without API calls. This still opens scoring labels after the preview;
the strategy must already be fixed and must not be tuned from those scores.

Each invocation writes a separate private `runs/<id>/report.json` and executed
predictions. The run validates unchanged fingerprints before and after execution.
Do not publish contexts, labels, reference examples, private indexes or detailed
prediction reports. Aggregate measurements can be documented publicly.

## Interpretation

Offline verification passed for all three frozen arms, with 100 scorable records
each and unchanged input/code/index fingerprints. Including gates, conservative
reservation estimates are 1,074,495 units for A zero-label, 1,265,496 for A assisted
and 1,130,550 for B assisted; all fit the two-million-per-arm default. The full
suite passed 522 tests at preparation, including 16 reserved-evaluation checks.
No API request was made during preparation or preview; live results follow below.

Report this separately from the earlier development pilots. The reserved groups
were excluded from retrieval training and prompt-specific pilot selection, but
earlier whole-data lexical evaluation and eligibility review have been disclosed.
This is not a pristine external test. Seed noise, group sampling, modest sample
size and absent C data limit the conclusions. No winning strategy is selected
automatically.

After seeing these results, changing prompts/indexes or selecting another strategy
using the scores makes them development evidence for that change. Preserve the
current report and disclose the distinction rather than reusing the same score
as independent validation. Full-run rehearsal, financial exceptions, final export
validation, submission naming and release documentation remain separate work.

## Completed live evaluation

The authenticated-terminal run completed all 300 predictions and three synthetic
gates. Saved predictions, gold comparisons, costs and fingerprints were verified
offline. Every arm reproduced its decisions from cache without API requests.

| Arm | Correct / sampled | Leaf accuracy | Absolute-spend weighted leaf accuracy |
| --- | --- | --- | --- |
| A zero-label | 14 / 100 | 14% | 9.77% |
| A assisted | 39 / 100 | 39% | 28.25% |
| B assisted | 84 / 100 | 84% | 88.31% |

On the paired A records, assistance corrected 28 zero-label errors and regressed
three correct decisions. The 303 requests cost an estimated USD 0.25258875 using
the recorded pricing snapshot. These are sample measurements, not full-company
accuracy, calibrated confidence or a forecast for C. A zero-label performance
remains weak. The classifier and indexes remain fixed for the next
[full-company rehearsal](./REHEARSAL.md).
