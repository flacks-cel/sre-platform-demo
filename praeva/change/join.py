from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

ABSENT = "ABSENT"
CALLER_ASSERTED = "CALLER_ASSERTED"


class ChangeJoinInputError(ValueError):
    """Raised when CHANGE-JOIN-001 receives structurally inconsistent input."""


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ChangeJoinInputError(f"{field} must be exact decimal text or an integer")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ChangeJoinInputError(f"{field} must be numeric") from exc
    else:
        raise ChangeJoinInputError(f"{field} must be numeric")

    if not result.is_finite():
        raise ChangeJoinInputError(f"{field} must be finite")
    return result


def _canonical_decimal(value: Any, *, field: str) -> str:
    decimal_value = _decimal(value, field=field)
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _millicores_from_cores(value: Any, *, field: str) -> str:
    millicores = _decimal(value, field=field) * Decimal(1000)
    return _canonical_decimal(millicores, field=field)


def _declared_limit_text(value: Any, *, field: str) -> str:
    if value == ABSENT:
        return ABSENT
    return _canonical_decimal(value, field=field)


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChangeJoinInputError(f"{field} must be an object")
    return value


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ChangeJoinInputError(f"{field} must be a non-empty string")
    return value


def _validate_inputs(
    *,
    change: dict,
    verify_report: dict,
    identity_assertion: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    if identity_assertion != CALLER_ASSERTED:
        raise ChangeJoinInputError("identity_assertion must be CALLER_ASSERTED")

    change_map = _require_mapping(change, field="change")
    report = _require_mapping(verify_report, field="verify_report")
    workload = _require_mapping(change_map.get("workload_identity"), field="workload_identity")
    container = _require_mapping(change_map.get("container"), field="container")
    acquisition = _require_mapping(report.get("acquisition"), field="acquisition")
    queries = _require_mapping(report.get("queries"), field="queries")
    windows = _require_mapping(report.get("windows"), field="windows")
    pods = _require_mapping(report.get("pods"), field="pods")

    namespace = _require_text(workload.get("namespace"), field="workload_identity.namespace")
    _require_text(workload.get("name"), field="workload_identity.name")
    _require_text(workload.get("group"), field="workload_identity.group")
    _require_text(workload.get("kind"), field="workload_identity.kind")

    container_name = _require_text(container.get("name"), field="container.name")
    container_space = _require_text(container.get("space"), field="container.space")
    if container_space != "containers":
        raise ChangeJoinInputError("CHANGE-JOIN-001 supports only container.space=containers")

    verify_namespace = _require_text(
        acquisition.get("namespace"),
        field="acquisition.namespace",
    )
    verify_container = _require_text(
        acquisition.get("container"),
        field="acquisition.container",
    )
    pod_selector = _require_mapping(
        acquisition.get("pod_selector"),
        field="acquisition.pod_selector",
    )
    _require_text(pod_selector.get("type"), field="acquisition.pod_selector.type")
    _require_text(pod_selector.get("value"), field="acquisition.pod_selector.value")

    if namespace != verify_namespace:
        raise ChangeJoinInputError(
            "Change Input namespace does not match Verify acquisition namespace"
        )
    if container_name != verify_container:
        raise ChangeJoinInputError(
            "Change Input container does not match Verify acquisition container"
        )

    for key in ("start", "end", "step"):
        value = acquisition.get(key)
        if not isinstance(value, str):
            raise ChangeJoinInputError(f"acquisition.{key} must be exact decimal text")
        _decimal(value, field=f"acquisition.{key}")

    short_window = _require_text(windows.get("short"), field="windows.short")
    long_window = _require_text(windows.get("long"), field="windows.long")
    for query_key, expected_window in (
        ("cpu_short", short_window),
        ("cpu_long", long_window),
    ):
        query = _require_mapping(queries.get(query_key), field=f"queries.{query_key}")
        _require_text(query.get("promql"), field=f"queries.{query_key}.promql")
        if query.get("rate_window") != expected_window:
            raise ChangeJoinInputError(
                f"queries.{query_key}.rate_window does not match report window"
            )

    limit_query = queries.get("cpu_limit")
    if limit_query is not None:
        limit_query_map = _require_mapping(limit_query, field="queries.cpu_limit")
        _require_text(limit_query_map.get("promql"), field="queries.cpu_limit.promql")

    _declared_limit_text(
        change_map.get("current_declared_cpu_limit"),
        field="current_declared_cpu_limit",
    )
    _declared_limit_text(
        change_map.get("proposed_declared_cpu_limit"),
        field="proposed_declared_cpu_limit",
    )

    return workload, container, acquisition, queries, pods


def _observed_cpu(summary: Any, *, rate_window: str) -> dict[str, Any]:
    summary_map = _require_mapping(summary, field="cpu usage summary")
    status = summary_map.get("status")

    if status == "VALID":
        value = summary_map.get("max")
        timestamp = summary_map.get("max_timestamp")
        query_key = summary_map.get("query_key")
        if not isinstance(value, str):
            raise ChangeJoinInputError("VALID CPU summary max must be exact decimal text")
        if not isinstance(timestamp, str):
            raise ChangeJoinInputError("VALID CPU summary timestamp must be exact decimal text")
        if not isinstance(query_key, str) or not query_key:
            raise ChangeJoinInputError("VALID CPU summary query_key is required")
        _decimal(value, field="CPU summary max")
        _decimal(timestamp, field="CPU summary timestamp")
        return {
            "status": "VALID",
            "value_millicores": _millicores_from_cores(value, field="CPU summary max"),
            "timestamp": timestamp,
            "query_key": query_key,
            "rate_window": rate_window,
        }

    if status == "UNKNOWN":
        result: dict[str, Any] = {"status": "UNKNOWN", "rate_window": rate_window}
        if "reason_code" in summary_map:
            result["reason_code"] = summary_map["reason_code"]
        if "reason" in summary_map:
            result["reason"] = summary_map["reason"]
        return result

    raise ChangeJoinInputError("CPU summary status must be VALID or UNKNOWN")


def _comparison(*, observed_cpu: dict[str, Any], proposed_limit: Any) -> dict[str, Any]:
    proposed_text = _declared_limit_text(
        proposed_limit,
        field="proposed_declared_cpu_limit",
    )

    if proposed_text == ABSENT:
        return {
            "status": "UNDEFINED",
            "proposed_declared_cpu_limit_millicores": ABSENT,
            "reason_code": "proposed_limit_absent",
            "reason": "proposed manifest does not declare a CPU limit",
        }

    if observed_cpu["status"] == "UNKNOWN":
        result: dict[str, Any] = {
            "status": "UNKNOWN",
            "proposed_declared_cpu_limit_millicores": proposed_text,
        }
        if "reason_code" in observed_cpu:
            result["reason_code"] = observed_cpu["reason_code"]
        if "reason" in observed_cpu:
            result["reason"] = observed_cpu["reason"]
        return result

    observed = _decimal(
        observed_cpu["value_millicores"],
        field="observed_cpu.value_millicores",
    )
    proposed = _decimal(proposed_text, field="proposed_declared_cpu_limit")
    return {
        "status": "VALID",
        "proposed_declared_cpu_limit_millicores": proposed_text,
        "delta_millicores": _canonical_decimal(
            proposed - observed,
            field="comparison.delta_millicores",
        ),
    }


def _effective_limit_witness(pod_report: dict[str, Any]) -> dict[str, Any]:
    ratio = _require_mapping(pod_report.get("cpu_limit_ratio"), field="cpu_limit_ratio")
    status = ratio.get("status")

    if status == "VALID":
        operands = _require_mapping(ratio.get("max"), field="cpu_limit_ratio.max")
        denominator = operands.get("denominator")
        if not isinstance(denominator, str):
            raise ChangeJoinInputError("cpu_limit_ratio denominator must be exact decimal text")
        timestamp = ratio.get("max_timestamp")
        if not isinstance(timestamp, str):
            raise ChangeJoinInputError(
                "cpu_limit_ratio max_timestamp must be exact decimal text"
            )
        query_keys = _require_mapping(
            ratio.get("query_keys"),
            field="cpu_limit_ratio.query_keys",
        )
        query_key = query_keys.get("denominator")
        if not isinstance(query_key, str) or not query_key:
            raise ChangeJoinInputError("cpu_limit_ratio denominator query_key is required")

        return {
            "status": "VALID",
            "value_millicores": _millicores_from_cores(
                denominator,
                field="cpu_limit_ratio denominator",
            ),
            "timestamp": timestamp,
            "query_key": query_key,
        }

    if status == "UNKNOWN":
        result: dict[str, Any] = {"status": "UNKNOWN"}
        if "reason_code" in ratio:
            result["reason_code"] = ratio["reason_code"]
        if "reason" in ratio:
            result["reason"] = ratio["reason"]
        return result

    raise ChangeJoinInputError("cpu_limit_ratio status must be VALID or UNKNOWN")


def _declared_effective_relation(
    *,
    current_declared_limit: Any,
    witness: dict[str, Any],
) -> dict[str, Any]:
    current_text = _declared_limit_text(
        current_declared_limit,
        field="current_declared_cpu_limit",
    )

    if witness["status"] == "UNKNOWN":
        result: dict[str, Any] = {
            "status": "UNKNOWN",
            "current_declared_cpu_limit_millicores": current_text,
        }
        if "reason_code" in witness:
            result["reason_code"] = witness["reason_code"]
        if "reason" in witness:
            result["reason"] = witness["reason"]
        return result

    effective_text = witness["value_millicores"]
    if current_text == ABSENT:
        relation = "DECLARED_ABSENT_EFFECTIVE_PRESENT"
    elif _decimal(current_text, field="current_declared_cpu_limit") == _decimal(
        effective_text,
        field="effective_observed_cpu_limit",
    ):
        relation = "MATCH"
    else:
        relation = "DIFFERS"

    return {
        "status": "VALID",
        "relation": relation,
        "current_declared_cpu_limit_millicores": current_text,
        "effective_observed_cpu_limit_millicores": effective_text,
    }


def _joined_pod(
    *,
    pod_report: Any,
    windows: dict[str, Any],
    current_declared_limit: Any,
    proposed_declared_limit: Any,
) -> dict[str, Any]:
    pod = _require_mapping(pod_report, field="pod report")
    usage = _require_mapping(pod.get("cpu_usage"), field="pod.cpu_usage")

    joined_windows: dict[str, Any] = {}
    for window_name in ("short", "long"):
        rate_window = windows[window_name]
        observed = _observed_cpu(usage.get(window_name), rate_window=rate_window)
        joined_windows[window_name] = {
            "observed_cpu": observed,
            "comparison": _comparison(
                observed_cpu=observed,
                proposed_limit=proposed_declared_limit,
            ),
        }

    witness = _effective_limit_witness(pod)
    relation = _declared_effective_relation(
        current_declared_limit=current_declared_limit,
        witness=witness,
    )

    return {
        "metadata": {
            "coverage": deepcopy(pod.get("coverage")),
            "sample_count": pod.get("sample_count"),
            "restart_delta": pod.get("restart_delta", 0),
            "node": pod.get("node"),
            "owner": pod.get("owner"),
        },
        "windows": joined_windows,
        "effective_limit_witness": witness,
        "current_declared_effective_relation": relation,
    }


def join_change_evidence(
    *,
    change: dict,
    verify_report: dict,
    identity_assertion: str,
) -> dict:
    """Join declared CPU change facts with exact historical Verify evidence."""

    workload, _container, acquisition, queries, pods = _validate_inputs(
        change=change,
        verify_report=verify_report,
        identity_assertion=identity_assertion,
    )
    windows = verify_report["windows"]

    joined_pods = {
        pod_name: _joined_pod(
            pod_report=pods[pod_name],
            windows=windows,
            current_declared_limit=change["current_declared_cpu_limit"],
            proposed_declared_limit=change["proposed_declared_cpu_limit"],
        )
        for pod_name in sorted(pods)
    }

    return {
        "join_id": "CHANGE-JOIN-001",
        "identity_assertion": {
            "status": CALLER_ASSERTED,
            "workload_to_pod_selector_relation": "UNVERIFIED",
            "change_workload": deepcopy(workload),
            "verify_scope": {
                "namespace": acquisition["namespace"],
                "pod_selector": deepcopy(acquisition["pod_selector"]),
                "container": acquisition["container"],
            },
        },
        "change_facts": {
            "current_declared_cpu_limit": change["current_declared_cpu_limit"],
            "proposed_declared_cpu_limit": change["proposed_declared_cpu_limit"],
            "direction": change.get("direction"),
            "change_ratio": deepcopy(change.get("change_ratio")),
            "current_declared_cpu_request": change.get("current_declared_cpu_request"),
            "proposed_declared_cpu_request": change.get("proposed_declared_cpu_request"),
        },
        "historical_context": {
            "start": acquisition["start"],
            "end": acquisition["end"],
            "step": acquisition["step"],
            "windows": deepcopy(windows),
            "application_version_relation": "UNVERIFIED",
        },
        "queries": deepcopy(queries),
        "pods": joined_pods,
    }
