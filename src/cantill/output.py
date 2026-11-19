"""Submission CSV contract checks; does not assess prediction or spend accuracy."""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Iterable, Sequence


OUTPUT_COLUMNS = (
    "record_id", "include", "exclusion_reason", "supplier_key", "item_key",
    "spend", "l1", "l2", "l3", "l4", "confidence",
)
EXCLUSION_CODES = frozenset({"CANCELLED", "NOT_APPROVED", "NON_PROCUREMENT", "DUPLICATE"})
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


@dataclass
class ValidationResult:
    row_count: int = 0
    included_rows: int = 0
    excluded_rows: int = 0
    total_spend: Decimal = Decimal(0)
    error_counts: Counter = field(default_factory=Counter)
    examples: list[dict] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.error_counts

    def error(self, code: str, row: int | None = None, count: int = 1):
        self.error_counts[code] += count
        # No IDs, names, descriptions or submitted cell values in diagnostics.
        if len(self.examples) < 20:
            self.examples.append({"code": code, "data_row": row, "count": count})

    def summary(self) -> dict:
        return {
            "valid": self.valid, "row_count": self.row_count,
            "included_rows": self.included_rows, "excluded_rows": self.excluded_rows,
            "total_spend": str(self.total_spend) if self.valid else None,
            "error_counts": dict(self.error_counts), "examples": self.examples,
        }


def decimal_cell(value: str) -> Decimal | None:
    """Finite dot-decimal/scientific numbers, without grouping or null tokens."""
    value = value.strip()
    if NUMBER.fullmatch(value) is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def add_exact(left: Decimal, right: Decimal) -> Decimal:
    """Sum finite decimals without the process decimal context rounding."""
    lowest = min(left.as_tuple().exponent, right.as_tuple().exponent)
    highest = max(left.adjusted(), right.adjusted(), 0)
    with localcontext() as context:
        context.prec = max(highest - lowest + 2, 28)
        return left + right


def validate_output(
    path: Path,
    expected_record_ids: Iterable[str],
    taxonomy: Sequence[Sequence[str]],
) -> ValidationResult:
    result = ValidationResult()
    expected = Counter(expected_record_ids)
    if any(not isinstance(key, str) or not key.strip() or count != 1 for key, count in expected.items()):
        result.error("INVALID_EXPECTED_IDS")
        return result
    paths = {tuple(path) for path in taxonomy}
    if not paths or any(not 1 <= len(path) <= 4 or any(not isinstance(v, str) or not v.strip() for v in path) for path in paths):
        result.error("INVALID_TAXONOMY")
        return result
    # A parent explicitly listed alongside descendants is not a lowest-level leaf.
    parents = {path[:depth] for path in paths for depth in range(1, len(path))}
    terminals = paths - parents
    seen = Counter()
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            if next(reader, None) != list(OUTPUT_COLUMNS):
                result.error("HEADER_MISMATCH")
                return result
            for index, cells in enumerate(reader, start=1):
                result.row_count += 1
                if len(cells) != len(OUTPUT_COLUMNS):
                    result.error("CSV_ROW_WIDTH", index)
                    continue
                row = dict(zip(OUTPUT_COLUMNS, cells))
                key = row["record_id"]
                if not key.strip():
                    result.error("BLANK_RECORD_ID", index)
                seen[key] += 1
                if seen[key] > 1:
                    result.error("DUPLICATE_RECORD_ID", index)

                included = row["include"] == "1"
                excluded = row["include"] == "0"
                if not (included or excluded):
                    result.error("INVALID_INCLUDE", index)
                if included:
                    result.included_rows += 1
                    if row["exclusion_reason"] != "":
                        result.error("INCLUDED_EXCLUSION_REASON", index)
                if excluded:
                    result.excluded_rows += 1
                    if row["exclusion_reason"] not in EXCLUSION_CODES:
                        result.error("EXCLUDED_REASON_INVALID", index)

                for column in ("supplier_key", "item_key"):
                    if included and not row[column].strip():
                        result.error(f"{column.upper()}_REQUIRED", index)
                    elif row[column] and not row[column].strip():
                        result.error("WHITESPACE_ENTITY_KEY", index)

                spend = decimal_cell(row["spend"])
                if spend is None:
                    result.error("INVALID_SPEND", index)
                else:
                    result.total_spend = add_exact(result.total_spend, spend)
                    if excluded and spend != 0:
                        result.error("EXCLUDED_SPEND_NONZERO", index)
                confidence = decimal_cell(row["confidence"])
                if confidence is None or not 0 <= confidence <= 1:
                    result.error("INVALID_CONFIDENCE", index)

                categories = [row[f"l{i}"] for i in range(1, 5)]
                while categories and categories[-1] == "":
                    categories.pop()
                if not categories:
                    if included:
                        result.error("CATEGORY_REQUIRED", index)
                elif tuple(categories) not in terminals:
                    result.error("INVALID_CATEGORY_PATH", index)
    except (OSError, UnicodeError, csv.Error):
        result.error("CSV_READ_ERROR")
        return result
    missing = sum((expected - seen).values())
    extra = sum((seen - expected).values())
    if missing:
        result.error("MISSING_RECORDS", count=missing)
    if extra:
        result.error("EXTRA_RECORDS", count=extra)
    return result
