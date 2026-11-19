"""Reserved evaluation sampling, fixed strategy and strict zero-label comparison."""

import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

from cantill.config import ConfigError
from cantill.llm import context_for


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    SPEC = importlib.util.spec_from_file_location("reserved_evaluation", TOOLS / "evaluate_holdout.py")
    evaluation = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(evaluation)
finally:
    sys.path.pop(0)


TREE = (("Goods", "Bolts"), ("Services", "Cleaning"))


def row(rid, **overrides):
    return {"record_id": rid, "include": 1, "source": "erp", "description": "Component " + rid, **overrides}


def sample(rid, assisted):
    context = context_for(row(rid))
    if assisted:
        context["labelled_examples"] = []
    result = {"record_id": rid, "group": "group-" + rid, "partition": "holdout", "context": context,
              "local_path": list(TREE[0]), "local_confidence": .2, "stratum": "short_text", "spend": "10"}
    if assisted:
        result.update(fallback_path=list(TREE[1]), fallback_confidence=.3)
    return result


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "REPO", tmp_path)
    monkeypatch.setattr(evaluation, "private_path", lambda path: Path(path))
    config = tmp_path / "configs"
    config.mkdir()
    (config / "openai_pricing.json").write_text(json.dumps({"test-model": {"input": ".75", "cached_input": ".075", "output": "4.5"}}), encoding="utf-8")
    payload = {"protocol": evaluation.PROTOCOL, "model": "test-model", "selection": {}, "arms": {}}
    for name, company, assisted in evaluation.ARMS:
        payload["arms"][name] = {"company_id": company, "assisted": assisted,
                                 "reference_fingerprint": "index" if assisted else "",
                                 "samples": [sample(company, assisted)], "taxonomy": TREE, "fingerprint": "fixed"}
    monkeypatch.setattr(evaluation, "read_freeze", lambda path: (payload, "integrity"))
    monkeypatch.setattr(evaluation, "load_config", lambda *args: object())
    monkeypatch.setattr(evaluation, "strategy_fingerprint", lambda *args: "fixed")
    def ingest(*args, **kwargs):
        labels = pd.DataFrame([{"record_id": company, "l1": "Goods", "l2": "Bolts"} for company in ("A", "B")])
        return type("Ingested", (), {"labels": labels})()
    monkeypatch.setattr(evaluation, "ingest_company", ingest)
    return tmp_path / "private/reserved", payload


def test_sampling_excludes_development_and_limits_related_groups():
    rows = [row("a"), row("b"), row("c"), row("dev"), row("excluded", include=0)]
    parts = {r["record_id"]: {"group": "shared" if r["record_id"] in ("a", "b") else r["record_id"],
                               "partition": "development" if r["record_id"] == "dev" else "holdout"} for r in rows}
    left, summary = evaluation.select_reserved(pd.DataFrame(rows), parts, "A", 100)
    right, _ = evaluation.select_reserved(pd.DataFrame(list(reversed(rows))), parts, "A", 100)
    assert left == right and len(left) == 2
    assert summary["candidate_rows"] == 3 and summary["selected_rows"] == 2
    assert all(r["record_id"] not in ("dev", "excluded") for r in left)


def test_source_label_availability_and_unique_context_selection():
    rows = [row("a", description="Same context"), row("b", description="Same context"),
            row("other", source="tool"), row("not_labelled")]
    parts = {r["record_id"]: {"group": r["record_id"], "partition": "holdout"} for r in rows}
    selected, summary = evaluation.select_reserved(pd.DataFrame(rows), parts, "A", 100,
                                                   source="erp", cohort_ids={"a", "b", "other"})
    assert len(selected) == 1 and summary["candidate_rows"] == 2


@pytest.mark.parametrize("size", [0, 501, True])
def test_invalid_sample_sizes_fail(size):
    with pytest.raises(ConfigError):
        evaluation.select_reserved(pd.DataFrame([row("a")]), {}, "A", size)


@pytest.mark.parametrize("change", ["zero_examples", "zero_fallback", "development", "different_A", "empty"])
def test_loader_enforces_zero_label_and_identical_A_population(prepared, change):
    root, payload = prepared
    zero = payload["arms"]["A_zero"]["samples"][0]
    if change == "zero_examples":
        zero["context"]["labelled_examples"] = []
    elif change == "zero_fallback":
        zero["fallback_path"] = list(TREE[1])
    elif change == "development":
        zero["partition"] = "development"
    elif change == "different_A":
        payload["arms"]["A_assisted"]["samples"][0]["record_id"] = "other"
    else:
        payload["arms"]["A_zero"]["samples"] = []
    with pytest.raises(ConfigError):
        evaluation.load_current("kit", root)


def test_classifier_or_index_drift_rejected(prepared, monkeypatch):
    root, _ = prepared
    monkeypatch.setattr(evaluation, "strategy_fingerprint", lambda *args: "changed")
    with pytest.raises(ConfigError, match="changed"):
        evaluation.load_current("kit", root)


def test_preview_never_calls_api(prepared, monkeypatch):
    root, _ = prepared
    monkeypatch.setattr(evaluation, "run_model", lambda *a, **kw: pytest.fail("Preview called API"))
    result = evaluation.run("kit", root, execute=False, max_requests=0, max_tokens=0, workers=1)
    assert result["status"] == "dry_run"
    assert "retrieval_metrics" not in result["arms"]["A_zero"]


@pytest.mark.parametrize("requests,tokens", [(5, 6000000), (6, 1)])
def test_budget_check_precedes_all_api_calls(prepared, monkeypatch, requests, tokens):
    root, _ = prepared
    monkeypatch.setattr(evaluation, "run_model", lambda *a, **kw: pytest.fail("Budget failed after API"))
    with pytest.raises(ConfigError, match="allowances"):
        evaluation.run("kit", root, execute=True, max_requests=requests, max_tokens=tokens, workers=1)


def test_every_inference_arm_finishes_before_scoring_labels(prepared, monkeypatch):
    root, _ = prepared
    calls = []
    def infer(samples, *args, **kwargs):
        calls.append(kwargs["label_assisted"])
        assert all(("labelled_examples" in s["context"]) == kwargs["label_assisted"] for s in samples)
        predictions = [(TREE[0], .8)]
        return {"status": "measured"}, {"all": predictions, "api_samples": samples,
                                        "api_predictions": predictions, "methods": ["openai"], "flags": [""]}
    monkeypatch.setattr(evaluation, "run_model", infer)
    ingest = evaluation.ingest_company
    def score(*args, **kwargs):
        assert calls == [False, True, True]
        return ingest(*args, **kwargs)
    monkeypatch.setattr(evaluation, "ingest_company", score)
    report = evaluation.run("kit", root, execute=True, max_requests=6, max_tokens=6000000, workers=1)
    assert report["status"] == "measured" and report["A_assisted_vs_zero"]["both_correct"] == 1


def test_failed_arm_stops_remaining_inference(prepared, monkeypatch):
    root, _ = prepared
    calls = []
    def blocked(*args, **kwargs):
        calls.append(1)
        return {"status": "blocked_preflight", "company_requests": 0}, None
    monkeypatch.setattr(evaluation, "run_model", blocked)
    report = evaluation.run("kit", root, execute=True, max_requests=6, max_tokens=6000000, workers=1)
    assert len(calls) == 1 and report["status"] == "incomplete"
    assert report["arms"]["B_assisted"]["status"] == "not_executed"
