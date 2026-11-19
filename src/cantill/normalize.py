"""Config-driven financial/date normalization with retained source values."""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache

import pandas as pd

from cantill.config import ConfigError
from cantill.ingest import IngestedCompany


@lru_cache(maxsize=32)
def number_pattern(decimal, thousands):
    integer = r"[0-9]+"
    if thousands:
        integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(thousands)}[0-9]{{3}})+)"
    point = re.escape(decimal)
    return re.compile(rf"[+-]?(?:{integer}(?:{point}[0-9]*)?|{point}[0-9]+)(?:[eE][+-]?[0-9]+)?")


def parse_number(value: str, formats: dict[str, str]) -> Decimal | None:
    value = value.strip()
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1].strip()
        if value.startswith(("+", "-")):
            return None
    decimal, thousands = formats["decimal"], formats["thousands"]
    if thousands == " ":
        value = value.replace("\u00a0", " ")
    if not number_pattern(decimal, thousands).fullmatch(value):
        return None
    if thousands:
        value = value.replace(thousands, "")
    value = value.replace(decimal, ".")
    try:
        result = Decimal(("-" if negative else "") + value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


@lru_cache(maxsize=100000)
def parse_date(value: str, formats: tuple[str, ...]):
    value = value.strip()
    if not value:
        return None, "", "MISSING"
    matches = []
    for fmt in formats:
        try:
            matches.append((datetime.strptime(value, fmt).date(), fmt))
        except ValueError:
            pass
    if not matches:
        return None, "", "INVALID"
    if len({date for date, _ in matches}) > 1:
        return None, "", "AMBIGUOUS"
    return matches[0][0], matches[0][1], ""


def currency_code(value):
    code = value.strip().upper()
    return code if re.fullmatch(r"[A-Z]{3}", code) else None


@dataclass
class NormalizedCompany:
    ingested: IngestedCompany
    records: pd.DataFrame
    reference_flags: Counter

    def summary(self):
        flags = Counter(flag for values in self.records["quality_flags"] for flag in values)
        ready = int(self.records["financial_ready"].sum())
        return {
            "company_id": self.ingested.config.company_id,
            "record_count": len(self.records), "financial_ready_rows": ready,
            "unresolved_financial_rows": len(self.records) - ready,
            "all_amounts_resolved": ready == len(self.records),
            "exchange_rate_sources": dict(Counter(self.records["exchange_rate_source"])),
            "vat_sources": dict(Counter(self.records["vat_source"])),
            "quality_flags": dict(flags), "reference_flags": dict(self.reference_flags),
            "scope": "All input records, before eligibility and purchase deduplication; not a spend total",
        }


def normalize_company(company: IngestedCompany) -> NormalizedCompany:
    reporting = currency_code(company.config.reporting_currency)
    if reporting is None:
        raise ConfigError("reporting_currency must be a three-letter currency code")
    fx, reference_flags = {}, Counter()
    if company.fx is not None:
        for row in company.fx.to_dict("records"):
            currency = currency_code(row["currency"])
            date, _, issue = parse_date(row["month"], (company.config.fx_month_format,))
            rate = parse_number(row["units_per_usd"], company.config.fx_number_format)
            if currency is None or issue:
                reference_flags["FX_KEY_INVALID"] += 1
                continue
            key = (currency, date.strftime("%Y-%m"))
            if key in fx:
                raise ConfigError("fx: duplicate normalized currency/month key")
            if rate is None or rate <= 0:
                reference_flags["FX_RATE_INVALID"] += 1
                rate = None
            fx[key] = rate

    source_configs = {s.name: s for s in company.config.sources}
    additions = []
    for row in company.records.to_dict("records"):
        source = source_configs[row["source"]]
        flags, parsed = [], {}
        for name, formats in source.date_formats.items():
            value, used, issue = parse_date(row[name], formats)
            parsed[name + "_value"] = value
            parsed[name + "_format"] = used
            if issue:
                flags.append(f"{name.upper()}_{issue}")
        invoice, posting = parsed.get("invoice_date_value"), parsed.get("posting_date_value")
        due, paid = parsed.get("due_date_value"), parsed.get("paid_date_value")
        if invoice and posting:
            if invoice > posting:
                flags.append("INVOICE_AFTER_POSTING")
            if abs((invoice - posting).days) > 366:
                flags.append("INVOICE_POSTING_GAP_OVER_366_DAYS")
        if invoice and due and due < invoice:
            flags.append("DUE_BEFORE_INVOICE")
        if invoice and paid and paid < invoice:
            flags.append("PAID_BEFORE_INVOICE")

        amount = parse_number(row["amount"], source.number_format)
        if amount is None:
            flags.append("AMOUNT_MISSING" if not row["amount"].strip() else "AMOUNT_INVALID")
            if not row["amount"].strip() and company.config.financial_fallback.missing_amount == "zero":
                amount = Decimal(0)
                flags.append("AMOUNT_ESTIMATED_ZERO")
        for name in ("quantity", "unit_cost"):
            parsed[name + "_value"] = parse_number(row[name], source.number_format)
            if row[name].strip() and parsed[name + "_value"] is None:
                flags.append(name.upper() + "_INVALID")

        vat, vat_source, net = None, "not_applicable", amount
        # Controlled precision for division; no currency-cent rounding at this stage.
        with localcontext() as context:
            context.prec = 50
            if source.amount_basis == "gross":
                raw_vat = row["vat_rate"].strip()
                if not raw_vat:
                    vat = Decimal(source.vat_default) if source.vat_default is not None else None
                    vat_source = "default" if vat is not None else "unresolved"
                    flags.append("VAT_DEFAULTED" if vat is not None else "VAT_MISSING")
                else:
                    percent = raw_vat.endswith("%")
                    vat = parse_number(raw_vat[:-1] if percent else raw_vat, source.number_format)
                    if vat is not None and (percent or vat > 1):
                        vat /= 100
                    if vat is None or not 0 <= vat <= 1:
                        vat, vat_source = None, "unresolved"
                        flags.append("VAT_INVALID")
                    else:
                        vat_source = "line"
                net = (amount if vat == 0 else amount / (1 + vat)) if amount is not None and vat is not None else None

            currency = currency_code(row["currency"])
            rate, rate_source, rate_convention, month = None, "unresolved", source.rate_convention, ""
            reference_month = ""
            if currency is None:
                flags.append("CURRENCY_MISSING" if not row["currency"].strip() else "CURRENCY_INVALID")
            elif currency == reporting:
                rate, rate_source, rate_convention = Decimal(1), "identity", "units_per_reporting"
            elif row["currency_rate"].strip():
                rate = parse_number(row["currency_rate"], source.number_format)
                if rate is None or rate <= 0:
                    flags.append("LINE_RATE_INVALID")
                    rate = None
                else:
                    rate_source = "line"
            elif reporting != "USD":
                flags.append("FX_RATE_MISSING")
            elif invoice is None:
                flags.append("FX_INVOICE_DATE_UNRESOLVED")
            else:
                month = invoice.strftime("%Y-%m")
                key = (currency, month)
                rate = fx.get(key)
                if rate is None:
                    flags.append("FX_RATE_INVALID" if key in fx else "FX_RATE_MISSING")
                    if key not in fx and company.config.financial_fallback.missing_fx == "nearest_month":
                        candidates = [(m, r) for (c, m), r in fx.items() if c == currency and r is not None]
                        if candidates:
                            target = invoice.year * 12 + invoice.month
                            # Equal-distance ties prefer the earlier month; no calendar/day inference.
                            reference_month, rate = min(candidates, key=lambda item: (
                                abs(int(item[0][:4]) * 12 + int(item[0][5:]) - target), item[0]))
                            rate_source, rate_convention = "nearest_month_fx", "units_per_reporting"
                            flags.append("FX_ESTIMATED_NEAREST_MONTH")
                else:
                    rate_source, rate_convention = "monthly_fx", "units_per_reporting"
                    reference_month = month
            converted = None
            if net is not None and rate is not None:
                if rate_source == "identity":
                    converted = net
                else:
                    converted = net / rate if rate_convention == "units_per_reporting" else net * rate

        additions.append({
            **parsed, "amount_value": amount, "net_amount_value": net,
            "vat_rate_value": vat, "vat_source": vat_source, "currency_value": currency,
            "exchange_rate_value": rate, "exchange_rate_source": rate_source,
            "exchange_rate_convention": rate_convention, "fx_month": month,
            "fx_reference_month": reference_month,
            "financial_estimated": any(f in flags for f in ("AMOUNT_ESTIMATED_ZERO", "FX_ESTIMATED_NEAREST_MONTH")),
            "reporting_amount_value": converted, "financial_ready": converted is not None,
            "quality_flags": tuple(flags),
        })
    columns = ["amount_value", "net_amount_value", "vat_rate_value", "vat_source", "currency_value",
               "exchange_rate_value", "exchange_rate_source", "exchange_rate_convention", "fx_month",
               "reporting_amount_value", "financial_ready", "quality_flags", "quantity_value", "unit_cost_value",
               "fx_reference_month", "financial_estimated"]
    dates = {name for source in company.config.sources for name in source.date_formats}
    columns += [name + suffix for name in sorted(dates) for suffix in ("_value", "_format")]
    extra = pd.DataFrame(additions, index=company.records.index, columns=columns, dtype=object)
    # Missing fields from another source are absent values, never string NaN or zero.
    extra = extra.where(pd.notna(extra), None)
    records = pd.concat([company.records.copy(deep=True), extra], axis=1)
    return NormalizedCompany(company, records, reference_flags)
