import math
from typing import Any


class RuleInputError(ValueError):
    """Raised when RULE-001 policy input is invalid."""


def _validate_ceiling_ratio(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuleInputError("ceiling_ratio must be a finite positive number")

    ratio = float(value)
    if not math.isfinite(ratio) or ratio <= 0:
        raise RuleInputError("ceiling_ratio must be a finite positive number")
    return ratio


def _pod_metadata(pod_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "coverage": pod_report.get("coverage"),
        "sample_count": pod_report.get("sample_count"),
        "restart_delta": pod_report.get("restart_delta", 0),
    }


def _evaluated_pod(name: str, pod_report: dict[str, Any]) -> dict[str, Any]:
    ratio = pod_report["cpu_limit_ratio"]
    return {
        "pod": name,
        "ratio": ratio["max"],
        "timestamp": ratio["max_timestamp"],
        "window": ratio["window"],
        **_pod_metadata(pod_report),
    }


def _excluded_pod(name: str, pod_report: dict[str, Any]) -> dict[str, Any]:
    ratio = pod_report["cpu_limit_ratio"]
    return {
        "pod": name,
        "reason_code": ratio["reason_code"],
        "reason": ratio["reason"],
        **_pod_metadata(pod_report),
    }


def _base_result(
    *,
    report: dict[str, Any],
    ceiling_ratio: float,
    evaluated_pods: list[dict[str, Any]],
    excluded_pods: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "rule_id": "RULE-001",
        "ceiling_ratio": ceiling_ratio,
        "selectors": report.get("selectors", {}),
        "evaluated_pods": evaluated_pods,
        "excluded_pods": excluded_pods,
        "witness": None,
    }


def evaluate_rule(*, report: dict, ceiling_ratio: float) -> dict:
    """Evaluate the pre-registered RULE-001 predicate from Verify evidence only."""

    ceiling = _validate_ceiling_ratio(ceiling_ratio)

    cpu_observed: list[tuple[str, dict[str, Any]]] = []
    for name, pod_report in sorted(report.get("pods", {}).items()):
        short_cpu = pod_report.get("cpu_usage", {}).get("short", {})
        if short_cpu.get("status") == "VALID":
            cpu_observed.append((name, pod_report))

    evaluated_pods: list[dict[str, Any]] = []
    excluded_pods: list[dict[str, Any]] = []
    for name, pod_report in cpu_observed:
        ratio = pod_report.get("cpu_limit_ratio", {})
        if ratio.get("status") == "VALID":
            evaluated_pods.append(_evaluated_pod(name, pod_report))
        else:
            excluded_pods.append(_excluded_pod(name, pod_report))

    result = _base_result(
        report=report,
        ceiling_ratio=ceiling,
        evaluated_pods=evaluated_pods,
        excluded_pods=excluded_pods,
    )

    if not cpu_observed:
        result.update(
            conclusion="UNKNOWN",
            reason_code="no_usable_short_cpu",
        )
        return result

    exceedance_candidates = [
        pod for pod in evaluated_pods if float(pod["ratio"]) > ceiling
    ]
    if exceedance_candidates:
        witness = max(
            exceedance_candidates,
            key=lambda pod: (float(pod["ratio"]), str(pod["pod"])),
        )
        result.update(
            conclusion="EXCEEDS_CEILING",
            witness={
                "pod": witness["pod"],
                "ratio": witness["ratio"],
                "timestamp": witness["timestamp"],
                "window": witness["window"],
            },
        )
        return result

    if not evaluated_pods:
        result.update(
            conclusion="UNKNOWN",
            reason_code="no_complete_cpu_limit_ratio",
        )
        return result

    if excluded_pods:
        result.update(
            conclusion="UNKNOWN",
            reason_code="incomplete_cpu_limit_ratio",
        )
        return result

    result.update(conclusion="WITHIN_CEILING")
    return result
