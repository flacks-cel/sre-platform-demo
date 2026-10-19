from __future__ import annotations

import importlib
import json
from decimal import Decimal
from typing import Any

import pytest

START = "0"
END = "30"
STEP = "15"
TARGET = {
    "api_group": "apps",
    "kind": "Deployment",
    "namespace": "app",
    "name": "jobs-api",
}


def _pod_owner_series(
    *,
    pod: str = "jobs-api-abc",
    uid: str = "pod-uid-a",
    owner_kind: str = "ReplicaSet",
    owner_name: str = "jobs-api-rs-a",
    values: list[tuple[str, str]] | None = None,
    extra_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    metric = {
        "namespace": "app",
        "pod": pod,
        "uid": uid,
        "owner_kind": owner_kind,
        "owner_name": owner_name,
        "owner_is_controller": "true",
    }
    if extra_labels:
        metric.update(extra_labels)
    return {
        "metric": metric,
        "values": [list(point) for point in (values or [("0", "1"), ("15", "1"), ("30", "1")])],
    }


def _replicaset_owner_series(
    *,
    replicaset: str = "jobs-api-rs-a",
    owner_kind: str = "Deployment",
    owner_name: str = "jobs-api",
    values: list[tuple[str, str]] | None = None,
    extra_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    metric = {
        "namespace": "app",
        "replicaset": replicaset,
        "owner_kind": owner_kind,
        "owner_name": owner_name,
        "owner_is_controller": "true",
    }
    if extra_labels:
        metric.update(extra_labels)
    return {
        "metric": metric,
        "values": [list(point) for point in (values or [("0", "1"), ("15", "1"), ("30", "1")])],
    }


def _matrix(series: list[dict[str, Any]], *, result_type: str = "matrix") -> dict[str, Any]:
    return {
        "status": "success",
        "data": {"resultType": result_type, "result": series},
    }


def _transport(
    *,
    pod_series: list[dict[str, Any]] | None = None,
    replicaset_series: list[dict[str, Any]] | None = None,
    result_type: str = "matrix",
    calls: list[str] | None = None,
    failure: Exception | None = None,
):
    pods = [_pod_owner_series()] if pod_series is None else pod_series
    replicasets = (
        [_replicaset_owner_series()] if replicaset_series is None else replicaset_series
    )

    def query_range(**kwargs: Any) -> dict[str, Any]:
        if failure is not None:
            raise failure
        query = kwargs["query"]
        if calls is not None:
            calls.append(query)
        if "kube_pod_owner" in query:
            return _matrix(pods, result_type=result_type)
        if "kube_replicaset_owner" in query:
            return _matrix(replicasets, result_type=result_type)
        raise AssertionError(f"unexpected query: {query}")

    return query_range


def _collect():
    return importlib.import_module(
        "praeva.ownership.prometheus_adapter"
    ).collect_ownership_evidence


def _build():
    return importlib.import_module("praeva.ownership.historical").build_ownership_report


def _evidence(*, query_range=None, namespace: str = "app") -> dict[str, Any]:
    collect = _collect()
    return collect(
        prometheus_url="http://prometheus.test",
        namespace=namespace,
        start=START,
        end=END,
        step=STEP,
        query_range=query_range or _transport(),
    )


def _report(
    *,
    query_range=None,
    required: dict[str, list[str]] | None = None,
    target: dict[str, str] | None = None,
    namespace: str = "app",
) -> dict[str, Any]:
    evidence = _evidence(query_range=query_range, namespace=namespace)
    build = _build()
    return build(
        evidence=evidence,
        target_workload=target or TARGET,
        required_timestamps_by_pod=required or {"jobs-api-abc": ["15"]},
    )


def _assert_no_float(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError(f"float found: {value!r}")
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_float(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_float(nested)


def test_matching_chain_is_valid_target_match() -> None:
    report = _report()
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert report["ownership_id"] == "WORKLOAD-OWNERSHIP-001"
    assert fact["evidence_status"] == "VALID"
    assert fact["relation"] == "TARGET_MATCH"
    assert fact["pod_identity"]["uid"] == "pod-uid-a"
    assert fact["pod_owner"]["kind"] == "ReplicaSet"
    assert fact["replicaset_owner"]["kind"] == "Deployment"
    assert fact["evidence_refs"] == [
        "pods.jobs-api-abc.ownership.15.pod_owner",
        "pods.jobs-api-abc.ownership.15.replicaset_owner",
    ]


def test_valid_chain_to_other_deployment_is_target_differs() -> None:
    report = _report(
        query_range=_transport(
            replicaset_series=[_replicaset_owner_series(owner_name="other-api")]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "VALID"
    assert fact["relation"] == "TARGET_DIFFERS"
    assert fact["replicaset_owner"]["name"] == "other-api"


def test_non_replicaset_pod_controller_is_valid_contradiction() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[
                _pod_owner_series(owner_kind="StatefulSet", owner_name="jobs-api")
            ],
            replicaset_series=[],
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "VALID"
    assert fact["relation"] == "TARGET_DIFFERS"
    assert fact["pod_owner"]["kind"] == "StatefulSet"
    assert "replicaset_owner" not in fact


def test_non_deployment_replicaset_controller_is_valid_contradiction() -> None:
    report = _report(
        query_range=_transport(
            replicaset_series=[
                _replicaset_owner_series(owner_kind="CustomController", owner_name="jobs-api")
            ]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "VALID"
    assert fact["relation"] == "TARGET_DIFFERS"
    assert fact["replicaset_owner"]["kind"] == "CustomController"


def test_missing_pod_owner_at_required_timestamp_is_unknown() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[_pod_owner_series(values=[("0", "1"), ("30", "1")])]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "pod_owner_missing_at_timestamp"
    assert "relation" not in fact


def test_multiple_pod_uids_at_same_timestamp_are_unknown() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[
                _pod_owner_series(uid="pod-uid-a"),
                _pod_owner_series(uid="pod-uid-b"),
            ]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "pod_identity_ambiguous_at_timestamp"


def test_multiple_controller_owners_for_one_pod_uid_are_unknown() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[
                _pod_owner_series(uid="pod-uid-a", owner_name="jobs-api-rs-a"),
                _pod_owner_series(uid="pod-uid-a", owner_name="jobs-api-rs-b"),
            ]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "pod_controller_owner_ambiguous"


def test_missing_replicaset_owner_at_required_timestamp_is_unknown() -> None:
    report = _report(query_range=_transport(replicaset_series=[]))
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "replicaset_owner_missing_at_timestamp"
    assert fact["evidence_refs"] == ["pods.jobs-api-abc.ownership.15.pod_owner"]


def test_multiple_replicaset_controller_owners_are_unknown() -> None:
    report = _report(
        query_range=_transport(
            replicaset_series=[
                _replicaset_owner_series(owner_name="jobs-api"),
                _replicaset_owner_series(owner_name="other-api"),
            ]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "replicaset_controller_owner_ambiguous"


def test_owner_metric_value_must_be_exact_decimal_one() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[_pod_owner_series(values=[("15", "0")])]
        )
    )
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert fact["evidence_status"] == "UNKNOWN"
    assert fact["reason_code"] == "owner_metric_invalid"


def test_pod_name_reuse_preserves_distinct_uids_across_timestamps() -> None:
    report = _report(
        query_range=_transport(
            pod_series=[
                _pod_owner_series(uid="pod-uid-a", values=[("0", "1")]),
                _pod_owner_series(uid="pod-uid-b", values=[("30", "1")]),
            ]
        ),
        required={"jobs-api-abc": ["30", "0"]},
    )
    pod = report["pods"]["jobs-api-abc"]

    assert pod["required_timestamps"] == ["0", "30"]
    assert pod["ownership"]["0"]["pod_identity"]["uid"] == "pod-uid-a"
    assert pod["ownership"]["30"]["pod_identity"]["uid"] == "pod-uid-b"


def test_replicaset_identity_never_fabricates_uid() -> None:
    report = _report()
    fact = report["pods"]["jobs-api-abc"]["ownership"]["15"]

    assert "uid" not in fact["replicaset_owner"]
    assert report["provenance"]["replicaset_identity_basis"] == "NAMESPACE_NAME"
    assert report["provenance"]["replicaset_uid_available"] is False


def test_required_timestamp_outside_interval_is_input_error() -> None:
    evidence = _evidence()
    build = _build()

    with pytest.raises(Exception, match="timestamp"):
        build(
            evidence=evidence,
            target_workload=TARGET,
            required_timestamps_by_pod={"jobs-api-abc": ["45"]},
        )


def test_required_timestamp_off_grid_is_input_error() -> None:
    evidence = _evidence()
    build = _build()

    with pytest.raises(Exception, match="grid"):
        build(
            evidence=evidence,
            target_workload=TARGET,
            required_timestamps_by_pod={"jobs-api-abc": ["7"]},
        )


def test_target_namespace_must_match_acquisition_namespace() -> None:
    evidence = _evidence(namespace="app")
    build = _build()
    target = {**TARGET, "namespace": "other"}

    with pytest.raises(Exception, match="namespace"):
        build(
            evidence=evidence,
            target_workload=target,
            required_timestamps_by_pod={"jobs-api-abc": ["15"]},
        )


def test_only_apps_deployment_target_is_supported() -> None:
    evidence = _evidence()
    build = _build()
    target = {**TARGET, "kind": "StatefulSet"}

    with pytest.raises(Exception, match="Deployment"):
        build(
            evidence=evidence,
            target_workload=target,
            required_timestamps_by_pod={"jobs-api-abc": ["15"]},
        )


def test_missing_required_ksm_label_is_adapter_error() -> None:
    collect = _collect()
    series = _pod_owner_series()
    del series["metric"]["uid"]

    with pytest.raises(Exception, match="uid"):
        collect(
            prometheus_url="http://prometheus.test",
            namespace="app",
            start=START,
            end=END,
            step=STEP,
            query_range=_transport(pod_series=[series]),
        )


def test_unexpected_prometheus_result_type_is_adapter_error() -> None:
    collect = _collect()

    with pytest.raises(Exception, match="matrix"):
        collect(
            prometheus_url="http://prometheus.test",
            namespace="app",
            start=START,
            end=END,
            step=STEP,
            query_range=_transport(result_type="vector"),
        )


def test_transport_failure_is_execution_error_not_unknown() -> None:
    collect = _collect()

    with pytest.raises(Exception, match="prometheus unavailable"):
        collect(
            prometheus_url="http://prometheus.test",
            namespace="app",
            start=START,
            end=END,
            step=STEP,
            query_range=_transport(failure=OSError("prometheus unavailable")),
        )


def test_queries_keep_wrong_kind_controller_owners_visible() -> None:
    calls: list[str] = []
    _evidence(query_range=_transport(calls=calls))

    assert len(calls) == 2
    assert all('owner_is_controller="true"' in query for query in calls)
    assert all('owner_kind="' not in query for query in calls)


def test_queries_normalize_scrape_topology_without_collapsing_owner_identity() -> None:
    calls: list[str] = []
    _evidence(
        query_range=_transport(
            calls=calls,
            pod_series=[_pod_owner_series(extra_labels={"instance": "ksm-a", "job": "ksm"})],
            replicaset_series=[
                _replicaset_owner_series(extra_labels={"instance": "ksm-a", "job": "ksm"})
            ],
        )
    )

    pod_query = next(query for query in calls if "kube_pod_owner" in query)
    rs_query = next(query for query in calls if "kube_replicaset_owner" in query)
    assert "max by (namespace, pod, uid, owner_kind, owner_name, owner_is_controller)" in pod_query
    assert (
        "max by (namespace, replicaset, owner_kind, owner_name, owner_is_controller)"
        in rs_query
    )


def test_historical_replay_requires_no_live_kubernetes_lookup() -> None:
    report = _report(query_range=_transport())

    assert report["pods"]["jobs-api-abc"]["ownership"]["15"]["relation"] == "TARGET_MATCH"
    assert report["historical_context"] == {"start": "0", "end": "30", "step": "15"}


def test_report_contains_no_version_risk_recommendation_or_aggregate_policy() -> None:
    report = _report()
    wire = json.dumps(report, sort_keys=True, separators=(",", ":"))

    assert "application_version_relation" not in wire
    assert "risk_level" not in wire
    assert "recommendation" not in wire
    assert "freshness" not in wire
    assert "ownership_score" not in wire
    assert "worst_ownership" not in wire


def test_same_replay_is_byte_for_byte_deterministic() -> None:
    first = _report(required={"jobs-api-abc": ["30", "15", "15", "0"]})
    second = _report(required={"jobs-api-abc": ["30", "15", "15", "0"]})

    first_wire = json.dumps(first, sort_keys=True, separators=(",", ":"))
    second_wire = json.dumps(second, sort_keys=True, separators=(",", ":"))
    assert first_wire == second_wire
    assert first["pods"]["jobs-api-abc"]["required_timestamps"] == ["0", "15", "30"]


def test_no_float_appears_in_normalized_evidence_or_report() -> None:
    evidence = _evidence()
    report = _build()(
        evidence=evidence,
        target_workload=TARGET,
        required_timestamps_by_pod={"jobs-api-abc": ["15"]},
    )

    _assert_no_float(evidence)
    _assert_no_float(report)
    assert Decimal(report["historical_context"]["step"]) == Decimal("15")
