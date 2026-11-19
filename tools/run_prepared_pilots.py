"""Run prepared pilots from the same terminal that holds a working API key."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from cantill.config import ClassificationConfig, ConfigError


REPO = Path(__file__).resolve().parents[1]
COHORTS = (("A", "company_A.yaml"), ("B", "company_B.yaml"), ("B_challenge", "company_B.yaml"))


def commands(data_dir, pilot_root, models, execute, max_requests, max_tokens):
    root = Path(pilot_root).resolve()
    if not root.is_relative_to((REPO / "private").resolve()):
        raise ConfigError("Prepared pilot root must remain under the repository's private directory")
    if not 1 <= len(models) <= 4 or len(set(models)) != len(models) or any(not model.strip() for model in models):
        raise ConfigError("Choose one to four unique model IDs")
    ClassificationConfig(max_requests=max_requests, max_tokens=max_tokens)
    planned = []
    for cohort, config in COHORTS:
        try:
            freeze = json.loads((root / cohort / "freeze.json").read_text(encoding="utf-8"))
            count = len(freeze["payload"]["samples"])
        except (OSError, ValueError, KeyError, TypeError):
            raise ConfigError("A prepared pilot freeze is missing or unreadable") from None
        if not count:
            raise ConfigError("A prepared pilot sample is empty")
        attempts = (count + 1) * len(models)  # One synthetic gate per model/cohort.
        command = [sys.executable, str(REPO / "tools/pilot_classification.py"), "run",
                   "--config", str(REPO / "configs" / config), "--data-dir", str(data_dir),
                   "--pilot-dir", str(root / cohort), "--models", *models,
                   "--max-requests", str(attempts), "--max-tokens", str(max_tokens // len(COHORTS))]
        if execute:
            command.append("--execute")
        planned.append((cohort, attempts, command))
    if execute and sum(attempts for _, attempts, _ in planned) > max_requests:
        raise ConfigError("Total request allowance cannot cover all prepared samples and synthetic gates")
    return planned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, default=REPO / "private/pilot/v1")
    parser.add_argument("--models", nargs="+", default=[ClassificationConfig().model])
    parser.add_argument("--execute", action="store_true", help="Allow bounded API requests; otherwise preview offline")
    parser.add_argument("--max-requests", type=int, default=95, help="Total for all cohorts and synthetic gates")
    parser.add_argument("--max-tokens", type=int, default=3_000_000, help="Total conservative allowance across cohorts")
    args = parser.parse_args()
    try:
        if args.execute and not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ConfigError("Set OPENAI_API_KEY in the SAME terminal that launches this command")
        planned = commands(args.data_dir, args.pilot_root, args.models, args.execute, args.max_requests, args.max_tokens)
    except ConfigError as exc:
        parser.exit(2, f"error: {exc}\n")
    for cohort, attempts, command in planned:
        print(f"Running {cohort}: {'bounded API pilot' if args.execute else 'offline preview'}", flush=True)
        # Inherit the terminal's environment in memory; never copy/log its key.
        result = subprocess.run(command, cwd=REPO, check=False)
        if result.returncode:
            print(f"Stopped after {cohort}; inspect its private report before retrying.", file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
