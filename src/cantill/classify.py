"""Local taxonomy-only lexical baseline. Scores are not calibrated probabilities."""

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import log, sqrt
import re

import pandas as pd

from cantill.config import ConfigError
from cantill.entities import ResolvedCompany
from cantill.matching import description_key


STOP_WORDS = frozenset({"and", "or", "of", "for", "the", "a", "an", "to", "in", "with", "other", "miscellaneous"})


def features(text):
    words = [word for word in re.findall(r"[^\W_]+", description_key(text))
             if word not in STOP_WORDS and not word.isdigit()]
    result = Counter()
    for word in words:
        # Light, explicit plural normalization; no category-specific dictionaries.
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        result["w:" + word] += 1
        padded = " " + word + " "
        for size in (3, 4):
            for index in range(len(padded) - size + 1):
                result["c:" + padded[index:index + size]] += .15
    return result


class TaxonomyClassifier:
    def __init__(self, taxonomy):
        paths = tuple(sorted(tuple(path) for path in taxonomy))
        if not paths or any(not 1 <= len(path) <= 4 or any(not level.strip() for level in path) for path in paths):
            raise ConfigError("classification: expected nonempty terminal paths of depth 1 to 4")
        if len(set(paths)) != len(paths) or any(path == other[:len(path)] for path in paths for other in paths if len(path) < len(other)):
            raise ConfigError("classification: duplicate or nonterminal taxonomy path")
        self.paths = paths
        documents = []
        for path in paths:
            document = Counter()
            for index, level in enumerate(path):
                weight = 1.0 if index == len(path) - 1 else .35
                document.update({key: value * weight for key, value in features(level).items()})
            documents.append(document)
        frequency = Counter(key for document in documents for key in document)
        self.idf = {key: 1 + log((1 + len(paths)) / (1 + count)) for key, count in frequency.items()}
        self.vectors = [self.vector(document) for document in documents]
        self._predict = lru_cache(maxsize=100000)(self._predict)

    def vector(self, document):
        values = {key: value * self.idf[key] for key, value in document.items() if key in self.idf}
        norm = sqrt(sum(value * value for value in values.values()))
        return {key: value / norm for key, value in values.items()} if norm else {}

    def predict(self, description="", service_text="", account_description="", material_type=""):
        return self._predict(description, service_text, account_description, material_type)

    def _predict(self, description, service_text, account_description, material_type):
        query = Counter()
        for text, weight in ((description, 1), (service_text, 1), (account_description, .4), (material_type, .15)):
            query.update({key: value * weight for key, value in features(text).items()})
        vector = self.vector(query)
        scores = [sum(value * vector.get(key, 0) for key, value in candidate.items()) for candidate in self.vectors]
        ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], self.paths[index]))
        first = ranked[0]
        best, second = scores[first], scores[ranked[1]] if len(ranked) > 1 else 0
        # Bounded evidence score includes separation; it is deliberately zero for
        # no overlap or a tied best category, including identical leaf names.
        confidence = min(1.0, max(0.0, best - second))
        flag = "NO_TAXONOMY_OVERLAP" if best == 0 else ("TAXONOMY_TIE" if abs(best - second) < 1e-12 else "")
        if flag:
            confidence = 0.0
        return self.paths[first], confidence, flag


@dataclass
class ClassifiedCompany:
    resolved: ResolvedCompany
    records: pd.DataFrame
    diagnostics: dict | None = None

    def summary(self):
        included = self.records["include"] == 1
        return {**self.resolved.summary(), "classified_rows": int(included.sum()),
                "classification_flags": dict(Counter(f for flags in self.records["classification_flags"] for f in flags)),
                "classifier": "taxonomy_lexical_v1" if self.diagnostics is None else self.diagnostics["mode"],
                "labels_used": bool(self.diagnostics and self.diagnostics.get("labels_used")),
                "classification_methods": dict(Counter(self.records["classification_method"])),
                "openai_usage": self.diagnostics,
                "confidence_mean": float(self.records.loc[included, "confidence"].mean()) if included.any() else None,
                "scope": "Runtime-tree classification; optional private labelled retrieval; confidence is method-specific and uncalibrated"}


def classify_company(company: ResolvedCompany, *, options=None, client=None, cache_dir=None, retrieval=None) -> ClassifiedCompany:
    options = options or company.matched.eligible.normalized.ingested.config.classification
    model = TaxonomyClassifier(company.matched.eligible.normalized.ingested.taxonomy)
    records = company.records.copy()
    predictions = []
    rows = records.to_dict("records")
    for row in rows:
        predictions.append(model.predict(*(row[field] for field in ("description", "service_text", "account_description", "material_type")))
                           if row["include"] else ((), 0.0, ""))
    methods = ["local" if row["include"] else "excluded" for row in rows]
    flags = [(flag,) if flag else () for _, _, flag in predictions]
    diagnostics = None
    if retrieval is not None:
        for index, row in enumerate(rows):
            if row["include"]:
                result = retrieval.predict(row)
                if result is not None:
                    predictions[index] = result
                    methods[index] = "retrieval"
                    flags[index] = (result[2],) if result[2] else ()
                else:
                    flags[index] += ("RETRIEVAL_NO_EVIDENCE",)
        diagnostics = {"mode": options.mode, "labels_used": True,
                       "retrieval_fingerprint": retrieval.fingerprint,
                       "retrieval_training_rows": retrieval.training_rows}
    if options.mode != "local":
        from cantill.llm import OpenAIClassifier, context_for
        backend = OpenAIClassifier(model.paths, options,
                                   company_id=company.matched.eligible.normalized.ingested.config.company_id,
                                   client=client, cache_dir=cache_dir, label_assisted=retrieval is not None,
                                   reference_fingerprint=retrieval.fingerprint if retrieval is not None else "")
        indices = [index for index, row in enumerate(rows) if row["include"]]
        results = backend.classify_many([retrieval.context(rows[index]) if retrieval is not None else context_for(rows[index])
                                         for index in indices])
        for index, (result, method, flag) in zip(indices, results, strict=True):
            if result is not None:
                methods[index] = method + ("_retrieval" if retrieval is not None else "")
                predictions[index] = (backend.paths[result["category_id"]], float(result["confidence"]), "")
                flags[index] = ("OPENAI_NEEDS_REVIEW",) if result["needs_review"] else ()
            else:
                flags[index] += (flag,)
        diagnostics = {**(diagnostics or {}), "mode": options.mode, "model": options.model, **dict(backend.stats),
                       "max_requests": options.max_requests, "max_tokens": options.max_tokens,
                       "confidence_semantics": "OpenAI/cache: model self-report; local/retrieval: evidence margin; none calibrated"}
    for index in range(4):
        records[f"l{index + 1}"] = [path[index] if index < len(path) else "" for path, _, _ in predictions]
    records["confidence"] = [confidence for _, confidence, _ in predictions]
    records["classification_flags"] = flags
    records["classification_method"] = methods
    return ClassifiedCompany(company, records, diagnostics)
