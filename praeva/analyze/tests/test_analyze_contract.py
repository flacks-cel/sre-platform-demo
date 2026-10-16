from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest


CURRENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jobs-api
  namespace: app
spec:
  template:
    spec:
      containers:
        - name: jobs-api
          resources:
            requests:
              cpu: 100m
            limits:
              cpu: 500m
"""

PROPOSED_CRITICAL = CURRENT.replace("cpu: 500m", "cpu: 250m")
PROPOSED_LOW = CURRENT.replace("cpu: 500m", "cpu: 450m")
PROPOSED_REMOVED = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jobs-api
  namespace: app
spec:
  template:
    spec:
      containers:
        - name: jobs-api
          resources:
            requests:
              cpu: 100m
"""


def _matrix(values: list[str], *, pod: str = "jobs-api-abc") -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"pod": pod},
                    "values": [[str(index * 15), value] for index, value in enumerate(values)],
                }
            ],
        },
    }


def _transport(
    *,
    cpu: str = "0.4",
    limit: str = "0.5",
    throttling: str = "0",
    bad_result_type: bool = False,
    calls: list[str] | None = None,
):
    def query_range(**kwargs: Any) -> dict[str, Any]:
        query = kwargs["query"]
        if calls is not None:
            calls.append(query)
        if bad_result_type:
            return {"status": "success", "data": {"resultType": "vector", "result": []}}
        if "container_cpu_cfs_throttled_periods_total" in query:
            return _matrix([throttling, throttling, throttling])
        if "kube_pod_container_resource_limits" in query:
            return _matrix([limit, limit, limit])
        if "container_cpu_usage_seconds_total" in query:
            return _matrix([cpu, cpu, cpu])
        raise AssertionError(f"unexpected query: {query}")

    return query_range


def _analyze():
    return importlib.import_module("praeva.analyze.orchestrator").analyze


def _main():
    return importlib.import_module("praeva.analyze.cli").main


def _kwargs(
    *,
    proposed: str = PROPOSED_CRITICAL,
    query_range=None,
    rule_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "current_manifest": CURRENT,
        "proposed_manifest": proposed,
        "api_group": "apps",
        "kind": "Deployment",
        "namespace": "app",
        "name": "jobs-api",
        "container": "jobs-api",
        "container_space": "containers",
        "pod_regex": "jobs-api-.*",
        "prometheus_url": "http://prometheus.test",
        "start": "0",
        "end": "30",
        "step": "15",
        "short_window": "2m",
        "long_window": "5m",
        "rule_id": "CHANGE-RISK-001",
        "rule_params": rule_params if rule_params is not None else {"margin": "11/10"},
        "query_range": query_range or _transport(),
    }


def _write_manifests(tmp_path: Path, *, proposed: str = PROPOSED_CRITICAL) -> tuple[Path, Path]:
    current_path = tmp_path / "current.yaml"
    proposed_path = tmp_path / "proposed.yaml"
    current_path.write_text(CURRENT, encoding="utf-8")
    proposed_path.write_text(proposed, encoding="utf-8")
    return current_path, proposed_path


def _cli_args(current: Path, proposed: Path) -> list[str]:
    return [
        "analyze",
        "--rule",
        "CHANGE-RISK-001",
        "--current",
        str(current),
        "--proposed",
        str(proposed),
        "--api-group",
        "apps",
        "--kind",
        "Deployment",
        "--namespace",
        "app",
        "--name",
        "jobs-api",
        "--container",
        "jobs-api",
        "--pod-regex",
        "jobs-api-.*",
        "--prometheus-url",
        "http://prometheus.test",
        "--start",
        "0",
        "--end",
        "30",
        "--step",
        "15",
        "--short-window",
        "2m",
        "--long-window",
        "5m",
        "--rule-param",
        "margin=11/10",
    ]


def test_happy_path_composes_all_four_layers() -> None:
    result = _analyze()(**_kwargs())

    assert result["schema_version"] == "PRAEVA-ANALYZE-001"
    assert result["result"]["risk_level"] == "CRITICAL"
    assert set(result["layers"]) == {"change_input", "verify", "change_join", "risk"}
    assert result["layers"]["risk"] == result["result"]


def test_missing_time_parameter_is_input_error() -> None:
    kwargs = _kwargs()
    kwargs.pop("start")

    with pytest.raises(Exception, match="start"):
        _analyze()(**kwargs)


