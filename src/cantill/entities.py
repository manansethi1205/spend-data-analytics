"""Label-free supplier and item grouping with reproducible, opaque keys."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import re

import pandas as pd

from cantill.matching import MatchedCompany, description_key, informative, similarity, supplier_key
from cantill.rules import clean_text


def opaque_key(kind, company, identity):
    payload = json.dumps([company, identity], ensure_ascii=False, separators=(",", ":"))
    return kind + "_" + sha256(payload.encode()).hexdigest()[:24]


def scope(row):
    # A logical source is the namespace when an ERP identifier is unavailable.
    return row["source_system"].strip() or row["source"]


def item_text(row):
    return description_key(row["description"].strip() or row["service_text"])


def item_unit(row):
    return clean_text(row["unit"].strip() or row["po_unit"])


class Groups:
    def __init__(self):
        self.parent = {}

    def find(self, key):
        self.parent.setdefault(key, key)
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != key:
            previous = self.parent[key]
            self.parent[key] = root
            key = previous
        return root

    def join(self, left, right):
        a, b = sorted((self.find(left), self.find(right)))
        self.parent[b] = a


@dataclass
class ResolvedCompany:
    matched: MatchedCompany
    records: pd.DataFrame

    def summary(self):
        included = self.records["include"] == 1
        return {**self.matched.summary(),
                "supplier_groups": self.records.loc[included, "supplier_key"].nunique(),
                "item_groups": self.records.loc[included, "item_key"].nunique(),
                "entity_flags": dict(Counter(f for flags in self.records["entity_flags"] for f in flags)),
                "scope": "Label-free entity groups; names and codes are evidence, not guaranteed real-world identity"}


def resolve_entities(company: MatchedCompany) -> ResolvedCompany:
    rows = company.records.to_dict("records")
    company_id = company.eligible.normalized.ingested.config.company_id
    suppliers = Groups()
    identities, flags, names = {}, {}, set()
    for row in rows:
        rid = row["record_id"]
        name = supplier_key(row["supplier_name"])
        vendor = row["supplier_id"].strip()
        named = ("name", name) if len(name) >= 4 else None
        coded = ("vendor", scope(row), vendor) if vendor else None
        identity = coded or named or ("unknown", rid)
        suppliers.find(identity)
        flags[rid] = []
        if named:
            names.add(name)
            suppliers.join(identity, named)
        if not coded and not named:
            flags[rid].append("SUPPLIER_IDENTITY_MISSING")
        identities[rid] = identity

    # Complete-link clusters prevent a sequence of small edits from bridging
    # increasingly different names. Only bounded, long-name blocks are compared.
    blocks = defaultdict(list)
    for name in sorted(names):
        blocks[name[:3]].append(name)
    for block in blocks.values():
        if len(block) > 200:
            continue
        clusters = []
        for name in block:
            numeric = re.findall(r"\d+", name)
            candidates = [cluster for cluster in clusters if len(name) >= 8 and all(
                len(other) >= 8 and numeric == re.findall(r"\d+", other)
                and similarity(name, other) >= .94 for other in cluster)]
            if len(candidates) == 1:
                cluster = candidates[0]
                suppliers.join(("name", cluster[0]), ("name", name))
                cluster.append(name)
            else:
                clusters.append([name])

    supplier_keys = {rid: opaque_key("supplier", company_id, suppliers.find(identity))
                     for rid, identity in identities.items()}
    items = Groups()
    item_ids, aliases, code_signatures = {}, defaultdict(set), defaultdict(set)
    for row in rows:
        rid = row["record_id"]
        code = row["item_code"].strip()
        text = item_text(row)
        unit = item_unit(row)
        # A catalogue code is stable within its ERP. Different codes are joined
        # only through exact, informative specification text AND an explicit unit.
        identity = ("code", scope(row), code) if code else (
            ("text", supplier_keys[rid], text, unit) if informative(text) else ("unknown", rid))
        items.find(identity)
        item_ids[rid] = identity
        if code:
            code_signatures[identity].add((text, unit))
        if not code and not informative(text):
            flags[rid].append("ITEM_IDENTITY_MISSING")
    # Recycled catalogue descriptions are unsafe alias bridges: a code can have
    # many unrelated texts. Require one consistent text/unit signature per code
    # before connecting DIFFERENT codes. Keep the original scoped code intact.
    for row in rows:
        rid = row["record_id"]
        identity, text, unit = item_ids[rid], item_text(row), item_unit(row)
        if row["item_code"].strip():
            if len(code_signatures[identity]) > 1:
                flags[rid].append("ITEM_CODE_TEXT_CONFLICT")
            elif informative(text) and unit:
                aliases[(supplier_keys[rid], text, unit)].add(identity)
    for candidates in aliases.values():
        ordered = sorted(candidates)
        for identity in ordered[1:]:
            items.join(ordered[0], identity)
    for row in rows:
        rid = row["record_id"]
        text = item_text(row)
        unit = item_unit(row)
        candidates = aliases.get((supplier_keys[rid], text, unit), ()) if unit else ()
        if not row["item_code"].strip() and informative(text) and candidates:
            roots = {items.find(candidate) for candidate in candidates}
            if len(roots) == 1:
                items.join(item_ids[rid], next(iter(roots)))

    # A duplicate can inherit a single retained identity. Do not union catalogue
    # groups on a fuzzy purchase match, or collapse a multi-item receipt group.
    item_keys = {rid: opaque_key("item", company_id, items.find(identity)) for rid, identity in item_ids.items()}
    by_id = {row["record_id"]: row for row in rows}
    for row in rows:
        rid, roots = row["record_id"], row["duplicate_of"]
        if not roots:
            continue
        candidates = {supplier_keys[root] for root in roots}
        if len(candidates) == 1 and not row["supplier_id"].strip():
            supplier_keys[rid] = next(iter(candidates))
        candidates = {item_keys[root] for root in roots}
        if len(candidates) == 1 and not row["item_code"].strip():
            target = by_id[roots[0]]
            left, right = item_text(row), item_text(target)
            units_agree = not item_unit(row) or not item_unit(target) or item_unit(row) == item_unit(target)
            if left == right and informative(left) and units_agree:
                item_keys[rid] = next(iter(candidates))
            else:
                flags[rid].append("ITEM_MATCH_TEXT_DISAGREEMENT")
    records = company.records.copy()
    records["supplier_key"] = [supplier_keys[row["record_id"]] for row in rows]
    records["item_key"] = [item_keys[row["record_id"]] for row in rows]
    records["entity_flags"] = [tuple(flags[row["record_id"]]) for row in rows]
    return ResolvedCompany(company, records)
