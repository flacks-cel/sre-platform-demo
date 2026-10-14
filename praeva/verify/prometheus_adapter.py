from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any


class PrometheusAdapterError(RuntimeError):
    """Raised when Prometheus acquisition cannot be normalized deterministically."""


QueryRange = Callable[..., dict[str, Any]]
Point = dict[str, float | int]


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _default_query_range(
    *,
    prometheus_url: str,
    query: str,
    start: float | int,
    end: float | int,
    step: float | int,
) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
        }
    )
    url = f"{prometheus_url.rstrip('/')}/api/v1/query_range?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response)
    except Exception as exc:  # pragma: no cover - transport depends on runtime
        raise PrometheusAdapterError(f"Prometheus request failed: {exc}") from exc


def _query_range(
    query_range: QueryRange,
    *,
    prometheus_url: str,
    query: str,
    start: float | int,
    end: float | int,
    step: float | int,
) -> dict[str, Any]:
    try:
        payload = query_range(
            prometheus_url=prometheus_url,
            query=query,
            start=start,
            end=end,
            step=step,
        )
    except PrometheusAdapterError:
        raise
    except Exception as exc:
        raise PrometheusAdapterError(f"Prometheus query execution failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise PrometheusAdapterError("Prometheus response must be a JSON object")
    if payload.get("status") != "success":
        detail = payload.get("error") or "unknown error"
        raise PrometheusAdapterError(f"Prometheus API returned failure: {detail}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise PrometheusAdapterError("Prometheus response is missing data")
    if data.get("resultType") != "matrix":
        raise PrometheusAdapterError("Prometheus query_range result must be matrix")

    return payload


def _parse_matrix(payload: dict[str, Any], *, metric_name: str) -> dict[str, list[Point]]:
    data = payload["data"]
    result = data.get("result")
    if not isinstance(result, list):
        raise PrometheusAdapterError("Prometheus matrix result must be a list")

    per_pod: dict[str, list[Point]] = {}
    for series in result:
        if not isinstance(series, dict):
            raise PrometheusAdapterError("Prometheus matrix series must be an object")

        labels = series.get("metric")
        values = series.get("values")
        if not isinstance(labels, dict) or not isinstance(values, list):
            raise PrometheusAdapterError("Prometheus matrix series is malformed")

        pod = labels.get("pod")
        if not isinstance(pod, str) or not pod:
            raise PrometheusAdapterError(f"Prometheus {metric_name} series is missing pod label")
        if pod in per_pod:
            raise PrometheusAdapterError(
                f"duplicate Prometheus series for pod {pod} and metric {metric_name}"
            )

        points: list[Point] = []
        for sample in values:
            if not isinstance(sample, list) or len(sample) != 2:
                raise PrometheusAdapterError("Prometheus matrix sample is malformed")
            timestamp, raw_value = sample
            if not isinstance(timestamp, int | float):
                raise PrometheusAdapterError("Prometheus sample timestamp must be numeric")
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise PrometheusAdapterError("Prometheus sample value must be numeric") from exc
            points.append({"timestamp": timestamp, "value": value})

        per_pod[pod] = points

    return per_pod


def _expected_points(start: float | int, end: float | int, step: float | int) -> int:
    if step <= 0:
        raise PrometheusAdapterError("query_range step must be positive")
    if end < start:
        raise PrometheusAdapterError("query_range end must not be before start")
    return int((end - start) // step) + 1


def collect_normalized_evidence(
    *,
    prometheus_url: str,
    namespace: str,
    pod_regex: str,
    container: str,
    start: float | int,
    end: float | int,
    step: float | int,
    short_window: str,
    long_window: str,
    request_rate_query: str | None = None,
    query_range: QueryRange | None = None,
) -> dict[str, Any]:
    """Acquire historical Prometheus matrices and normalize them for build_report()."""

    namespace_label = _escape_label_value(namespace)
    pod_label = _escape_label_value(pod_regex)
    container_label = _escape_label_value(container)
    selector = (
        f'namespace="{namespace_label}",pod=~"{pod_label}",'
        f'container="{container_label}"'
    )

    short_query = (
        "sum by (pod) (rate(container_cpu_usage_seconds_total"
        f"{{{selector}}}[{short_window}]))"
    )
    long_query = (
        "sum by (pod) (rate(container_cpu_usage_seconds_total"
        f"{{{selector}}}[{long_window}]))"
    )
    limit_query = (
        "max by (pod) (kube_pod_container_resource_limits{"
        f'{selector},resource="cpu"}})'
    )

    runner = query_range or _default_query_range
    common = {
        "prometheus_url": prometheus_url,
        "start": start,
        "end": end,
        "step": step,
    }

    short_payload = _query_range(runner, query=short_query, **common)
    long_payload = _query_range(runner, query=long_query, **common)
    limit_payload = _query_range(runner, query=limit_query, **common)

    short_by_pod = _parse_matrix(short_payload, metric_name="cpu_short")
    long_by_pod = _parse_matrix(long_payload, metric_name="cpu_long")
    limit_by_pod = _parse_matrix(limit_payload, metric_name="cpu_limit")

    request_by_pod: dict[str, list[Point]] = {}
    if request_rate_query is not None:
        request_payload = _query_range(runner, query=request_rate_query, **common)
        request_by_pod = _parse_matrix(request_payload, metric_name="request_rate")

    pod_names = sorted(
        set(short_by_pod)
        | set(long_by_pod)
        | set(limit_by_pod)
        | set(request_by_pod)
    )
    expected = _expected_points(start, end, step)

    pods: list[dict[str, Any]] = []
    for pod_name in pod_names:
        cpu_short = short_by_pod.get(pod_name, [])
        sample_count = len(cpu_short)
        pods.append(
            {
                "name": pod_name,
                "cpu_short": cpu_short,
                "cpu_long": long_by_pod.get(pod_name, []),
                "cpu_limit": limit_by_pod.get(pod_name),
                "request_rate": (
                    request_by_pod.get(pod_name) if request_rate_query is not None else None
                ),
                "sample_count": sample_count,
                "coverage": sample_count / expected,
                "restart_delta": 0,
                "node": None,
                "owner": None,
            }
        )

    return {
        "pods": pods,
        "short_window": short_window,
        "long_window": long_window,
    }
