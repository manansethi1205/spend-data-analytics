"""Copy publishable candidates, install offline, and run without keys/private artifacts."""

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, env):
    started = perf_counter()
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {result.stderr[-2000:]}")
    return result.stdout, perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Optionally verify real A/B in local mode too")
    args = parser.parse_args()
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv must be installed")
    work = ROOT / "private/release_checks"
    work.mkdir(parents=True, exist_ok=True)
    checkout = Path(tempfile.mkdtemp(prefix="checkout_", dir=work))
    candidates = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    for value in filter(None, candidates):
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.parts[0] in ("private", "data", ".git", ".venv", ".cache") or path.name.startswith(".env"):
            raise RuntimeError("Private/unsafe candidate encountered")
        destination = checkout / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, destination)
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("OPENAI_") and key.upper() not in
           ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "UV_PROJECT", "UV_WORKING_DIRECTORY")}
    env["UV_PYTHON_DOWNLOADS"] = "never"
    print("Installing locked dependencies offline in isolated checkout", flush=True)
    _, install_seconds = run([uv, "sync", "--locked", "--offline", "--no-dev", "--no-editable",
                              "--python", sys.executable, "--cache-dir", str(ROOT / ".cache/uv")], checkout, env)
    python = checkout / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    report = {"checkout": str(checkout.relative_to(ROOT)), "install_seconds": install_seconds,
              "no_openai_environment": not any(k.upper().startswith("OPENAI_") for k in env),
              "private_artifacts_copied": False, "dependency_cache_only": True, "api_requests": 0, "runs": {}}
    jobs = [("C_DEMO", "configs/company_C.example.yaml", checkout)]
    if args.data_dir:
        jobs += [(company, f"configs/company_{company}.yaml", args.data_dir.resolve()) for company in ("A", "B")]
    for company, config, data_dir in jobs:
        print(f"Running {company} with no labels/index/API cache in local mode", flush=True)
        output = checkout / "private" / f"check_{company}.csv"
        stdout, seconds = run([str(python), "-m", "cantill", "run", "--config", config, "--data-dir", str(data_dir),
                               "--classifier", "local", "--llm-max-requests", "0", "--llm-max-tokens", "0", "--output", str(output)], checkout, env)
        summary = json.loads(stdout)
        if summary["labels_used"] or summary["openai_usage"] is not None:
            raise RuntimeError("Unexpected labels or API usage")
        stdout, _ = run([str(python), "-m", "cantill", "validate-output", "--config", config, "--data-dir", str(data_dir), "--output", str(output)], checkout, env)
        validation = json.loads(stdout)
        if not validation["valid"]:
            raise RuntimeError("Clean checkout export did not validate")
        if company == "C_DEMO":
            with output.open(newline="", encoding="utf-8") as stream:
                included = [row for row in csv.DictReader(stream) if row["include"] == "1"]
            if (validation["row_count"] != 6 or validation["included_rows"] != 3
                    or validation["total_spend"] != "325" or not all(row["l4"] for row in included)
                    or set(summary["exclusion_reasons"]) != {"CANCELLED", "NOT_APPROVED", "DUPLICATE"}):
                raise RuntimeError("Synthetic four-level new-company check failed")
        report["runs"][company] = {"seconds": seconds, "summary": summary, "validation": validation}
    report["status"] = "passed"
    (checkout / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (work / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
