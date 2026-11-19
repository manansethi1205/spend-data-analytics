# Zero-label classifier revision

The historical flat LLM measured 14% terminal accuracy (9.77% spend-weighted) on
the original 100-row A sample. New strategy accuracy is **not yet measured**:
the instruction to make no further paid API calls remains active.

## Selection and configuration

Zero-label API inference now defaults to hierarchical immediate-child selection.
Each prompt supplies candidate prefixes and descendant scope; its strict schema
permits only those child IDs. A representative leaf ID identifies each branch,
but cannot jump to another branch. Single-child steps are skipped; variable-depth
terminals stop traversal. A single-leaf tree uses one call. Invalid, refused,
incomplete or failed steps fall back to the existing local terminal prediction.
Parents never become terminal outputs. Path model confidence is the minimum
branch confidence, and any branch's review flag propagates to the result.

The alternative shortlist ranks terminal paths using local TF-IDF, then asks the
LLM to select among the top k full paths (default eight). Zero lexical overlap
uses the full hierarchy rather than an arbitrary alphabetical shortlist. The
fixed A sample's top-eight gold recall is only 34%; shortlist remains an
experimental alternative. Lexical recall does not measure LLM or C accuracy.

Supplier name now enters zero-label LLM context as supporting evidence, not proof
of the item category. Supplier text and category names remain untrusted data,
never instructions. Opaque supplier IDs, source IDs, amounts and golden keys are
not sent as fields. Labelled retrieval retains its separate backend/context.

```yaml
classification:
  mode: auto
  zero_label_strategy: hierarchical  # flat | hierarchical | shortlist
  shortlist_size: 8
  include_supplier_context: true
  confidence_mode: blended          # raw | blended
```

CLI overrides are `--zero-label-strategy`, `--shortlist-size`,
`--no-supplier-context` and `--confidence-mode`. Local mode remains API-free.
Each context reserves all possible branch calls and retries before execution.
Token allowances conservatively cover all levels. Strategy/tree/shortlist/supplier
context separate cache keys; historical caches and final CSVs remain untouched.

## Confidence

The default zero-label confidence is `0.7 * model_confidence + 0.3 * local_margin`,
where local margin is the nonnegative chosen-leaf similarity minus the strongest
other leaf. If another leaf wins locally, the margin is zero. Review halves the
blend and caps it at 0.49. Raw decisions remain cached; blending occurs after
inference/cache lookup. Label-assisted confidence and local fallbacks are unchanged.
This fixed heuristic is not a fitted probability calibrator.

On a no-API replay of the old 100 cached decisions, Brier score decreased from
0.192415 to 0.119296; fixed 10-bin ECE decreased from 0.218900 to 0.071916.
Category accuracy remains 14% because only confidence changed. These descriptive
results do not establish new-strategy accuracy or transferable calibration.

## Evaluation

[evaluate_zero_label.py](./tools/evaluate_zero_label.py) freezes the same original
100 A IDs/groups, checks source hashes and original contexts, and retains the
old evaluation. It loads no labelled index. Selection/shortlists precede gold;
live scoring follows inference and zero-request warm-cache verification.
This historical comparison requires the original private freeze and decision
cache; those confidential artifacts are not shipped in the public repository.

Four ablations isolate current flat, hierarchy without supplier, shortlist without
supplier, and hierarchy with supplier. Each run scores both raw and blended
confidence on the same decisions, avoiding another API run just for confidence.
Reports include terminal/per-level/spend-weighted accuracy, API-only/fallback
coverage, Brier/ECE, usage, runtime and cache reproduction. This reused sample
is now regression/development evidence, not a fresh independent holdout.

```powershell
uv run --locked python tools/evaluate_zero_label.py prepare --data-dir "<kit-root>"
uv run --locked python tools/evaluate_zero_label.py run --data-dir "<kit-root>" --variant hierarchical
```

Preparation/preview make no requests. Live execution requires `--execute` and
explicit sufficient `--max-requests`/`--max-tokens` (both default zero), restored
credits and renewed spending authorization. None was performed in this revision.
Prepared ceilings including a gate are 101 flat, 301 hierarchical, 103 shortlist
(one no-overlap hierarchy fallback), and 301 hierarchy-with-supplier requests.
These are worst-case ceilings, not a bill or a speed claim. No category names
are hard-coded in the classifier.

Schemas follow [official OpenAI Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses);
application validation still handles refusal, incomplete output and API failure.
