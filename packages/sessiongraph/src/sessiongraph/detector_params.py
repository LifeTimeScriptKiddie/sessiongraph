"""Load checked-in detector parameter defaults."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PARAMS_PATH = Path(__file__).resolve().parents[2] / "detector_params.v1.json"


@lru_cache(maxsize=1)
def load_detector_params() -> dict[str, Any]:
    data = json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))
    if data.get("schema") != "sessiongraph.detector-params.v1":
        raise ValueError(f"unexpected detector params schema: {data.get('schema')}")
    return data


def repeated_action_params() -> tuple[int, int]:
    block = load_detector_params()["repeated_action"]
    return int(block["minimum"]), int(block["window"])


def same_tool_failing_minimum() -> int:
    return int(load_detector_params()["same_tool_failing"]["minimum"])


def revert_window() -> int:
    return int(load_detector_params()["revert_window"])


def verify_thresholds() -> dict[str, float]:
    raw = load_detector_params()["verify_thresholds"]
    return {key: float(raw[key]) for key in ("min_labeled_flagged", "precision", "recall")}
