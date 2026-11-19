"""Fixed retrieval pilot: grouping boundaries, budget gates and inference-before-score."""

import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

from cantill.config import ConfigError
from cantill.llm import OpenAIClassifier, context_for
from test_llm import Client


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    SPEC = importlib.util.spec_from_file_location("retrieval_pilot", TOOLS / "pilot_retrieval.py")
    pilot = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(pilot)
finally:
    sys.path.pop(0)


TREE = (("Goods", "Bolts"), ("Services", "Cleaning"))
RATES = {"input": ".75", "cached_input": ".075", "output": "4.5"}


def sample(rid):
    return {"record_id": rid, "context": {**context_for({"description": "Steel bolt"}), "labelled_examples": []},
            "local_path": list(TREE[0]), "local_confidence": .2, "fallback_path": list(TREE[1]),
            "fallback_confidence": .3, "stratum": "short_text", "spend": "10"}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "REPO", tmp_path)
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "openai_pricing.json").write_text(json.dumps({"test-model": RATES}), encoding="utf-8")
    root = tmp_path / "private/pilot"
    payload = {"model": "test-model", "cohorts": {}}
    for name, company in pilot.COHORTS:
        rid = name + "-id"
        payload["cohorts"][name] = {"company_id": company, "taxonomy": TREE,
                                   "reference_fingerprint": "private-index", "samples": [sample(rid)],
                                   "original_predictions": [{"record_id": rid, "path": list(TREE[0]), "confidence": .8}]}
    monkeypatch.setattr(pilot, "load_current", lambda *args: (payload, "frozen-integrity"))
    monkeypatch.setattr(pilot, "load_config", lambda *args: object())
    def ingest(*args, **kwargs):
        labels = pd.DataFrame([{"record_id": name + "-id", "l1": "Goods", "l2": "Bolts"} for name, _ in pilot.COHORTS])
        return type("Ingested", (), {"labels": labels})()
    monkeypatch.setattr(pilot, "ingest_company", ingest)
    return root, payload


@pytest.mark.parametrize("bad", [
    {"record_id": "pilot", "group": "eval"},
    {"record_id": "relative", "group": "eval"},
    {"record_id": "hold", "group": "reserved"},
    {"record_id": "unknown", "group": "safe"},
    {"record_id": "train", "group": "invented"},
])
def test_training_provenance_checked_against_actual_reference_groups(bad):
    parts = {rid: {"group": group, "partition": partition} for rid, group, partition in (
        ("train", "safe", "development"), ("pilot", "eval", "development"),
        ("relative", "eval", "development"), ("hold", "reserved", "holdout"))}
    with pytest.raises(ConfigError, match="overlaps"):
        pilot.check_training({"training_rows": [bad]}, {"partitions": parts}, {"pilot"})
    pilot.check_training({"training_rows": [{"record_id": "train", "group": "safe"}]},
                         {"partitions": parts}, {"pilot"})


def test_dry_run_never_calls_api_and_reports_three_baselines(prepared, monkeypatch):
    root, _ = prepared
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run attempted API inference")
    monkeypatch.setattr(pilot, "run_model", forbidden)
    result = pilot.run("kit", root, execute=False, max_requests=0, max_tokens=0, workers=1)
    assert result["status"] == "dry_run"
    assert all("original_zero_label_metrics" in c and "retrieval_metrics" in c for c in result["cohorts"].values())


@pytest.mark.parametrize("requests,tokens", [(5, 3000000), (6, 1)])
def test_underfunded_comparison_fails_before_any_api_request(prepared, monkeypatch, requests, tokens):
    root, _ = prepared
    monkeypatch.setattr(pilot, "run_model", lambda *a, **kw: pytest.fail("Budget check happened after inference"))
    with pytest.raises(ConfigError, match="allowance"):
        pilot.run("kit", root, execute=True, max_requests=requests, max_tokens=tokens, workers=1)


