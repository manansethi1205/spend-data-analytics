# Supplier/item resolution and taxonomy-only baseline

Stages 9 and 10 provide a local baseline that runs from configured raw inputs to
entity keys and terminal category paths. It uses pandas, PyYAML and Python's
standard library, without model downloads, API keys, paid calls or label artifacts.
It is a measured development baseline, not a final quality claim.

## Execution and APIs

```powershell
uv run --locked cantill-spend resolve --config configs/company_A.yaml --data-dir "<kit-root>"
uv run --locked cantill-spend run --config configs/company_A.yaml --data-dir "<kit-root>" --output private/baseline_A.csv
uv run --locked cantill-spend run --config configs/company_B.yaml --data-dir "<kit-root>"
uv run --locked python tools/evaluate_baseline.py --kit-dir "<kit-root>"
```

`resolve_entities(MatchedCompany)` returns a `ResolvedCompany`. It adds
`supplier_key`, `item_key` and `entity_flags`, preserving all previous columns.
`classify_company(ResolvedCompany)` returns a `ClassifiedCompany`, adding exact
`l1` through `l4`, `confidence` and `classification_flags`.
`run_company(CompanyConfig)` performs all stages without loading labels.
`write_output(ClassifiedCompany, path)` writes the exact eleven-column contract,
validates a temporary CSV, then atomically replaces the selected destination.

`run` without `--output` prints aggregate counts only. Exit 0 means all included
financial values are available, exit 1 reports unresolved financial values, and
exit 2 reports configuration/export failure. No unresolved included amount is
filled with zero. A requested output cannot overwrite any configured input or
reference. Excluded rows retain entity keys, have zero spend/confidence and blank
category levels. These conventions are implementation choices allowed by the
output contract; confidence on excluded rows does not measure exclusion certainty.

## Supplier evidence

- Vendor IDs are scoped by mapped ERP ID, or logical source when ERP is absent.
  Equal IDs in different ERPs are not evidence of a shared supplier.
- Names use Unicode/accent/case normalization, punctuation and legal-suffix
  removal. Exact normalized names connect IDs and uncoded rows across sources.
- Long names with the same first three normalized characters may join at string
  similarity at least 0.94. Numeric tokens must agree. Complete-link comparisons
  prevent a chain of fuzzy edits from gradually bridging different names. Blocks
  above 200 names skip fuzzy comparisons. These are conservative design choices,
  not supplied rules or optimized thresholds.
- Missing IDs and unusable names receive separate per-record identities and
  `SUPPLIER_IDENTITY_MISSING`. An uncoded duplicate may inherit the common supplier
  of its retained purchase targets. No vendor-ID cluster is merged through that
  purchase-link inheritance.

There is no B supplier ground truth or name table. B grouping remains scoped-ID
based; cross-ERP aliases cannot be established from equal raw IDs alone. A's
golden supplier groups sometimes span unrelated anonymized names, which cannot
be safely inferred through spelling. Low measured recall is disclosed rather
than solved with a confidential golden-name lookup.

## Item evidence

Scoped material codes are the primary identity. Uncoded rows use supplier group,
normalized description (or service text when blank) and unit. Generic/missing
text receives a separate identity and `ITEM_IDENTITY_MISSING`; it is not one
global "unknown item" group. Normalization preserves numerical specifications.
Different unit names are not assumed to be equivalent.

Different codes can join through exact informative text, the same supplier and
an explicit identical unit, only when each code has one consistent text/unit
signature across its observed rows. Reused codes with different signatures are
flagged `ITEM_CODE_TEXT_CONFLICT` and cannot act as alias bridges. Their scoped
code identity is retained. This guard was added after reviewing baseline false
merges; its resulting evaluation is a development recheck, not a fresh holdout.

An uncoded duplicate may inherit an item when all retained targets have the same
item key, text agrees exactly and explicit units do not conflict. Fuzzy purchase
matches do not union catalogue items. Disagreements remain separate and flagged.
No price-based grouping or automatic specification/unit conversion is used.

Keys hash company ID and deterministic cluster identity; they contain no raw
names. They are reproducible for the same input set regardless of input order.
They are not a persistent registry: adding new alias evidence can change a
cluster's representative and its key. Grouping, rather than key spelling, is the
task's scoring target. Hashes are not a confidentiality guarantee for guessed names.

## Runtime tree and lexical classification

The classifier reads only terminal paths from the supplied tree. Trees may have
one to four levels and variable terminal depth. Invalid duplicate/nonterminal
paths fail. No company's category names, golden mappings or seed categories are
embedded in application code.

Word and character 3/4-gram features use Unicode normalization, generic stop words
and a light English plural normalization. Category documents weight leaf text
1.0 and each ancestor 0.35; inverse-document-frequency weights come only from
the runtime category documents. Query fields weight description/service text
1.0, account description 0.4 and material type 0.15. Supplier IDs, item IDs,
amounts and golden keys are not classifier features. Weighted sparse cosine
similarity ranks the paths; ties use a deterministic lexicographic path order.

