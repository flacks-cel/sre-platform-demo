from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any


class OwnershipPrometheusAdapterError(RuntimeError):
    """Raised when historical ownership telemetry cannot be normalized deterministically."""


QueryRange = Callable[..., dict[str, Any]]
TemporalValue = str | int | Decimal


_POD_LABELS = (
    "namespace",
    "pod",
    "uid",
    "owner_kind",
    "owner_name",
    "owner_is_controller",
)
_REPLICASET_LABELS = (
    "namespace",
    "replicaset",
    "owner_kind",
    "owner_name",
    "owner_is_controller",
)


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise OwnershipPrometheusAdapterError(f"{field} must not be represented as float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise OwnershipPrometheusAdapterError(f"{field} must be numeric") from exc
    else:
        raise OwnershipPrometheusAdapterError(f"{field} must be numeric")
    if not number.is_finite():
        raise OwnershipPrometheusAdapterError(f"{field} must be finite")
    return number


def _canonical_decimal(value: Any, *, field: str) -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _default_query_range(
    *,
    prometheus_url: str,
    query: str,
    start: TemporalValue,
    end: TemporalValue,
    step: TemporalValue,
) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "start": _canonical_decimal(start, field="start"),
            "end": _canonical_decimal(end, field="end"),
            "step": _canonical_decimal(step, field="step"),
        }
    )
    url = f"{prometheus_url.rstrip('/')}/api/v1/query_range?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response, parse_float=Decimal)
    except Exception as exc:  # pragma: no cover - runtime transport
        raise OwnershipPrometheusAdapterError(f"Prometheus request failed: {exc}") from exc


def _query_range(
    query_range: QueryRange,
    *,
    prometheus_url: str,
    query: str,
    start: TemporalValue,
    end: TemporalValue,
    step: TemporalValue,
) -> dict[str, Any]:
    try:
        payload = query_range(
            prometheus_url=prometheus_url,
            query=query,
            start=start,
            end=end,
            step=step,
        )
    except OwnershipPrometheusAdapterError:
        raise
    except Exception as exc:
        raise OwnershipPrometheusAdapterError(
            f"Prometheus query execution failed: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise OwnershipPrometheusAdapterError("Prometheus response must be a JSON object")
    if payload.get("status") != "success":
        detail = payload.get("error") or "unknown error"
        raise OwnershipPrometheusAdapterError(f"Prometheus API returned failure: {detail}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise OwnershipPrometheusAdapterError("Prometheus response is missing data")
    if data.get("resultType") != "matrix":
        raise OwnershipPrometheusAdapterError("Prometheus query_range result must be matrix")
    if not isinstance(data.get("result"), list):
        raise OwnershipPrometheusAdapterError("Prometheus matrix result must be a list")
    return payload


def _required_labels(
    labels: dict[str, Any],
    *,
    required: tuple[str, ...],
    metric_name: str,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for label in required:
        value = labels.get(label)
        if not isinstance(value, str) or not value:
            raise OwnershipPrometheusAdapterError(
                f"Prometheus {metric_name} series is missing required {label} label"
            )
        normalized[label] = value
    return normalized


def _parse_samples(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise OwnershipPrometheusAdapterError("Prometheus matrix series values must be a list")

    samples: list[dict[str, str]] = []
    for sample in values:
        if not isinstance(sample, list) or len(sample) != 2:
            raise OwnershipPrometheusAdapterError("Prometheus matrix sample is malformed")
        timestamp, raw_value = sample
        timestamp_text = _canonical_decimal(
            timestamp,
            field="Prometheus sample timestamp",
        )
        if not isinstance(raw_value, str):
            raise OwnershipPrometheusAdapterError(
                "Prometheus owner metric sample value must be a string"
            )
        samples.append({"timestamp": timestamp_text, "value": raw_value})

    return sorted(samples, key=lambda item: _decimal(item["timestamp"], field="timestamp"))


def _parse_matrix(
    payload: dict[str, Any],
    *,
    metric_name: str,
    required_labels: tuple[str, ...],
) -> list[dict[str, Any]]:
    result = payload["data"]["result"]
    normalized: list[dict[str, Any]] = []
    for series in result:
        if not isinstance(series, dict):
            raise OwnershipPrometheusAdapterError("Prometheus matrix series must be an object")
        labels = series.get("metric")
        if not isinstance(labels, dict):
            raise OwnershipPrometheusAdapterError(
                "Prometheus matrix series is missing metric labels"
            )
        identity = _required_labels(
            labels,
            required=required_labels,
            metric_name=metric_name,
        )
        normalized.append(
            {
                **identity,
                "samples": _parse_samples(series.get("values")),
            }
        )

    return sorted(
        normalized,
        key=lambda item: tuple(item[label] for label in required_labels),
    )


def collect_ownership_evidence(
    *,
    prometheus_url: str,
    namespace: str,
    start: TemporalValue,
    end: TemporalValue,
    step: TemporalValue,
    query_range: QueryRange | None = None,
) -> dict[str, Any]:
    """Collect and normalize historical Pod and ReplicaSet controller-owner telemetry."""

    if not isinstance(namespace, str) or not namespace:
        raise OwnershipPrometheusAdapterError("namespace must be a non-empty string")

    start_text = _canonical_decimal(start, field="start")
    end_text = _canonical_decimal(end, field="end")
    step_text = _canonical_decimal(step, field="step")
    start_value = _decimal(start_text, field="start")
    end_value = _decimal(end_text, field="end")
    step_value = _decimal(step_text, field="step")
    if step_value <= 0:
        raise OwnershipPrometheusAdapterError("query_range step must be positive")
    if end_value < start_value:
        raise OwnershipPrometheusAdapterError("query_range end must not be before start")

    namespace_label = _escape_label_value(namespace)
    pod_query = (
        "max by (namespace, pod, uid, owner_kind, owner_name, owner_is_controller) ("
        f'kube_pod_owner{{namespace="{namespace_label}",owner_is_controller="true"}}'
        ")"
    )
    replicaset_query = (
        "max by (namespace, replicaset, owner_kind, owner_name, owner_is_controller) ("
        f'kube_replicaset_owner{{namespace="{namespace_label}",owner_is_controller="true"}}'
        ")"
    )

    runner = query_range or _default_query_range
    common = {
        "prometheus_url": prometheus_url,
        "start": start_text,
        "end": end_text,
        "step": step_text,
    }
    pod_payload = _query_range(runner, query=pod_query, **common)
    replicaset_payload = _query_range(runner, query=replicaset_query, **common)

    return {
        "acquisition": {
            "namespace": namespace,
            "start": start_text,
            "end": end_text,
            "step": step_text,
        },
        "queries": {
            "pod_owner": {"promql": pod_query},
            "replicaset_owner": {"promql": replicaset_query},
        },
        "pod_owner_series": _parse_matrix(
            pod_payload,
            metric_name="kube_pod_owner",
            required_labels=_POD_LABELS,
        ),
        "replicaset_owner_series": _parse_matrix(
            replicaset_payload,
            metric_name="kube_replicaset_owner",
            required_labels=_REPLICASET_LABELS,
        ),
    }
