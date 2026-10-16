from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

Status = str
Point = dict[str, Any]
PodInput = dict[str, Any]
Ratio = dict[str, str]


def _unknown(reason: str, *, reason_code: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "UNKNOWN", "reason": reason}
    if reason_code is not None:
        result["reason_code"] = reason_code
    return result


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal measurement")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # Legacy direct-core callers remain readable; the normative Prometheus wire is text.
        result = Decimal(str(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal measurement: {value!r}") from exc
    else:
        raise ValueError(f"invalid decimal measurement type: {type(value).__name__}")
    return result


def _canonical_decimal(value: Any) -> str:
    number = _decimal(value)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _wire_value(value: Any) -> str:
    if isinstance(value, str):
        _decimal(value)
        return value
    return _canonical_decimal(value)


def _wire_timestamp(value: Any) -> str:
    return _canonical_decimal(value)


def _normalize_point(point: Point, default_query_key: str) -> dict[str, str]:
    return {
        "timestamp": _wire_timestamp(point["timestamp"]),
        "value": _wire_value(point["value"]),
        "query_key": str(point.get("query_key") or default_query_key),
    }


def _finite(value: Any) -> bool:
    return _decimal(value).is_finite()


def _coverage_wire(pod: PodInput) -> dict[str, int] | None:
    coverage = pod.get("coverage")
    if coverage is None:
        return None
    if isinstance(coverage, dict):
        observed = coverage.get("observed_points")
        expected = coverage.get("expected_points")
        if not isinstance(observed, int) or not isinstance(expected, int):
            raise ValueError("coverage point counts must be integers")
        return {"observed_points": observed, "expected_points": expected}

    sample_count = pod.get("sample_count")
    if not isinstance(sample_count, int):
        raise ValueError("legacy numeric coverage requires integer sample_count")
    coverage_decimal = _decimal(coverage)
    if not coverage_decimal.is_finite() or coverage_decimal <= 0:
        raise ValueError("legacy numeric coverage must be finite and positive")
    expected = Decimal(sample_count) / coverage_decimal
    if expected != expected.to_integral_value():
        raise ValueError("legacy numeric coverage cannot be represented as exact point counts")
    return {"observed_points": sample_count, "expected_points": int(expected)}


def _indexed_points(
    points: list[Point] | None,
    query_key: str,
) -> tuple[dict[str, dict[str, str]], bool, bool]:
    if not points:
        return {}, False, False

    indexed: dict[str, dict[str, str]] = {}
    duplicate = False
    non_finite = False
    for point in points:
        normalized = _normalize_point(point, query_key)
        timestamp = normalized["timestamp"]
        if timestamp in indexed:
            duplicate = True
        if not _finite(normalized["value"]):
            non_finite = True
        indexed[timestamp] = normalized
    return indexed, duplicate, non_finite


def _series_summary(points: list[Point] | None, window: str, query_key: str) -> dict[str, Any]:
    if not points:
        return {
            "status": "UNKNOWN",
            "window": window,
            "reason": "series is missing or empty",
        }

    normalized = [_normalize_point(point, query_key) for point in points]
    if any(not _finite(point["value"]) for point in normalized):
        return {
            "status": "UNKNOWN",
            "window": window,
            "reason_code": "non_finite_sample",
            "reason": "series contains a non-finite sample",
        }

    maximum = max(normalized, key=lambda item: _decimal(item["value"]))
    minimum = min(normalized, key=lambda item: _decimal(item["value"]))
    return {
        "status": "VALID",
        "window": window,
        "max": maximum["value"],
        "max_timestamp": maximum["timestamp"],
        "query_key": maximum["query_key"],
        "points": len(normalized),
        "min": minimum["value"],
    }


def _ratio(numerator: str, denominator: str) -> Ratio:
    return {"numerator": numerator, "denominator": denominator}


def _ratio_gt(left: Ratio, right: Ratio) -> bool:
    return _decimal(left["numerator"]) * _decimal(right["denominator"]) > _decimal(
        right["numerator"]
    ) * _decimal(left["denominator"])


def _ratio_eq(left: Ratio, right: Ratio) -> bool:
    return _decimal(left["numerator"]) * _decimal(right["denominator"]) == _decimal(
        right["numerator"]
    ) * _decimal(left["denominator"])


def _max_ratio_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    best = candidates[0]
    for candidate in candidates[1:]:
        if _ratio_gt(candidate["ratio"], best["ratio"]):
            best = candidate
        elif _ratio_eq(candidate["ratio"], best["ratio"]):
            if str(candidate.get("pod", "")) > str(best.get("pod", "")):
                best = candidate
    return best


def _per_pod_limit_ratio(pod: PodInput, short_window: str) -> dict[str, Any]:
    cpu_points, cpu_duplicate, cpu_non_finite = _indexed_points(
        pod.get("cpu_short"), "cpu_short"
    )
    limit_points, limit_duplicate, limit_non_finite = _indexed_points(
        pod.get("cpu_limit"), "cpu_limit"
    )

    if not cpu_points:
        return {
            "status": "UNKNOWN",
            "window": short_window,
            "reason_code": "missing_cpu",
            "reason": "short-window CPU telemetry is missing",
        }
    if not limit_points:
        return {
            "status": "UNKNOWN",
            "window": short_window,
            "reason_code": "missing_limit",
            "reason": "historical CPU limit is missing",
        }
    if cpu_non_finite or limit_non_finite:
        return {
            "status": "UNKNOWN",
            "window": short_window,
            "reason_code": "non_finite_sample",
            "reason": "non-finite CPU or historical limit sample prevents deterministic ratio",
        }
    if cpu_duplicate or limit_duplicate:
        return {
            "status": "UNKNOWN",
            "window": short_window,
            "reason_code": "duplicate_timestamp",
            "reason": "duplicate timestamp values prevent deterministic CPU/limit join",
        }

    cpu_timestamps = set(cpu_points)
    limit_timestamps = set(limit_points)
    if cpu_timestamps != limit_timestamps:
        return {
            "status": "UNKNOWN",
            "window": short_window,
            "reason_code": "timestamp_misalignment",
            "reason": "CPU and historical limit timestamps are not exactly aligned",
        }

    candidates: list[dict[str, Any]] = []
    for timestamp in sorted(cpu_timestamps, key=_decimal):
        cpu = cpu_points[timestamp]
        limit = limit_points[timestamp]
        if _decimal(limit["value"]) <= 0:
            return {
                "status": "UNKNOWN",
                "window": short_window,
                "reason_code": "non_positive_limit",
                "reason": "historical CPU limit is not positive",
            }
        candidates.append(
            {
                "ratio": _ratio(cpu["value"], limit["value"]),
                "timestamp": timestamp,
                "query_keys": {
                    "numerator": cpu["query_key"],
                    "denominator": limit["query_key"],
                },
            }
        )

    best = candidates[0]
    for candidate in candidates[1:]:
        if _ratio_gt(candidate["ratio"], best["ratio"]):
            best = candidate

    return {
        "status": "VALID",
        "window": short_window,
        "max": best["ratio"],
        "max_timestamp": best["timestamp"],
        "query_keys": best["query_keys"],
        "points": len(candidates),
    }


def _selector_result(
    *,
    pod: PodInput,
    metric: str,
    value: str | Ratio,
    timestamp: str,
    window: str | None = None,
    query_key: str | None = None,
    query_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "VALID",
        "pod": pod["name"],
        "metric": metric,
        "value": value,
        "timestamp": timestamp,
        "coverage": _coverage_wire(pod),
        "sample_count": pod.get("sample_count"),
    }
    if window is not None:
        result["window"] = window
    if query_key is not None:
        result["query_key"] = query_key
    if query_keys is not None:
        result["query_keys"] = query_keys
    return result


def _max_cpu_usage_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[tuple[Decimal, str, PodInput, dict[str, str]]] = []
    for pod in pods:
        points = pod.get("cpu_short")
        if not points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        normalized = [_normalize_point(point, "cpu_short") for point in points]
        if any(not _finite(point["value"]) for point in normalized):
            return _unknown(
                f"non-finite CPU telemetry for pod {pod['name']}",
                reason_code="non_finite_sample",
            )
        for point in normalized:
            candidates.append((_decimal(point["value"]), str(pod["name"]), pod, point))

    _, _, pod, point = max(candidates, key=lambda item: (item[0], item[1]))
    return _selector_result(
        pod=pod,
        metric="cpu_usage_rate",
        value=point["value"],
        timestamp=point["timestamp"],
        window=short_window,
        query_key=point["query_key"],
    )


def _max_limit_ratio_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[dict[str, Any]] = []
    for pod in pods:
        cpu_points, cpu_duplicate, cpu_non_finite = _indexed_points(
            pod.get("cpu_short"), "cpu_short"
        )
        limit_points, limit_duplicate, limit_non_finite = _indexed_points(
            pod.get("cpu_limit"), "cpu_limit"
        )

        if not cpu_points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        if not limit_points:
            return _unknown(f"historical CPU limit missing for pod {pod['name']}")
        if cpu_non_finite or limit_non_finite:
            return _unknown(
                f"non-finite CPU or historical limit telemetry for pod {pod['name']}",
                reason_code="non_finite_sample",
            )
        if cpu_duplicate or limit_duplicate:
            return _unknown(
                "duplicate timestamp values prevent deterministic join "
                f"for pod {pod['name']}"
            )

        cpu_timestamps = set(cpu_points)
        limit_timestamps = set(limit_points)
        if cpu_timestamps != limit_timestamps:
            return _unknown(
                "timestamp alignment between CPU and historical limit "
                f"is incomplete for pod {pod['name']}"
            )

        for timestamp in sorted(cpu_timestamps, key=_decimal):
            cpu = cpu_points[timestamp]
            limit = limit_points[timestamp]
            if _decimal(limit["value"]) <= 0:
                return _unknown(f"historical CPU limit is not positive for pod {pod['name']}")
            candidates.append(
                {
                    "ratio": _ratio(cpu["value"], limit["value"]),
                    "timestamp": timestamp,
                    "pod": pod,
                    "query_keys": {
                        "numerator": cpu["query_key"],
                        "denominator": limit["query_key"],
                    },
                }
            )

    best = _max_ratio_candidate(candidates)
    return _selector_result(
        pod=best["pod"],
        metric="cpu_limit_ratio",
        value=best["ratio"],
        timestamp=best["timestamp"],
        window=short_window,
        query_keys=best["query_keys"],
    )


def _max_cost_rate_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[dict[str, Any]] = []
    for pod in pods:
        cpu_points, cpu_duplicate, cpu_non_finite = _indexed_points(
            pod.get("cpu_short"), "cpu_short"
        )
        request_points, request_duplicate, request_non_finite = _indexed_points(
            pod.get("request_rate"), "request_rate"
        )

        if not cpu_points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        if not request_points:
            return _unknown(f"request telemetry missing for pod {pod['name']}")
        if cpu_non_finite or request_non_finite:
            return _unknown(
                f"non-finite CPU or request telemetry for pod {pod['name']}",
                reason_code="non_finite_sample",
            )
        if cpu_duplicate or request_duplicate:
            return _unknown(
                "duplicate timestamp values prevent deterministic join "
                f"for pod {pod['name']}"
            )

        cpu_timestamps = set(cpu_points)
        request_timestamps = set(request_points)
        if cpu_timestamps != request_timestamps:
            return _unknown(
                "timestamp alignment between CPU and request rate is incomplete "
                f"for pod {pod['name']}"
            )

        for timestamp in sorted(cpu_timestamps, key=_decimal):
            cpu = cpu_points[timestamp]
            request = request_points[timestamp]
            if _decimal(request["value"]) <= 0:
                return _unknown(f"request-rate denominator is not positive for pod {pod['name']}")
            candidates.append(
                {
                    "ratio": _ratio(cpu["value"], request["value"]),
                    "timestamp": timestamp,
                    "pod": pod,
                    "query_keys": {
                        "numerator": cpu["query_key"],
                        "denominator": request["query_key"],
                    },
                }
            )

    best = _max_ratio_candidate(candidates)
    return _selector_result(
        pod=best["pod"],
        metric="cpu_cost_rate",
        value=best["ratio"],
        timestamp=best["timestamp"],
        window=short_window,
        query_keys=best["query_keys"],
    )


def build_report(
    *,
    pods: list[PodInput],
    short_window: str,
    long_window: str,
    acquisition: dict[str, Any] | None = None,
    queries: dict[str, Any] | None = None,
    live_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic per-pod CPU evidence without producing a sizing decision."""

    unknown_reasons: list[str] = []
    pod_reports: dict[str, Any] = {}

    if not pods:
        unknown_reasons.append("no pods were supplied")

    for pod in pods:
        name = str(pod["name"])
        short_summary = _series_summary(pod.get("cpu_short"), short_window, "cpu_short")
        long_summary = _series_summary(pod.get("cpu_long"), long_window, "cpu_long")

        if short_summary["status"] == "UNKNOWN":
            unknown_reasons.append(f"{name}: {short_summary['reason']}")
        if long_summary["status"] == "UNKNOWN":
            unknown_reasons.append(f"{name}: {long_summary['reason']}")

        pod_reports[name] = {
            "sample_count": pod.get("sample_count"),
            "coverage": _coverage_wire(pod),
            "restart_delta": pod.get("restart_delta", 0),
            "node": pod.get("node"),
            "owner": pod.get("owner"),
            "cpu_usage": {
                "short": short_summary,
                "long": long_summary,
            },
            "cpu_limit_ratio": _per_pod_limit_ratio(pod, short_window),
        }

    report: dict[str, Any] = {
        "status": "UNKNOWN" if unknown_reasons else "VALID",
        "windows": {"short": short_window, "long": long_window},
        "pods": pod_reports,
        "selectors": {
            "max_cpu_usage_pod": _max_cpu_usage_selector(pods, short_window),
            "max_cpu_limit_ratio_pod": _max_limit_ratio_selector(pods, short_window),
            "max_cpu_cost_rate_pod": _max_cost_rate_selector(pods, short_window),
        },
        "unknown_reasons": unknown_reasons,
    }

    if acquisition is not None:
        report["acquisition"] = acquisition
    if queries is not None:
        report["queries"] = queries
    if live_context is not None:
        report["live_context"] = live_context

    return report
