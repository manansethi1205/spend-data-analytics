"""One synthetic request to identify API error codes without company data or secrets."""

import argparse
import json
import os
import re

from openai import APIConnectionError, APIStatusError, OpenAI

from cantill.config import ClassificationConfig


def safe_error(exc):
    body = getattr(exc, "body", None)
    body = body if isinstance(body, dict) else {}
    error = body.get("error", body)
    error = error if isinstance(error, dict) else {}
    result = {"success": False, "http_status": getattr(exc, "status_code", None)}
    for name in ("code", "type"):
        value = error.get(name)
        result["error_" + name] = value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value) else "unavailable"
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {})
    retry_after = headers.get("retry-after", "")
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", retry_after):
        result["retry_after_seconds"] = retry_after
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow one small paid synthetic request; no retries")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "preview", "requests": 0, "message": "Add --execute for one synthetic request"}))
        return 0
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print(json.dumps({"success": False, "error_code": "key_unavailable", "requests": 0}))
        return 1
    try:
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", max_retries=0, timeout=30) as client:
            response = client.responses.create(model=ClassificationConfig().model, input="Reply with OK.",
                                               max_output_tokens=32, store=False)
        result = {"success": True, "response_status": response.status,
                  "note": "One small request succeeded; sustained throughput limits are not verified."}
    except (APIConnectionError, APIStatusError) as exc:
        result = safe_error(exc)
    print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