Every included row gets a terminal path. No lexical overlap produces a zero
confidence fallback and `NO_TAXONOMY_OVERLAP`; tied best paths have zero confidence
and `TAXONOMY_TIE`. Otherwise confidence is the top-minus-runner-up cosine score,
bounded to [0,1]. It is an evidence score, not a calibrated correctness probability.
Generic, abbreviated and multilingual descriptions remain difficult. Character
overlap cannot establish semantics; weak accuracy demonstrates the need for
later semantic/label-assisted improvements, particularly for unseen company C.

## Evaluation protocol and boundaries

The evaluator disables the labels config, rejects any attempted label-table read,
runs all stages, and checks source-column preservation, nonblank keys and valid
included paths. Only afterward does it open labels and score predictions. No
A-derived alias table, model or golden key enters inference. Prior aggregate
profiling and the stage-7 eligibility review are disclosed; this is a strict
labels-hidden inference test of the current classifier, not a claim that the
developer never inspected any labels during the project.

Supplier/item metrics report pair precision/recall, false/missed pair counts and
B-cubed precision/recall. Blank golden item keys are excluded, never treated as
one shared item. Classification uses exact terminal paths and prefix correctness
at each level with that level's labelled denominator. Spend weighting uses
absolute normalized spend, so credits cannot cancel positive weights; unknown
spend is omitted from that denominator and counted separately. Zero weights
contribute nothing. Confidence-band accuracy is reported without claiming calibration.

B classification evaluates retained included seed lines, with skipped labelled
lines counted separately. Seeds are noisy and omit blank-description included
examples; their accuracy does not estimate accuracy on all B rows. There is no
unseen-C performance measurement. Synthetic four-level tests establish structural
support, not semantic generalization.

Detailed aggregate reports and the validated A baseline CSV stay in ignored
`private/baseline/`. Initial pre-review results are retained separately. B export
is blocked by the same eight financial exceptions; classification still runs for
all 37,910 included B rows. Final named submission outputs and release checks are
pending. Source hashes are checked unchanged by the evaluator.

## Measured development results

All 392 synthetic tests pass. Both companies retain their exact input record
counts (A 65,549; B 41,028). All 46,325 included A and 37,910 included B rows
receive keys and valid runtime terminal paths. A's private eleven-column output
passes independent output validation; B intentionally has no export yet.

| Classification measure | A: labels hidden, 37,029 ERP rows | B: 2,549 retained included seeds |
| --- | ---: | ---: |
| L1 path accuracy | 45.50% | 48.06% |
| L2 path accuracy | 20.64% | 46.84% |
| Terminal / L3 accuracy | 15.26% | 29.50% |
| Absolute-spend-weighted terminal accuracy | 23.24% | 28.99% |

One of B's 2,550 included seed rows was excluded as a purchase duplicate, so it
does not enter the classification denominator. Neither supplied tree has L4;
four-level behavior is tested synthetically. There is no A tool-line category
ground truth. No-overlap fallbacks occur on 1,535 included A and 13,111 included B
rows. Valid category coverage is not evidence of correct categories.

| A grouping measure | Supplier: 37,029 labelled rows | Item: 21,213 nonblank labels |
| --- | ---: | ---: |
| Label coverage of A ERP rows | 100% | 57.29% |
| Pair precision | 100% | 99.9956% |
| Pair recall | 10.00% | 48.08% |
| B-cubed precision | 100% | 99.91% |
| B-cubed recall | 47.33% | 89.76% |
| False merged pairs | 0 | 113 |
| Missed same-entity pairs | 203,705,694 | 2,766,570 |

These metrics are complementary: pair counts emphasize large groups. High
precision with low recall means the resolver leaves many true aliases separate;
it does not establish complete supplier/item resolution. A's evaluated supplier
prediction has 191 groups versus 70 golden groups. Item prediction has 2,627
groups versus 2,426 golden groups within its labelled subset.

Before the inconsistent-code guard, item pair precision was 80.20% with 659,298
false merged pairs. The generic guard reduces that to 113, while pair recall
falls from 50.11% to 48.08%. Both before/after results are development evidence
from the same labels, not independent accuracy estimates. Supplier thresholds
and classifier parameters were not tuned against these scores.

On native CPython 3.12.11 in this Windows workspace, the latest measured inference
run took approximately 71 seconds for A and 32 seconds for B, including ingestion,
normalization, eligibility, purchase matching, entity resolution and classification.
These timings exclude label-based scoring and export validation. A's export plus
independent revalidation took another 10 seconds. Earlier runs with tests also
running measured approximately 65 seconds A / 30 seconds B. These measurements
demonstrate baseline speed, not a clean-machine
release benchmark. No model download or API calls are involved; API cost is zero.
Final runtime and clean-checkout verification remain stage 14.
