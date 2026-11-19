"""Private labelled examples with explicit split boundaries and local retrieval."""

from collections import Counter, defaultdict
from functools import lru_cache
from hashlib import sha256
import json
from math import log, sqrt
from pathlib import Path

from cantill.classify import features
from cantill.config import ConfigError
from cantill.entities import scope
from cantill.llm import CONTEXT_FIELDS, canonical, context_for


PROTOCOL = "cantill-labelled-retrieval-v1"


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def item_identity(row):
    code = row.get("item_code", "").strip()
    return digest([scope(row), code]) if code else ""


def document(context):
    result = Counter()
    for field, weight in (("description", 1), ("service_text", 1),
                          ("account_description", .4), ("material_type", .15)):
        result.update({key: value * weight for key, value in features(context[field]).items()})
    return result


def build_payload(records, labels, taxonomy, company_id, partitions, evaluation_ids):
    """Only included development rows outside every evaluation-related group train."""
    rows = records.to_dict("records")
    ids = {row["record_id"] for row in rows}
    if set(partitions) != ids or not set(evaluation_ids) <= ids:
        raise ConfigError("Retrieval split must cover all records and evaluation IDs")
    if any(p.get("partition") not in ("development", "holdout") or not p.get("group") for p in partitions.values()):
        raise ConfigError("Invalid retrieval split")
    group_partitions = defaultdict(set)
    for entry in partitions.values():
        group_partitions[entry["group"]].add(entry["partition"])
    if any(len(values) != 1 for values in group_partitions.values()):
        raise ConfigError("Related group crosses development/holdout boundary")
    excluded = {p["group"] for p in partitions.values() if p["partition"] == "holdout"}
    excluded.update(partitions[rid]["group"] for rid in evaluation_ids)
    paths = {tuple(path) for path in taxonomy}
    examples, provenance, skipped = {}, [], Counter()
    for row in sorted(rows, key=lambda row: row["record_id"]):
        rid = row["record_id"]
        split = partitions[rid]
        if not row["include"] or split["group"] in excluded:
            continue
        label = labels.get(rid)
        if label is None or label.get("include", "1") != "1":
            skipped["unlabelled_or_excluded"] += 1
            continue
        path = tuple(label.get(f"l{i}", "") for i in range(1, 5) if label.get(f"l{i}", ""))
        if path not in paths:
            skipped["invalid_label_path"] += 1
            continue
        context, identity = context_for(row), item_identity(row)
        key = digest([context, identity])
        example = examples.setdefault(key, {"context": context, "item_identity": identity, "labels": Counter()})
        example["labels"][path] += 1
        provenance.append({"record_id": rid, "group": split["group"]})
    if not examples:
        raise ConfigError("No eligible development labels remain after leakage exclusions")
    serialized = []
    for _, entry in sorted(examples.items()):
        serialized.append({**entry, "labels": [{"path": list(path), "support": count}
                                               for path, count in sorted(entry["labels"].items())]})
    return {"protocol": PROTOCOL, "company_id": company_id,
            "taxonomy": sorted([list(path) for path in paths]), "examples": serialized,
            "training_rows": provenance, "excluded_groups": sorted(excluded),
            "evaluation_ids": sorted(evaluation_ids), "skipped": dict(skipped)}


