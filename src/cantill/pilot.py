"""Fixed development samples and comparable classification pilot measurements."""

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from cantill.classify import TaxonomyClassifier
from cantill.config import ConfigError
from cantill.entities import Groups, scope
from cantill.llm import canonical, context_for
from cantill.matching import description_key, informative, reference_key
from cantill.metrics import classification_metrics


PILOT_PROTOCOL = "cantill-classification-pilot-v1"


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def partition_records(rows):
    """Keep repeated contexts, scoped items/invoices and matched purchases together."""
    groups, anchors = Groups(), {}
    for row in sorted(rows, key=lambda row: row["record_id"]):
        rid = row["record_id"]
        groups.find(rid)
        identities = [("context", canonical(context_for(row)))]
        if row["item_code"].strip():
            identities.append(("item", scope(row), row["item_code"].strip()))
        if row["invoice_number"].strip():
            identities.append(("invoice", scope(row), row["supplier_key"], reference_key(row["invoice_number"])))
        for text in (row["description"], row["service_text"]):
            if informative(text):
                identities.append(("description", description_key(text)))
        for identity in identities:
            if identity in anchors:
                groups.join(rid, anchors[identity])
            else:
                anchors[identity] = rid
        for root in row["duplicate_of"]:
            groups.join(rid, root)
    members = defaultdict(list)
    for row in rows:
        members[groups.find(row["record_id"])].append(row["record_id"])
    group_ids = {root: digest([PILOT_PROTOCOL, sorted(ids)]) for root, ids in members.items()}
    return {row["record_id"]: {"group": group_ids[groups.find(row["record_id"])],
                             "partition": "holdout" if int(group_ids[groups.find(row["record_id"])], 16) % 5 == 0 else "development"}
            for row in rows}


def stratum(row, model):
    text = row["description"].strip() or row["service_text"].strip()
    if not text:
        return "blank"
    if not informative(text):
        return "generic_or_very_short"
    if any(ord(character) > 127 and character.isalpha() for character in text):
        return "non_ascii"
    account = row["account_description"].strip()
    if account:
        left, left_score, _ = model.predict(text)
        right, right_score, _ = model.predict(account_description=account)
        if left_score > 0 and right_score > 0 and left != right:
            return "lexical_account_disagreement"
    return "short_text" if len(text.split()) <= 3 else "longer_text"


def select_samples(records, taxonomy, *, sample_size, source=None, cohort_ids=None):
    if type(sample_size) is not int or not 1 <= sample_size <= 500:
        raise ConfigError("Pilot sample_size must be an integer in [1, 500]")
    rows = records.to_dict("records")
    if source is not None and source not in {row["source"] for row in rows}:
        raise ConfigError("Pilot source must reference an ingested logical source")
    partitions = partition_records(rows)
    model, buckets = TaxonomyClassifier(taxonomy), defaultdict(list)
    candidates = 0
    for row in rows:
        rid = row["record_id"]
        if (not row["include"] or partitions[rid]["partition"] != "development"
                or (source is not None and row["source"] != source)
                or (cohort_ids is not None and rid not in cohort_ids)):
            continue
        candidates += 1
        entry = {"record_id": rid, **partitions[rid], "context": context_for(row),
                 "local_path": [row[f"l{i}"] for i in range(1, 5) if row[f"l{i}"]],
                 "local_confidence": row["confidence"],
                 "spend": str(row["spend_value"]) if row["spend_value"] is not None else None,
                 "stratum": stratum(row, model)}
        buckets[entry["stratum"]].append(entry)
    for bucket in buckets.values():
        bucket.sort(key=lambda entry: digest([PILOT_PROTOCOL, entry["context"], entry["record_id"]]), reverse=True)
    selected, seen = [], set()
    while len(selected) < sample_size and any(buckets.values()):
        for name in sorted(buckets):
            while buckets[name]:
                entry = buckets[name].pop()
                key = digest(entry["context"])
                if key not in seen:
                    selected.append(entry)
                    seen.add(key)
                    break
            if len(selected) == sample_size:
                break
    return selected, partitions, {"candidate_rows": candidates, "selected_rows": len(selected),
                                  "requested_rows": sample_size, "strata": dict(Counter(row["stratum"] for row in selected)),
                                  "partition_rows": dict(Counter(row["partition"] for row in partitions.values())),
                                  "partition_groups": len({row["group"] for row in partitions.values()})}


def score_predictions(samples, predictions, labels):
    scored, by_stratum = [], defaultdict(list)
    for sample, (path, confidence) in zip(samples, predictions, strict=True):
        label = labels.get(sample["record_id"])
        if label is None or ("include" in label and label["include"] != "1"):
            continue
        golden = tuple(label.get(f"l{i}", "") for i in range(1, 5) if label.get(f"l{i}", ""))
        if not golden:
            continue
        row = {"predicted": tuple(path), "golden": golden, "confidence": confidence, "spend": sample["spend"]}
        scored.append(row)
        by_stratum[sample["stratum"]].append(row)
    return {"all": classification_metrics(scored),
            "by_stratum": {key: classification_metrics(value) for key, value in sorted(by_stratum.items())},
            "unscored_rows": len(samples) - len(scored)}


def cost_estimate(usage, rates, lines):
    """Public standard-token estimate, not an invoice or a population forecast."""
    if rates is None:
        return {"usd": None, "usd_per_1000_sample_lines": None, "status": "missing_price"}
    parsed = {}
    try:
        for key in ("input", "cached_input", "output"):
            value = Decimal(str(rates[key]))
            if not value.is_finite() or value < 0:
                raise ValueError
            parsed[key] = value
    except (KeyError, InvalidOperation, ValueError, TypeError):
        raise ConfigError("Pilot prices must provide finite nonnegative input/cached_input/output USD per million tokens") from None
    if usage.get("api_errors") or usage.get("responses_without_usage"):
        return {"usd": None, "usd_per_1000_sample_lines": None, "status": "unknown_usage"}
    inputs, cached, outputs = (usage.get(key, 0) for key in ("input_tokens", "cached_input_tokens", "output_tokens"))
    if not 0 <= cached <= inputs:
        raise ConfigError("Pilot usage contains invalid cached token counts")
    value = ((inputs - cached) * parsed["input"] + cached * parsed["cached_input"] + outputs * parsed["output"]) / Decimal(1_000_000)
    return {"usd": str(value), "usd_per_1000_sample_lines": str(value * 1000 / lines) if lines else None,
            "status": "public_standard_price_estimate", "price_source": rates.get("source"), "price_as_of": rates.get("as_of")}
