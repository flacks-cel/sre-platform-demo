"""POPULATION-ENUMERATION-001: preregistered RED contract tests.

Scenario numbering follows section 8 of
praeva/ownership/POPULATION-ENUMERATION-001.md.

Enumeration walks Deployment -> ReplicaSet -> Pod over evidence the
ownership adapter already acquires for the whole namespace. It never
sees a selector, so a wrong regex cannot narrow it.

Imports are delayed per test so the missing module produces independent
RED failures rather than a collection error. No production code here.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from praeva.ownership.tests.test_workload_ownership_contract import (
    END,
    START,
    STEP,
    TARGET,
    _pod_owner_series,
    _replicaset_owner_series,
    _transport,
)

NAMESPACE = "app"
GRID = ("0", "15", "30")


def _enumerate() -> Any:
    return importlib.import_module("praeva.ownership.population").enumerate_population


def _evidence(
    *,
    pod_series: list[dict[str, Any]] | None = None,
    replicaset_series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    collect = importlib.import_module(
        "praeva.ownership.prometheus_adapter"
    ).collect_ownership_evidence
    return collect(
        prometheus_url="http://prometheus.test",
        namespace=NAMESPACE,
        start=START,
        end=END,
        step=STEP,
        query_range=_transport(
            pod_series=pod_series,
            replicaset_series=replicaset_series,
        ),
    )


def _run(
    *,
    pod_series: list[dict[str, Any]] | None = None,
    replicaset_series: list[dict[str, Any]] | None = None,
    timestamps: tuple[str, ...] = GRID,
    observed: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "evidence": _evidence(
            pod_series=pod_series,
            replicaset_series=replicaset_series,
        ),
        "target_workload": TARGET,
        "timestamps": list(timestamps),
    }
    if observed is not None:
        kwargs["observed_pods_by_timestamp"] = observed
    return _enumerate()(**kwargs)


def _at(result: dict[str, Any], timestamp: str) -> dict[str, Any]:
    return result["timestamps"][timestamp]


def _owned_names(result: dict[str, Any], timestamp: str) -> list[str]:
    return [entry["pod"] for entry in _at(result, timestamp)["owned_pods"]]


# ---------------------------------------------------------------------------
# 1-4: who belongs to the target, and who does not.
# ---------------------------------------------------------------------------


def test_01_single_replicaset_enumerates_its_pods_in_order() -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-c", uid="uid-c"),
        _pod_owner_series(pod="jobs-api-a", uid="uid-a"),
        _pod_owner_series(pod="jobs-api-b", uid="uid-b"),
    ]

    result = _run(pod_series=pods)

    assert _at(result, "15")["status"] == "ENUMERATED"
    assert _owned_names(result, "15") == ["jobs-api-a", "jobs-api-b", "jobs-api-c"]
    assert _at(result, "15")["replicasets"] == ["jobs-api-rs-a"]


def test_02_rollout_with_two_replicasets_enumerates_the_union() -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-old", uid="uid-old", owner_name="jobs-api-rs-a"),
        _pod_owner_series(pod="jobs-api-new", uid="uid-new", owner_name="jobs-api-rs-b"),
    ]
    replicasets = [
        _replicaset_owner_series(replicaset="jobs-api-rs-a"),
        _replicaset_owner_series(replicaset="jobs-api-rs-b"),
    ]

    result = _run(pod_series=pods, replicaset_series=replicasets)

    assert _owned_names(result, "15") == ["jobs-api-new", "jobs-api-old"]
    assert _at(result, "15")["replicasets"] == ["jobs-api-rs-a", "jobs-api-rs-b"]


def test_03_replicaset_of_another_deployment_is_excluded() -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-a", uid="uid-a", owner_name="jobs-api-rs-a"),
        _pod_owner_series(pod="other-a", uid="uid-o", owner_name="other-rs"),
    ]
    replicasets = [
        _replicaset_owner_series(replicaset="jobs-api-rs-a"),
        _replicaset_owner_series(replicaset="other-rs", owner_name="other-api"),
    ]

    result = _run(pod_series=pods, replicaset_series=replicasets)

    assert _owned_names(result, "15") == ["jobs-api-a"]


@pytest.mark.parametrize("owner_kind", ["Job", "StatefulSet", "DaemonSet"])
def test_04_pods_under_another_controller_kind_are_excluded(owner_kind: str) -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-a", uid="uid-a"),
        _pod_owner_series(pod="batch-1", uid="uid-j", owner_kind=owner_kind, owner_name="batch"),
    ]

    result = _run(pod_series=pods)

    assert _owned_names(result, "15") == ["jobs-api-a"]


# ---------------------------------------------------------------------------
# 5-8: an empty set is a fact; a missing sample is ignorance.
# ---------------------------------------------------------------------------


def test_05_no_replicaset_of_the_target_is_an_enumerated_empty_set() -> None:
    pods = [_pod_owner_series(pod="other-a", uid="uid-o", owner_name="other-rs")]
    replicasets = [_replicaset_owner_series(replicaset="other-rs", owner_name="other-api")]

    result = _run(pod_series=pods, replicaset_series=replicasets)

    assert _at(result, "15")["status"] == "ENUMERATED"
    assert _at(result, "15")["owned_pods"] == []
    assert "reason" not in _at(result, "15")


def test_06_absent_replicaset_series_is_unknown_never_empty() -> None:
    replicasets = [_replicaset_owner_series(values=[("0", "1"), ("30", "1")])]

    result = _run(replicaset_series=replicasets, timestamps=("15",))

    entry = _at(result, "15")
    assert entry["status"] == "UNKNOWN"
    assert entry["reason"] == "replicaset_series_absent_at_timestamp"
    assert entry.get("owned_pods") in (None, [])
    assert entry.get("comparison") is None


def test_07_absent_pod_series_is_unknown_never_empty() -> None:
    pods = [_pod_owner_series(values=[("0", "1"), ("30", "1")])]

    result = _run(pod_series=pods, timestamps=("15",))

    entry = _at(result, "15")
    assert entry["status"] == "UNKNOWN"
    assert entry["reason"] == "pod_series_absent_at_timestamp"


def test_08_timestamp_outside_acquisition_is_unknown() -> None:
    result = _run(timestamps=("45",))

    entry = _at(result, "45")
    assert entry["status"] == "UNKNOWN"
    assert entry["reason"] == "timestamp_outside_acquisition"


# ---------------------------------------------------------------------------
# 9-11: ambiguity is never resolved by picking one.
# ---------------------------------------------------------------------------


def test_09_same_pod_name_with_two_uids_is_ambiguous() -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-a", uid="uid-1"),
        _pod_owner_series(pod="jobs-api-a", uid="uid-2"),
    ]

    result = _run(pod_series=pods, timestamps=("15",))

    assert _at(result, "15")["reason"] == "pod_identity_ambiguous_at_timestamp"


def test_10_pod_with_two_controller_owners_is_ambiguous() -> None:
    pods = [
        _pod_owner_series(pod="jobs-api-a", uid="uid-a", owner_name="jobs-api-rs-a"),
        _pod_owner_series(pod="jobs-api-a", uid="uid-a", owner_name="jobs-api-rs-b"),
    ]
    replicasets = [
        _replicaset_owner_series(replicaset="jobs-api-rs-a"),
        _replicaset_owner_series(replicaset="jobs-api-rs-b"),
    ]

    result = _run(pod_series=pods, replicaset_series=replicasets, timestamps=("15",))

    assert _at(result, "15")["reason"] == "pod_controller_owner_ambiguous"


def test_11_replicaset_with_two_controller_owners_is_ambiguous() -> None:
    replicasets = [
        _replicaset_owner_series(replicaset="jobs-api-rs-a", owner_name="jobs-api"),
        _replicaset_owner_series(replicaset="jobs-api-rs-a", owner_name="jobs-api-v2"),
    ]

    result = _run(replicaset_series=replicasets, timestamps=("15",))

    assert _at(result, "15")["reason"] == "replicaset_controller_owner_ambiguous"


# ---------------------------------------------------------------------------
# 12-16: comparison against what Verify observed.
# ---------------------------------------------------------------------------


def _three_pods() -> list[dict[str, Any]]:
    return [
        _pod_owner_series(pod="jobs-api-a", uid="uid-a"),
        _pod_owner_series(pod="jobs-api-b", uid="uid-b"),
        _pod_owner_series(pod="jobs-api-c", uid="uid-c"),
    ]


def test_12_identical_sets_are_complete() -> None:
    observed = {"15": ["jobs-api-a", "jobs-api-b", "jobs-api-c"]}

    comparison = _at(
        _run(pod_series=_three_pods(), timestamps=("15",), observed=observed),
        "15",
    )["comparison"]

    assert comparison["verdict"] == "COMPLETE"
    assert comparison["missing"] == []
    assert comparison["foreign"] == []


def test_13_observed_subset_is_omission_and_names_the_missing() -> None:
    observed = {"15": ["jobs-api-a", "jobs-api-b"]}

    comparison = _at(
        _run(pod_series=_three_pods(), timestamps=("15",), observed=observed),
        "15",
    )["comparison"]

    assert comparison["verdict"] == "OMISSION"
    assert comparison["missing"] == ["jobs-api-c"]
    assert comparison["foreign"] == []


def test_14_observed_superset_is_foreign_and_names_the_strangers() -> None:
    observed = {"15": ["jobs-api-a", "jobs-api-b", "jobs-api-c", "intruder"]}

    comparison = _at(
        _run(pod_series=_three_pods(), timestamps=("15",), observed=observed),
        "15",
    )["comparison"]

    assert comparison["verdict"] == "FOREIGN"
    assert comparison["foreign"] == ["intruder"]
    assert comparison["missing"] == []


def test_15_both_directions_are_reported_separately() -> None:
    observed = {"15": ["jobs-api-a", "intruder"]}

    comparison = _at(
        _run(pod_series=_three_pods(), timestamps=("15",), observed=observed),
        "15",
    )["comparison"]

    assert comparison["verdict"] == "OMISSION_AND_FOREIGN"
    assert comparison["missing"] == ["jobs-api-b", "jobs-api-c"]
    assert comparison["foreign"] == ["intruder"]


def test_16_unknown_enumeration_is_never_compared() -> None:
    pods = [_pod_owner_series(values=[("0", "1"), ("30", "1")])]
    observed = {"15": ["jobs-api-abc"]}

    entry = _at(
        _run(pod_series=pods, timestamps=("15",), observed=observed),
        "15",
    )

    assert entry["status"] == "UNKNOWN"
    assert entry.get("comparison") is None


# ---------------------------------------------------------------------------
# 17: determinism.
# ---------------------------------------------------------------------------


def test_17_same_input_produces_the_same_output() -> None:
    observed = {"15": ["jobs-api-a"]}
    first = _run(pod_series=_three_pods(), timestamps=("15",), observed=observed)
    second = _run(pod_series=_three_pods(), timestamps=("15",), observed=observed)

    assert first == second


# ---------------------------------------------------------------------------
# 18: the selector is never an input.
# ---------------------------------------------------------------------------


def test_18_enumeration_takes_no_selector() -> None:
    import inspect  # noqa: PLC0415

    signature = inspect.signature(_enumerate())
    forbidden = {"pod_regex", "selector", "pod_selector", "identity_assertion"}

    assert forbidden.isdisjoint(signature.parameters)
