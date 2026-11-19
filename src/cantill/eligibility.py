"""Evidence-based procurement eligibility; purchase duplicates are a later stage."""

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from cantill.normalize import NormalizedCompany
from cantill.rules import clean_text


@dataclass
class EligibleCompany:
    normalized: NormalizedCompany
    records: pd.DataFrame

    def summary(self):
        eligible = self.records["eligible"]
        unresolved = eligible & ~self.records["financial_ready"].astype(bool)
        return {
            "company_id": self.normalized.ingested.config.company_id,
            "record_count": len(self.records), "eligible_rows": int(eligible.sum()),
            "excluded_rows": int((~eligible.astype(bool)).sum()),
            "exclusion_reasons": dict(Counter(self.records.loc[~eligible.astype(bool), "eligibility_reason"])),
            "eligible_unresolved_financial_rows": int(unresolved.sum()),
            "eligibility_flags": dict(Counter(flag for values in self.records["eligibility_flags"] for flag in values)),
            "rule_matches": dict(Counter(e for values in self.records["eligibility_evidence"] for e in values if e.startswith("rule:"))),
            "scope": "Procurement candidates before purchase deduplication; status absence is flagged, not verified approval",
        }


def assess_eligibility(company: NormalizedCompany) -> EligibleCompany:
    config = company.ingested.config
    sources = {s.name: s for s in config.sources}
    rules = [(rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in config.eligibility_rules]
    decisions = []
    for row in company.records.to_dict("records"):
        source = sources[row["source"]]
        reason, basis, flags, evidence = "", "no_exclusion_evidence", [], []
        if source.status_policy == "unavailable":
            flags.append("STATUS_UNAVAILABLE")
        else:
            status = clean_text(row["status"])
            if status in source.cancelled_statuses:
                reason, basis = "CANCELLED", "status_cancelled"
            elif status not in source.approved_statuses:
                reason, basis = "NOT_APPROVED", "status_not_approved"
                flags.append("STATUS_MISSING" if not status else "STATUS_NOT_ALLOWED")
            else:
                evidence.append("status:allowed")
            if reason:
                evidence.append("status:" + basis.removeprefix("status_"))
        matches = []
        for rule, pattern in rules:
            if rule.sources and row["source"] not in rule.sources:
                continue
            for field in rule.fields:
                value = clean_text(row[field])
                if value and pattern.search(value):
                    matches.append("rule:" + rule.name + ":" + field)
        evidence.extend(matches)
        if matches and not reason:
            reason, basis = "NON_PROCUREMENT", matches[0]
        eligible = not reason
        if eligible and not row["financial_ready"]:
            flags.append("ELIGIBLE_AMOUNT_UNRESOLVED")
        decisions.append({
            "eligible": eligible, "eligibility_reason": reason, "eligibility_basis": basis,
            "eligibility_evidence": tuple(evidence), "eligibility_flags": tuple(flags),
            "eligible_amount_value": row["reporting_amount_value"] if eligible else Decimal(0),
        })
    extra = pd.DataFrame(decisions, index=company.records.index, columns=[
        "eligible", "eligibility_reason", "eligibility_basis", "eligibility_evidence",
        "eligibility_flags", "eligible_amount_value",
    ], dtype=object)
    records = pd.concat([company.records.copy(deep=True), extra], axis=1)
    return EligibleCompany(company, records)
