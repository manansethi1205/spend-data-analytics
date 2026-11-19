"""Label-free splitting, pilot gates, warm caches and cost accounting."""

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import httpx
from openai import APIStatusError
import pytest

from test_matching import factory
from test_llm import Client, response
from cantill.classify import classify_company
from cantill.config import ConfigError
from cantill.entities import resolve_entities
from cantill.llm import OpenAIClassifier, context_for
from cantill.pilot import cost_estimate, partition_records, score_predictions, select_samples


SPEC = importlib.util.spec_from_file_location("pilot_tool", Path(__file__).resolve().parents[1] / "tools/pilot_classification.py")
pilot_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot_tool)
RATES = {"input": ".75", "cached_input": ".075", "output": "4.5", "source": "synthetic"}


def local_records(factory):
    _, matched = factory(primary=[{"id": str(index), "item": f"MAT{index}", "description": f"Steel bolt component {index} mm"}
                                 for index in range(60)], secondary=[], cross=False)
    return classify_company(resolve_entities(matched))


def test_partition_is_order_independent_and_groups_related_items(factory):
    local = local_records(factory)
    rows = local.records.to_dict("records")
    assert partition_records(rows) == partition_records(rows[::-1])
    rows[1]["item_code"] = rows[0]["item_code"]
    rows[2]["duplicate_of"] = (rows[1]["record_id"],)
    parts = partition_records(rows)
    assert parts[rows[0]["record_id"]] == parts[rows[1]["record_id"]] == parts[rows[2]["record_id"]]


def test_same_classifier_context_never_crosses_partition(factory):
    rows = local_records(factory).records.to_dict("records")
    rows[1].update({field: rows[0][field] for field in context_for(rows[0])})
    parts = partition_records(rows)
    assert parts[rows[0]["record_id"]] == parts[rows[1]["record_id"]]


def test_scoped_invoices_stay_together_but_ids_across_erps_do_not(factory):
    rows = local_records(factory).records.to_dict("records")
    rows[0]["invoice_number"] = "INV-01"
    rows[1]["invoice_number"] = "INV01"
    rows[2]["invoice_number"] = "INV01"
    rows[2]["source_system"] = "OTHER"
    parts = partition_records(rows)
    assert parts[rows[0]["record_id"]]["group"] == parts[rows[1]["record_id"]]["group"]
    assert parts[rows[0]["record_id"]]["group"] != parts[rows[2]["record_id"]]["group"]


def test_sampling_is_fixed_unique_context_and_development_only(factory):
    local = local_records(factory)
    tree = local.resolved.matched.eligible.normalized.ingested.taxonomy
    selected, parts, summary = select_samples(local.records, tree, sample_size=10)
    reverse, _, _ = select_samples(local.records.iloc[::-1], tree, sample_size=10)
    assert selected == reverse and len(selected) == 10
    assert all(sample["partition"] == "development" for sample in selected)
    assert len({json.dumps(sample["context"], sort_keys=True) for sample in selected}) == 10
    assert sum(summary["partition_rows"].values()) == len(local.records)
    assert all("supplier_key" not in sample["context"] and "record_id" not in sample["context"] for sample in selected)


def test_source_cohort_filters_and_exclusion_filter(factory):
    local = local_records(factory)
    tree = local.resolved.matched.eligible.normalized.ingested.taxonomy
    initial, _, _ = select_samples(local.records, tree, sample_size=10)
    allowed = {entry["record_id"] for entry in initial[:3]}
    result, _, _ = select_samples(local.records, tree, sample_size=10, source="primary", cohort_ids=allowed)
    assert {entry["record_id"] for entry in result} == allowed
    records = local.records.copy()
    records.loc[records.record_id.isin(allowed), "include"] = 0
    assert not select_samples(records, tree, sample_size=10, cohort_ids=allowed)[0]
    with pytest.raises(ConfigError):
        select_samples(records, tree, sample_size=10, source="invented")


@pytest.mark.parametrize("size", [0, -1, 501, True])
def test_invalid_sample_size(size, factory):
    local = local_records(factory)
    with pytest.raises(ConfigError):
        select_samples(local.records, (("Synthetic terminal",),), sample_size=size)


def test_grouping_does_not_read_or_depend_on_gold_fields(factory):
    rows = local_records(factory).records.to_dict("records")
    parts = partition_records(rows)
    poisoned = deepcopy(rows)
    for row in poisoned:
        row["l1"] = row["golden_item_key"] = "POISON"
    assert partition_records(poisoned) == parts


def test_scoring_handles_missing_labels_and_missing_spend():
    samples = [{"record_id": "a", "stratum": "blank", "spend": None},
               {"record_id": "b", "stratum": "short", "spend": "-3"},
               {"record_id": "c", "stratum": "short", "spend": "1"}]
    scores = score_predictions(samples, [(('A',), .9)] * 3,
                               {"a": {"l1": "A"}, "b": {"include": "0", "l1": "B"}})
    assert scores["all"]["evaluated_rows"] == 1 and scores["unscored_rows"] == 2
    assert scores["all"]["rows_with_missing_spend"] == 1


