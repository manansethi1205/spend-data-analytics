"""Evaluation preview, preflight and confidence diagnostics never need a live API."""

import importlib.util
from pathlib import Path
import sys

import pytest

from cantill.config import ClassificationConfig, ConfigError
from test_zero_label import TREE


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("zero_evaluation", TOOLS / "evaluate_zero_label.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
sys.path.pop(0)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    payload = {"protocol": evaluation.PROTOCOL, "model": ClassificationConfig().model,
               "fingerprint": {"same": True}, "taxonomy": TREE,
               "samples": [{"record_id": "1", "context": {"description": "Sensors"},
                            "supplier_name": "Synthetic Supplier", "local_path": TREE[0],
                            "local_confidence": .1, "spend": "100", "stratum": "short"}]}
    monkeypatch.setattr(evaluation, "read_freeze", lambda path: (payload, "integrity"))
    monkeypatch.setattr(evaluation, "load_config", lambda *args: object())
    monkeypatch.setattr(evaluation, "current", lambda *args: payload["fingerprint"])
    return tmp_path, payload


def test_evaluation_preview_and_small_budget_never_infer(frozen, monkeypatch):
    root, _ = frozen
    monkeypatch.setattr(evaluation, "run_model", lambda *a, **kw: pytest.fail("Unintended API execution"))
    report = evaluation.run("kit", root, "hierarchical", False, 0, 0, 1)
    assert report["api_requests"] == 0 and report["required"]["requests"] == 5
    with pytest.raises(ConfigError, match="every hierarchy level"):
        evaluation.run("kit", root, "hierarchical", True, 2, 1_000_000, 1)


def test_failed_gate_persists_report_without_gold_reads(frozen, monkeypatch):
    root, _ = frozen
    monkeypatch.setattr(evaluation, "run_model", lambda *a, **kw: ({"status": "blocked_preflight"}, None))
    monkeypatch.setattr(evaluation, "ingest_company", lambda *a, **kw: pytest.fail("Gold opened after failed gate"))
    result = evaluation.run("kit", root, "hierarchical", True, 10, 1_000_000, 1)
    assert result["status"] == "blocked_preflight" and list((root / "runs").glob("*/report.json"))


def test_confidence_metrics_have_correct_perfect_and_wrong_limits():
    samples = [{"record_id": "1"}, {"record_id": "2"}]
    labels = {"1": {"l1": "A"}, "2": {"l1": "B"}}
    perfect = evaluation.reliability(samples, [(("A",), 1), (("A",), 0)], labels)
    wrong = evaluation.reliability(samples, [(("A",), 0), (("A",), 1)], labels)
    assert perfect["brier"] == perfect["ece_10_bins"] == 0
    assert wrong["brier"] == wrong["ece_10_bins"] == 1
    assert not perfect["calibration_fitted"]
