"""The published new-company example runs through the real CLI without private assets."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_published_four_level_company_runs_without_labels_keys_or_cache(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("OPENAI_")}
    output = tmp_path / "example.csv"
    command = [sys.executable, "-m", "cantill", "run", "--config", str(ROOT / "configs/company_C.example.yaml"),
               "--data-dir", str(ROOT), "--classifier", "local", "--llm-max-requests", "0",
               "--llm-max-tokens", "0", "--output", str(output)]
    run = subprocess.run(command, cwd=tmp_path, env=env, text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    summary = json.loads(run.stdout)
    assert summary["labels_used"] is False and summary["openai_usage"] is None
    assert summary["record_count"] == 6 and summary["included_rows"] == 3
    assert summary["exclusion_reasons"] == {"CANCELLED": 1, "NOT_APPROVED": 1, "DUPLICATE": 1}
    with output.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["l4"] for row in rows if row["include"] == "1"} == {
        "Sterile nitrile gloves", "Laboratory pipette tips", "Facility cleaning service"}
    validate = subprocess.run([sys.executable, "-m", "cantill", "validate-output", "--config",
                               str(ROOT / "configs/company_C.example.yaml"), "--data-dir", str(ROOT),
                               "--output", str(output)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert validate.returncode == 0, validate.stderr
    assert json.loads(validate.stdout)["total_spend"] == "325"
