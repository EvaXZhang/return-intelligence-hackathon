"""Load only the explicit synthetic fixture inside this project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Buyer, ConditionObservation, ReturnItem, Store

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "synthetic_demo.json"


def load_demo_data() -> dict[str, Any]:
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return {
        "notice": raw["notice"],
        "returns": [ReturnItem.model_validate(value) for value in raw["returns"]],
        "observations": {
            key: ConditionObservation.model_validate(value)
            for key, value in raw["observations"].items()
        },
        "scenarios": raw["scenarios"],
        "buyers": [Buyer.model_validate(value) for value in raw["buyers"]],
        "stores": [Store.model_validate(value) for value in raw["stores"]],
    }
