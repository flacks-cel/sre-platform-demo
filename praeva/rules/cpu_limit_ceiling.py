from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class RuleInputError(ValueError):
    """Raised when RULE-001 policy input is invalid."""


def _validate_ceiling_ratio(value: Any) -> tuple[Decimal, str]:
    if isinstance(value, bool) or isinstance(value, float):
        raise RuleInputError("ceiling_ratio must be exact decimal text or an integer")

    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise RuleInputError("ceiling_ratio must be exact decimal text or an integer")

    try:
        ratio = Decimal(text)
    except InvalidOperation as exc:
        raise RuleInputError("ceiling_ratio must be a finite positive decimal") from exc

    if not ratio.is_finite() or ratio <= 0:
        raise RuleInputError("ceiling_ratio must be a finite positive decimal")
    return ratio, text


def _ratio_parts(value: Any) -> tuple[Decimal, Decimal]:
    if not isinstance(value, dict):
        raise RuleInputError("cpu_limit_ratio must use exact numerator/denominator operands")
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not isinstance(numerator, str) or not isinstance(denominator, str):
        raise RuleInputError("cpu_limit_ratio operands must be decimal strings")
    try:
        numerator_value = Decimal(numerator)
        denominator_value = Decimal(denominator)
    except InvalidOperation as exc:
        raise RuleInputError("cpu_limit_ratio operands must be numeric") from exc
    if not numerator_value.is_finite() or not denominator_value.is_finite():
        raise RuleInputError("cpu_limit_ratio operands must be finite")
    if denominator_value <= 0:
        raise RuleInputError("cpu_limit_ratio denominator must be positive")
    return numerator_value, denominator_value


def _ratio_exceeds(value: dict[str, str], ceiling: Decimal) -> bool:
    numerator, denominator = _ratio_parts(value)
    return numerator > denominator * ceiling


def _ratio_gt(left: dict[str, str], right: dict[str, str]) -> bool:
    left_num, left_den = _ratio_parts(left)
    right_num, right_den = _ratio_parts(right)
    return left_num * right_den > right_num * left_den


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
    ceiling_ratio: str,
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


def _max_ratio_pod(pods: list[dict[str, Any]]) -> dict[str, Any]:
    best = pods[0]
    for pod in pods[1:]:
        if _ratio_gt(pod["ratio"], best["ratio"]):
            best = pod
        elif not _ratio_gt(best["ratio"], pod["ratio"]):
            if str(pod["pod"]) > str(best["pod"]):
                best = pod
    return best


def evaluate_rule(*, report: dict, ceiling_ratio: str | int) -> dict:
    """Evaluate the pre-registered RULE-001 predicate from Verify evidence only."""

    ceiling, ceiling_text = _validate_ceiling_ratio(ceiling_ratio)

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
        ceiling_ratio=ceiling_text,
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
        pod for pod in evaluated_pods if _ratio_exceeds(pod["ratio"], ceiling)
    ]
    if exceedance_candidates:
        witness = _max_ratio_pod(exceedance_candidates)
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
