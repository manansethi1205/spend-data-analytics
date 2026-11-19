"""Labelled retrieval boundaries, conflicting evidence and inference isolation."""

import json

import pandas as pd
import pytest

from test_llm import Client
from test_matching import factory
from cantill.classify import classify_company
from cantill.config import ClassificationConfig, ConfigError
from cantill.entities import resolve_entities
from cantill.llm import CONTEXT_FIELDS, OpenAIClassifier, context_for
from cantill.pipeline import run_company
from cantill.retrieval import RetrievalIndex, build_payload, digest


TREE = (("Goods", "Fasteners"), ("Services", "Cleaning"))


def row(rid, text="Steel bolts", **overrides):
    return {**dict.fromkeys(CONTEXT_FIELDS, ""), "record_id": rid, "include": 1,
            "description": text, "item_code": "", "source_system": "ERP", "source": "primary", **overrides}


def label(path=TREE[0]):
    return {f"l{i}": name for i, name in enumerate(path, 1)}


def payload():
    rows = [row("train"), row("evaluation"), row("relative"), row("holdout")]
    splits = {rid: {"group": group, "partition": part} for rid, group, part in (
        ("train", "safe", "development"), ("evaluation", "pilot", "development"),
        ("relative", "pilot", "development"), ("holdout", "reserved", "holdout"))}
    return build_payload(pd.DataFrame(rows), {r["record_id"]: label() for r in rows}, TREE,
                         "synthetic", splits, {"evaluation"})


def index(value=None):
    return RetrievalIndex(value or payload(), company_id="synthetic", taxonomy=TREE)


def test_builder_excludes_pilot_relatives_and_all_holdout_groups():
    value = payload()
    assert value["training_rows"] == [{"record_id": "train", "group": "safe"}]
    assert set(value["excluded_groups"]) == {"pilot", "reserved"}
    assert index(value).training_rows == 1


def test_missing_split_or_unknown_evaluation_id_rejected():
    with pytest.raises(ConfigError, match="cover"):
        build_payload(pd.DataFrame([row("a")]), {}, TREE, "synthetic", {}, {"a"})
    with pytest.raises(ConfigError, match="cover"):
        build_payload(pd.DataFrame([row("a")]), {}, TREE, "synthetic",
                      {"a": {"group": "g", "partition": "development"}}, {"unknown"})


def test_related_group_cannot_cross_partitions():
    with pytest.raises(ConfigError, match="crosses"):
        build_payload(pd.DataFrame([row("a"), row("b")]), {"a": label()}, TREE, "synthetic",
                      {"a": {"group": "g", "partition": "development"},
                       "b": {"group": "g", "partition": "holdout"}}, set())


def test_conflicting_categories_and_minority_labels_are_preserved():
    rows = [row("a"), row("b"), row("c")]
    value = build_payload(pd.DataFrame(rows), {"a": label(), "b": label(), "c": label(TREE[1])},
                          TREE, "synthetic", {r["record_id"]: {"group": "g", "partition": "development"} for r in rows}, set())
    model = index(value)
    assert [v["support"] for v in model.lookup(row("query"))[0]["labels"]] == [2, 1]
    prediction = model.predict(row("query"))
    assert prediction[0] == TREE[0] and prediction[2] == "RETRIEVAL_CONFLICT"
    assert prediction[1] < .5


@pytest.mark.parametrize("field,value", [("company_id", "other"), ("taxonomy", [["Unknown"]]),
                                        ("protocol", "other")])
def test_company_tree_and_protocol_isolation(field, value):
    bad = payload()
    bad[field] = value
    with pytest.raises(ConfigError, match="mismatch"):
        index(bad)


@pytest.mark.parametrize("change", ["group", "record_id", "support", "path"])
def test_bad_artifact_evidence_is_rejected(change):
    bad = payload()
    if change in ("group", "record_id"):
        bad["training_rows"][0][change] = "pilot" if change == "group" else "evaluation"
    else:
        bad["examples"][0]["labels"][0][change] = 0 if change == "support" else ["Unknown"]
    with pytest.raises(ConfigError):
        index(bad)


def test_no_matching_text_or_identity_abstains():
    assert index().predict(row("query", text="")) is None


def test_item_identity_is_scoped_and_never_sent_as_an_example_field():
    rows = [row("a", item_code="PART-1")]
    value = build_payload(pd.DataFrame(rows), {"a": label()}, TREE, "synthetic",
                          {"a": {"group": "g", "partition": "development"}}, set())
    model = index(value)
    assert model.lookup(row("q", text="", item_code="PART-1"))[0]["evidence"] == "scoped_item_code"
    assert not model.lookup(row("q", text="", item_code="PART-1", source_system="OTHER"))
    assert "PART-1" not in json.dumps(model.context(row("q", item_code="PART-1")))


def test_retrieval_request_preserves_conflicts_and_separate_cache(tmp_path):
    model = index()
    client = Client()
    options = ClassificationConfig(mode="openai")
    zero = OpenAIClassifier(TREE, options, company_id="synthetic", client=Client(), cache_dir=tmp_path)
    assisted = OpenAIClassifier(TREE, options, company_id="synthetic", client=client, cache_dir=tmp_path,
                                label_assisted=True, reference_fingerprint=model.fingerprint)
    with pytest.raises(ConfigError, match="separate"):
        zero.key_for(model.context(row("q")))
    assert zero.key_for(context_for(row("q"))) != assisted.key_for(model.context(row("q")))
    assisted.classify_many([model.context(row("q"))])
    request = client.calls[0]
    assert "labelled_examples" in json.loads(request["input"])["line"]
    assert "labels may be noisy" in request["instructions"]
    assert "record_id" not in request["input"] and "training_rows" not in request["input"]


def test_integrity_tamper_rejected(tmp_path):
    path = tmp_path / "index.json"
    value = payload()
    frozen = {"integrity": digest(value), "payload": value}
    frozen["payload"]["company_id"] = "tampered"
    path.write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(ConfigError, match="integrity"):
        RetrievalIndex.load(path, company_id="synthetic", taxonomy=TREE)


def test_pipeline_opt_in_and_zero_label_path(factory, tmp_path, monkeypatch):
    _, matched = factory(primary=[{"id": "train"}, {"id": "query", "item": "NEW"}], secondary=[], cross=False)
    resolved = resolve_entities(matched)
    config = resolved.matched.eligible.normalized.ingested.config
    tree = resolved.matched.eligible.normalized.ingested.taxonomy
    records = resolved.records
    splits = {rid: {"group": rid, "partition": "development"} for rid in records.record_id}
    value = build_payload(records, {"P:train": label(tree[0])}, tree, config.company_id, splits, {"P:query"})
    model = RetrievalIndex(value, company_id=config.company_id, taxonomy=tree)
    result = classify_company(resolved, retrieval=model)
    assert result.summary()["labels_used"] is True
    assert set(result.records.classification_method) == {"retrieval"}
    for column in ("include", "spend_value", "supplier_key", "item_key"):
        pd.testing.assert_series_equal(result.records[column], records[column])
    # The fixture label file does not exist. Both inference modes must avoid opening it.
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"integrity": digest(value), "payload": value}), encoding="utf-8")
    assert run_company(config, retrieval_index=path).summary()["labels_used"] is True
    def forbidden(*args, **kwargs):
        raise AssertionError("Zero-label inference tried to load an index")
    monkeypatch.setattr(RetrievalIndex, "load", forbidden)
    assert run_company(config).summary()["labels_used"] is False