class RetrievalIndex:
    def __init__(self, payload, *, company_id, taxonomy):
        paths = sorted([list(path) for path in taxonomy])
        if payload.get("protocol") != PROTOCOL or payload.get("company_id") != company_id or payload.get("taxonomy") != paths:
            raise ConfigError("Retrieval artifact company/taxonomy/protocol mismatch")
        excluded, evaluation = set(payload["excluded_groups"]), set(payload["evaluation_ids"])
        provenance = payload["training_rows"]
        if (len({row["record_id"] for row in provenance}) != len(provenance)
                or any(row["group"] in excluded or row["record_id"] in evaluation for row in provenance)):
            raise ConfigError("Retrieval artifact contains excluded training rows/groups")
        self.examples = payload["examples"]
        if not self.examples or not provenance:
            raise ConfigError("Empty retrieval artifact")
        total = 0
        for example in self.examples:
            if set(example["context"]) != set(CONTEXT_FIELDS) or any(not isinstance(v, str) for v in example["context"].values()):
                raise ConfigError("Invalid retrieval example context")
            if not isinstance(example["item_identity"], str) or not example["labels"]:
                raise ConfigError("Invalid retrieval identity/labels")
            for label in example["labels"]:
                if label["path"] not in paths or type(label["support"]) is not int or label["support"] <= 0:
                    raise ConfigError("Invalid retrieval label path/support")
                total += label["support"]
        if total != len(provenance):
            raise ConfigError("Retrieval support/provenance count mismatch")
        self.fingerprint = digest(payload)
        self.training_rows = len(provenance)
        documents = [document(example["context"]) for example in self.examples]
        frequency = Counter(key for doc in documents for key in doc)
        self.idf = {key: 1 + log((len(documents) + 1) / (count + 1)) for key, count in frequency.items()}
        self.postings, self.items = defaultdict(list), defaultdict(list)
        for index, (example, doc) in enumerate(zip(self.examples, documents, strict=True)):
            for key, value in self.vector(doc).items():
                self.postings[key].append((index, value))
            if example["item_identity"]:
                self.items[example["item_identity"]].append(index)
        self._lookup = lru_cache(maxsize=100000)(self._lookup)

    def vector(self, doc):
        values = {key: count * self.idf[key] for key, count in doc.items() if key in self.idf}
        norm = sqrt(sum(value * value for value in values.values()))
        return {key: value / norm for key, value in values.items()} if norm else {}

    def _lookup(self, serialized, identity):
        context = json.loads(serialized)
        scores = Counter()
        for key, value in self.vector(document(context)).items():
            for index, weight in self.postings[key]:
                scores[index] += value * weight
        exact = set(self.items.get(identity, ())) if identity else set()
        candidates = {index for index, score in scores.items() if score >= .2} | exact
        ranked = sorted(candidates, key=lambda index: (index not in exact, -scores[index], index))[:4]
        # Conflicting categories within an example are all retained, including minority labels.
        return [{"line": self.examples[index]["context"], "labels": self.examples[index]["labels"],
                 "similarity": min(1.0, scores[index]),
                 "evidence": "scoped_item_code" if index in exact else "text_similarity"} for index in ranked]

    def lookup(self, row):
        return self._lookup(canonical(context_for(row)), item_identity(row))

    def context(self, row):
        return {**context_for(row), "labelled_examples": self.lookup(row)}

    def predict(self, row):
        votes = Counter()
        examples = self.lookup(row)
        for example in examples:
            weight = 1.0 if example["evidence"] == "scoped_item_code" else example["similarity"]
            total = sum(label["support"] for label in example["labels"])
            for label in example["labels"]:
                votes[tuple(label["path"])] += weight * label["support"] / total
        if not votes:
            return None
        ranked = sorted(votes, key=lambda path: (-votes[path], path))
        # Evidence margin only; neither label frequencies nor similarities are calibrated.
        margin = (votes[ranked[0]] - (votes[ranked[1]] if len(ranked) > 1 else 0)) / sum(votes.values())
        strongest = max(1.0 if e["evidence"] == "scoped_item_code" else e["similarity"] for e in examples)
        return ranked[0], min(1.0, max(0.0, margin * strongest)), "RETRIEVAL_CONFLICT" if len(votes) > 1 else ""

    @classmethod
    def load(cls, path, *, company_id, taxonomy):
        try:
            frozen = json.loads(Path(path).read_text(encoding="utf-8"))
            if frozen["integrity"] != digest(frozen["payload"]):
                raise ConfigError("Retrieval artifact integrity mismatch")
            return cls(frozen["payload"], company_id=company_id, taxonomy=taxonomy)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ConfigError):
                raise
            raise ConfigError("Cannot load private retrieval artifact") from None
