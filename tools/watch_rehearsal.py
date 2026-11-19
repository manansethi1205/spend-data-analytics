"""Observe saved rehearsal progress without starting inference or reading credentials."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import time


def snapshot(root, company):
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))["payload"]
    expected = plan["companies"][company]["unique_contexts"]
    directory = root / company
    decisions = list((directory / "decisions").glob("*.json"))
    newest = max((path.stat().st_mtime for path in decisions), default=None)
    reports = []
    for run in sorted((directory / "runs").glob("*")):
        report = run / "report.json"
        status = json.loads(report.read_text(encoding="utf-8"))["status"] if report.exists() else "no final report"
        reports.append(f"{run.name}: {status}")
    updated = datetime.fromtimestamp(newest).isoformat(timespec="seconds") if newest else "none"
    return (f"{company}: {len(decisions):,}/{expected:,} cached decisions; latest saved: {updated}\n"
            + "\n".join(reports)
            + "\nSaved files do not prove a process is still running. No API requests made by this monitor.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", choices=("A", "B"), default="A")
    parser.add_argument("--rehearsal-root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "private/rehearsal/v2")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        while True:
            print(snapshot(args.rehearsal_root, args.company), flush=True)
            if args.once:
                return
            time.sleep(10)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
