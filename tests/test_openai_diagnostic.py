"""Only allow non-sensitive API error metadata into diagnostic output."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location("diagnostic", Path(__file__).parents[1] / "tools/diagnose_openai.py")
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_diagnostic_preserves_quota_code_without_message_or_headers():
    exc = SimpleNamespace(status_code=429, body={"code": "insufficient_quota", "type": "insufficient_quota",
                                               "message": "private payload"},
                          response=SimpleNamespace(headers={"retry-after": "30", "authorization": "private key"}))
    result = diagnostic.safe_error(exc)
    assert result == {"success": False, "http_status": 429, "error_code": "insufficient_quota",
                      "error_type": "insufficient_quota", "retry_after_seconds": "30"}


def test_diagnostic_rejects_payloads_in_code_fields():
    exc = SimpleNamespace(body={"error": {"code": "Bearer SECRET", "type": ["private"]}})
    assert diagnostic.safe_error(exc) == {"success": False, "http_status": None,
                                          "error_code": "unavailable", "error_type": "unavailable"}
