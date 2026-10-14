from __future__ import annotations

from typing import Any


Status = str
Point = dict[str, float | int]
PodInput = dict[str, Any]


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "reason": reason}


def _indexed_points(points: list[Point] | None) -> tuple[dict[float | int, float], bool]:
    if not points:
        return {}, False

    indexed: dict[float | int, float] = {}
    duplicate = False
    for point in points:
        timestamp = point["timestamp"]
        if timestamp in indexed:
            duplicate = True
        indexed[timestamp] = float(point["value"])
    return indexed, duplicate


def _series_summary(points: list[Point] | None, window: str) -> dict[str, Any]:
    if not points:
        return {
            "status": "UNKNOWN",
            "window": window,
            "reason": "series is missing or empty",
        }

    maximum = max(points, key=lambda item: float(item["value"]))
    values = [float(item["value"]) for item in points]
    return {
        "status": "VALID",
        "window": window,
        "max": float(maximum["value"]),
        "max_timestamp": maximum["timestamp"],
        "points": len(points),
        "min": min(values),
    }


def _selector_result(
    *,
    pod: PodInput,
    metric: str,
    value: float,
    timestamp: float | int,
    window: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "VALID",
        "pod": pod["name"],
        "metric": metric,
        "value": value,
        "timestamp": timestamp,
        "coverage": pod.get("coverage"),
        "sample_count": pod.get("sample_count"),
    }
    if window is not None:
        result["window"] = window
    return result


def _max_cpu_usage_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[tuple[float, float | int, PodInput]] = []
    for pod in pods:
        points = pod.get("cpu_short")
        if not points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        for point in points:
            candidates.append((float(point["value"]), point["timestamp"], pod))

    value, timestamp, pod = max(candidates, key=lambda item: (item[0], str(item[2]["name"])))
    return _selector_result(
        pod=pod,
        metric="cpu_usage_rate",
        value=value,
        timestamp=timestamp,
        window=short_window,
    )


def _max_limit_ratio_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[tuple[float, float | int, PodInput]] = []
    for pod in pods:
        cpu_points, cpu_duplicate = _indexed_points(pod.get("cpu_short"))
        limit_points, limit_duplicate = _indexed_points(pod.get("cpu_limit"))

        if not cpu_points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        if not limit_points:
            return _unknown(f"historical CPU limit missing for pod {pod['name']}")
        if cpu_duplicate or limit_duplicate:
            return _unknown(f"duplicate timestamp values prevent deterministic join for pod {pod['name']}")

        cpu_timestamps = set(cpu_points)
        limit_timestamps = set(limit_points)
        if cpu_timestamps != limit_timestamps:
            return _unknown(
                f"timestamp alignment between CPU and historical limit is incomplete for pod {pod['name']}"
            )

        for timestamp in sorted(cpu_timestamps):
            limit = limit_points[timestamp]
            if limit <= 0:
                return _unknown(f"historical CPU limit is not positive for pod {pod['name']}")
            candidates.append((cpu_points[timestamp] / limit, timestamp, pod))

    value, timestamp, pod = max(candidates, key=lambda item: (item[0], str(item[2]["name"])))
    return _selector_result(
        pod=pod,
        metric="cpu_limit_ratio",
        value=value,
        timestamp=timestamp,
        window=short_window,
    )


def _max_cost_rate_selector(pods: list[PodInput], short_window: str) -> dict[str, Any]:
    if not pods:
        return _unknown("no pods were supplied")

    candidates: list[tuple[float, float | int, PodInput]] = []
    for pod in pods:
        cpu_points, cpu_duplicate = _indexed_points(pod.get("cpu_short"))
        request_points, request_duplicate = _indexed_points(pod.get("request_rate"))

        if not cpu_points:
            return _unknown(f"CPU telemetry missing for pod {pod['name']}")
        if not request_points:
            return _unknown(f"request telemetry missing for pod {pod['name']}")
        if cpu_duplicate or request_duplicate:
            return _unknown(f"duplicate timestamp values prevent deterministic join for pod {pod['name']}")

        cpu_timestamps = set(cpu_points)
        request_timestamps = set(request_points)
        if cpu_timestamps != request_timestamps:
            return _unknown(
                f"timestamp alignment between CPU and request rate is incomplete for pod {pod['name']}"
            )

        for timestamp in sorted(cpu_timestamps):
            request_rate = request_points[timestamp]
            if request_rate <= 0:
                return _unknown(f"request-rate denominator is not positive for pod {pod['name']}")
            candidates.append((cpu_points[timestamp] / request_rate, timestamp, pod))

    value, timestamp, pod = max(candidates, key=lambda item: (item[0], str(item[2]["name"])))
    return _selector_result(
        pod=pod,
        metric="cpu_cost_rate",
        value=value,
        timestamp=timestamp,
        window=short_window,
    )


def build_report(
    *,
    pods: list[PodInput],
    short_window: str,
    long_window: str,
    live_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic per-pod CPU evidence without producing a sizing decision."""

    unknown_reasons: list[str] = []
    pod_reports: dict[str, Any] = {}

    if not pods:
        unknown_reasons.append("no pods were supplied")

    for pod in pods:
        name = str(pod["name"])
        short_summary = _series_summary(pod.get("cpu_short"), short_window)
        long_summary = _series_summary(pod.get("cpu_long"), long_window)

        if short_summary["status"] == "UNKNOWN":
            unknown_reasons.append(f"{name}: short-window CPU telemetry is missing")
        if long_summary["status"] == "UNKNOWN":
            unknown_reasons.append(f"{name}: long-window CPU telemetry is missing")

        pod_reports[name] = {
            "sample_count": pod.get("sample_count"),
            "coverage": pod.get("coverage"),
            "restart_delta": pod.get("restart_delta", 0),
            "node": pod.get("node"),
            "owner": pod.get("owner"),
            "cpu_usage": {
                "short": short_summary,
                "long": long_summary,
            },
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

    if live_context is not None:
        report["live_context"] = live_context

    return report
