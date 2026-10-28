from __future__ import annotations

import pytest

from praeva.attribution.projection import (
    AttributionDecisionInputError,
    project_attribution_decision,
)


def _ownership_fact(*, relation: str = "TARGET_MATCH") -> dict:
    return {
        "evidence_status": "VALID",
        "relation": relation,
        "pod_identity": {
            "namespace": "app",
            "name": "pod-a",
            "uid": "uid-a",
        },
        "evidence_refs": ["pod_owner", "replicaset_owner"],
    }


def _unknown_ownership() -> dict:
    return {
        "evidence_status": "UNKNOWN",
        "reason_code": "pod_owner_missing_at_timestamp",
        "reason": "ownership unavailable",
        "evidence_refs": [],
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


def _support(
    *,
    start: str = "0",
    end: str = "30",
    required: list[str] | None = None,
) -> dict:
    return {
        "start": start,
        "end": end,
        "required_timestamps": ["0", "15", "30"] if required is None else required,
        "boundary_proven": True,
    }


def _fact(*, observed_sample: dict | None = None, nominal: dict | None = None) -> dict:
    return {
        "fact_id": "cpu_long:pod-a:30",
        "pod": "pod-a",
        "evidence_family": "cpu_long",
        "evaluated_at": "30",
        "support": {
            "nominal": nominal or _support(),
            "observed_sample": observed_sample,
        },
        "creation_by_uid": {"uid-a": "-100"},
    }


def _population() -> dict:
    return {
        "cpu_long": {"status": "COMPLETE", "diagnostics": []},
    }


def _requirements() -> dict:
    return {
        "EXISTENTIAL": [{"quantifier": "EXISTS", "domain": "cpu_long"}],
        "UNIVERSAL": [{"quantifier": "FORALL", "domain": "cpu_long"}],
    }


def _project(*, report: dict, fact: dict) -> dict:
    return project_attribution_decision(
        target_domain_status="DETERMINED",
        ownership_report=report,
        facts=[fact],
        population_evidence=_population(),
        level_requirements=_requirements(),
    )


def test_unattributed_target_fact_makes_effective_domain_incomplete():
    result = _project(
        report=_report(
            {
                "0": _ownership_fact(),
                "15": _ownership_fact(),
                "30": _unknown_ownership(),
            }
        ),
        fact=_fact(),
    )

    assert result["facts"]["cpu_long:pod-a:30"]["class"] == "attribution_unproven"
    assert result["population_evidence"]["cpu_long"]["status"] == "COMPLETE"
    assert result["effective_population_evidence"]["cpu_long"]["status"] == "INCOMPLETE"
    assert result["level_eligibility"]["EXISTENTIAL"]["status"] == "ELIGIBLE"
    assert result["level_eligibility"]["UNIVERSAL"] == {
        "status": "BLOCKED",
        "blocked_by": ["population_incomplete:cpu_long"],
    }


def test_foreign_fact_does_not_make_target_domain_incomplete():
    result = _project(
        report=_report(
            {
                "0": _ownership_fact(relation="TARGET_DIFFERS"),
                "15": _ownership_fact(relation="TARGET_DIFFERS"),
                "30": _ownership_fact(relation="TARGET_DIFFERS"),
            }
        ),
        fact=_fact(),
    )

    assert result["facts"]["cpu_long:pod-a:30"]["class"] == "foreign_workload"
    assert result["effective_population_evidence"]["cpu_long"] == {
        "status": "COMPLETE",
        "diagnostics": [],
    }
    assert result["level_eligibility"]["UNIVERSAL"]["status"] == "ELIGIBLE"


def test_observed_sample_support_must_be_subset_of_nominal_support():
    observed = _support(start="-15", end="15", required=["0", "15"])

    with pytest.raises(AttributionDecisionInputError):
        _project(
            report=_report({"0": _ownership_fact(), "15": _ownership_fact()}),
            fact=_fact(observed_sample=observed),
        )


def test_support_requires_at_least_one_required_timestamp():
    nominal = _support(required=[])

    with pytest.raises(AttributionDecisionInputError):
        _project(
            report=_report({}),
            fact=_fact(nominal=nominal),
        )
