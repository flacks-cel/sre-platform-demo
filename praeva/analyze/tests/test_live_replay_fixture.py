from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from praeva.analyze.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "jobs-api-live-001"


def _load_metadata() -> dict[str, Any]:
    return json.loads((FIXTURE / "replay.json").read_text(encoding="utf-8"))


def _load_prometheus(name: str) -> dict[str, Any]:
    return json.loads(
        (FIXTURE / "prometheus" / f"{name}.json").read_text(encoding="utf-8"),
        parse_float=Decimal,
    )


def _query_range(
    *,
    prometheus_url: str,
    query: str,
    start: Any,
    end: Any,
    step: Any,
) -> dict[str, Any]:
    del prometheus_url

    metadata = _load_metadata()
    acquisition = metadata["acquisition"]
    short_window = acquisition["short_window"]
    long_window = acquisition["long_window"]

    assert str(start) == acquisition["start"]
    assert str(end) == acquisition["end"]
    assert str(step) == acquisition["step"]

    if "kube_pod_container_resource_limits" in query:
        return _load_prometheus("cpu_limit")

    if "container_cpu_cfs_throttled_periods_total" in query:
        if f"[{short_window}]" in query:
            return _load_prometheus("cfs_throttled_short")
        if f"[{long_window}]" in query:
            return _load_prometheus("cfs_throttled_long")

    if "container_cpu_usage_seconds_total" in query:
        if f"[{short_window}]" in query:
            return _load_prometheus("cpu_short")
        if f"[{long_window}]" in query:
            return _load_prometheus("cpu_long")

    raise AssertionError(f"unexpected replay query: {query}")


def _args() -> list[str]:
    metadata = _load_metadata()
    acquisition = metadata["acquisition"]
    workload = metadata["workload"]

    return [
        "analyze",
        "--rule",
        metadata["rule_id"],
        "--current",
        str(FIXTURE / "current.yaml"),
        "--proposed",
        str(FIXTURE / "proposed.yaml"),
        "--api-group",
        workload["api_group"],
        "--kind",
        workload["kind"],
        "--namespace",
        workload["namespace"],
        "--name",
        workload["name"],
        "--container",
        workload["container"],
        "--container-space",
        workload["container_space"],
        "--pod-regex",
        workload["pod_regex"],
        "--prometheus-url",
        "http://replay.invalid",
        "--start",
        acquisition["start"],
        "--end",
        acquisition["end"],
        "--step",
        acquisition["step"],
        "--short-window",
        acquisition["short_window"],
        "--long-window",
        acquisition["long_window"],
        "--rule-param",
        f"margin={metadata['rule_params']['margin']}",
    ]


def test_live_prometheus_replay_matches_captured_wire_byte_for_byte(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = (FIXTURE / "expected.json").read_text(encoding="utf-8")

    assert main(_args(), query_range=_query_range) == 0
    first = capsys.readouterr().out
    assert first == expected

    assert main(_args(), query_range=_query_range) == 0
    second = capsys.readouterr().out
    assert second == expected
    assert second == first

    payload = json.loads(first)
    assert payload["result"]["classification_status"] == "UNKNOWN"
    assert payload["result"]["unknown_reasons"] == [
        {
            "code": "censored_evidence",
            "precondition": "uncensored_evidence_for_noncontradiction",
        }
    ]
