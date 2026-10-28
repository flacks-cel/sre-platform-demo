from __future__ import annotations

import pytest

from praeva.attribution.projection import (
    AttributionDecisionInputError,
    project_attribution_decision,
)


def _ownership_fact(*, uid: str = "uid-a") -> dict:
    return {
        "evidence_status": "VALID",
        "relation": "TARGET_MATCH",
        "pod_identity": {
            "namespace": "app",
            "name": "pod-a",
            "uid": uid,
        },
        "evidence_refs": ["pod_owner", "replicaset_owner"],
    }


def _report(points: dict[str, dict]) -> dict:
    return {
        "ownership_id": "WORKLOAD-OWNERSHIP-001",
        "target_workload": {
            "api_group": "apps",
            "kind": "Deployment",
            "namespace": "app",
            "name": "jobs-api",
        },
        "pods": {
            "pod-a": {
                "required_timestamps": sorted(points, key=int),
                "ownership": points,
            }
        },
    }


def _fact(*, creation_by_uid: dict | None = None, legacy_creation: object = None) -> dict:
    fact = {
        "fact_id": "cpu_long:pod-a:30",
        "pod": "pod-a",
        "evidence_family": "cpu_long",
        "evaluated_at": "30",
        "support": {
            "nominal": {
                "start": "0",
                "end": "30",
                "required_timestamps": ["0", "15", "30"],
                "boundary_proven": True,
            },
            "observed_sample": None,
        },
        "creation_by_uid": {} if creation_by_uid is None else creation_by_uid,
    }
    if legacy_creation is not None:
        fact["creation_timestamp"] = legacy_creation
    return fact


def _project(*, report: dict, fact: dict) -> dict:
    return project_attribution_decision(
        target_domain_status="DETERMINED",
        ownership_report=report,
        facts=[fact],
        population_evidence={
            "cpu_long": {"status": "COMPLETE", "diagnostics": []},
        },
        level_requirements={
            "EXISTENTIAL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
            "UNIVERSAL": [{"quantifier": "FORALL", "domain": "cpu_long"}],
        },
    )


def _stable_report() -> dict:
    return _report(
        {
            "0": _ownership_fact(),
            "15": _ownership_fact(),
            "30": _ownership_fact(),
        }
    )


def test_unique_uid_with_creation_before_support_is_attributed():
    result = _project(
        report=_stable_report(),
        fact=_fact(creation_by_uid={"uid-a": "-100"}),
    )

    assert result["facts"]["cpu_long:pod-a:30"]["status"] == "ATTRIBUTED"


def test_unique_uid_with_missing_creation_is_semantically_unattributed():
    result = _project(report=_stable_report(), fact=_fact(creation_by_uid={}))

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "attribution_unproven"
    assert result["effective_population_evidence"]["cpu_long"]["status"] == "INCOMPLETE"


def test_unique_uid_created_after_support_start_is_support_predates_pod():
    result = _project(
        report=_stable_report(),
        fact=_fact(creation_by_uid={"uid-a": "10"}),
    )

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "support_predates_pod"


def test_uid_change_does_not_require_creation_evidence_to_classify_discontinuity():
    report = _report(
        {
            "0": _ownership_fact(uid="uid-a"),
            "15": _ownership_fact(uid="uid-a"),
            "30": _ownership_fact(uid="uid-b"),
        }
    )

    result = _project(report=report, fact=_fact(creation_by_uid={}))

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "identity_discontinuity"


def test_uid_change_is_same_with_creation_for_both_uids():
    report = _report(
        {
            "0": _ownership_fact(uid="uid-a"),
            "15": _ownership_fact(uid="uid-a"),
            "30": _ownership_fact(uid="uid-b"),
        }
    )

    result = _project(
        report=report,
        fact=_fact(creation_by_uid={"uid-a": "-100", "uid-b": "20"}),
    )

    fact = result["facts"]["cpu_long:pod-a:30"]
    assert fact["status"] == "UNATTRIBUTED"
    assert fact["class"] == "identity_discontinuity"


def test_float_creation_value_is_structural_input_error():
    with pytest.raises(AttributionDecisionInputError):
        _project(
            report=_stable_report(),
            fact=_fact(creation_by_uid={"uid-a": 1.5}),
        )


def test_empty_uid_key_is_structural_input_error():
    with pytest.raises(AttributionDecisionInputError):
        _project(
            report=_stable_report(),
            fact=_fact(creation_by_uid={"": "-100"}),
        )


def test_legacy_scalar_creation_timestamp_is_not_normative_input():
    fact = _fact(creation_by_uid={"uid-a": "-100"}, legacy_creation="-100")
    fact.pop("creation_by_uid")

    with pytest.raises(AttributionDecisionInputError):
        _project(report=_stable_report(), fact=fact)