def test_cost_uses_cached_input_rate_and_sample_denominator():
    result = cost_estimate({"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100}, RATES, 40)
    assert result["usd"] == "0.001065"
    assert result["usd_per_1000_sample_lines"] == "0.026625"
    assert cost_estimate({}, None, 40)["usd"] is None
    assert cost_estimate({"api_errors": 1}, RATES, 40)["usd"] is None
    assert cost_estimate({"responses_without_usage": 1}, RATES, 40)["status"] == "unknown_usage"


@pytest.mark.parametrize("rates", [{"input": "NaN", "cached_input": 0, "output": 1},
                                   {"input": -1, "cached_input": 0, "output": 1}, {}])
def test_invalid_price_data_fails_before_use(rates):
    with pytest.raises(ConfigError):
        cost_estimate({}, rates, 1)


def test_cold_then_warm_does_not_send_second_company_request(tmp_path):
    calls = []
    def build(paths, options, **kwargs):
        client = Client()
        calls.append(client)
        return OpenAIClassifier(paths, options, client=client, **kwargs)
    samples = [{"record_id": "a", "context": context_for({"description": "Steel bolt"}),
                "local_path": ["Goods", "Bolts"], "local_confidence": .2}]
    report, predictions = pilot_tool.run_model(samples, (("Goods", "Bolts"),), "synthetic", "test-model", RATES,
                                                tmp_path, max_requests=2, max_tokens=100000, workers=1,
                                                backend_factory=build)
    assert report["status"] == "measured" and report["company_requests"] == 1
    assert len(calls[0].calls) == 1 and len(calls[1].calls) == 1 and not calls[2].calls
    assert report["warm"]["cache_rows"] == 1 and report["warm"]["successful_cold_decisions_reproduced"]
    assert predictions["all"][0][0] == ("Goods", "Bolts")


def test_failed_synthetic_gate_prevents_all_company_requests(tmp_path):
    clients = []
    error = APIStatusError("synthetic secret", response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com")), body={})
    def build(paths, options, **kwargs):
        client = Client([error])
        clients.append(client)
        return OpenAIClassifier(paths, options, client=client, **kwargs)
    report, predictions = pilot_tool.run_model([{"context": context_for({"description": "CONFIDENTIAL COMPANY DATA"})}],
                                               (("Goods",),), "synthetic", "test-model", RATES, tmp_path,
                                               max_requests=2, max_tokens=100000, workers=1, backend_factory=build)
    assert report["status"] == "blocked_preflight" and report["company_requests"] == 0 and predictions is None
    assert len(clients) == 1 and len(clients[0].calls) == 1
    assert "CONFIDENTIAL COMPANY DATA" not in json.dumps(clients[0].calls)


def test_underfunded_model_comparison_sends_no_partial_company_sample(tmp_path):
    clients = []
    def build(paths, options, **kwargs):
        client = Client()
        clients.append(client)
        return OpenAIClassifier(paths, options, client=client, **kwargs)
    samples = [{"context": context_for({"description": f"Steel bolt {i}"}),
                "local_path": ["Goods", "Bolts"], "local_confidence": .2} for i in range(2)]
    report, predictions = pilot_tool.run_model(samples, (("Goods", "Bolts"),), "synthetic", "test-model", RATES,
                                                tmp_path, max_requests=2, max_tokens=100000, workers=1,
                                                backend_factory=build)
    assert report["status"] == "blocked_budget" and report["company_requests"] == 0
    assert len(clients[0].calls) == 1 and not clients[1].calls and predictions is None


def test_preview_never_constructs_an_api_backend(factory, tmp_path, monkeypatch):
    _, matched = factory(primary=[{"id": str(i), "item": f"M{i}", "description": f"Component {i} steel bolt"} for i in range(50)],
                         secondary=[], cross=False)
    from dataclasses import replace
    config = replace(matched.eligible.normalized.ingested.config, labels=None)
    config_path, directory = tmp_path / "company.yaml", tmp_path / "pilot"
    pilot_tool.prepare(config, config_path, directory, sample_size=5, source=None, cohort="all")
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview tried to create an API backend")
    monkeypatch.setattr(pilot_tool, "OpenAIClassifier", forbidden)
    report = pilot_tool.run(config, config_path, directory, execute=False, models=["test-model"],
                            prices={}, max_requests=0, max_tokens=0, workers=1)
    assert report["status"] == "dry_run" and report["models"] == {}
    assert report["local"]["all"]["evaluated_rows"] == 0


def test_freeze_rejects_mutation_and_never_overwrites(factory, tmp_path):
    _, matched = factory(primary=[{"id": str(i), "item": f"MAT{i}", "description": f"Component {i} mm steel bolt"} for i in range(50)],
                         secondary=[], cross=False)
    config = matched.eligible.normalized.ingested.config
    # The synthetic fixture deliberately configures a nonexistent, unused label path.
    from dataclasses import replace
    config = replace(config, labels=None)
    config_path = tmp_path / "company.yaml"
    directory = tmp_path / "private/pilot"
    pilot_tool.prepare(config, config_path, directory, sample_size=5, source=None, cohort="all")
    payload, _ = pilot_tool.load_frozen(config, config_path, directory)
    assert len(payload["samples"]) == 5
    with pytest.raises(ConfigError, match="already frozen"):
        pilot_tool.prepare(config, config_path, directory, sample_size=5, source=None, cohort="all")
    path = directory / "freeze.json"
    value = json.loads(path.read_text())
    value["payload"]["samples"][0]["partition"] = "holdout"
    path.write_text(json.dumps(value))
    with pytest.raises(ConfigError, match="integrity"):
        pilot_tool.load_frozen(config, config_path, directory)
