"""Full-company paid runs require financial readiness and explicit complete budgets."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from cantill.config import ConfigError
from cantill.llm import context_for


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    SPEC = importlib.util.spec_from_file_location("rehearsal", TOOLS / "rehearse.py")
    rehearsal = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(rehearsal)
finally:
    sys.path.pop(0)


TREE = (("Goods", "Bolts"), ("Services", "Cleaning"))


@pytest.mark.parametrize("changed,allowed", [("src\\cantill\\normalize.py", True),
                                            ("src\\cantill\\llm.py", False),
                                            ("src\\cantill\\retrieval.py", False)])
def test_financial_version_guard_rejects_classifier_changes(monkeypatch, changed, allowed):
    import copy
    previous = {"pipeline": {"config": "same", "inputs": {"source": "same"},
                             "code": {changed: "old"}},
                "index": "same", "evaluation_tool": "same", "reference_tool": "same"}
    current = copy.deepcopy(previous)
    current["pipeline"]["code"][changed] = "new"
    payload = {"protocol": rehearsal.EVALUATION_PROTOCOL, "arms": {"B_assisted": {"fingerprint": previous}}}
    monkeypatch.setattr(rehearsal, "read_freeze", lambda path: (payload, "integrity"))
    monkeypatch.setattr(rehearsal, "config_for", lambda *args: (None, None, None))
    monkeypatch.setattr(rehearsal, "strategy_fingerprint", lambda *args: current)
    if allowed:
        _, trace = rehearsal.financial_update_provenance("kit")
        assert trace["changes"]["B_assisted"]["changed_code"] == [changed]
    else:
        with pytest.raises(ConfigError, match="outside config/normalization"):
            rehearsal.financial_update_provenance("kit")


def resolved():
    ingested = NS(taxonomy=TREE, config=NS(company_id="A"))
    return NS(matched=NS(eligible=NS(normalized=NS(ingested=ingested))))


def test_requirements_deduplicate_complete_reference_contexts_without_requests():
    local = NS(resolved=resolved())
    index = NS(fingerprint="index", context=lambda row: {**context_for({"description": "Steel bolt"}), "labelled_examples": []})
    contexts, needed = rehearsal.requirements(local, index, [{}, {}], "test-model")
    assert len(contexts) == 2 and needed["unique_contexts"] == 1
    assert needed["required_requests_including_gate"] == 2
    assert needed["required_token_allowance_including_gate"] > 0


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(rehearsal, "REPO", tmp_path)
    monkeypatch.setattr(rehearsal, "private_path", lambda path: Path(path))
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "openai_pricing.json").write_text('{"test-model":{"input":".75","cached_input":".075","output":"4.5"}}', encoding="utf-8")
    entry = {"financial_export_ready": True, "required_requests_including_gate": 2,
             "required_token_allowance_including_gate": 15000, "unique_contexts": 1, "included_rows": 2}
    plan = {"model": "test-model", "companies": {"A": entry}}
    root = tmp_path / "private/rehearsal"
    monkeypatch.setattr(rehearsal, "load_plan", lambda *args: (plan, "integrity", object(), Path("config"), Path("index")))
    return root, plan


def test_preview_never_creates_a_client(prepared, monkeypatch):
    root, _ = prepared
    monkeypatch.setattr(rehearsal, "gate_backend", lambda *a, **kw: pytest.fail("Preview created API client"))
    report = rehearsal.run("kit", root, "A", execute=False, max_requests=0, max_tokens=0, workers=1)
    assert report["status"] == "preview" and report["api_requests"] == 0


def test_financial_block_precedes_any_api_request(prepared, monkeypatch):
    root, plan = prepared
    plan["companies"]["A"]["financial_export_ready"] = False
    monkeypatch.setattr(rehearsal, "gate_backend", lambda *a, **kw: pytest.fail("Blocked data sent to API"))
    with pytest.raises(ConfigError, match="unresolved financial"):
        rehearsal.run("kit", root, "A", execute=True, max_requests=2, max_tokens=20000, workers=1)


@pytest.mark.parametrize("requests,tokens", [(0, 0), (1, 20000), (2, 100)])
def test_incomplete_explicit_budget_rejected_before_gate(prepared, monkeypatch, requests, tokens):
    root, _ = prepared
    monkeypatch.setattr(rehearsal, "gate_backend", lambda *a, **kw: pytest.fail("Budget checked after API"))
    with pytest.raises(ConfigError, match="allowances"):
        rehearsal.run("kit", root, "A", execute=True, max_requests=requests, max_tokens=tokens, workers=1)


def test_failed_authentication_sends_no_company_context(prepared, monkeypatch):
    root, _ = prepared
    gate = NS(stats={"requests": 1, "api_errors": 1, "http_401": 1}, reservation=lambda context: 500,
              classify_many=lambda contexts: [(None, "local", "OPENAI_API_ERROR")])
    monkeypatch.setattr(rehearsal, "gate_backend", lambda *args, **kwargs: gate)
    monkeypatch.setattr(rehearsal, "components", lambda *args: pytest.fail("Company processing followed failed gate"))
    report = rehearsal.run("kit", root, "A", execute=True, max_requests=2, max_tokens=20000, workers=1)
    assert report["status"] == "blocked_preflight" and report["preflight"]["cost"]["usd"] is None


@pytest.mark.parametrize("case,expected", [("success", "measured"), ("fallback", "partial_api_or_cache"),
                                          ("cache_mismatch", "partial_api_or_cache")])
def test_full_run_coverage_cache_and_validated_export(prepared, monkeypatch, case, expected):
    root, plan = prepared
    decision = {"category_id": "C0000", "confidence": .85, "needs_review": False}
    gate = NS(stats={"requests": 1, "input_tokens": 10, "output_tokens": 2}, reservation=lambda context: 500,
              classify_many=lambda contexts: [(decision, "openai", "")])
    monkeypatch.setattr(rehearsal, "gate_backend", lambda *args, **kwargs: gate)
    local = NS(resolved=resolved())
    index = NS(fingerprint="index")
    monkeypatch.setattr(rehearsal, "components", lambda *args: (local, index, [{}, {}]))
    needed = {key: plan["companies"]["A"][key] for key in ("unique_contexts", "included_rows",
                                                         "required_requests_including_gate", "required_token_allowance_including_gate")}
    monkeypatch.setattr(rehearsal, "requirements", lambda *args: ([{}, {}], needed))
    records = pd.DataFrame([{"record_id": rid, "include": 1, "l1": "Goods", "l2": "Bolts", "l3": "", "l4": "",
                             "confidence": .85, "classification_flags": (),
                             "classification_method": "retrieval" if case == "fallback" else "openai_retrieval"}
                            for rid in ("a", "b")])
    result = NS(records=records, resolved=resolved(), diagnostics={"requests": 1, "input_tokens": 200, "output_tokens": 50},
                summary=lambda: {"classification_methods": {"openai_retrieval": 2}})
    monkeypatch.setattr(rehearsal, "classify_company", lambda *args, **kwargs: result)
    warmed = {**decision, "confidence": .1 if case == "cache_mismatch" else .85}
    warm = NS(stats={"cache_hits": 1}, paths={"C0000": TREE[0]},
              classify_many=lambda contexts: [(warmed, "cache", "")] * 2)
    monkeypatch.setattr(rehearsal, "OpenAIClassifier", lambda *args, **kwargs: warm)
    monkeypatch.setattr(rehearsal, "write_output", lambda result, path: path.write_text("synthetic output", encoding="utf-8"))
    monkeypatch.setattr(rehearsal, "independently_validate", lambda result, path: {"valid": path.exists()})
    report = rehearsal.run("kit", root, "A", execute=True, max_requests=2, max_tokens=20000, workers=1)
    assert report["status"] == expected
    assert report["output_validation"]["valid"] and report["inputs_code_index_unchanged"]
    assert report["warm"]["usage"].get("requests", 0) == 0
    assert report["cost"]["usd_per_1000_input_records"] is not None
    assert report["cold_runtime_verified"] == (case == "success")
    assert report["execution"]["workers"] == 1 and report["execution"]["retries"] == 0


def test_plan_fingerprint_drift_rejected_before_execution(tmp_path, monkeypatch):
    root = tmp_path / "private/rehearsal"
    plan = {"protocol": rehearsal.PROTOCOL, "companies": {"A": {"fingerprint": "original"}}}
    monkeypatch.setattr(rehearsal, "read_freeze", lambda path: (plan, "integrity"))
    monkeypatch.setattr(rehearsal, "config_for", lambda *args: (object(), Path("config"), Path("index")))
    monkeypatch.setattr(rehearsal, "current_fingerprint", lambda *args: "changed")
    with pytest.raises(ConfigError, match="changed"):
        rehearsal.load_plan("kit", root, "A")
