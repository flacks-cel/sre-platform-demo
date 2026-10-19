from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class WorkloadOwnershipInputError(ValueError):
    """Raised when historical ownership inputs violate the frozen contract."""


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise WorkloadOwnershipInputError(f"{field} must not be represented as float")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise WorkloadOwnershipInputError(f"{field} must be numeric") from exc
    else:
        raise WorkloadOwnershipInputError(f"{field} must be numeric")
    if not number.is_finite():
        raise WorkloadOwnershipInputError(f"{field} must be finite")
    return number


def _canonical_decimal(value: Any, *, field: str) -> str:
    number = _decimal(value, field=field)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _owner_sample_is_valid(raw_value: Any) -> bool:
    if not isinstance(raw_value, str):
        return False
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return False
    return value.is_finite() and value == Decimal(1)


def _samples_at(series: dict[str, Any], timestamp: str) -> list[dict[str, Any]]:
    samples = series.get("samples")
    if not isinstance(samples, list):
        raise WorkloadOwnershipInputError("normalized ownership series samples must be a list")
    return [
        sample
        for sample in samples
        if isinstance(sample, dict) and sample.get("timestamp") == timestamp
    ]


def _unknown(
    reason_code: str,
    reason: str,
    *,
    pod_identity: dict[str, str] | None = None,
    pod_owner: dict[str, str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_status": "UNKNOWN",
        "reason_code": reason_code,
        "reason": reason,
        "evidence_refs": list(evidence_refs or []),
    }
    if pod_identity is not None:
        result["pod_identity"] = pod_identity
    if pod_owner is not None:
        result["pod_owner"] = pod_owner
    return result


def _pod_observations_at(
    evidence: dict[str, Any],
    *,
    namespace: str,
    pod: str,
    timestamp: str,
) -> tuple[list[dict[str, str]], bool]:
    series_list = evidence.get("pod_owner_series")
    if not isinstance(series_list, list):
        raise WorkloadOwnershipInputError("evidence pod_owner_series must be a list")

    observations: list[dict[str, str]] = []
    invalid = False
    for series in series_list:
        if not isinstance(series, dict):
            raise WorkloadOwnershipInputError("normalized pod owner series must be an object")
        if series.get("namespace") != namespace or series.get("pod") != pod:
            continue
        samples = _samples_at(series, timestamp)
        if not samples:
            continue
        if len(samples) != 1:
            invalid = True
            continue
        sample = samples[0]
        if not _owner_sample_is_valid(sample.get("value")):
            invalid = True
            continue
        if series.get("owner_is_controller") != "true":
            invalid = True
            continue
        observations.append(
            {
                "uid": str(series["uid"]),
                "owner_kind": str(series["owner_kind"]),
                "owner_name": str(series["owner_name"]),
            }
        )
    return observations, invalid


def _replicaset_observations_at(
    evidence: dict[str, Any],
    *,
    namespace: str,
    replicaset: str,
    timestamp: str,
) -> tuple[list[dict[str, str]], bool]:
    series_list = evidence.get("replicaset_owner_series")
    if not isinstance(series_list, list):
        raise WorkloadOwnershipInputError("evidence replicaset_owner_series must be a list")

    observations: list[dict[str, str]] = []
    invalid = False
    for series in series_list:
        if not isinstance(series, dict):
            raise WorkloadOwnershipInputError(
                "normalized ReplicaSet owner series must be an object"
            )
        if series.get("namespace") != namespace or series.get("replicaset") != replicaset:
            continue
        samples = _samples_at(series, timestamp)
        if not samples:
            continue
        if len(samples) != 1:
            invalid = True
            continue
        sample = samples[0]
        if not _owner_sample_is_valid(sample.get("value")):
            invalid = True
            continue
        if series.get("owner_is_controller") != "true":
            invalid = True
            continue
        observations.append(
            {
                "owner_kind": str(series["owner_kind"]),
                "owner_name": str(series["owner_name"]),
            }
        )
    return observations, invalid


def _pod_owner_fact(
    *,
    kind: str,
    name: str,
    timestamp: str,
) -> dict[str, str]:
    return {
        "kind": kind,
        "name": name,
        "query_key": "pod_owner",
        "timestamp": timestamp,
    }


def _replicaset_owner_fact(
    *,
    kind: str,
    name: str,
    timestamp: str,
) -> dict[str, str]:
    return {
        "kind": kind,
        "name": name,
        "query_key": "replicaset_owner",
        "timestamp": timestamp,
    }


def _resolve_at_timestamp(
    evidence: dict[str, Any],
    *,
    namespace: str,
    pod: str,
    timestamp: str,
    target_name: str,
) -> dict[str, Any]:
    pod_ref = f"pods.{pod}.ownership.{timestamp}.pod_owner"
    rs_ref = f"pods.{pod}.ownership.{timestamp}.replicaset_owner"

    pod_observations, pod_invalid = _pod_observations_at(
        evidence,
        namespace=namespace,
        pod=pod,
        timestamp=timestamp,
    )
    if pod_invalid:
        return _unknown(
            "owner_metric_invalid",
            "Pod owner relationship sample is not a unique exact decimal 1",
        )
    if not pod_observations:
        return _unknown(
            "pod_owner_missing_at_timestamp",
            "Pod controller-owner telemetry is missing at the required timestamp",
        )

    uids = sorted({observation["uid"] for observation in pod_observations})
    if len(uids) != 1:
        return _unknown(
            "pod_identity_ambiguous_at_timestamp",
            "Multiple Pod UIDs are simultaneously plausible at the required timestamp",
        )

    uid = uids[0]
    owners = sorted(
        {
            (observation["owner_kind"], observation["owner_name"])
            for observation in pod_observations
            if observation["uid"] == uid
        }
    )
    if len(owners) != 1:
        return _unknown(
            "pod_controller_owner_ambiguous",
            "Pod has multiple controller-owner candidates at the required timestamp",
        )

    pod_owner_kind, pod_owner_name = owners[0]
    pod_identity = {"namespace": namespace, "name": pod, "uid": uid}
    pod_owner = _pod_owner_fact(
        kind=pod_owner_kind,
        name=pod_owner_name,
        timestamp=timestamp,
    )

    if pod_owner_kind != "ReplicaSet":
        return {
            "evidence_status": "VALID",
            "relation": "TARGET_DIFFERS",
            "pod_identity": pod_identity,
            "pod_owner": pod_owner,
            "evidence_refs": [pod_ref],
        }

    rs_observations, rs_invalid = _replicaset_observations_at(
        evidence,
        namespace=namespace,
        replicaset=pod_owner_name,
        timestamp=timestamp,
    )
    if rs_invalid:
        return _unknown(
            "owner_metric_invalid",
            "ReplicaSet owner relationship sample is not a unique exact decimal 1",
            pod_identity=pod_identity,
            pod_owner=pod_owner,
            evidence_refs=[pod_ref],
        )
    if not rs_observations:
        return _unknown(
            "replicaset_owner_missing_at_timestamp",
            "ReplicaSet controller-owner telemetry is missing at the required timestamp",
            pod_identity=pod_identity,
            pod_owner=pod_owner,
            evidence_refs=[pod_ref],
        )

    rs_owners = sorted(
        {
            (observation["owner_kind"], observation["owner_name"])
            for observation in rs_observations
        }
    )
    if len(rs_owners) != 1:
        return _unknown(
            "replicaset_controller_owner_ambiguous",
            "ReplicaSet has multiple controller-owner candidates at the required timestamp",
            pod_identity=pod_identity,
            pod_owner=pod_owner,
            evidence_refs=[pod_ref],
        )

    rs_owner_kind, rs_owner_name = rs_owners[0]
    replicaset_owner = _replicaset_owner_fact(
        kind=rs_owner_kind,
        name=rs_owner_name,
        timestamp=timestamp,
    )
    relation = (
        "TARGET_MATCH"
        if rs_owner_kind == "Deployment" and rs_owner_name == target_name
        else "TARGET_DIFFERS"
    )
    return {
        "evidence_status": "VALID",
        "relation": relation,
        "pod_identity": pod_identity,
        "pod_owner": pod_owner,
        "replicaset_owner": replicaset_owner,
        "evidence_refs": [pod_ref, rs_ref],
    }


def _validate_target(target_workload: dict[str, Any], *, namespace: str) -> dict[str, str]:
    if not isinstance(target_workload, dict):
        raise WorkloadOwnershipInputError("target workload must be an object")
    required = ("api_group", "kind", "namespace", "name")
    target: dict[str, str] = {}
    for field in required:
        value = target_workload.get(field)
        if not isinstance(value, str) or not value:
            raise WorkloadOwnershipInputError(f"target workload {field} must be non-empty")
        target[field] = value

    if target["api_group"] != "apps" or target["kind"] != "Deployment":
        raise WorkloadOwnershipInputError(
            "WORKLOAD-OWNERSHIP-001 supports only apps/Deployment targets"
        )
    if target["namespace"] != namespace:
        raise WorkloadOwnershipInputError(
            "target namespace must match ownership acquisition namespace"
        )
    return target


def _validate_context(evidence: dict[str, Any]) -> tuple[dict[str, str], Decimal, Decimal, Decimal]:
    if not isinstance(evidence, dict):
        raise WorkloadOwnershipInputError("ownership evidence must be an object")
    acquisition = evidence.get("acquisition")
    if not isinstance(acquisition, dict):
        raise WorkloadOwnershipInputError("ownership evidence is missing acquisition")

    namespace = acquisition.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise WorkloadOwnershipInputError("acquisition namespace must be non-empty")
    start_text = _canonical_decimal(acquisition.get("start"), field="start")
    end_text = _canonical_decimal(acquisition.get("end"), field="end")
    step_text = _canonical_decimal(acquisition.get("step"), field="step")
    start = _decimal(start_text, field="start")
    end = _decimal(end_text, field="end")
    step = _decimal(step_text, field="step")
    if step <= 0:
        raise WorkloadOwnershipInputError("acquisition step must be positive")
    if end < start:
        raise WorkloadOwnershipInputError("acquisition end must not be before start")
    return (
        {
            "namespace": namespace,
            "start": start_text,
            "end": end_text,
            "step": step_text,
        },
        start,
        end,
        step,
    )


def _required_timestamps(
    values: Any,
    *,
    start: Decimal,
    end: Decimal,
    step: Decimal,
) -> list[str]:
    if not isinstance(values, list):
        raise WorkloadOwnershipInputError("required timestamps for each pod must be a list")

    canonical: dict[Decimal, str] = {}
    for raw_timestamp in values:
        timestamp = _decimal(raw_timestamp, field="required timestamp")
        if timestamp < start or timestamp > end:
            raise WorkloadOwnershipInputError(
                f"required timestamp {raw_timestamp!r} is outside acquisition interval"
            )
        if (timestamp - start) % step != 0:
            raise WorkloadOwnershipInputError(
                f"required timestamp {raw_timestamp!r} is off the acquisition grid"
            )
        canonical[timestamp] = _canonical_decimal(
            timestamp,
            field="required timestamp",
        )
    return [canonical[timestamp] for timestamp in sorted(canonical)]


def build_ownership_report(
    *,
    evidence: dict[str, Any],
    target_workload: dict[str, Any],
    required_timestamps_by_pod: dict[str, list[str]],
) -> dict[str, Any]:
    """Resolve historical Pod→ReplicaSet→Deployment ownership at required timestamps."""

    context, start, end, step = _validate_context(evidence)
    target = _validate_target(target_workload, namespace=context["namespace"])
    if not isinstance(required_timestamps_by_pod, dict):
        raise WorkloadOwnershipInputError("required_timestamps_by_pod must be an object")

    queries = evidence.get("queries")
    if not isinstance(queries, dict):
        raise WorkloadOwnershipInputError("ownership evidence is missing query provenance")

    pods: dict[str, Any] = {}
    for pod in sorted(required_timestamps_by_pod):
        if not isinstance(pod, str) or not pod:
            raise WorkloadOwnershipInputError("required pod names must be non-empty strings")
        required = _required_timestamps(
            required_timestamps_by_pod[pod],
            start=start,
            end=end,
            step=step,
        )
        ownership = {
            timestamp: _resolve_at_timestamp(
                evidence,
                namespace=context["namespace"],
                pod=pod,
                timestamp=timestamp,
                target_name=target["name"],
            )
            for timestamp in required
        }
        pods[pod] = {
            "required_timestamps": required,
            "ownership": ownership,
        }

    return {
        "ownership_id": "WORKLOAD-OWNERSHIP-001",
        "target_workload": target,
        "historical_context": {
            "start": context["start"],
            "end": context["end"],
            "step": context["step"],
        },
        "provenance": {
            "pod_identity_basis": "NAMESPACE_NAME_UID",
            "replicaset_identity_basis": "NAMESPACE_NAME",
            "replicaset_uid_available": False,
            "owner_api_version_available": False,
        },
        "queries": {
            "pod_owner": queries["pod_owner"],
            "replicaset_owner": queries["replicaset_owner"],
        },
        "pods": pods,
    }
