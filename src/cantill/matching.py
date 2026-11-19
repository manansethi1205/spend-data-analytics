"""Count-once purchase matching with explicit evidence and allocation capacity."""

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
from difflib import SequenceMatcher
from functools import lru_cache

import pandas as pd

from cantill.config import ConfigError, FIELDS
from cantill.eligibility import EligibleCompany
from cantill.rules import clean_text


LEGAL_WORDS = frozenset({"pty", "ltd", "limited", "cc", "inc", "incorporated", "llc", "plc", "co", "company", "corp", "corporation", "the"})
GENERIC_TEXT = frozenset({"product", "products", "part", "parts", "item", "items", "service", "services", "goods", "materials", "material"})


def reference_key(value):
    return "".join(c for c in clean_text(value) if c.isalnum())


def supplier_key(value):
    text = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold()
    return "".join(word for word in re.findall(r"[^\W_]+", text) if word not in LEGAL_WORDS)


def description_key(value):
    text = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold()
    text = re.sub(r"(?<=[0-9]),(?=[0-9])", ".", text)
    return " ".join(re.sub(r"[^\w.]+", " ", text).split())


def informative(value):
    key = description_key(value)
    return key not in GENERIC_TEXT and sum(c.isalnum() for c in key) >= 6


@lru_cache(maxsize=100000)
def similarity(left, right):
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def line_key(value):
    try:
        number = Decimal(value.strip())
        if number.is_finite() and number == number.to_integral_value():
            return str(int(number))
    except (InvalidOperation, ValueError):
        pass
    return reference_key(value)


def po_reference(row, pattern):
    value = row["po_number"].strip()
    if not value:
        return "", line_key(row["po_line"]), ""
    matches = list(pattern.finditer(value))
    if len(matches) != 1:
        return "", "", "MULTIPLE_PO_REFERENCES" if len(matches) > 1 else "PO_REFERENCE_UNPARSEABLE"
    match = matches[0]
    po = reference_key(match.group("po") or "")
    captured = line_key(match.groupdict().get("line") or "")
    mapped = line_key(row["po_line"])
    if captured and mapped and captured != mapped:
        return po, "", "PO_LINE_METADATA_CONFLICT"
    return po, mapped or captured, ""


def numeric_spec(value):
    return frozenset(Decimal(s.replace(",", ".")) for s in re.findall(r"(?<![\w])[0-9]+(?:[.,][0-9]+)?", value))


def total(values):
    with localcontext() as context:
        context.prec = 60
        return sum(values, Decimal(0))


@dataclass
class MatchedCompany:
    eligible: EligibleCompany
    records: pd.DataFrame
    allocations: list[dict]

    def summary(self):
        included = self.records["include"] == 1
        duplicates = self.records["exclusion_reason"] == "DUPLICATE"
        return {
            "company_id": self.eligible.normalized.ingested.config.company_id,
            "record_count": len(self.records), "included_rows": int(included.sum()),
            "excluded_rows": int((~included).sum()), "duplicate_rows": int(duplicates.sum()),
            "exclusion_reasons": dict(Counter(self.records.loc[~included, "exclusion_reason"])),
            "duplicate_methods": dict(Counter(self.records.loc[duplicates, "match_method"])),
            "included_by_source": dict(Counter(self.records.loc[included, "source"])),
            "included_unresolved_financial_rows": int((included & ~self.records["financial_ready"].astype(bool)).sum()),
            "matching_flags": dict(Counter(flag for values in self.records["matching_flags"] for flag in values)),
            "scope": "Counted purchases before supplier/item resolution and classification; unmatched records are not proven source-only purchases",
        }


def count_purchases(company: EligibleCompany) -> MatchedCompany:
    with localcontext() as context:
        context.prec = 60
        return _count_purchases(company)


