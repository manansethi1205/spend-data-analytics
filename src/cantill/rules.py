"""Generic procurement exclusion evidence; no company records or category names."""

from dataclasses import dataclass
import unicodedata


def clean_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


RULE_FIELDS = frozenset({
    "account_code", "account_description", "description", "service_text", "supplier_name",
    "supplier_id", "supplier_type", "document_type", "spend_type", "source_system", "company_code",
})


@dataclass(frozen=True)
class EligibilityRule:
    name: str
    fields: tuple[str, ...]
    pattern: str
    sources: tuple[str, ...] = ()


DEFAULT_RULES = (
    EligibilityRule(
        "intercompany_account", ("account_description",),
        r"^(?:ic[0-9]+|i\s*/?\s*c\s+payables?)$|\b(?:inter[ -]?company|intra[ -]?group)\b",
    ),
    EligibilityRule(
        "tax_control_line", ("description", "service_text", "account_description"),
        r"^(?:sales tax(?: expense)?|gst input tax|input vat|output vat|vat payable|vat receivable|"
        r"withholding tax|income tax payable|corporate income tax|tax payable|"
        r"state(?:\s*&\s*|\s+and\s+)local taxes|state taxes|local taxes)(?:\s*[-:/].*)?$",
    ),
    EligibilityRule(
        "intercompany_transfer", ("description", "service_text"),
        r"^(?:inter[ -]?company|intra[ -]?group)\s+(?:charges?|transfers?|billings?|payables?|receivables?|settlements?|recharges?)\b"
        r"(?!\s+(?:pricing|advisory|consulting)\b)",
    ),
    EligibilityRule(
        "royalty_payment", ("description", "service_text", "account_description"),
        r"^royalt(?:y|ies)(?:\s+(?:payments?|charges?|expense|fees?)\b|\s*[-:/]|\s*$)",
    ),
    EligibilityRule(
        "partner_billing", ("description", "service_text", "account_description"),
        r"^partner\s+(?:billings?|recharges?|settlements?)\b",
    ),
    EligibilityRule(
        "financing_cost", ("description", "service_text", "account_description"),
        r"^(?:interest expense|interest payable|financing costs?|finance charges?|loan interest|loan repayments?|dividend payments?)\b",
    ),
    EligibilityRule(
        "revenue_control", ("description", "service_text", "account_description"),
        r"^(?:sales revenue|revenue|customer receivables?|accounts receivable)(?:\s*[-:/].*)?$",
    ),
)
