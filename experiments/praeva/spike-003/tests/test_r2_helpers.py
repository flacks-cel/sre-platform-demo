from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SPIKE_DIR / filename)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load module: {filename}")

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SPIKE_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_r2_preflight_requires_ten_minutes_behind_ingestion_lag() -> None:
    module = _load_module("spike003_r2_preflight", "r2_preflight.py")

    interval = module.compute_preflight_interval(1000)

    assert interval == {
        "start": "270",
        "end": "870",
        "step": "15",
        "required_trailing_seconds": "600",
        "ingestion_lag_seconds": "120",
    }


def test_r2_collection_interval_is_derived_from_mutation_grid() -> None:
    module = _load_module("spike003_r2_collect", "r2_collect.py")

    interval = module.compute_r2_interval(
        mutation_before="1001",
        mutation_after="1003",
    )

    assert interval["mutation_grid_before"] == "990"
    assert interval["mutation_grid_after"] == "1005"
    assert interval["start"] == "690"
    assert interval["end"] == "1605"
    assert interval["extended_ownership_start"] == "390"
    assert interval["earliest_collection"] == "1725"
    assert interval["extension_steps"] == "20"


def test_r2_collection_rejects_reversed_mutation_timestamps() -> None:
    module = _load_module("spike003_r2_collect_invalid", "r2_collect.py")

    with pytest.raises(module.collect.CollectionError, match="mutation_after"):
        module.compute_r2_interval(
            mutation_before="1003",
            mutation_after="1001",
        )
