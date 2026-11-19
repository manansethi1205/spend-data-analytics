"""Prepared-pilot launcher preserves session credentials and global bounds."""

import importlib.util
import json
from pathlib import Path

import pytest

from cantill.config import ConfigError


SPEC = importlib.util.spec_from_file_location("pilot_launcher", Path(__file__).resolve().parents[1] / "tools/run_prepared_pilots.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "REPO", tmp_path)
    root = tmp_path / "private/pilot/v1"
    for cohort, count in (("A", 40), ("B", 40), ("B_challenge", 12)):
        directory = root / cohort
        directory.mkdir(parents=True)
        (directory / "freeze.json").write_text(json.dumps({"payload": {"samples": [{}] * count}}))
    return root


def test_three_cohorts_share_explicit_total_budget(prepared):
    plan = launcher.commands("kit", prepared, ["candidate"], True, 95, 3_000_000)
    assert [attempts for _, attempts, _ in plan] == [41, 41, 13]
    assert all("--execute" in command for _, _, command in plan)
    assert all(command[command.index("--max-tokens") + 1] == "1000000" for _, _, command in plan)


def test_preview_does_not_enable_api_or_pass_credentials(prepared, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    plan = launcher.commands("kit", prepared, ["candidate"], False, 0, 0)
    assert all("--execute" not in command for _, _, command in plan)
    assert "synthetic-secret" not in json.dumps(plan)


def test_underfunded_or_nonprivate_runs_fail_before_launch(prepared):
    with pytest.raises(ConfigError, match="Total request"):
        launcher.commands("kit", prepared, ["candidate"], True, 94, 3_000_000)
    with pytest.raises(ConfigError, match="private"):
        launcher.commands("kit", prepared.parent.parent.parent, ["candidate"], True, 95, 3_000_000)


def test_two_models_require_two_gates_and_double_context_budget(prepared):
    plan = launcher.commands("kit", prepared, ["one", "two"], True, 190, 6_000_000)
    assert sum(attempts for _, attempts, _ in plan) == 190
