"""Validated company configuration, with no company-specific processing branches."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import math

import yaml

from cantill.rules import DEFAULT_RULES, RULE_FIELDS, EligibilityRule, clean_text
from cantill.match_config import CrossSourceMatch, MatchingConfig


class ConfigError(ValueError):
    """Invalid configuration or input contract."""


FIELDS = (
    "source_record_id", "source_system", "invoice_number", "invoice_line",
    "po_number", "po_line", "receipt_document", "receipt_line",
    "invoice_date", "posting_date", "due_date", "paid_date", "amount",
    "currency", "document_currency", "currency_rate", "vat_rate", "supplier_id",
    "supplier_name", "supplier_type", "item_code", "description", "service_text",
    "quantity", "unit", "po_unit", "unit_cost", "status", "document_type", "account_code",
    "account_description", "cost_centre", "company_code", "site_code", "site_name",
    "region", "spend_type", "material_type", "opex_capex", "contract_status",
    "contract_number", "po_type", "payment_terms", "transport_flag",
)
LABEL_FIELDS = ("l1", "l2", "l3", "l4", "include", "exclusion_reason", "supplier_key", "item_key")


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        pairs = self.construct_pairs(node, deep=deep)
        result = {}
        for key, value in pairs:
            if not isinstance(key, str) or key in result:
                raise ConfigError("Config keys must be unique strings")
            result[key] = value
        return result


def mapping(value, where, allowed, required=()):
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")
    if set(value) - set(allowed):
        raise ConfigError(f"{where} has unsupported keys: {sorted(set(value) - set(allowed))}")
    if set(required) - set(value):
        raise ConfigError(f"{where} is missing keys: {sorted(set(required) - set(value))}")
    return value


def text(value, where, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{where} must be a {'possibly empty ' if allow_empty else 'nonblank '}string")
    return value


def string_map(value, where, allowed):
    value = mapping(value, where, allowed)
    return {k: text(v, f"{where}.{k}", allow_empty=True) for k, v in value.items()}


@dataclass(frozen=True)
class CsvOptions:
    encoding: str = "utf-8-sig"
    delimiter: str = ","


@dataclass(frozen=True)
class TableConfig:
    path: str
    fields: dict[str, str]
    csv: CsvOptions
    record_id_prefix: str = ""


@dataclass(frozen=True)
class SourceConfig:
    name: str
    table: TableConfig
    constants: dict[str, str]
    amount_basis: str
    number_format: dict[str, str]
    date_formats: dict[str, tuple[str, ...]]
    vat_default: str | None
    rate_convention: str = "units_per_reporting"
    status_policy: str = "unavailable"
    approved_statuses: tuple[str, ...] = ("approved", "paid")
    cancelled_statuses: tuple[str, ...] = ("cancelled", "canceled")


@dataclass(frozen=True)
class ClassificationConfig:
    mode: str = "local"
    model: str = "gpt-5.4-mini-2026-03-17"
    workers: int = 4
    max_requests: int = 20
    max_tokens: int = 1_000_000
    max_output_tokens: int = 512
    timeout_seconds: float = 30
    retries: int = 1
    zero_label_strategy: str = "hierarchical"
    shortlist_size: int = 8
    include_supplier_context: bool = True
    confidence_mode: str = "blended"

    def __post_init__(self):
        if self.mode not in ("local", "openai", "auto"):
            raise ConfigError("classification.mode must be local, openai or auto")
        if self.zero_label_strategy not in ("flat", "hierarchical", "shortlist"):
            raise ConfigError("classification.zero_label_strategy must be flat, hierarchical or shortlist")
        if type(self.shortlist_size) is not int or not 2 <= self.shortlist_size <= 100:
            raise ConfigError("classification.shortlist_size must be an integer in [2, 100]")
        if type(self.include_supplier_context) is not bool or self.confidence_mode not in ("raw", "blended"):
            raise ConfigError("classification supplier context must be boolean and confidence_mode raw or blended")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigError("classification.model must be nonblank")
        for key, minimum, maximum in (("workers", 1, 32), ("max_requests", 0, 1_000_000),
                                      ("max_tokens", 0, 1_000_000_000), ("max_output_tokens", 128, 32768),
                                      ("retries", 0, 3)):
            value = getattr(self, key)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ConfigError(f"classification.{key} must be an integer in [{minimum}, {maximum}]")
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 120:
            raise ConfigError("classification.timeout_seconds must be finite in [1, 120]")


@dataclass(frozen=True)
class FinancialFallbackConfig:
    missing_amount: str = "strict"
    missing_fx: str = "strict"

    def __post_init__(self):
        if self.missing_amount not in ("strict", "zero"):
            raise ConfigError("financial_fallback.missing_amount must be strict or zero")
        if self.missing_fx not in ("strict", "nearest_month"):
            raise ConfigError("financial_fallback.missing_fx must be strict or nearest_month")


@dataclass(frozen=True)
class EntityResolutionConfig:
    supplier_similarity_threshold: float = .94
    supplier_jaccard_threshold: float = .8

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not .5 <= value <= 1:
                raise ConfigError(f"entity_resolution.{name} must be finite in [0.5, 1]")


@dataclass(frozen=True)
class CompanyConfig:
    company_id: str
    reporting_currency: str
    sources: tuple[SourceConfig, ...]
    taxonomy: TableConfig
    fx: TableConfig | None
    labels: TableConfig | None
    base_dir: Path
    fx_number_format: dict[str, str] | None = None
    fx_month_format: str = "%Y-%m"
    eligibility_rules: tuple[EligibilityRule, ...] = DEFAULT_RULES
    matching: MatchingConfig = MatchingConfig()
    classification: ClassificationConfig = ClassificationConfig()
    financial_fallback: FinancialFallbackConfig = FinancialFallbackConfig()
    entity_resolution: EntityResolutionConfig = EntityResolutionConfig()


def csv_options(value, defaults):
    value = mapping(value, "csv", {"encoding", "delimiter"})
    encoding = text(value.get("encoding", defaults.encoding), "csv.encoding")
    delimiter = text(value.get("delimiter", defaults.delimiter), "csv.delimiter", allow_empty=True)
    if len(delimiter) != 1 or delimiter in "\r\n\x00":
        raise ConfigError("csv.delimiter must be one non-newline character")
    return CsvOptions(encoding, delimiter)


def table_config(value, where, allowed_fields, defaults, required_fields=()):
    value = mapping(value, where, {"path", "fields", "csv", "record_id_prefix"}, {"path", "fields"})
    fields = string_map(value["fields"], f"{where}.fields", allowed_fields)
    if set(required_fields) - set(fields) or any(not v.strip() for v in fields.values()):
        raise ConfigError(f"{where}.fields must map required fields to nonblank column names")
    return TableConfig(
        text(value["path"], f"{where}.path"), fields,
        csv_options(value.get("csv", {}), defaults),
        text(value.get("record_id_prefix", ""), f"{where}.record_id_prefix", allow_empty=True),
    )


def number_format(value, where):
    value = mapping(value, where, {"decimal", "thousands"}, {"decimal", "thousands"})
    decimal = text(value["decimal"], f"{where}.decimal")
    thousands = text(value["thousands"], f"{where}.thousands", allow_empty=True)
    if decimal not in (".", ",") or len(thousands) > 1 or decimal == thousands:
        raise ConfigError("number_format requires dot/comma decimal and a distinct optional grouping character")
    if thousands and (thousands.isalnum() or thousands in "+-()%"):
        raise ConfigError("number_format grouping must not use digits, letters, signs or percent markers")
    return {"decimal": decimal, "thousands": thousands}


def string_list(value, where):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ConfigError(f"{where} must be a list of nonblank strings")
    return tuple(value)


def eligibility_rules(value, source_names):
    value = mapping(value, "eligibility", {"additional_rules", "disabled_rules"})
    additional = value.get("additional_rules", [])
    if not isinstance(additional, list):
        raise ConfigError("eligibility.additional_rules must be a list")
    disabled = string_list(value.get("disabled_rules", []), "eligibility.disabled_rules")
    if set(disabled) - {r.name for r in DEFAULT_RULES}:
        raise ConfigError("eligibility.disabled_rules must reference built-in rule names")
    rules = [rule for rule in DEFAULT_RULES if rule.name not in disabled]
    for rule in additional:
        rule = mapping(rule, "eligibility rule", {"name", "fields", "pattern", "sources"}, {"name", "fields", "pattern"})
        fields = string_list(rule["fields"], "eligibility rule.fields")
        sources = string_list(rule.get("sources", []), "eligibility rule.sources")
        if not fields or set(fields) - RULE_FIELDS or set(sources) - source_names:
            raise ConfigError("Eligibility rule fields/sources must reference supported context and declared sources")
        pattern = text(rule["pattern"], "eligibility rule.pattern")
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ConfigError("Eligibility rule has an invalid regex") from exc
        rules.append(EligibilityRule(text(rule["name"], "eligibility rule.name"), fields, pattern, sources))
    if len({r.name for r in rules}) != len(rules):
        raise ConfigError("Eligibility rule names must be unique")
    return tuple(rules)


def matching_config(value, source_names):
    value = mapping(value, "matching", {"repeat_sources", "cross_sources"})
    repeats = string_list(value.get("repeat_sources", []), "matching.repeat_sources")
    if len(set(repeats)) != len(repeats) or set(repeats) - source_names:
        raise ConfigError("matching.repeat_sources must reference unique declared sources")
    pairs = value.get("cross_sources", [])
    if not isinstance(pairs, list):
        raise ConfigError("matching.cross_sources must be a list")
    parsed = []
    for pair in pairs:
        allowed = set(CrossSourceMatch.__dataclass_fields__)
        pair = mapping(pair, "matching pair", allowed, {"preferred", "secondary", "po_pattern"})
        preferred, secondary = pair["preferred"], pair["secondary"]
        if not isinstance(preferred, str) or not isinstance(secondary, str) or preferred == secondary or {preferred, secondary} - source_names:
            raise ConfigError("Matching pair requires two different declared sources")
        pattern = text(pair["po_pattern"], "matching.po_pattern")
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ConfigError("Matching PO pattern must be a valid regex") from exc
        if "po" not in regex.groupindex or regex.search(""):
            raise ConfigError("Matching PO pattern must capture named group 'po' and not match empty text")
        options = dict(pair)
        for key in ("amount_tolerance", "quantity_tolerance"):
            if key in options:
                try:
                    number = Decimal(text(options[key], f"matching.{key}"))
                    if not number.is_finite() or number < 0:
                        raise InvalidOperation
                except InvalidOperation as exc:
                    raise ConfigError(f"matching.{key} must be a nonnegative finite decimal string") from exc
                options[key] = number
        for key in ("supplier_similarity", "description_similarity", "no_po_supplier_similarity", "no_po_description_similarity", "weak_supplier_similarity"):
            if key in options and (type(options[key]) not in (int, float) or not 0 <= options[key] <= 1):
                raise ConfigError(f"matching.{key} must be numeric in [0, 1]")
        for key in ("max_candidates", "max_group_size", "max_no_po_date_gap_days"):
            minimum = 0 if key == "max_no_po_date_gap_days" else 1
            if key in options and (type(options[key]) is not int or options[key] < minimum):
                raise ConfigError(f"matching.{key} must be an integer >= {minimum}")
        parsed.append(CrossSourceMatch(**options))
    if len({p.secondary for p in parsed}) != len(parsed) or {p.preferred for p in parsed} & {p.secondary for p in parsed}:
        raise ConfigError("Each secondary source may have one preferred source; chained/cyclic pairs are unsupported")
    return MatchingConfig(repeats, tuple(parsed))


def load_config(path: Path, data_dir: Path | None = None) -> CompanyConfig:
    try:
        value = yaml.load(Path(path).read_text(encoding="utf-8-sig"), Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigError("Cannot read config as safe YAML/JSON") from exc
    value = mapping(value, "config", {
        "schema_version", "company_id", "reporting_currency", "csv", "sources", "taxonomy", "fx", "labels", "eligibility", "matching", "classification", "financial_fallback", "entity_resolution",
    }, {"schema_version", "company_id", "reporting_currency", "sources", "taxonomy"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ConfigError("schema_version must be 1")
    defaults = csv_options(value.get("csv", {}), CsvOptions())
    if not isinstance(value["sources"], list) or not value["sources"]:
        raise ConfigError("sources must be a nonempty list")
    sources = []
    for i, source in enumerate(value["sources"]):
        where = f"sources[{i}]"
        source = mapping(source, where, {
            "name", "path", "fields", "csv", "record_id_prefix", "constants",
            "amount_basis", "number_format", "date_formats", "vat_default", "rate_convention",
            "status_policy", "approved_statuses", "cancelled_statuses",
        }, {"name", "path", "fields", "amount_basis", "number_format"})
        table = table_config(
            {k: source[k] for k in ("path", "fields", "csv", "record_id_prefix") if k in source},
            where, FIELDS, defaults, {"source_record_id", "amount"},
        )
        constants = string_map(source.get("constants", {}), f"{where}.constants", set(FIELDS) - {"source_record_id", "amount"})
        if set(constants) & set(table.fields):
            raise ConfigError(f"{where}: constants must not overwrite mapped columns")
        basis = source["amount_basis"]
        if basis not in ("net", "gross", "as_provided"):
            raise ConfigError(f"{where}.amount_basis must be net, gross or as_provided")
        formats = number_format(source["number_format"], f"{where}.number_format")
        convention = source.get("rate_convention", "units_per_reporting")
        if convention not in ("units_per_reporting", "reporting_per_unit"):
            raise ConfigError(f"{where}.rate_convention must be units_per_reporting or reporting_per_unit")
        date_fields = {k for k in set(table.fields) | set(constants) if k.endswith("_date")}
        dates = mapping(source.get("date_formats", {}), f"{where}.date_formats", date_fields)
        for key, options in dates.items():
            if not isinstance(options, list) or not options or any(not isinstance(fmt, str) or not fmt for fmt in options):
                raise ConfigError(f"{where}.date_formats.{key} must be a nonempty list of format strings")
        if date_fields - set(dates):
            raise ConfigError(f"{where}: every mapped date requires explicit formats")
        vat = source.get("vat_default")
        if vat is not None:
            text(vat, f"{where}.vat_default")
            try:
                rate = Decimal(vat)
                if not rate.is_finite() or not 0 <= rate <= 1:
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise ConfigError(f"{where}.vat_default must be a fractional rate from 0 to 1") from exc
        if basis == "gross" and "vat_rate" not in table.fields and "vat_rate" not in constants and vat is None:
            raise ConfigError(f"{where}: gross amounts require a VAT field or default")
        has_status = "status" in table.fields or "status" in constants
        policy = source.get("status_policy", "require_approved" if has_status else "unavailable")
        if policy not in ("require_approved", "unavailable"):
            raise ConfigError(f"{where}.status_policy must be require_approved or unavailable")
        if (policy == "require_approved") != has_status:
            raise ConfigError(f"{where}: status policy must agree with the presence of a status mapping/constant")
        approved = tuple(clean_text(v) for v in string_list(source.get("approved_statuses", ["approved", "paid"]), "approved_statuses"))
        cancelled = tuple(clean_text(v) for v in string_list(source.get("cancelled_statuses", ["cancelled", "canceled"]), "cancelled_statuses"))
        if not approved or set(approved) & set(cancelled):
            raise ConfigError(f"{where}: approved statuses must be nonempty and disjoint from cancelled statuses")
        sources.append(SourceConfig(text(source["name"], f"{where}.name"), table, constants, basis,
                                    formats, {k: tuple(v) for k, v in dates.items()}, vat, convention,
                                    policy, approved, cancelled))
    if len({s.name for s in sources}) != len(sources):
        raise ConfigError("Source names must be unique")
    taxonomy = table_config(value["taxonomy"], "taxonomy", {"l1", "l2", "l3", "l4"}, defaults, {"l1"})
    levels = set(taxonomy.fields)
    if levels != {f"l{i}" for i in range(1, len(levels) + 1)}:
        raise ConfigError("Taxonomy level mappings must be contiguous from l1")
    fx, fx_format, month_format = None, None, "%Y-%m"
    if "fx" in value:
        spec = mapping(value["fx"], "fx", {"path", "fields", "csv", "record_id_prefix", "number_format", "month_format"})
        fx = table_config({k: v for k, v in spec.items() if k not in ("number_format", "month_format")},
                          "fx", {"currency", "month", "units_per_usd"}, defaults,
                          {"currency", "month", "units_per_usd"})
        fx_format = number_format(spec.get("number_format", {"decimal": ".", "thousands": ""}), "fx.number_format")
        month_format = text(spec.get("month_format", "%Y-%m"), "fx.month_format")
        if text(value["reporting_currency"], "reporting_currency").strip().upper() != "USD":
            raise ConfigError("Monthly units_per_usd FX requires USD reporting currency")
    if taxonomy.record_id_prefix or (fx is not None and fx.record_id_prefix):
        raise ConfigError("record_id_prefix is only supported for purchase sources and labels")
    labels = table_config(value["labels"], "labels", {"record_id", *LABEL_FIELDS}, defaults,
                          {"record_id"}) if "labels" in value else None
    return CompanyConfig(
        text(value["company_id"], "company_id"), text(value["reporting_currency"], "reporting_currency"),
        tuple(sources), taxonomy, fx, labels,
        Path(data_dir).resolve() if data_dir is not None else Path(path).resolve().parent,
        fx_format, month_format,
        eligibility_rules(value.get("eligibility", {}), {s.name for s in sources}),
        matching_config(value.get("matching", {}), {s.name for s in sources}),
        ClassificationConfig(**mapping(value.get("classification", {}), "classification", ClassificationConfig.__dataclass_fields__)),
        FinancialFallbackConfig(**mapping(value.get("financial_fallback", {}), "financial_fallback", FinancialFallbackConfig.__dataclass_fields__)),
        EntityResolutionConfig(**mapping(value.get("entity_resolution", {}), "entity_resolution", EntityResolutionConfig.__dataclass_fields__)),
    )
