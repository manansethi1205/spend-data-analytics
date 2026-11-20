"""Offline OpenRouter endpoint, credential, budget and cache isolation contracts."""

from dataclasses import replace

import httpx
from openai import APIStatusError
import pytest

from cantill.config import ClassificationConfig, ConfigError
from cantill.llm import OpenAIClassifier
from test_llm import Client, PATHS, context


def options(**kwargs):
    return ClassificationConfig(mode="openai", provider="openrouter", model="openai/gpt-oss-120b:free", **kwargs)


def test_router_key_cannot_fall_back_to_openai_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        OpenAIClassifier(PATHS, options(), company_id="synthetic", cache_dir=tmp_path)


def test_credentials_are_sent_only_to_selected_fixed_host(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-router-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid")
    constructed = []
    def create(**kwargs):
        constructed.append(kwargs)
        return Client()
    monkeypatch.setattr("cantill.llm.OpenAI", create)
    OpenAIClassifier(PATHS, options(), company_id="synthetic", cache_dir=tmp_path)
    OpenAIClassifier(PATHS, ClassificationConfig(mode="openai"), company_id="synthetic", cache_dir=tmp_path)
    assert constructed[0]["base_url"] == "https://openrouter.ai/api/v1"
    assert constructed[0]["api_key"] == "synthetic-router-key"
    assert constructed[1]["base_url"] == "https://api.openai.com/v1"
    assert constructed[1]["api_key"] == "synthetic-openai-key"


def test_router_request_keeps_schema_and_disallows_paid_or_collecting_endpoints(tmp_path):
    client = Client()
    model = OpenAIClassifier(PATHS, options(retries=0), company_id="synthetic", client=client, cache_dir=tmp_path)
    results = model.classify_many([context()])
    assert results[0][1] == "openrouter"
    request = client.calls[0]
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    assert request["extra_body"]["provider"] == {
        "require_parameters": True, "data_collection": "deny",
        "max_price": {"prompt": 0, "completion": 0, "request": 0}}
    other = OpenAIClassifier(PATHS, replace(options(), provider="openai"), company_id="synthetic", client=Client(), cache_dir=tmp_path)
    assert model.key_for(context()) != other.key_for(context())
    assert other.read_cache(other.key_for(context())) is None


def test_requests_share_free_tier_pacing_including_multiple_contexts(monkeypatch, tmp_path):
    now, waits = [0.0], []
    monkeypatch.setattr("cantill.llm.time.monotonic", lambda: now[0])
    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
    monkeypatch.setattr("cantill.llm.time.sleep", sleep)
    client = Client()
    model = OpenAIClassifier(PATHS, options(workers=1, retries=0), company_id="synthetic", client=client, cache_dir=tmp_path)
    model.classify_many([context("bolt"), context("cleaning")])
    assert len(client.calls) == 2
    assert waits == [3.1]


@pytest.mark.parametrize("model", ["openai/gpt-oss-120b", "openrouter/auto", "openrouter/free", ""])
def test_router_requires_a_fixed_free_model(model):
    with pytest.raises(ConfigError, match=":free"):
        ClassificationConfig(provider="openrouter", model=model)


def test_invalid_provider_is_rejected():
    with pytest.raises(ConfigError, match="provider"):
        ClassificationConfig(provider="other")


@pytest.mark.parametrize("status", [402, 429])
def test_router_quota_error_stops_remaining_requests_without_retry(tmp_path, status):
    error = APIStatusError("synthetic", response=httpx.Response(status,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/responses")), body={})
    client = Client([error])
    model = OpenAIClassifier(PATHS, options(workers=1), company_id="synthetic", client=client, cache_dir=tmp_path)
    results = model.classify_many([context("one"), context("two")])
    assert len(client.calls) == 1 and model.stats[f"http_{status}"] == 1
    assert model.stats["retries"] == 0
    assert all(result is None for result, _, _ in results)