def test_all_inference_finishes_before_labels_open(prepared, monkeypatch):
    root, _ = prepared
    calls = []
    def infer(samples, *args, **kwargs):
        assert kwargs["label_assisted"] and kwargs["reference_fingerprint"] == "private-index"
        calls.append("inference")
        decisions = [(TREE[0], .8)]
        return {"status": "measured"}, {"all": decisions, "api_samples": samples,
                                        "api_predictions": decisions, "methods": ["openai"], "flags": [""]}
    monkeypatch.setattr(pilot, "run_model", infer)
    ingest = pilot.ingest_company
    def score_labels(*args, **kwargs):
        assert calls == ["inference"] * 3
        return ingest(*args, **kwargs)
    monkeypatch.setattr(pilot, "ingest_company", score_labels)
    result = pilot.run("kit", root, execute=True, max_requests=6, max_tokens=3000000, workers=1)
    assert result["status"] == "measured" and result["inputs_code_index_unchanged"]
    assert all(c["paired_vs_original"]["both_correct"] == 1 for c in result["cohorts"].values())


def test_failed_gate_stops_later_cohorts(prepared, monkeypatch):
    root, _ = prepared
    calls = []
    def blocked(*args, **kwargs):
        calls.append(1)
        return {"status": "blocked_preflight", "company_requests": 0}, None
    monkeypatch.setattr(pilot, "run_model", blocked)
    report = pilot.run("kit", root, execute=True, max_requests=6, max_tokens=3000000, workers=1)
    assert report["status"] == "incomplete" and len(calls) == 1
    assert report["cohorts"]["B"]["status"] == "not_executed"


def test_shared_runner_uses_labelled_cold_and_warm_namespace(tmp_path):
    clients = []
    def backend(paths, options, **kwargs):
        client = Client()
        clients.append(client)
        return OpenAIClassifier(paths, options, client=client, **kwargs)
    report, predictions = pilot.run_model([sample("q")], TREE, "synthetic", "test-model", RATES, tmp_path,
                                           max_requests=2, max_tokens=100000, workers=1,
                                           backend_factory=backend, label_assisted=True, reference_fingerprint="index")
    assert report["status"] == "measured"
    assert report["warm"]["cache_rows"] == 1 and not clients[2].calls
    assert "labelled_examples" in clients[1].calls[0]["input"]
    assert "labelled_examples" not in clients[0].calls[0]["input"]


def test_shared_runner_uses_retrieval_fallback_when_api_is_invalid(tmp_path):
    from test_llm import response
    def backend(paths, options, **kwargs):
        # The synthetic gate remains valid; company classification is deliberately invalid.
        client = Client() if kwargs["company_id"] == "synthetic-pilot-preflight" else Client([response({})])
        return OpenAIClassifier(paths, options, client=client, **kwargs)
    report, predictions = pilot.run_model([sample("q")], TREE, "synthetic", "test-model", RATES, tmp_path,
                                           max_requests=2, max_tokens=100000, workers=1,
                                           backend_factory=backend, label_assisted=True, reference_fingerprint="index")
    assert report["status"] == "partial"
    assert predictions["all"] == [(TREE[1], .3)]


def test_paired_changes_count_regressions_and_unscored_rows():
    samples = [sample(str(i)) for i in range(5)]
    original = [(TREE[0], .5), (TREE[0], .5), (TREE[1], .5), (TREE[1], .5), (TREE[0], .5)]
    assisted = [(TREE[0], .5), (TREE[1], .5), (TREE[0], .5), (TREE[1], .5), (TREE[0], .5)]
    labels = {str(i): {"l1": "Goods", "l2": "Bolts"} for i in range(4)}
    assert pilot.paired_changes(samples, original, assisted, labels) == {
        "both_correct": 1, "regressed": 1, "corrected": 1, "both_wrong": 1, "unscored": 1}


def test_baseline_context_change_rejected_before_loading_predictions(monkeypatch):
    old = {**sample("q"), "group": "g", "partition": "development"}
    current = {**old, "context": {**old["context"], "description": "Different purchase"}}
    monkeypatch.setattr(pilot, "read_freeze", lambda path: ({"samples": [old]}, "integrity"))
    with pytest.raises(ConfigError, match="population/context"):
        pilot.original_predictions("A", [current], TREE, "test-model")


def test_cold_success_without_warm_cache_is_not_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(OpenAIClassifier, "write_cache", lambda *args: None)
    def backend(paths, options, **kwargs):
        return OpenAIClassifier(paths, options, client=Client(), **kwargs)
    report, _ = pilot.run_model([sample("q")], TREE, "synthetic", "test-model", RATES, tmp_path,
                                max_requests=2, max_tokens=100000, workers=1,
                                backend_factory=backend, label_assisted=True, reference_fingerprint="index")
    assert report["api_coverage_rows"] == 1
    assert report["warm"]["cache_rows"] == 0
    assert report["status"] == "cache_verification_failed"