def _count_purchases(company: EligibleCompany) -> MatchedCompany:
    config = company.normalized.ingested.config
    rows = {row["record_id"]: row for row in company.records.to_dict("records")}
    states = {key: {"include": int(row["eligible"]), "exclusion_reason": row["eligibility_reason"],
                    "spend_value": row["eligible_amount_value"], "duplicate_of": (), "match_method": "",
                    "match_score": None, "match_evidence": (), "matching_flags": []} for key, row in rows.items()}
    source_configs = {s.name: s for s in config.sources}
    patterns = {}
    for pair in config.matching.cross_sources:
        pattern = re.compile(pair.po_pattern, re.IGNORECASE)
        for source in (pair.preferred, pair.secondary):
            if source in patterns and patterns[source].pattern != pattern.pattern:
                raise ConfigError("A matching source cannot have conflicting PO normalization patterns")
            patterns[source] = pattern
    refs = {}
    for key, row in rows.items():
        refs[key] = po_reference(row, patterns[row["source"]]) if row["source"] in patterns else (reference_key(row["po_number"]), line_key(row["po_line"]), "")
        if refs[key][2]:
            states[key]["matching_flags"].append(refs[key][2])
    allocations = []

    def bind(secondary, preferred, method, evidence, score=None, pair=None):
        for key in secondary:
            if not states[key]["include"]:
                raise ConfigError("Matching attempted to replace an existing exclusion")
            states[key].update(include=0, exclusion_reason="DUPLICATE", spend_value=Decimal(0),
                               duplicate_of=tuple(preferred), match_method=method, match_score=score,
                               match_evidence=tuple(evidence))
            if "numeric_spec_disagreement" in evidence:
                states[key]["matching_flags"].append("DESCRIPTION_NUMERIC_DISAGREEMENT")
            if "weak_supplier_name" in evidence:
                states[key]["matching_flags"].append("WEAK_SUPPLIER_NAME_EVIDENCE")
            if "date_unavailable" in evidence:
                states[key]["matching_flags"].append("NO_PO_DATE_UNAVAILABLE")
            if "long_cross_system_date_gap" in evidence:
                states[key]["matching_flags"].append("LONG_CROSS_SYSTEM_DATE_GAP")
        allocations.append({"method": method, "preferred_ids": tuple(preferred),
                            "secondary_ids": tuple(secondary), "source_pair": pair})

    def fingerprint(key):
        row = rows[key]
        values = []
        for field in FIELDS:
            if field in ("source_record_id", "status", "paid_date", "due_date", "posting_date"):
                continue
            value = row[field]
            if field == "po_number":
                value = refs[key][:2] if refs[key][0] and not refs[key][2] else value.strip()
            elif field in ("invoice_number",):
                value = reference_key(value)
            elif field in ("amount", "quantity", "unit_cost"):
                value = row.get(field + "_value") if row.get(field + "_value") is not None else ("raw", value)
            elif field == "vat_rate":
                value = row["vat_rate_value"] if row["vat_rate_value"] is not None else value.strip()
            elif field == "currency_rate":
                value = row["exchange_rate_value"]
            elif field == "currency":
                value = row["currency_value"]
            elif field.endswith("_date"):
                value = row.get(field + "_value") if row.get(field + "_value") is not None else value.strip()
            elif field in ("description", "service_text", "supplier_name"):
                value = clean_text(value)
            values.append(value)
        mapped = set(source_configs[row["source"]].table.fields.values())
        values.append(tuple(sorted((k, v) for k, v in row["raw"].items() if k not in mapped)))
        return tuple(values)

    for source in config.matching.repeat_sources:
        groups, identities = defaultdict(list), defaultdict(set)
        for key in sorted(rows):
            row = rows[key]
            if row["source"] != source or not states[key]["include"]:
                continue
            if not row["financial_ready"] or not row["invoice_number"].strip() or not (row["supplier_id"].strip() or row["supplier_name"].strip()):
                continue
            if not row["invoice_line"].strip() and not row["item_code"].strip() and not informative(row["description"]):
                states[key]["matching_flags"].append("REPEAT_IDENTITY_INSUFFICIENT")
                continue
            signature = fingerprint(key)
            groups[signature].append(key)
            if row["invoice_line"].strip():
                identity = (row["source_system"], row["company_code"], row["supplier_id"] or clean_text(row["supplier_name"]),
                            reference_key(row["invoice_number"]), row["invoice_line"].strip())
                identities[identity].add(signature)
        for keys in groups.values():
            representative = keys[0]
            row = rows[representative]
            if row["invoice_line"].strip():
                identity = (row["source_system"], row["company_code"], row["supplier_id"] or clean_text(row["supplier_name"]),
                            reference_key(row["invoice_number"]), row["invoice_line"].strip())
                if len(identities[identity]) > 1:
                    for key in keys:
                        states[key]["matching_flags"].append("INVOICE_LINE_CONFLICT")
            if len(keys) > 1:
                bind(keys[1:], (representative,), "repeat_export", ("invoice_identity", "full_business_fingerprint"), 1.0)
                if not row["invoice_line"].strip():
                    for key in keys:
                        states[key]["matching_flags"].append("REPEAT_WITHOUT_LINE_ID")

    for pair in config.matching.cross_sources:
        preferred = [key for key in sorted(rows) if rows[key]["source"] == pair.preferred and states[key]["include"] and rows[key]["financial_ready"]]
        secondary = [key for key in sorted(rows) if rows[key]["source"] == pair.secondary and states[key]["include"] and rows[key]["financial_ready"]]
        used, by_po, by_amount = set(), defaultdict(list), defaultdict(list)
        width = pair.amount_tolerance or Decimal("0.01")

        def bucket(amount):
            with localcontext() as context:
                context.prec = 60
                return int((amount / width).to_integral_value(rounding=ROUND_FLOOR))

        for key in preferred:
            if refs[key][0] and not refs[key][2]:
                by_po[refs[key][0]].append(key)
            by_amount[bucket(rows[key]["reporting_amount_value"])].append(key)

        def date_gap(left, right):
            a = left.get("invoice_date_value") or left.get("posting_date_value")
            b = right.get("posting_date_value") or right.get("invoice_date_value")
            return abs((a - b).days) if a is not None and b is not None else None

        def quantity_close(left, right):
            if left is None or right is None:
                return False
            return abs(left - right) <= pair.quantity_tolerance

        def candidate(left, right, left_ref, right_ref, tolerance, no_po):
            a, b = left["reporting_amount_value"], right["reporting_amount_value"]
            if a is None or b is None or (a > 0) != (b > 0) or (a < 0) != (b < 0) or abs(a - b) > tolerance:
                return None
            qa, qb = left["quantity_value"], right["quantity_value"]
            if a < 0 and qa is not None and qb is not None:
                qa, qb = abs(qa), abs(qb)
            if not quantity_close(qa, qb):
                return None
            if left_ref[1] and right_ref[1] and left_ref[1] != right_ref[1]:
                return None
            supplier = similarity(supplier_key(left["supplier_name"]), supplier_key(right["supplier_name"]))
            if not supplier and left["supplier_id"] and left["supplier_id"] == right["supplier_id"] and left["source_system"] and left["source_system"] == right["source_system"]:
                supplier = 1.0
            description = max(similarity(description_key(left[field]), description_key(right[other]))
                              for field in ("description", "service_text") for other in ("description", "service_text"))
            evidence = ["net_reporting_amount", "quantity", "supplier", "description"]
            gap = date_gap(left, right)
            if no_po:
                if not informative(left["description"] or left["service_text"]) or supplier < pair.no_po_supplier_similarity or description < pair.no_po_description_similarity:
                    return None
                specs_left, specs_right = numeric_spec(left["description"]), numeric_spec(right["description"])
                if specs_left and specs_right and specs_left != specs_right:
                    return None
                if gap is not None and gap > pair.max_no_po_date_gap_days:
                    return None
                evidence.append("bounded_date" if gap is not None else "date_unavailable")
            else:
                evidence.append("po")
                if gap is not None and gap > pair.max_no_po_date_gap_days:
                    evidence.append("long_cross_system_date_gap")
                explicit_line = bool(left_ref[1] and right_ref[1])
                if explicit_line:
                    evidence.append("po_line")
                strong = supplier >= pair.supplier_similarity and description >= pair.description_similarity
                weak_name = supplier >= pair.weak_supplier_similarity and description >= 0.97
                generic = explicit_line and supplier == 1 and not informative(left["description"] or left["service_text"])
                if not (strong or weak_name or generic):
                    return None
                if weak_name and not strong:
                    evidence.append("weak_supplier_name")
                specs_left, specs_right = numeric_spec(left["description"]), numeric_spec(right["description"])
                if specs_left and specs_right and specs_left != specs_right:
                    evidence.append("numeric_spec_disagreement")
            return {"score": (supplier + description) / 2, "delta": abs(a - b),
                    "gap": gap if gap is not None else 10**9, "evidence": tuple(evidence)}

        def signature(key):
            row = rows[key]
            return refs[key][:2] + (row["source_system"], row["item_code"].strip() or description_key(row["description"]),)

        def select(options, secondary_ids, no_po=False, quantity_budget=False):
            options = [option for option in options if quantity_budget or not set(option["ids"]) & used]
            options.sort(key=lambda o: (-o["score"], o["delta"], o["gap"], o["ids"]))
            if not options:
                return None
            top = options[0]
            others = [o for o in options[1:] if o["signature"] != top["signature"]]
            if others and top["score"] - others[0]["score"] < (0.05 if no_po else 0.03):
                for key in secondary_ids:
                    states[key]["matching_flags"].append("AMBIGUOUS_CROSS_SYSTEM_MATCH")
                return None
            return top

        def options_for(key, no_po=False):
            row, ref = rows[key], refs[key]
            if ref[2] in ("MULTIPLE_PO_REFERENCES", "PO_LINE_METADATA_CONFLICT"):
                return []
            if no_po:
                center = bucket(row["reporting_amount_value"])
                pool = [p for offset in (-1, 0, 1) for p in by_amount.get(center + offset, [])]
            else:
                pool = by_po.get(ref[0], [])
            options = []
            for preferred_key in pool:
                if preferred_key in used:
                    continue
                details = candidate(row, rows[preferred_key], ref, refs[preferred_key], pair.amount_tolerance, no_po)
                if details is not None:
                    options.append({**details, "ids": (preferred_key,), "signature": signature(preferred_key)})
                if len(options) > pair.max_candidates:
                    states[key]["matching_flags"].append("MATCH_CANDIDATE_LIMIT")
                    return []
            return options

        def allocate(keys, option, method):
            bind(keys, option["ids"], method, option["evidence"], option["score"], (pair.preferred, pair.secondary))
            used.update(option["ids"])

        jobs = [(key, options_for(key)) for key in secondary if refs[key][0]]
        jobs.sort(key=lambda job: (len(job[1]), -max((o["score"] for o in job[1]), default=0), job[0]))
        for key, options in jobs:
            chosen = select(options, (key,))
            if chosen:
                allocate((key,), chosen, "po_line_match" if refs[key][1] else "po_match")
            elif options and all(set(o["ids"]) & used for o in options):
                states[key]["matching_flags"].append("PREFERRED_CAPACITY_EXHAUSTED")

        # Full same-item receipt groups, never an arbitrary amount-only subset sum.
        receipt_groups = defaultdict(list)
        for key in preferred:
            row = rows[key]
            if key not in used and refs[key][0] and not refs[key][2]:
                receipt_groups[signature(key) + (row["reporting_amount_value"] < 0,)].append(key)
        receipt_by_po = defaultdict(list)
        for group in receipt_groups.values():
            if 2 <= len(group) <= pair.max_group_size:
                receipt_by_po[refs[group[0]][0]].append(group)
        for key in secondary:
            if not states[key]["include"] or not refs[key][0] or refs[key][2]:
                continue
            options = []
            for group in receipt_by_po.get(refs[key][0], []):
                if set(group) & used:
                    continue
                if any(rows[p]["quantity_value"] is None for p in group):
                    continue
                aggregate = {**rows[group[0]], "reporting_amount_value": total(rows[p]["reporting_amount_value"] for p in group),
                             "quantity_value": total(rows[p]["quantity_value"] for p in group)}
                details = candidate(rows[key], aggregate, refs[key], refs[group[0]], pair.amount_tolerance * len(group), False)
                if details is not None:
                    options.append({**details, "ids": tuple(group), "signature": signature(group[0])})
            chosen = select(options, (key,))
            if chosen:
                allocate((key,), chosen, "receipt_group")

        invoice_groups = defaultdict(list)
        for key in secondary:
            row = rows[key]
            if states[key]["include"] and refs[key][0] and not refs[key][2] and row["invoice_number"].strip():
                invoice_groups[(reference_key(row["invoice_number"]), refs[key][:2], supplier_key(row["supplier_name"]),
                                description_key(row["description"]), row["reporting_amount_value"] < 0)].append(key)
        for group in invoice_groups.values():
            if not 2 <= len(group) <= pair.max_group_size or any(rows[k]["quantity_value"] is None for k in group):
                continue
            key = group[0]
            dates = {rows[k].get("invoice_date_value") for k in group} - {None}
            if len(dates) > 1:
                for k in group:
                    states[k]["matching_flags"].append("INVOICE_GROUP_DATE_CONFLICT")
                continue
            aggregate = {**rows[key], "reporting_amount_value": total(rows[k]["reporting_amount_value"] for k in group),
                         "quantity_value": total(rows[k]["quantity_value"] for k in group)}
            options = []
            for p in by_po.get(refs[key][0], []):
                if p in used:
                    continue
                details = candidate(aggregate, rows[p], refs[key], refs[p], pair.amount_tolerance * len(group), False)
                if details is not None:
                    options.append({**details, "ids": (p,), "signature": signature(p)})
            chosen = select(options, group)
            if chosen:
                allocate(tuple(group), chosen, "invoice_group")

        # Partial invoices can be fully covered by a larger receipt, or a bounded
        # quantity allocation across same-item receipts. Never reduce an included
        # invoice's amount merely because only part of it appears covered.
        budget_groups = defaultdict(list)
        remaining = {}
        for key in preferred:
            row = rows[key]
            quantity = row["quantity_value"]
            if quantity is not None and quantity < 0 and row["reporting_amount_value"] > 0:
                states[key]["matching_flags"].append("QUANTITY_SIGN_CONFLICT")
                continue
            if key not in used and refs[key][0] and not refs[key][2] and quantity is not None and quantity != 0 and row["reporting_amount_value"] != 0:
                remaining[key] = {"quantity": abs(quantity), "amount": abs(row["reporting_amount_value"])}
                budget_groups[(refs[key][0], signature(key), row["reporting_amount_value"] < 0)].append(key)
        budgets_by_po = defaultdict(list)
        for (po, _, _), group in budget_groups.items():
            budgets_by_po[po].append(group)
        for key in secondary:
            if not states[key]["include"] or not refs[key][0] or refs[key][2]:
                continue
            row = rows[key]
            quantity, amount = row["quantity_value"], row["reporting_amount_value"]
            if quantity is None or quantity == 0 or amount == 0:
                continue
            if amount > 0 and quantity < 0:
                states[key]["matching_flags"].append("QUANTITY_SIGN_CONFLICT")
                continue
            wanted = abs(quantity)
            unit_price = abs(amount) / wanted
            options = []
            for group in budgets_by_po.get(refs[key][0], []):
                if (amount < 0) != (rows[group[0]]["reporting_amount_value"] < 0):
                    continue
                need, covered, claims = wanted, Decimal(0), {}
                ordered = sorted(group, key=lambda p: (date_gap(row, rows[p]) if date_gap(row, rows[p]) is not None else 10**9, p))
                for p in ordered:
                    balance, preferred_row = remaining[p], rows[p]
                    if balance["quantity"] <= 0:
                        continue
                    original_quantity = abs(preferred_row["quantity_value"])
                    price = abs(preferred_row["reporting_amount_value"]) / original_quantity
                    if abs(unit_price - price) > pair.amount_tolerance / min(wanted, original_quantity):
                        continue
                    take = min(need, balance["quantity"])
                    cost = balance["amount"] if take == balance["quantity"] else abs(preferred_row["reporting_amount_value"]) * take / original_quantity
                    claims[p] = {"quantity": take, "amount": cost}
                    covered += cost
                    need -= take
                    if need <= pair.quantity_tolerance:
                        break
                    if len(claims) >= pair.max_group_size:
                        break
                if need > pair.quantity_tolerance:
                    if claims:
                        states[key]["matching_flags"].append("QUANTITY_COVERAGE_INSUFFICIENT")
                    continue
                if not claims:
                    continue
                representative = next(iter(claims))
                aggregate = {**rows[representative], "reporting_amount_value": -covered if amount < 0 else covered,
                             "quantity_value": quantity}
                details = candidate(row, aggregate, refs[key], refs[representative], pair.amount_tolerance * len(claims), False)
                if details is not None:
                    options.append({**details, "ids": tuple(claims), "signature": signature(representative), "claims": claims})
            chosen = select(options, (key,), quantity_budget=True)
            if chosen:
                bind((key,), chosen["ids"], "quantity_coverage", (*chosen["evidence"], "unit_price", "quantity_budget"),
                     chosen["score"], (pair.preferred, pair.secondary))
                allocations[-1]["quantity_claims"] = {p: claim["quantity"] for p, claim in chosen["claims"].items()}
                allocations[-1]["amount_claims"] = {p: claim["amount"] for p, claim in chosen["claims"].items()}
                for p, claim in chosen["claims"].items():
                    remaining[p]["quantity"] -= claim["quantity"]
                    remaining[p]["amount"] -= claim["amount"]
                    used.add(p)

        jobs = [(key, options_for(key, True)) for key in secondary if states[key]["include"] and not refs[key][0]]
        jobs.sort(key=lambda job: (len(job[1]), -max((o["score"] for o in job[1]), default=0), job[0]))
        for key, options in jobs:
            chosen = select(options, (key,), True)
            if chosen:
                allocate((key,), chosen, "no_po_match")
            elif options and all(set(o["ids"]) & used for o in options):
                states[key]["matching_flags"].append("PREFERRED_CAPACITY_EXHAUSTED")
        for key in secondary:
            if states[key]["include"]:
                states[key]["matching_flags"].append("UNMATCHED_SECONDARY")

    def roots(key, visiting):
        if key in visiting:
            raise ConfigError("Matching duplicate links contain a cycle")
        if states[key]["include"]:
            return {key}
        targets = states[key]["duplicate_of"]
        if not targets:
            raise ConfigError("Matching duplicate links target a prior exclusion")
        return {root for target in targets for root in roots(target, visiting | {key})}

    for key, state in states.items():
        if state["duplicate_of"]:
            state["duplicate_of"] = tuple(sorted(roots(key, set())))
        state["matching_flags"] = tuple(dict.fromkeys(state["matching_flags"]))
    extra = pd.DataFrame([states[k] for k in company.records["record_id"]], index=company.records.index,
                         columns=["include", "exclusion_reason", "spend_value", "duplicate_of", "match_method",
                                  "match_score", "match_evidence", "matching_flags"], dtype=object)
    return MatchedCompany(company, pd.concat([company.records.copy(deep=True), extra], axis=1), allocations)
