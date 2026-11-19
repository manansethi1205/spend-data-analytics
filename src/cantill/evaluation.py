"""Label-independent grouping for the documented eligibility development split."""

import hashlib
import json

from cantill.rules import clean_text


ELIGIBILITY_PROTOCOL = "cantill-eligibility-v1"


def eligibility_group(row):
    description = clean_text(row["description"])
    key = ["description", description] if description else [
        "invoice", row["source_system"], row["supplier_id"], row["invoice_number"],
    ]
    value = ELIGIBILITY_PROTOCOL + "\0" + json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def eligibility_partition(group_sha256):
    return "holdout" if int(group_sha256, 16) % 5 == 0 else "development"