def test_missing_rule_is_cli_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current, proposed = _write_manifests(tmp_path)
    args = _cli_args(current, proposed)
    index = args.index("--rule")
    del args[index : index + 2]

    assert _main()(args, query_range=_transport()) != 0
    assert "rule" in capsys.readouterr().err.lower()


def test_unknown_rule_is_named_input_error() -> None:
    kwargs = _kwargs()
    kwargs["rule_id"] = "CHANGE-RISK-999"

    with pytest.raises(Exception, match="CHANGE-RISK-999"):
        _analyze()(**kwargs)


def test_decimal_margin_text_is_rejected_by_selected_rule() -> None:
    with pytest.raises(Exception, match="margin"):
        _analyze()(**_kwargs(rule_params={"margin": "1.1"}))


def test_margin_not_greater_than_one_is_rejected_by_selected_rule() -> None:
    with pytest.raises(Exception, match="greater than one"):
        _analyze()(**_kwargs(rule_params={"margin": "10/11"}))


def test_missing_margin_is_rejected_by_selected_rule() -> None:
    with pytest.raises(Exception, match="margin"):
        _analyze()(**_kwargs(rule_params={}))


def test_transport_failure_is_execution_error_not_unknown() -> None:
    def broken_transport(**_: Any) -> dict[str, Any]:
        raise OSError("prometheus unavailable")

    with pytest.raises(Exception, match="prometheus unavailable"):
        _analyze()(**_kwargs(query_range=broken_transport))


def test_unexpected_prometheus_result_type_fails_through_real_adapter() -> None:
    with pytest.raises(Exception, match="matrix"):
        _analyze()(**_kwargs(query_range=_transport(bad_result_type=True)))


def test_invalid_manifest_fails_before_prometheus_is_called() -> None:
    calls: list[str] = []
    kwargs = _kwargs(query_range=_transport(calls=calls))
    kwargs["current_manifest"] = "not: [valid"

    with pytest.raises(Exception):
        _analyze()(**kwargs)

    assert calls == []


def test_critical_is_a_successful_cli_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _write_manifests(tmp_path)

    assert _main()(_cli_args(current, proposed), query_range=_transport()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["risk_level"] == "CRITICAL"


def test_censored_unknown_is_success_and_auditable() -> None:
    result = _analyze()(
        **_kwargs(
            proposed=PROPOSED_LOW,
            query_range=_transport(cpu="0.4", limit="0.5", throttling="0.01"),
        )
    )

    assert result["result"]["classification_status"] == "UNKNOWN"
    assert result["result"]["unknown_reasons"][0]["code"] == "censored_evidence"
    assert result["result"]["evidence_refs"]
    assert set(result["layers"]) == {"change_input", "verify", "change_join", "risk"}


def test_canonical_document_preserves_layers_without_summary() -> None:
    result = _analyze()(**_kwargs())

    assert "summary" not in result
    assert result["layers"]["change_input"]["direction"] == "DECREASE"
    assert result["layers"]["verify"]["pods"]
    assert result["layers"]["change_join"]["join_id"] == "CHANGE-JOIN-001"


def test_same_replay_is_byte_for_byte_deterministic() -> None:
    first = _analyze()(**_kwargs())
    second = _analyze()(**_kwargs())

    first_wire = json.dumps(first, sort_keys=True, separators=(",", ":"))
    second_wire = json.dumps(second, sort_keys=True, separators=(",", ":"))
    assert first_wire == second_wire


def test_summary_is_rendering_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    current, proposed = _write_manifests(tmp_path)
    args = [*_cli_args(current, proposed), "--summary"]

    assert _main()(args, query_range=_transport()) == 0
    summary = capsys.readouterr().out
    assert "CRITICAL" in summary

    canonical = _analyze()(**_kwargs())
    assert canonical["result"]["risk_level"] == "CRITICAL"
    assert "summary" not in canonical


def test_limit_removed_is_not_applicable_and_exit_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current, proposed = _write_manifests(tmp_path, proposed=PROPOSED_REMOVED)

    assert _main()(_cli_args(current, proposed), query_range=_transport()) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["applicability"] == "NOT_APPLICABLE"
    assert "classification_status" not in payload["result"]
