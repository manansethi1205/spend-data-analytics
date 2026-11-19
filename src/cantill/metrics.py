"""Grouping and hierarchy metrics used only after prediction."""

from collections import Counter, defaultdict
from fractions import Fraction


def grouping_metrics(predicted, golden):
    pairs = [(p, g) for p, g in zip(predicted, golden, strict=True) if g.strip()]
    joint, pred, gold = Counter(pairs), Counter(p for p, _ in pairs), Counter(g for _, g in pairs)
    choose = lambda count: count * (count - 1) // 2
    correct = sum(choose(count) for count in joint.values())
    proposed, true = sum(map(choose, pred.values())), sum(map(choose, gold.values()))
    n = len(pairs)
    return {"labelled_rows": n, "predicted_groups": len(pred), "golden_groups": len(gold),
            "pair_true_positive": correct, "pair_false_positive": proposed - correct,
            "pair_false_negative": true - correct,
            "pair_precision": correct / proposed if proposed else None,
            "pair_recall": correct / true if true else None,
            "b_cubed_precision": sum(count * count / pred[p] for (p, g), count in joint.items()) / n if n else None,
            "b_cubed_recall": sum(count * count / gold[g] for (p, g), count in joint.items()) / n if n else None}


def classification_metrics(rows):
    """Rows have predicted/golden tuples, confidence and optional normalized spend."""
    rows = list(rows)
    n = len(rows)
    correct = [r["predicted"] == r["golden"] for r in rows]
    weights = [abs(Fraction(r["spend"])) if r["spend"] is not None else None for r in rows]
    denominator = sum((weight for weight in weights if weight is not None), Fraction(0))
    bands = defaultdict(lambda: [0, 0])
    for row, success in zip(rows, correct, strict=True):
        band = "0" if row["confidence"] == 0 else ("(0,0.1]" if row["confidence"] <= .1 else ("(0.1,0.3]" if row["confidence"] <= .3 else "(0.3,1]"))
        bands[band][0] += 1
        bands[band][1] += int(success)
    levels = {}
    for level in range(1, 5):
        eligible = [r for r in rows if len(r["golden"]) >= level]
        levels[f"l{level}_path_accuracy"] = (sum(r["predicted"][:level] == r["golden"][:level] for r in eligible) / len(eligible)) if eligible else None
    return {"evaluated_rows": n, "terminal_accuracy": sum(correct) / n if n else None, **levels,
            "absolute_spend_weighted_terminal_accuracy": float(sum((w for w, c in zip(weights, correct, strict=True) if w is not None and c), Fraction(0)) / denominator) if denominator else None,
            "rows_with_missing_spend": sum(w is None for w in weights),
            "confidence_bands": {key: {"rows": count, "terminal_accuracy": successes / count} for key, (count, successes) in sorted(bands.items())}}
