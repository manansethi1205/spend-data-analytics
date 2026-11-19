"""Matching declarations independent of ingestion and company identity."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CrossSourceMatch:
    preferred: str
    secondary: str
    po_pattern: str
    amount_tolerance: Decimal = Decimal("0.01")
    quantity_tolerance: Decimal = Decimal("0.000001")
    supplier_similarity: float = 0.85
    description_similarity: float = 0.80
    no_po_supplier_similarity: float = 0.90
    no_po_description_similarity: float = 0.92
    weak_supplier_similarity: float = 0.65
    max_no_po_date_gap_days: int = 45
    max_candidates: int = 200
    max_group_size: int = 20


@dataclass(frozen=True)
class MatchingConfig:
    repeat_sources: tuple[str, ...] = ()
    cross_sources: tuple[CrossSourceMatch, ...] = ()
