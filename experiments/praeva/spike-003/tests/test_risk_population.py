from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from praeva.risk.cpu_limit_insufficiency import evaluate_cpu_limit_insufficiency

SPIKE_DIR = Path(__file__).resolve().parents[1]
FIXTURE = SPIKE_DIR / "fixtures" / "S9-population-incomplete-high.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _cpu(value: str, *, window: str) -> dict[str, Any]:
    return {
        "status": "VALID",
        "value_millicores": value,
        "timestamp": "30",
        "query_key": f"cpu_{window}",
        "rate_window": "2m" if window == "short" else "5m",
    }


def _throttling(*, window: str) -> dict[str, Any]:
    return {
        "status": "VALID",
        "any_positive": False,
        "max_rate": "0",
        "max_timestamp": "30",
        "query_key": f"cfs_throttled_{window}",
        "points": 3,
        "coverage": {"observed_points": 3, "expected_points": 3},
        "coverage_complete": True,
        "rate_window": "2m" if window == "short" else "5m",
    }


def _pod(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "windows": {
            "short": {
                "observed_cpu": _cpu(spec["short_millicores"], window="short"),
                "cfs_throttling": _throttling(window="short"),
            },
            "long": {
                "observed_cpu": _cpu(spec["long_millicores"], window="long"),
                "cfs_throttling": _throttling(window="long"),
            },
        },
        "current_declared_effective_relation": {
            "status": "VALID",
            "relation": "MATCH",
            "current_declared_cpu_limit_millicores": "500",
            "effective_observed_cpu_limit_millicores": "500",
        },
    }


def _joined(fixture: dict[str, Any], population: list[str]) -> dict[str, Any]:
    return {
        "join_id": "CHANGE-JOIN-001",
        "identity_assertion": {
            "status": "CALLER_ASSERTED",
            "workload_to_pod_selector_relation": "UNVERIFIED",
        },
        "change_facts": {
            "direction": "DECREASE",
            "proposed_declared_cpu_limit": fixture["proposed_limit_millicores"],
        },
        "historical_context": {
            "application_version_relation": "UNVERIFIED",
        },
        "pods": {
            pod: _pod(fixture["pods"][pod])
            for pod in population
        },
    }


def test_s9_incomplete_population_can_misclassify_high_when_complete_is_critical() -> None:
    fixture = _load_fixture()

    observed = evaluate_cpu_limit_insufficiency(
        joined=_joined(fixture, fixture["observed_population"]),
        margin=fixture["margin"],
    )
    complete = evaluate_cpu_limit_insufficiency(
        joined=_joined(fixture, fixture["complete_population"]),
        margin=fixture["margin"],
    )

    assert observed["classification_status"] == "CLASSIFIED"
    assert observed["risk_level"] == "HIGH"
    assert observed["classification_basis"] == "short_window_only_contradiction"

    assert complete["classification_status"] == "CLASSIFIED"
    assert complete["risk_level"] == "CRITICAL"
    assert complete["classification_basis"] == "sustained_window_contradiction"
    assert any("pods.pod-c.windows.long.observed_cpu" == ref for ref in complete["evidence_refs"])
