"""Saved pilot review rejects corrupt coverage and invalid decisions."""

import importlib.util
from pathlib import Path
import sys

import pytest

from cantill.config import ConfigError


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
try:
    SPEC = importlib.util.spec_from_file_location("pilot_review", TOOLS / "review_pilot_results.py")
    review = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(review)
finally:
    sys.path.pop(0)


def decision(**overrides):
    return {"record_id": "synthetic-1", "path": ["Goods", "Bolts"],
            "confidence": .8, "method": "openai", "flag": "", **overrides}


def test_valid_saved_prediction():
    assert review.verify_predictions([{"record_id": "synthetic-1"}], [decision()],
                                     [["Goods", "Bolts"]]) == [(("Goods", "Bolts"), .8)]


@pytest.mark.parametrize("changes", [
    {"record_id": "other"}, {"path": ["Goods"]}, {"confidence": float("nan")},
    {"confidence": True}, {"confidence": 1.1}, {"method": "local"}, {"flag": "fallback"},
])
def test_invalid_or_incomplete_saved_decision(changes):
    with pytest.raises(ConfigError):
        review.verify_predictions([{"record_id": "synthetic-1"}], [decision(**changes)],
                                  [["Goods", "Bolts"]])


def test_duplicate_or_missing_prediction_ids():
    with pytest.raises(ConfigError):
        review.verify_predictions([{"record_id": "synthetic-1"}], [], [["Goods", "Bolts"]])
    with pytest.raises(ConfigError):
        review.verify_predictions([{"record_id": "synthetic-1"}] * 2, [decision()] * 2,
                                  [["Goods", "Bolts"]])
