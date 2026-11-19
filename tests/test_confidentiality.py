"""Repository safeguards use synthetic paths, never company records."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="Repository confidentiality checks require Git and a checkout",
)


@pytest.mark.parametrize(
    "path",
    [
        "private/profiling/profile.json",
        "data/company_A/unknown_input.csv",
        "nested/erp_goods_receipts.csv",
        "nested/invoice_tool_export.csv",
        "nested/labels_A.csv",
        "nested/taxonomy_A.csv",
        "nested/invoice_lines.csv",
        "nested/fx_rates_usd.csv",
        "nested/seed_labels.csv",
        "nested/taxonomy_B.csv",
        ".env",
        ".env.local",
        ".venv/pyvenv.cfg",
        ".cache/model/weights.bin",
        "dist/package.whl",
        "build/temp/file.txt",
        "src/cantill_spend.egg-info/PKG-INFO",
    ],
)
def test_confidential_and_generated_paths_are_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", path], cwd=ROOT
    )
    assert result.returncode == 0, f"Missing ignore protection for {path}"


@pytest.mark.parametrize(
    "path",
    [
        "submission/candidate__A2.csv",
        "submission/candidate__B2.csv",
        "submission/candidate__C.csv",
        "candidate__A.csv",
        "candidate__B.csv",
        "submission/company_C.yaml",
        "configs/company_A.yaml",
        "uv.lock",
    ],
)
def test_submission_and_config_paths_remain_publishable(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", path], cwd=ROOT
    )
    assert result.returncode == 1, f"Required deliverable unexpectedly ignored: {path}"


def test_no_ignored_files_are_tracked():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--ignored", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert not result.stdout.strip(), "Ignored files are already tracked; audit the Git index"
